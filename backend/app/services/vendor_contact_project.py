"""Vendor people on projects and tasks.

`VendorContactProjectService` attaches a vendor contact (a person under a
main vendor or sub-vendor) to a project, optionally per trade category, and
sets the point person on a task delegated to their vendor. Neither touches
the vendor's project mapping or task delegation itself - they only record
which of the vendor's people is doing the work, so the team can reach that
person directly and task messages reach them (see
`MessageDispatchService._vendor_task_recipients`).

Who may do it: Super Admin/Admin anywhere; a Project Manager or Supervisor
only on projects they are an active member of.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import User, UserRole
from app.project_models import V2AuditEvent, V2Project
from app.routes.projects_v2 import has_membership
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorContact,
    VendorContactProject,
)

ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}
MEMBER_MANAGER_ROLES = {UserRole.project_manager, UserRole.supervisor}


class VendorContactProjectService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access ---------------------------------------------------------

    def _require_manager(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in ADMIN_ROLES:
            return project
        if actor.role in MEMBER_MANAGER_ROLES and has_membership(self.db, project.id, actor):
            return project
        raise HTTPException(403, "Only an Admin, or a PM or Supervisor on this project, can change who works on it.")

    def _vendor_on_project(self, vendor: V2Vendor, project_id: uuid.UUID) -> bool:
        """The contact's vendor is actively mapped to the project - or, for a
        sub-vendor, its parent is (the same inherited visibility Vendor Hub
        shows on a sub-vendor's Projects tab)."""
        vendor_ids = [vendor.id] + ([vendor.parent_vendor_id] if vendor.parent_vendor_id else [])
        return self.db.scalar(
            select(ProjectVendor.id).where(
                ProjectVendor.project_id == project_id,
                ProjectVendor.vendor_id.in_(vendor_ids),
                ProjectVendor.ends_at.is_(None),
            ).limit(1)
        ) is not None

    def _audit(self, actor: User, project_id: uuid.UUID, action: str, entity_type: str, entity_id: uuid.UUID, reason: str, before=None, after=None) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id, action=action, entity_type=entity_type, entity_id=entity_id,
            project_id=project_id, before_json=before, after_json=after, reason=reason,
        ))

    # ---- project attachments -------------------------------------------

    def attach(self, project_id: uuid.UUID, contact_id: uuid.UUID, category_ids: list[uuid.UUID], note: str | None, actor: User) -> list[VendorContactProject]:
        project = self._require_manager(project_id, actor)
        contact = self.db.get(V2VendorContact, contact_id)
        if not contact:
            raise HTTPException(404, "Contact not found.")
        vendor = self.db.get(V2Vendor, contact.vendor_id)
        if not vendor or not self._vendor_on_project(vendor, project.id):
            raise HTTPException(422, "This person's vendor is not mapped to this project. Map the vendor to the project first.")

        wanted: list[uuid.UUID | None] = list(dict.fromkeys(category_ids)) or [None]
        for category_id in wanted:
            if category_id is not None and not self.db.get(V2CapabilityCategory, category_id):
                raise HTTPException(400, "One or more categories are invalid.")

        active = self.db.scalars(
            select(VendorContactProject).where(
                VendorContactProject.contact_id == contact.id,
                VendorContactProject.project_id == project.id,
                VendorContactProject.ends_at.is_(None),
            )
        ).all()
        existing = {row.category_id for row in active}
        clean_note = (note or "").strip() or None
        created: list[VendorContactProject] = []
        for category_id in wanted:
            if category_id in existing:
                continue
            row = VendorContactProject(
                contact_id=contact.id, project_id=project.id, category_id=category_id,
                note=clean_note, assigned_by=actor.id,
            )
            self.db.add(row)
            created.append(row)
        self.db.flush()
        for row in created:
            self._audit(actor, project.id, "VENDOR_CONTACT_ATTACHED", "vendor_contact_project", row.id,
                        "Vendor contact attached to project", None,
                        {"contact_id": str(contact.id), "category_id": str(row.category_id) if row.category_id else None})
        self.db.commit()
        return self.db.scalars(
            select(VendorContactProject).where(
                VendorContactProject.contact_id == contact.id,
                VendorContactProject.project_id == project.id,
                VendorContactProject.ends_at.is_(None),
            )
        ).all()

    def end(self, project_id: uuid.UUID, attachment_id: uuid.UUID, actor: User) -> VendorContactProject:
        project = self._require_manager(project_id, actor)
        row = self.db.get(VendorContactProject, attachment_id)
        if not row or row.project_id != project.id or row.ends_at is not None:
            raise HTTPException(404, "Active attachment not found on this project.")
        now = datetime.now(timezone.utc)
        row.ends_at = now
        self._audit(actor, project.id, "VENDOR_CONTACT_DETACHED", "vendor_contact_project", row.id,
                    "Vendor contact removed from project", {"ends_at": None}, {"ends_at": now.isoformat()})
        self.db.commit()
        self.db.refresh(row)
        return row

    # ---- task point person ----------------------------------------------

    def require_contact_of_vendor(self, contact_id: uuid.UUID | None, vendor_id: uuid.UUID) -> V2VendorContact | None:
        if contact_id is None:
            return None
        contact = self.db.get(V2VendorContact, contact_id)
        if not contact or contact.vendor_id != vendor_id:
            raise HTTPException(422, "The point person must be one of this vendor's contacts.")
        return contact

    def set_point_person(self, project_id: uuid.UUID, task_id: uuid.UUID, assignment_id: uuid.UUID, contact_id: uuid.UUID | None, actor: User) -> TaskVendorAssignment:
        project = self._require_manager(project_id, actor)
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id))
        if not task:
            raise HTTPException(404, "Task not found.")
        assignment = self.db.scalar(
            select(TaskVendorAssignment).where(
                TaskVendorAssignment.id == assignment_id,
                TaskVendorAssignment.task_id == task.id,
                TaskVendorAssignment.ends_at.is_(None),
            )
        )
        if not assignment:
            raise HTTPException(404, "Active vendor assignment not found for this task.")
        self.require_contact_of_vendor(contact_id, assignment.vendor_id)
        before = str(assignment.contact_id) if assignment.contact_id else None
        assignment.contact_id = contact_id
        self._audit(actor, project.id, "VENDOR_TASK_POINT_PERSON_SET", "task_vendor_assignment", assignment.id,
                    "Task point person changed", {"contact_id": before},
                    {"contact_id": str(contact_id) if contact_id else None})
        self.db.commit()
        self.db.refresh(assignment)
        return assignment
