"""U5: blocker capture (BR-010).

`TaskBlockerService.create_blocker` and `.resolve_blocker` record and
resolve `TaskBlocker` rows against an execution-layer task. Blockers are an
independently queryable condition, not a lifecycle state: this service
NEVER calls `TaskLifecycleService.transition` and NEVER writes
`Task.lifecycle_status` - a task can be `in_progress` (or any other status)
with an unresolved blocker logged against it at the same time, per BR-010's
"blocked/delayed/overdue/no_update are separate conditions, not mutually
exclusive lifecycle states."

Access: any active project member (or admin/super_admin) may log a
blocker. Only the project's accountable Supervisor or PM (or an
admin/super_admin fallback) may resolve one - mirrors
`TaskVerificationService._require_verifier`'s BR-007 fallback pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskBlocker
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService


class TaskBlockerService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access ---------------------------------------------------------

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

    def _require_resolver(self, project: V2Project, actor: User) -> None:
        """Only the accountable Supervisor/PM, or an admin/super_admin
        fallback, may resolve a blocker (BR-007's Supervisor-unavailable
        hierarchy also covers this fallback)."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "site_supervisor" in roles or "project_manager" in roles:
            return
        raise HTTPException(
            403, "Only the project's Supervisor, PM, or an Admin can resolve a blocker.",
        )

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    # ---- create -----------------------------------------------------------

    def create_blocker(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        actor: User,
        type_: str,
        description: str,
        owner_employee_id: uuid.UUID | None = None,
    ) -> TaskBlocker:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        clean_type = (type_ or "").strip()
        clean_description = (description or "").strip()
        if not clean_type:
            raise HTTPException(422, "A blocker type is required.")
        if not clean_description:
            raise HTTPException(422, "A blocker description is required.")

        blocker = TaskBlocker(
            task_id=task.id,
            project_id=project.id,
            type=clean_type,
            description=clean_description,
            owner_employee_id=owner_employee_id,
            # recorded for every channel, so the
            # reporter is told when the blocker is resolved.
            reported_by=actor.id,
        )
        self.db.add(blocker)
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="task.blocker_created",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "blocker_id": str(blocker.id),
                "type": clean_type,
                "description": clean_description,
                "reported_by": str(actor.id),
            },
            idempotency_key=f"task:{task.id}:task.blocker_created:{blocker.id}",
        )

        self.db.commit()
        self.db.refresh(blocker)
        return blocker

    # ---- resolve -----------------------------------------------------------

    def resolve_blocker(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        blocker_id: uuid.UUID,
        actor: User,
    ) -> TaskBlocker:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)
        self._require_resolver(project, actor)

        blocker = self.db.scalar(
            select(TaskBlocker).where(TaskBlocker.id == blocker_id, TaskBlocker.task_id == task.id)
        )
        if not blocker:
            raise HTTPException(404, "Blocker not found for this task.")
        if blocker.resolved_at is not None:
            raise HTTPException(409, "This blocker has already been resolved.")

        blocker.resolved_at = datetime.now(timezone.utc)
        blocker.resolved_by = actor.id
        self.db.add(blocker)
        self.db.flush()

        OutboxService(self.db).emit(
            event_type="task.blocker_resolved",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "blocker_id": str(blocker.id),
                "resolved_by": str(actor.id),
                "reported_by": str(blocker.reported_by) if blocker.reported_by else None,
            },
            idempotency_key=f"task:{task.id}:task.blocker_resolved:{blocker.id}",
        )

        self.db.commit()
        self.db.refresh(blocker)
        return blocker
