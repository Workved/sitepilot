"""Add a task to a project after it was created - to this project only, or
to this project and its template.

Who: Admin on any project; the project's own Project Manager or Site
Supervisor on theirs. Only Admin may also add the task to the template,
because a template is shared by every project made from it.

Running project (active / on hold): the task becomes an execution task
straight away. It is not part of the locked baseline (the original plan), so
it has no baseline_task row and is marked `created_from_baseline = False`,
with who added it and why. The baseline is never touched.

Draft project: `ProjectManualTaskService` still owns that path; this module
only supplies the shared access rule and the template step.

"And the template": template versions are frozen once published, and every
project stays on the version it started from. So the task is added to a new
version - the current published one, cloned - which is then published. New
projects get it; existing projects, this one aside, are left alone
(product decision). The template step runs after the project task is saved;
if it fails, the project task stays and the response says why, naming the
draft version left for an Admin to finish.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import ProjectBaseline, Task, TaskDependency
from app.models import User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectTask
from app.services.access_control import is_org_admin
from app.services.outbox import OutboxService
from app.template_models import V2TemplateTask, V2TemplateVersion

RUNNING_STATUSES = {"active", "on_hold"}
PROJECT_TASK_ROLES = {"project_manager", "site_supervisor"}
MANUAL_CODE_PATTERN = re.compile(r"^MANUAL-(\d+)$")
TEMPLATE_CODE_PATTERN = re.compile(r"^([A-Z]+-?)(\d+)$")


def require_task_adder(db: Session, project: V2Project, actor: User) -> None:
    """Admin anywhere; a PM or Supervisor only on a project they belong to."""
    if is_org_admin(actor):
        return
    # Imported here: routes.projects_v2 imports the manual-task service,
    # which imports this module.
    from app.routes.projects_v2 import has_membership

    if actor.role in (UserRole.project_manager, UserRole.supervisor) and has_membership(db, project.id, actor, PROJECT_TASK_ROLES):
        return
    raise HTTPException(403, "Only Admin, or this project's Project Manager or Supervisor, can add tasks.")


def require_template_adder(actor: User) -> None:
    if not is_org_admin(actor):
        raise HTTPException(403, "Only Admin can add a task to the template.")


def next_manual_code(db: Session, project_id: uuid.UUID) -> str:
    """Next free MANUAL-NNN code, across both the draft task list and the
    execution tasks, so a code is never reused within a project."""
    codes = [
        *db.scalars(select(V2ProjectTask.original_code).where(V2ProjectTask.project_id == project_id)).all(),
        *db.scalars(select(Task.original_code).where(Task.project_id == project_id)).all(),
    ]
    used = {int(m.group(1)) for code in codes if (m := MANUAL_CODE_PATTERN.fullmatch(code or ""))}
    number = 1
    while number in used:
        number += 1
    return f"MANUAL-{number:03d}"


def day_offset(project: V2Project, value: date) -> int:
    """Calendar day number in the project, Day 1 being the start date
    (the same rule as `project_schedule_dates.planned_date_for_day`)."""
    return (value - project.start_date).days + 1


class TemplateTaskPromotion:
    """Publish a new version of the project's template with one more task."""

    def __init__(self, db: Session):
        self.db = db

    def current_version(self, project: V2Project) -> V2TemplateVersion:
        if not project.template_version_id:
            raise HTTPException(409, "This project has no template to add the task to.")
        project_version = self.db.get(V2TemplateVersion, project.template_version_id)
        current = self.db.scalar(
            select(V2TemplateVersion).where(
                V2TemplateVersion.template_id == project_version.template_id,
                V2TemplateVersion.is_current_published.is_(True),
            )
        ) if project_version else None
        if current is None:
            raise HTTPException(409, "This project's template has no published version to add the task to.")
        return current

    def check(self, project: V2Project, start_day: int, end_day: int) -> V2TemplateVersion:
        """Everything that can be checked before anything is saved."""
        current = self.current_version(project)
        if end_day > current.duration_days:
            raise HTTPException(
                422,
                f"The template plans {current.duration_days} days, and this task ends on day {end_day}. "
                "Add it to this project only, or pick dates within the template's length.",
            )
        return current

    def _next_code(self, version_id: uuid.UUID) -> tuple[str, int]:
        rows = self.db.execute(
            select(V2TemplateTask.code, V2TemplateTask.sequence_no).where(V2TemplateTask.template_version_id == version_id)
        ).all()
        codes = {code.strip().upper() for code, _ in rows}
        sequence = max((seq for _, seq in rows), default=0) + 1
        # Follow the template's own numbering (T001 -> T014) when it has one.
        prefixes: dict[str, list[re.Match]] = {}
        for code in codes:
            match = TEMPLATE_CODE_PATTERN.fullmatch(code)
            if match:
                prefixes.setdefault(match.group(1), []).append(match)
        if prefixes:
            prefix, matches = max(prefixes.items(), key=lambda item: len(item[1]))
            width = max(len(m.group(2)) for m in matches)
            number = max(int(m.group(2)) for m in matches) + 1
        else:
            prefix, width, number = "ADD-", 3, 1
        while f"{prefix}{number:0{width}d}" in codes:
            number += 1
        return f"{prefix}{number:0{width}d}", sequence

    def add(self, actor: User, project: V2Project, *, title: str, description: str | None, phase: str, category: str,
            start_day: int, end_day: int, evidence_required: bool, reason: str) -> dict:
        """Clone, add the task, publish. Each step commits on its own (the
        template commands own their transactions), so a failure part-way
        returns an error description instead of raising."""
        from app.services.template_commands import TemplateCommandService
        from app.services.template_mutation_access import concurrency_token
        from app.services.template_publish_service import TemplatePublishService
        from app.services.template_task_commands import TemplateTaskCommandService
        from app.template_mutation_schemas import TemplateCloneRequest
        from app.template_publish_schemas import TemplatePublishRequest
        from app.template_task_mutation_schemas import TemplateTaskCreateRequest

        current = self.check(project, start_day, end_day)
        note = f"Added task \"{title}\" from project {project.code}: {reason}"[:1000]
        draft_id = None
        try:
            clone = TemplateCommandService(self.db).clone_version(actor, current.id, TemplateCloneRequest(change_note=note))
            draft_id = clone.version_id
            code, sequence = self._next_code(draft_id)
            draft = self.db.get(V2TemplateVersion, draft_id)
            created = TemplateTaskCommandService(self.db).create_task(actor, draft_id, TemplateTaskCreateRequest(
                code=code, sequence_no=sequence, title=title, description=description,
                schedule_classification="execution", planned_start_day=start_day, planned_end_day=end_day,
                phase=phase, category=category, evidence_required=evidence_required,
                duration_days=end_day - start_day + 1, revision_token=concurrency_token(draft),
            ))
            published = TemplatePublishService(self.db).publish(actor, draft_id, TemplatePublishRequest(
                revision_token=created.revision_token, change_note=note,
            ))
        except HTTPException as exc:
            self.db.rollback()
            detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
            version_no = self.db.scalar(select(V2TemplateVersion.version_no).where(V2TemplateVersion.id == draft_id)) if draft_id else None
            return {
                "added": False,
                "error": str(detail),
                "draft_version_id": str(draft_id) if draft_id else None,
                "draft_version_no": version_no,
            }
        return {
            "added": True,
            "template_code": clone.template_code,
            "template_name": clone.template_name,
            "version_id": str(published.version_id),
            "version_no": published.version_no,
            "task_code": code,
        }


class ProjectTaskAdditionService:
    def __init__(self, db: Session):
        self.db = db

    def add_to_running(self, project_id: uuid.UUID, actor: User, payload) -> dict:
        project = self.db.scalar(select(V2Project).where(V2Project.id == project_id).with_for_update())
        if not project:
            raise HTTPException(404, "Project not found.")
        require_task_adder(self.db, project, actor)
        if project.status == "draft":
            raise HTTPException(409, "This project hasn't started yet - add the task from its task review instead.")
        if project.status not in RUNNING_STATUSES:
            raise HTTPException(409, "Tasks can't be added to a completed or archived project.")
        if payload.planned_start_date < project.start_date:
            raise HTTPException(422, f"The task can't start before the project's start date ({project.start_date:%d %b %Y}).")
        start_day = day_offset(project, payload.planned_start_date)
        end_day = day_offset(project, payload.planned_end_date)

        promotion = TemplateTaskPromotion(self.db)
        if payload.add_to_template:
            require_template_adder(actor)
            promotion.check(project, start_day, end_day)

        baseline = self.db.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project.id))
        if baseline is None:
            raise HTTPException(409, "This project has no locked plan yet, so tasks can't be added to it.")

        predecessor = None
        if payload.after_task_id:
            predecessor = self.db.get(Task, payload.after_task_id)
            if predecessor is None or predecessor.project_id != project.id:
                raise HTTPException(422, "The task it should start after isn't in this project.")
            if predecessor.lifecycle_status == "cancelled":
                raise HTTPException(422, "A new task can't wait on a cancelled task.")

        sequence = (self.db.scalar(select(func.max(Task.template_sequence)).where(Task.project_id == project.id)) or 0) + 1
        task = Task(
            project_id=project.id,
            baseline_id=baseline.id,
            baseline_task_id=None,
            original_code=next_manual_code(self.db, project.id),
            template_sequence=sequence,
            title=payload.title,
            description=payload.description,
            schedule_classification="execution",
            planned_start_day=start_day,
            planned_end_day=end_day,
            planned_start_date=payload.planned_start_date,
            planned_end_date=payload.planned_end_date,
            phase=payload.phase,
            category=payload.category,
            applicability="mandatory",
            task_class=None,
            task_kind="work",
            evidence_required=payload.evidence_required,
            duration_days=end_day - start_day + 1,
            lifecycle_status="planned",
            created_from_baseline=False,
            added_by=actor.id,
            added_reason=payload.reason,
        )
        self.db.add(task)
        self.db.flush()
        if predecessor is not None:
            self.db.add(TaskDependency(
                project_id=project.id, baseline_id=baseline.id, project_dependency_id=None,
                predecessor_task_id=predecessor.id, successor_task_id=task.id,
                dependency_type="finish_to_start", blocking=True,
                rule_text=f"Starts after {predecessor.original_code} is finished.", created_from_baseline=False,
            ))
        now = datetime.now(timezone.utc)
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id, action="TASK_ADDED_AFTER_START", entity_type="task", entity_id=task.id,
            project_id=project.id, source="portal", before_json=None,
            after_json={
                "code": task.original_code, "title": task.title, "phase": task.phase, "category": task.category,
                "planned_start_date": task.planned_start_date.isoformat(), "planned_end_date": task.planned_end_date.isoformat(),
                "after_task_id": str(predecessor.id) if predecessor else None, "add_to_template": payload.add_to_template,
            },
            reason=payload.reason, occurred_at=now,
        ))
        emit_task_added(self.db, task, project, actor)
        self.db.commit()

        result = {
            "task_id": str(task.id), "code": task.original_code, "title": task.title,
            "planned_start_date": task.planned_start_date.isoformat(), "planned_end_date": task.planned_end_date.isoformat(),
            "template": None,
        }
        if payload.add_to_template:
            result["template"] = promotion.add(
                actor, project, title=task.title, description=task.description, phase=task.phase, category=task.category,
                start_day=start_day, end_day=end_day, evidence_required=task.evidence_required, reason=payload.reason,
            )
        return result


def emit_task_added(db: Session, task: Task, project: V2Project, actor: User) -> None:
    """Tell the project's PM and Supervisor (not whoever added it)."""
    OutboxService(db).emit(
        event_type="task.added",
        aggregate_type="task",
        aggregate_id=task.id,
        payload={
            "task_id": str(task.id),
            "project_id": str(project.id),
            "title": task.title,
            "planned_start_date": task.planned_start_date.isoformat() if task.planned_start_date else None,
            "planned_end_date": task.planned_end_date.isoformat() if task.planned_end_date else None,
            "reason": task.added_reason,
            "added_by": str(actor.id),
        },
        idempotency_key=f"task:{task.id}:task.added",
    )
