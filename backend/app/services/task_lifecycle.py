"""U2: Task lifecycle state machine (BR-009).

`TaskLifecycleService.transition` is the single authority for moving a
`Task.lifecycle_status` from one state to another. It encodes BR-009's exact
transition table as an explicit allow-list (nothing inferred), gates
`ready`/`in_progress` on an active project Supervisor (BR-004) and on
predecessor-dependency satisfaction (BR-011/BR-008), auto-completes
successor milestones as a side effect, and writes a `V2AuditEvent` for every
transition.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import (
    TASK_LIFECYCLE_STATUSES,
    Task,
    TaskDependency,
    TaskEvidence,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
    is_work_task_kind,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService


# BR-009's canonical transition table, as an explicit allow-list:
#   planned -> ready -> in_progress -> submitted -> verified -> completed
#   submitted -> rejected -> in_progress (rejected work reopens)
#   verified -> approval_pending -> completed (Class A work, pending PM approval)
#   submitted -> approval_pending -> completed (approval gates skip Supervisor
#       verification per BR-008)
#   approval_pending -> rejected -> in_progress
#   planned -> completed (system-derived milestone auto-completion only)
#   any non-terminal state -> cancelled (authorized override, reason required)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"ready", "completed", "cancelled"},
    "ready": {"in_progress", "cancelled"},
    "in_progress": {"submitted", "cancelled"},
    "submitted": {"verified", "approval_pending", "rejected", "cancelled"},
    "verified": {"approval_pending", "completed", "cancelled"},
    "approval_pending": {"completed", "rejected", "cancelled"},
    "rejected": {"in_progress", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

# Targets whose decision record (TaskVerification/TaskApprovalDecision) is
# owned by U4's TaskVerificationService/TaskApprovalService - a direct call
# to this raw transition() would move lifecycle_status without writing that
# record, silently breaking the dependency-satisfaction checks below (which
# key off the TaskVerification row, not the status alone) and letting
# class_a/approval_gate work skip PM approval entirely. Reachable only with
# `_via_decision_service=True` (see transition()).
_DECISION_SERVICE_ONLY_TARGETS = {"verified", "approval_pending", "rejected"}

# Transitions a Supervisor (or PM, or Admin/Super Admin) may drive
# unconditionally: scheduling (`ready`) and reopening after rejection.
# `ready` is additionally open to the task's actively assigned Internal
# Employee (see `_require_role_for_transition`).
_SUPERVISOR_OR_PM_TARGETS = {"ready", "rejected", "verified", "approval_pending", "completed"}

# `in_progress` ("start") and `submitted` ("submit completion") are driven
# by whoever is actually doing the work: the assigned Internal Employee if
# one is actively support-assigned to the task, otherwise the Supervisor/PM
# (BR: "Supervisor may start, execute and submit completion only when no
# Internal Employee is assigned to the task").
_EXECUTOR_DRIVEN_TARGETS = {"in_progress", "submitted"}

# A predecessor counts as "started" for a `start_to_start` edge once it has
# left the pre-start statuses (`planned`, `ready`). Everything from
# `in_progress` onward means work actually began, including states the task
# later moved through - a task that reached `submitted` and was rejected has
# still started, so its start-to-start successors stay released.
_STARTED_STATUSES = {
    "in_progress", "submitted", "verified", "approval_pending", "rejected", "completed",
}


class EarlyStartReasonRequired(HTTPException):
    """Starting before the planned start date without a reason. The same 422
    and message the Web App has always shown; a distinct type so a messaging
    channel can ask for the reason instead of just refusing - the rule itself
    stays here, never duplicated elsewhere."""

    def __init__(self, planned_start_date: date):
        super().__init__(
            422,
            "A reason is required to start a task before its planned start date "
            f"({planned_start_date.isoformat()}).",
        )
        self.planned_start_date = planned_start_date


def latest_submitter_user_id(db: Session, task_id: uuid.UUID) -> uuid.UUID | None:
    """Who most recently moved the task to `submitted` - the person whose
    work is under review (read from the transition's own audit row). Used to
    tell the executor the outcome of their submission."""
    rows = db.execute(
        select(V2AuditEvent.actor_user_id, V2AuditEvent.after_json)
        .where(
            V2AuditEvent.entity_type == "task",
            V2AuditEvent.entity_id == task_id,
            V2AuditEvent.action == "TASK_STATUS_CHANGED",
            V2AuditEvent.actor_user_id.is_not(None),
        )
        .order_by(V2AuditEvent.occurred_at.desc(), V2AuditEvent.id.desc())
    ).all()
    for actor_user_id, after_json in rows:
        if (after_json or {}).get("lifecycle_status") == "submitted":
            return actor_user_id
    return None


class TaskLifecycleService:
    def __init__(self, db: Session):
        self.db = db

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

    def _actor_employee_id(self, actor: User) -> uuid.UUID | None:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        return employee.id if employee else None

    def _active_internal_employee_assignee_ids(self, task_id: uuid.UUID) -> set[uuid.UUID]:
        return set(self.db.scalars(
            select(TaskSupportAssignment.employee_id).where(
                TaskSupportAssignment.task_id == task_id,
                TaskSupportAssignment.status == "active",
                TaskSupportAssignment.ends_at.is_(None),
            )
        ))

    def _require_role_for_transition(self, project: V2Project, task: Task, target_status: str, actor: User) -> None:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        roles = self._actor_project_roles(project.id, actor)

        if target_status in _EXECUTOR_DRIVEN_TARGETS:
            assignee_ids = self._active_internal_employee_assignee_ids(task.id)
            if assignee_ids:
                if self._actor_employee_id(actor) in assignee_ids:
                    return
                raise HTTPException(
                    403,
                    "An Internal Employee is assigned to this task; only they can start or submit it. "
                    "End their support assignment to change who executes it.",
                )
            # Approval-gate work has no Supervisor/PM self-execute fallback:
            # unlike ordinary work, a PM can't just do the task themselves
            # when nobody's assigned - an Internal Employee must be
            # delegated first. The PM still retains the actual approval
            # decision either way (TaskApprovalService); this only removes
            # the shortcut around who performs the underlying work.
            if task.task_kind == "approval_gate":
                raise HTTPException(
                    409,
                    "This is an approval-gate task; assign it to an Internal Employee before work can start.",
                )
            if "site_supervisor" in roles or "project_manager" in roles:
                return
            raise HTTPException(403, "Only the project's Supervisor, PM, or an Admin can make this task transition.")

        if target_status in _SUPERVISOR_OR_PM_TARGETS:
            if "site_supervisor" in roles or "project_manager" in roles:
                return
            # The Internal Employee actively assigned to the task may also
            # mark it `ready`, so a busy Supervisor/PM doesn't block its start.
            # Every other target here (verify/approve/complete/reject) stays
            # Supervisor/PM-only.
            if target_status == "ready" and self._actor_employee_id(actor) in self._active_internal_employee_assignee_ids(task.id):
                return
            raise HTTPException(403, "Only the project's Supervisor, PM, or an Admin can make this task transition.")
        raise HTTPException(403, "You do not have permission to make this task transition.")

    def _can_cancel(self, project: V2Project, actor: User) -> bool:
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return True
        roles = self._actor_project_roles(project.id, actor)
        # "authorized override" per BR-009: Admin/Super Admin, or the
        # accountable PM, may cancel a task.
        return "project_manager" in roles

    def _has_active_supervisor(self, project_id: uuid.UUID) -> bool:
        return self.db.scalar(
            select(V2ProjectMembership.id).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == "site_supervisor",
                V2ProjectMembership.ends_at.is_(None),
            )
        ) is not None

    # ---- dependency satisfaction -------------------------------------

    def _has_unrejected_verification(self, predecessor: Task) -> bool:
        """Whether the most recent TaskVerification recorded against
        `predecessor` is a 'verified' decision with no later rejection.

        Since a rejection always moves lifecycle_status off 'verified' (back
        to 'in_progress' via U4's TaskVerificationService, requiring
        resubmission and a fresh verification), a predecessor that is
        currently sitting at lifecycle_status == 'verified' can only be
        there because its latest verification decision was 'verified' - but
        we still query explicitly here (rather than trust the status alone)
        so this check is correct even if called from a context that hasn't
        re-read the task's current status.
        """
        latest = self.db.scalar(
            select(TaskVerification)
            .where(TaskVerification.task_id == predecessor.id)
            .order_by(TaskVerification.verified_at.desc(), TaskVerification.id.desc())
            .limit(1)
        )
        return latest is not None and latest.decision == "verified"

    def _predecessor_satisfied(self, predecessor: Task, dependency_type: str) -> bool:
        """Whether a predecessor task satisfies a blocking dependency, per
        BR-008's per-kind rule and the edge's own `dependency_type`.

        `finish_to_start` (the default, and every edge before this change):

        - `standard` work: satisfied once Supervisor-verified (a
          `task_verifications` row with decision='verified' and no later
          rejection exists) - it does not need to also reach `completed`,
          since BR-008 only requires PM approval for Class A work, not
          standard work. `completed` also satisfies it (the standard-work
          verify path immediately auto-completes it anyway, per U4's
          TaskVerificationService, so this task is nearly always observed
          at `completed`, not `verified` - but the `verified` case is
          the "satisfied" moment we should not block on regardless).
        - `class_a` work and `approval_gate`: require PM-approved
          `completed` (BR-008: "Verified class_a work requires PM approval
          before completion"; gates likewise complete only via PM
          approval).
        - `milestone`: requires `completed` (system-derived, BR-009).

        `start_to_start`: satisfied as soon as the predecessor has actually
        started, i.e. left the pre-start statuses. This is the whole point
        of the edge type - the successor is allowed to overlap the
        predecessor rather than queue behind it. Before this change
        `dependency_type` was stored and rendered but never read here, so
        every start-to-start edge silently behaved as finish-to-start and
        the parallel execution the template's SS edges exist to express
        never happened.

        `cancelled` satisfies either type: the work will not happen, so it
        can never become satisfied any other way, and leaving it
        unsatisfied strands every downstream task permanently with no
        recovery but cancelling them too.

        NOTE: this relaxed rule is for *startability* only. Milestone
        auto-completion deliberately does not use it - see
        `_milestone_predecessors_completed`.
        """
        if predecessor.lifecycle_status == "cancelled":
            return True
        if dependency_type == "start_to_start":
            return predecessor.lifecycle_status in _STARTED_STATUSES
        if predecessor.lifecycle_status == "completed":
            return True
        if (
            is_work_task_kind(predecessor.task_kind)
            and predecessor.task_class == "standard"
            and predecessor.lifecycle_status == "verified"
        ):
            return self._has_unrejected_verification(predecessor)
        return False

    def _blocking_predecessors_satisfied(self, task: Task) -> bool:
        """Startability check: may `task` move to ready/in_progress?"""
        deps = self.db.scalars(
            select(TaskDependency).where(
                TaskDependency.successor_task_id == task.id,
                TaskDependency.blocking.is_(True),
            )
        )
        for dep in deps:
            predecessor = self.db.get(Task, dep.predecessor_task_id)
            if not predecessor or not self._predecessor_satisfied(predecessor, dep.dependency_type):
                return False
        return True

    def _milestone_predecessors_completed(self, task: Task) -> bool:
        """Derived-completion check: may `task` (a milestone) auto-complete?

        Deliberately stricter than `_blocking_predecessors_satisfied`, and
        deliberately NOT sharing its per-edge rule. A milestone asserts that
        the work behind it actually happened, so:

        - `start_to_start` is ignored here: a predecessor that has merely
          *started* has not delivered anything a milestone can claim.
        - `cancelled` does NOT satisfy: work that was abandoned cannot
          evidence a milestone. Sharing the startability rule would let a
          milestone auto-complete - writing a TASK_STATUS_CHANGED audit
          event and an actual finish - on the strength of cancelled work,
          and would cascade recursively through chained milestones.

        Only a predecessor that genuinely reached `completed` counts.
        """
        deps = self.db.scalars(
            select(TaskDependency).where(
                TaskDependency.successor_task_id == task.id,
                TaskDependency.blocking.is_(True),
            )
        )
        for dep in deps:
            predecessor = self.db.get(Task, dep.predecessor_task_id)
            if not predecessor or predecessor.lifecycle_status != "completed":
                return False
        return True

    # ---- milestone auto-completion -----------------------------------

    def _auto_complete_successor_milestones(self, source_task: Task, actor: User) -> None:
        """Side effect run whenever a task reaches `completed`: any
        successor `milestone` task still `planned` whose blocking
        predecessors are now all satisfied auto-transitions to `completed`.
        Recurses to handle chained milestones."""
        dep_rows = list(self.db.scalars(
            select(TaskDependency).where(
                TaskDependency.predecessor_task_id == source_task.id,
                TaskDependency.blocking.is_(True),
            )
        ))
        for dep in dep_rows:
            successor = self.db.get(Task, dep.successor_task_id)
            if not successor or successor.task_kind != "milestone" or successor.lifecycle_status != "planned":
                continue
            if not self._milestone_predecessors_completed(successor):
                continue
            before_status = successor.lifecycle_status
            successor.lifecycle_status = "completed"
            # This cascade sets lifecycle_status directly rather than going
            # through transition(), so it must record its own actuals - the
            # U10 block in transition() does not cover it. A milestone is
            # derived, never worked on, so its start and finish are the same
            # instant: the moment its predecessors made it true.
            completed_at = datetime.now(timezone.utc)
            successor.actual_finish_at = completed_at
            if successor.actual_start_at is None:
                successor.actual_start_at = completed_at
            self.db.add(V2AuditEvent(
                actor_user_id=actor.id,
                action="TASK_STATUS_CHANGED",
                entity_type="task",
                entity_id=successor.id,
                project_id=successor.project_id,
                source="system",
                before_json={"lifecycle_status": before_status},
                after_json={"lifecycle_status": "completed"},
                reason="Milestone auto-completed: all blocking predecessors satisfied.",
            ))
            self.db.flush()
            # This path deliberately mutates lifecycle_status directly
            # (never through `transition()`, which would re-run role/access
            # gating not applicable to a system-derived cascade) - so it
            # needs its own outbox emission; `transition()`'s own emit call
            # below does NOT cover this cascade.
            OutboxService(self.db).emit(
                event_type="task.status_changed",
                aggregate_type="task",
                aggregate_id=successor.id,
                payload={
                    "task_id": str(successor.id),
                    "project_id": str(successor.project_id),
                    "before_status": before_status,
                    "target_status": "completed",
                    "reason": "Milestone auto-completed: all blocking predecessors satisfied.",
                },
                idempotency_key=f"task:{successor.id}:task.status_changed:completed",
            )
            self._auto_complete_successor_milestones(successor, actor)

    # ---- review cycle ------------------------------------------------------

    def _submission_snapshot(self, task_id: uuid.UUID, actor: User) -> dict:
        """who submitted and exactly which progress
        updates this submission rests on - the unreviewed set at submit time,
        read under the task row lock (KTD24), so nothing can join or leave it
        before the decision. Review messages, their files and the people told
        the outcome are built from this, never from a live "current cycle"
        query that could have moved on by the time a message is sent."""
        update_ids = self.db.scalars(
            select(TaskProgressUpdate.id)
            .where(TaskProgressUpdate.task_id == task_id, TaskProgressUpdate.reviewed_at.is_(None))
            .order_by(TaskProgressUpdate.created_at, TaskProgressUpdate.id)
        ).all()
        return {"submitted_by": str(actor.id), "progress_update_ids": [str(i) for i in update_ids]}

    def mark_progress_reviewed(self, task_id: uuid.UUID) -> None:
        """Closes the task's current review cycle: every progress update not
        yet covered by a decision is marked reviewed now. Called by the
        verification and approval services for BOTH outcomes, inside the
        decision's own transaction (before their first transition() commit),
        so a decision and the cycle it closed can never be split."""
        self.db.execute(
            update(TaskProgressUpdate)
            .where(TaskProgressUpdate.task_id == task_id, TaskProgressUpdate.reviewed_at.is_(None))
            .values(reviewed_at=datetime.now(timezone.utc))
        )

    # ---- transition entry point ---------------------------------------

    def transition(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        target_status: str,
        actor: User,
        reason: str | None = None,
        _via_decision_service: bool = False,
        source: str = "portal",
    ) -> Task:
        """`_via_decision_service` is set only by TaskVerificationService/
        TaskApprovalService's own internal calls (never by the raw
        `POST /status` route) - it (a) unlocks the decision-only targets
        below and (b) skips the role re-check, since the calling service
        already validated the actor as the verifier/approver of record for
        this exact decision.

        `source` is purely an audit-trail label ('portal'/'whatsapp'/
        'system') - it changes nothing about who is allowed to
        transition what. Defaults to 'portal' for every existing call site
        (the raw route, TaskVerificationService, TaskApprovalService); only
        `InboundMessageService`'s STATUS-command handler passes its own
        channel, so a WhatsApp-originated status change is no
        longer mis-recorded as if it happened in the Web App."""
        project = self._require_access(project_id, actor)

        task = self.db.scalar(
            select(Task).where(Task.id == task_id, Task.project_id == project.id).with_for_update()
        )
        if not task:
            raise HTTPException(404, "Task not found.")

        if target_status not in TASK_LIFECYCLE_STATUSES:
            raise HTTPException(422, "Unknown task lifecycle status.")

        current_status = task.lifecycle_status
        if target_status == current_status:
            raise HTTPException(409, f"Task is already {current_status}.")

        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise HTTPException(
                409,
                f"A task cannot move from {current_status} to {target_status}.",
            )

        if not _via_decision_service:
            if target_status in _DECISION_SERVICE_ONLY_TARGETS:
                raise HTTPException(
                    409,
                    "Use the task's verification or approval endpoint to record this decision.",
                )
            if target_status == "completed" and task.task_kind != "milestone":
                raise HTTPException(
                    409,
                    "Use the task's verification or approval endpoint to complete this task.",
                )

        # planned -> completed is exclusively the system-derived milestone
        # auto-completion path (BR-009) - not a user-initiated transition
        # for any other task_kind, and not permitted before its blocking
        # predecessors are actually satisfied.
        if current_status == "planned" and target_status == "completed":
            if task.task_kind != "milestone":
                raise HTTPException(
                    409,
                    "Only a milestone task can move directly from planned to completed.",
                )
            if not self._milestone_predecessors_completed(task):
                raise HTTPException(
                    409,
                    "This milestone's blocking predecessor tasks are not yet all completed.",
                )

        if target_status == "cancelled":
            clean_reason = (reason or "").strip()
            if not clean_reason:
                raise HTTPException(422, "A reason is required to cancel a task.")
            if not self._can_cancel(project, actor):
                raise HTTPException(403, "Only Admin, Super Admin, or the project's PM can cancel a task.")
        elif not _via_decision_service:
            self._require_role_for_transition(project, task, target_status, actor)

        if target_status in {"ready", "in_progress"}:
            # BR-004: work cannot start/proceed without an accountable
            # active Supervisor on the project.
            if not self._has_active_supervisor(project.id):
                raise HTTPException(
                    409,
                    "This project has no active Supervisor; task work cannot start or proceed.",
                )
            # BR-011: a dependent task cannot start while a blocking
            # predecessor is unsatisfied.
            if not self._blocking_predecessors_satisfied(task):
                raise HTTPException(
                    409,
                    "One or more blocking predecessor tasks are not yet satisfied.",
                )

        if target_status == "submitted" and (is_work_task_kind(task.task_kind) or task.task_kind == "approval_gate"):
            # A submission must rest on progress logged since the task's last
            # review decision. Every verification or approval decision (either
            # outcome) sets `reviewed_at` on all of the task's unreviewed
            # updates (`mark_progress_reviewed`), so "unreviewed" means exactly
            # "logged in this cycle".
            #
            # - No progress update at all -> nothing for Verify/Reject to act
            #   on -> the task would strand at `submitted` (the original bug: a
            #   Supervisor self-executing, clicking straight through the
            #   forward-transition buttons without ever opening Log Progress).
            # - Only already-reviewed updates -> resubmitting would re-send the
            #   same decided work - every update of a rejected cycle, not just
            #   the one a verification happened to name, and also after a PM
            #   rejection, which names no update at all.
            #
            # Approval-gate tasks follow the same rule: an intentional shared change - before it they could be
            # submitted with no progress, and resubmitted after a PM rejection
            # with nothing new.
            #
            # Deliberately an existence check, not "pick the most recent
            # update and check it" - `created_at` timestamps are not
            # guaranteed unique at sub-second resolution (notably under this
            # codebase's SQLite test harness).
            unreviewed_update_ids = select(TaskProgressUpdate.id).where(
                TaskProgressUpdate.task_id == task.id,
                TaskProgressUpdate.reviewed_at.is_(None),
            )
            if self.db.scalar(unreviewed_update_ids.limit(1)) is None:
                raise HTTPException(
                    409,
                    "Log a new progress update (a note and/or evidence) before submitting this task for review.",
                )

            # U7 (R25): `evidence_required` is enforced over the SAME
            # unreviewed set, so "fresh" means one thing on this path and a
            # rejected file can never satisfy a resubmission.
            if task.evidence_required:
                has_unreviewed_evidence = self.db.scalar(
                    select(TaskEvidence.id)
                    .where(TaskEvidence.task_progress_update_id.in_(unreviewed_update_ids))
                    .limit(1)
                ) is not None
                if not has_unreviewed_evidence:
                    # Deliberately distinct wording from the message above: the
                    # board surfaces the backend's own text, and "you logged
                    # nothing" and "you logged a note but no file" are different
                    # things for the user to go and do.
                    raise HTTPException(
                        409,
                        "This task requires evidence. Attach a file to a new progress update "
                        "before submitting this task for review.",
                    )

        # U14: starting ahead of plan is permitted, but never silently. The
        # reason is validated here - before any mutation - so a refused early
        # start leaves the task exactly as it was, the same shape as the
        # cancellation path above.
        #
        # Only the FIRST start can be early: "early" is a fact about when work
        # began, and a rejected task reopening through `in_progress` resumes
        # work that already started. The `actual_start_at is None` guard is the
        # same one U10's actuals block below writes under, so the reason and
        # the actual start it must accompany always land in one write - which
        # is what ck_v2_tasks_early_start_reason_requires_start demands.
        #
        # Deliberately no authority check: who may authorise an early start is
        # an open question owned by management (R17/Q3). This captures the
        # reason without narrowing who may act.
        early_start_reason: str | None = None
        if (
            target_status == "in_progress"
            and task.actual_start_at is None
            and task.planned_start_date is not None
            # UTC to match the clock U10 stamps actual_start_at from, so the
            # date compared against the plan is the date that gets recorded.
            and datetime.now(timezone.utc).date() < task.planned_start_date
        ):
            early_start_reason = (reason or "").strip()
            if not early_start_reason:
                raise EarlyStartReasonRequired(task.planned_start_date)

        before_status = current_status
        task.lifecycle_status = target_status

        # U10: record when work actually began and ended, on the same write
        # path and inside the same transaction as the status change itself -
        # the transition is already the single audited authority for status,
        # and writing actuals anywhere else would create a second source of
        # truth for the same fact.
        if target_status == "in_progress" and task.actual_start_at is None:
            # Only on the FIRST start. A rejected task reopens through
            # `in_progress` again, and the date work actually began must not
            # be overwritten by the date it resumed.
            task.actual_start_at = datetime.now(timezone.utc)
            if early_start_reason:
                # Same write as the status and the actual start, never a
                # second pass: the CHECK constraint only permits a reason
                # where actual_start_at is set, so an update ordered after
                # this block would have nothing to attach to.
                task.early_start_reason = early_start_reason
        elif target_status == "completed":
            task.actual_finish_at = datetime.now(timezone.utc)
            if task.actual_start_at is None:
                # A milestone auto-completes from `planned` without ever
                # passing through `in_progress`, so it has no start to
                # inherit. Anchor it to its finish rather than leaving a
                # finish with no start, which the actual-window CHECK would
                # otherwise permit but variance could not interpret.
                task.actual_start_at = task.actual_finish_at
        # `cancelled` deliberately records no finish: the task never finished.

        clean_reason = (reason or "").strip() or f"Task moved from {before_status} to {target_status}."
        after_json: dict[str, str] = {"lifecycle_status": target_status}
        if early_start_reason:
            # Carried in the audit event as well as on the row, so the trail
            # explains the early start at the moment it happened - the column
            # alone says only that some start was early, not which transition
            # it was given for.
            after_json["early_start_reason"] = early_start_reason
        audit_event = V2AuditEvent(
            actor_user_id=actor.id,
            action="TASK_STATUS_CHANGED",
            entity_type="task",
            entity_id=task.id,
            project_id=project.id,
            source=source,
            before_json={"lifecycle_status": before_status},
            after_json=after_json,
            reason=clean_reason,
        )
        self.db.add(audit_event)
        self.db.flush()

        # Single instrumentation point for every user-initiated status
        # change in the system (BR-015's generic "status change" event) -
        # verify()/approve()'s multi-step cascades each land here once per
        # transition() call, riding the SAME open transaction that this
        # method's own commit below closes.
        OutboxService(self.db).emit(
            event_type="task.status_changed",
            aggregate_type="task",
            aggregate_id=task.id,
            payload={
                "task_id": str(task.id),
                "project_id": str(project.id),
                "before_status": before_status,
                "target_status": target_status,
                "reason": clean_reason,
                "actor_user_id": str(actor.id),
                # Set only for the intermediate steps a verification/approval
                # decision drives (e.g. submitted -> rejected -> in_progress):
                # lets readers tell them apart from user-driven steps.
                **({"cause": "decision"} if _via_decision_service else {}),
                **(self._submission_snapshot(task.id, actor) if target_status == "submitted" else {}),
            },
            # Keyed by this transition's own audit row, not by target status:
            # a rework loop reaches `submitted`/`in_progress` again and again,
            # and each occurrence must notify. Retrying the same occurrence
            # still collapses onto the one key.
            idempotency_key=f"task:{task.id}:task.status_changed:{target_status}:{audit_event.id}",
        )

        if target_status == "completed":
            self._auto_complete_successor_milestones(task, actor)

        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "This task transition could not be completed.") from exc

        self.db.refresh(task)
        return task
