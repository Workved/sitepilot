"""Phase 2 U2: task vendor delegation (R3).

`TaskVendorAssignmentService.assign_vendor` delegates an execution-layer
task to a vendor already mapped to the task's project
(`app.services.project_vendor.ProjectVendorService`), without transferring
Site Supervisor accountability. `Task.lifecycle_status` is never read for
gating purposes here (beyond loading the row) and never written by this
service - a vendor assignment is a separate concept from BR-009's lifecycle
transitions and BR-008/BR-011's dependency-blocking checks.

This module deliberately imports nothing from `app.services.task_lifecycle`,
`app.services.task_verification`, or any other Phase 1 accountability/
dependency-resolution service - that is how non-interference with the
accountable-Supervisor derivation (R3) is proven structurally, not just by a
passing test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2CapabilityCategory, V2Vendor, V2VendorCapability


class TaskVendorAssignmentService:
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
        raise HTTPException(403, "Only the project's PM, or an Admin, can delegate a task to a vendor.")

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    # ---- capability matching -------------------------------------------

    def _vendor_matches_task_category(self, vendor_id: uuid.UUID, task: Task) -> bool:
        """R3/plan Approach: a null `Task.phase` carries no capability
        requirement, so any mapped vendor may be assigned. Otherwise the
        vendor must hold a `V2VendorCapability` whose category `name`
        case-insensitively equals the task's PHASE (not its finer-grained
        `category`).

        Matching against `phase` rather than `category` is deliberate: a
        vendor's capability categories are a small set of broad trade
        buckets (the same vocabulary `_ensure_phase_categories` in
        project_vendors_v2.py seeds from template phases - "Partitions",
        "Electrical", "Glass", etc.), while `Task.category` is a much finer
        breakdown within a phase (e.g. "Gypsum", "Interior", "Supports" are
        all `category` values under the "Partitions" phase). Matching on
        `category` would require a vendor capability literally named
        "Gypsum" to exist, which no vendor taxonomy in this system defines -
        every delegation would 422 regardless of how a vendor's
        capabilities were set. Phase is the granularity vendor capabilities
        are actually scoped at.
        """
        phase = (task.phase or "").strip()
        if not phase:
            return True
        match = self.db.scalar(
            select(V2VendorCapability.id)
            .join(V2CapabilityCategory, V2VendorCapability.category_id == V2CapabilityCategory.id)
            .where(
                V2VendorCapability.vendor_id == vendor_id,
                func.lower(V2CapabilityCategory.name) == phase.lower(),
            )
        )
        return match is not None

    # ---- assignment ------------------------------------------------------

    def assign_vendor(
        self, project_id: uuid.UUID, task_id: uuid.UUID, vendor_id: uuid.UUID, actor: User,
        contact_id: uuid.UUID | None = None,
    ) -> TaskVendorAssignment:
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)
        task = self._get_task(project.id, task_id)

        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")
        if vendor.status != "active":
            raise HTTPException(422, "Only an active vendor can be assigned to a task.")

        mapped = self.db.scalar(
            select(ProjectVendor.id).where(
                ProjectVendor.project_id == project.id,
                ProjectVendor.vendor_id == vendor.id,
                ProjectVendor.ends_at.is_(None),
            )
        )
        if not mapped:
            raise HTTPException(422, "This vendor is not mapped to this project.")

        if not self._vendor_matches_task_category(vendor.id, task):
            phase_label = (task.phase or "").strip() or "this task's phase"
            raise HTTPException(422, f"This vendor's trade phase does not cover \"{phase_label}\".")

        # Imported here, not at module top: that module imports from
        # app.routes.projects_v2, and this one must stay importable on its own.
        from app.services.vendor_contact_project import VendorContactProjectService
        VendorContactProjectService(self.db).require_contact_of_vendor(contact_id, vendor.id)

        assignment = TaskVendorAssignment(
            task_id=task.id,
            project_id=project.id,
            vendor_id=vendor.id,
            status="pending_ack",
            assigned_by=actor.id,
            contact_id=contact_id,
        )
        self.db.add(assignment)
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="task.vendor_assigned",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "assignment_id": str(assignment.id),
                "vendor_id": str(vendor.id),
                "contact_id": str(contact_id) if contact_id else None,
            },
            idempotency_key=f"task:{task.id}:task.vendor_assigned:{assignment.id}",
        )

        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    # ---- unassignment ---------------------------------------------------

    def unassign_vendor(
        self, project_id: uuid.UUID, task_id: uuid.UUID, assignment_id: uuid.UUID, actor: User, reason: str,
    ) -> TaskVendorAssignment:
        """Soft-ends one `TaskVendorAssignment` (`ends_at`), leaving the
        vendor's project mapping and every acknowledgement against this
        assignment untouched - pulling a vendor off one task never affects
        their standing on the rest of the project (see `remove_vendor` in
        `project_vendor.py` for the whole-project action)."""
        project = self._require_access(project_id, actor)
        self._require_pm(project, actor)
        task = self._get_task(project.id, task_id)

        assignment = self.db.scalar(
            select(TaskVendorAssignment).where(
                TaskVendorAssignment.id == assignment_id,
                TaskVendorAssignment.task_id == task.id,
                TaskVendorAssignment.project_id == project.id,
            )
        )
        if not assignment or assignment.ends_at is not None:
            raise HTTPException(404, "Active vendor assignment not found for this task.")

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A reason is required to unassign a vendor from a task.")

        now = datetime.now(timezone.utc)
        assignment.ends_at = now

        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="VENDOR_TASK_UNASSIGNED",
            entity_type="task_vendor_assignment",
            entity_id=assignment.id,
            project_id=project.id,
            before_json={"vendor_id": str(assignment.vendor_id), "task_id": str(task.id), "ends_at": None},
            after_json={"vendor_id": str(assignment.vendor_id), "task_id": str(task.id), "ends_at": now.isoformat()},
            reason=clean_reason,
        ))

        if project.status == "active":
            OutboxService(self.db).emit(
                event_type="task.vendor_unassigned",
                aggregate_type="task",
                aggregate_id=task.id,
                payload={
                    "task_id": str(task.id),
                    "project_id": str(project.id),
                    "assignment_id": str(assignment.id),
                    "vendor_id": str(assignment.vendor_id),
                    "reason": clean_reason,
                },
                idempotency_key=f"task:{task.id}:task.vendor_unassigned:{assignment.id}",
            )

        self.db.commit()
        self.db.refresh(assignment)
        return assignment
