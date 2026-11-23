"""U11 / Plan: External Approval Gate Assignment & Evidence Lifecycle (U5).

`ProjectGateDecisionService.decide` moves one `ProjectExternalApproval` from
`submitted` to `approved` or `rejected`, recording who decided and when, and
`ProjectGateDecisionService.list_for_project` reads a project's approvals back
out for the Execution tab.

Why this writes to `ProjectExternalApproval` and never to the planning-layer
`V2ProjectExternalGate`: the gate's `status` is a Draft-time review marker,
CHECK-constrained to the single value `pending_review` and written only while
the project is still a draft. "Has the authority granted this?" is a runtime
question about a live project, and answering it on the gate would conflate the
planning question with the execution one and split one approval's state across
two families (KTD3/KTD8). `ProjectExternalApproval` exists precisely so that it
does not have to.

Authority is Admin-only (R3) - a deliberate divergence from
`TaskApprovalService._require_approver`'s PM-first/Admin-fallback pattern,
made because there is no PM-fallback tier for this decision (see the plan's
Key Technical Decisions). Read access stays wider (any active project
member): a Supervisor needs to see which approvals are holding up their site
even though they may not decide one, which is the same split
`ProjectGateApplicabilityService` already draws between `_require_access` and
`_require_decider`.

Invariants this module is careful about:

- `ck_v2_project_external_approvals_decision_completeness` requires `status`,
  `decided_by` and `decided_at` to move together - `unassigned`/`assigned`/
  `submitted` rows must have both nulls, `approved`/`rejected` rows must have
  both set. They are therefore assigned in one place, never incrementally,
  within each of the two writes a rejection makes (see below).
- `ck_v2_project_external_approvals_coverage_text` permits prose only on an
  `unresolved` approval, so a decision never touches the coverage columns. A
  decision answers "was it granted?", not "what does it cover?" - the two are
  independent, and an approval can perfectly well be granted while its scope is
  still unresolved for a human to pin down (R10).
- An approved approval is final - re-deciding is refused rather than
  overwritten, because the row carries the attribution of who granted what and
  silently replacing it would destroy the audit answer the row exists to give.
- A rejection is a TWO-STEP transition, not a single write straight to
  `assigned`. `decide()` first persists `status='rejected'` with
  `decided_by`/`decided_at`/`rejection_reason` set (satisfying the
  completeness check and giving the assignee/PM/Supervisor a real record of
  why the gate was rejected), then immediately performs a second write in the
  same call to `status='assigned'`, resetting `decided_by`/`decided_at` to
  null while KEEPING `rejection_reason` populated so it survives the reset
  and stays visible to the assignee on resubmission. Without persisting the
  intermediate `rejected` row, the CHECK constraint's rejected branch would
  never actually be exercised - a gap three independent doc reviewers flagged
  before implementation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import (
    FileObject,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
    ProjectExternalApprovalTask,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.outbox import OutboxService
from app.services.project_reference_material import NO_MATERIAL, material_for_gates

GATE_DECISIONS = ("approved", "rejected")
"""The subset of `EXTERNAL_APPROVAL_STATUSES` a human may write - `pending` is
instantiation's starting point, not a decision anyone records, which is also
why `decide` treats "not pending" as "already decided"."""


@dataclass(frozen=True)
class GateEvidenceView:
    id: uuid.UUID
    file_id: uuid.UUID
    evidence_type: str
    caption: str | None
    original_filename: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class GateSubmissionView:
    """One past submission - the review context Admin needs on a `submitted`
    gate (what was actually attached), and the history PM/Supervisor read
    (R6). Without this, an Admin deciding a gate had no way to see what the
    assignee uploaded - the same gap task review closes via
    `TaskDetailOut.progress_updates`."""
    id: uuid.UUID
    submitted_by: uuid.UUID
    submitted_by_name: str | None
    note: str | None
    submitted_at: datetime
    evidence: tuple[GateEvidenceView, ...]


@dataclass(frozen=True)
class ExternalApprovalView:
    """One approval as the Execution tab needs it: the runtime decision, the
    coverage facts readiness uses, and enough of the gate (code, name) to name
    it to a human without the frontend having to fetch the planning layer."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_gate_id: uuid.UUID
    gate_code: str
    gate_name: str
    status: str
    blocking: bool
    coverage_state: str
    coverage_text: str | None
    covered_task_ids: tuple[uuid.UUID, ...]
    assigned_to_user_id: uuid.UUID | None
    assigned_to_name: str | None
    assigned_by: uuid.UUID | None
    assigned_at: datetime | None
    rejection_reason: str | None
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    submissions: tuple[GateSubmissionView, ...]
    # The deadline set when the gate was assigned (or resolved from a manual
    # gate's day rule). None for gates that never had one.
    due_at: date | None = None
    evidence_instructions: str | None = None
    reference_files: tuple[dict, ...] = ()


class ProjectGateDecisionService:
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

    def _require_approver(self, project: V2Project, actor: User) -> None:
        """R3: Admin-only, with no PM-fallback tier - a deliberate divergence
        from `TaskApprovalService._require_approver`'s PM-first pattern. See
        the plan's Key Technical Decisions for why: the assignment/submission
        steps that now precede a decision give Admin a real evidence trail to
        decide from, which is the accountability a PM-first rule exists to
        provide for task approvals."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        raise HTTPException(403, "Only an Admin can decide an external approval.")

    def get_approval(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> ProjectExternalApproval:
        approval = self.db.scalar(
            select(ProjectExternalApproval).where(
                ProjectExternalApproval.id == approval_id,
                ProjectExternalApproval.project_id == project_id,
            )
        )
        if not approval:
            raise HTTPException(404, "External approval not found for this project.")
        return approval

    # ---- decide ------------------------------------------------------

    def decide(
        self,
        project_id: uuid.UUID,
        approval_id: uuid.UUID,
        decision: str,
        actor: User,
        reason: str | None = None,
        source: str = "portal",
    ) -> ExternalApprovalView:
        """`source` is an audit-trail label only ('portal'/'whatsapp')
        - `_require_approver` below still owns the actual
        Admin/Super-Admin authorization check regardless of channel.
        Defaults to 'portal' for the raw route; `InboundMessageService`'s
        GATEDECIDE handler passes its own channel."""
        project = self._require_access(project_id, actor)

        if decision not in GATE_DECISIONS:
            raise HTTPException(422, "An approval decision must be 'approved' or 'rejected'.")

        clean_reason = (reason or "").strip() or None
        # Same rule as rejecting a task (`TaskApprovalService.approve`): a
        # refusal that says nothing leaves nobody able to act on it.
        if decision == "rejected" and not clean_reason:
            raise HTTPException(422, "A reason is required to reject an external approval.")

        self._require_approver(project, actor)
        approval = self.get_approval(project.id, approval_id)

        if approval.status == "approved":
            raise HTTPException(
                409, "This external approval has already been approved; a recorded decision cannot be replaced.",
            )
        if approval.status != "submitted":
            raise HTTPException(
                409,
                f"This external approval is {approval.status}; only a submitted gate can be decided.",
            )

        previous_status = approval.status
        decided_at = datetime.now(timezone.utc)

        if decision == "approved":
            # Single write: assigned together, in one place, so the
            # completeness CHECK never sees status and decided_by/decided_at
            # disagree. coverage_state/coverage_text are deliberately
            # untouched - a decision answers "was it granted?", not "what
            # does it cover?".
            approval.status = "approved"
            approval.decided_by = actor.id
            approval.decided_at = decided_at
            self.db.add(approval)

            self.db.add(V2AuditEvent(
                actor_user_id=actor.id,
                action="PROJECT_EXTERNAL_APPROVAL_DECIDED",
                entity_type="project_external_approval",
                entity_id=approval.id,
                project_id=project.id,
                source=source,
                before_json={"status": previous_status},
                after_json={"status": "approved", "decided_by": str(actor.id), "decided_at": decided_at.isoformat()},
                reason=clean_reason or "External approval approved by Admin.",
                occurred_at=decided_at,
            ))
        else:
            # Two-step transition (see module docstring): persist the
            # 'rejected' state first - satisfying the completeness CHECK and
            # giving the record a real "why" - then move on to 'assigned' in
            # the same call so the same assignee can resubmit immediately.
            approval.status = "rejected"
            approval.decided_by = actor.id
            approval.decided_at = decided_at
            approval.rejection_reason = clean_reason
            self.db.add(approval)
            self.db.flush()

            self.db.add(V2AuditEvent(
                actor_user_id=actor.id,
                action="PROJECT_EXTERNAL_APPROVAL_DECIDED",
                entity_type="project_external_approval",
                entity_id=approval.id,
                project_id=project.id,
                source=source,
                before_json={"status": previous_status},
                after_json={
                    "status": "rejected", "decided_by": str(actor.id),
                    "decided_at": decided_at.isoformat(), "rejection_reason": clean_reason,
                },
                reason=clean_reason,
                occurred_at=decided_at,
            ))
            self.db.flush()

            # The reset: decided_by/decided_at go back to null (no longer a
            # completed decision) but rejection_reason is deliberately left
            # populated, unlike the decision pair - it must survive the reset
            # to stay visible to the assignee's resubmission.
            approval.status = "assigned"
            approval.decided_by = None
            approval.decided_at = None
            self.db.add(approval)

            self.db.add(V2AuditEvent(
                actor_user_id=actor.id,
                action="PROJECT_EXTERNAL_APPROVAL_REOPENED_FOR_RESUBMISSION",
                entity_type="project_external_approval",
                entity_id=approval.id,
                project_id=project.id,
                source=source,
                before_json={"status": "rejected"},
                after_json={"status": "assigned"},
                reason="Returned to the assignee for resubmission after rejection.",
                occurred_at=decided_at,
            ))
        self.db.flush()

        # Emitted before the commit, inside the same transaction as the row it
        # describes - `OutboxService.emit` never commits, so the event and the
        # decision land together or not at all. `aggregate_type` is the
        # approval rather than the project on purpose: the dispatcher fans a
        # `project` aggregate out to the PM and Supervisor over WhatsApp, and
        # notifying on gate decisions is not this unit's call to make. One
        # outbox event per decide() call regardless of decision - the
        # reject-then-reopen sequence is one logical business event (the
        # decision), not two.
        OutboxService(self.db).emit(
            event_type="project_external_approval.decided",
            aggregate_type="project_external_approval",
            aggregate_id=approval.id,
            payload={
                "approval_id": str(approval.id),
                "project_id": str(project.id),
                "project_gate_id": str(approval.project_gate_id),
                "decision": decision,
                "reason": clean_reason,
                "decided_by": str(actor.id),
                "decided_at": decided_at.isoformat(),
                "blocking": approval.blocking,
            },
            idempotency_key=f"project_external_approval:{approval.id}:project_external_approval.decided:{decided_at.isoformat()}",
        )

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(approval)
        # The decided row is returned in the same shape the listing uses, so a
        # caller can drop it straight back into the list it came from without
        # a second round trip.
        return self.view_for_approval(approval)

    # ---- read --------------------------------------------------------

    @staticmethod
    def _view(
        approval: ProjectExternalApproval,
        gate: V2ProjectExternalGate,
        covered_task_ids,
        decided_by_name: str | None,
        assigned_to_name: str | None,
        submissions: tuple[GateSubmissionView, ...],
        material: dict | None = None,
    ) -> ExternalApprovalView:
        material = material or NO_MATERIAL
        return ExternalApprovalView(
            id=approval.id,
            project_id=approval.project_id,
            project_gate_id=approval.project_gate_id,
            gate_code=gate.original_code,
            gate_name=gate.approval_name,
            status=approval.status,
            blocking=approval.blocking,
            coverage_state=approval.coverage_state,
            coverage_text=approval.coverage_text,
            covered_task_ids=tuple(covered_task_ids),
            assigned_to_user_id=approval.assigned_to_user_id,
            assigned_to_name=assigned_to_name,
            assigned_by=approval.assigned_by,
            assigned_at=approval.assigned_at,
            rejection_reason=approval.rejection_reason,
            decided_by=approval.decided_by,
            decided_by_name=decided_by_name,
            decided_at=approval.decided_at,
            submissions=submissions,
            due_at=approval.due_at,
            evidence_instructions=material["evidence_instructions"],
            reference_files=tuple(material["reference_files"]),
        )

    def _submissions_for_approvals(
        self, approval_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[GateSubmissionView, ...]]:
        """Batched submission+evidence build for one or many approvals - the
        review context Admin needs on a `submitted` gate (what was actually
        attached) and the history PM/Supervisor/the assignee read (R6).
        Four flat queries regardless of how many approvals are asked for,
        matching this module's existing batching discipline."""
        if not approval_ids:
            return {}

        submissions = list(self.db.scalars(
            select(ProjectExternalApprovalSubmission)
            .where(ProjectExternalApprovalSubmission.approval_id.in_(approval_ids))
            .order_by(ProjectExternalApprovalSubmission.submitted_at.desc(), ProjectExternalApprovalSubmission.id.desc())
        ))
        if not submissions:
            return {}
        submission_ids = [submission.id for submission in submissions]

        evidence_rows = list(self.db.scalars(
            select(ProjectExternalApprovalEvidence)
            .where(ProjectExternalApprovalEvidence.submission_id.in_(submission_ids))
        ))
        file_ids = {row.file_id for row in evidence_rows}
        files_by_id: dict[uuid.UUID, FileObject] = {}
        if file_ids:
            files_by_id = {
                file_object.id: file_object
                for file_object in self.db.scalars(select(FileObject).where(FileObject.id.in_(file_ids)))
            }
        evidence_by_submission: dict[uuid.UUID, list[GateEvidenceView]] = {}
        for row in evidence_rows:
            file_object = files_by_id.get(row.file_id)
            if not file_object:
                continue
            evidence_by_submission.setdefault(row.submission_id, []).append(GateEvidenceView(
                id=row.id,
                file_id=row.file_id,
                evidence_type=row.evidence_type,
                caption=row.caption,
                original_filename=file_object.original_filename,
                mime_type=file_object.mime_type,
                size_bytes=file_object.size_bytes,
            ))

        submitter_ids = {submission.submitted_by for submission in submissions}
        submitter_names: dict[uuid.UUID, str] = {}
        if submitter_ids:
            submitter_names = {
                row[0]: row[1]
                for row in self.db.execute(select(User.id, User.name).where(User.id.in_(submitter_ids))).all()
            }

        by_approval: dict[uuid.UUID, list[GateSubmissionView]] = {}
        for submission in submissions:
            by_approval.setdefault(submission.approval_id, []).append(GateSubmissionView(
                id=submission.id,
                submitted_by=submission.submitted_by,
                submitted_by_name=submitter_names.get(submission.submitted_by),
                note=submission.note,
                submitted_at=submission.submitted_at,
                evidence=tuple(evidence_by_submission.get(submission.id, ())),
            ))
        return {approval_id: tuple(views) for approval_id, views in by_approval.items()}

    def view_for_approval(self, approval: ProjectExternalApproval) -> ExternalApprovalView:
        """Single-row counterpart to `list_for_project`'s batched build - used
        by `decide`/`assign`/`reassign`/`unassign`/`submit`, where exactly
        one approval is in hand."""
        gate = self.db.get(V2ProjectExternalGate, approval.project_gate_id)
        covered_task_ids = list(self.db.scalars(
            select(ProjectExternalApprovalTask.task_id)
            .where(ProjectExternalApprovalTask.approval_id == approval.id)
            .order_by(ProjectExternalApprovalTask.task_id.asc())
        ))
        decided_by_name = (
            self.db.scalar(select(User.name).where(User.id == approval.decided_by))
            if approval.decided_by else None
        )
        assigned_to_name = (
            self.db.scalar(select(User.name).where(User.id == approval.assigned_to_user_id))
            if approval.assigned_to_user_id else None
        )
        submissions = self._submissions_for_approvals([approval.id]).get(approval.id, ())
        material = material_for_gates(self.db, [gate]).get(gate.id) if gate else None
        return self._view(approval, gate, covered_task_ids, decided_by_name, assigned_to_name, submissions, material)

    def list_for_project(self, project_id: uuid.UUID, actor: User) -> list[ExternalApprovalView]:
        """Every execution-layer approval on one project, with the gate's
        identity, the decision, the coverage facts and the covered task ids.

        Read access is any active project member - a Supervisor must be able
        to see what is holding up their site even though `_require_approver`
        will not let them decide it. An Internal Employee is the one
        exception: mirroring `list_project_tasks`'s own scoping (they only
        see tasks they're actively assigned to support, not the whole
        project), they see only the gates assigned to them - not every other
        assignee's approval evidence on the project.

        Three flat queries rather than a join per approval: the Execution tab
        renders the whole list at once, and a per-row lookup would grow with
        the project."""
        project = self._require_access(project_id, actor)

        query = (
            select(ProjectExternalApproval, V2ProjectExternalGate)
            .join(V2ProjectExternalGate, V2ProjectExternalGate.id == ProjectExternalApproval.project_gate_id)
            .where(ProjectExternalApproval.project_id == project.id)
            .order_by(
                V2ProjectExternalGate.template_sequence.asc(),
                V2ProjectExternalGate.original_code.asc(),
            )
        )
        if actor.role == UserRole.internal_employee:
            query = query.where(ProjectExternalApproval.assigned_to_user_id == actor.id)
        rows = self.db.execute(query).all()
        if not rows:
            return []

        covered: dict[uuid.UUID, list[uuid.UUID]] = {}
        for link in self.db.scalars(
            select(ProjectExternalApprovalTask)
            .where(ProjectExternalApprovalTask.project_id == project.id)
            .order_by(ProjectExternalApprovalTask.task_id.asc())
        ):
            covered.setdefault(link.approval_id, []).append(link.task_id)

        decider_ids = {approval.decided_by for approval, _ in rows if approval.decided_by}
        assignee_ids = {approval.assigned_to_user_id for approval, _ in rows if approval.assigned_to_user_id}
        user_names: dict[uuid.UUID, str] = {}
        name_lookup_ids = decider_ids | assignee_ids
        if name_lookup_ids:
            user_names = {
                row[0]: row[1]
                for row in self.db.execute(select(User.id, User.name).where(User.id.in_(name_lookup_ids))).all()
            }

        submissions_by_approval = self._submissions_for_approvals([approval.id for approval, _ in rows])
        material_by_gate = material_for_gates(self.db, [gate for _, gate in rows])

        return [
            self._view(
                approval,
                gate,
                covered.get(approval.id, ()),
                user_names.get(approval.decided_by) if approval.decided_by else None,
                user_names.get(approval.assigned_to_user_id) if approval.assigned_to_user_id else None,
                submissions_by_approval.get(approval.id, ()),
                material_by_gate.get(gate.id),
            )
            for approval, gate in rows
        ]
