"""Phase 2 U2/U3: project-vendor mapping, task vendor delegation, and vendor
acknowledgement routes (R2/R3/R4).

Mirrors the router/route/dependency-injection pattern established in
`app.routes.execution_tasks_v2`: a service instantiated per-request, plain
`Depends(current_user)` / `Depends(get_db)`, and a Pydantic `_Out` schema on
the response. The acknowledgement route is a PM-authenticated portal action
only - a vendor cannot start/complete/verify/approve/close a task through
this mechanism (R4); see
`app.services.vendor_acknowledgement.VendorAcknowledgementService`.

Vendor activity/incident capture (presence/delay/rework/incident + evidence)
was removed - Phase 2 scope, not this release.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_roles
from app.database import get_db
from app.execution_models import Task
from app.models import User, UserRole
from app.routes.projects_v2 import get_project
from app.schemas.vendor_assignment import (
    CapabilityCategoryIn,
    CapabilityCategoryOut,
    CapabilityCategoryUpdateIn,
    ProjectContactAttachmentOut,
    ProjectVendorContactOut,
    ProjectVendorMapIn,
    ProjectVendorMappingOut,
    ProjectVendorOut,
    ProjectVendorRemoveIn,
    TaskVendorAssignmentDetailOut,
    TaskVendorAssignmentIn,
    TaskVendorAssignmentOut,
    TaskVendorContactIn,
    TaskVendorUnassignIn,
    V2VendorOut,
    VendorAcknowledgementIn,
    VendorAcknowledgementOut,
    VendorCapabilitiesIn,
    VendorContactProjectIn,
    VendorContactProjectOut,
)
from app.services.project_vendor import ProjectVendorService
from app.services.task_vendor_assignment import TaskVendorAssignmentService
from app.services.vendor_acknowledgement import VendorAcknowledgementService
from app.services.vendor_contact_project import VendorContactProjectService
from app.template_models import V2TemplateTask, V2TemplateVersion
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    V2VendorContact,
    VendorAcknowledgement,
    VendorContactProject,
)

router = APIRouter(prefix="/api/v2/projects", tags=["v2-vendors"])

# A bare `/api/v2/vendors` listing isn't project-scoped, so it can't live on
# the `/api/v2/projects`-prefixed router above - registered separately in
# main.py alongside it.
vendors_router = APIRouter(prefix="/api/v2/vendors", tags=["v2-vendors"])


def _ensure_phase_categories(db: Session) -> None:
    """Idempotently creates a `V2CapabilityCategory` for every distinct,
    non-null phase used by a published template's tasks (case-insensitive
    dedupe against categories that already exist - including ones left
    over from the one-time vendor import, which creates a category per
    LEGACY vendor.category string and so may not use the same casing/name
    as a template phase). Mirrors the auto-seed pattern already used for
    the legacy Vendor Hub (communication.py's get_hub()), applied to the
    V2 side: vendor capabilities are matched against task PHASE (see
    TaskVendorAssignmentService._vendor_matches_task_category), so the
    category picker a PM uses to set a vendor's capabilities must offer
    the same vocabulary that matching actually checks against - otherwise
    an Admin has no way to create a vendor capability that could ever
    match a real task."""
    phases = [
        phase for (phase,) in db.execute(
            select(V2TemplateTask.phase)
            .join(V2TemplateVersion, V2TemplateTask.template_version_id == V2TemplateVersion.id)
            .where(V2TemplateVersion.status == "published", V2TemplateTask.phase.is_not(None))
            .distinct()
        ).all()
        if phase and phase.strip()
    ]
    if not phases:
        return
    existing_by_lower = {
        name.lower(): True for (name,) in db.execute(select(V2CapabilityCategory.name)).all()
    }
    for phase in phases:
        clean_phase = phase.strip()
        if clean_phase.lower() in existing_by_lower:
            continue
        db.add(V2CapabilityCategory(name=clean_phase))
        existing_by_lower[clean_phase.lower()] = True
    db.commit()


@vendors_router.get("/capability-categories", response_model=list[CapabilityCategoryOut])
def list_capability_categories(
    include_hidden: bool = False,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The vendor-category list, which is also the template phase list.
    Admin-managed (see app/services/vendor_categories.py); phases used by
    published templates are still added if missing. Hidden categories are
    left out unless `include_hidden`."""
    from app.services.vendor_categories import vendor_counts

    _ensure_phase_categories(db)
    query = select(V2CapabilityCategory).order_by(V2CapabilityCategory.name)
    if not include_hidden:
        query = query.where(V2CapabilityCategory.active.is_(True))
    counts = vendor_counts(db)
    return [
        CapabilityCategoryOut(id=category.id, name=category.name, active=category.active, vendor_count=counts.get(category.id, 0))
        for category in db.scalars(query).all()
    ]


CATEGORY_ADMIN_ROLES = (UserRole.super_admin, UserRole.admin)


@vendors_router.post("/capability-categories", response_model=CapabilityCategoryOut, status_code=201)
def add_capability_category(
    payload: CapabilityCategoryIn,
    actor: User = Depends(require_roles(*CATEGORY_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    from app.services.vendor_categories import VendorCategoryService, vendor_counts

    category, _created = VendorCategoryService(db).create(payload.name, actor)
    return CapabilityCategoryOut(id=category.id, name=category.name, active=category.active, vendor_count=vendor_counts(db).get(category.id, 0))


@vendors_router.patch("/capability-categories/{category_id}", response_model=CapabilityCategoryOut)
def update_capability_category(
    category_id: uuid.UUID,
    payload: CapabilityCategoryUpdateIn,
    actor: User = Depends(require_roles(*CATEGORY_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    from app.services.vendor_categories import VendorCategoryService, vendor_counts

    category = VendorCategoryService(db).update(category_id, actor, name=payload.name, active=payload.active)
    return CapabilityCategoryOut(id=category.id, name=category.name, active=category.active, vendor_count=vendor_counts(db).get(category.id, 0))


@vendors_router.delete("/capability-categories/{category_id}")
def remove_capability_category(
    category_id: uuid.UUID,
    actor: User = Depends(require_roles(*CATEGORY_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Deletes an unused category; hides one that vendors or tasks use."""
    from app.services.vendor_categories import VendorCategoryService

    return VendorCategoryService(db).remove(category_id, actor)


@vendors_router.post("/{vendor_id}/capabilities", response_model=V2VendorOut)
def set_vendor_capabilities(
    vendor_id: uuid.UUID,
    payload: VendorCapabilitiesIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)),
    db: Session = Depends(get_db),
):
    """Replaces a V2 vendor's full capability set. This is the only write
    path for `V2VendorCapability` outside the one-time legacy import - a
    vendor's capabilities were previously frozen at whatever the import
    produced, with no way to correct or update them (editing a vendor
    through the legacy Vendor Hub only touches the legacy `VendorCategory`
    table, which this route and delegation's matching check never read)."""
    vendor = db.get(V2Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    category_ids = set(payload.category_ids)
    if category_ids:
        valid_ids = set(db.scalars(
            select(V2CapabilityCategory.id).where(V2CapabilityCategory.id.in_(category_ids))
        ).all())
        if valid_ids != category_ids:
            raise HTTPException(422, "One or more capability categories are invalid.")
    db.execute(V2VendorCapability.__table__.delete().where(V2VendorCapability.vendor_id == vendor.id))
    for category_id in category_ids:
        db.add(V2VendorCapability(vendor_id=vendor.id, category_id=category_id))
    db.commit()

    category_names = db.scalars(
        select(V2CapabilityCategory.name).where(V2CapabilityCategory.id.in_(category_ids))
    ).all() if category_ids else []
    return V2VendorOut(
        id=vendor.id,
        name=vendor.name,
        engagement_type=vendor.engagement_type,
        parent_vendor_id=vendor.parent_vendor_id,
        status=vendor.status,
        contact_person=vendor.contact_person,
        phone=vendor.phone,
        whatsapp=vendor.whatsapp,
        capability_categories=sorted(category_names),
        capability_category_ids=sorted(category_ids),
    )


@vendors_router.get("", response_model=list[V2VendorOut])
def list_vendors(
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read surface for the vendor picker (ProjectVendorPanel) - every
    active V2 vendor plus its capability category names. Any authenticated
    project-side user may view vendor master data (mirrors the legacy
    Vendor Hub's unrestricted vendor read), since mapping/delegation
    itself is still PM/Admin-gated at the write routes below."""
    # Blacklisted vendors, and sub-vendors of a blacklisted main vendor, can't
    # take new work, so they aren't offered.
    blacklisted_ids = set(db.scalars(select(V2Vendor.id).where(V2Vendor.status == "blacklisted")).all())
    vendors = [
        vendor for vendor in db.scalars(select(V2Vendor).order_by(V2Vendor.name)).all()
        if vendor.id not in blacklisted_ids and vendor.parent_vendor_id not in blacklisted_ids
    ]
    if not vendors:
        return []
    category_rows = db.execute(
        select(V2VendorCapability.vendor_id, V2CapabilityCategory.id, V2CapabilityCategory.name)
        .join(V2CapabilityCategory, V2VendorCapability.category_id == V2CapabilityCategory.id)
        .where(V2VendorCapability.vendor_id.in_([vendor.id for vendor in vendors]))
    ).all()
    categories_by_vendor: dict[uuid.UUID, list[str]] = {}
    category_ids_by_vendor: dict[uuid.UUID, list[uuid.UUID]] = {}
    for vendor_id, category_id, category_name in category_rows:
        categories_by_vendor.setdefault(vendor_id, []).append(category_name)
        category_ids_by_vendor.setdefault(vendor_id, []).append(category_id)
    return [
        V2VendorOut(
            id=vendor.id,
            name=vendor.name,
            engagement_type=vendor.engagement_type,
            parent_vendor_id=vendor.parent_vendor_id,
            status=vendor.status,
            contact_person=vendor.contact_person,
            phone=vendor.phone,
            whatsapp=vendor.whatsapp,
            capability_categories=categories_by_vendor.get(vendor.id, []),
            capability_category_ids=category_ids_by_vendor.get(vendor.id, []),
        )
        for vendor in vendors
    ]


@router.post("/{project_id}/vendors", response_model=ProjectVendorOut)
def map_vendor(
    project_id: uuid.UUID,
    payload: ProjectVendorMapIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectVendorService(db).map_vendor(project_id, payload.vendor_id, actor)


@router.get("/{project_id}/vendors", response_model=list[ProjectVendorMappingOut])
def list_project_vendors(
    project_id: uuid.UUID,
    include_ended: bool = Query(False),
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read surface for ProjectVendorPanel's "list current mappings" and
    TaskVendorDelegationForm's vendor picker, which must only offer
    vendors already mapped to this project (plan U2 frontend test
    scenario). Defaults to active mappings only - the vendor picker relies
    on that. `include_ended=true` (ProjectVendorPanel's own display) also
    returns removed mappings so history stays visible, distinguished by
    `ends_at`."""
    project = get_project(db, project_id, actor)
    query = (
        select(ProjectVendor, V2Vendor)
        .join(V2Vendor, ProjectVendor.vendor_id == V2Vendor.id)
        .where(ProjectVendor.project_id == project.id)
    )
    if not include_ended:
        query = query.where(ProjectVendor.ends_at.is_(None))
    rows = db.execute(query.order_by(V2Vendor.name)).all()
    contacts_by_vendor = _project_contacts_by_vendor(db, project.id, {vendor.id for _, vendor in rows})
    return [
        ProjectVendorMappingOut(
            id=mapping.id,
            project_id=mapping.project_id,
            vendor_id=mapping.vendor_id,
            vendor_name=vendor.name,
            engagement_type=vendor.engagement_type,
            parent_vendor_id=vendor.parent_vendor_id,
            mapped_by=mapping.mapped_by,
            created_at=mapping.created_at,
            ends_at=mapping.ends_at,
            acknowledged_at=mapping.acknowledged_at,
            contacts=contacts_by_vendor.get(vendor.id, []),
        )
        for mapping, vendor in rows
    ]


def _project_contacts_by_vendor(db: Session, project_id: uuid.UUID, vendor_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[ProjectVendorContactOut]]:
    """Each vendor's contacts, with what they're attached to on this
    project. Attached people first, then the primary contact, then by name -
    so the people actually working here lead every list."""
    if not vendor_ids:
        return {}
    contacts = db.scalars(select(V2VendorContact).where(V2VendorContact.vendor_id.in_(vendor_ids))).all()
    attachments = db.scalars(
        select(VendorContactProject).where(
            VendorContactProject.project_id == project_id,
            VendorContactProject.contact_id.in_([contact.id for contact in contacts]),
            VendorContactProject.ends_at.is_(None),
        )
    ).all() if contacts else []
    category_names = dict(db.execute(select(V2CapabilityCategory.id, V2CapabilityCategory.name)).all())
    by_contact: dict[uuid.UUID, list[ProjectContactAttachmentOut]] = {}
    for row in attachments:
        by_contact.setdefault(row.contact_id, []).append(ProjectContactAttachmentOut(
            id=row.id, category_id=row.category_id,
            category_name=category_names.get(row.category_id) if row.category_id else None, note=row.note,
        ))
    result: dict[uuid.UUID, list[ProjectVendorContactOut]] = {}
    for contact in sorted(contacts, key=lambda c: (not by_contact.get(c.id), not c.is_primary, c.name.lower())):
        result.setdefault(contact.vendor_id, []).append(ProjectVendorContactOut(
            id=contact.id, name=contact.name, designation=contact.designation, phone=contact.phone,
            whatsapp=contact.whatsapp, is_primary=contact.is_primary, attachments=by_contact.get(contact.id, []),
        ))
    return result


@router.post("/{project_id}/vendor-contacts", response_model=list[VendorContactProjectOut])
def attach_vendor_contact(
    project_id: uuid.UUID,
    payload: VendorContactProjectIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Attach one of a mapped vendor's people to this project, optionally
    per trade category. Returns that person's active attachments here."""
    return VendorContactProjectService(db).attach(project_id, payload.contact_id, payload.category_ids, payload.note, actor)


@router.post("/{project_id}/vendor-contacts/{attachment_id}/end", response_model=VendorContactProjectOut)
def end_vendor_contact(
    project_id: uuid.UUID,
    attachment_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return VendorContactProjectService(db).end(project_id, attachment_id, actor)


@router.post("/{project_id}/vendors/{vendor_id}/remove", response_model=ProjectVendorOut)
def remove_project_vendor(
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    payload: ProjectVendorRemoveIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return ProjectVendorService(db).remove_vendor(project_id, vendor_id, actor, payload.reason)


@router.post("/{project_id}/tasks/{task_id}/vendor-assignment", response_model=TaskVendorAssignmentOut)
def assign_vendor_to_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskVendorAssignmentIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskVendorAssignmentService(db).assign_vendor(project_id, task_id, payload.vendor_id, actor, contact_id=payload.contact_id)


@router.get(
    "/{project_id}/tasks/{task_id}/vendor-assignments",
    response_model=list[TaskVendorAssignmentDetailOut],
)
def list_task_vendor_assignments(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Read surface for TaskVendorDelegationForm/VendorAcknowledgementForm -
    a task's vendor assignment(s) with full acknowledgement history, so the
    UI reflects the updated status immediately after a portal action (plan
    U3 frontend test scenario)."""
    project = get_project(db, project_id, actor)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id))
    if not task:
        raise HTTPException(404, "Task not found.")
    rows = db.execute(
        select(TaskVendorAssignment, V2Vendor, V2VendorContact)
        .join(V2Vendor, TaskVendorAssignment.vendor_id == V2Vendor.id)
        .outerjoin(V2VendorContact, TaskVendorAssignment.contact_id == V2VendorContact.id)
        .where(TaskVendorAssignment.task_id == task.id)
        .order_by(TaskVendorAssignment.created_at.desc())
    ).all()
    return [
        TaskVendorAssignmentDetailOut(
            id=assignment.id,
            task_id=assignment.task_id,
            project_id=assignment.project_id,
            vendor_id=assignment.vendor_id,
            vendor_name=vendor.name,
            status=assignment.status,
            assigned_by=assignment.assigned_by,
            created_at=assignment.created_at,
            ends_at=assignment.ends_at,
            contact_id=contact.id if contact else None,
            contact_name=contact.name if contact else None,
            contact_phone=contact.phone if contact else None,
            contact_whatsapp=contact.whatsapp if contact else None,
            acknowledgements=[
                VendorAcknowledgementOut.model_validate(ack)
                for ack in db.scalars(
                    select(VendorAcknowledgement)
                    .where(VendorAcknowledgement.task_vendor_assignment_id == assignment.id)
                    .order_by(VendorAcknowledgement.created_at.asc())
                ).all()
            ],
        )
        for assignment, vendor, contact in rows
    ]


@router.put(
    "/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/contact",
    response_model=TaskVendorAssignmentOut,
)
def set_task_point_person(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: TaskVendorContactIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Change (or clear) which of the vendor's people handles this task."""
    return VendorContactProjectService(db).set_point_person(project_id, task_id, assignment_id, payload.contact_id, actor)


@router.post(
    "/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/unassign",
    response_model=TaskVendorAssignmentOut,
)
def unassign_task_vendor(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: TaskVendorUnassignIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return TaskVendorAssignmentService(db).unassign_vendor(project_id, task_id, assignment_id, actor, payload.reason)


@router.post(
    "/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/acknowledge",
    response_model=VendorAcknowledgementOut,
)
def acknowledge_vendor_assignment(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: VendorAcknowledgementIn,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return VendorAcknowledgementService(db).record_acknowledgement(
        project_id, task_id, assignment_id, payload.response, actor,
        channel=payload.channel, note=payload.note,
    )
