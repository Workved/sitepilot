"""Readable Telegram messages for internal task-execution events.

Telegram task plan U4. Replaces the raw key:value dump (and the old plain
renderers with typed-command hints) for every internal task event in scope.
Buttons arrive in later units (U5+); until then each message says what
happened and, where the recipient has something to do, what that is.

Recipient-aware: the same event reads differently for the people doing the
work (active support assignees and whoever submitted the work) than for the
reviewers and the rest of the team.

Read-only like `telegram_gate_render.py`: never mutates anything, holds no
business rules, and degrades to placeholders rather than raising. Every
dynamic value is HTML-escaped (sent with `parse_mode="HTML"`), and no UUID,
event name or payload key is ever shown.

Vendor events (`task.vendor_*`) are deliberately not here: vendor removal is
in `telegram_render.py`, vendor assignment in `telegram_assignment_render.py`.
"""

from __future__ import annotations

import html
import uuid
from datetime import date
from typing import Callable
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import (
    FileObject,
    Task,
    TaskBlocker,
    TaskDelayEvent,
    TaskEvidence,
    TaskProgressUpdate,
    TaskReadinessDeclaration,
    TaskSupportAssignment,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.task_approval import TaskApprovalService
from app.services.task_approval_metadata import (
    APPROVAL_SUMMARY_PM_APPROVAL,
    APPROVAL_SUMMARY_SUPERVISOR_AND_PM,
    APPROVAL_SUMMARY_SUPERVISOR_VERIFICATION,
    build_approval_metadata,
)
from app.services.task_lifecycle import latest_submitter_user_id
from app.services.telegram_message import (
    TelegramAction,
    TelegramAttachment,
    TelegramMessage,
    ack_callback,
    submission_token,
    task_callback,
)

# [Acknowledge] on "Task Assigned to You" (T2) - same code as
# telegram_assignment_render.ACK_SUPPORT_ASSIGNMENT, handled by
# telegram_ack_callback.py.
_ACK_SUPPORT_ASSIGNMENT = "sa"

_FYI = "For your information. No action required."

# Display labels for the backend's own task classification
# (task_approval_metadata.approval_summary). Milestones get no label.
_TASK_TYPE_LABELS = {
    APPROVAL_SUMMARY_SUPERVISOR_VERIFICATION: "Standard",
    APPROVAL_SUMMARY_SUPERVISOR_AND_PM: "Class A",
    APPROVAL_SUMMARY_PM_APPROVAL: "Approval Gate",
}
_APPROVAL_FLOW_LABELS = {
    APPROVAL_SUMMARY_SUPERVISOR_AND_PM: "Supervisor Verification → PM Approval",
    APPROVAL_SUMMARY_PM_APPROVAL: "Direct PM Approval",
}
_APPROVAL_STEP = "Approve it, or reject it with a reason. You can also decide in the Web App."
# U10: the one explicit "nobody can approve" state - never a silent dead end.
NO_ELIGIBLE_APPROVER = "No one else can approve this yet - an Admin or another PM must be added to the project."
_REWORK_STEP = "Add new progress and submit the task for review again."

_STATUS_LABELS = {
    "planned": "Planned",
    "ready": "Ready",
    "in_progress": "In Progress",
    "submitted": "Submitted for Review",
    "verified": "Verified",
    "approval_pending": "Awaiting Approval",
    "rejected": "Rejected",
    "completed": "Completed",
    "cancelled": "Cancelled",
}


def _e(value: object) -> str:
    return html.escape(str(value))


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _label(value: object) -> str:
    return str(value).replace("_", " ").strip().capitalize() if value else "Not given"


def _date(value: object) -> str:
    if not value:
        return "Not set"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(value)


def _user_name(db: Session, user_id: object, fallback: str = "Unknown user") -> str:
    resolved = _uuid_or_none(user_id)
    user = db.get(User, resolved) if resolved else None
    return user.name if user else fallback


def _employee_name(db: Session, employee_id: object, fallback: str = "Unknown employee") -> str:
    resolved = _uuid_or_none(employee_id)
    employee = db.get(EmployeeProfile, resolved) if resolved else None
    user = db.get(User, employee.user_id) if employee else None
    return user.name if user else fallback


class _Ctx:
    """The task, its project and who the recipient is to this task."""

    def __init__(self, db: Session, payload: dict, recipient_employee_id: uuid.UUID | None):
        self.db = db
        self.payload = payload
        self.task: Task | None = None
        resolved_task = _uuid_or_none(payload.get("task_id"))
        if resolved_task:
            self.task = db.get(Task, resolved_task)
        resolved_project = _uuid_or_none(payload.get("project_id")) or (self.task.project_id if self.task else None)
        self.project: V2Project | None = db.get(V2Project, resolved_project) if resolved_project else None
        self.recipient_employee_id = recipient_employee_id
        self.recipient_user_id = None
        if recipient_employee_id is not None:
            employee = db.get(EmployeeProfile, recipient_employee_id)
            self.recipient_user_id = employee.user_id if employee else None

    # ---- who the recipient is ------------------------------------------

    def project_roles(self) -> set[str]:
        if self.recipient_employee_id is None or self.project is None:
            return set()
        return set(self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == self.project.id,
                V2ProjectMembership.employee_id == self.recipient_employee_id,
                V2ProjectMembership.ends_at.is_(None),
            )
        ))

    def is_pm(self) -> bool:
        return "project_manager" in self.project_roles()

    def is_supervisor(self) -> bool:
        return "site_supervisor" in self.project_roles()

    def is_assignee(self) -> bool:
        if self.task is None or self.recipient_employee_id is None:
            return False
        return self.db.scalar(
            select(TaskSupportAssignment.id).where(
                TaskSupportAssignment.task_id == self.task.id,
                TaskSupportAssignment.employee_id == self.recipient_employee_id,
                TaskSupportAssignment.status == "active",
            ).limit(1)
        ) is not None

    def submitter_user_id(self) -> uuid.UUID | None:
        # The submission snapshot names its submitter (KTD18); older events
        # fall back to the task's latest submission.
        snapshot = _uuid_or_none(self.payload.get("submitted_by"))
        if snapshot is not None:
            return snapshot
        return latest_submitter_user_id(self.db, self.task.id) if self.task else None

    def is_submitter(self) -> bool:
        submitter = self.submitter_user_id()
        return submitter is not None and submitter == self.recipient_user_id

    def is_executor(self) -> bool:
        """The people doing the work: an active support assignee, or whoever
        submitted it (e.g. a Supervisor who executed it themselves)."""
        return self.is_assignee() or self.is_submitter()

    def is_admin(self) -> bool:
        user = self.db.get(User, self.recipient_user_id) if self.recipient_user_id else None
        return user is not None and user.role in (UserRole.admin, UserRole.super_admin)

    def has_assignee(self) -> bool:
        return self.task is not None and self.db.scalar(
            select(TaskSupportAssignment.id).where(
                TaskSupportAssignment.task_id == self.task.id, TaskSupportAssignment.status == "active",
            ).limit(1)
        ) is not None

    # ---- buttons (KTD12: shown to people the lifecycle rules would allow;
    # the service still enforces every rule when one is pressed) ------------

    def can_mark_ready(self) -> bool:
        if self.task is None or self.task.lifecycle_status != "planned":
            return False
        return self.is_admin() or self.is_supervisor() or self.is_pm() or self.is_assignee()

    def can_start(self) -> bool:
        """Mirrors task_lifecycle's executor rule: the assigned Internal
        Employee once one is assigned, otherwise the Supervisor/PM - never
        for an approval-gate task, which must be delegated first."""
        if self.task is None or self.task.lifecycle_status != "ready":
            return False
        if self.is_admin():
            return True
        if self.has_assignee():
            return self.is_assignee()
        return not _is_approval_gate(self) and (self.is_supervisor() or self.is_pm())

    def can_log_progress(self) -> bool:
        """Mirrors TaskProgressService's rules: only while in progress; the
        assigned Internal Employee once one is assigned, otherwise the
        Supervisor/PM; Admin always."""
        if self.task is None or self.task.lifecycle_status != "in_progress":
            return False
        if self.is_admin():
            return True
        if self.has_assignee():
            return self.is_assignee()
        return self.is_supervisor() or self.is_pm()

    def review_actions(self, snapshot_ids) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Verify] [Reject] on a work submission (U9): for the Supervisor,
        PM or Admin - never the person who submitted it, unless Admin (the
        verification service's self-verification rule) - and only while this
        exact submission is the one waiting (KTD19)."""
        if self.task is None or _is_approval_gate(self) or self.task.lifecycle_status != "submitted":
            return ()
        token = submission_token(snapshot_ids)
        if token is None or token != current_submission_token(self.db, self.task):
            return ()
        if not (self.is_admin() or ((self.is_supervisor() or self.is_pm()) and not self.is_submitter())):
            return ()
        return ((
            TelegramAction("Verify", "", task_callback("vf", self.task.id, token)),
            TelegramAction("Reject", "", task_callback("vr", self.task.id, token)),
        ),)

    def is_ineligible_approver(self) -> bool:
        excluded = TaskApprovalService(self.db).ineligible_approver_user_id(self.task) if self.task else None
        return excluded is not None and excluded == self.recipient_user_id

    def approval_actions(self, token: str | None) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Approve] [Reject] (U10) for a PM or Admin who may approve this
        cycle - never the fallback verifier (KTD20) - and only while `token`
        is still what is waiting for approval (KTD19)."""
        if self.task is None or not token or token != current_approval_token(self.db, self.task):
            return ()
        if not (self.is_pm() or self.is_admin()) or self.is_ineligible_approver():
            return ()
        return ((
            TelegramAction("Approve", "", task_callback("pa", self.task.id, token)),
            TelegramAction("Reject", "", task_callback("pr", self.task.id, token)),
        ),)

    def report_blocker_actions(self) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Report Blocker] (U12) for any active project member or Admin -
        the blocker service's own rule for who may log one - on a task that is
        not finished."""
        if self.task is None or self.task.lifecycle_status in ("completed", "cancelled"):
            return ()
        if not (self.is_admin() or self.project_roles()):
            return ()
        return ((TelegramAction("Report Blocker", "", task_callback("rb", self.task.id)),),)

    def can_resolve_blockers(self) -> bool:
        """The blocker service's resolver rule: Supervisor, PM or Admin."""
        return self.is_admin() or self.is_supervisor() or self.is_pm()

    def rework_actions(self) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Add Progress] [Submit Again] on "Rework Required" (U11), for
        whoever may log progress on the reopened task. Submit Again is the
        same Submit for Review action (U8): the new-progress rule still
        refuses it until something new is logged this round."""
        if not self.can_log_progress():
            return ()
        return ((
            TelegramAction("Add Progress", "", task_callback("ap", self.task.id)),
            TelegramAction("Submit Again", "", task_callback("sb", self.task.id)),
        ),)

    def progress_actions(self) -> tuple[tuple[TelegramAction, ...], ...]:
        if not self.can_log_progress():
            return ()
        return ((TelegramAction("Add Progress", "", task_callback("ap", self.task.id)),),)

    def progress_and_submit_actions(self, submit_label: str = "Submit for Review") -> tuple[tuple[TelegramAction, ...], ...]:
        """[Add Progress] [Submit for Review] (T4) for whoever may log progress;
        the submit rules themselves stay with the lifecycle service."""
        if not self.can_log_progress():
            return ()
        return ((
            TelegramAction("Add Progress", "", task_callback("ap", self.task.id)),
            TelegramAction(submit_label, "", task_callback("sb", self.task.id)),
        ),)

    def _is_member_or_admin(self) -> bool:
        return self.is_admin() or bool(self.project_roles())

    def readiness_actions(self) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Ready] [Need Help] [Issue] on the readiness check (T3) - a
        readiness declaration, which any project member or Admin may make, on
        a task that has not started. It does not change the task's status."""
        if self.task is None or self.task.lifecycle_status not in ("planned", "ready") or not self._is_member_or_admin():
            return ()
        return ((
            TelegramAction("Ready", "", task_callback("yr", self.task.id)),
            TelegramAction("Need Help", "", task_callback("yh", self.task.id)),
            TelegramAction("Issue", "", task_callback("yi", self.task.id)),
        ),)

    def report_delay_actions(self) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Report Delay] (T7) - the delay service's own rule: any project
        member or Admin, on a task that is not finished."""
        if self.task is None or self.task.lifecycle_status in ("completed", "cancelled") or not self._is_member_or_admin():
            return ()
        return ((TelegramAction("Report Delay", "", task_callback("dl", self.task.id)),),)

    def start_actions(self) -> tuple[tuple[TelegramAction, ...], ...]:
        """[Mark Task Ready] or [Start Task], whichever the task's current
        status allows this recipient to press - or none."""
        if self.can_mark_ready():
            return ((TelegramAction("Mark Task Ready", f"STATUS {self.task.original_code} ready", task_callback("rd", self.task.id)),),)
        if self.can_start():
            return ((TelegramAction("Start Task", f"STATUS {self.task.original_code} in_progress", task_callback("st", self.task.id)),),)
        return ()

    # ---- task type (display only) ------------------------------------------

    def _approval_summary(self) -> str | None:
        """The backend's own classification of this task (task_kind +
        task_class, via task_approval_metadata) - never a second rule here."""
        if self.task is None:
            return None
        return build_approval_metadata(self.task.task_kind, self.task.task_class, self.task.lifecycle_status).approval_summary

    def type_rows(self, with_flow: bool = False) -> list[tuple[str, object]]:
        """ "Task Type" (and, for review/approval messages of Class A and
        approval-gate tasks, "Approval Flow") rows. Milestones get none."""
        summary = self._approval_summary()
        label = _TASK_TYPE_LABELS.get(summary)
        if label is None:
            return []
        rows: list[tuple[str, object]] = [("Task Type", label)]
        if with_flow and summary in _APPROVAL_FLOW_LABELS:
            rows.append(("Approval Flow", _APPROVAL_FLOW_LABELS[summary]))
        return rows

    # ---- message parts ----------------------------------------------------

    def rows(self, *extra: tuple[str, object]) -> list[tuple[str, object]]:
        task_label = f"{self.task.original_code} - {self.task.title}" if self.task else "Unknown task"
        return [("Project", self.project.name if self.project else "Unknown project"), ("Task", task_label), *extra]

    def link(self) -> tuple[str, str] | None:
        if self.project is None or not settings.frontend_url:
            return None
        query = urlencode({"tab": "execution", "project": self.project.code})
        return "Open in Web App", f"{settings.frontend_url.rstrip('/')}/?{query}"


def current_submission_token(db: Session, task: Task) -> str | None:
    """The token of the submission waiting for verification (KTD19), or None.
    While a task is submitted its unreviewed updates are exactly its
    submission's (KTD24)."""
    if task.lifecycle_status != "submitted":
        return None
    return submission_token(db.scalars(
        select(TaskProgressUpdate.id).where(
            TaskProgressUpdate.task_id == task.id, TaskProgressUpdate.reviewed_at.is_(None),
        )
    ).all())


def current_approval_token(db: Session, task: Task) -> str | None:
    """What is waiting for PM approval: an approval-gate task's submission,
    or the verification of class_a work (its id, first 8 hex)."""
    if task.task_kind == "approval_gate":
        return current_submission_token(db, task)
    if task.task_class != "class_a" or task.lifecycle_status != "verified":
        return None
    verification = TaskApprovalService(db)._current_verification(task.id)
    return verification.id.hex[:8] if verification is not None and verification.decision == "verified" else None


def _message(
    ctx: _Ctx,
    title: str,
    rows: list[tuple[str, object]],
    paragraph: str | None = None,
    actions: tuple[tuple[TelegramAction, ...], ...] = (),
    attachments: tuple[TelegramAttachment, ...] = (),
) -> TelegramMessage:
    parts = [f"<b>{_e(title)}</b>"]
    if rows:
        parts.append("\n".join(f"{_e(label)}: {_e(value)}" for label, value in rows))
    if paragraph:
        parts.append(_e(paragraph))
    link = ctx.link()
    if link:
        parts.append(f'<a href="{_e(link[1])}">{_e(link[0])}</a>')
    return TelegramMessage(text="\n\n".join(parts), parse_mode="HTML", actions=actions, attachments=attachments)


MAX_REVIEW_FILES = 5


class _Submission:
    """The exact submission a review message is about - the progress updates
    named in the `submitted` event's snapshot (KTD18), never "whatever is on
    the task now", so a message sent after a later decision or new progress
    still shows what was submitted."""

    def __init__(self, db: Session, payload: dict):
        ids = [_uuid_or_none(value) for value in payload.get("progress_update_ids") or []]
        ids = [i for i in ids if i is not None]
        # The snapshot lists the updates in the order they were logged; keep
        # that order rather than re-sorting by timestamp.
        position = {update_id: index for index, update_id in enumerate(ids)}
        self.updates: list[TaskProgressUpdate] = sorted(
            db.scalars(select(TaskProgressUpdate).where(TaskProgressUpdate.id.in_(ids))),
            key=lambda u: position[u.id],
        ) if ids else []
        rows = db.execute(
            select(FileObject, TaskEvidence.task_progress_update_id)
            .join(TaskEvidence, TaskEvidence.file_id == FileObject.id)
            .where(TaskEvidence.task_progress_update_id.in_(ids))
        ).all() if ids else []
        self.files: list[FileObject] = [
            f for f, _ in sorted(rows, key=lambda row: (position[row[1]], row[0].original_filename))
        ]
        notes = [u.note for u in self.updates if u.note]
        self.latest_note = notes[-1] if notes else None

    def evidence_summary(self) -> str:
        if not self.files:
            return "No files"
        photos = sum(1 for f in self.files if f.mime_type != "application/pdf")
        pdfs = len(self.files) - photos
        parts = [f"{photos} photo{'s' if photos != 1 else ''}"] if photos else []
        if pdfs:
            parts.append(f"{pdfs} PDF{'s' if pdfs != 1 else ''}")
        shown = f" (first {MAX_REVIEW_FILES} sent below)" if len(self.files) > MAX_REVIEW_FILES else ""
        return ", ".join(parts) + shown

    def attachments(self) -> tuple[TelegramAttachment, ...]:
        return tuple(TelegramAttachment(file_id=f.id, caption=f.original_filename) for f in self.files[:MAX_REVIEW_FILES])


def _is_approval_gate(ctx: _Ctx) -> bool:
    return ctx.task is not None and ctx.task.task_kind == "approval_gate"


def _is_class_a_work(ctx: _Ctx) -> bool:
    return ctx.task is not None and ctx.task.task_class == "class_a" and not _is_approval_gate(ctx)


# ---- status changes ----------------------------------------------------------


def _render_status_changed(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    target = payload.get("target_status")
    actor = _user_name(db, payload.get("actor_user_id"), fallback="") if payload.get("actor_user_id") else ""

    if target == "ready":
        rows = ctx.rows(*([("Marked ready by", actor)] if actor else []))
        actions = ctx.start_actions()
        step = "This task is ready to start." if actions or ctx.is_executor() else _FYI
        return _message(ctx, "Task Ready", rows, step, actions)

    if target == "in_progress":
        extra = [("Started by", actor)] if actor else []
        if ctx.task is not None and ctx.task.early_start_reason and payload.get("before_status") in ("planned", "ready"):
            extra.append(("Early start reason", ctx.task.early_start_reason))
        progress = ctx.progress_actions()
        step = "Log your progress as you work." if progress or ctx.is_executor() else _FYI
        return _message(ctx, "Task Started", ctx.rows(*extra), step, progress + ctx.report_blocker_actions())

    if target == "submitted":
        submission = _Submission(db, payload)
        rows = ctx.rows(
            *ctx.type_rows(with_flow=True),
            ("Submitted by", actor or "Unknown user"),
            ("Latest note", submission.latest_note or "No note"),
            ("Evidence", submission.evidence_summary()),
        )
        # Reviewers and everyone else receive the submission's files; the
        # person who submitted them already has them.
        files = () if ctx.is_submitter() else submission.attachments()
        if _is_approval_gate(ctx):
            # Approval-gate tasks skip Supervisor verification entirely (KTD23):
            # only the PM (or Admin) decides, and the Supervisor is never asked
            # to "review" or "verify" it.
            actions = ctx.approval_actions(submission_token(payload.get("progress_update_ids")))
            if ctx.is_submitter() and not ctx.is_admin():
                step = "Sent to the PM for approval. You will be told the outcome."
            elif actions:
                step = _APPROVAL_STEP
            else:
                step = _FYI
            return _message(ctx, "Submitted - Awaiting PM Approval", rows, step, actions, attachments=files)
        if ctx.is_submitter() and not ctx.is_admin():
            return _message(ctx, "Submitted for Review", rows, "Your work was sent for review. You will be told the outcome.")
        actions = ctx.review_actions(payload.get("progress_update_ids"))
        step = "Verify it, or reject it with a reason. You can also decide in the Web App." if actions else _FYI
        return _message(ctx, "Task Submitted for Review", rows, step, actions, attachments=files)

    if target == "completed":
        if ctx.task is not None and ctx.task.task_kind == "milestone":
            return _message(ctx, "Milestone Completed", ctx.rows(), "All of its predecessor tasks are complete.")
        return _message(ctx, "Task Completed", ctx.rows(), _FYI)

    if target == "cancelled":
        rows = ctx.rows(*([("Cancelled by", actor)] if actor else []), ("Reason", payload.get("reason") or "Not given"))
        return _message(ctx, "Task Cancelled", rows, _FYI)

    before = _STATUS_LABELS.get(payload.get("before_status"), _label(payload.get("before_status")))
    after = _STATUS_LABELS.get(target, _label(target))
    return _message(ctx, "Task Status Updated", ctx.rows(("Status", f"{before} -> {after}")), _FYI)


# ---- review decisions -----------------------------------------------------------


def _render_rework(ctx: _Ctx, reviewer_label: str, reviewer: str, reason: object) -> TelegramMessage:
    rows = ctx.rows(*ctx.type_rows(), (reviewer_label, reviewer), ("Reason", reason or "Not given"))
    step = _REWORK_STEP if ctx.is_executor() else "Sent back for rework. " + _FYI
    return _message(ctx, "Rework Required", rows, step, ctx.rework_actions())


def _render_verification_recorded(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    reviewer = _user_name(db, payload.get("verified_by"))
    if payload.get("decision") == "rejected":
        return _render_rework(ctx, "Rejected by", reviewer, payload.get("remarks"))
    rows = ctx.rows(*ctx.type_rows(with_flow=True), ("Verified by", reviewer))
    if _is_class_a_work(ctx):
        # The PM approval request (U10), built from the verified submission.
        submission = _Submission(db, payload)
        rows = ctx.rows(
            *ctx.type_rows(with_flow=True),
            ("Verified by", reviewer),
            ("Submitted by", _user_name(db, payload.get("submitted_by"), fallback="Unknown user")),
            ("Latest note", submission.latest_note or "No note"),
            ("Evidence", submission.evidence_summary()),
        )
        verification_id = _uuid_or_none(payload.get("verification_id"))
        actions = ctx.approval_actions(verification_id.hex[:8] if verification_id else None)
        files = () if ctx.is_executor() else submission.attachments()
        if actions:
            step = _APPROVAL_STEP
        elif ctx.is_ineligible_approver():
            approvals = TaskApprovalService(db)
            if approvals.eligible_pm_user_ids(ctx.task) or approvals.has_eligible_admin(ctx.task):
                step = "You verified this as a fallback, so a different PM or an Admin must approve it."
            else:
                step = NO_ELIGIBLE_APPROVER
        elif ctx.is_executor():
            step = "Your work passed verification and is now waiting for PM approval."
        else:
            step = _FYI
        title = "Task Ready for Approval" if actions else "Verified - Awaiting PM Approval"
        return _message(ctx, title, rows, step, actions, attachments=files)
    step = "Your work was verified. Nothing more to do on this task." if ctx.is_executor() else _FYI
    return _message(ctx, "Task Completed", rows, step)


def _render_approval_recorded(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    reviewer = _user_name(db, payload.get("decided_by"))
    if payload.get("decision") == "rejected":
        return _render_rework(ctx, "Rejected by", reviewer, payload.get("remarks"))
    step = "Your work was approved. Nothing more to do on this task." if ctx.is_executor() else _FYI
    return _message(
        ctx, "Task Approved and Completed", ctx.rows(*ctx.type_rows(with_flow=True), ("Approved by", reviewer)), step,
    )


# ---- support assignment ------------------------------------------------------


def _render_support_assigned(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    responsibility = [("Responsibility", payload["responsibility"])] if payload.get("responsibility") else []
    planned = [("Planned start", _date(ctx.task.planned_start_date))] if ctx.task is not None else []
    actions = ctx.start_actions()
    if recipient_employee_id is not None and str(recipient_employee_id) == str(payload.get("employee_id")):
        assignment_id = _uuid_or_none(payload.get("assignment_id"))
        assignment = db.get(TaskSupportAssignment, assignment_id) if assignment_id else None
        if assignment is not None and assignment.status == "active" and assignment.ends_at is None and assignment.acknowledged_at is None:
            # T2: the assignee confirms they received it, before any start button.
            actions = ((TelegramAction("Acknowledge", "", ack_callback(_ACK_SUPPORT_ASSIGNMENT, assignment.id)),),) + actions
        return _message(
            ctx, "Task Assigned to You", ctx.rows(*ctx.type_rows(), *responsibility, *planned),
            "You are responsible for doing this task and logging its progress.", actions,
        )
    rows = ctx.rows(("Employee", _employee_name(db, payload.get("employee_id"))), *responsibility)
    return _message(ctx, "Employee Assigned to Task", rows, None if actions else _FYI, actions)


def _render_support_ended(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    replacement = payload.get("replacement_employee_id")
    replaced = [("Replaced by", _employee_name(db, replacement))] if replacement else []
    reason = [("Reason", _label(payload.get("reason_code")))] if payload.get("reason_code") else []
    if recipient_employee_id is not None and str(recipient_employee_id) == str(payload.get("previous_employee_id")):
        return _message(ctx, "No Longer Assigned to You", ctx.rows(*replaced, *reason), "You are no longer responsible for this task.")
    if replacement and recipient_employee_id is not None and str(recipient_employee_id) == str(replacement):
        return _message(
            ctx, "Task Assigned to You", ctx.rows(("Previously", _employee_name(db, payload.get("previous_employee_id")))),
            "You are responsible for doing this task and logging its progress.", ctx.start_actions(),
        )
    rows = ctx.rows(("Employee", _employee_name(db, payload.get("previous_employee_id"))), *replaced, *reason)
    return _message(ctx, "Task Assignment Ended", rows, _FYI)


# ---- blockers, delays, schedule ---------------------------------------------


def _render_blocker_created(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    reporter = [("Reported by", _user_name(db, payload.get("reported_by")))] if payload.get("reported_by") else []
    rows = ctx.rows(
        ("Type", payload.get("type") or "Not given"), ("Description", payload.get("description") or "Not given"), *reporter,
    )
    blocker_id = _uuid_or_none(payload.get("blocker_id"))
    blocker = db.get(TaskBlocker, blocker_id) if blocker_id else None
    # [Resolve] (U12): only for the blocker service's resolvers, only while it
    # is still open. The button carries the blocker's id.
    actions: tuple[tuple[TelegramAction, ...], ...] = ()
    if blocker is not None and blocker.resolved_at is None and ctx.can_resolve_blockers():
        actions = ((TelegramAction("Resolve", "", task_callback("bs", blocker.id)),),)
    step = "Resolve it once the blocker is cleared." if actions else _FYI
    return _message(ctx, "Blocker Reported", rows, step, actions)


def _render_blocker_resolved(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    blocker_id = _uuid_or_none(payload.get("blocker_id"))
    blocker = db.get(TaskBlocker, blocker_id) if blocker_id else None
    extra = [("Blocker", f"{blocker.type}: {blocker.description}")] if blocker else []
    reporter = _uuid_or_none(payload.get("reported_by"))
    is_reporter = reporter is not None and reporter == ctx.recipient_user_id
    step = "The blocker you reported was resolved." if is_reporter else _FYI
    return _message(
        ctx, "Blocker Resolved", ctx.rows(*extra, ("Resolved by", _user_name(db, payload.get("resolved_by")))), step,
    )


def _render_delay_recorded(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    delay_id = _uuid_or_none(payload.get("delay_id"))
    delay = db.get(TaskDelayEvent, delay_id) if delay_id else None
    days = payload.get("impact_days")
    rows = ctx.rows(
        ("Responsibility", _label(payload.get("responsibility_type"))),
        ("Impact", f"{days} day{'s' if days != 1 else ''}" if days is not None else "Not given"),
        *([("Reason", delay.reason)] if delay else []),
    )
    return _message(ctx, "Delay Recorded", rows, _FYI)


def _render_rescheduled(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(
        ("Start", f"{_date(payload.get('before_planned_start_date'))} -> {_date(payload.get('planned_start_date'))}"),
        ("Finish", f"{_date(payload.get('before_planned_end_date'))} -> {_date(payload.get('planned_end_date'))}"),
        ("Reason", payload.get("reason") or "Not given"),
    )
    return _message(ctx, "Task Rescheduled", rows, _FYI)


def _render_task_added(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(
        ("Planned", f"{_date(payload.get('planned_start_date'))} -> {_date(payload.get('planned_end_date'))}"),
        ("Added by", _user_name(db, payload.get("added_by"))),
        ("Reason", payload.get("reason") or "Not given"),
    )
    return _message(ctx, "New Task Added", rows, _FYI)


# ---- daily prompts and follow-ups ----------------------------------------------


def _status_row(payload: dict) -> tuple[str, str]:
    status = payload.get("lifecycle_status")
    return "Status", _STATUS_LABELS.get(status, _label(status))


# T3-T5: every reminder below is sent by `task_reminders.py` at a fixed
# Asia/Kolkata time; the buttons are whatever the recipient may do now.


def _render_prestart_warning(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(_status_row(payload), ("Planned start", _date(payload.get("planned_start_date"))))
    actions = ctx.report_blocker_actions()
    step = (
        "This task starts tomorrow. Check that materials, people and access are in place, "
        "and report a blocker now if anything will stop it starting."
    ) if actions else _FYI
    return _message(ctx, "Task Starts Tomorrow", rows, step, actions)


def _render_readiness_check(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(_status_row(payload), ("Planned start", _date(payload.get("planned_start_date"))))
    actions = ctx.readiness_actions()
    step = (
        "Can this task start tomorrow? Tap Ready, or Need Help / Issue and tell us what is missing."
    ) if actions else _FYI
    return _message(ctx, "Can This Task Start Tomorrow?", rows, step, actions)


def _render_start_check(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(_status_row(payload), ("Planned start", _date(payload.get("planned_start_date"))))
    actions = ctx.start_actions()
    step = "This task starts today. Start it when work begins." if actions or ctx.is_executor() else _FYI
    return _message(ctx, "Task Starts Today", rows, step, actions + ctx.report_blocker_actions())


def _render_midday_check(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    actions = ctx.progress_and_submit_actions()
    step = "How is it going? Add today's progress so far, or submit it if the work is complete." if actions else _FYI
    return _message(ctx, "Midday Check", ctx.rows(_status_row(payload)), step, actions + ctx.report_blocker_actions())


def _render_eod_check(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(_status_row(payload), ("Planned finish", _date(payload.get("planned_end_date"))))
    actions = ctx.progress_and_submit_actions()
    step = (
        "End of day: add what was completed today, submit the task if it is finished, "
        "or report a delay if it will not finish on time."
    ) if actions else _FYI
    return _message(ctx, "End-of-Day Check", rows, step, actions + ctx.report_delay_actions() + ctx.report_blocker_actions())


def _render_sla_overdue(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    rows = ctx.rows(_status_row(payload), ("Was due", _date(payload.get("planned_end_date"))))
    actions = ctx.progress_and_submit_actions(submit_label="Submit Now") + ctx.report_delay_actions()
    step = (
        "This task was due yesterday and has not been submitted. Submit it now if it is finished, "
        "or report a delay with the reason. Your PM will be alerted at 9:30 AM."
    ) if actions else "This task was due yesterday and has not been submitted. " + _FYI
    return _message(ctx, "Task Overdue", rows, step, actions)


def _render_sla_escalated(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    assignees = []
    last_update = None
    if ctx.task is not None:
        assignees = [
            _employee_name(db, employee_id) for employee_id in db.scalars(
                select(TaskSupportAssignment.employee_id).where(
                    TaskSupportAssignment.task_id == ctx.task.id, TaskSupportAssignment.status == "active",
                )
            )
        ]
        last_update = db.scalar(
            select(TaskProgressUpdate.created_at).where(TaskProgressUpdate.task_id == ctx.task.id)
            .order_by(TaskProgressUpdate.created_at.desc()).limit(1)
        )
    rows = ctx.rows(
        _status_row(payload),
        ("Was due", _date(payload.get("planned_end_date"))),
        ("Assigned to", ", ".join(assignees) or "Nobody"),
        ("Last progress", _date(last_update) if last_update else "None logged"),
    )
    return _message(
        ctx, "Escalation: Task Overdue", rows,
        "This task is past its due date, has not been submitted, and the assignee was reminded at 6:30 AM. "
        "Please follow up.",
    )


_READINESS_LABELS = {"ready": "Ready", "issue": "Issue", "need_help": "Need Help"}


def _render_readiness_declared(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
    ctx = _Ctx(db, payload, recipient_employee_id)
    status = _READINESS_LABELS.get(payload.get("status"), _label(payload.get("status")))
    declaration = None
    declaration_id = _uuid_or_none(payload.get("declaration_id"))
    if declaration_id:
        declaration = db.get(TaskReadinessDeclaration, declaration_id)
    rows = ctx.rows(
        ("Readiness", status),
        ("Declared by", _user_name(db, declaration.declared_by) if declaration else "Unknown user"),
        *([("Note", payload["note"])] if payload.get("note") else []),
    )
    step = _FYI if payload.get("status") == "ready" else "Help is needed before this task can start. Please follow up."
    return _message(ctx, f"Readiness: {status}", rows, step)


def _render_no_update(title: str) -> Callable[[Session, dict, uuid.UUID | None], TelegramMessage]:
    def _render(db: Session, payload: dict, recipient_employee_id: uuid.UUID | None) -> TelegramMessage:
        ctx = _Ctx(db, payload, recipient_employee_id)
        hours = payload.get("update_sla_hours")
        status = _STATUS_LABELS.get(payload.get("lifecycle_status"), _label(payload.get("lifecycle_status")))
        rows = ctx.rows(("Status", status), *([("Expected update every", f"{hours} hours")] if hours else []))
        step = "Please log a progress update." if ctx.is_executor() else "No progress update has been logged in time. " + _FYI
        return _message(ctx, title, rows, step)

    return _render


TASK_RENDERERS: dict[str, Callable[[Session, dict, uuid.UUID | None], TelegramMessage]] = {
    "task.status_changed": _render_status_changed,
    "task.verification_recorded": _render_verification_recorded,
    "task.approval_recorded": _render_approval_recorded,
    "task.support_assigned": _render_support_assigned,
    "task.support_ended": _render_support_ended,
    "task.blocker_created": _render_blocker_created,
    "task.blocker_resolved": _render_blocker_resolved,
    "task.delay_recorded": _render_delay_recorded,
    "task.rescheduled": _render_rescheduled,
    "task.added": _render_task_added,
    "task.prestart_warning": _render_prestart_warning,
    "task.readiness_check": _render_readiness_check,
    "task.start_check": _render_start_check,
    "task.midday_check": _render_midday_check,
    "task.eod_check": _render_eod_check,
    "task.sla_overdue": _render_sla_overdue,
    "task.sla_escalated": _render_sla_escalated,
    "task.readiness_declared": _render_readiness_declared,
    "task.eod_followup_required": _render_no_update("Progress Update Overdue"),
    "task.escalated_to_admin": _render_no_update("Escalated: Progress Update Overdue"),
}
