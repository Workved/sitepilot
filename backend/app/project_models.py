import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


V2_SCHEMA = "siteops_v2"


class V2Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": V2_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    site_address: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_handover_date: Mapped[date | None] = mapped_column(Date)
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    # Anchors the evidence retention clock (app.services.evidence_retention)
    # to when the project was ACTUALLY marked complete, never to
    # target_handover_date - that field is a plan, not a fact, and a
    # delayed project must never have live evidence swept while it is
    # still active. Set once, on the draft/on_hold/active -> completed
    # transition (routes/projects_v2.py); there is no path back out of
    # 'completed' except 'archived', so it is never cleared once set.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by the retention sweep once it has purged this project's evidence
    # bytes, so a later sweep pass never rescans (and re-no-ops against) the
    # same project forever.
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class V2ProjectTask(Base):
    __tablename__ = "project_tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "template_task_id", name="uq_v2_project_tasks_project_template_task"),
        UniqueConstraint("project_id", "original_code", name="uq_v2_project_tasks_project_code"),
        CheckConstraint("template_sequence > 0", name="ck_v2_project_tasks_sequence_positive"),
        CheckConstraint("source_type in ('template', 'project_manual')", name="ck_v2_project_tasks_source_type"),
        CheckConstraint(
            "(source_type = 'template' and template_task_id is not null) or "
            "(source_type = 'project_manual' and template_task_id is null)",
            name="ck_v2_project_tasks_source_reference",
        ),
        CheckConstraint("lifecycle_status = 'draft'", name="ck_v2_project_tasks_draft_lifecycle"),
        CheckConstraint("applicability in ('mandatory', 'conditional')", name="ck_v2_project_tasks_applicability"),
        CheckConstraint("schedule_classification in ('pre_activation', 'execution')", name="ck_v2_project_tasks_schedule_classification"),
        CheckConstraint("decision_state in ('pending_review', 'included', 'excluded')", name="ck_v2_project_tasks_decision_state"),
        CheckConstraint(
            "(included = true and decision_state in ('pending_review', 'included')) or "
            "(included = false and decision_state = 'excluded')",
            name="ck_v2_project_tasks_review_state_consistency",
        ),
        Index("ix_v2_project_tasks_project_sequence", "project_id", "template_sequence"),
        Index("ix_v2_project_tasks_template_task", "template_task_id"),
        Index("ix_v2_project_tasks_project_review", "project_id", "included", "decision_state", "template_sequence"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{V2_SCHEMA}.v2_template_tasks.id", ondelete="RESTRICT"),
    )
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
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="template")
    reason: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision_state: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    added_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)



class V2ProjectExternalGate(Base):
    __tablename__ = "project_external_gates"
    __table_args__ = (
        UniqueConstraint("project_id", "template_gate_id", name="uq_v2_project_external_gates_project_template_gate"),
        UniqueConstraint("project_id", "original_code", name="uq_v2_project_external_gates_project_code"),
        CheckConstraint("template_sequence > 0", name="ck_v2_project_external_gates_sequence_positive"),
        CheckConstraint("mapping_classification in ('exact', 'broad_text', 'unmapped')", name="ck_v2_project_external_gates_mapping"),
        CheckConstraint("status = 'pending_review'", name="ck_v2_project_external_gates_status"),
        CheckConstraint("source_type in ('template', 'project_manual')", name="ck_v2_project_external_gates_source"),
        CheckConstraint("(source_type = 'template' and template_version_id is not null and template_gate_id is not null) or (source_type = 'project_manual' and template_version_id is null and template_gate_id is null)", name="ck_v2_project_external_gates_source_reference"),
        CheckConstraint("(mapping_classification = 'broad_text' and nullif(btrim(broad_mapping_text), '') is not null) or (mapping_classification <> 'broad_text' and broad_mapping_text is null)", name="ck_v2_project_external_gates_broad_text"),
        Index("ix_v2_project_external_gates_project_sequence", "project_id", "template_sequence"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="CASCADE"), nullable=False)
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"))
    template_gate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.v2_template_external_gates.id", ondelete="RESTRICT"))
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    template_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    external_party: Mapped[str | None] = mapped_column(Text)
    required_by_type: Mapped[str | None] = mapped_column(Text)
    required_by_value: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    mapping_classification: Mapped[str] = mapped_column(Text, nullable=False)
    broad_mapping_text: Mapped[str | None] = mapped_column(Text)
    requires_configuration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    applicability_state: Mapped[str] = mapped_column(Text, nullable=False, default="pending_review")
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="template")
    accountable_pm_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2ProjectExternalGateTask(Base):
    __tablename__ = "project_external_gate_tasks"
    __table_args__ = (
        UniqueConstraint("project_gate_id", "project_task_id", name="uq_v2_project_external_gate_tasks_pair"),
        Index("ix_v2_project_external_gate_tasks_gate", "project_gate_id"),
        Index("ix_v2_project_external_gate_tasks_task", "project_task_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_gate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_gates.id", ondelete="CASCADE"), nullable=False)
    project_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_tasks.id", ondelete="RESTRICT"), nullable=False)
    template_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.v2_template_tasks.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2ProjectExternalGateApplicabilityDecision(Base):
    __tablename__ = "project_external_gate_applicability_decisions"
    __table_args__ = (
        CheckConstraint("decision in ('applicable', 'not_applicable')", name="ck_v2_project_gate_applicability_decision"),
        Index("ix_v2_project_gate_applicability_history", "project_gate_id", "decided_at"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="CASCADE"), nullable=False)
    project_gate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_external_gates.id", ondelete="CASCADE"), nullable=False)
    previous_state: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = {"schema": V2_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"), nullable=False)
    project_role: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assignment_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set by the removed Telegram Acknowledge button; nothing writes it now.
    # Kept so acknowledgements recorded before the removal are not lost.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectRoleChange(Base):
    """U6: the two-step (request + approval) PM/Supervisor reassignment
    record (BR-007/R7), replacing today's immediate `assign_membership()`
    change for accountable roles. Placed here (not execution_models.py)
    because it is conceptually a `V2ProjectMembership` lifecycle event -
    it targets `project_memberships` directly and has no dependency on the
    execution-layer `tasks` table, unlike U6's other new models
    (`TaskSupportAssignment`/`SupportAssignmentChange`), which scope to a
    `Task` and so live in `execution_models.py` instead.

    A `pending` record never affects who is currently accountable -
    accountability resolution (BR-004) only ever reads active
    `V2ProjectMembership` rows. `approve_role_change`
    (`backend/app/services/project_role_change.py`) atomically ends the
    `previous_membership_id` row (if any) and creates the replacement,
    reusing the same "end prior active membership in the same transaction"
    shape `assign_membership()` already uses for immediate changes.
    """

    __tablename__ = "project_role_changes"
    __table_args__ = (
        CheckConstraint("role_type in ('project_manager', 'site_supervisor')", name="ck_v2_project_role_changes_role_type"),
        CheckConstraint("change_type in ('replacement', 'vacate')", name="project_role_changes_change_type_check"),
        CheckConstraint("status in ('pending', 'approved', 'rejected')", name="ck_v2_project_role_changes_status"),
        CheckConstraint(
            "(status = 'pending' and decided_by is null and decided_at is null) or "
            "(status in ('approved', 'rejected') and decided_by is not null and decided_at is not null)",
            name="ck_v2_project_role_changes_decision_pair",
        ),
        # 'replacement' always names who steps in; 'vacate' never does - see
        # 202609020001_v2_project_role_change_vacate.sql.
        CheckConstraint(
            "(change_type = 'replacement' and replacement_employee_id is not null) or "
            "(change_type = 'vacate' and replacement_employee_id is null)",
            name="ck_v2_project_role_changes_replacement_pair",
        ),
        Index("ix_v2_project_role_changes_project", "project_id"),
        Index("ix_v2_project_role_changes_project_status", "project_id", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False)
    role_type: Mapped[str] = mapped_column(Text, nullable=False)
    previous_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_memberships.id", ondelete="RESTRICT"))
    # Null for a 'vacate' change - see ck_v2_project_role_changes_replacement_pair above.
    replacement_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"))
    change_type: Mapped[str] = mapped_column(Text, nullable=False, default="replacement")
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = {"schema": V2_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="SET NULL"))
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="portal")
    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class V2ProjectTaskDependency(Base):
    __tablename__ = "project_task_dependencies"
    __table_args__ = (
        UniqueConstraint("project_id", "template_dependency_id", name="uq_v2_project_dependencies_project_template"),
        UniqueConstraint("project_id", "predecessor_project_task_id", "successor_project_task_id", "dependency_type", name="uq_v2_project_dependencies_edge"),
        CheckConstraint("predecessor_project_task_id <> successor_project_task_id", name="ck_v2_project_dependencies_not_self"),
        CheckConstraint("dependency_type in ('finish_to_start', 'start_to_start')", name="ck_v2_project_dependencies_type"),
        CheckConstraint("template_sequence > 0", name="ck_v2_project_dependencies_sequence_positive"),
        CheckConstraint("source_type in ('template','project_manual')", name="ck_v2_project_dependencies_source"),
        CheckConstraint("lifecycle_status = 'draft'", name="ck_v2_project_dependencies_lifecycle"),
        Index("ix_v2_project_dependencies_project_sequence", "project_id", "template_sequence"),
        Index("ix_v2_project_dependencies_predecessor", "predecessor_project_task_id"),
        Index("ix_v2_project_dependencies_successor", "successor_project_task_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="CASCADE"), nullable=False)
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.v2_template_versions.id", ondelete="RESTRICT"))
    template_dependency_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.v2_template_task_dependencies.id", ondelete="RESTRICT"))
    predecessor_project_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_tasks.id", ondelete="RESTRICT"), nullable=False)
    successor_project_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_tasks.id", ondelete="RESTRICT"), nullable=False)
    dependency_type: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_text: Mapped[str | None] = mapped_column(Text)
    template_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_task_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="template")
    reason: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
