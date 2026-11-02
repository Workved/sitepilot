"""Execution-layer models (U1): baseline lock and instantiated task graph.

`project_baselines` / `baseline_tasks` are the immutable snapshot captured at
project activation. `tasks` / `task_dependencies` are the execution-layer
entities instantiated from that snapshot at activation time.

This is a deliberately NEW table pair, distinct from
`app.project_models.V2ProjectTask` / `V2ProjectTaskDependency` (the planning
table, still `lifecycle_status = 'draft'`-only). `V2ProjectTask` remains
purely a planning/authoring artifact; `tasks` here is purely an execution
artifact. Never conflate the two - see the plan's Key Technical Decisions.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA


TASK_LIFECYCLE_STATUSES = (
    "planned", "ready", "in_progress", "submitted", "verified",
    "approval_pending", "rejected", "completed", "cancelled",
)

EXTERNAL_APPROVAL_STATUSES = ("unassigned", "assigned", "submitted", "approved", "rejected")
"""Plan: External Approval Gate Assignment & Evidence Lifecycle (U1/U2).

Widened from the original ('pending', 'approved', 'rejected'). 'rejected' is
a real but briefly-held state: `ProjectGateDecisionService.decide()` persists
it (with `rejection_reason`/`decided_by`/`decided_at` set) before a second
transition in the same call moves the row on to 'assigned' for resubmission -
see project_gate_decision.py."""

EXTERNAL_APPROVAL_COVERAGE_STATES = ("exact", "unresolved")
"""U8: whether an approval's task coverage was resolvable at activation.

`exact` means the template named specific tasks and this approval's coverage
links are those tasks. `unresolved` means it did not - the template described
coverage in prose, or named nothing at all - and the prose is carried on the
row instead. The distinction has to be stored rather than inferred from an
empty link set, because "covers no tasks" and "we do not know what this
covers" are opposite answers and R10 forbids guessing between them.
"""


def is_work_task_kind(task_kind: str | None) -> bool:
    """Whether a task should go through the `work` (Supervisor verification,
    optionally PM approval) path, per BR-008.

    `task_kind` is nullable at the DB level (baseline_tasks/tasks'
    CheckConstraint allows it) - a task whose template row never had a kind
    assigned during authoring still needs a real completion path, and
    "ordinary work requiring Supervisor verification" is the only safe
    default: it never skips a required PM approval (that's driven by
    `task_class`, checked independently) and never mistakenly grants
    milestone auto-completion or gate semantics. Only an *explicit*
    `milestone`/`approval_gate` value opts a task out of this path.
    """
    return task_kind not in ("milestone", "approval_gate")


# The only task_class values baseline_tasks/tasks accept (ck_v2_*_task_class).
# Template and project-task rows have no such DB check, so the app validates
# against this before a bad value can reach activation.
TASK_CLASSES = ("standard", "class_a")

# The only non-null task_kind values baseline_tasks/tasks accept
# (ck_v2_*_task_kind); null is ordinary work (see is_work_task_kind).
TASK_KINDS = ("work", "approval_gate", "milestone")


class ProjectBaseline(Base):
    __tablename__ = "project_baselines"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_v2_project_baselines_project"),
        CheckConstraint("task_count > 0", name="ck_v2_project_baselines_task_count_positive"),
        CheckConstraint("dependency_count >= 0", name="ck_v2_project_baselines_dependency_count"),
        CheckConstraint("gate_count >= 0", name="ck_v2_project_baselines_gate_count"),
        Index("ix_v2_project_baselines_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BaselineTask(Base):
    """An immutable snapshot row of one included V2ProjectTask at lock time.

    DB-level immutability (reject UPDATE/DELETE) is enforced by a Postgres
    trigger in the migration, not by application code - see
    supabase/migrations/202608020001_v2_project_baseline_and_tasks.sql.
    `content_hash` here is a cheap cross-environment integrity check only.
    """

    __tablename__ = "baseline_tasks"
    __table_args__ = (
        UniqueConstraint("baseline_id", "project_task_id", name="uq_v2_baseline_tasks_baseline_project_task"),
        UniqueConstraint("baseline_id", "original_code", name="uq_v2_baseline_tasks_baseline_code"),
        CheckConstraint("template_sequence > 0", name="ck_v2_baseline_tasks_sequence_positive"),
        CheckConstraint("schedule_classification in ('pre_activation', 'execution')", name="ck_v2_baseline_tasks_schedule_classification"),
        CheckConstraint("applicability in ('mandatory', 'conditional')", name="ck_v2_baseline_tasks_applicability"),
        CheckConstraint("task_class is null or task_class in ('standard', 'class_a')", name="ck_v2_baseline_tasks_task_class"),
        CheckConstraint("task_kind is null or task_kind in ('work', 'approval_gate', 'milestone')", name="ck_v2_baseline_tasks_task_kind"),
        Index("ix_v2_baseline_tasks_baseline", "baseline_id"),
        Index("ix_v2_baseline_tasks_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_baselines.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    project_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_tasks.id", ondelete="RESTRICT"), nullable=False)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    template_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_classification: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start_day: Mapped[int | None] = mapped_column(SmallInteger)
    planned_end_day: Mapped[int | None] = mapped_column(SmallInteger)
    phase: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, nullable=False)
    task_class: Mapped[str | None] = mapped_column(Text)
    task_kind: Mapped[str | None] = mapped_column(Text)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Task(Base):
    """Execution-layer task instantiated from a BaselineTask at activation."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "original_code", name="uq_v2_tasks_project_code"),
        UniqueConstraint("baseline_task_id", name="uq_v2_tasks_baseline_task"),
        CheckConstraint("template_sequence > 0", name="ck_v2_tasks_sequence_positive"),
        CheckConstraint("schedule_classification in ('pre_activation', 'execution')", name="ck_v2_tasks_schedule_classification"),
        CheckConstraint("applicability in ('mandatory', 'conditional')", name="ck_v2_tasks_applicability"),
        CheckConstraint("task_class is null or task_class in ('standard', 'class_a')", name="ck_v2_tasks_task_class"),
        CheckConstraint("task_kind is null or task_kind in ('work', 'approval_gate', 'milestone')", name="ck_v2_tasks_task_kind"),
        CheckConstraint(f"lifecycle_status in {TASK_LIFECYCLE_STATUSES!r}", name="ck_v2_tasks_lifecycle_status"),
        CheckConstraint("update_sla_hours is null or update_sla_hours > 0", name="ck_v2_tasks_update_sla_hours_positive"),
        CheckConstraint("early_start_reason is null or actual_start_at is not null", name="ck_v2_tasks_early_start_reason_requires_start"),
        CheckConstraint("actual_finish_at is null or actual_start_at is null or actual_finish_at >= actual_start_at", name="ck_v2_tasks_actual_finish_after_start"),
        CheckConstraint("planned_end_date is null or planned_start_date is null or planned_end_date >= planned_start_date", name="ck_v2_tasks_planned_end_after_start"),
        Index("ix_v2_tasks_project_sequence", "project_id", "template_sequence"),
        Index("ix_v2_tasks_baseline", "baseline_id"),
        Index("ix_v2_tasks_project_status", "project_id", "lifecycle_status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_baselines.id", ondelete="RESTRICT"), nullable=False)
    baseline_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.baseline_tasks.id", ondelete="RESTRICT"), nullable=False)
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    template_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_classification: Mapped[str] = mapped_column(Text, nullable=False)
    planned_start_day: Mapped[int | None] = mapped_column(SmallInteger)
    planned_end_day: Mapped[int | None] = mapped_column(SmallInteger)
    phase: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, nullable=False)
    task_class: Mapped[str | None] = mapped_column(Text)
    task_kind: Mapped[str | None] = mapped_column(Text)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    lifecycle_status: Mapped[str] = mapped_column(Text, nullable=False, default="planned")
    created_from_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Phase 3 U1: when set, a task not `completed`/`cancelled` past this
    timestamp counts toward the `overdue` derived condition. Nullable -
    not every task carries a due date."""
    update_sla_hours: Mapped[int | None] = mapped_column(Integer)
    """Phase 3 U1: when set, a task not `completed`/`cancelled` whose most
    recent `TaskProgressUpdate` (or `created_at`, if none exists) is older
    than this many hours counts toward the `no_update` derived condition."""
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)
    """U5/U9: the baseline day offsets resolved against the project's start
    date. `date`, not a timestamp - a planned day is a calendar concept with
    no time-of-day, and `V2Project.start_date` it derives from is itself a
    bare date. Null for a pre-activation task, which sits outside the
    execution window. Never rewritten by actual execution: the immutable
    baseline stays in `planned_start_day`/`planned_end_day`."""
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_finish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """U5/U10: when work really began and ended, written by the lifecycle
    transition. Instants rather than dates, matching every other timestamp
    in this schema. `actual_start_at` is written once and never overwritten
    when a rejected task reopens; `actual_finish_at` stays null for a
    cancelled task, which never finished."""
    early_start_reason: Mapped[str | None] = mapped_column(Text)
    """U5/U14: why this task started ahead of its planned start date.
    Required by the transition when the start is early; null otherwise."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TaskDependency(Base):
    """Execution-layer dependency edge, copied 1:1 from the baseline graph."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("project_id", "predecessor_task_id", "successor_task_id", "dependency_type", name="uq_v2_task_dependencies_edge"),
        CheckConstraint("predecessor_task_id <> successor_task_id", name="ck_v2_task_dependencies_not_self"),
        CheckConstraint("dependency_type in ('finish_to_start', 'start_to_start')", name="ck_v2_task_dependencies_type"),
        Index("ix_v2_task_dependencies_project", "project_id"),
        Index("ix_v2_task_dependencies_predecessor", "predecessor_task_id"),
        Index("ix_v2_task_dependencies_successor", "successor_task_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_baselines.id", ondelete="RESTRICT"), nullable=False)
    project_dependency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_task_dependencies.id", ondelete="RESTRICT"))
    predecessor_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    successor_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    dependency_type: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_text: Mapped[str | None] = mapped_column(Text)
    created_from_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectExternalApproval(Base):
    """U4: the runtime state of one external approval, instantiated at
    activation from the planning-layer `V2ProjectExternalGate` it names.

    This table exists precisely so that `project_external_gates` does not
    have to carry it. That table's `status` is a Draft-time review marker,
    CHECK-constrained to `pending_review` and written only while the project
    is still a draft; `applicability_state` beside it answers a different
    question again (does this approval apply to this project at all?).
    Neither answers the runtime question "has the approval been granted?",
    and answering it there would split one approval's state across the
    planning and execution families - see KTD3/KTD8.

    The gate link mirrors how `Task` points at `BaselineTask`: it is the
    instantiated-from reference, unique because an approval is instantiated
    exactly once per gate. It is the ONE place the execution layer names a
    planning-layer row; readiness itself reads only this table, never the
    gate.
    """

    __tablename__ = "project_external_approvals"
    __table_args__ = (
        UniqueConstraint("project_gate_id", name="uq_v2_project_external_approvals_gate"),
        CheckConstraint(f"status in {EXTERNAL_APPROVAL_STATUSES!r}", name="ck_v2_project_external_approvals_status"),
        # Decided means attributable. Without this, a half-written decision
        # would leave readiness and the audit trail disagreeing about
        # whether anyone actually granted anything.
        CheckConstraint(
            "(status in ('unassigned', 'assigned', 'submitted') and decided_by is null and decided_at is null)"
            " or (status in ('approved', 'rejected') and decided_by is not null and decided_at is not null)",
            name="ck_v2_project_external_approvals_decision_completeness",
        ),
        # Every state past 'unassigned' names an assignee - see U1's
        # migration for the full rationale.
        CheckConstraint(
            "(status = 'unassigned' and assigned_to_user_id is null)"
            " or (status <> 'unassigned' and assigned_to_user_id is not null)",
            name="ck_v2_project_external_approvals_assignment_completeness",
        ),
        CheckConstraint(f"coverage_state in {EXTERNAL_APPROVAL_COVERAGE_STATES!r}", name="ck_v2_project_external_approvals_coverage_state"),
        # Prose is what an unresolved approval has *instead of* links. An
        # exact approval carrying prose would mean both were true at once,
        # leaving no answer to "which tasks does this block?".
        CheckConstraint(
            "coverage_state = 'unresolved' or coverage_text is null",
            name="ck_v2_project_external_approvals_coverage_text",
        ),
        Index("ix_v2_project_external_approvals_project", "project_id"),
        # Readiness sweeps a project's still-pending approvals on every
        # recompute, so status is part of the lookup, not a filter after it.
        Index("ix_v2_project_external_approvals_project_status", "project_id", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    project_gate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_gates.id", ondelete="RESTRICT"), nullable=False)
    """RESTRICT, not the CASCADE the planning layer uses between projects and
    gates: a granted approval is an execution record and must not evaporate
    because a planning row was removed underneath it."""
    status: Mapped[str] = mapped_column(Text, nullable=False, default="unassigned")
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """U1/U2 (assignment lifecycle): who the gate is assigned to, who
    assigned them, and when. Cleared and reset together by assign()/
    reassign()/unassign() (project_gate_assignment.py) - never written
    incrementally, matching the decided_by/decided_at pairing below."""
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    """Set alongside decided_by/decided_at when decide() persists the
    intermediate 'rejected' state, but - unlike those two - NOT reset when
    the row moves on to 'assigned' in the same call, so the assignee and
    PM/Supervisor can see why a submission was rejected without querying
    the audit log directly."""
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    """U8: copied from `V2ProjectExternalGate.blocking`, which a PM sets while
    the project is a draft and the UI already renders as a "Blocking" badge.
    Without it here, readiness would block every task a deliberately
    non-blocking approval covers. Defaults to blocking, matching the gate."""
    coverage_state: Mapped[str] = mapped_column(Text, nullable=False, default="unresolved", server_default=text("'unresolved'"))
    """U8: `exact` or `unresolved` - see EXTERNAL_APPROVAL_COVERAGE_STATES.

    Defaults to `unresolved` rather than `exact` deliberately: a row written
    without stating its coverage has not proven it covers exactly its (zero)
    links, and surfacing it for a human beats silently claiming it blocks
    nothing (R10). Instantiation always states this explicitly."""
    coverage_text: Mapped[str | None] = mapped_column(Text)
    """The gate's `broad_mapping_text` verbatim when coverage is unresolved,
    so U12 can show a PM what the template actually asked for instead of an
    empty list. Null on an exact approval, and also null on an unresolved one
    whose gate carried no prose at all (`mapping_classification = 'unmapped'`)
    - both are unresolved, and neither is expanded into a guess."""
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Nullable pair, unlike `TaskApprovalDecision.decided_by`/`decided_at`:
    that model records a decision that has already happened, whereas this row
    exists from activation onward and spends its early life undecided. The
    completeness CHECK keeps the two columns moving together."""
    due_at: Mapped[date | None] = mapped_column(Date)
    """Phase 5: resolved at activation (`project_baseline.py`) from the
    gate's `required_by_type`/`required_by_value`
    (`app.services.project_gate_due_date.resolve_gate_due_at`). Nullable with
    no CHECK: a gate with no `required_by_type` set, or a `project_day` gate
    activated before `project.start_date` existed, legitimately has no due
    date - never invented."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ProjectExternalApprovalTask(Base):
    """U8: one execution task that an external approval covers.

    The execution-layer mirror of `V2ProjectExternalGateTask`, which points at
    planning-layer `project_tasks`. Activation maps each of those links
    through to the instantiated `tasks` row and records the result here, so
    readiness can answer "which tasks does this ungranted approval block?"
    without ever touching the planning tables (KTD8).

    Rows exist only where coverage was resolvable. An approval with
    `coverage_state = 'unresolved'` has none, which is why that state is a
    stored column and not something read off the absence of links here.

    No back-reference to the planning link row is kept: the approval already
    names its gate, and each task names its baseline task, so provenance is
    fully recoverable without a second FK into the planning family.
    """

    __tablename__ = "project_external_approval_tasks"
    __table_args__ = (
        UniqueConstraint("approval_id", "task_id", name="uq_v2_project_external_approval_tasks_pair"),
        Index("ix_v2_project_external_approval_tasks_approval", "approval_id"),
        # Readiness walks the other way too - given a task, which approvals
        # are still pending against it - so the task side is indexed as well.
        Index("ix_v2_project_external_approval_tasks_task", "task_id"),
        Index("ix_v2_project_external_approval_tasks_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    """Denormalised from the approval, as on `TaskDependency`, so a project's
    whole coverage set is one indexed read rather than a join."""
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approvals.id", ondelete="CASCADE"), nullable=False)
    """CASCADE, unlike the RESTRICT the approval itself uses toward the
    planning layer: this row has no meaning apart from its approval, so it
    should not outlive it."""
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectExternalApprovalSubmission(Base):
    """Plan: External Approval Gate Assignment & Evidence Lifecycle (U1/U2).

    Append-only submission of evidence against a `ProjectExternalApproval`,
    mirroring `TaskProgressUpdate`'s shape. One row per submit() call -
    including a resubmission after rejection, so the full history of what
    was submitted and when is retained rather than overwritten."""

    __tablename__ = "project_external_approval_submissions"
    __table_args__ = (
        Index("ix_v2_project_external_approval_submissions_approval", "approval_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approvals.id", ondelete="CASCADE"), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectExternalApprovalEvidence(Base):
    """Plan: External Approval Gate Assignment & Evidence Lifecycle (U1/U2).

    Real FK link between a submission and an uploaded file - deliberately
    NOT a polymorphic entity_type/entity_id reference, mirroring
    `TaskEvidence`'s Key Technical Decision for the same reason: this
    repo's non-polymorphic convention keeps a submission's evidence typed
    to exactly one entity rather than shared across unrelated ones."""

    __tablename__ = "project_external_approval_evidence"
    __table_args__ = (
        UniqueConstraint("submission_id", "file_id", name="uq_v2_project_external_approval_evidence_submission_file"),
        Index("ix_v2_project_external_approval_evidence_submission", "submission_id"),
        Index("ix_v2_project_external_approval_evidence_file", "file_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approval_submissions.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.file_objects.id", ondelete="RESTRICT"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False, default="photo")
    caption: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectExternalApprovalStatusCheck(Base):
    """Phase 3 (3c): an advisory, append-only self-reported health check
    ('on_track'/'blocked'/'need_help') against a `ProjectExternalApproval`,
    recorded by the approval's own assignee only
    (`project_gate_status_check.py`).

    The direct structural analog of `TaskBlocker`'s BLOCKED-overlay
    decision, applied to gates: it must never become a lifecycle status,
    never touches `ProjectExternalApproval.status`, and is never read by
    the formal assign/submit/decide state machine
    (`project_gate_assignment.py`, `project_gate_decision.py`). Point-in-
    time like `TaskDelayEvent`: every check is kept as its own row.
    """

    __tablename__ = "project_external_approval_status_checks"
    __table_args__ = (
        CheckConstraint(
            "health in ('on_track', 'waiting_external', 'blocked', 'need_help')",
            name="ck_v2_project_external_approval_status_checks_health",
        ),
        Index("ix_v2_project_external_approval_status_checks_approval_recorded", "approval_id", "recorded_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approvals.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    health: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectGateAcknowledgement(Base):
    """R3/R5/R6 (U5): a recorded 'accepted'/'declined' acknowledgement of a
    `ProjectExternalApproval` gate, from the employee it is assigned to.

    Append-only, mirroring `VendorAcknowledgement`'s own precedent exactly:
    every response is kept as its own row, even a second one against the
    same gate, and none is ever overwritten or deleted. Purely additive -
    it stands entirely alongside the formal assign/submit/decide state
    machine and never writes `ProjectExternalApproval.status`
    (`project_gate_assignment.py`, `project_gate_submission.py`,
    `project_gate_decision.py`), the same non-lifecycle framing already
    applied to `ProjectExternalApprovalStatusCheck`.
    """

    __tablename__ = "project_gate_acknowledgements"
    __table_args__ = (
        CheckConstraint(
            "response in ('accepted', 'declined')",
            name="ck_v2_project_gate_acknowledgements_response",
        ),
        Index("ix_v2_project_gate_acknowledgements_approval", "approval_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approvals.id", ondelete="RESTRICT"), nullable=False
    )
    response: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskProgressUpdate(Base):
    """U3: append-only progress note against an execution-layer task.

    Never itself changes `Task.lifecycle_status` - it's evidence a later
    `submitted` transition (U2's TaskLifecycleService) can reference. May
    optionally carry evidence files via `TaskEvidence` link rows.
    """

    __tablename__ = "task_progress_updates"
    __table_args__ = (
        CheckConstraint("update_type in ('note', 'evidence')", name="ck_v2_task_progress_updates_update_type"),
        CheckConstraint("source in ('portal', 'whatsapp', 'telegram', 'system')", name="ck_v2_task_progress_updates_source"),
        Index("ix_v2_task_progress_updates_task", "task_id"),
        Index("ix_v2_task_progress_updates_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    update_type: Mapped[str] = mapped_column(Text, nullable=False)
    status_claim: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="portal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set when a verification or approval decision (either outcome) covers
    this update. Null = logged since the task's last decision, i.e. the only
    progress a new submission may rest on."""


class FileObject(Base):
    """U3: metadata for one uploaded file. Bytes live in the private
    Supabase Storage `evidence` bucket (see app.services.evidence_storage),
    never a path passed to StaticFiles (see backend/app/main.py) - keyed by
    `storage_key`. This table never stores a public URL, only enough
    metadata for the authenticated download route to locate and validate
    the file."""

    __tablename__ = "file_objects"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_v2_file_objects_storage_key"),
        CheckConstraint("size_bytes > 0", name="ck_v2_file_objects_size_positive"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskEvidence(Base):
    """U3: real FK link between a progress update and an uploaded file -
    deliberately NOT a polymorphic entity_type/entity_id reference, per the
    plan's Key Technical Decisions."""

    __tablename__ = "task_evidence"
    __table_args__ = (
        UniqueConstraint("task_progress_update_id", "file_id", name="uq_v2_task_evidence_update_file"),
        Index("ix_v2_task_evidence_progress_update", "task_progress_update_id"),
        Index("ix_v2_task_evidence_file", "file_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_progress_update_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_progress_updates.id", ondelete="RESTRICT"), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.file_objects.id", ondelete="RESTRICT"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False, default="photo")
    caption: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskVerification(Base):
    """U4: a Supervisor's (or audited PM/Admin fallback's) verification
    decision on a `work` task's submitted evidence (BR-008). Never applies
    to `approval_gate` tasks - those skip Supervisor verification entirely
    and go straight to `TaskApprovalDecision`.

    `submission_update_id` links back to the `TaskProgressUpdate` (U3) that
    was being verified. On `decision == 'verified'`,
    `TaskLifecycleService.transition` advances the task to `verified`
    (and immediately to `completed` for `standard` work, since standard
    work needs no PM step). On `decision == 'rejected'`, the task returns
    to `in_progress` under Supervisor accountability again.
    """

    __tablename__ = "task_verifications"
    __table_args__ = (
        CheckConstraint("decision in ('verified', 'rejected')", name="ck_v2_task_verifications_decision"),
        Index("ix_v2_task_verifications_task", "task_id"),
        Index("ix_v2_task_verifications_task_verified_at", "task_id", "verified_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    submission_update_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_progress_updates.id", ondelete="RESTRICT"), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 'role_normal' (the project's own Supervisor), 'pm_fallback' (PM
    # standing in per BR-007), 'admin_fallback' (Admin/Super Admin standing
    # in with no active Supervisor on the project), or 'admin_override'
    # (Admin/Super Admin acting despite an active Supervisor existing) -
    # see TaskVerificationService.verify.
    decision_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="role_normal")


class TaskBlocker(Base):
    """U5: an independently queryable blocker condition on a task (BR-010).

    Blockers never touch `Task.lifecycle_status` - a task can be
    `in_progress` (or any other state) with an unresolved blocker logged
    against it at the same time. Any active project member may log one;
    only the accountable Supervisor/PM (or admin/super_admin fallback) may
    resolve it - see `backend/app/services/task_blocker.py`.
    """

    __tablename__ = "task_blockers"
    __table_args__ = (
        CheckConstraint(
            "(resolved_at is null and resolved_by is null) or (resolved_at is not null and resolved_by is not null)",
            name="ck_v2_task_blockers_resolution_pair",
        ),
        Index("ix_v2_task_blockers_task", "task_id"),
        Index("ix_v2_task_blockers_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    reported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    """Who logged the blocker (any channel), so they are told when it is
    resolved. Null on blockers logged before it was recorded."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskDelayEvent(Base):
    """U5: an independently queryable delay record on a task (BR-010).

    Never touches `Task.lifecycle_status`. `responsible_vendor_id` is a
    plain nullable uuid (not an FK - no vendor V2 table exists yet);
    required when `responsibility_type == 'vendor'`, must be null
    otherwise - enforced both at the DB (check constraint, migration) and
    application layer (`backend/app/services/task_delay.py`).
    """

    __tablename__ = "task_delay_events"
    __table_args__ = (
        CheckConstraint(
            "responsibility_type in ('vendor', 'client', 'approval', 'design', 'site_readiness', 'internal', 'other')",
            name="ck_v2_task_delay_events_responsibility_type",
        ),
        CheckConstraint("impact_days > 0", name="ck_v2_task_delay_events_impact_days_positive"),
        CheckConstraint(
            "(responsibility_type = 'vendor' and responsible_vendor_id is not null) "
            "or (responsibility_type <> 'vendor' and responsible_vendor_id is null)",
            name="ck_v2_task_delay_events_vendor_id_pairing",
        ),
        Index("ix_v2_task_delay_events_task", "task_id"),
        Index("ix_v2_task_delay_events_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    responsibility_type: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    impact_days: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskReadinessDeclaration(Base):
    """Phase 3 (3a): an advisory, append-only self-reported readiness signal
    against a task ('ready', 'issue', or 'need_help'), point-in-time like
    `TaskDelayEvent` - a task may be declared 'issue' and later 'ready'
    without either row being overwritten or deleted.

    Deliberately NOT read by `task_readiness.py`, which stays a pure
    derived projection over already-persisted facts (approvals,
    dependencies) per that service's own docstring - a declaration is a
    human's signal, not a fact the derived projection is computed from.
    Never touches `Task.lifecycle_status`.
    """

    __tablename__ = "task_readiness_declarations"
    __table_args__ = (
        CheckConstraint(
            "status in ('ready', 'issue', 'need_help')",
            name="ck_v2_task_readiness_declarations_status",
        ),
        Index("ix_v2_task_readiness_declarations_task_declared", "task_id", "declared_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    declared_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskReminderLog(Base):
    """Telegram T3-T5: one row per scheduled task reminder that was sent.

    The unique (task_id, reminder_type, scheduled_for_date) key is the
    at-most-once guarantee: the reminder service inserts this row in the same
    transaction as the reminder's outbox event, so a second scheduler pass (or
    a second server) hits the unique key and sends nothing.
    `scheduled_for_date` is an Asia/Kolkata calendar date - the day the
    reminder belongs to (the task's start or due date, or the day of a daily
    check)."""

    __tablename__ = "task_reminders_log"
    __table_args__ = (
        UniqueConstraint("task_id", "reminder_type", "scheduled_for_date", name="uq_v2_task_reminders_log_once"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="CASCADE"), nullable=False)
    reminder_type: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EscalationTracking(Base):
    """Phase 6 (first half): sweep-idempotency tracking for the escalation
    engine (`services/escalation.py`). One row per (entity_type, entity_id,
    stage) - unlike the three Phase 3 overlay tables just above, this table
    is NOT append-only: its whole purpose is to stop every sweep pass from
    double-tracking/double-emitting the same in-flight escalation, not to
    log a history of signals.

    `entity_id` deliberately carries no foreign key: it names a row in
    `Task` when `entity_type = 'task'`, or a row in `ProjectExternalApproval`
    when `entity_type = 'project_external_approval'`, and one column cannot
    hold two different real FKs at once. `TaskEvidence`'s docstring records
    this codebase's default of real, typed FKs over polymorphic
    entity_type/entity_id references; this is the one deliberate exception,
    forced by this table legitimately needing to watch two unrelated
    aggregate types with no shared parent to FK against instead.
    `EscalationService` never trusts a tracking row alone as truth - every
    sweep re-derives the referenced entity's live state (via its own FK'd
    query) before escalating further, so a stale row here without an
    explicit `resolved_at` is harmless.

    Only one OPEN row (`resolved_at is null`) may exist per (entity_type,
    entity_id, stage) - enforced by a PARTIAL unique index
    (`uq_v2_escalation_tracking_entity_stage_open`, `where resolved_at is
    null`), not a table-wide `UniqueConstraint` here: an entity that
    escalates, resolves, and later stalls again must be able to get a second
    row for the same stage. Mirrored below the same way
    `MessageDelivery.uq_v2_message_deliveries_provider_message_id` mirrors
    its own partial unique index, so both Postgres and the SQLite test
    harness enforce it - `EscalationService`'s own open-row check
    (`_has_open_tracking`) is the first line of defense, and
    `_commit_new_tracking` treats the `IntegrityError` this index raises on
    a lost race as a benign no-op rather than a crash.
    """

    __tablename__ = "escalation_tracking"
    __table_args__ = (
        CheckConstraint("entity_type in ('task', 'project_external_approval')", name="ck_v2_escalation_tracking_entity_type"),
        CheckConstraint("stage in ('followup', 'admin_escalation')", name="ck_v2_escalation_tracking_stage"),
        Index("ix_v2_escalation_tracking_entity", "entity_type", "entity_id"),
        Index(
            "uq_v2_escalation_tracking_entity_stage_open", "entity_type", "entity_id", "stage",
            unique=True,
            postgresql_where=text("resolved_at is null"),
            sqlite_where=text("resolved_at is null"),
        ),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskApprovalDecision(Base):
    """U4: a PM's (or audited Admin fallback's) approval decision (BR-008).

    Required for every `class_a` work task (after Supervisor verification -
    `verification_id` populated, and the verifying actor may not also be
    the approving actor for the same decision cycle - enforced in
    `TaskApprovalService`, not at the schema level) and every
    `approval_gate` task (directly, no verification prerequisite -
    `verification_id` is null).
    """

    __tablename__ = "task_approval_decisions"
    __table_args__ = (
        CheckConstraint("decision in ('approved', 'rejected')", name="ck_v2_task_approval_decisions_decision"),
        Index("ix_v2_task_approval_decisions_task", "task_id"),
        Index("ix_v2_task_approval_decisions_task_decided_at", "task_id", "decided_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    verification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_verifications.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 'role_normal' (the project's own PM), 'admin_fallback' (Admin/Super
    # Admin standing in with no active PM on the project), or
    # 'admin_override' (Admin/Super Admin acting despite an active PM
    # existing) - see TaskApprovalService.approve.
    decision_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="role_normal")


class TaskSupportAssignment(Base):
    """U6: a delegated Internal Employee's support assignment on a task
    (BR-005). Supervisor controls support for `work` tasks; PM controls
    follow-up support for `approval_gate` tasks - see
    `backend/app/services/task_support_assignment.py`.

    Never alters task accountability: `Task` accountability stays derived
    from the active project Supervisor/PM membership (BR-004), never from
    this table. The assignee must be an active `internal_employee` project
    member. Unique active assignment per task/employee is enforced both at
    the DB level (`uq_v2_task_support_assignments_active_task_employee`,
    migration) and the service layer.
    """

    __tablename__ = "task_support_assignments"
    __table_args__ = (
        CheckConstraint("status in ('active', 'ended')", name="ck_v2_task_support_assignments_status"),
        CheckConstraint(
            "(status = 'active' and ends_at is null) or (status = 'ended' and ends_at is not null)",
            name="ck_v2_task_support_assignments_status_ends_at_pair",
        ),
        Index("ix_v2_task_support_assignments_task", "task_id"),
        Index("ix_v2_task_support_assignments_project", "project_id"),
        Index("ix_v2_task_support_assignments_employee", "employee_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"), nullable=False)
    responsibility: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Telegram T2: when the employee pressed [Acknowledge] on "Task Assigned
    # to You". Receipt only - it never touches the task's lifecycle.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportAssignmentChange(Base):
    """U6: an audited change record for a `TaskSupportAssignment` (R7) -
    written whenever a support assignment is ended or replaced, mirroring
    `project_role_changes`'s audit shape but for the non-accountable
    support-employee layer (BR-005/BR-007)."""

    __tablename__ = "support_assignment_changes"
    __table_args__ = (
        Index("ix_v2_support_assignment_changes_assignment", "task_support_assignment_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_support_assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_support_assignments.id", ondelete="RESTRICT"), nullable=False)
    previous_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    replacement_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEvent(Base):
    """Phase 2 U4: durable, idempotent record of a business-meaningful
    mutation event (R6/BR-015), written in the SAME transaction as the
    domain mutation that caused it - see `backend/app/services/outbox.py`'s
    `OutboxService.emit` for the same-transaction invariant this table
    exists to guarantee: `emit()` only ever adds + flushes, NEVER commits,
    so it rides inside the caller's own open transaction and an
    outbox-insert failure rolls back the domain mutation with it.

    This unit (U4) only ever writes `status = 'pending'` rows here - it does
    not dispatch or send anything. A later unit is responsible for reading
    `pending` rows and moving them to `dispatched`/`failed`, which is why
    those two values are already in the check constraint below even though
    nothing in this unit writes them.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_v2_outbox_events_idempotency_key"),
        CheckConstraint("status in ('pending', 'dispatched', 'failed')", name="ck_v2_outbox_events_status"),
        Index("ix_v2_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_v2_outbox_events_status", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MessageDelivery(Base):
    """Phase 2 U5: per-recipient delivery record for a pending `OutboxEvent`
    (R7), read/written by `backend/app/services/message_dispatch.py`'s
    `MessageDispatchService.process_pending`.

    One `OutboxEvent` fans out to N recipients (e.g. a task event notifies
    both the project's PM and Supervisor, and sometimes an assigned
    vendor's primary contact too) - this table is that fan-out target, one
    row per (event, recipient, template).

    `recipient_phone` is a DENORMALIZED SNAPSHOT of the phone number at
    dispatch time, not a live join - the underlying `User.phone` /
    `V2VendorContact.phone` value could change after a message was sent,
    and this durably records what number a given message actually went to.

    Recipient identity uses two nullable real FK columns
    (`recipient_employee_id` / `recipient_vendor_contact_id`), never a
    polymorphic entity_type/entity_id pair - mirrors `TaskEvidence`'s real
    FK link convention elsewhere in this schema. Exactly one must be set
    (enforced by a DB CHECK constraint in the migration).

    Idempotency: the migration's unique index on
    (outbox_event_id, recipient_employee_id, recipient_vendor_contact_id,
    template) - using `NULLS NOT DISTINCT`, since exactly one recipient
    column is always null - means retrying dispatch for the same
    event+recipient+template never creates a second row. A retry after a
    prior 'failed' attempt updates the EXISTING row (increments
    `attempt_count`, updates `status`) instead of inserting a new one.
    """

    __tablename__ = "message_deliveries"
    __table_args__ = (
        CheckConstraint(
            "(recipient_employee_id is not null and recipient_vendor_contact_id is null) or "
            "(recipient_employee_id is null and recipient_vendor_contact_id is not null)",
            name="ck_v2_message_deliveries_recipient_exclusive",
        ),
        CheckConstraint(
            "status in ('queued', 'sending', 'sent', 'delivered', 'read', 'failed', 'suppressed')",
            name="ck_v2_message_deliveries_status",
        ),
        UniqueConstraint(
            "outbox_event_id", "recipient_employee_id", "recipient_vendor_contact_id", "template",
            name="uq_v2_message_deliveries_event_recipient_template",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_v2_message_deliveries_provider_message_id", "provider_message_id", unique=True,
            postgresql_where=text("provider_message_id is not null"),
            sqlite_where=text("provider_message_id is not null"),
        ),
        Index("ix_v2_message_deliveries_outbox_event", "outbox_event_id"),
        Index("ix_v2_message_deliveries_status", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.outbox_events.id", ondelete="RESTRICT"), nullable=False)
    recipient_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    recipient_vendor_contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendor_contacts.id", ondelete="RESTRICT"))
    recipient_phone: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    # U6 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
    # which channel this delivery actually went out on. Additive, defaults
    # to 'whatsapp' for every existing and new row - nothing writes anything
    # else here yet; `MessageDispatchService._dispatch_to_recipient` keeps
    # writing exactly as it does today until U9.
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="whatsapp")
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="sandbox")
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class InboundMessage(Base):
    """Phase 2 U6: inbound WhatsApp webhook delivery, matched to at most one
    known identity and translated into the SAME service call a portal
    action of that kind would make (R8/R9).

    Only a signature-verified webhook delivery ever reaches the point of
    writing a row here - see `backend/app/routes/whatsapp_webhook_v2.py`'s
    HMAC gate, which rejects an invalid/missing signature before any query
    or write against any table. So every row here, whatever its
    `processing_status`, represents an authentic provider delivery; a
    'unmatched'/'rejected' row never mutates any other domain state.

    `matched_identity_type`/`matched_identity_id` is a deliberately
    polymorphic pair - unlike `MessageDelivery`'s two-nullable-real-FK
    "exactly one set" convention - because a message resolves to at most
    one of two genuinely different identity tables (`employee_profiles` or
    `siteops_v2.vendor_contacts`) and, on 'unmatched'/'rejected' rows, BOTH
    stay null rather than exactly one being required. No FK constraint is
    placed on `matched_identity_id` since which table it references
    depends on `matched_identity_type`.
    """

    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_v2_inbound_messages_provider_message_id"),
        CheckConstraint(
            "matched_identity_type is null or matched_identity_type in ('employee', 'vendor_contact')",
            name="ck_v2_inbound_messages_identity_type",
        ),
        CheckConstraint(
            "processing_status in ('processed', 'unmatched', 'rejected')",
            name="ck_v2_inbound_messages_processing_status",
        ),
        Index("ix_v2_inbound_messages_sender_phone", "sender_phone"),
        Index("ix_v2_inbound_messages_processing_status", "processing_status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    sender_phone: Mapped[str] = mapped_column(Text, nullable=False)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
    matched_identity_type: Mapped[str | None] = mapped_column(Text)
    matched_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    processing_status: Mapped[str] = mapped_column(Text, nullable=False, default="unmatched")
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TelegramInboundUpdate(Base):
    """U2 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
    raw Telegram Bot API update storage, before any identity matching or
    command dispatch (U13/U14).

    Only a secret-token-verified webhook delivery ever reaches the point of
    writing a row here - see `backend/app/routes/telegram_webhook.py`'s
    verification gate, mirroring `InboundMessage`'s "only a verified
    delivery is ever stored" discipline for WhatsApp.

    `update_id` is Telegram's own per-update identifier. Telegram's Bot API
    redelivers on a slow or failed response - the same at-least-once
    behavior `InboundMessage.provider_message_id`'s uniqueness guards
    against for WhatsApp - so its uniqueness here lets U13/U14 detect and
    reject a duplicate delivery before executing any state-changing action
    (connect-token consumption, a gate command, etc.).
    """

    __tablename__ = "telegram_inbound_updates"
    __table_args__ = (
        UniqueConstraint("update_id", name="uq_v2_telegram_inbound_updates_update_id"),
        Index("ix_v2_telegram_inbound_updates_chat_id", "chat_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[str] = mapped_column(Text, nullable=False)
    message_text: Mapped[str | None] = mapped_column(Text)
    callback_data: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TelegramConnectToken(Base):
    """U3 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
    a one-time token issued to a specific employee or vendor contact, so
    they can link a Telegram chat to their existing identity by opening the
    bot's `/start <token>` link (U13). Purely schema at this point - no
    token-generation or token-consumption logic yet.

    `token` must be generated as a cryptographically random, sufficiently
    long value (e.g. Python's `secrets.token_urlsafe(32)`) by whichever
    later unit issues one - this is a security requirement on the data
    this table holds, not something the schema itself can enforce.

    Exclusive-recipient-pair `CheckConstraint` mirrors `MessageDelivery`'s
    own convention (`recipient_employee_id`/`recipient_vendor_contact_id`)
    rather than a polymorphic entity_type/entity_id pair.
    """

    __tablename__ = "telegram_connect_tokens"
    __table_args__ = (
        CheckConstraint(
            "(employee_id is not null and vendor_contact_id is null) or "
            "(employee_id is null and vendor_contact_id is not null)",
            name="ck_v2_telegram_connect_tokens_recipient_exclusive",
        ),
        UniqueConstraint("token", name="uq_v2_telegram_connect_tokens_token"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="CASCADE"))
    vendor_contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendor_contacts.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TelegramPendingInput(Base):
    """Gate plan chunk 3: a question the bot is waiting for a typed answer
    to - the Admin's rejection reason, or an optional note after a gate
    health button. At most one per chat (asking again replaces it); the next
    text message from that chat answers it before being treated as a
    command or evidence text. Deleted once answered, skipped or cancelled;
    `expires_at` bounds how long it can capture the next message. See
    `app.services.telegram_pending_input`."""

    __tablename__ = "telegram_pending_inputs"
    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_v2_telegram_pending_inputs_chat"),
        CheckConstraint(
            "kind in ('gate_reject_reason', 'gate_health_note', 'task_early_start_reason', "
            "'task_verify_reject_reason', 'task_approval_reject_reason', 'task_blocker_type', "
            "'task_blocker_description', 'task_add_progress', 'task_readiness_note', "
            "'task_delay_days', 'task_delay_reason')",
            name="ck_v2_telegram_pending_inputs_kind",
        ),
        # Telegram task plan U6 (KTD7): a gate question points at its gate, a
        # task question at its task - exactly one, matching the kind.
        CheckConstraint(
            "(kind in ('gate_reject_reason', 'gate_health_note') and approval_id is not null and task_id is null) or "
            "(kind not in ('gate_reject_reason', 'gate_health_note') and task_id is not null and approval_id is null)",
            name="ck_v2_telegram_pending_inputs_target",
        ),
        CheckConstraint(
            "(kind = 'gate_health_note' and health is not null) or "
            "(kind <> 'gate_health_note' and health is null)",
            name="ck_v2_telegram_pending_inputs_health",
        ),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approvals.id", ondelete="CASCADE"),
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="CASCADE"),
    )
    draft_text: Mapped[str | None] = mapped_column(Text)
    """An earlier answer carried into the next question of the same flow."""
    review_token: Mapped[str | None] = mapped_column(Text)
    """Which submission a review question belongs to (KTD19)."""
    health: Mapped[str | None] = mapped_column(Text)
    prompt_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GateEvidenceSession(Base):
    """Plan: WhatsApp Gate Workflow (U8, KTD4-KTD9).

    A buffering session for evidence an employee sends over WhatsApp for one
    `ProjectExternalApproval` gate - opened by `GATEOPEN <ref>` and closed by
    `GATECLOSE` (`project_gate_evidence_session.py`). Every inbound text/
    attachment while a session is open appends to it (`note`/
    `GateEvidenceSessionAttachment`) rather than submitting on its own -
    `close_session` is the only path that ever calls
    `ProjectGateSubmissionService.submit()`.

    Modeled on `EscalationTracking`'s "one open row, partial unique index on
    the open state" pattern (KTD4): `uq_v2_gate_evidence_sessions_employee_open`
    enforces at most one open session (`closed_at is null and expired_at is
    null`) per employee at the database level, not just in application
    logic. `GateEvidenceSessionService.open_session`'s own proactive check is
    the first line of defense; it treats the `IntegrityError` this index
    raises on a lost race as a benign rejection rather than a crash,
    mirroring `EscalationTracking._commit_new_tracking`'s exact precedent
    (`execution_models.py:737-770` above).

    A session ends exactly one of two ways, never both: `closed_at` set by a
    successful `GATECLOSE` (evidence submitted via `submit()`), or
    `expired_at` set by the silence-expiry sweep (KTD5/KTD6 - buffered
    evidence discarded, never submitted).
    """

    __tablename__ = "gate_evidence_sessions"
    __table_args__ = (
        Index("ix_v2_gate_evidence_sessions_approval", "approval_id"),
        Index(
            "uq_v2_gate_evidence_sessions_employee_open", "employee_id",
            unique=True,
            postgresql_where=text("closed_at is null and expired_at is null"),
            sqlite_where=text("closed_at is null and expired_at is null"),
        ),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_approvals.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    """Appended to (newline-joined) across every inbound text message
    belonging to this session - see `GateEvidenceSessionService.append_text`.
    Passed straight through as `submit()`'s own `note` on close."""
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    """Bumped on every message belonging to the session (text or
    attachment) - the silence-expiry sweep (KTD5) reads this, not
    `opened_at`, so a session that is actively (if slowly) accumulating
    evidence is never expired out from under the employee."""
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GateEvidenceSessionAttachment(Base):
    """Plan: WhatsApp Gate Workflow (U8). One attachment buffered against an
    open `GateEvidenceSession`, linking to a `FileObject` the caller (U10)
    has already downloaded and stored - a real, typed FK, mirroring
    `ProjectExternalApprovalEvidence`'s own non-polymorphic shape.

    CASCADE on `session_id`, matching `ProjectExternalApprovalEvidence`'s
    existing CASCADE-to-parent-submission convention: an attachment has no
    meaning apart from its session. RESTRICT on `file_id`, same as every
    other FileObject-linking table in this schema - the file's own bytes
    must outlive an accidental session-row delete.
    """

    __tablename__ = "gate_evidence_session_attachments"
    __table_args__ = (
        Index("ix_v2_gate_evidence_session_attachments_session", "session_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.gate_evidence_sessions.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.file_objects.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
