"""Phase 2 U2: project-vendor mapping (R2).

`ProjectVendorService.map_vendor` records that a vendor is engaged on a
project. Only an `active` `V2Vendor` may be mapped; a `sub_vendor`
additionally requires its parent vendor to already have an active mapping to
the *same* project - a sub-vendor can never appear on a project its parent
hasn't also been mapped to.

Access: only the project's PM (or admin/super_admin fallback) may map a
vendor - mirrors `TaskApprovalService`'s `_require_access` + role-specific
gate pattern.

This module intentionally imports nothing from `app.services.task_lifecycle`
/ `app.services.task_verification` (Phase 1's accountability-resolution
services) - project-vendor mapping has no bearing on Supervisor
accountability (R2/R3).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2Vendor


class ProjectVendorService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access -----------------------------------------------------

    def _actor_project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if not employee:
            return set()
        rows = self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        return set(rows)

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return project
        if self._actor_project_roles(project_id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _require_pm(self, project: V2Project, actor: User) -> None:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "project_manager" in roles:
            return
        raise HTTPException(403, "Only the project's PM, or an Admin, can map a vendor to this project.")

    # ---- mapping ------------------------------------------------------

    def map_vendor(self, project_id: uuid.UUID, vendor_id: uuid.UUID, actor: User) -> ProjectVendor:
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)

        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")
        from app.services.vendor_blacklist import vendor_block_reason
        blocked = vendor_block_reason(self.db, vendor)
        if blocked:
            raise HTTPException(422, f"{blocked} It can't be mapped to a project.")

        existing = self.db.scalar(
            select(ProjectVendor).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == vendor.id,
                ProjectVendor.ends_at.is_(None),
            )
        )
        if existing:
            raise HTTPException(409, "This vendor is already mapped to this project.")

        if vendor.engagement_type == "sub_vendor":
            if vendor.parent_vendor_id is None:
                raise HTTPException(422, "This sub-vendor has no parent vendor configured.")
            parent_mapped = self.db.scalar(
                select(ProjectVendor.id).where(
                    ProjectVendor.project_id == project.id,
                    ProjectVendor.vendor_id == vendor.parent_vendor_id,
                    ProjectVendor.ends_at.is_(None),
                )
            )
            if not parent_mapped:
                raise HTTPException(
                    422, "This sub-vendor's parent vendor is not yet mapped to this project.",
                )

        mapping = ProjectVendor(project_id=project.id, vendor_id=vendor.id, mapped_by=actor.id)
        self.db.add(mapping)
        self.db.flush()

        # U3 (WhatsApp gate workflow): emit in the same transaction as the
        # mapping row itself, following U2's project.activated / assign_membership's
        # project.member_added discipline - a later rollback in this same
        # commit would take the event with it. Keyed on the mapping's own id
        # since a project can be mapped to many vendors over time.
        #
        # Gated to Active projects only, same rule and same reason as
        # `assign_membership`'s `project.member_added` guard: this event
        # fans out to every current project member plus every mapped
        # vendor (`_ALL_MEMBERS_PROJECT_EVENTS`), and a Draft project's
        # vendor mapping is planning, not something the execution team
        # should be notified about yet.
        if project.status == "active":
            OutboxService(self.db).emit(
                event_type="project.vendor_mapped",
                aggregate_type="project",
                aggregate_id=project.id,
                payload={"project_id": str(project.id), "vendor_id": str(vendor.id)},
                idempotency_key=f"project:{project.id}:project.vendor_mapped:{mapping.id}",
            )

        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    # ---- removal ------------------------------------------------------

    def remove_vendor(self, project_id: uuid.UUID, vendor_id: uuid.UUID, actor: User, reason: str) -> ProjectVendor:
        """Soft-removes a vendor from a project: ends its `ProjectVendor`
        mapping and every currently-active `TaskVendorAssignment` it holds
        on this project. Nothing is deleted - acknowledgements, evidence,
        and every prior audit event stay exactly as they were, and this
        vendor can be re-mapped to the project later (the DB-level active-
        only unique index allows it once `ends_at` is set here).

        Blocks removing a `main` vendor while any of its sub-vendors still
        hold an active mapping on this same project (mirrors `map_vendor`'s
        mapping-time invariant in reverse) - deliberately not cascaded, so
        removing one company never silently removes others.
        """
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)

        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")

        mapping = self.db.scalar(
            select(ProjectVendor).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == vendor.id,
                ProjectVendor.ends_at.is_(None),
            )
        )
        if not mapping:
            raise HTTPException(404, "This vendor is not actively mapped to this project.")

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A reason is required to remove a vendor from a project.")

        if vendor.engagement_type == "main":
            active_sub_vendor_count = len(self.db.scalars(
                select(ProjectVendor.id)
                .join(V2Vendor, V2Vendor.id == ProjectVendor.vendor_id)
                .where(
                    ProjectVendor.project_id == project.id,
                    ProjectVendor.ends_at.is_(None),
                    V2Vendor.parent_vendor_id == vendor.id,
                )
            ).all())
            if active_sub_vendor_count:
                noun = "sub-vendor" if active_sub_vendor_count == 1 else "sub-vendors"
                raise HTTPException(
                    409,
                    f"This vendor has {active_sub_vendor_count} active {noun} on this project. "
                    "Remove them first.",
                )

        now = datetime.now(timezone.utc)
        mapping.ends_at = now

        active_assignments = self.db.scalars(
            select(TaskVendorAssignment).where(
                TaskVendorAssignment.project_id == project.id,
                TaskVendorAssignment.vendor_id == vendor.id,
                TaskVendorAssignment.ends_at.is_(None),
            )
        ).all()
        for assignment in active_assignments:
            assignment.ends_at = now
            self.db.add(V2AuditEvent(
                actor_user_id=actor.id,
                action="VENDOR_TASK_UNASSIGNED",
                entity_type="task_vendor_assignment",
                entity_id=assignment.id,
                project_id=project.id,
                before_json={"vendor_id": str(vendor.id), "task_id": str(assignment.task_id), "ends_at": None},
                after_json={"vendor_id": str(vendor.id), "task_id": str(assignment.task_id), "ends_at": now.isoformat()},
                reason=f"Ended due to project-level vendor removal: {clean_reason}",
            ))

        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="VENDOR_REMOVED_FROM_PROJECT",
            entity_type="project_vendor",
            entity_id=mapping.id,
            project_id=project.id,
            before_json={"vendor_id": str(vendor.id), "ends_at": None},
            after_json={"vendor_id": str(vendor.id), "ends_at": now.isoformat()},
            reason=clean_reason,
        ))

        if project.status == "active":
            OutboxService(self.db).emit(
                event_type="project.vendor_removed",
                aggregate_type="project",
                aggregate_id=project.id,
                payload={"project_id": str(project.id), "vendor_id": str(vendor.id), "reason": clean_reason},
                idempotency_key=f"project:{project.id}:project.vendor_removed:{mapping.id}",
            )

        self.db.commit()
        self.db.refresh(mapping)
        return mapping
