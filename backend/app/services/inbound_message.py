"""Phase 2 U6: inbound WhatsApp message matching (R8/R9).

`InboundMessageService.process` is the single entry point called after
`backend/app/routes/whatsapp_webhook_v2.py` has already verified the
webhook's HMAC signature. Its job is strictly: (1) de-duplicate by
`provider_message_id`, (2) match `sender_phone` to exactly one known
identity (an active employee, via `users.phone` joined to an active
`EmployeeProfile`; or a vendor contact, via `V2VendorContact.phone` /
`.whatsapp`), (3) parse a minimal command grammar scoped to that identity's
allowed command set, and (4) translate an approved command into the EXACT
SAME service call a portal action of that kind would make -
`TaskLifecycleService.transition` for employees,
`VendorAcknowledgementService.record_acknowledgement` for vendor contacts.
This module never mutates `Task.lifecycle_status` or any vendor-assignment
state directly - it only ever calls into those two existing services, which
already own all role/access/state-machine checks.

No phone-number normalization is applied anywhere in this codebase yet
(see the plan's gap note) - matching is raw string equality against
whatever is stored in `users.phone` / `V2VendorContact.phone` /
`V2VendorContact.whatsapp`.

Command grammar (deliberately minimal - this is new entry-point wiring for
R8/R9's identity/signature/same-service-path guarantees, not a UX-polish
exercise; a real product would need a friendlier conversational UX):

    Whitespace-split the message body. The first token is the command
    keyword, matched case-insensitively. Everything else is positional.

    Vendor-contact identity only:
        ACCEPT <assignment_ref>
        DECLINE <assignment_ref>
        CLARIFY <assignment_ref> <note...>

    where <assignment_ref> is the first 8 hex characters of a
    `TaskVendorAssignment.id` UUID with dashes stripped (matched
    case-insensitively against every assignment's id in that same form -
    zero or more than one match is an error, never resolved by a
    "most recent" or similar heuristic). <note...> (CLARIFY only) is
    whatever text follows the ref, verbatim.

    Employee identity only:
        STATUS <task_code> <target_status>
        GATEACCEPT <approval_ref>
        GATEDECLINE <approval_ref>
        GATESTATUS <approval_ref> <health> [note...]
        GATEDECIDE <approval_ref> APPROVE|REJECT [reason...] (Admin/Super Admin only)

    where <task_code> is a `Task.original_code` (e.g. "T003" - unique only
    within a project, not globally) and <target_status> is passed through
    verbatim to `TaskLifecycleService.transition`, which validates it.
    <approval_ref> is the first 8 hex characters of a
    `ProjectExternalApproval.id` UUID with dashes stripped, matched the
    exact same way <assignment_ref> is above (zero or more than one match
    is an error). GATEACCEPT/GATEDECLINE call
    `ProjectGateAcknowledgementService.record` (U5) with response
    "accepted"/"declined" - that service owns its own assignee-only access
    check (`_require_assignee`), so no project-role gate is applied here.
    GATESTATUS (U7) calls the existing `ProjectGateStatusCheckService.record`
    unchanged, with <health> lower-cased before being passed through - that
    service is what actually validates it against `STATUS_CHECK_HEALTHS`
    and owns its own assignee-only access check, so nothing here duplicates
    either. <note...> (GATESTATUS only, optional) is whatever text follows
    <health>, verbatim - same convention as CLARIFY's trailing note above.

        GATEOPEN <approval_ref>
        GATECLOSE [note...]
        GATEDECIDE <approval_ref> APPROVE|REJECT [reason...]

    (U10) GATEOPEN calls `GateEvidenceSessionService.open_session` (U8),
    <approval_ref> resolved the same way GATEACCEPT/GATEDECLINE's is above.
    GATECLOSE takes no ref - the sender's one open session (KTD4's DB
    constraint) already identifies the gate; an optional trailing note is
    appended to that session before it is closed. Both delegate every
    access/state check to `GateEvidenceSessionService` itself.

    (U12) GATEDECIDE is the WhatsApp analogue of a portal Admin decision on
    a submitted gate - `ProjectGateDecisionService.decide` (already
    existing) unchanged. Unlike every other employee-identity gate command
    above, it is role-gated at THIS layer FIRST, before the ref is even
    resolved: only `UserRole.admin`/`UserRole.super_admin` may send it - any
    other employee (PM, Supervisor, Internal Employee) is rejected with
    "This command is not available for your role.", a wording deliberately
    distinct from BR-015's cross-identity "not available for your identity
    type" below, so the two rejection reasons stay distinguishable in
    `InboundMessage.rejection_reason`. This role gate is a WhatsApp-layer
    pre-check for that distinguishable reason, not a substitute for
    `decide`'s own Admin-only `_require_approver` - the service's check is
    left in place unchanged. `APPROVE`/`REJECT` (case-insensitive) map to
    `decide`'s own `"approved"`/`"rejected"` decision values; anything after
    them is the optional `reason`, verbatim - same trailing-text convention
    as CLARIFY's/GATESTATUS's/GATECLOSE's own note.

    Any OTHER inbound message from an employee - free text with no
    recognized keyword, or an attachment (U9's media metadata: `id`,
    `mime_type`, `filename`, no bytes yet) - is routed into the sender's
    currently open evidence session instead of being rejected as
    "Unrecognized command", provided one is open (a genuinely empty message
    - no text AND no attachment, e.g. a location pin - is still
    "Unrecognized command" unconditionally). Plain text appends verbatim via
    `append_text`. An attachment is checked against
    `ALLOWED_EVIDENCE_MIME_TYPES` first (a miss is rejected without ever
    calling `download_inbound_media`); only a supported mime_type is
    downloaded, then checked against `MAX_EVIDENCE_SIZE_BYTES` (KTD18 - the
    same cap `project_gate_submission.py` enforces on the portal path)
    before being written to storage as a `FileObject` and linked via
    `append_attachment`. An employee with NO open session gets a distinct
    "no open session - send GATEOPEN first" rejection, checked before the
    mime_type check even runs - see `_handle_gate_session_fallback`/
    `_handle_gate_attachment` below for the exact ordering and the three
    distinct rejection reasons (unsupported type / download failure /
    oversized).

    A vendor contact sending STATUS/GATEACCEPT/GATEDECLINE/GATESTATUS/
    GATEOPEN/GATECLOSE/GATEDECIDE, or an employee sending
    ACCEPT/DECLINE/CLARIFY, is rejected as "not available for your identity
    type" (BR-015). An unrecognized keyword is rejected as "Unrecognized
    command."

Actor substitution for vendor acknowledgements (the one genuinely
non-obvious design decision here): `VendorAcknowledgementService.
record_acknowledgement` requires a `User` actor because it runs its own
PM-only access check (`_require_pm`) - but a `V2VendorContact` has no
`User` row at all in this codebase (no `user_id` FK). R4 already
establishes that a PM records an acknowledgement "on the vendor's behalf";
R9 says this unit must produce "the identical record a PM's portal
acknowledgement would produce" for an approved vendor reply. Combining
those: the correct actor to pass is the project's currently active PM's
`User` (resolved via `V2ProjectMembership` for the assignment's project,
`project_role == 'project_manager'`, `ends_at IS NULL`, then that
membership's `EmployeeProfile.user_id`). This satisfies
`record_acknowledgement`'s own access check exactly as a real PM-driven
portal call would, while the `inbound_messages` row itself still records
the vendor contact as the identity that actually sent the message - the
PM substitution is purely an actor-parameter mechanic for the downstream
service call, never surfaced as who "did" the acknowledgement in this
table. If no active PM exists for the project, that is a `'rejected'`
outcome, not a crash - there is no one to record on the vendor's behalf.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.execution_models import FileObject, GateEvidenceSession, InboundMessage, ProjectExternalApproval, Task
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services import evidence_storage
from app.services.outbox import OutboxService
from app.services.project_gate_acknowledgement import ProjectGateAcknowledgementService
from app.services.project_gate_decision import ProjectGateDecisionService
from app.services.project_gate_evidence_session import GateEvidenceSessionService
from app.services.project_gate_status_check import ProjectGateStatusCheckService
from app.services.project_gate_submission import ALLOWED_EVIDENCE_MIME_TYPES, MAX_EVIDENCE_SIZE_BYTES
from app.services.task_lifecycle import TaskLifecycleService
from app.services.vendor_acknowledgement import VendorAcknowledgementService
from app.services.whatsapp_media import download_inbound_media
from app.vendor_models import TaskVendorAssignment, V2VendorContact

VENDOR_COMMANDS = {"ACCEPT", "DECLINE", "CLARIFY"}
EMPLOYEE_COMMAND = "STATUS"
# U6: GATEACCEPT/GATEDECLINE are the WhatsApp analogue of a portal gate
# acknowledgement (ProjectGateAcknowledgementService, U5) - employee-identity
# only, alongside STATUS. Not role-restricted at this layer: the service's
# own `_require_assignee` already enforces "only the specific assignee",
# which is a narrower and sufficient check.
GATE_COMMANDS = {"GATEACCEPT", "GATEDECLINE"}
# U7: GATESTATUS is the WhatsApp analogue of a portal gate status check
# (ProjectGateStatusCheckService, already existing) - kept as its own
# constant rather than folded into GATE_COMMANDS because it routes to a
# different handler (_handle_gate_status_command) and a different
# downstream service call, not `_GATE_RESPONSE_BY_COMMAND`.
GATE_STATUS_COMMAND = "GATESTATUS"
# U10: GATEOPEN/GATECLOSE are the WhatsApp analogue of starting/finishing a
# portal evidence submission (GateEvidenceSessionService, U8) - kept as
# their own constants rather than folded into GATE_COMMANDS because they
# route to their own handlers and a different downstream service.
GATE_SESSION_OPEN_COMMAND = "GATEOPEN"
GATE_SESSION_CLOSE_COMMAND = "GATECLOSE"
# Abandons the sender's open evidence session without submitting it
# (GateEvidenceSessionService.discard_session). Like GATECLOSE it takes no
# <ref> - the sender's one open session names the gate.
GATE_SESSION_CANCEL_COMMAND = "GATECANCEL"
# U12: the WhatsApp analogue of a portal Admin decision on a submitted gate
# (ProjectGateDecisionService.decide, already existing) - kept as its own
# constant rather than folded into GATE_COMMANDS because it routes to its
# own handler and, unlike every other GATE* command, is additionally
# role-gated at this layer (Admin/Super Admin only) before anything else.
GATE_DECIDE_COMMAND = "GATEDECIDE"
GATE_DECIDE_DECISION_BY_KEYWORD = {"APPROVE": "approved", "REJECT": "rejected"}
EMPLOYEE_COMMANDS = {
    EMPLOYEE_COMMAND, *GATE_COMMANDS, GATE_STATUS_COMMAND,
    GATE_SESSION_OPEN_COMMAND, GATE_SESSION_CLOSE_COMMAND, GATE_SESSION_CANCEL_COMMAND, GATE_DECIDE_COMMAND,
}

# Rejection reasons for evidence sent into a session, named so a channel can
# turn each into its own reply without parsing text.
NO_OPEN_SESSION_REASON = "You have no open evidence session. Send GATEOPEN <ref> first."
SESSION_NOT_ASSIGNED_REASON = (
    "This approval is no longer assigned to you for evidence, so nothing was added. "
    "Send GATECANCEL to close this evidence submission."
)
UNSUPPORTED_ATTACHMENT_REASON = "Unsupported attachment type; evidence must be JPG, PNG, WebP, or PDF."
OVERSIZED_ATTACHMENT_REASON = "Attachment is too large; evidence must be 10 MB or smaller."
DOWNLOAD_FAILED_REASON_PREFIX = "Could not download the attachment"

# The project roles that may drive a task-lifecycle transition at all
# (TaskLifecycleService._require_role_for_transition) - reused verbatim as
# the pre-filter for resolving an ambiguous project-scoped task code,
# rather than inventing a separate role set for the WhatsApp path.
# `internal_employee` was added here (Phase 1 fix) to bring the WhatsApp
# STATUS path in line with what the portal itself already allows: an
# Internal Employee support-assigned to a task can drive its
# `in_progress`/`submitted` transitions per task_lifecycle.py - excluding
# them here was a WhatsApp-path-only gap, not a deliberate narrower rule.
_STATUS_DRIVING_ROLES = ("site_supervisor", "project_manager", "internal_employee")

# Projects whose tasks a STATUS command can no longer target.
_CLOSED_PROJECT_STATUSES = ("completed", "archived")

_RESPONSE_BY_COMMAND = {
    "ACCEPT": "accepted",
    "DECLINE": "declined",
    "CLARIFY": "clarification_requested",
}

_GATE_RESPONSE_BY_COMMAND = {
    "GATEACCEPT": "accepted",
    "GATEDECLINE": "declined",
}

EmployeeIdentity = tuple[User, EmployeeProfile]


def active_pm_user(db: Session, project_id: uuid.UUID) -> User | None:
    """The project's active PM, who records a vendor's acknowledgement on the
    vendor's behalf (see the actor-substitution note above)."""
    membership = db.scalar(
        select(V2ProjectMembership).where(
            V2ProjectMembership.project_id == project_id,
            V2ProjectMembership.project_role == "project_manager",
            V2ProjectMembership.ends_at.is_(None),
        )
    )
    if membership is None:
        return None
    employee = db.get(EmployeeProfile, membership.employee_id)
    if employee is None:
        return None
    return db.get(User, employee.user_id)


class InboundMessageService:
    def __init__(self, db: Session):
        self.db = db
        # The channel recorded on audit rows and shown in replies.
        self._inbound_channel = "whatsapp"
        self._inbound_channel_label = "WhatsApp"

    # ---- entry point ----------------------------------------------------

    def process(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        media_metadata: dict | None = None,
    ) -> InboundMessage:
        """`media_metadata` (U10, optional - defaults to `None` so U15's
        call site does not need it) is U9's `_extract_media_metadata` output
        for an `"image"`/`"document"` inbound message (`id`, `mime_type`,
        and, document-only, `filename` - no bytes yet). It only ever
        matters to the employee-identity branch's session-fallback routing
        below; a vendor contact's commands are all text-only."""
        existing = self.db.scalar(
            select(InboundMessage).where(InboundMessage.provider_message_id == provider_message_id)
        )
        if existing is not None:
            # Duplicate webhook delivery: return the prior outcome
            # unchanged. No new row, no re-execution of any command.
            return existing

        employee_matches = self._match_employees(sender_phone)
        vendor_matches = self._match_vendor_contacts(sender_phone)
        total_matches = len(employee_matches) + len(vendor_matches)

        if total_matches == 0:
            return self._save(
                provider_message_id, sender_phone, message_text, None, None,
                "unmatched", "No identity matched this phone number.",
            )
        if total_matches > 1:
            return self._save(
                provider_message_id, sender_phone, message_text, None, None,
                "unmatched", "Phone number matched more than one identity; ambiguous.",
            )

        if employee_matches:
            return self._handle_employee(
                provider_message_id, sender_phone, message_text, employee_matches[0], media_metadata,
            )
        return self._handle_vendor_contact(
            provider_message_id, sender_phone, message_text, vendor_matches[0],
        )

    # ---- identity matching ------------------------------------------------

    def _match_employees(self, sender_phone: str) -> list[EmployeeIdentity]:
        rows = self.db.execute(
            select(User, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(User.phone == sender_phone, User.active.is_(True))
        ).all()
        return [(row[0], row[1]) for row in rows]

    def _match_vendor_contacts(self, sender_phone: str) -> list[V2VendorContact]:
        return list(
            self.db.scalars(
                select(V2VendorContact).where(
                    or_(V2VendorContact.phone == sender_phone, V2VendorContact.whatsapp == sender_phone)
                )
            ).all()
        )

    # ---- command parsing + dispatch ---------------------------------------

    def _handle_employee(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        identity: EmployeeIdentity,
        media_metadata: dict | None = None,
    ) -> InboundMessage:
        user, employee = identity
        parts = message_text.split()
        keyword = parts[0].upper() if parts else ""

        if keyword in VENDOR_COMMANDS:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "This command is not available for your identity type.",
            )
        if keyword in GATE_COMMANDS:
            return self._handle_gate_command(
                provider_message_id, sender_phone, message_text, user, employee, keyword, parts,
            )
        if keyword == GATE_STATUS_COMMAND:
            return self._handle_gate_status_command(
                provider_message_id, sender_phone, message_text, user, employee, parts,
            )
        if keyword == GATE_SESSION_OPEN_COMMAND:
            return self._handle_gate_open_command(
                provider_message_id, sender_phone, message_text, user, employee, parts,
            )
        if keyword == GATE_SESSION_CLOSE_COMMAND:
            return self._handle_gate_close_command(
                provider_message_id, sender_phone, message_text, user, employee, parts,
            )
        if keyword == GATE_SESSION_CANCEL_COMMAND:
            return self._handle_gate_cancel_command(provider_message_id, sender_phone, message_text, user, employee)
        if keyword == GATE_DECIDE_COMMAND:
            return self._handle_gate_decide_command(
                provider_message_id, sender_phone, message_text, user, employee, parts,
            )
        if keyword == EMPLOYEE_COMMAND:
            if len(parts) < 3:
                return self._save(
                    provider_message_id, sender_phone, message_text, "employee", employee.id,
                    "rejected", "Unrecognized command.",
                )

            task_code, target_status = parts[1], parts[2]
            # Cancelling needs a real, typed reason and stays a Web App
            # action. A messaging channel used to pass an automatic
            # "Reported via ..." text as that reason, which satisfied the
            # lifecycle's reason rule without anyone giving one.
            if target_status.lower() == "cancelled":
                return self._save(
                    provider_message_id, sender_phone, message_text, "employee", employee.id,
                    "rejected", "Cancellation is only available in the Web App.",
                )
            task = self._resolve_task_for_employee(task_code, employee)
            if task is None:
                return self._save(
                    provider_message_id, sender_phone, message_text, "employee", employee.id,
                    "rejected", "Could not uniquely resolve this task code to one of your projects.",
                )

            try:
                # The EXACT SAME service call a portal status-update action
                # would make - transition() owns all role/dependency/state
                # checks itself; nothing here duplicates that logic. No
                # reason is passed: an automatic text would otherwise be
                # recorded as the reason for an early start. An early typed
                # start is therefore refused by the lifecycle's own rule; the
                # channel is still recorded through `source`.
                TaskLifecycleService(self.db).transition(
                    task.project_id, task.id, target_status, actor=user,
                    source=self._inbound_channel,
                )
            except HTTPException as exc:
                return self._save(
                    provider_message_id, sender_phone, message_text, "employee", employee.id,
                    "rejected", str(exc.detail),
                )

            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
            )

        # U10: not one of the keywords above at all (as opposed to a
        # recognized keyword used with too few args, handled by each
        # branch's own check above). A genuinely empty message - no text
        # AND no attachment, e.g. a location pin - stays "Unrecognized
        # command." unconditionally; anything else (free text, or a bare
        # attachment - neither of which carries a keyword of its own)
        # routes into the sender's open evidence session, if one exists.
        if not message_text.strip() and media_metadata is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )
        return self._handle_gate_session_fallback(
            provider_message_id, sender_phone, message_text, user, employee, media_metadata,
        )

    def _resolve_task_for_employee(self, task_code: str, employee: EmployeeProfile) -> Task | None:
        # Task codes come from the template, so every project has its own
        # T022 - a code is only unique among the sender's live projects.
        # Completed/archived projects are excluded, otherwise lingering
        # membership in an old project makes every code ambiguous.
        candidates = self.db.scalars(
            select(Task)
            .join(V2Project, V2Project.id == Task.project_id)
            .where(Task.original_code == task_code, V2Project.status.not_in(_CLOSED_PROJECT_STATUSES))
        ).all()
        matched: list[Task] = []
        for task in candidates:
            has_driving_role = self.db.scalar(
                select(V2ProjectMembership.id).where(
                    V2ProjectMembership.project_id == task.project_id,
                    V2ProjectMembership.employee_id == employee.id,
                    V2ProjectMembership.ends_at.is_(None),
                    V2ProjectMembership.project_role.in_(_STATUS_DRIVING_ROLES),
                )
            )
            if has_driving_role is not None:
                matched.append(task)
        if len(matched) != 1:
            return None
        return matched[0]

    def _emit_gate_confirmation(
        self,
        provider_message_id: str,
        approval: ProjectExternalApproval,
        user: User,
        event_type: str,
        extra_payload: dict | None = None,
    ) -> None:
        """U15: the sender-facing half KTD2 promised but no unit emitted -
        one confirmation event per successful gate command, distinct from
        U5's Admin-facing `project_external_approval.accepted`/`.declined`
        (those keep notifying Admin unchanged; these notify the sender
        back). `gate_name`/`project_name` are resolved the same way U4's
        `project_gate_assignment.py` enriches its own payload
        (`gate.approval_name`/`project.name`) - this module never already
        holds those rows loaded the way U4's caller does, so they're
        fetched fresh via `approval.project_gate_id`/`approval.project_id`.
        Only ever called from a handler's success path, right before its
        existing `processed` `_save` - a rejected command never reaches
        this. `idempotency_key` is keyed on `provider_message_id`, which is
        unique per inbound message and already the de-duplication key
        `process()` uses before any handler ever runs."""
        gate = self.db.get(V2ProjectExternalGate, approval.project_gate_id)
        project = self.db.get(V2Project, approval.project_id)
        payload = {
            "actor_user_id": str(user.id),
            "gate_name": gate.approval_name,
            "project_name": project.name,
        }
        if extra_payload:
            payload.update(extra_payload)
        OutboxService(self.db).emit(
            event_type=event_type,
            aggregate_type="gate_command_confirmation",
            aggregate_id=approval.id,
            payload=payload,
            idempotency_key=f"gate_command_confirmation:{approval.id}:{event_type}:{provider_message_id}",
        )

    def _handle_gate_command(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        keyword: str,
        parts: list[str],
    ) -> InboundMessage:
        if len(parts) < 2:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )

        ref = parts[1]
        approval = self._resolve_gate_by_ref(ref)
        if approval is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "No unique assignment matched this reference.",
            )

        try:
            # The EXACT SAME service call a portal gate-acknowledgement
            # action would make - ProjectGateAcknowledgementService.record
            # owns the assignee-only access check itself (_require_assignee);
            # nothing here duplicates or narrows that.
            ProjectGateAcknowledgementService(self.db).record(
                approval.project_id, approval.id, actor=user, response=_GATE_RESPONSE_BY_COMMAND[keyword],
            )
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )

        self._emit_gate_confirmation(
            provider_message_id, approval, user, f"gate_confirmation.{_GATE_RESPONSE_BY_COMMAND[keyword]}",
        )
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _handle_gate_status_command(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        parts: list[str],
    ) -> InboundMessage:
        if len(parts) < 3:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )

        ref = parts[1]
        health = parts[2].lower()
        note = " ".join(parts[3:]) if len(parts) > 3 else None

        approval = self._resolve_gate_by_ref(ref)
        if approval is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "No unique assignment matched this reference.",
            )

        try:
            # The EXACT SAME service call a portal gate status-check action
            # would make - ProjectGateStatusCheckService.record owns both
            # the assignee-only access check (_require_assignee) and the
            # `STATUS_CHECK_HEALTHS` validation itself; nothing here
            # duplicates or narrows either.
            ProjectGateStatusCheckService(self.db).record(
                approval.project_id, approval.id, actor=user, health=health, note=note,
            )
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )

        self._emit_gate_confirmation(
            provider_message_id, approval, user, "gate_confirmation.status_recorded", {"health": health},
        )
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    # ---- evidence session commands (U10) -----------------------------------

    def _handle_gate_open_command(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        parts: list[str],
    ) -> InboundMessage:
        if len(parts) < 2:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )

        ref = parts[1]
        approval = self._resolve_gate_by_ref(ref)
        if approval is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "No unique assignment matched this reference.",
            )

        try:
            # The EXACT SAME service call a portal "start an evidence
            # session" action would make (U8) - open_session owns the
            # assignee-only access check and the approval.status ==
            # 'assigned' guard (KTD8) itself; nothing here duplicates
            # either.
            GateEvidenceSessionService(self.db).open_session(approval.project_id, approval.id, actor=user)
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )

        self._emit_gate_confirmation(provider_message_id, approval, user, "gate_confirmation.session_opened")
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _handle_gate_close_command(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        parts: list[str],
    ) -> InboundMessage:
        # GATECLOSE takes no <ref> - the sender's one open session (KTD4's
        # DB constraint) already identifies the gate. Everything after the
        # keyword is an optional trailing note, verbatim - same convention
        # as CLARIFY's/GATESTATUS's trailing note.
        note = " ".join(parts[1:]) if len(parts) > 1 else None

        session = self._open_session_for_employee(user.id)
        if session is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "You have no open evidence session to close.",
            )

        approval = self.db.get(ProjectExternalApproval, session.approval_id)
        if approval is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "The external approval for this evidence session no longer exists.",
            )

        service = GateEvidenceSessionService(self.db)
        if note:
            service.append_text(session, note)

        try:
            # The EXACT SAME service call a portal submission close would
            # make (U8/KTD17) - close_session owns the assignee-only
            # re-check (KTD7) and the empty-session guard (KTD9) itself;
            # nothing here duplicates either.
            service.close_session(approval.project_id, session, actor=user, source=self._inbound_channel)
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )

        self._emit_gate_confirmation(provider_message_id, approval, user, "gate_confirmation.session_closed")
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _handle_gate_cancel_command(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
    ) -> InboundMessage:
        session = self._open_session_for_employee(user.id)
        if session is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "You have no open evidence session to cancel.",
            )
        try:
            # The shared service owns who may cancel and the discarded state.
            GateEvidenceSessionService(self.db).discard_session(session, actor=user)
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )
        approval = self.db.get(ProjectExternalApproval, session.approval_id)
        if approval is not None:
            self._emit_gate_confirmation(
                provider_message_id, approval, user, "gate_confirmation.session_cancelled",
                {"approval_id": str(approval.id)},
            )
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _handle_gate_decide_command(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        parts: list[str],
    ) -> InboundMessage:
        """U12: role-gated to Admin/Super Admin FIRST, before the <ref> is
        even resolved or `ProjectGateDecisionService.decide` is ever called
        - a non-admin employee is rejected with a role-specific reason
        ("not available for your role") that stays distinguishable from
        BR-015's cross-identity "not available for your identity type"
        rejection (used when a vendor contact sends an employee-only
        command). This is a WhatsApp-layer pre-check for that
        distinguishable reason, not a substitute for `decide`'s own
        Admin-only `_require_approver` - which is left in place unchanged
        and still runs inside the service call below."""
        if user.role not in (UserRole.super_admin, UserRole.admin):
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "This command is not available for your role.",
            )

        if len(parts) < 3:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )

        ref = parts[1]
        decision = GATE_DECIDE_DECISION_BY_KEYWORD.get(parts[2].upper())
        if decision is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "Unrecognized command.",
            )
        reason = " ".join(parts[3:]) if len(parts) > 3 else None

        approval = self._resolve_gate_by_ref(ref)
        if approval is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", "No unique assignment matched this reference.",
            )

        try:
            # The EXACT SAME service call a portal Admin gate-decision
            # action would make - ProjectGateDecisionService.decide owns
            # its own Admin-only approver check and status/reason
            # validation itself; nothing here duplicates or narrows either.
            ProjectGateDecisionService(self.db).decide(
                approval.project_id, approval.id, decision=decision, actor=user, reason=reason,
                source=self._inbound_channel,
            )
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", str(exc.detail),
            )

        self._emit_gate_confirmation(
            provider_message_id, approval, user, "gate_confirmation.decided", {"decision": decision},
        )
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _handle_gate_session_fallback(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        media_metadata: dict | None,
    ) -> InboundMessage:
        """Neither a recognized keyword nor an empty message (see
        `_handle_employee`'s own gate above this call) - routed into the
        sender's open evidence session instead of "Unrecognized command."
        No open session is a distinct rejection reason, checked BEFORE the
        mime_type check `_handle_gate_attachment` runs (so a wrong-type
        attachment sent with no open session still reports "no session",
        never a mime-type reason)."""
        session = self._open_session_for_employee(user.id)
        if session is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", NO_OPEN_SESSION_REASON,
            )

        # Evidence is only added while the sender can still submit it: the
        # gate is still assigned to them and awaiting evidence. Otherwise it
        # would be accepted now and lost at GATECLOSE (KTD7's 403).
        approval = self.db.get(ProjectExternalApproval, session.approval_id)
        if approval is None or approval.assigned_to_user_id != user.id or approval.status != "assigned":
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", SESSION_NOT_ASSIGNED_REASON,
            )

        if media_metadata is not None:
            return self._handle_gate_attachment(
                provider_message_id, sender_phone, message_text, user, employee, session, media_metadata,
            )

        # Plain text, no keyword - appended verbatim to the session's note.
        GateEvidenceSessionService(self.db).append_text(session, message_text)
        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _handle_gate_attachment(
        self,
        provider_message_id: str,
        sender_phone: str,
        message_text: str,
        user: User,
        employee: EmployeeProfile,
        session: GateEvidenceSession,
        media_metadata: dict,
    ) -> InboundMessage:
        """KTD10/KTD18: downloads and stores one WhatsApp attachment against
        an already-open evidence session. Three distinct rejection reasons
        stay distinguishable in `InboundMessage.rejection_reason` - an
        unsupported mime_type (never even calls `download_inbound_media`),
        a download failure (U9's `ok=False`), and an oversized download
        (KTD18, discarded without ever being written to storage)."""
        mime_type = media_metadata.get("mime_type")
        if mime_type not in ALLOWED_EVIDENCE_MIME_TYPES:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", UNSUPPORTED_ATTACHMENT_REASON,
            )

        # A size the channel reports up front rejects an
        # oversized file without downloading it at all.
        declared_size = media_metadata.get("file_size")
        if isinstance(declared_size, int) and declared_size > MAX_EVIDENCE_SIZE_BYTES:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", OVERSIZED_ATTACHMENT_REASON,
            )

        download = self._download_media(media_metadata)
        if not download.ok and download.failure_code == "too_large":
            # The channel found it too large before downloading it.
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", OVERSIZED_ATTACHMENT_REASON,
            )
        if not download.ok:
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", f"{DOWNLOAD_FAILED_REASON_PREFIX}: {download.failure_reason or download.failure_code}.",
            )

        if len(download.bytes) > MAX_EVIDENCE_SIZE_BYTES:
            # KTD18: discarded, not stored - no FileObject is ever created
            # for an oversized download, mirroring the portal upload path's
            # own MAX_EVIDENCE_SIZE_BYTES rejection in
            # project_gate_submission.py.
            return self._save(
                provider_message_id, sender_phone, message_text, "employee", employee.id,
                "rejected", OVERSIZED_ATTACHMENT_REASON,
            )

        # Same write -> checksum -> FileObject sequence
        # ProjectGateSubmissionService.submit() uses for a portal upload
        # (project_gate_submission.py), reused verbatim rather than
        # re-derived - including its exact storage_key convention.
        extension = ALLOWED_EVIDENCE_MIME_TYPES[mime_type]
        storage_key = f"{session.approval_id}-{uuid.uuid4().hex}{extension}"
        evidence_storage.write(storage_key, download.bytes, mime_type)
        checksum = hashlib.sha256(download.bytes).hexdigest()
        file_object = FileObject(
            storage_key=storage_key,
            original_filename=media_metadata.get("filename") or storage_key,
            mime_type=mime_type,
            size_bytes=len(download.bytes),
            checksum=checksum,
            uploaded_by=user.id,
        )
        self.db.add(file_object)
        self.db.flush()

        service = GateEvidenceSessionService(self.db)
        service.append_attachment(session, file_object)
        # A caption sent with the file is kept in the session note, labelled
        # with the file it describes (the session has no per-file caption).
        caption = (media_metadata.get("caption") or "").strip()
        if caption:
            service.append_text(session, f"{file_object.original_filename}: {caption}")

        return self._save(
            provider_message_id, sender_phone, message_text, "employee", employee.id, "processed", None,
        )

    def _download_media(self, media_metadata: dict):
        """Fetches an attachment's bytes from the channel it arrived on
        (`MediaDownloadResult`)."""
        return download_inbound_media(media_metadata.get("id"))

    def _open_session_for_employee(self, user_id: uuid.UUID) -> GateEvidenceSession | None:
        """At most one open session per employee (KTD4's DB constraint) -
        the lookup GATECLOSE and the session-fallback routing both need,
        independent of any <ref> (GATECLOSE takes none)."""
        return self.db.scalar(
            select(GateEvidenceSession).where(
                GateEvidenceSession.employee_id == user_id,
                GateEvidenceSession.closed_at.is_(None),
                GateEvidenceSession.expired_at.is_(None),
            )
        )

    def _handle_vendor_contact(
        self, provider_message_id: str, sender_phone: str, message_text: str, vendor_contact: V2VendorContact,
    ) -> InboundMessage:
        parts = message_text.split()
        keyword = parts[0].upper() if parts else ""

        if keyword in EMPLOYEE_COMMANDS:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "This command is not available for your identity type.",
            )
        if keyword not in VENDOR_COMMANDS or len(parts) < 2:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "Unrecognized command.",
            )

        ref = parts[1]
        note = " ".join(parts[2:]) if keyword == "CLARIFY" and len(parts) > 2 else None

        assignment = self._resolve_assignment_by_ref(ref)
        if assignment is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "No unique assignment matched this reference.",
            )
        if assignment.vendor_id != vendor_contact.vendor_id:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "This assignment does not belong to your vendor.",
            )

        pm_actor = self._active_pm_user(assignment.project_id)
        if pm_actor is None:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", "No active PM on this project to record the acknowledgement.",
            )

        try:
            # The EXACT SAME service call a PM's portal acknowledgement
            # action would make - see this module's docstring for why
            # `pm_actor` (not the vendor contact, which has no User row)
            # is the correct `actor` here.
            VendorAcknowledgementService(self.db).record_acknowledgement(
                assignment.project_id, assignment.task_id, assignment.id,
                response=_RESPONSE_BY_COMMAND[keyword], actor=pm_actor, channel=self._inbound_channel, note=note,
            )
        except HTTPException as exc:
            return self._save(
                provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
                "rejected", str(exc.detail),
            )

        return self._save(
            provider_message_id, sender_phone, message_text, "vendor_contact", vendor_contact.id,
            "processed", None,
        )

    def _resolve_assignment_by_ref(self, ref: str) -> TaskVendorAssignment | None:
        ref_lower = ref.lower()
        candidates = self.db.scalars(
            select(TaskVendorAssignment).where(TaskVendorAssignment.ends_at.is_(None))
        ).all()
        matched = [
            assignment for assignment in candidates
            if str(assignment.id).replace("-", "").lower()[:8] == ref_lower
        ]
        if len(matched) != 1:
            return None
        return matched[0]

    def _resolve_gate_by_ref(self, ref: str) -> ProjectExternalApproval | None:
        """Sibling of `_resolve_assignment_by_ref` for gate approvals -
        same first-8-hex-chars-of-id convention, same ambiguity handling
        (zero or more than one match is unresolved, never heuristically
        picked). Reused by later units (U7/U10/U12)."""
        ref_lower = ref.lower()
        candidates = self.db.scalars(select(ProjectExternalApproval)).all()
        matched = [
            approval for approval in candidates
            if str(approval.id).replace("-", "").lower()[:8] == ref_lower
        ]
        if len(matched) != 1:
            return None
        return matched[0]

    def _active_pm_user(self, project_id: uuid.UUID) -> User | None:
        return active_pm_user(self.db, project_id)

    # ---- persistence --------------------------------------------------

    def _save(
        self,
        provider_message_id: str,
        sender_phone: str,
        raw_body: str,
        matched_identity_type: str | None,
        matched_identity_id: uuid.UUID | None,
        processing_status: str,
        rejection_reason: str | None,
    ) -> InboundMessage:
        row = InboundMessage(
            provider_message_id=provider_message_id,
            sender_phone=sender_phone,
            raw_body=raw_body,
            matched_identity_type=matched_identity_type,
            matched_identity_id=matched_identity_id,
            processing_status=processing_status,
            rejection_reason=rejection_reason,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
