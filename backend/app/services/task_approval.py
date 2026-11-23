"""U4: PM approval decisions (BR-008).

`TaskApprovalService.approve` records a `TaskApprovalDecision` against a
task and drives `Task.lifecycle_status` forward (or back) via U2's
`TaskLifecycleService`:

- `class_a` work: requires the task to currently be `verified` (i.e. a
  prior `TaskVerificationService.verify` call with `decision == 'verified'`
  and no later rejection - checked explicitly against `TaskVerification`,
  not just trusting `lifecycle_status`). On approve: `verified ->
  approval_pending -> completed`. `verification_id` on the recorded
  decision is populated from that verification.
- `approval_gate`: no verification prerequisite - `approval_gate` tasks
  skip Supervisor verification entirely per BR-008. Requires the task to
  currently be `submitted`. On approve: `submitted -> approval_pending ->
  completed`. `verification_id` is null.
- `rejected` (either kind): requires a correction reason (`remarks`) and
  transitions the task back to `in_progress`, per BR-009's literal
  transition table (`verified -> approval_pending` is never entered on
  rejection; BR-009 also allows a direct `submitted -> approval_pending`
  or `verified -> approval_pending` before landing on `rejected` - this
  service transitions straight to `approval_pending` then `rejected` so
  the intermediate state is recorded, matching the same two-step shape
  used for `verified -> approval_pending -> completed`).

Same-actor restriction (BR-008's "the fallback verifier may not also be
the approver of record for the same decision cycle"): if the most recent
`TaskVerification` for this task was recorded by a PM acting as a
fallback verifier (i.e. the verifying user is not the project's active
Supervisor), that same user may not also record this task's approval
decision - a different authorized actor (a different PM, or Admin/Super
Admin) must approve.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskApprovalDecision, TaskVerification, is_work_task_kind
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.services.task_lifecycle import TaskLifecycleService

APPROVAL_DECISIONS = ("approved", "rejected")


class TaskApprovalService:
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

    def _require_approver(self, project: V2Project, actor: User) -> None:
        """BR-008: the PM approves class_a work and every approval_gate, or
        Admin stands in as the audited fallback (BR-007's PM-unavailable
        hierarchy)."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)
        if "project_manager" in roles:
            return
        raise HTTPException(
            403, "Only the project's PM, or an authorized Admin fallback, can approve this task.",
        )

    def _has_active_pm(self, project_id: uuid.UUID) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == "project_manager",
                V2ProjectMembership.ends_at.is_(None),
            )
        ) is not None

    def _decision_mode(self, project: V2Project, actor: User) -> str:
        """Distinguishes a genuine BR-007 fallback from an Admin override,
        which `_require_approver` alone cannot: it lets Admin/Super Admin
        through unconditionally with no record of whether a PM was actually
        unavailable. See the migration adding this column."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return "admin_fallback" if not self._has_active_pm(project.id) else "admin_override"
        return "role_normal"

    def _get_task(self, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if not task:
            raise HTTPException(404, "Task not found.")
        return task

    def _current_verification(self, task_id: uuid.UUID) -> TaskVerification | None:
        """Most recent TaskVerification for this task, i.e. the current
        decision cycle's verification record (if any)."""
        return self.db.scalar(
            select(TaskVerification)
            .where(TaskVerification.task_id == task_id)
            .order_by(TaskVerification.verified_at.desc(), TaskVerification.id.desc())
            .limit(1)
        )

    def _is_active_supervisor(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id).join(
                EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id,
            ).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == "site_supervisor",
                V2ProjectMembership.ends_at.is_(None),
                EmployeeProfile.user_id == user_id,
            )
        ) is not None

    def ineligible_approver_user_id(self, task: Task) -> uuid.UUID | None:
        """Read-only: the one person who may not
        approve this task's current cycle - a class_a verification recorded by
        someone who is not the project's active Supervisor (a PM or Admin
        fallback). Exactly the actor `_require_not_same_fallback_actor` refuses;
        None when nobody is excluded."""
        if task.task_kind == "approval_gate" or task.task_class != "class_a":
            return None
        verification = self._current_verification(task.id)
        if verification is None or verification.decision != "verified":
            return None
        if self._is_active_supervisor(task.project_id, verification.verified_by):
            return None
        return verification.verified_by

    def eligible_pm_user_ids(self, task: Task) -> list[uuid.UUID]:
        """Read-only: active PMs of the project who may approve this cycle
        (the fallback verifier excluded)."""
        excluded = self.ineligible_approver_user_id(task)
        rows = self.db.scalars(
            select(User.id)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .join(V2ProjectMembership, V2ProjectMembership.employee_id == EmployeeProfile.id)
            .where(
                V2ProjectMembership.project_id == task.project_id,
                V2ProjectMembership.project_role == "project_manager",
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
            )
        ).all()
        return [user_id for user_id in rows if user_id != excluded]

    def has_eligible_admin(self, task: Task) -> bool:
        """Read-only: an active Admin/Super Admin other than the fallback
        verifier, who could approve this cycle."""
        excluded = self.ineligible_approver_user_id(task)
        query = select(User.id).where(User.role.in_((UserRole.admin, UserRole.super_admin)), User.active.is_(True))
        if excluded is not None:
            query = query.where(User.id != excluded)
        return self.db.scalar(query.limit(1)) is not None

    def _require_not_same_fallback_actor(self, project: V2Project, verification: TaskVerification | None, actor: User) -> None:
        """BR-008: if the verification on record was made by a PM acting as
        a fallback verifier (not the project's active Supervisor), that
        same person may not also record the approval decision."""
        if verification is None:
            return
        if verification.verified_by == actor.id and not self._is_active_supervisor(project.id, verification.verified_by):
            raise HTTPException(
                409,
                "The actor who verified this task as a fallback for the Supervisor cannot also record its "
                "approval decision - a different authorized PM/Admin must approve.",
            )

    # ---- approve ------------------------------------------------------

    def approve(
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

        if decision not in APPROVAL_DECISIONS:
            raise HTTPException(422, "Approval decision must be 'approved' or 'rejected'.")

        clean_remarks = (remarks or "").strip() or None
        if decision == "rejected" and not clean_remarks:
            raise HTTPException(422, "A correction reason is required to reject a task.")

        self._require_approver(project, actor)
        decision_mode = self._decision_mode(project, actor)

        verification: TaskVerification | None = None
        if task.task_kind == "approval_gate":
            if task.lifecycle_status != "submitted":
                raise HTTPException(409, "An approval gate must be submitted before it can be approved.")
        elif is_work_task_kind(task.task_kind) and task.task_class == "class_a":
            if task.lifecycle_status != "verified":
                raise HTTPException(
                    409, "Class A work must be Supervisor-verified before it can be PM-approved.",
                )
            verification = self._current_verification(task.id)
            if verification is None or verification.decision != "verified":
                raise HTTPException(
                    409, "Class A work requires a current 'verified' verification record before PM approval.",
                )
            self._require_not_same_fallback_actor(project, verification, actor)
        else:
            raise HTTPException(
                409, "Only approval gates and Class A work tasks go through PM approval.",
            )

        approval_decision = TaskApprovalDecision(
            task_id=task.id,
            verification_id=verification.id if verification else None,
            decision=decision,
            remarks=clean_remarks,
            decided_by=actor.id,
            decision_mode=decision_mode,
        )
        self.db.add(approval_decision)
        self.db.flush()
        self.lifecycle.mark_progress_reviewed(task.id)

        # Same transaction-boundary trap as TaskVerificationService.verify:
        # must be emitted BEFORE the first self.lifecycle.transition(...)
        # call below, since that call commits on its own and this method
        # may invoke it up to three times in sequence.
        OutboxService(self.db).emit(
            event_type="task.approval_recorded",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "decision": decision,
                "remarks": clean_remarks,
                "decided_by": str(actor.id),
                "verification_id": str(verification.id) if verification else None,
                "decision_mode": decision_mode,
            },
            # One event per decision row, so each PM rejection in a rework
            # loop notifies (see transition()'s status_changed key).
            idempotency_key=f"task:{task.id}:task.approval_recorded:{decision}:{approval_decision.id}",
        )

        if decision == "rejected":
            if task.lifecycle_status != "approval_pending":
                task = self.lifecycle.transition(
                    project.id, task.id, "approval_pending", actor,
                    reason=clean_remarks, _via_decision_service=True, source=source,
                )
            task = self.lifecycle.transition(
                project.id, task.id, "rejected", actor, reason=clean_remarks, _via_decision_service=True, source=source,
            )
            return self.lifecycle.transition(
                project.id, task.id, "in_progress", actor, reason=clean_remarks, _via_decision_service=True, source=source,
            )

        task = self.lifecycle.transition(
            project.id, task.id, "approval_pending", actor,
            reason=clean_remarks or "Awaiting PM approval.",
            _via_decision_service=True, source=source,
        )
        return self.lifecycle.transition(
            project.id, task.id, "completed", actor,
            reason=clean_remarks or "Approved by PM.",
            _via_decision_service=True, source=source,
        )
