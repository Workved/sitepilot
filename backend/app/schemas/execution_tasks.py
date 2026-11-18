import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.execution_models import TASK_LIFECYCLE_STATUSES
from app.template_schemas import TemplateReferenceFileItem
from app.services.task_approval_metadata import ApprovalMetadataOut
from app.services.task_delay_variance import DelayVariance
from app.services.task_readiness import ReadinessReason, TaskReadiness, UnresolvedApproval

TaskLifecycleStatus = Literal[
    "planned", "ready", "in_progress", "submitted", "verified",
    "approval_pending", "rejected", "completed", "cancelled",
]


class TaskStatusTransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: TaskLifecycleStatus
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @field_validator("target_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in TASK_LIFECYCLE_STATUSES:
            raise ValueError("Unknown task lifecycle status.")
        return value


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    title: str
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskEvidenceOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    evidence_type: str
    caption: str | None
    original_filename: str
    mime_type: str
    size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class TaskVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["verified", "rejected"]
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    remarks: str | None = Field(default=None, max_length=2000)

    @field_validator("remarks")
    @classmethod
    def normalize_remarks(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskVerificationOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    submission_update_id: uuid.UUID
    decision: str
    remarks: str | None
    verified_by: uuid.UUID
    verified_at: datetime
    decision_mode: str
    task: TaskOut

    model_config = ConfigDict(from_attributes=True)


class TaskApprovalOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    verification_id: uuid.UUID | None
    decision: str
    remarks: str | None
    decided_by: uuid.UUID
    decided_at: datetime
    decision_mode: str
    task: TaskOut

    model_config = ConfigDict(from_attributes=True)


class TaskBlockerCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    owner_employee_id: uuid.UUID | None = None

    @field_validator("type", "description")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class TaskBlockerOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    type: str
    description: str
    owner_employee_id: uuid.UUID | None
    started_at: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


DelayResponsibilityType = Literal[
    "vendor", "client", "approval", "design", "site_readiness", "internal", "other",
]


class TaskDelayCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    responsibility_type: DelayResponsibilityType
    responsible_vendor_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    impact_days: int = Field(gt=0)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class TaskDelayOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    responsibility_type: str
    responsible_vendor_id: uuid.UUID | None
    reason: str
    impact_days: int
    recorded_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


ReadinessDeclarationStatus = Literal["ready", "issue", "need_help"]


class TaskReadinessDeclarationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReadinessDeclarationStatus
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskReadinessDeclarationOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    declared_by: uuid.UUID
    status: str
    note: str | None
    declared_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskRescheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_planned_start_date: date
    new_planned_end_date: date
    # Optional at the schema layer, same shape as TaskStatusTransitionIn's
    # `reason` - required-and-blank is enforced by TaskRescheduleService
    # itself (mirrors task_lifecycle.py's transition() cancel-reason check),
    # not here.
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskRescheduleOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    title: str
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    planned_start_date: date | None
    planned_end_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskSupportAssignmentCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: uuid.UUID
    responsibility: str = Field(min_length=1, max_length=2000)

    @field_validator("responsibility")
    @classmethod
    def normalize_responsibility(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned


class TaskSupportAssignmentEndIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = Field(min_length=1, max_length=200)
    reason_detail: str | None = Field(default=None, max_length=2000)
    # Optional atomic reassignment: TaskSupportAssignmentService.end_support
    # already creates a replacement assignment in the same transaction when
    # this is set, rather than requiring a separate end + assign round trip.
    replacement_employee_id: uuid.UUID | None = None

    @field_validator("reason_code")
    @classmethod
    def normalize_reason_code(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned

    @field_validator("reason_detail")
    @classmethod
    def normalize_reason_detail(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None


class TaskSupportAssignmentOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    employee_id: uuid.UUID
    responsibility: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    assigned_by: uuid.UUID
    created_at: datetime
    acknowledged_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskProgressUpdateOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    update_type: str
    status_claim: str | None
    note: str | None
    submitted_by: uuid.UUID
    source: str
    created_at: datetime
    reviewed_at: datetime | None = None
    evidence: list[TaskEvidenceOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ReadinessReasonOut(BaseModel):
    """U15: one named fact standing between a task and being ready.

    Mirrors `task_readiness.ReadinessReason` field for field rather than
    inventing a second vocabulary: `detail` is the sentence the engine
    already wrote (the frontend must not recompose it, or the board and the
    engine would drift), and `subject_id` is the predecessor task or the
    approval itself so a client can link straight to it instead of parsing
    prose. `blocking` is carried even though blockers and advisories arrive
    in separate lists, so a client rendering a merged view keeps the flag.
    """

    kind: str
    subject_id: uuid.UUID
    detail: str
    blocking: bool

    model_config = ConfigDict(from_attributes=False)

    @classmethod
    def from_reason(cls, reason: ReadinessReason) -> "ReadinessReasonOut":
        return cls(
            kind=reason.kind,
            subject_id=reason.subject_id,
            detail=reason.detail,
            blocking=reason.blocking,
        )


class TaskReadinessOut(BaseModel):
    """U15: one task's computed readiness, as `TaskReadinessService` answered it.

    `reasons` are the facts that actually hold the task; `advisories` are the
    unsatisfied-but-non-blocking ones the engine deliberately keeps separate
    (a PM marked that dependency or approval non-blocking, and reporting it
    as a blocker would override their decision). Both lists are sent so the
    board can show the whole picture without re-deriving which is which.

    Readiness is advisory this release (R5, KTD1): this is a projection of
    already-persisted facts, never a statement about which lifecycle
    transitions the portal permits.
    """

    state: str
    reasons: list[ReadinessReasonOut] = Field(default_factory=list)
    advisories: list[ReadinessReasonOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=False)

    @classmethod
    def from_readiness(cls, readiness: TaskReadiness) -> "TaskReadinessOut":
        return cls(
            state=readiness.state,
            reasons=[ReadinessReasonOut.from_reason(reason) for reason in readiness.reasons],
            advisories=[ReadinessReasonOut.from_reason(reason) for reason in readiness.advisories],
        )


class TaskVarianceOut(BaseModel):
    """U15: one task's schedule variance, computed by U13 on the way out.

    `days` is the unsigned magnitude a screen renders ("2 days early") and
    `variance_days` keeps the sign so a client can sort or sum without
    consulting `status` first - both are sent because deriving one from the
    other in the frontend is exactly the recomputation this unit removes.
    """

    status: str
    variance_days: int
    days: int
    measured_against: str | None

    model_config = ConfigDict(from_attributes=False)

    @classmethod
    def from_variance(cls, variance: DelayVariance) -> "TaskVarianceOut":
        return cls(
            status=variance.status,
            variance_days=variance.variance_days,
            days=variance.days,
            measured_against=variance.measured_against,
        )


class UnresolvedApprovalOut(BaseModel):
    """U15: an external approval whose task coverage could not be resolved.

    A project-level fact, not a per-task one (R10): an unresolved approval
    has no rows in `project_external_approval_tasks`, so no task is ever
    mapped to one and it can never appear as a task's readiness reason. It
    rides on the list rows because the list response is a JSON array and has
    no other place to put a project fact - see `list_project_tasks`.
    """

    approval_id: uuid.UUID
    status: str
    blocking: bool
    coverage_text: str | None

    model_config = ConfigDict(from_attributes=False)

    @classmethod
    def from_unresolved(cls, approval: UnresolvedApproval) -> "UnresolvedApprovalOut":
        return cls(
            approval_id=approval.approval_id,
            status=approval.status,
            blocking=approval.blocking,
            coverage_text=approval.coverage_text,
        )


class TaskListItemOut(BaseModel):
    """List row for the execution board (TaskExecutionBoard). Blockers and
    support assignments are summarized as counts here - the full detail
    (individual blocker/delay/verification/approval/support records) is
    only fetched per-task, via TaskDetailOut, when a row is expanded."""

    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    template_sequence: int
    title: str
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    schedule_classification: str
    planned_start_day: int | None
    planned_end_day: int | None
    # The resolved calendar dates alongside the baseline day offsets. The
    # board needs the planned start to tell a user that a start would be
    # early; re-deriving it client-side from the offsets would put a second
    # copy of the derivation rule in the frontend.
    planned_start_date: date | None
    planned_end_date: date | None
    # The recorded actuals alongside the promise, so the board and U16's
    # timeline read one payload instead of each fetching them separately.
    actual_start_at: datetime | None
    actual_finish_at: datetime | None
    phase: str | None
    category: str | None
    evidence_required: bool
    open_blocker_count: int
    active_support_count: int
    approval: ApprovalMetadataOut
    # U15: readiness and variance are computed server-side and attached
    # here. Both are derived from facts the client would otherwise have to
    # re-derive - and a client's copy of the dependency/approval rules would
    # drift from the engine's, which is worse than no board.
    readiness: TaskReadinessOut
    variance: TaskVarianceOut
    project_unresolved_approvals: list[UnresolvedApprovalOut] = Field(default_factory=list)
    added_after_start: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskDependencyRefOut(BaseModel):
    id: uuid.UUID
    original_code: str
    title: str
    lifecycle_status: str
    task_kind: str | None
    task_class: str | None
    dependency_type: str
    blocking: bool


class TaskVerificationSummaryOut(BaseModel):
    id: uuid.UUID
    submission_update_id: uuid.UUID
    decision: str
    remarks: str | None
    verified_by: uuid.UUID
    verified_by_name: str | None = None
    verified_at: datetime
    decision_mode: str

    model_config = ConfigDict(from_attributes=True)


class TaskApprovalSummaryOut(BaseModel):
    id: uuid.UUID
    verification_id: uuid.UUID | None
    decision: str
    remarks: str | None
    decided_by: uuid.UUID
    decided_by_name: str | None = None
    decided_at: datetime
    decision_mode: str

    model_config = ConfigDict(from_attributes=True)


class TaskAuditEventOut(BaseModel):
    """A `TASK_STATUS_CHANGED` audit trail entry for one task - the only
    audit events any task service currently writes (task_lifecycle.py's
    `transition()`, for every status change including cancellation and
    system-driven milestone auto-completion). Read-only history; not a new
    table or migration."""

    id: uuid.UUID
    action: str
    source: str
    before_status: str | None
    after_status: str | None
    reason: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None = None
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=False)


class TaskDetailOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    baseline_id: uuid.UUID
    original_code: str
    template_sequence: int
    title: str
    # A task added after the project started (not in the original plan).
    added_after_start: bool = False
    added_by_name: str | None = None
    added_reason: str | None = None
    description: str | None
    task_kind: str | None
    task_class: str | None
    lifecycle_status: str
    schedule_classification: str
    planned_start_day: int | None
    planned_end_day: int | None
    planned_start_date: date | None
    planned_end_date: date | None
    actual_start_at: datetime | None
    actual_finish_at: datetime | None
    # U14 wrote this on the row and into the audit event, and then nothing
    # could ever read it back - the reason a task started ahead of plan was
    # captured from the user and visible to nobody. Carried on the detail
    # response only: it is per-task narrative, and the board's list rows have
    # no place to show a sentence.
    early_start_reason: str | None
    phase: str | None
    category: str | None
    evidence_required: bool
    # From the template version this project is pinned to (Template Builder Phase 2).
    evidence_instructions: str | None = None
    reference_files: list[TemplateReferenceFileItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    approval: ApprovalMetadataOut
    # Same computed readiness the list row carries, from the same engine, so
    # opening a task cannot contradict the row it was opened from.
    readiness: TaskReadinessOut
    variance: TaskVarianceOut
    actor_is_assigned_support: bool
    predecessors: list[TaskDependencyRefOut] = Field(default_factory=list)
    progress_updates: list[TaskProgressUpdateOut] = Field(default_factory=list)
    verifications: list[TaskVerificationSummaryOut] = Field(default_factory=list)
    approvals: list[TaskApprovalSummaryOut] = Field(default_factory=list)
    audit_events: list[TaskAuditEventOut] = Field(default_factory=list)
    blockers: list[TaskBlockerOut] = Field(default_factory=list)
    delays: list[TaskDelayOut] = Field(default_factory=list)
    support_assignments: list[TaskSupportAssignmentOut] = Field(default_factory=list)
