"""Phase 1 (1a): template-name registry (fixes the doc's own template-naming
rule being violated by `message_dispatch.py` sending
`template = event.event_type` straight to the WhatsApp provider - an internal
event-type string like `task.status_changed`, not a Meta-approved template
name, was never a valid `template.name` for the Graph API call
`MetaCloudApiAdapter` makes).

`TEMPLATE_REGISTRY` maps every `event_type` string this codebase's services
currently emit (via `OutboxService.emit(event_type=...)` - see each
`app.services.*` module for the emit call site) to the Meta template it
should render as. Names are chosen to align with the WhatsApp Operating
Model doc's own template names where a clear 1:1 mapping exists; where the
doc has no per-transition template (e.g. every `task.status_changed`
transition sharing one message shape), a sensible generic name is used
instead and flagged below.

Unmapped/unknown event types fall back to `DEFAULT_TEMPLATE` - logged, never
raising, and never leaking the raw internal event-type string out as if it
were a real template name (a stray/renamed event type must degrade to a
generic notification, not silently break dispatch or expose internals to
the WhatsApp provider).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateSpec:
    """One event type's WhatsApp template binding.

    `variable_order` names the `OutboxEvent.payload` keys to render into the
    Meta template's body parameters, in the order the approved template's
    placeholders expect them (`{{1}}`, `{{2}}`, ...) - see `render_components`.
    """

    meta_template_name: str
    language: str
    variable_order: tuple[str, ...]

    @property
    def is_placeholder(self) -> bool:
        return is_placeholder_template(self.meta_template_name)


def is_placeholder_template(template_name: str | None) -> bool:
    """Returns True when `template_name` is an unapproved `TBD_` placeholder
    identifier awaiting Meta Business Manager creation/approval."""
    return bool(template_name and template_name.startswith("TBD_"))


DEFAULT_TEMPLATE = TemplateSpec("generic_notification", "en", ())

# WhatsApp gate workflow plan (U14, KTD14): every new event type below is
# registered with a `TBD_<event_name>` placeholder `meta_template_name` and
# the correct `variable_order` only - no literal template body copy exists
# anywhere in this codebase, blocked on management/Meta approval (tracked in
# `todo.md` at the repo root). `grep -rn "TBD_" backend/app/services/message_templates.py`
# finds every entry still needing a real, approved template name.


TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {
    # ---- task events ---------------------------------------------------
    "task.status_changed": TemplateSpec(
        # No doc template maps 1:1 to every individual transition - one
        # generic status-update template covers all of them.
        "task_status_update", "en", ("task_id", "before_status", "target_status", "reason"),
    ),
    "task.verification_recorded": TemplateSpec(
        "task_verification_recorded", "en", ("task_id", "decision", "remarks", "decision_mode"),
    ),
    "task.approval_recorded": TemplateSpec(
        # BR-008: Admin is a recipient here (see message_dispatch.py's
        # `_ADMIN_CC_TASK_EVENTS`), never the decision-maker of record.
        "task_approval_decision", "en", ("task_id", "decision", "remarks", "decision_mode"),
    ),
    "task.blocker_created": TemplateSpec(
        "task_blocker_alert", "en", ("task_id", "type", "description"),
    ),
    "task.blocker_resolved": TemplateSpec(
        "task_blocker_resolved", "en", ("task_id", "resolved_by"),
    ),
    "task.delay_recorded": TemplateSpec(
        "task_delay_recorded", "en", ("task_id", "responsibility_type", "impact_days"),
    ),
    "task.support_assigned": TemplateSpec(
        "task_support_assigned", "en", ("task_id", "employee_id", "responsibility"),
    ),
    "task.support_ended": TemplateSpec(
        # Non-doc event type (doc doesn't distinguish "support ended" from
        # "support reassigned") - mapped to the nearest doc-aligned name,
        # flagged for later product review per the plan's Decisions section.
        "task_support_ended", "en", ("task_id", "previous_employee_id", "replacement_employee_id", "reason_code"),
    ),
    "task.evidence_submitted": TemplateSpec(
        "task_evidence_submitted", "en", ("task_id", "update_type"),
    ),
    "task.vendor_assigned": TemplateSpec(
        "task_vendor_assigned", "en", ("task_id", "vendor_id"),
    ),
    "task.vendor_unassigned": TemplateSpec(
        "TBD_task_vendor_unassigned", "en", ("task_id", "vendor_id", "reason"),
    ),
    "task.readiness_declared": TemplateSpec(
        # Non-doc event type (Phase 3 advisory overlay table, not a doc
        # workflow) - mapped to the nearest doc-aligned name, flagged for
        # later product review per the plan's Decisions section.
        "task_readiness_declared", "en", ("task_id", "status", "note"),
    ),
    "task.rescheduled": TemplateSpec(
        # Plan Phase 4: no doc template covers a planned-date replan
        # specifically - the closest doc-aligned name is used, flagged for
        # later product review per the plan's Decisions section.
        "task_rescheduled", "en", ("task_id", "planned_start_date", "planned_end_date", "reason"),
    ),
    "task.eod_followup_required": TemplateSpec(
        # Plan Phase 6: emitted by `EscalationService.sweep_task_followups`
        # for a task whose "no update since SLA cutoff" condition is true.
        "task_eod_followup_required", "en", ("task_id", "lifecycle_status", "update_sla_hours"),
    ),
    "task.completion_followup_required": TemplateSpec(
        # Plan Phase 6: registered ahead of emission - the plan lists this
        # as a distinct event type for a later refinement of the followup
        # sweep. No sweep method emits it yet in this dispatch.
        "task_completion_followup_required", "en", ("task_id", "lifecycle_status"),
    ),
    "task.escalated_to_admin": TemplateSpec(
        # Plan Phase 6: emitted by `EscalationService.sweep_task_escalations`
        # once a `followup`-stage tracking row has stayed open >= 6h and the
        # task is still stale on live re-check. Admin reached via
        # `message_dispatch.py`'s `_ADMIN_CC_TASK_EVENTS`.
        "task_escalated_to_admin", "en", ("task_id", "lifecycle_status", "update_sla_hours"),
    ),
    "task.readiness_check": TemplateSpec(
        # Plan Phase 6 (second half): emitted by
        # `DailyTaskPromptsService.emit_readiness_checks` the day before
        # `planned_start_date` for a task not yet started.
        "task_readiness_check", "en", ("task_id", "planned_start_date"),
    ),
    "task.start_check": TemplateSpec(
        # Plan Phase 6 (second half): emitted by
        # `DailyTaskPromptsService.emit_start_checks` on `planned_start_date`
        # itself for a task still not started.
        "task_start_check", "en", ("task_id", "planned_start_date"),
    ),
    "task.midday_check": TemplateSpec(
        # Plan Phase 6 (second half): emitted by
        # `DailyTaskPromptsService.emit_midday_checks` for every
        # `in_progress` task.
        "task_midday_check", "en", ("task_id", "lifecycle_status"),
    ),
    "task.eod_check": TemplateSpec(
        # Plan Phase 6 (second half): emitted by
        # `DailyTaskPromptsService.emit_eod_checks` for every `in_progress`
        # task.
        "task_eod_check", "en", ("task_id", "lifecycle_status"),
    ),
    "task.prestart_warning": TemplateSpec(
        # Telegram T3: `TaskReminderService`, 09:00 IST the day before
        # `planned_start_date` for a task not started yet.
        "task_prestart_warning", "en", ("task_id", "planned_start_date"),
    ),
    "task.sla_overdue": TemplateSpec(
        # Telegram T5: 06:30 IST (EOD + 12h) the day after `planned_end_date`
        # for work still not submitted.
        "task_sla_overdue", "en", ("task_id", "planned_end_date"),
    ),
    "task.sla_escalated": TemplateSpec(
        # Telegram T5: 09:30 IST (EOD + 15h), same condition, to PM and Admin.
        "task_sla_escalated", "en", ("task_id", "planned_end_date"),
    ),
    # ---- project events -------------------------------------------------
    "project.role_change_requested": TemplateSpec(
        "project_role_change_requested", "en", ("project_id", "role_type", "reason_code"),
    ),
    "project.role_change_approved": TemplateSpec(
        "project_role_change_approved", "en", ("project_id", "role_type"),
    ),
    "project.role_change_rejected": TemplateSpec(
        "project_role_change_rejected", "en", ("project_id", "role_type", "reason"),
    ),
    # ---- project_external_approval (gate) events -------------------------
    "project_external_approval.assigned": TemplateSpec(
        # WhatsApp gate workflow plan (U14): widened with gate_name/
        # project_name/due_date - U4 already writes these three keys into
        # this event's payload (project_gate_assignment.py), but without
        # this widening render_components only emitted the original two
        # parameters and the new fields never reached a rendered message.
        "external_approval_assigned", "en",
        ("approval_id", "assigned_to_user_id", "gate_name", "project_name", "due_date"),
    ),
    "project_external_approval.reassigned": TemplateSpec(
        # Same widening as .assigned above, same reason.
        "external_approval_reassigned", "en",
        ("approval_id", "assigned_to_user_id", "gate_name", "project_name", "due_date"),
    ),
    "project_external_approval.unassigned": TemplateSpec(
        "external_approval_unassigned", "en", ("approval_id", "previous_assignee_id"),
    ),
    "project_external_approval.submitted": TemplateSpec(
        # Doc's "external approval status update" template - the closest
        # doc-named match for a submission notice.
        "external_approval_status_update", "en", ("approval_id", "submission_id"),
    ),
    "project_external_approval.decided": TemplateSpec(
        "external_approval_decided", "en", ("approval_id", "decision", "reason"),
    ),
    "project_external_approval.status_checked": TemplateSpec(
        # Non-doc event type (Phase 3 advisory overlay table, the gate
        # analog of task.blocker_created) - mapped to the nearest
        # doc-aligned name, flagged for later product review.
        "external_approval_status_checked", "en", ("approval_id", "health", "note"),
    ),
    "project_external_approval.followup_required": TemplateSpec(
        # Plan Phase 6: emitted by `EscalationService.sweep_approval_followups`
        # for an `assigned` (not yet submitted) approval at or past `due_at`.
        "external_approval_followup_required", "en", ("approval_id", "assigned_to_user_id", "due_at"),
    ),
    "project_external_approval.escalated_to_admin": TemplateSpec(
        # Plan Phase 6: emitted by
        # `EscalationService.sweep_approval_escalations` once a
        # `followup`-stage tracking row has stayed open >= 6h and the
        # approval is still `assigned` on live re-check. Admin already
        # resolves unconditionally for every project_external_approval.*
        # event via `message_dispatch.py`'s own branch - no allowlist entry
        # needed here.
        "external_approval_escalated_to_admin", "en", ("approval_id", "assigned_to_user_id", "due_at"),
    ),
    "project_external_approval.due_reminder": TemplateSpec(
        # Plan Phase 6: registered ahead of emission, per Phase 1's registry
        # being meant to be complete/ahead of emission - the day-before
        # due-date reminder this maps to is emitted by a later dispatch's
        # `gate_reminder_scheduler.py`, not by anything in this dispatch.
        "external_approval_due_reminder", "en", ("approval_id", "assigned_to_user_id", "due_at"),
    ),
    # ---- WhatsApp gate workflow plan events (U14) -------------------------
    # Every entry below is a TBD_ placeholder (KTD14) - no literal template
    # body copy exists anywhere in this codebase; see the module-level note
    # above DEFAULT_TEMPLATE.
    "project.activated": TemplateSpec(
        "TBD_project_activated", "en", ("project_id", "project_name"),
    ),
    "project.member_added": TemplateSpec(
        "TBD_project_member_added", "en", ("project_id", "employee_id", "project_role"),
    ),
    "project.vendor_mapped": TemplateSpec(
        # KTD19: a distinct event type from project.member_added, not the
        # same type reused with different payload keys - the two shapes
        # never overlap (person vs. vendor), so each gets its own entry.
        "TBD_project_vendor_mapped", "en", ("project_id", "vendor_id"),
    ),
    "project.vendor_removed": TemplateSpec(
        "TBD_project_vendor_removed", "en", ("project_id", "vendor_id", "reason"),
    ),
    "project_external_approval.accepted": TemplateSpec(
        # U5: the assignee's WhatsApp acknowledgement - distinct from the
        # U15 gate_confirmation.* entries below, which confirm back to
        # whoever sent a gate command, not this Admin-facing overlay event.
        "TBD_project_external_approval_accepted", "en",
        ("approval_id", "project_id", "response", "note"),
    ),
    "project_external_approval.declined": TemplateSpec(
        "TBD_project_external_approval_declined", "en",
        ("approval_id", "project_id", "response", "note"),
    ),
    "user.created": TemplateSpec(
        "TBD_user_created", "en", ("user_id", "name"),
    ),
    "user.offboarded": TemplateSpec(
        "TBD_user_offboarded", "en", ("user_id", "name"),
    ),
    # ---- gate command WhatsApp confirmations (U15) -------------------------
    # Sender-facing confirmations for the six gate commands
    # (GATEACCEPT/DECLINE/STATUS/OPEN/CLOSE/DECIDE) - distinct from the
    # Admin-facing project_external_approval.accepted/.declined above, which
    # keep notifying Admin unchanged.
    "gate_confirmation.accepted": TemplateSpec(
        "TBD_gate_confirmation_accepted", "en", ("actor_user_id", "gate_name", "project_name"),
    ),
    "gate_confirmation.declined": TemplateSpec(
        "TBD_gate_confirmation_declined", "en", ("actor_user_id", "gate_name", "project_name"),
    ),
    "gate_confirmation.status_recorded": TemplateSpec(
        "TBD_gate_confirmation_status_recorded", "en",
        ("actor_user_id", "gate_name", "project_name", "health"),
    ),
    "gate_confirmation.session_opened": TemplateSpec(
        "TBD_gate_confirmation_session_opened", "en", ("actor_user_id", "gate_name", "project_name"),
    ),
    "gate_confirmation.session_closed": TemplateSpec(
        "TBD_gate_confirmation_session_closed", "en", ("actor_user_id", "gate_name", "project_name"),
    ),
    "gate_confirmation.session_cancelled": TemplateSpec(
        "TBD_gate_confirmation_session_cancelled", "en", ("actor_user_id", "gate_name", "project_name"),
    ),
    "gate_confirmation.decided": TemplateSpec(
        "TBD_gate_confirmation_decided", "en",
        ("actor_user_id", "gate_name", "project_name", "decision"),
    ),
    # ---- report events ---------------------------------------------------
    "report.weekly_summary_generated": TemplateSpec(
        # Plan Phase 8: emitted by `weekly_summary_scheduler.py` after
        # `ReportGenerationService.generate` produces a new weekly
        # `ReportSnapshot` on its 7-day cadence. No doc template names a
        # "weekly summary ready" notice specifically - the closest
        # doc-aligned name is used, flagged for later product review per
        # the plan's Decisions section. `aggregate_type="project"` routes
        # this through `_resolve_pm_supervisor_recipients` unchanged, plus
        # Admin via `message_dispatch.py`'s `_ADMIN_CC_PROJECT_EVENTS`.
        "weekly_project_summary", "en", ("project_id", "report_snapshot_id"),
    ),
    # ---- broadcast events (Milestone 1 Phase 2) --------------------------
    "broadcast.message_dispatched": TemplateSpec(
        "project_broadcast_announcement", "en", ("project_name", "title", "message_body"),
    ),
}


def resolve(event_type: str) -> TemplateSpec:
    """Registry lookup with a logged, non-raising fallback. Never returns a
    `TemplateSpec` built from the raw `event_type` string itself - an
    unmapped event type degrades to `DEFAULT_TEMPLATE`, not a fabricated
    template name derived from internal wording."""
    spec = TEMPLATE_REGISTRY.get(event_type)
    if spec is not None:
        return spec
    logger.warning("No template registered for event_type=%r; falling back to default template.", event_type)
    return DEFAULT_TEMPLATE


def render_components(spec: TemplateSpec, payload: dict) -> list[dict]:
    """Builds Meta's WhatsApp template body-parameters shape (the
    `components` list `MetaCloudApiAdapter._build_body` already reads off
    `payload["components"]`, but nothing has ever populated until now).

    A spec with no `variable_order` (e.g. `DEFAULT_TEMPLATE`) returns no
    components at all - Meta rejects a body component with an empty
    `parameters` list for a template that has no placeholders.

    Meta also rejects an empty-string parameter, so an optional field that
    is missing or blank (a `reason` on a normal status change, `remarks` on
    an approval) is sent as `EMPTY_PARAMETER_TEXT` instead."""
    if not spec.variable_order:
        return []
    return [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": _parameter_text(payload.get(key))} for key in spec.variable_order],
        }
    ]


EMPTY_PARAMETER_TEXT = "-"


def _parameter_text(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return text or EMPTY_PARAMETER_TEXT


def audit_template_registry() -> list[dict]:
    """Returns a structured audit inventory of every entry in
    `TEMPLATE_REGISTRY`, categorizing each template as `'configured'` or
    `'placeholder_tbd'`."""
    inventory: list[dict] = []
    for event_type, spec in TEMPLATE_REGISTRY.items():
        inventory.append({
            "event_type": event_type,
            "meta_template_name": spec.meta_template_name,
            "language": spec.language,
            "variable_order": spec.variable_order,
            "status": "placeholder_tbd" if spec.is_placeholder else "configured",
        })
    return inventory
