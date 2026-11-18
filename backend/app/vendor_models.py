"""Phase 2 U1: V2 vendor/capability models (R1).

Mirrors `supabase/migrations/202608040001_v2_vendors.sql`. See that
migration's header for the modeling rationale (legacy_vendor_id back-ref
for idempotent import, category normalization, parent_vendor_id as the
sole authoritative sub-vendor relationship).

Naming: these are prefixed `V2Vendor*` (not bare `Vendor*`) because
`app.models.Vendor` / `app.models.VendorContact` already exist for the
legacy schema - an unprefixed class name here would collide at the Python
level even though the DB tables themselves don't collide (`siteops_v2.*`
vs. legacy `public.*`). This mirrors the existing `V2Project` / `V2Task`
naming convention used throughout `app.project_models` /
`app.execution_models`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA


class V2Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("legacy_vendor_id", name="uq_v2_vendors_legacy_vendor_id"),
        CheckConstraint("engagement_type in ('main', 'sub_vendor')", name="ck_v2_vendors_engagement_type"),
        CheckConstraint("engagement_type != 'sub_vendor' OR parent_vendor_id IS NOT NULL", name="ck_v2_vendors_sub_vendor_parent"),
        CheckConstraint("engagement_type != 'main' OR parent_vendor_id IS NULL", name="ck_v2_vendors_main_without_parent"),
        CheckConstraint("status in ('active', 'blacklisted')", name="ck_v2_vendors_status"),
        Index("ix_v2_vendors_parent", "parent_vendor_id"),
        Index("ix_v2_vendors_status", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Historical reference to the dropped legacy `public.vendors.id` a row
    # was originally imported from. Retained as provenance for the rows that
    # predate the consolidation; always null for vendors created since.
    legacy_vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_person: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    gst_number: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # 'active' only means "not blacklisted" and is never shown; the one status
    # a person sets is 'blacklisted' (VendorBlacklistService), with a reason.
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    blacklist_reason: Mapped[str | None] = mapped_column(Text)
    blacklisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blacklisted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    engagement_type: Mapped[str] = mapped_column(Text, nullable=False, default="main")
    parent_vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="RESTRICT")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class V2CapabilityCategory(Base):
    __tablename__ = "capability_categories"
    __table_args__ = (
        UniqueConstraint("name", name="uq_v2_capability_categories_name"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Hidden from pickers; vendors that already have it keep it.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2VendorCapability(Base):
    __tablename__ = "vendor_capabilities"
    __table_args__ = (
        UniqueConstraint("vendor_id", "category_id", name="uq_v2_vendor_capabilities_vendor_category"),
        Index("ix_v2_vendor_capabilities_vendor", "vendor_id"),
        Index("ix_v2_vendor_capabilities_category", "category_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.capability_categories.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class V2VendorContact(Base):
    __tablename__ = "vendor_contacts"
    __table_args__ = (
        Index("ix_v2_vendor_contacts_vendor", "vendor_id"),
        CheckConstraint("active_channel in ('whatsapp', 'telegram')", name="ck_v2_vendor_contacts_active_channel"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    designation: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(Text)
    # U4 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
    # set once this contact opens the bot's Start link with a valid
    # connect-token (U13). Nullable and unused by any code path until then.
    telegram_chat_id: Mapped[str | None] = mapped_column(Text, unique=True)
    # U5 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
    # KTD1): which channel this contact is actually reachable on right now.
    # Defaults to 'whatsapp' for every existing and new row so behavior is
    # unchanged until an Admin/Super-Admin explicitly toggles someone (U15).
    active_channel: Mapped[str] = mapped_column(Text, nullable=False, default="whatsapp")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectVendor(Base):
    """Phase 2 U2: a vendor mapped to a project (R2).

    Only a `V2Vendor` with `status == 'active'` may be mapped
    (`ProjectVendorService.map_vendor`). A `sub_vendor` additionally
    requires its `parent_vendor_id` to already have its own active mapping
    to the *same* project - that rule spans two rows (this vendor's mapping
    candidacy and its parent's existing mapping), so it is enforced in the
    service layer rather than as a single-row CHECK constraint.

    Soft removal (`ProjectVendorService.remove_vendor`): `ends_at` marks
    when a mapping stopped being active. The row is never deleted, so
    history (acknowledgements, evidence, audit trail) stays intact -
    `ends_at is null` is what "actively mapped" means everywhere this is
    read (including the sub-vendor parent check above). A vendor can be
    re-mapped to the same project after removal - only one *active* mapping
    per project/vendor is enforced (`uq_v2_project_vendors_active_project_vendor`),
    not one ever.
    """

    __tablename__ = "project_vendors"
    __table_args__ = (
        Index("ix_v2_project_vendors_project", "project_id"),
        Index("ix_v2_project_vendors_vendor", "vendor_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="RESTRICT"), nullable=False
    )
    mapped_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Telegram T2: when the vendor pressed [Acknowledge / स्वीकार करें] on the
    # project assignment. Receipt only.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskVendorAssignment(Base):
    """Phase 2 U2: a vendor delegated to an execution-layer task (R3).

    A pure delegation record - it never transfers or alters Site Supervisor
    accountability (Phase 1 U6's accountability resolution stays entirely
    independent of this table's existence) and never itself satisfies or
    affects a `TaskDependency` blocking check. `TaskVendorAssignmentService`
    requires the vendor to already be `ProjectVendor`-mapped to the task's
    project, to be `status == 'active'`, and (when the task has a
    `category`) to hold a matching `V2VendorCapability` by category name.

    `status` starts at `pending_ack` on every insert here; `acknowledged`
    and `declined` are reserved for a later unit's vendor-acknowledgement
    flow - this unit does not transition this column after creation.

    Soft removal (`TaskVendorAssignmentService.unassign_vendor`): `ends_at`
    marks when the delegation stopped being active, independent of
    `status` - an assignment can be ended regardless of its acknowledgement
    outcome. The row and every `VendorAcknowledgement` against it stay in
    place; `ends_at is null` is what "currently delegated" means everywhere
    this is read.
    """

    __tablename__ = "task_vendor_assignments"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending_ack', 'acknowledged', 'declined')",
            name="ck_v2_task_vendor_assignments_status",
        ),
        Index("ix_v2_task_vendor_assignments_task", "task_id"),
        Index("ix_v2_task_vendor_assignments_project", "project_id"),
        Index("ix_v2_task_vendor_assignments_vendor", "vendor_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Note: no direct FK class import from app.execution_models needed here -
    # this references the `siteops_v2.tasks` table by schema-qualified name
    # only, keeping this module's import surface limited to app.vendor_models
    # + app.project_models (see the "no accountability import" R3 proof).
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending_ack")
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Point person: the vendor contact handling this task. Must belong to
    # `vendor_id` (TaskVendorAssignmentService). Task messages go to this
    # person and the vendor's primary contact; null = primary contact only.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendor_contacts.id", ondelete="SET NULL")
    )


class VendorAcknowledgement(Base):
    """Phase 2 U3: a recorded vendor response to a `TaskVendorAssignment`
    (R4).

    Append-only: every response - 'accepted', 'declined', or
    'clarification_requested' - is kept as its own row, even across
    multiple attempts on the same assignment (a clarification request may
    be followed by a later acceptance; neither row is overwritten or
    deleted). Only `VendorAcknowledgementService.record_acknowledgement`
    transitions the parent `TaskVendorAssignment.status`, and only for the
    two terminal responses ('accepted' -> 'acknowledged', 'declined' ->
    'declined'); 'clarification_requested' never changes it.

    `channel` defaults to 'portal' because this unit's route is PM-
    submitted only (R4 - there is no vendor-identity auth here, the PM
    records on the vendor's behalf), but the column is not restricted to
    that value so a later unit's WhatsApp inbound-matching flow can append
    rows with channel = 'whatsapp' without a schema change.
    """

    __tablename__ = "vendor_acknowledgements"
    __table_args__ = (
        CheckConstraint(
            "response in ('accepted', 'declined', 'clarification_requested')",
            name="ck_v2_vendor_acknowledgements_response",
        ),
        CheckConstraint(
            "channel in ('portal', 'whatsapp', 'telegram', 'system')", name="ck_v2_vendor_acknowledgements_channel",
        ),
        Index("ix_v2_vendor_acknowledgements_assignment", "task_vendor_assignment_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_vendor_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.task_vendor_assignments.id", ondelete="RESTRICT"), nullable=False
    )
    response: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="portal")
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Vendor activity/incident logging (VendorActivityEvent, VendorActivityEvidence)
# and vendor notes (V2VendorNote) were removed - Phase 2 scope, not this
# release. See `supabase/migrations/202608040003_v2_vendor_acknowledgements_activity.sql`
# and `202608080001_v2_vendor_notes.sql` for the tables themselves, left in
# place (unused) rather than dropped.


class V2VendorPastProject(Base):
    """A past project entered by hand on a vendor's Work history.

    Mirrors `supabase/migrations/202611150001_v2_vendor_past_projects.sql`.
    Projects the vendor worked on inside SiteOps are not stored here - they
    are the ended `ProjectVendor` rows, read live. Months are the first day
    of the month."""

    __tablename__ = "vendor_past_projects"
    __table_args__ = (
        CheckConstraint("start_month is null or end_month is null or end_month >= start_month", name="ck_v2_vendor_past_projects_months"),
        CheckConstraint("approx_value is null or approx_value >= 0", name="ck_v2_vendor_past_projects_value"),
        Index("ix_v2_vendor_past_projects_vendor", "vendor_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="CASCADE"), nullable=False
    )
    project_name: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.capability_categories.id", ondelete="SET NULL")
    )
    work_description: Mapped[str | None] = mapped_column(Text)
    start_month: Mapped[date | None] = mapped_column(Date)
    end_month: Mapped[date | None] = mapped_column(Date)
    approx_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class VendorContactProject(Base):
    """A vendor contact (a person) attached to a project, optionally for one
    trade category - one row per category, `category_id` null meaning all of
    the vendor's work there.

    Mirrors `supabase/migrations/202611160001_v2_vendor_contact_assignments.sql`.
    Soft removal via `ends_at`, like `ProjectVendor`; one active row per
    contact/project/category (partial unique index in SQL, also checked in
    `VendorContactProjectService`)."""

    __tablename__ = "vendor_contact_projects"
    __table_args__ = (
        Index("ix_v2_vendor_contact_projects_contact", "contact_id"),
        Index("ix_v2_vendor_contact_projects_project", "project_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendor_contacts.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.capability_categories.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
