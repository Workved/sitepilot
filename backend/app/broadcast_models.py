"""Communication module: admin project-wide meeting announcements/broadcasts.

A `Broadcast` targets exactly one project and a snapshot of that project's
current team + vendors (`BroadcastRecipient`, resolved and persisted at
create time - see `app.services.broadcast_service`). The snapshot is
deliberate: who a historical broadcast was sent to should not silently
change if the project's membership changes later, which is also why this
is a separate table rather than a live join re-computed on every read.

`BroadcastTemplate` only stores reusable message content (title/agenda/body)
- never recipients, since a template is meant to be reused across different
projects with different teams.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA

RECIPIENT_GROUPS = ("project_manager", "site_supervisor", "internal_employee", "vendor", "vendor_contact")
SEND_MODES = ("now", "scheduled")
BROADCAST_STATUSES = ("scheduled", "sent", "partially_failed", "failed")
DELIVERY_STATUSES = ("pending", "sent", "skipped_no_contact", "failed")


class Broadcast(Base):
    __tablename__ = "broadcasts"
    __table_args__ = (
        CheckConstraint("send_mode in ('now', 'scheduled')", name="ck_v2_broadcasts_send_mode"),
        CheckConstraint("status in ('scheduled', 'sent', 'partially_failed', 'failed')", name="ck_v2_broadcasts_status"),
        CheckConstraint(
            "(send_mode = 'scheduled' and scheduled_at is not null) or (send_mode = 'now' and scheduled_at is null)",
            name="ck_v2_broadcasts_scheduled_at_pair",
        ),
        Index("ix_v2_broadcasts_project", "project_id"),
        Index("ix_v2_broadcasts_status", "status"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_date: Mapped[date | None] = mapped_column(Date)
    meeting_time: Mapped[str | None] = mapped_column(Text)
    location_or_link: Mapped[str | None] = mapped_column(Text)
    agenda: Mapped[str | None] = mapped_column(Text)
    message_body: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    send_mode: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"
    __table_args__ = (
        CheckConstraint(
            "recipient_type in ('project_manager', 'site_supervisor', 'internal_employee', 'vendor', 'vendor_contact')",
            name="ck_v2_broadcast_recipients_type",
        ),
        CheckConstraint(
            "delivery_status in ('pending', 'sent', 'skipped_no_contact', 'failed')",
            name="ck_v2_broadcast_recipients_delivery_status",
        ),
        Index("ix_v2_broadcast_recipients_broadcast", "broadcast_id"),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.broadcasts.id", ondelete="CASCADE"), nullable=False)
    recipient_type: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendors.id", ondelete="SET NULL"))
    vendor_contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.vendor_contacts.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role_label: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"
    __table_args__ = ({"schema": V2_SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    agenda: Mapped[str | None] = mapped_column(Text)
    message_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
