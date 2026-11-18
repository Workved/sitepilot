import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import ProjectRoleChange, V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion
from app.schemas.projects import ProjectActivateIn, ProjectCreateIn, ProjectDeleteIn, ProjectMembershipEndIn, ProjectMembershipIn, ProjectRestoreIn, ProjectRoleChangeRejectIn, ProjectRoleChangeRequestIn, ProjectStatusIn, ProjectUpdateIn
from app.schemas.project_template_review import ProjectTemplateReviewSummaryOut, ProjectTemplateReviewTaskPage
from app.schemas.project_task_applicability import ProjectTaskApplicabilityDecisionIn, ProjectTaskApplicabilityDecisionOut, ProjectTaskApplicabilityHistoryItem
from app.schemas.project_manual_task import ProjectManualTaskCreateIn, ProjectManualTaskCreateOut, RunningProjectTaskAddIn
from app.services.project_manual_task import ProjectManualTaskService
from app.services.project_task_applicability import ProjectTaskApplicabilityService
from app.services.project_template_review import ProjectTemplateReviewService
from app.schemas.project_task_classification import ProjectTaskClassificationListOut, ProjectTaskClassificationUpdateIn
from app.services.project_task_classification import ProjectTaskClassificationService
from app.services.project_gate_generation import ProjectGateGenerationService
from app.schemas.project_gates import ProjectGateGenerateOut, ProjectGateListOut
from app.schemas.project_gate_applicability import ProjectGateApplicabilityDecisionIn, ProjectGateApplicabilityDecisionOut, ProjectGateApplicabilityHistoryItem
from app.services.project_gate_applicability import ProjectGateApplicabilityService
from app.schemas.project_manual_gate import ProjectManualGateCreateIn, ProjectManualGateCreateOut
from app.services.project_manual_gate import ProjectManualGateService
from app.schemas.project_dependencies import ProjectDependencyGenerateOut, ProjectDependencyListOut
from app.services.project_dependency_generation import ProjectDependencyGenerationService
from app.services.project_baseline import ProjectBaselineService
from app.services.project_role_change import ProjectRoleChangeService
from app.services.access_control import ORG_ADMIN_ROLES, is_org_admin
from app.services.outbox import OutboxService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-projects"])

PROJECT_STATUSES = {"draft", "active", "on_hold", "completed", "archived"}
ACCOUNTABLE_ROLES = {"project_manager", "site_supervisor"}
ROLE_TO_USER_ROLE = {
    "project_manager": UserRole.project_manager,
    "site_supervisor": UserRole.supervisor,
    "internal_employee": UserRole.internal_employee,
}


def clean_required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(422, f"{label} is required.")
    return cleaned


def clean_optional(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def today_ist() -> date:
    """Today's calendar date in India, where every site runs - so a project
    created late evening UTC still counts as that Indian day. One place, so
    tests can pin "today"."""
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def derive_target_handover_date(start_date: date, template_version: V2TemplateVersion) -> date:
    """Day 1 of the schedule is the start date itself, so a 45-day template
    starting on 11 Aug hands over on 24 Sep - start + 44, not start + 45.

    This is the only place a handover date is produced. It cannot drift:
    `update_project` refuses to move `start_date` once a template is
    attached, and refuses to replace the template version at all, so the
    two inputs are frozen from creation onward.
    """
    return start_date + timedelta(days=template_version.duration_days - 1)


def project_snapshot(project: V2Project) -> dict:
    return {
        "code": project.code,
        "name": project.name,
        "client_name": project.client_name,
        "site_address": project.site_address,
        "description": project.description,
        "start_date": project.start_date.isoformat(),
        "target_handover_date": project.target_handover_date.isoformat() if project.target_handover_date else None,
        "template_version_id": str(project.template_version_id) if project.template_version_id else None,
        "status": project.status,
    }


def add_audit(db: Session, actor: User, project: V2Project, action: str, reason: str, before: dict | None = None, after: dict | None = None, entity_type: str = "project", entity_id: uuid.UUID | None = None) -> None:
    db.add(V2AuditEvent(
        actor_user_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id or project.id,
        project_id=project.id,
        before_json=before,
        after_json=after,
        reason=reason,
    ))


def actor_employee(db: Session, actor: User) -> EmployeeProfile | None:
    return db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))


def active_memberships(db: Session, project_id: uuid.UUID, role: str | None = None) -> list[V2ProjectMembership]:
    statement = select(V2ProjectMembership).where(V2ProjectMembership.project_id == project_id, V2ProjectMembership.ends_at.is_(None))
    if role:
        statement = statement.where(V2ProjectMembership.project_role == role)
    return list(db.scalars(statement.order_by(V2ProjectMembership.starts_at)).all())


def has_membership(db: Session, project_id: uuid.UUID, actor: User, roles: set[str] | None = None) -> bool:
    employee = actor_employee(db, actor)
    if not employee:
        return False
    statement = select(V2ProjectMembership.id).where(
        V2ProjectMembership.project_id == project_id,
        V2ProjectMembership.employee_id == employee.id,
        V2ProjectMembership.ends_at.is_(None),
    )
    if roles:
        statement = statement.where(V2ProjectMembership.project_role.in_(roles))
    return db.scalar(statement) is not None


def can_view(db: Session, project: V2Project, actor: User) -> bool:
    return is_org_admin(actor) or has_membership(db, project.id, actor)


def can_edit(db: Session, project: V2Project, actor: User) -> bool:
    return is_org_admin(actor) or (actor.role == UserRole.project_manager and has_membership(db, project.id, actor, {"project_manager"}))


def get_project(db: Session, project_id: uuid.UUID, actor: User) -> V2Project:
    project = db.get(V2Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    if not can_view(db, project, actor):
        raise HTTPException(403, "You do not have access to this project.")
    return project


def membership_json(db: Session, item: V2ProjectMembership) -> dict:
    employee = db.get(EmployeeProfile, item.employee_id)
    user = db.get(User, employee.user_id) if employee else None
    return {
        "id": str(item.id),
        "employee_id": str(item.employee_id),
        "user_id": str(user.id) if user else None,
        "name": user.name if user else "Unknown employee",
        "email": user.email if user else None,
        "employee_code": employee.employee_code if employee else None,
        "designation": employee.designation if employee else None,
        "project_role": item.project_role,
        "starts_at": item.starts_at.isoformat(),
        "ends_at": item.ends_at.isoformat() if item.ends_at else None,
        "assignment_reason": item.assignment_reason,
        "acknowledged_at": item.acknowledged_at.isoformat() if item.acknowledged_at else None,
    }


def role_change_json(db: Session, change: ProjectRoleChange) -> dict:
    employee = db.get(EmployeeProfile, change.replacement_employee_id) if change.replacement_employee_id else None
    user = db.get(User, employee.user_id) if employee else None
    if user:
        replacement_name = user.name
    elif change.change_type == "vacate":
        replacement_name = None
    else:
        replacement_name = "Unknown employee"
    return {
        "id": str(change.id),
        "project_id": str(change.project_id),
        "role_type": change.role_type,
        "previous_membership_id": str(change.previous_membership_id) if change.previous_membership_id else None,
        "replacement_employee_id": str(change.replacement_employee_id) if change.replacement_employee_id else None,
        "replacement_name": replacement_name,
        "change_type": change.change_type,
        "reason_code": change.reason_code,
        "reason_detail": change.reason_detail,
        "status": change.status,
        "requested_by": str(change.requested_by),
        "requested_at": change.requested_at.isoformat(),
        "decided_by": str(change.decided_by) if change.decided_by else None,
        "decided_at": change.decided_at.isoformat() if change.decided_at else None,
    }


def project_json(db: Session, project: V2Project, include_history: bool = False) -> dict:
    memberships = db.scalars(select(V2ProjectMembership).where(V2ProjectMembership.project_id == project.id).order_by(V2ProjectMembership.ends_at.is_(None).desc(), V2ProjectMembership.starts_at.desc())).all()
    active = [membership_json(db, item) for item in memberships if item.ends_at is None]
    roles = {item["project_role"] for item in active}
    result = {
        "id": str(project.id),
        **project_snapshot(project),
        "activated_at": project.activated_at.isoformat() if project.activated_at else None,
        "completed_at": project.completed_at.isoformat() if project.completed_at else None,
        "created_by": str(project.created_by),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "memberships": active,
        "setup": {
            "has_project_manager": "project_manager" in roles,
            "has_site_supervisor": "site_supervisor" in roles,
            "has_template": project.template_version_id is not None,
            "has_target_handover_date": project.target_handover_date is not None,
            "activation_ready": ACCOUNTABLE_ROLES.issubset(roles) and project.template_version_id is not None and project.target_handover_date is not None,
        },
    }
    if include_history:
        result["membership_history"] = [membership_json(db, item) for item in memberships]
    return result


def role_reference(db: Session, role: UserRole) -> list[dict]:
    rows = db.execute(select(EmployeeProfile, User).join(User, User.id == EmployeeProfile.user_id).where(User.active.is_(True), User.role == role).order_by(User.name)).all()
    return [{
        "employee_id": str(profile.id), "user_id": str(user.id), "name": user.name, "email": user.email,
        "employee_code": profile.employee_code, "designation": profile.designation, "availability": profile.availability,
    } for profile, user in rows]


@router.get("/reference-data")
def reference_data(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    can_assign_pm = is_org_admin(actor)
    can_assign_supervisor = actor.role in {UserRole.super_admin, UserRole.admin, UserRole.project_manager}
    can_assign_support = actor.role in {UserRole.super_admin, UserRole.admin, UserRole.project_manager, UserRole.supervisor}
    return {
        "project_managers": role_reference(db, UserRole.project_manager) if can_assign_pm else [],
        "supervisors": role_reference(db, UserRole.supervisor) if can_assign_supervisor else [],
        "internal_employees": role_reference(db, UserRole.internal_employee) if can_assign_support else [],
        "statuses": sorted(PROJECT_STATUSES),
    }


@router.get("/published-template-versions")
def published_template_versions(
    actor: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Return the stable project-form reference list of eligible templates."""
    rows = db.execute(
        select(V2Template, V2TemplateVersion)
        .join(V2TemplateVersion, V2TemplateVersion.template_id == V2Template.id)
        .where(V2TemplateVersion.status == "published")
        .order_by(
            V2TemplateVersion.is_current_published.desc(),
            V2Template.name.asc(),
            V2TemplateVersion.version_no.desc(),
        )
    ).all()
    return [
        {
            "template_id": str(template.id),
            "template_code": template.code,
            "template_name": template.name,
            "version_id": str(version.id),
            "version_no": version.version_no,
            "duration_days": version.duration_days,
            "status": version.status,
            "is_current_published": version.is_current_published,
        }
        for template, version in rows
    ]


@router.get("")
def list_projects(status_filter: str | None = Query(None, alias="status"), search: str | None = None, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    statement = select(V2Project).order_by(V2Project.updated_at.desc())
    if not is_org_admin(actor):
        employee = actor_employee(db, actor)
        if not employee:
            return []
        visible_ids = select(V2ProjectMembership.project_id).where(V2ProjectMembership.employee_id == employee.id, V2ProjectMembership.ends_at.is_(None))
        statement = statement.where(V2Project.id.in_(visible_ids))
    if status_filter:
        if status_filter not in PROJECT_STATUSES:
            raise HTTPException(422, "Unknown project status.")
        statement = statement.where(V2Project.status == status_filter)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(or_(V2Project.code.ilike(term), V2Project.name.ilike(term), V2Project.client_name.ilike(term), V2Project.site_address.ilike(term)))
    return [project_json(db, project) for project in db.scalars(statement).all()]


def assign_membership(db: Session, project: V2Project, employee_id: uuid.UUID, project_role: str, reason: str, actor: User) -> V2ProjectMembership:
    expected_role = ROLE_TO_USER_ROLE.get(project_role)
    if not expected_role:
        raise HTTPException(422, "Unknown project role.")
    employee = db.get(EmployeeProfile, employee_id)
    user = db.get(User, employee.user_id) if employee else None
    if not employee or not user or not user.active or user.role != expected_role:
        raise HTTPException(422, f"Select an active {project_role.replace('_', ' ')} employee.")
    if employee.availability == "unavailable":
        raise HTTPException(409, f"{user.name} is currently unavailable and cannot receive a new project assignment.")
    current = active_memberships(db, project.id, project_role)
    if any(item.employee_id == employee_id for item in current):
        return next(item for item in current if item.employee_id == employee_id)
    now = datetime.now(timezone.utc)
    before = [membership_json(db, item) for item in current]
    if project_role in ACCOUNTABLE_ROLES:
        for item in current:
            item.ends_at = now
    membership = V2ProjectMembership(project_id=project.id, employee_id=employee_id, project_role=project_role, assigned_by=actor.id, assignment_reason=clean_required(reason, "Assignment reason"))
    db.add(membership)
    db.flush()
    add_audit(db, actor, project, "PROJECT_ROLE_REASSIGNED" if current else "PROJECT_ROLE_ASSIGNED", reason.strip(), {"memberships": before}, {"membership": membership_json(db, membership)}, "project_membership", membership.id)
    # U3 (WhatsApp gate workflow): emit in the same transaction as the
    # membership row itself, so the caller's IntegrityError -> 409 rollback
    # (see assign_membership's callers) also rolls back this event, same
    # discipline as U2's project.activated emit above. Keyed on the
    # membership's own id - unlike activation this can happen many times per
    # project, so the id (not just project/event type) is what makes repeat
    # calls distinct.
    #
    # Gated to Active projects only: a Draft project is planning/setup, and
    # `_ALL_MEMBERS_PROJECT_EVENTS` fans this out to the ENTIRE current team,
    # not just the person just assigned - notifying an execution team about
    # roster changes while the project hasn't started yet is exactly the
    # Draft-phase operational noise the product rules forbid. Team setup
    # before activation stays silent; `project.activated` (U2 above) is what
    # tells everyone the project - and their assignment - is now live.
    if project.status == "active":
        OutboxService(db).emit(
            event_type="project.member_added",
            aggregate_type="project",
            aggregate_id=project.id,
            payload={"project_id": str(project.id), "employee_id": str(employee_id), "project_role": project_role},
            idempotency_key=f"project:{project.id}:project.member_added:{membership.id}",
        )
    return membership


@router.post("", status_code=201)
def create_project(payload: ProjectCreateIn, actor: User = Depends(require_roles(*ORG_ADMIN_ROLES)), db: Session = Depends(get_db)):
    """Create only the draft project shell and accountable memberships.

    Template task generation is deliberately deferred to the next Phase 3
    capability. All eligibility checks occur before the first write.
    """
    name = clean_required(payload.name, "Project name")
    client_name = clean_required(payload.client_name, "Client")
    site_address = clean_required(payload.site_address, "Location")
    # A new project starts today or later, never in the past. (Editing an
    # existing project is not affected - its start may already be behind us.)
    if payload.start_date < today_ist():
        raise HTTPException(422, "The proposed start date cannot be before today.")

    template_version = db.get(V2TemplateVersion, payload.template_version_id)
    if not template_version or template_version.status != "published":
        raise HTTPException(422, "Select a published template version.")

    # Always derived from the template's own duration, never taken from the
    # client. `payload.target_handover_date` is retained on the schema only
    # so older callers do not break on extra="forbid"; a supplied value is
    # deliberately ignored rather than silently trusted, because a handover
    # that disagrees with the schedule it is measured against is worse than
    # no handover at all.
    target_handover_date = derive_target_handover_date(payload.start_date, template_version)

    def resolve_accountable_user(user_or_employee_id: uuid.UUID, expected_role: UserRole, label: str) -> tuple[User, EmployeeProfile]:
        # The accepted Phase 3 contract uses user IDs. Retain compatibility with
        # existing Phase 2 selectors that may still submit employee-profile IDs.
        user = db.get(User, user_or_employee_id)
        profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_or_employee_id)) if user else None
        if not user:
            profile = db.get(EmployeeProfile, user_or_employee_id)
            user = db.get(User, profile.user_id) if profile else None
        if not user or not user.active or user.role != expected_role or not profile:
            raise HTTPException(422, f"Select an active {label} with the correct role.")
        if profile.availability == "unavailable":
            raise HTTPException(409, f"{user.name} is currently unavailable and cannot receive a new project assignment.")
        return user, profile

    _pm_user, pm_profile = resolve_accountable_user(
        payload.project_manager_user_id, UserRole.project_manager, "Project Manager"
    )
    _supervisor_user, supervisor_profile = resolve_accountable_user(
        payload.supervisor_user_id, UserRole.supervisor, "Supervisor"
    )

    code = clean_optional(payload.code)
    if code:
        code = code.upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,29}", code):
            raise HTTPException(422, "Use 3-30 uppercase letters, numbers or hyphens for the project code.")
    else:
        code = f"PRJ-{payload.start_date:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"

    assignment_reason = clean_optional(payload.assignment_reason) or "Initial draft project assignment."
    project = V2Project(
        code=code,
        name=name,
        client_name=client_name,
        site_address=site_address,
        description=clean_optional(payload.description),
        start_date=payload.start_date,
        target_handover_date=target_handover_date,
        template_version_id=template_version.id,
        status="draft",
        created_by=actor.id,
    )

    try:
        db.add(project)
        db.flush()
        db.add_all([
            V2ProjectMembership(
                project_id=project.id,
                employee_id=pm_profile.id,
                project_role="project_manager",
                assigned_by=actor.id,
                assignment_reason=assignment_reason,
            ),
            V2ProjectMembership(
                project_id=project.id,
                employee_id=supervisor_profile.id,
                project_role="site_supervisor",
                assigned_by=actor.id,
                assignment_reason=assignment_reason,
            ),
        ])
        db.flush()
        # Tasks, dependencies and gates are a deterministic copy of the
        # selected template - there is no decision between creating the
        # project and generating them, so they run here rather than as three
        # manual steps. All four writes share one transaction: a project can
        # never exist with a half-built snapshot. Order matters - dependencies
        # and gates both remap onto the generated task rows, and gates need
        # the PM membership flushed above to set accountable_pm_user_id.
        task_result = generate_task_snapshot(db, project, actor, commit=False)
        dependency_result = ProjectDependencyGenerationService(db).generate(project, actor, commit=False)
        gate_result = ProjectGateGenerationService(db).generate(project.id, actor, commit=False)
        add_audit(
            db,
            actor,
            project,
            "PROJECT_CREATED",
            "Draft project created from published template reference; task snapshot generated automatically.",
            after={
                **project_snapshot(project),
                "project_manager_user_id": str(_pm_user.id),
                "supervisor_user_id": str(_supervisor_user.id),
                "generated_task_count": task_result["generated_task_count"],
                "generated_dependency_count": dependency_result["generated_dependency_count"],
                "generated_gate_count": gate_result["generated_gate_count"],
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Project code or initial team assignment conflicts with an existing record.") from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(project)
    return project_json(db, project, True)


def generate_task_snapshot(db: Session, project: V2Project, actor: User, *, commit: bool = True) -> dict:
    """Copy the selected published template's tasks into this project.

    Pure copy, no decisions: the template version and start date are fixed at
    creation and cannot change afterwards, so this produces the same rows
    however often it runs. Re-running is a no-op.

    `commit=False` lets `create_project` fold generation into the same
    transaction that creates the project, so a project can never exist with a
    half-built snapshot. The standalone route keeps `commit=True`.
    """
    if project.status != "draft":
        raise HTTPException(409, "Tasks can only be generated while the project is draft.")
    if not project.template_version_id:
        raise HTTPException(422, "Select a published template version before generating tasks.")

    template_version = db.get(V2TemplateVersion, project.template_version_id)
    if not template_version or template_version.status != "published":
        raise HTTPException(409, "The selected template version is no longer published.")

    template_tasks = list(db.scalars(
        select(V2TemplateTask)
        .where(V2TemplateTask.template_version_id == template_version.id)
        .order_by(V2TemplateTask.sequence_no.asc(), V2TemplateTask.code.asc(), V2TemplateTask.id.asc())
    ).all())
    if not template_tasks:
        raise HTTPException(422, "The selected published template contains no tasks.")

    existing = list(db.scalars(
        select(V2ProjectTask)
        .where(V2ProjectTask.project_id == project.id)
        .order_by(V2ProjectTask.template_sequence.asc(), V2ProjectTask.original_code.asc())
    ).all())
    if existing:
        expected_ids = [task.id for task in template_tasks]
        existing_ids = [task.template_task_id for task in existing]
        if existing_ids != expected_ids:
            raise HTTPException(409, "Project task generation is incomplete or does not match the selected template.")
        return {
            "project_id": str(project.id),
            "status": project.status,
            "template_version_id": str(template_version.id),
            "generated_task_count": len(existing),
            "created_task_count": 0,
            "no_op": True,
        }

    generated = [
        V2ProjectTask(
            project_id=project.id,
            template_version_id=template_version.id,
            template_task_id=task.id,
            original_code=task.code,
            template_sequence=task.sequence_no,
            title=task.title,
            description=task.description,
            schedule_classification=task.schedule_classification,
            planned_start_day=task.planned_start_day,
            planned_end_day=task.planned_end_day,
            phase=task.phase,
            category=task.category,
            applicability=task.applicability,
            task_class=task.task_class,
            task_kind=task.task_kind,
            evidence_required=task.evidence_required,
            duration_days=task.duration_days,
            source_type="template",
            lifecycle_status="draft",
            included=True,
            decision_state="pending_review",
        )
        for task in template_tasks
    ]

    try:
        db.add_all(generated)
        db.flush()
        add_audit(
            db,
            actor,
            project,
            "PROJECT_TASKS_GENERATED",
            "Generated draft project tasks from the selected published template.",
            before={"generated_task_count": 0},
            after={
                "template_version_id": str(template_version.id),
                "generated_task_count": len(generated),
                "first_task_code": generated[0].original_code,
                "last_task_code": generated[-1].original_code,
            },
        )
        if commit:
            db.commit()
    except Exception:
        if commit:
            db.rollback()
        raise

    return {
        "project_id": str(project.id),
        "status": project.status,
        "template_version_id": str(template_version.id),
        "generated_task_count": len(generated),
        "created_task_count": len(generated),
        "no_op": False,
    }


@router.post("/{project_id}/generate-tasks")
def generate_project_tasks(
    project_id: uuid.UUID,
    actor: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Manual fallback. Creation now generates the snapshot automatically, so
    this only matters for drafts that predate that, or if generation was
    somehow skipped."""
    project = db.get(V2Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    return generate_task_snapshot(db, project, actor)



@router.post("/{project_id}/gates", response_model=ProjectManualGateCreateOut, status_code=201)
def create_project_manual_gate(
    project_id: uuid.UUID,
    payload: ProjectManualGateCreateIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectManualGateService(db).create(project_id, actor, payload)




@router.post("/{project_id}/generate-dependencies", response_model=ProjectDependencyGenerateOut)
def generate_project_dependencies(project_id: uuid.UUID, actor: User = Depends(require_roles(*ORG_ADMIN_ROLES)), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    return ProjectDependencyGenerationService(db).generate(project, actor)


@router.get("/{project_id}/dependencies", response_model=ProjectDependencyListOut)
def list_project_dependencies(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    return ProjectDependencyGenerationService(db).list(project)

@router.post("/{project_id}/generate-gates", response_model=ProjectGateGenerateOut)
def generate_project_gates(
    project_id: uuid.UUID,
    actor: User = Depends(require_roles(*ORG_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    return ProjectGateGenerationService(db).generate(project_id, actor)


@router.get("/{project_id}/external-gates", response_model=ProjectGateListOut)
def list_project_gates(
    project_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectGateGenerationService(db).list(project_id, actor)


@router.post(
    "/{project_id}/gates/{gate_id}/applicability-decisions",
    response_model=ProjectGateApplicabilityDecisionOut,
)
def decide_project_gate_applicability(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    payload: ProjectGateApplicabilityDecisionIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectGateApplicabilityService(db).decide(project_id, gate_id, actor, payload)


@router.get(
    "/{project_id}/gates/{gate_id}/applicability-decisions",
    response_model=list[ProjectGateApplicabilityHistoryItem],
)
def project_gate_applicability_history(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectGateApplicabilityService(db).history(project_id, gate_id, actor)


@router.get("/{project_id}/template-review/tasks", response_model=ProjectTemplateReviewTaskPage)
def project_template_review_tasks(
    project_id: uuid.UUID,
    search: str | None = None,
    phase: str | None = None,
    category: str | None = None,
    applicability: Literal["mandatory", "conditional"] | None = None,
    included: bool | None = None,
    source: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectTemplateReviewService(db).list_tasks(
        project_id,
        actor,
        search=search,
        phase=phase,
        category=category,
        applicability=applicability,
        included=included,
        source=source,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}/template-review/summary", response_model=ProjectTemplateReviewSummaryOut)
def project_template_review_summary(
    project_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectTemplateReviewService(db).summary(project_id, actor)


@router.get("/{project_id}/task-classification", response_model=ProjectTaskClassificationListOut)
def project_task_classification(
    project_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectTaskClassificationService(db).list(project_id, actor)


@router.put("/{project_id}/task-classification", response_model=ProjectTaskClassificationListOut)
def update_project_task_classification(
    project_id: uuid.UUID,
    payload: ProjectTaskClassificationUpdateIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectTaskClassificationService(db).update(project_id, actor, payload)


@router.post("/{project_id}/tasks", response_model=ProjectManualTaskCreateOut, status_code=201)
def create_project_manual_task(
    project_id: uuid.UUID,
    payload: ProjectManualTaskCreateIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectManualTaskService(db).create(project_id, actor, payload)


@router.post("/{project_id}/running-tasks", status_code=201)
def add_task_to_running_project(
    project_id: uuid.UUID,
    payload: RunningProjectTaskAddIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Add a task to a project that has started - to this project only, or
    (Admin) to this project and its template. See
    app/services/project_task_addition.py."""
    from app.services.project_task_addition import ProjectTaskAdditionService

    return ProjectTaskAdditionService(db).add_to_running(project_id, actor, payload)


@router.post(
    "/{project_id}/tasks/{task_id}/applicability-decisions",
    response_model=ProjectTaskApplicabilityDecisionOut,
)
def decide_project_task_applicability(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: ProjectTaskApplicabilityDecisionIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectTaskApplicabilityService(db).decide(project_id, task_id, actor, payload)


@router.get(
    "/{project_id}/tasks/{task_id}/applicability-decisions",
    response_model=list[ProjectTaskApplicabilityHistoryItem],
)
def project_task_applicability_history(
    project_id: uuid.UUID, task_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    return ProjectTaskApplicabilityService(db).history(project_id, task_id, actor)


@router.get("/{project_id}")
def project_detail(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return project_json(db, get_project(db, project_id, actor), True)


@router.patch("/{project_id}")
def update_project(project_id: uuid.UUID, payload: ProjectUpdateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    if not can_edit(db, project, actor):
        raise HTTPException(403, "Only Admin or the assigned Project Manager can edit project details.")
    if project.status in {"completed", "archived"}:
        raise HTTPException(409, "Completed or archived projects cannot be edited.")
    before = project_snapshot(project)
    if payload.name is not None: project.name = clean_required(payload.name, "Project name")
    if payload.client_name is not None: project.client_name = clean_required(payload.client_name, "Client name")
    if payload.site_address is not None: project.site_address = clean_required(payload.site_address, "Site address")
    if payload.description is not None: project.description = clean_optional(payload.description)
    if payload.template_version_id is not None:
        if not is_org_admin(actor):
            raise HTTPException(403, "Only Admin or Super Admin can attach the published template version.")
        if project.status != "draft":
            raise HTTPException(409, "A template can only be attached while the project is draft.")
        if project.template_version_id and project.template_version_id != payload.template_version_id:
            raise HTTPException(409, "The attached template version cannot be replaced through project details.")
        template_version = db.get(V2TemplateVersion, payload.template_version_id)
        if not template_version or template_version.status != "published":
            raise HTTPException(422, "Select a published template version.")
        project.template_version_id = template_version.id
    if payload.start_date is not None:
        if project.template_version_id and payload.start_date != project.start_date:
            raise HTTPException(409, "Start date cannot change after a template is applied. Use schedule revision later.")
        project.start_date = payload.start_date
    # Target handover is derived from the template's duration, not entered.
    # Clearing it would leave a project that can never be activated and no
    # way to restore the value, so say so rather than accept and re-derive.
    if payload.clear_target_handover_date:
        raise HTTPException(409, "Target handover is derived from the template duration and cannot be cleared.")
    if payload.target_handover_date is not None and project.template_version_id:
        raise HTTPException(409, "Target handover is derived from the template duration and cannot be set directly.")
    if payload.target_handover_date is not None:
        project.target_handover_date = payload.target_handover_date
    # Heals drafts created before the date became derived, and any project
    # whose start date just moved while no template was attached. Without
    # this they would sit permanently un-activatable now that no client can
    # supply the value by hand.
    if project.template_version_id and not project.target_handover_date:
        template_version = db.get(V2TemplateVersion, project.template_version_id)
        if template_version:
            project.target_handover_date = derive_target_handover_date(project.start_date, template_version)
    if project.target_handover_date and project.target_handover_date < project.start_date:
        raise HTTPException(422, "Target handover date cannot be before the start date.")
    add_audit(db, actor, project, "PROJECT_DETAILS_UPDATED", payload.reason.strip(), before, project_snapshot(project))
    db.commit()
    db.refresh(project)
    return project_json(db, project, True)


@router.post("/{project_id}/memberships")
def set_membership(project_id: uuid.UUID, payload: ProjectMembershipIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    if project.status in {"completed", "archived"}:
        raise HTTPException(409, "The team cannot change on a completed or archived project.")
    is_pm = has_membership(db, project.id, actor, {"project_manager"})
    is_supervisor = has_membership(db, project.id, actor, {"site_supervisor"})
    allowed = (payload.project_role == "project_manager" and is_org_admin(actor)) or (payload.project_role == "site_supervisor" and (is_org_admin(actor) or is_pm)) or (payload.project_role == "internal_employee" and (is_org_admin(actor) or is_pm or is_supervisor))
    if not allowed:
        raise HTTPException(403, "You do not have permission to assign this project role.")
    if payload.project_role in ACCOUNTABLE_ROLES and project.status == "active":
        # U6: on an ACTIVE project, PM/Supervisor changes go through the
        # two-step request/approval flow (BR-007) instead of taking
        # immediate effect. Draft-phase team setup (before activation)
        # stays on the immediate path below, unchanged from pre-U6
        # behavior - BR-007's reassignment rules govern live execution,
        # not initial project setup, and several existing tests
        # (test_activate_rejects_when_accountable_role_missing,
        # test_activation_without_active_pm_or_supervisor_is_rejected_...)
        # rely on freely ending/reassigning an accountable role while the
        # project is still draft.
        change = ProjectRoleChangeService(db).request_role_change(
            project.id, payload.project_role, payload.employee_id, payload.reason, actor,
        )
        return role_change_json(db, change)
    membership = assign_membership(db, project, payload.employee_id, payload.project_role, payload.reason, actor)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This project role already has an active assignment.") from exc
    return membership_json(db, membership)


@router.post("/{project_id}/memberships/{membership_id}/end")
def end_membership(project_id: uuid.UUID, membership_id: uuid.UUID, payload: ProjectMembershipEndIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    membership = db.get(V2ProjectMembership, membership_id)
    if not membership or membership.project_id != project.id or membership.ends_at is not None:
        raise HTTPException(404, "Active project membership not found.")
    is_pm = has_membership(db, project.id, actor, {"project_manager"})
    is_supervisor = has_membership(db, project.id, actor, {"site_supervisor"})
    allowed = (membership.project_role == "project_manager" and is_org_admin(actor)) or (membership.project_role == "site_supervisor" and (is_org_admin(actor) or is_pm)) or (membership.project_role == "internal_employee" and (is_org_admin(actor) or is_pm or is_supervisor))
    if not allowed:
        raise HTTPException(403, "You do not have permission to end this project assignment.")
    if project.status == "active" and membership.project_role in ACCOUNTABLE_ROLES:
        # U6: on an ACTIVE project, an accountable role can no longer be
        # ended directly - it must go through a role-change request naming
        # a replacement, approved via
        # POST /{project_id}/role-changes/{change_id}/approve, which
        # atomically ends this membership and starts the replacement.
        # Draft-phase projects keep the pre-U6 direct-end behavior (see
        # matching note in set_membership above).
        raise HTTPException(
            409,
            "A PM or Supervisor cannot be ended directly on an active project - request a replacement via the role change flow.",
        )
    before = membership_json(db, membership)
    membership.ends_at = datetime.now(timezone.utc)
    add_audit(db, actor, project, "PROJECT_ROLE_ENDED", payload.reason.strip(), before, membership_json(db, membership), "project_membership", membership.id)
    db.commit()
    return membership_json(db, membership)


@router.post("/{project_id}/role-changes")
def create_role_change_request(project_id: uuid.UUID, payload: ProjectRoleChangeRequestIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """Dedicated request endpoint for U6's two-step PM/Supervisor
    reassignment flow (BR-007). POST /{project_id}/memberships also routes
    PM/Supervisor role assignments here (see set_membership above) so both
    the legacy membership-assignment path and this explicit endpoint reach
    the same gated flow."""
    if payload.role_type not in ACCOUNTABLE_ROLES:
        raise HTTPException(422, "Only project_manager or site_supervisor role changes go through this flow.")
    change = ProjectRoleChangeService(db).request_role_change(
        project_id, payload.role_type, payload.replacement_employee_id, payload.reason, actor,
        change_type=payload.change_type,
    )
    return role_change_json(db, change)


@router.get("/{project_id}/role-changes")
def list_role_changes(project_id: uuid.UUID, status_filter: str | None = Query(None, alias="status"), actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    statement = select(ProjectRoleChange).where(ProjectRoleChange.project_id == project.id).order_by(ProjectRoleChange.requested_at.desc())
    if status_filter:
        statement = statement.where(ProjectRoleChange.status == status_filter)
    return [role_change_json(db, change) for change in db.scalars(statement).all()]


@router.post("/{project_id}/role-changes/{change_id}/approve")
def approve_role_change(project_id: uuid.UUID, change_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    membership = ProjectRoleChangeService(db).approve_role_change(project_id, change_id, actor)
    return membership_json(db, membership)


@router.post("/{project_id}/role-changes/{change_id}/reject")
def reject_role_change(project_id: uuid.UUID, change_id: uuid.UUID, payload: ProjectRoleChangeRejectIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    change = ProjectRoleChangeService(db).reject_role_change(project_id, change_id, actor, payload.reason)
    return role_change_json(db, change)


@router.get("/{project_id}/role-changes/reassignment-required")
def reassignment_required(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """BR-007: employees currently holding an active accountable (PM/
    Supervisor) membership on this project while marked
    `availability = 'unavailable'` - a queryable condition surfaced for a
    human to act on, never a silent auto-reassignment."""
    return ProjectRoleChangeService(db).reassignment_required(project_id, actor)


# Phase 8: actions a future task-execution engine would record. None of these
# are written anywhere in the codebase today (no execution workflow exists
# yet), so this set exists purely so the deletion guard below activates
# automatically once that engine ships, instead of needing to be revisited.
EXECUTION_AUDIT_ACTIONS = {
    "TASK_STARTED",
    "TASK_PROGRESS_SUBMITTED",
    "TASK_EVIDENCE_SUBMITTED",
    "TASK_VERIFIED",
    "TASK_REJECTED",
    "TASK_APPROVAL_DECIDED",
    "TASK_COMPLETED",
}


def execution_activity_reasons(db: Session, project: V2Project) -> list[str]:
    """Detect whether task execution has started for this project.

    Checked against fields/tables that already exist:
    - V2ProjectTask.lifecycle_status leaving "draft" (its authoritative
      execution-state field). This branch is currently unreachable in
      practice: the column carries a database CheckConstraint pinning it to
      "draft" until a later phase relaxes it, so it cannot fire today.
    - V2AuditEvent rows recording an execution action for this project.
    Both are read-only checks; neither creates or assumes an execution
    workflow, which is explicitly out of scope for this phase.
    """
    reasons: list[str] = []
    non_draft_tasks = db.scalar(
        select(func.count()).select_from(V2ProjectTask).where(
            V2ProjectTask.project_id == project.id,
            V2ProjectTask.lifecycle_status != "draft",
        )
    )
    if non_draft_tasks:
        reasons.append(f"{non_draft_tasks} task(s) have progressed beyond planning status")
    execution_events = db.scalar(
        select(func.count()).select_from(V2AuditEvent).where(
            V2AuditEvent.project_id == project.id,
            V2AuditEvent.action.in_(EXECUTION_AUDIT_ACTIONS),
        )
    )
    if execution_events:
        reasons.append(f"{execution_events} task execution audit event(s) recorded")
    return reasons


@router.post("/{project_id}/activate")
def activate_project(project_id: uuid.UUID, payload: ProjectActivateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """Dedicated Phase 8 activation endpoint.

    This mirrors the draft-to-active eligibility rules already enforced by
    POST /{project_id}/status, but adds an explicit duplicate-activation
    guard, a distinct PROJECT_ACTIVATED audit action, and an atomic
    rollback on any failure. POST /{project_id}/status is left completely
    unmodified so its existing Phase 1/2 behaviour (including its own
    draft-to-active path) is unaffected.
    """
    project = get_project(db, project_id, actor)

    if project.status == "active":
        raise HTTPException(409, "This project is already active. Activation cannot be requested again.")
    if project.status != "draft":
        raise HTTPException(409, f"A {project.status.replace('_', ' ')} project cannot be activated. Only a draft project is eligible.")
    if not is_org_admin(actor):
        raise HTTPException(403, "Only Admin can activate a project.")

    roles = {item.project_role for item in active_memberships(db, project.id)}
    missing = []
    if "project_manager" not in roles: missing.append("Project Manager")
    if "site_supervisor" not in roles: missing.append("Site Supervisor")
    if not project.template_version_id: missing.append("approved 45-day template")
    if not project.target_handover_date: missing.append("target handover date")
    if missing:
        raise HTTPException(409, "Project activation requires: " + ", ".join(missing) + ".")

    template_version = db.get(V2TemplateVersion, project.template_version_id)
    if not template_version or template_version.status != "published":
        raise HTTPException(409, "The attached template version is no longer published. Re-attach a published version before activating.")

    before = project_snapshot(project)
    try:
        # U1: lock the immutable baseline and instantiate execution tasks
        # before flipping status, in the same transaction, so no path can
        # activate a project without both succeeding together.
        baseline = ProjectBaselineService(db).lock_and_instantiate(project, actor)
        project.status = "active"
        project.activated_at = datetime.now(timezone.utc)
        project.activated_by = actor.id
        db.flush()
        # Template/version reference lock: PATCH /{project_id} already
        # refuses to change template_version_id once status != "draft"
        # (see update_project below), so no additional enforcement is
        # needed here beyond this project having just left "draft".
        add_audit(
            db, actor, project, "PROJECT_ACTIVATED", payload.reason.strip(),
            before, {**project_snapshot(project), "template_version_locked": True, "baseline_id": str(baseline.id) if baseline else None},
        )
        # U2 (WhatsApp gate workflow): emit in the same transaction as the
        # activation itself, so a rollback on any later failure in this
        # block means the event never persists either (see OutboxService
        # docstring). The draft-to-active guard above makes this a one-time
        # transition per project, so the idempotency key needs no timestamp.
        OutboxService(db).emit(
            event_type="project.activated",
            aggregate_type="project",
            aggregate_id=project.id,
            payload={"project_id": str(project.id), "project_name": project.name},
            idempotency_key=f"project:{project.id}:project.activated",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(project)
    return project_json(db, project, True)


def restore_target_status(db: Session, project: V2Project) -> str:
    """The status a project returns to when its archive is undone.

    Read from the audit trail rather than guessed: the archive transition
    recorded the previous status in `before_json`. An `active` project comes
    back as `on_hold`, never straight to `active` - undoing an archive must
    not silently restart execution, SLA timers or no-update tracking. Admin
    or the accountable PM can then resume it deliberately.
    """
    events = db.scalars(
        select(V2AuditEvent)
        .where(V2AuditEvent.project_id == project.id)
        .order_by(V2AuditEvent.occurred_at.desc(), V2AuditEvent.id.desc())
        .limit(100)
    ).all()

    previous = None
    for event in events:
        if (event.after_json or {}).get("status") == "archived":
            previous = (event.before_json or {}).get("status")
            break

    if previous in {"draft", "on_hold", "completed"}:
        return previous
    if previous == "active":
        return "on_hold"
    # No archive event on record (archived before auditing, or trimmed).
    return "on_hold" if project.activated_at else "draft"


@router.post("/{project_id}/restore")
def restore_project(project_id: uuid.UUID, payload: ProjectRestoreIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """Undo an archive. Archived is otherwise terminal in `change_status`,
    which left an accidentally archived project unrecoverable through the
    portal - this is the only route out of it."""
    project = get_project(db, project_id, actor)
    if not is_org_admin(actor):
        raise HTTPException(403, "Only Admin can restore an archived project.")
    if project.status != "archived":
        raise HTTPException(409, "Only an archived project can be restored.")

    target = restore_target_status(db, project)
    before = project_snapshot(project)
    project.status = target
    try:
        add_audit(
            db, actor, project, "PROJECT_RESTORED", payload.reason.strip(),
            before, {**project_snapshot(project), "restored_to": target},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(project)
    return project_json(db, project, True)


@router.post("/{project_id}/status")
def change_status(project_id: uuid.UUID, payload: ProjectStatusIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    target = payload.status.strip().lower()
    allowed_transitions = {"draft": {"active", "archived"}, "active": {"on_hold", "completed", "archived"}, "on_hold": {"active", "completed", "archived"}, "completed": {"archived"}, "archived": set()}
    if target not in PROJECT_STATUSES:
        raise HTTPException(422, "Unknown project status.")
    if target == project.status:
        return project_json(db, project, True)
    if target not in allowed_transitions[project.status]:
        raise HTTPException(409, f"A {project.status.replace('_', ' ')} project cannot move to {target.replace('_', ' ')}.")
    is_pm = has_membership(db, project.id, actor, {"project_manager"})
    if target in {"active", "archived"} and not is_org_admin(actor):
        raise HTTPException(403, "Only Admin can activate or archive a project.")
    if target in {"on_hold", "completed"} and not (is_org_admin(actor) or is_pm):
        raise HTTPException(403, "Only Admin or the assigned Project Manager can make this status change.")
    if target == "active" and project.status == "draft":
        roles = {item.project_role for item in active_memberships(db, project.id)}
        missing = []
        if "project_manager" not in roles: missing.append("Project Manager")
        if "site_supervisor" not in roles: missing.append("Site Supervisor")
        if not project.template_version_id: missing.append("approved 45-day template")
        if not project.target_handover_date: missing.append("target handover date")
        if missing:
            raise HTTPException(409, "Project activation requires: " + ", ".join(missing) + ".")
        # U1: lock the immutable baseline and instantiate execution tasks
        # before flipping status, in the same transaction as this status
        # change - this is the second (of two) independent draft->active
        # code paths, so it must call the same baseline-lock service.
        ProjectBaselineService(db).lock_and_instantiate(project, actor)
        project.activated_at = datetime.now(timezone.utc)
        project.activated_by = actor.id
    before = project_snapshot(project)
    project.status = target
    if target == "completed":
        # Anchors app.services.evidence_retention's 6-month clock - see
        # V2Project.completed_at's docstring for why this must be the
        # actual completion moment, not target_handover_date.
        project.completed_at = datetime.now(timezone.utc)
    try:
        add_audit(db, actor, project, "PROJECT_STATUS_CHANGED", payload.reason.strip(), before, project_snapshot(project))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(project)
    return project_json(db, project, True)


@router.get("/{project_id}/activity")
def project_activity(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id, actor)
    rows = db.execute(select(V2AuditEvent, User).outerjoin(User, User.id == V2AuditEvent.actor_user_id).where(V2AuditEvent.project_id == project.id).order_by(V2AuditEvent.occurred_at.desc()).limit(100)).all()
    return [{"id": str(event.id), "action": event.action, "entity_type": event.entity_type, "entity_id": str(event.entity_id), "actor_name": user.name if user else "System", "reason": event.reason, "before": event.before_json, "after": event.after_json, "occurred_at": event.occurred_at.isoformat()} for event, user in rows]


@router.get("/{project_id}/execution-tasks")
def project_execution_tasks(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """Phase 9: read-only task baseline for an activated project.

    This intentionally returns only what the Phase 3 task-generation and
    Phase 8 activation capabilities already produced - the project's
    generated task snapshot, its planning/applicability fields, and its
    lifecycle_status (always "draft" today, since no task-execution engine
    exists yet). No status, evidence, verification or assignment mutation
    is exposed here; this endpoint has no write path at all.
    """
    project = get_project(db, project_id, actor)
    if not project.activated_at:
        raise HTTPException(409, "This project has not been activated yet. No task baseline is available to view.")

    tasks = list(db.scalars(
        select(V2ProjectTask)
        .where(V2ProjectTask.project_id == project.id)
        .order_by(V2ProjectTask.template_sequence.asc(), V2ProjectTask.original_code.asc())
    ).all())

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "project_code": project.code,
        "project_status": project.status,
        "activated_at": project.activated_at.isoformat(),
        "total_tasks": len(tasks),
        "included_task_count": sum(1 for task in tasks if task.included),
        "excluded_task_count": sum(1 for task in tasks if not task.included),
        "tasks": [
            {
                "id": str(task.id),
                "code": task.original_code,
                "sequence": task.template_sequence,
                "title": task.title,
                "description": task.description,
                "phase": task.phase,
                "category": task.category,
                "task_kind": task.task_kind,
                "task_class": task.task_class,
                "applicability": task.applicability,
                "schedule_classification": task.schedule_classification,
                "planned_start_day": task.planned_start_day,
                "planned_end_day": task.planned_end_day,
                "duration_days": task.duration_days,
                "evidence_required": task.evidence_required,
                "lifecycle_status": task.lifecycle_status,
                "included": task.included,
                "decision_state": task.decision_state,
            }
            for task in tasks
        ],
    }


@router.delete("/{project_id}")
def delete_project(project_id: uuid.UUID, payload: ProjectDeleteIn, actor: User = Depends(require_roles(*ORG_ADMIN_ROLES)), db: Session = Depends(get_db)):
    """Controlled Phase 8 project deletion.

    - Draft projects are permanently removed (hard delete). Membership rows
      are deleted explicitly first because V2ProjectMembership.project_id is
      declared ON DELETE RESTRICT (not CASCADE) at the schema level -
      Postgres would otherwise reject the delete. Every other project child
      table (tasks, external gates, dependencies, gate-applicability
      decisions) is ON DELETE CASCADE and is left to the database.
    - Activated projects (active/on_hold) with no detected execution
      activity are soft-deleted by moving them into the existing "archived"
      status - the same terminal state POST /{project_id}/status already
      supports. No row is removed.
    - Completed or already-archived projects, and any project where
      execution activity is detected, are blocked with a clear reason.
    - Template tables (V2Template/V2TemplateVersion/V2TemplateTask/...) are
      never read for writes and never touched by this endpoint.
    """
    project = get_project(db, project_id, actor)

    if project.status == "archived":
        raise HTTPException(409, "This project has already been archived and cannot be deleted again.")
    if project.status == "completed":
        raise HTTPException(409, "Completed projects cannot be deleted through this action.")

    activity = execution_activity_reasons(db, project)
    if activity:
        raise HTTPException(
            409,
            "This project cannot be deleted because execution activity already exists: "
            + "; ".join(activity)
            + ". Deletion is only allowed before execution starts.",
        )

    if payload.confirmation.strip().upper() != project.code:
        raise HTTPException(422, f"Type {project.code} to confirm this action.")

    before = project_snapshot(project)
    try:
        if project.status == "draft":
            add_audit(db, actor, project, "PROJECT_DRAFT_DELETED", payload.reason.strip(), before=before)
            db.flush()
            memberships = db.scalars(select(V2ProjectMembership).where(V2ProjectMembership.project_id == project.id)).all()
            for membership in memberships:
                db.delete(membership)
            db.flush()
            db.delete(project)
            db.commit()
            return {"deleted": True, "deletion_type": "hard", "project_id": str(project_id), "status": None}

        # Activated project (active/on_hold) with no execution activity:
        # soft delete by archiving, never by removing the row.
        project.status = "archived"
        db.flush()
        add_audit(db, actor, project, "PROJECT_ARCHIVED", payload.reason.strip(), before, project_snapshot(project))
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(project)
    return {"deleted": True, "deletion_type": "soft", "project_id": str(project_id), "status": project.status}
