"""U4: Supervisor verification decisions (BR-008).

`TaskVerificationService.verify` records a `TaskVerification` decision
against a `work` task's most recent submitted progress update, then drives
`Task.lifecycle_status` forward (or back) via U2's `TaskLifecycleService`:

- `decision == 'verified'`: `submitted -> verified`; if the task is
  `standard` class, immediately also `verified -> completed` (standard
  work needs no PM step per BR-008). `class_a` work stops at `verified`,
  awaiting a later `TaskApprovalService.approve` call.
- `decision == 'rejected'`: `submitted -> rejected -> in_progress`, per
  BR-009's literal transition table - the task reopens under Supervisor
  accountability. A correction reason (`remarks`) is required.

`approval_gate` tasks never go through this service - BR-008 says gates
skip Supervisor verification entirely; they go straight to
`TaskApprovalService`.

Verifier resolution: the project's active Supervisor, or an audited PM/
Admin fallback (BR-007's "if a Supervisor is unavailable, the project PM
replaces or temporarily assigns the Supervisor" plus Admin's general
fallback authority). `TaskApprovalService` is responsible for refusing to
let that same fallback actor also record the task's approval decision.

Self-verification: no role rule authorizes the actor who submitted a
task's most recent progress update to also verify it - not even a
Supervisor who executed the task themselves because no Internal Employee
was assigned. Admin/Super Admin are exempt, matching their blanket
override elsewhere in this service.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskProgressUpdate, TaskVerification, is_work_task_kind
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.services.task_lifecycle import TaskLifecycleService, latest_submitter_user_id

VERIFICATION_DECISIONS = ("verified", "rejected")


class TaskVerificationService:
    def __init__(self, db: Session):
        self.db = db
        self.lifecycle = TaskLifecycleService(db)

    # ---- access / role resolution -----------------------------------

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

    def _require_verifier(self, project: V2Project, actor: User) -> None:
        """BR-008: the Supervisor verifies work, or an audited PM/Admin
        fallback stands in (BR-007's Supervisor-unavailable hierarchy)."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "site_supervisor" in roles or "project_manager" in roles:
            return
        raise HTTPException(
            403, "Only the project's Supervisor, or an authorized PM/Admin fallback, can verify work.",
        )

    def _has_active_supervisor(self, project_id: uuid.UUID) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == "site_supervisor",
                V2ProjectMembership.ends_at.is_(None),
            )
        ) is not None

    def _decision_mode(self, project: V2Project, actor: User, roles: set[str]) -> str:
        """Distinguishes a genuine BR-007 fallback from an Admin override,
        which `_require_verifier` alone cannot: it lets Admin/Super Admin
        through unconditionally with no record of whether a Supervisor was
        actually unavailable. See the migration adding this column."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return "admin_fallback" if not self._has_active_supervisor(project.id) else "admin_override"
        if "project_manager" in roles and "site_supervisor" not in roles:
            return "pm_fallback"
        return "role_normal"

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    def _latest_submission(self, task_id: uuid.UUID) -> TaskProgressUpdate | None:
        return self.db.scalar(
            select(TaskProgressUpdate)
            .where(TaskProgressUpdate.task_id == task_id)
            .order_by(TaskProgressUpdate.created_at.desc(), TaskProgressUpdate.id.desc())
            .limit(1)
        )

    # ---- verify -----------------------------------------------------------

    def verify(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        decision: str,
        actor: User,
        remarks: str | None = None,
        source: str = "portal",
    ) -> Task:
        project = self._require_access(project_id, actor)
        task = self._get_task(project.id, task_id)

        if not is_work_task_kind(task.task_kind):
            raise HTTPException(
                409, "Only work tasks go through Supervisor verification; approval gates go straight to PM approval.",
            )
        if task.lifecycle_status != "submitted":
            raise HTTPException(409, "A task must be submitted before it can be verified.")
        if decision not in VERIFICATION_DECISIONS:
            raise HTTPException(422, "Verification decision must be 'verified' or 'rejected'.")

        clean_remarks = (remarks or "").strip() or None
        if decision == "rejected" and not clean_remarks:
            raise HTTPException(422, "A correction reason is required to reject a task.")

        self._require_verifier(project, actor)
        decision_mode = self._decision_mode(project, actor, self._actor_project_roles(project.id, actor))

        submission = self._latest_submission(task.id)
        if submission is None:
            raise HTTPException(409, "This task has no pending progress submission to verify.")

        # No role rule explicitly authorizes self-verification - the actor
        # who submitted this progress update may not also verify it, even
        # if they otherwise qualify as verifier (e.g. a Supervisor who
        # executed the task themselves because no Internal Employee was
        # assigned). Admin/Super Admin retain their blanket override, same
        # as every other role check in this service.
        if submission.submitted_by == actor.id and actor.role not in (UserRole.super_admin, UserRole.admin):
            raise HTTPException(
                409, "You submitted this task's progress - a different Supervisor, PM, or Admin must verify it.",
            )

        verification = TaskVerification(
            task_id=task.id,
            submission_update_id=submission.id,
            decision=decision,
            remarks=clean_remarks,
            verified_by=actor.id,
            decision_mode=decision_mode,
        )
        self.db.add(verification)
        self.db.flush()
        # The submission this decision covers, captured before the cycle is
        # marked reviewed, so the class_a approval request that follows shows
        # exactly the verified work.
        reviewed_update_ids = [str(i) for i in self.db.scalars(
            select(TaskProgressUpdate.id)
            .where(TaskProgressUpdate.task_id == task.id, TaskProgressUpdate.reviewed_at.is_(None))
            .order_by(TaskProgressUpdate.created_at, TaskProgressUpdate.id)
        )]
        self.lifecycle.mark_progress_reviewed(task.id)

        # Emitted here - BEFORE the first `self.lifecycle.transition(...)`
        # call below - because `TaskLifecycleService.transition` commits at
        # the end of each of its own calls, and this method calls it one or
        # two times in sequence. Emitting after any transition() call would
        # put this event in a transaction that already closed with the
        # TaskVerification row, breaking the same-transaction guarantee.
        # Placed here, it rides inside the same open transaction that the
        # FIRST transition() call's commit closes, so the TaskVerification
        # row and this outbox event commit atomically together.
        OutboxService(self.db).emit(
            event_type="task.verification_recorded",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "decision": decision,
                "remarks": clean_remarks,
                "verified_by": str(actor.id),
                "decision_mode": decision_mode,
                "verification_id": str(verification.id),
                "submitted_by": str(latest_submitter_user_id(self.db, task.id) or ""),
                "progress_update_ids": reviewed_update_ids,
            },
            # One event per decision row: a task rejected in two cycles
            # must notify twice (see transition()'s status_changed key).
            idempotency_key=f"task:{task.id}:task.verification_recorded:{decision}:{verification.id}",
        )

        if decision == "rejected":
            task = self.lifecycle.transition(
                project.id, task.id, "rejected", actor, reason=clean_remarks, _via_decision_service=True, source=source,
            )
            return self.lifecycle.transition(
                project.id, task.id, "in_progress", actor, reason=clean_remarks, _via_decision_service=True, source=source,
            )

        task = self.lifecycle.transition(
            project.id, task.id, "verified", actor,
            reason=clean_remarks or "Verified by Supervisor.",
            _via_decision_service=True, source=source,
        )
        # `task_class` is nullable, same as `task_kind` - only an explicit
        # "class_a" requires the extra PM approval step (BR-008). A task
        # with no class assigned must still complete here: task_approval.py
        # only accepts a PM decision for task_class == "class_a" exactly,
        # so leaving this branch keyed on "== standard" would strand any
        # unclassified task at `verified` forever, with no PM mechanism
        # able to move it forward (that was a real bug, not intentional
        # Class A behavior).
        if task.task_class != "class_a":
            task = self.lifecycle.transition(
                project.id, task.id, "completed", actor,
                reason="Standard work completes automatically after Supervisor verification (BR-008).",
                _via_decision_service=True, source=source,
            )
        return task
