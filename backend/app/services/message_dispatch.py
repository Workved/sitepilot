"""Phase 2 U5: message delivery tracking + provider-agnostic dispatch (R7).

`MessageDispatchService.process_pending` is an internal dispatch process
(not a user-facing portal route, so it is not actor-gated the way
`TaskLifecycleService`/`TaskVendorAssignmentService` etc. are) that reads
pending `OutboxEvent` rows (`app.execution_models.OutboxEvent`, written by
`OutboxService.emit` - see `app.services.outbox`) and attempts delivery to
every resolved recipient via a `WhatsAppProviderAdapter`.

This unit is provider-agnostic and holds no opinion on which adapter it is
given. `SandboxProviderAdapter` (below) is a deterministic fake used for
infrastructure testing - no network call, no credentials. `MessageDispatchService(db)` with no `adapter` argument defaults to it. The real
sender, `MetaCloudApiAdapter` (`app.services.whatsapp_provider`), implements
the same `WhatsAppProviderAdapter` protocol; `app.services.outbox_scheduler`
is what actually chooses between the two per pass, based on whether real
credentials are configured (`backend/app/config.py`'s
`whatsapp_access_token`/`whatsapp_phone_number_id`) - this module itself
never reads that config.

`_resolve_pm_supervisor_recipients` (and therefore `_ACCOUNTABLE_ROLES`)
structurally excludes `UserRole.super_admin`: it only ever queries
`V2ProjectMembership.project_role in ('project_manager', 'site_supervisor')`,
and `project_role` never stores `'super_admin'` (see
`app.project_models.V2ProjectMembership` - the column's only values are
`'project_manager'`, `'site_supervisor'`, `'internal_employee'`). A Super
Admin acting on a project is never a project *member* and therefore can
never be selected as a notification recipient via that path, independent of
their `User.role`.

This is narrower than a claim about `_resolve_recipients` as a whole,
though: `_resolve_admin_recipients` (Phase 1b) is a second, deliberately
separate resolver that DOES query `User.role in (admin, super_admin)`
directly - it is invoked only for an explicit allowlist of event types
(every `project_external_approval.*` event, `task.approval_recorded` via
`_ADMIN_CC_TASK_EVENTS`, and `report.weekly_summary_generated` via Phase 8's
`_ADMIN_CC_PROJECT_EVENTS`), never as a blanket widening of the PM/
Supervisor path, and never changes what `_ACCOUNTABLE_ROLES` itself means.
Admin becomes a WhatsApp *recipient* on those specific events (visibility),
never an approver - BR-008's PM-primary approval authority in
`task_approval.py` is untouched.

Recipient resolution never silently drops a project member (PM/Supervisor)
or a vendor's primary contact for lacking a phone number: it always
resolves them to a `Recipient` (using `User.phone or ""` / `contact.phone
or contact.whatsapp or ""`) and lets them reach the adapter, which then
fails deterministically with `failure_code='missing_phone'`. This is a
deliberate deviation from an earlier draft of this unit's Approach notes,
which described silently skipping a phone-less recipient at resolution
time with "no delivery attempt for them, don't error". Two things pushed
this to resolve-then-fail instead: (1) the plan's own test scenarios
(a retry test that expects a first, failing `process_pending()` pass
against a recipient with no phone, and an error-path test that expects an
explicit `status='failed'` `MessageDelivery` row for exactly that
recipient) are only satisfiable if the recipient is actually resolved and
reaches the adapter - a silently-skipped recipient leaves no row and
nothing to retry; and (2) it is the better design regardless: a silently
dropped recipient leaves no queryable trace that a PM/Supervisor/vendor
contact couldn't be reached, whereas a `'failed'` row with
`failure_code='missing_phone'` is visible and actionable to ops. A
genuinely unresolvable recipient (no `EmployeeProfile` link, or no primary
vendor contact at all) is still skipped, since there is no row to even
construct in that case.

Idempotency / retry: `process_pending` never creates a second
`MessageDelivery` row for the same
(outbox_event_id, recipient, template) - see the unique index in
`supabase/migrations/202608040005_v2_message_deliveries.sql`. A recipient
whose prior attempt is `'failed'` is retried in place (existing row,
incremented `attempt_count`) rather than duplicated. A `'sent'`/
`'delivered'`/`'read'` prior attempt is left alone (already succeeded).

Outbox event re-selection: `process_pending` selects `OutboxEvent` rows
that are `status = 'pending'` OR are `status = 'dispatched'` but still have
at least one `MessageDelivery` row `status = 'failed'` against them - this
is a deliberate small widening of the plan's literal "query rows with
status='pending'" Approach note, needed to reconcile two requirements that
are otherwise in tension: (a) an event is marked `'dispatched'` after every
recipient has been attempted once, regardless of individual outcomes (so a
failed delivery to one recipient never blocks the others, and never leaves
the outbox event itself stuck mid-processing on a crash), and (b) a later
`process_pending()` call must still be able to retry a recipient whose
delivery previously failed (e.g. once their phone number is corrected).
Purely `'pending'`-only re-selection would satisfy (a) but never retry
anything after the first pass; this widened predicate satisfies both,
while a `'dispatched'` event with no failed deliveries is never
re-selected - so re-running `process_pending()` immediately after a fully
successful batch is still a safe no-op that creates zero new rows, exactly
as the plan's verification test scenario expects.

Not every failed delivery is retried every pass, though: a failure caused by
the recipient having no address on their channel (`missing_chat_id`,
`missing_phone`) is only retried once they are reachable again, a template
rejection (`_PERMANENT_FAILURE_CODES`) is never retried, nothing is retried
more than `_MAX_DELIVERY_ATTEMPTS` times, and retries run fewest-attempts
first - see `_select_events`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import (
    FileObject,
    MessageDelivery,
    OutboxEvent,
    ProjectExternalApproval,
    Task,
    TaskSupportAssignment,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2ProjectMembership
from app.services import evidence_storage
from app.services.message_templates import TemplateSpec, render_components, resolve
from app.services.task_approval import TaskApprovalService
from app.services.task_lifecycle import latest_submitter_user_id
from app.services.telegram_render import render_telegram
from app.services.whatsapp_template_fields import template_fields
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2VendorContact

logger = logging.getLogger(__name__)

# Sent as Telegram photos; any other evidence type (WebP, PDF) goes as a
# document, which Telegram shows as a downloadable file.
_TELEGRAM_PHOTO_MIME_TYPES = frozenset({"image/jpeg", "image/png"})

# The only two `V2ProjectMembership.project_role` values this service ever
# treats as notification recipients. `'super_admin'` is deliberately never
# in this tuple (and is not even a value `project_role` can hold - see the
# module docstring) - this is the structural proof R7 relies on.
_ACCOUNTABLE_ROLES = ("project_manager", "site_supervisor")

_SUCCEEDED_STATUSES = ("sent", "delivered", "read")

# Failures caused by the recipient having no address on their current channel
# (no Telegram chat linked / no phone on file). Retrying them cannot succeed
# until that changes, so they are only retried once the recipient is
# reachable again - see `_select_events`.
_UNREACHABLE_FAILURE_CODES = ("missing_chat_id", "missing_phone", "recipient_offboarded")

# Failures that resending the same message can never fix: a `TBD_`
# placeholder template, or Meta rejecting the template itself (missing /
# unapproved template, wrong parameter count or format). They need a fix in
# Meta Business Manager or the code, not another attempt every 30 seconds.
_PERMANENT_FAILURE_CODES = (
    "template_unapproved",
    "100",     # invalid parameter
    "131008",  # required parameter missing
    "131009",  # parameter value invalid
    "132000",  # parameter count mismatch
    "132001",  # template does not exist (name or language)
    "132005",  # translated text too long
    "132007",  # template format policy violation
    "132012",  # parameter format mismatch
    "132015",  # template paused
    "132016",  # template disabled
)

# Any other failure (network errors, Meta 5xx, rate limits) is retried on
# later passes, but only this many times in total per delivery.
_MAX_DELIVERY_ATTEMPTS = 5

# Phase 1b (locked decision #1): Class A approval decisions are the one
# task-event class where Admin becomes a CC recipient - visibility only,
# never authority. BR-008's PM-primary approve/reject flow in
# task_approval.py is unchanged; this only widens who is *notified* of the
# outcome it already decided. Deliberately narrow - do not add every task
# event here.
#
# Phase 6 adds `task.escalated_to_admin` (`EscalationService.
# sweep_task_escalations`): a task that reaches the admin-escalation stage
# is, by definition, an Admin-visibility event - the same "visibility, not
# authority" rationale as the Class A decision above.
_ADMIN_CC_TASK_EVENTS = {"task.approval_recorded", "task.escalated_to_admin"}

# Plan Phase 8: mirrors `_ADMIN_CC_TASK_EVENTS`'s exact pattern for the
# `project` aggregate branch. Deliberately a narrow allowlist, not a
# blanket "every project.* event reaches Admin" widening - the plan's own
# framing is that Admin is pushed the weekly summary specifically, not
# every project-aggregate event `_resolve_pm_supervisor_recipients` already
# reaches PM/Supervisor for.
_ADMIN_CC_PROJECT_EVENTS = {"report.weekly_summary_generated"}

# Phase 7: the four daily-prompt event types `daily_task_prompts.py` emits.
# Per the doc's own §5-§6 readiness/start/midday/EOD templates, the assigned
# Internal Employee is a receiver on all four - unlike the vendor-eligible
# set below, this one is not narrowed to exclude the EOD check.
_EMPLOYEE_ELIGIBLE_TASK_EVENTS: set[str] = {
    "task.readiness_check",
    "task.start_check",
    "task.midday_check",
    "task.eod_check",
}

# Gate command confirmations whose sender is always also a recipient of the
# paired main event (GATEACCEPT/GATEDECLINE -> `.accepted`/`.declined`,
# GATESTATUS -> `.status_checked`, GATECLOSE -> `.submitted`: the assignee;
# GATEDECIDE -> `.decided`: every Admin, including the sender). On Telegram
# the main event's recipient-specific message already confirms the action, so
# these would be a second message to the same person for the same action.
# `gate_confirmation.session_opened` has no paired event and is still sent.
# WhatsApp delivery of these confirmations is unchanged.
_TELEGRAM_REDUNDANT_GATE_CONFIRMATIONS = frozenset({
    "gate_confirmation.accepted",
    "gate_confirmation.declined",
    "gate_confirmation.status_recorded",
    "gate_confirmation.session_closed",
    "gate_confirmation.decided",
})

# Telegram task plan KTD11 - Telegram-only noise rules for task execution:
# every progress item (`task.evidence_submitted`) would otherwise be its own
# message to the reviewers, and a verification/approval decision drives
# several intermediate status changes (submitted -> rejected -> in_progress)
# whose outcome the decision's own event already tells everyone. Those status
# rows carry `cause: "decision"` (task_lifecycle.transition). WhatsApp
# delivery of both is unchanged.
_TELEGRAM_SKIPPED_TASK_EVENTS = frozenset({"task.evidence_submitted"})

# Events whose outcome the people doing the work must hear themselves
# (KTD10): see `_resolve_execution_participants`.
_EXECUTION_OUTCOME_EVENTS = frozenset({
    "task.status_changed",
    "task.verification_recorded",
    "task.approval_recorded",
})

# Telegram T3/T5 reminders that go to their own audience instead of the
# default PM/Supervisor set: the pre-start warning to the assignee, the
# Supervisor and the vendor delegated to the task, the overdue warning to the assignee (the Supervisor when nobody
# is assigned), the overdue escalation to the PM and Admins.
_REMINDER_AUDIENCES: dict[str, frozenset[str]] = {
    "task.prestart_warning": frozenset({"assignee", "supervisor", "vendor"}),
    "task.sla_overdue": frozenset({"assignee", "supervisor_if_unassigned"}),
    "task.sla_escalated": frozenset({"pm", "admin"}),
}

# Gate events whose payload names a previous assignee who must also be told
# they are no longer responsible - by dispatch time the gate's current
# assignee is already someone else (reassign) or nobody (unassign).
_GATE_PREVIOUS_ASSIGNEE_EVENTS = frozenset({
    "project_external_approval.reassigned",
    "project_external_approval.unassigned",
})

# Support-assignment events and the payload keys naming the employee(s) they
# directly affect - each is notified in addition to the PM/Supervisor.
_SUPPORT_ASSIGNMENT_EMPLOYEE_KEYS: dict[str, tuple[str, ...]] = {
    "task.support_assigned": ("employee_id",),
    "task.support_ended": ("previous_employee_id", "replacement_employee_id"),
}

# Vendors get exactly three kinds of message: their project assignment
# (`project.activated` / their own `project.vendor_mapped`), their task
# assignment (`task.vendor_assigned`), and one reminder the day before the
# task (`task.prestart_warning`, see `_REMINDER_AUDIENCES`) - plus the notice
# when they are removed. No daily checks, delays or team news.

# U1: the three `project`-aggregate event types (not emitted until later
# units - see this unit's own plan note) whose audience is "every active
# project member regardless of role, plus every vendor mapped to the
# project" rather than the default PM/Supervisor-only audience. This is a
# branch, not an addition: for these event types,
# `_resolve_all_project_members` + `_resolve_all_project_vendors` are called
# INSTEAD OF `_resolve_pm_supervisor_recipients` (whose entire result is
# already a subset of `_resolve_all_project_members`'s), so a project-
# activation-shaped event never resolves PM/Supervisor twice - see
# `_resolve_recipients`'s `project` branch.
_ALL_MEMBERS_PROJECT_EVENTS: set[str] = {
    "project.activated",
    "project.member_added",
    "project.vendor_mapped",
}


@dataclass(frozen=True)
class ProviderSendResult:
    """Outcome of one `WhatsAppProviderAdapter.send(...)` attempt."""

    ok: bool
    provider_message_id: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class Recipient:
    """One resolved notification target. Exactly one of `employee_id` /
    `vendor_contact_id` is set, mirroring `MessageDelivery`'s own
    real-FK-pair recipient columns.

    `channel` (U5, KTD5) defaults to `'whatsapp'` so no existing
    construction site needs to change yet - it is populated from the
    recipient's `active_channel` column starting in U8/U9, not here."""

    employee_id: uuid.UUID | None
    vendor_contact_id: uuid.UUID | None
    phone: str
    channel: str = "whatsapp"


def _skipped_on_telegram(event: OutboxEvent) -> bool:
    """Events a Telegram recipient never gets, because another message they
    receive already covers them (gate confirmations: the paired gate event;
    progress items and decision-driven status steps: KTD11)."""
    if event.event_type in _TELEGRAM_REDUNDANT_GATE_CONFIRMATIONS or event.event_type in _TELEGRAM_SKIPPED_TASK_EVENTS:
        return True
    return event.event_type == "task.status_changed" and (event.payload or {}).get("cause") == "decision"


def _unique_recipients(recipients: list[Recipient]) -> list[Recipient]:
    """One entry per person, first occurrence kept - e.g. a Supervisor who
    submitted the task is both an accountable member and a participant."""
    seen: set[tuple[uuid.UUID | None, uuid.UUID | None]] = set()
    unique = []
    for recipient in recipients:
        key = (recipient.employee_id, recipient.vendor_contact_id)
        if key not in seen:
            seen.add(key)
            unique.append(recipient)
    return unique


class WhatsAppProviderAdapter(Protocol):
    """Provider-agnostic send interface. A real adapter (Meta/WABA, etc.)
    implements this same shape; `MessageDispatchService` never depends on
    provider-specific details beyond this method."""

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult: ...


class SandboxProviderAdapter:
    """Deterministic fake provider for infra testing - no real network
    call, no real credentials. Succeeds for any non-empty
    `recipient_phone`; fails with `failure_code='missing_phone'` when the
    phone is falsy, which is this unit's only controllable way to exercise
    the failure path without real network mocking."""

    provider_name = "sandbox"

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
        if not recipient_phone:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_phone",
                failure_reason="Recipient has no phone number on file.",
            )
        return ProviderSendResult(ok=True, provider_message_id=f"sandbox-{uuid.uuid4().hex}")


class MessageDispatchService:
    def __init__(self, db: Session, adapter: WhatsAppProviderAdapter | None = None):
        self.db = db
        self.adapter = adapter or SandboxProviderAdapter()
        # U9 (KTD4): channel -> adapter mapping, replacing `self.adapter` as
        # dispatch's actual send target - `_dispatch_to_recipient` looks up
        # the adapter here by the recipient's resolved channel instead of
        # always using `self.adapter` directly. Built here, not as a new
        # `__init__` parameter, so `outbox_scheduler.run_dispatch_pass`'s
        # call site (`MessageDispatchService(db, adapter=_build_adapter())`)
        # does not need to change - `_build_adapter()` still decides which
        # real-vs-sandbox WhatsApp adapter to use, unchanged, and simply
        # becomes the `'whatsapp'` slot of this mapping. `self.adapter` is
        # kept as the fallback for an unrecognized channel value.
        # U10: registers the Telegram adapter as a real option in this
        # mapping, keyed 'telegram'. Instantiated unconditionally (like
        # `SandboxProviderAdapter()` above) - `TelegramProviderAdapter`
        # itself fails fast at `.send()` time (`failure_code='not_configured'`)
        # when no token is set, not at construction time, so this is safe
        # even with no Telegram credentials configured.
        #
        # Imported here, not at module level: `telegram_provider.py`
        # imports `ProviderSendResult` from this module, so a top-level
        # import here would be circular.
        from app.services.telegram_provider import TelegramProviderAdapter

        self._adapters: dict[str, WhatsAppProviderAdapter] = {
            "whatsapp": self.adapter,
            "telegram": TelegramProviderAdapter(),
        }

    # ---- recipient resolution -------------------------------------------

    def _resolve_pm_supervisor_recipients(self, project_id: uuid.UUID) -> list[Recipient]:
        rows = self.db.execute(
            select(V2ProjectMembership.employee_id, User.phone)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role.in_(_ACCOUNTABLE_ROLES),
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
            )
        ).all()
        # Every active PM/Supervisor member is resolved to a Recipient
        # regardless of phone - see the module docstring's "recipient
        # resolution never silently drops..." note. A missing phone
        # becomes an explicit, queryable failed delivery instead of a
        # silent no-op.
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

    def _resolve_all_project_members(self, project_id: uuid.UUID) -> list[Recipient]:
        """U1: every active project member regardless of `project_role` -
        follows `_resolve_pm_supervisor_recipients`'s exact shape, but with
        no `project_role` filter (only `ends_at IS NULL` and `User.active`),
        so its result is a strict superset of what a plain
        `_resolve_pm_supervisor_recipients` call for the same project would
        return. Used for the handful of `project`-aggregate event types
        (`_ALL_MEMBERS_PROJECT_EVENTS`) whose audience is "every project
        member", not just PM/Supervisor - see `_resolve_recipients`'s
        `project` branch for why this replaces rather than adds to that call
        for those event types."""
        rows = self.db.execute(
            select(V2ProjectMembership.employee_id, User.phone)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
            )
        ).all()
        # Same resolve-then-fail-visibly discipline as
        # `_resolve_pm_supervisor_recipients`: a missing phone still becomes
        # a Recipient, surfacing as a queryable failed delivery rather than
        # a silent skip.
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

    def _resolve_all_project_vendors(self, project_id: uuid.UUID) -> list[Recipient]:
        """U1: every vendor mapped to the project (`ProjectVendor`, R2),
        resolved to its primary contact via `_primary_vendor_contact_recipient`.
        A mapped vendor with no primary contact is skipped - same "not an
        error" precedent `_primary_vendor_contact_recipient` already
        documents (a genuinely unresolvable recipient, no row to construct).
        A project with no mapped vendors returns `[]`, not an error."""
        vendor_ids = self.db.scalars(
            select(ProjectVendor.vendor_id).where(
                ProjectVendor.project_id == project_id, ProjectVendor.ends_at.is_(None),
            )
        ).all()
        recipients: list[Recipient] = []
        for vendor_id in vendor_ids:
            recipient = self._primary_vendor_contact_recipient(vendor_id)
            if recipient is not None:
                recipients.append(recipient)
        return recipients

    def _primary_vendor_contact_recipient(self, vendor_id: uuid.UUID) -> Recipient | None:
        """Shared tail of vendor recipient resolution: given a `vendor_id`,
        find its primary `V2VendorContact` and build a `Recipient`. Used by
        both `_resolve_vendor_recipient` (payload-driven, `task.
        vendor_assigned`) and `_resolve_vendor_recipient_for_task`
        (lookup-driven, Phase 7's readiness/start/midday checks)."""
        contact = self.db.scalar(
            select(V2VendorContact).where(
                V2VendorContact.vendor_id == vendor_id,
                V2VendorContact.is_primary.is_(True),
            )
        )
        if contact is None:
            return None
        # As with PM/Supervisor resolution: resolve regardless of phone,
        # using phone falling back to whatsapp, falling back to "" - a
        # missing number surfaces as a failed delivery, not a silent skip.
        phone = contact.phone or contact.whatsapp or ""
        return Recipient(employee_id=None, vendor_contact_id=contact.id, phone=phone)

    def _resolve_vendor_recipient(self, event: OutboxEvent) -> Recipient | None:
        """Called for `task.vendor_assigned`/`task.vendor_unassigned` and
        `project.vendor_removed`. Reads `vendor_id` directly off the payload
        (the shape `TaskVendorAssignmentService`/`ProjectVendorService`
        actually write - always includes a `vendor_id` key), with a
        fallback re-derivation via `assignment_id` for robustness against a
        future payload shape change.

        Deliberately does NOT go through `_resolve_all_project_vendors` (or
        any other "currently active" vendor query): by the time a removal/
        unassignment event dispatches, the departing vendor's mapping or
        assignment row already has `ends_at` set, so an "active vendors"
        query would exclude the very person this event needs to reach."""
        payload = event.payload or {}
        vendor_id_raw = payload.get("vendor_id")
        if not vendor_id_raw:
            assignment_id_raw = payload.get("assignment_id")
            if assignment_id_raw:
                assignment = self.db.get(TaskVendorAssignment, uuid.UUID(assignment_id_raw))
                if assignment is not None:
                    vendor_id_raw = str(assignment.vendor_id)
        if not vendor_id_raw:
            return None

        return self._primary_vendor_contact_recipient(uuid.UUID(vendor_id_raw))

    def _resolve_vendor_recipient_for_task(self, task: Task) -> Recipient | None:
        """Lookup-driven vendor resolution for the vendor's day-before
        reminder (`task.prestart_warning`). Unlike `_resolve_vendor_recipient`,
        a reminder's payload (written by `TaskReminderService`) carries no
        vendor info at all, since the reminder sweep doesn't know per-task
        vendor assignment without querying for it.

        "Active" here mirrors `vendor_acknowledgement.py`'s
        `RESOLVED_ASSIGNMENT_STATUSES` framing in reverse: a
        `TaskVendorAssignment` is still "the vendor is involved" as long as
        it hasn't been explicitly `declined` - `pending_ack` (not yet
        responded) and `acknowledged` (accepted) both count. When more than
        one non-declined assignment exists on the same task (e.g. a re-
        delegation), the most recently created one wins.

        Returns `None` (not an error) when the task has no active vendor
        assignment or that vendor has no primary contact - "vendor not
        involved" is the normal case for most tasks, per the doc's "if
        involved" language."""
        assignment = self.db.scalar(
            select(TaskVendorAssignment)
            .where(
                TaskVendorAssignment.task_id == task.id,
                TaskVendorAssignment.status != "declined",
                TaskVendorAssignment.ends_at.is_(None),
            )
            .order_by(TaskVendorAssignment.created_at.desc())
            .limit(1)
        )
        if assignment is None:
            return None
        return self._primary_vendor_contact_recipient(assignment.vendor_id)

    def _resolve_admin_recipients(self) -> list[Recipient]:
        """All active users with `role in (admin, super_admin)`. Deliberately
        "all admins" - there is no per-project Admin assignment anywhere in
        the schema (`V2ProjectMembership.project_role` cannot hold
        `'admin'`/`'super_admin'` - see the module docstring) to narrow this
        to project scope, so every project's `project_external_approval.*`
        event and every `task.approval_recorded` event notifies the same
        Admin set. This is a locked decision (plan Decisions section), not
        an oversight.

        Follows the same resolve-then-fail-visibly pattern as
        `_resolve_pm_supervisor_recipients`/`_resolve_vendor_recipient`: an
        Admin with no phone on file is still resolved to a `Recipient` and
        reaches the adapter, surfacing as an explicit `failed`/
        `missing_phone` delivery row rather than silently vanishing.
        """
        rows = self.db.execute(
            select(EmployeeProfile.id, User.phone)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(User.role.in_((UserRole.admin, UserRole.super_admin)), User.active.is_(True))
        ).all()
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

    def _resolve_gate_assignee_recipient(self, approval: ProjectExternalApproval) -> list[Recipient]:
        """Resolves a `project_external_approval` gate's own assignee
        (`assigned_to_user_id`) to a `Recipient`. Returns `[]` - a genuinely
        unresolvable recipient, skipped rather than resolved-then-failed,
        matching this module's own precedent for "no row to even construct"
        cases (see `_resolve_vendor_recipient`'s `None` returns) - when the
        gate has no assignee yet (`unassigned` status) or the assignee's
        `EmployeeProfile`/`User` link can't be found."""
        if approval.assigned_to_user_id is None:
            return []
        employee = self.db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == approval.assigned_to_user_id)
        )
        if employee is None:
            return []
        user = self.db.get(User, approval.assigned_to_user_id)
        if user is None or not user.active:
            return []
        return [Recipient(employee_id=employee.id, vendor_contact_id=None, phone=user.phone or "")]

    def _resolve_role_recipients(self, project_id: uuid.UUID, roles: tuple[str, ...]) -> list[Recipient]:
        rows = self.db.execute(
            select(V2ProjectMembership.employee_id, User.phone)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role.in_(roles),
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
            )
        ).all()
        return [Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "") for employee_id, phone in rows]

    def _resolve_reminder_audience(self, task: Task, event_type: str) -> list[Recipient]:
        """Telegram T3/T5 reminders with their own audience (see
        `_REMINDER_AUDIENCES`), still limited to active project members; the
        escalation's Admin copy is added after that filter, as for every other
        Admin copy (visibility, not membership)."""
        audience = _REMINDER_AUDIENCES[event_type]
        recipients: list[Recipient] = []
        if "assignee" in audience:
            recipients.extend(self._resolve_internal_employee_recipient(task))
        if "supervisor" in audience or ("supervisor_if_unassigned" in audience and not recipients):
            recipients.extend(self._resolve_role_recipients(task.project_id, ("site_supervisor",)))
        if "pm" in audience:
            recipients.extend(self._resolve_role_recipients(task.project_id, ("project_manager",)))
        recipients = self._only_active_project_members(task.project_id, recipients)
        if "vendor" in audience:
            vendor_recipient = self._resolve_vendor_recipient_for_task(task)
            if vendor_recipient is not None:
                recipients.append(vendor_recipient)
        if "admin" in audience:
            recipients.extend(self._resolve_admin_recipients())
        return _unique_recipients(recipients)

    def _resolve_internal_employee_recipient(self, task: Task) -> list[Recipient]:
        """Resolves every active `TaskSupportAssignment` on `task` to its
        employee's `Recipient`. Scaffolded in Phase 1, wired up in Phase 7 -
        called for every event type in `_EMPLOYEE_ELIGIBLE_TASK_EVENTS`
        (the four daily-prompt events: readiness/start/midday/EOD)."""
        rows = self.db.execute(
            select(EmployeeProfile.id, User.phone)
            .join(User, User.id == EmployeeProfile.user_id)
            .join(TaskSupportAssignment, TaskSupportAssignment.employee_id == EmployeeProfile.id)
            .where(
                TaskSupportAssignment.task_id == task.id,
                TaskSupportAssignment.status == "active",
                User.active.is_(True),
            )
        ).all()
        return [
            Recipient(employee_id=employee_id, vendor_contact_id=None, phone=phone or "")
            for employee_id, phone in rows
        ]

    def _resolve_execution_participants(self, task: Task) -> list[Recipient]:
        """The people doing the work on `task`: every active support assignee
        plus whoever submitted it for review (e.g. a Supervisor who executed
        it themselves). They are told status changes and review outcomes, not
        only the PM/Supervisor (Telegram task plan KTD10)."""
        recipients = self._resolve_internal_employee_recipient(task)
        submitter_user_id = latest_submitter_user_id(self.db, task.id)
        if submitter_user_id is not None:
            recipients.extend(self._resolve_user_id_recipient(submitter_user_id))
        return recipients

    def _submission_needs_admin_reviewer(self, task: Task, event: OutboxEvent) -> bool:
        """Telegram task plan KTD20: a submission's review request also goes
        to Admins when nobody on the project can act on it - for work, no
        active Supervisor/PM other than the submitter (who may not verify their
        own work); for an approval-gate task, no active PM. Admin keeps their
        existing authority either way; this only decides who is asked."""
        payload = event.payload or {}
        if event.event_type != "task.status_changed" or payload.get("target_status") != "submitted":
            return False
        if payload.get("cause") == "decision":
            return False
        roles = ("project_manager",) if task.task_kind == "approval_gate" else _ACCOUNTABLE_ROLES
        query = (
            select(V2ProjectMembership.id)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_id == task.project_id,
                V2ProjectMembership.project_role.in_(roles),
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
            )
        )
        submitter = payload.get("submitted_by") or payload.get("actor_user_id")
        if submitter and task.task_kind != "approval_gate":
            query = query.where(User.id != uuid.UUID(str(submitter)))
        return self.db.scalar(query.limit(1)) is None

    def _approval_needs_admin(self, task: Task, event: OutboxEvent) -> bool:
        """Telegram task plan KTD20 (U10): a class_a verification opens the PM
        approval step. If no PM may approve it - none on the project, or the
        only one verified as a fallback and so may not also approve - the
        request goes to Admins. If no Admin may either, the state is logged
        explicitly (the ineligible PM's own message says so too) rather than
        the request silently reaching nobody who can act."""
        payload = event.payload or {}
        if event.event_type != "task.verification_recorded" or payload.get("decision") != "verified":
            return False
        if task.task_kind == "approval_gate" or task.task_class != "class_a":
            return False
        approvals = TaskApprovalService(self.db)
        if approvals.eligible_pm_user_ids(task):
            return False
        if not approvals.has_eligible_admin(task):
            logger.warning(
                "no_eligible_approver: task %s (project %s) is verified and awaiting approval, "
                "but no PM or Admin other than the fallback verifier can approve it.",
                task.original_code, task.project_id,
            )
        return True

    def _only_active_project_members(self, project_id: uuid.UUID, recipients: list[Recipient]) -> list[Recipient]:
        """Task messages reach only people still on the project: an active
        user with an active membership (Telegram task plan R20). Vendor
        contacts are resolved by their own rules and pass through unchanged."""
        member_employee_ids = set(self.db.scalars(
            select(V2ProjectMembership.employee_id)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.ends_at.is_(None),
                User.active.is_(True),
            )
        ))
        return [r for r in recipients if r.employee_id is None or r.employee_id in member_employee_ids]

    def _resolve_payload_employee_recipient(self, event: OutboxEvent, key: str) -> list[Recipient]:
        """Resolves the `EmployeeProfile` id stored under `payload[key]` to a
        `Recipient`. `[]` when the key is missing/null or the employee can't
        be found - same skip-not-fail precedent as `_resolve_user_recipient`."""
        employee_id_raw = (event.payload or {}).get(key)
        if not employee_id_raw:
            return []
        employee = self.db.get(EmployeeProfile, uuid.UUID(str(employee_id_raw)))
        if employee is None:
            return []
        user = self.db.get(User, employee.user_id)
        if user is None or not user.active:
            return []
        return [Recipient(employee_id=employee.id, vendor_contact_id=None, phone=user.phone or "")]

    def _resolve_user_id_recipient(self, user_id_raw: object) -> list[Recipient]:
        """Resolves one `User.id` (as stored in an event payload) to that
        user's employee `Recipient`. `[]` when the id is missing or has no
        active `EmployeeProfile`/`User` - same skip-not-fail precedent as
        `_resolve_user_recipient`."""
        if not user_id_raw:
            return []
        user_id = uuid.UUID(str(user_id_raw))
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
        user = self.db.get(User, user_id)
        if employee is None or user is None or not user.active:
            return []
        return [Recipient(employee_id=employee.id, vendor_contact_id=None, phone=user.phone or "")]

    def _resolve_user_recipient(self, event: OutboxEvent) -> list[Recipient]:
        """U13: resolves a `user`-aggregate event (`user.created`/
        `user.offboarded`) straight to the one `User` named by the payload's
        `user_id` - the affected user themselves, never the actor who
        performed the invite/offboard action. Single-recipient resolution,
        mirroring `_resolve_gate_assignee_recipient`'s shape for "resolve
        exactly one specific person": `[]` (skipped, not resolved-then-
        failed) when `user_id` is missing from the payload or the user has
        no `EmployeeProfile`/`User` row to resolve - a genuinely
        unresolvable recipient, same precedent as the gate resolver's
        `unassigned`/missing-link cases.

        A resolvable user with no phone on file is still returned as a
        `Recipient` (phone `""`) - same resolve-then-fail-visibly
        discipline as every other resolver in this module: a missing phone
        surfaces as an explicit `failed`/`missing_phone` delivery, not a
        silent skip."""
        user_id_raw = (event.payload or {}).get("user_id")
        if not user_id_raw:
            return []
        user_id = uuid.UUID(user_id_raw)
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
        if employee is None:
            return []
        user = self.db.get(User, user_id)
        if user is None:
            return []
        return [Recipient(employee_id=employee.id, vendor_contact_id=None, phone=user.phone or "")]

    def _resolve_command_actor_recipient(self, event: OutboxEvent) -> list[Recipient]:
        """U15: resolves a `gate_command_confirmation`-aggregate event
        (the six `gate_confirmation.*` types) straight to the one `User`
        named by the payload's `actor_user_id` - the employee/Admin who
        actually sent the WhatsApp gate command being confirmed, never
        Admin as a fixed role-based set the way `project_external_approval.*`
        events resolve them via `_resolve_admin_recipients`. Same
        single-recipient shape as `_resolve_user_recipient` (U13), keyed on
        `actor_user_id` instead of `user_id` since this aggregate has no
        `user`-shaped payload of its own: `[]` (skipped, not resolved-then-
        failed) when `actor_user_id` is missing or unresolvable, same
        precedent as `_resolve_user_recipient`'s own missing-link cases.

        A resolvable actor with no phone on file is still returned as a
        `Recipient` (phone `""`) - same resolve-then-fail-visibly
        discipline as every other resolver in this module: a missing phone
        surfaces as an explicit `failed`/`missing_phone` delivery, not a
        silent skip."""
        actor_user_id_raw = (event.payload or {}).get("actor_user_id")
        if not actor_user_id_raw:
            return []
        actor_user_id = uuid.UUID(actor_user_id_raw)
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor_user_id))
        if employee is None:
            return []
        user = self.db.get(User, actor_user_id)
        if user is None:
            return []
        return [Recipient(employee_id=employee.id, vendor_contact_id=None, phone=user.phone or "")]

    def _resolve_recipients(self, event: OutboxEvent) -> list[Recipient]:
        recipients: list[Recipient] = []
        if event.aggregate_type == "task":
            task = self.db.get(Task, event.aggregate_id)
            if task is None:
                return []
            if event.event_type in _REMINDER_AUDIENCES:
                return self._resolve_reminder_audience(task, event.event_type)
            recipients.extend(self._resolve_pm_supervisor_recipients(task.project_id))
            if event.event_type in ("task.vendor_assigned", "task.vendor_unassigned"):
                vendor_recipient = self._resolve_vendor_recipient(event)
                if vendor_recipient is not None:
                    recipients.append(vendor_recipient)
            if event.event_type in _EMPLOYEE_ELIGIBLE_TASK_EVENTS:
                recipients.extend(self._resolve_internal_employee_recipient(task))
            if event.event_type in _SUPPORT_ASSIGNMENT_EMPLOYEE_KEYS:
                # The employee being assigned/ended must hear about it
                # themselves, not only their PM/Supervisor. Resolved from the
                # payload (not active TaskSupportAssignment rows), since an
                # ended assignment is already inactive by dispatch time.
                for key in _SUPPORT_ASSIGNMENT_EMPLOYEE_KEYS[event.event_type]:
                    for recipient in self._resolve_payload_employee_recipient(event, key):
                        if all(r.employee_id != recipient.employee_id for r in recipients):
                            recipients.append(recipient)
            if event.event_type == "task.blocker_resolved":
                # Telegram task plan U12: whoever reported the blocker is told
                # it was resolved (still subject to the active-member filter).
                recipients.extend(self._resolve_user_id_recipient((event.payload or {}).get("reported_by")))
            if event.event_type == "task.delay_recorded":
                # A delay must reach everyone actually working this task, not
                # just its PM/Supervisor: any Internal Employee support-
                # assigned to it. Vendors are not told (vendor message rule).
                recipients.extend(self._resolve_internal_employee_recipient(task))
            if event.event_type in _EXECUTION_OUTCOME_EVENTS:
                recipients.extend(self._resolve_execution_participants(task))
            recipients = self._only_active_project_members(task.project_id, recipients)
            if event.event_type in _ADMIN_CC_TASK_EVENTS:
                # Added after the membership filter: Admin has no project
                # membership, and this copy is visibility, not authority.
                recipients.extend(self._resolve_admin_recipients())
            elif self._submission_needs_admin_reviewer(task, event) or self._approval_needs_admin(task, event):
                recipients.extend(self._resolve_admin_recipients())
            recipients = _unique_recipients(recipients)
        elif event.aggregate_type == "project":
            if event.event_type == "project.vendor_removed":
                # Deliberately NOT the default PM/Supervisor-only branch
                # below: this event's only intended recipient is the vendor
                # being removed (product decision - no team-wide notice for
                # a vendor removal). Resolved straight from the payload, not
                # `_resolve_all_project_vendors`, since that query excludes
                # this vendor the moment its mapping's `ends_at` is set.
                vendor_recipient = self._resolve_vendor_recipient(event)
                if vendor_recipient is not None:
                    recipients.append(vendor_recipient)
            elif event.event_type in _ALL_MEMBERS_PROJECT_EVENTS:
                # Branch, not addition: `_resolve_all_project_members`'s
                # result already includes every PM/Supervisor
                # `_resolve_pm_supervisor_recipients` would have found, so
                # calling both here would resolve PM/Supervisor twice -
                # risking a real duplicate send if a retry pass re-resolves
                # a first attempt that failed (see `_ALL_MEMBERS_PROJECT_EVENTS`'s
                # comment).
                recipients.extend(self._resolve_all_project_members(event.aggregate_id))
                # Vendors hear only about their own project assignment: every
                # mapped vendor on activation, and only the vendor just
                # mapped on `project.vendor_mapped` - never team news.
                if event.event_type == "project.activated":
                    recipients.extend(self._resolve_all_project_vendors(event.aggregate_id))
                elif event.event_type == "project.vendor_mapped":
                    vendor_recipient = self._resolve_vendor_recipient(event)
                    if vendor_recipient is not None:
                        recipients.append(vendor_recipient)
            else:
                recipients.extend(self._resolve_pm_supervisor_recipients(event.aggregate_id))
            recipients = self._only_active_project_members(event.aggregate_id, recipients)
            if event.event_type in _ADMIN_CC_PROJECT_EVENTS:
                recipients.extend(self._resolve_admin_recipients())
            recipients = _unique_recipients(recipients)
        elif event.aggregate_type == "project_external_approval":
            approval = self.db.get(ProjectExternalApproval, event.aggregate_id)
            if approval is None:
                return []
            recipients.extend(self._resolve_gate_assignee_recipient(approval))
            if event.event_type in _GATE_PREVIOUS_ASSIGNEE_EVENTS:
                for recipient in self._resolve_user_id_recipient((event.payload or {}).get("previous_assignee_id")):
                    if all(r.employee_id != recipient.employee_id for r in recipients):
                        recipients.append(recipient)
            # Every project_external_approval.* event resolves Admin - this
            # is where doc #27's "Admin review-required push" falls out of,
            # `submitted` included (Phase 1b).
            recipients.extend(self._resolve_admin_recipients())
        elif event.aggregate_type == "user":
            # U13: `user.created`/`user.offboarded` - single-recipient,
            # resolving straight to the affected user themselves (R13), not
            # any role-based set.
            recipients.extend(self._resolve_user_recipient(event))
        elif event.aggregate_type == "gate_command_confirmation":
            # U15: the six `gate_confirmation.*` events - single-recipient,
            # resolving straight back to whoever sent the WhatsApp gate
            # command (`payload["actor_user_id"]`), never Admin. Distinct
            # from the `project_external_approval` branch above, which
            # resolves the gate's assignee plus Admin for U5's Admin-facing
            # `.accepted`/`.declined` events - those are unaffected by this
            # branch and keep notifying Admin exactly as today.
            recipients.extend(self._resolve_command_actor_recipient(event))
        return recipients

    # ---- delivery -----------------------------------------------------

    def _existing_delivery(self, event_id: uuid.UUID, recipient: Recipient, template: str) -> MessageDelivery | None:
        stmt = select(MessageDelivery).where(
            MessageDelivery.outbox_event_id == event_id,
            MessageDelivery.template == template,
        )
        if recipient.employee_id is not None:
            stmt = stmt.where(
                MessageDelivery.recipient_employee_id == recipient.employee_id,
                MessageDelivery.recipient_vendor_contact_id.is_(None),
            )
        else:
            stmt = stmt.where(
                MessageDelivery.recipient_vendor_contact_id == recipient.vendor_contact_id,
                MessageDelivery.recipient_employee_id.is_(None),
            )
        return self.db.scalar(stmt)

    def _resolve_recipient_channel(self, recipient: Recipient) -> str:
        """U8 (KTD5): read-only channel lookup - answers "what channel is
        this recipient on right now" by reading the recipient's identity
        row's `active_channel` column (`EmployeeProfile`/`V2VendorContact`,
        U5). Always returns `'whatsapp'` today, since no one has been
        toggled onto Telegram yet. NOT called from `_dispatch_to_recipient`
        or `_build_adapter` - that wiring is U9."""
        if recipient.employee_id is not None:
            return self.db.scalar(
                select(EmployeeProfile.active_channel).where(EmployeeProfile.id == recipient.employee_id)
            ) or "whatsapp"
        return self.db.scalar(
            select(V2VendorContact.active_channel).where(V2VendorContact.id == recipient.vendor_contact_id)
        ) or "whatsapp"

    def _resolve_telegram_chat_id(self, recipient: Recipient) -> str:
        """U10: the identifier a Telegram send actually targets - the
        recipient's `telegram_chat_id` (U4), not `recipient.phone`. Mirrors
        `_resolve_recipient_channel`'s employee/vendor-contact branching."""
        if recipient.employee_id is not None:
            return self.db.scalar(
                select(EmployeeProfile.telegram_chat_id).where(EmployeeProfile.id == recipient.employee_id)
            ) or ""
        return self.db.scalar(
            select(V2VendorContact.telegram_chat_id).where(V2VendorContact.id == recipient.vendor_contact_id)
        ) or ""

    def _is_offboarded_employee(self, recipient: Recipient) -> bool:
        if recipient.employee_id is None:
            return False
        active = self.db.scalar(
            select(User.active)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(EmployeeProfile.id == recipient.employee_id)
        )
        return active is False

    def _dispatch_to_recipient(self, event: OutboxEvent, recipient: Recipient, spec: TemplateSpec) -> None:
        if self._resolve_recipient_channel(recipient) == "telegram" and _skipped_on_telegram(event):
            return  # another message to this person already covers it
        template = spec.meta_template_name
        delivery = self._existing_delivery(event.id, recipient, template)
        if delivery is not None and delivery.status in _SUCCEEDED_STATUSES:
            return  # already succeeded - no re-send

        if delivery is None:
            delivery = MessageDelivery(
                outbox_event_id=event.id,
                recipient_employee_id=recipient.employee_id,
                recipient_vendor_contact_id=recipient.vendor_contact_id,
                recipient_phone=recipient.phone,
                template=template,
                status="queued",
                attempt_count=0,
            )
            self.db.add(delivery)
            try:
                self.db.flush()
            except IntegrityError:
                # Lost a race against a concurrent dispatch pass that already
                # inserted the same (event, recipient, template) delivery -
                # `uq_v2_message_deliveries_event_recipient_template` caught
                # it. Benign: roll back our half-started insert and fall back
                # to the row the other pass already committed, same as if
                # `_existing_delivery` above had found it in the first place.
                self.db.rollback()
                delivery = self._existing_delivery(event.id, recipient, template)
                if delivery is None or delivery.status in _SUCCEEDED_STATUSES:
                    return

        # An offboarded employee gets nothing further - checked at send time,
        # so queued or parked deliveries stop too. Recorded as an unreachable
        # failure: it is never retried unless the account is restored. The one
        # exception is the offboarding notice itself (R13), addressed to them.
        if event.event_type != "user.offboarded" and self._is_offboarded_employee(recipient):
            delivery.status = "failed"
            delivery.failure_code = "recipient_offboarded"
            delivery.failure_reason = "Recipient's account is offboarded."
            self.db.flush()
            return

        # U9: the channel this attempt actually targets, read fresh from the
        # recipient's identity row (U8) rather than trusting
        # `recipient.channel`'s construction-time default - the same
        # resolve-fresh-on-every-attempt discipline `recipient_phone` below
        # already follows.
        channel = self._resolve_recipient_channel(recipient)
        if delivery.status == "failed" and (
            delivery.failure_code in _PERMANENT_FAILURE_CODES or delivery.attempt_count >= _MAX_DELIVERY_ATTEMPTS
        ):
            # Given up on: this event was re-selected for another recipient's
            # retry - see `_select_events`.
            return
        if delivery.status == "failed" and delivery.failure_code in _UNREACHABLE_FAILURE_CODES:
            address = self._resolve_telegram_chat_id(recipient) if channel == "telegram" else recipient.phone
            if not address:
                # Still unreachable: this event was re-selected for another
                # recipient's retry - don't burn an attempt on this one.
                return

        # Refresh the denormalized snapshot on every attempt (including a
        # retry) so it reflects the number this specific attempt targeted.
        delivery.recipient_phone = recipient.phone
        delivery.channel = channel
        delivery.status = "sending"
        delivery.attempt_count += 1

        if channel == "telegram":
            # U10/KTD8: Telegram has no Meta-template registry, so it never
            # gets the WhatsApp-shaped `components` payload below - this
            # renders human-readable plain text via `telegram_render.py`
            # instead (event/data -> shared backend -> Telegram renderer ->
            # message; no Telegram-specific business logic here).
            send_target = self._resolve_telegram_chat_id(recipient)
            message = render_telegram(
                self.db, event.event_type, event.payload or {}, recipient.employee_id, recipient.vendor_contact_id,
            )
            # Actions with a callback become inline buttons (pressing one runs
            # the same typed command - telegram_callback.py); any action
            # without one stays listed as a typed command in the text.
            send_payload = {
                "text": message.text_for_buttons(),
                "parse_mode": message.parse_mode,
                "buttons": message.button_rows(),
            }
        else:
            # Merge `components` into a copy of the event payload rather
            # than mutating `event.payload` itself - the outbox row's
            # payload is the durable record of what happened; `components`
            # is dispatch-time rendering derived from it, not part of that
            # record.
            components = render_components(spec, template_fields(self.db, event.payload or {}))
            send_payload = {**(event.payload or {}), "components": components, "language_code": spec.language}
            send_target = recipient.phone

        adapter = self._adapters.get(channel, self.adapter)
        delivery.provider = getattr(adapter, "provider_name", "sandbox")
        result = adapter.send(recipient_phone=send_target, template=template, payload=send_payload)
        if result.ok:
            delivery.status = "sent"
            delivery.provider_message_id = result.provider_message_id
            delivery.failure_code = None
            delivery.failure_reason = None
            if channel == "telegram" and message.attachments:
                # Only after the message itself went out: a delivery that is
                # 'sent' is never re-sent, so files can't arrive twice.
                self._send_telegram_attachments(adapter, send_target, message.attachments)
        else:
            delivery.status = "failed"
            delivery.failure_code = result.failure_code
            delivery.failure_reason = result.failure_reason
        self.db.flush()

    def _send_telegram_attachments(self, adapter, chat_id: str, attachments) -> None:
        """Sends stored evidence files after a Telegram message (Admin
        evidence review), uploading the bytes from evidence storage - the
        recipient never gets a storage link. Best-effort: the message they
        follow is already delivered and links to the Web App, where every
        file is available, so a file that can't be sent is logged, not
        retried."""
        for attachment in attachments:
            file_object = self.db.get(FileObject, attachment.file_id)
            try:
                data = evidence_storage.read(file_object.storage_key) if file_object is not None else None
            except evidence_storage.EvidenceStorageError:
                data = None
            if data is None:
                logger.warning("Evidence file %s could not be read for Telegram review.", attachment.file_id)
                continue
            send = adapter.send_photo if file_object.mime_type in _TELEGRAM_PHOTO_MIME_TYPES else adapter.send_document
            result = send(chat_id, data, file_object.original_filename, file_object.mime_type, attachment.caption)
            if not result.ok:
                logger.warning(
                    "Evidence file %s was not sent on Telegram: %s", attachment.file_id, result.failure_reason,
                )

    # ---- entry point ------------------------------------------------

    @staticmethod
    def _recipient_reachable():
        """SQL condition (correlated to `MessageDelivery`): the delivery's
        recipient now has an address on their current channel - a linked
        Telegram chat when on Telegram, otherwise a phone number. Mirrors
        what `_dispatch_to_recipient` would send to."""
        employee_reachable = (
            select(EmployeeProfile.id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(
                EmployeeProfile.id == MessageDelivery.recipient_employee_id,
                # Offboarded: nothing is sent to them, so nothing to retry.
                User.active.is_(True),
                or_(
                    and_(EmployeeProfile.active_channel == "telegram",
                         func.coalesce(EmployeeProfile.telegram_chat_id, "") != ""),
                    and_(EmployeeProfile.active_channel != "telegram", func.coalesce(User.phone, "") != ""),
                ),
            )
            .exists()
        )
        vendor_reachable = (
            select(V2VendorContact.id)
            .where(
                V2VendorContact.id == MessageDelivery.recipient_vendor_contact_id,
                or_(
                    and_(V2VendorContact.active_channel == "telegram",
                         func.coalesce(V2VendorContact.telegram_chat_id, "") != ""),
                    and_(
                        V2VendorContact.active_channel != "telegram",
                        or_(func.coalesce(V2VendorContact.phone, "") != "",
                            func.coalesce(V2VendorContact.whatsapp, "") != ""),
                    ),
                ),
            )
            .exists()
        )
        return or_(employee_reachable, vendor_reachable)

    def _select_events(self, limit: int) -> list[OutboxEvent]:
        """New (`pending`) events first, oldest first; any remaining batch
        capacity goes to retries (`dispatched` events that still have a
        retryable failed delivery).

        A failure for an unreachable recipient (`_UNREACHABLE_FAILURE_CODES`)
        is only retryable once that recipient is reachable again (e.g. they
        linked Telegram), so it neither retries every pass forever nor takes
        batch space. A permanent failure (`_PERMANENT_FAILURE_CODES`) or a
        delivery that already used `_MAX_DELIVERY_ATTEMPTS` is never retried. Retries are ordered by their fewest attempts, then
        oldest, so deliveries that keep failing for other reasons (hundreds
        of attempts) never crowd out a recipient who just became reachable
        or failed once."""
        pending = list(
            self.db.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.status == "pending")
                .order_by(OutboxEvent.created_at)
                .limit(limit)
            ).all()
        )
        remaining = limit - len(pending)
        if remaining <= 0:
            return pending
        retryable = (
            select(
                MessageDelivery.outbox_event_id.label("event_id"),
                func.min(MessageDelivery.attempt_count).label("fewest_attempts"),
            )
            .where(
                MessageDelivery.status == "failed",
                MessageDelivery.attempt_count < _MAX_DELIVERY_ATTEMPTS,
                or_(
                    MessageDelivery.failure_code.is_(None),
                    MessageDelivery.failure_code.not_in(_PERMANENT_FAILURE_CODES),
                ),
                or_(
                    MessageDelivery.failure_code.is_(None),
                    MessageDelivery.failure_code.not_in(_UNREACHABLE_FAILURE_CODES),
                    self._recipient_reachable(),
                ),
            )
            .group_by(MessageDelivery.outbox_event_id)
            .subquery()
        )
        retries = list(
            self.db.scalars(
                select(OutboxEvent)
                .join(retryable, retryable.c.event_id == OutboxEvent.id)
                .where(OutboxEvent.status == "dispatched")
                .order_by(retryable.c.fewest_attempts, OutboxEvent.created_at)
                .limit(remaining)
            ).all()
        )
        return pending + retries

    def process_pending(self, limit: int = 50) -> int:
        """Processes up to `limit` outbox events (pending, plus dispatched
        events still carrying a failed delivery - see module docstring).
        Commits once per event so a crash mid-loop across recipients never
        leaves an event half-processed and uncommitted; re-running
        `process_pending()` afterward is safe because of the existing-row
        check in `_dispatch_to_recipient`. Returns the number of events
        processed in this call."""
        events = self._select_events(limit)
        for event in events:
            spec = resolve(event.event_type)
            for recipient in self._resolve_recipients(event):
                self._dispatch_to_recipient(event, recipient, spec)
            event.status = "dispatched"
            self.db.add(event)
            self.db.commit()
        return len(events)
