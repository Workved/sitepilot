"""Project and task targets. Mirrors supabase/migrations/202611260002_v2_project_targets.sql.
Rules live in app/services/targets.py."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.project_models import V2_SCHEMA


class ProjectTarget(Base):
    __tablename__ = "project_targets"
    __table_args__ = (
        CheckConstraint("kind in ('task', 'project')", name="ck_v2_project_targets_kind"),
        CheckConstraint("status in ('active', 'replaced', 'cleared')", name="ck_v2_project_targets_status"),
        CheckConstraint(
            "(kind = 'task' and task_id is not null) or (kind = 'project' and task_id is null and title is not null and trim(title) <> '')",
            name="ck_v2_project_targets_shape",
        ),
        Index("ix_v2_project_targets_project", "project_id"),
        Index("uq_v2_project_targets_active_task", "task_id", unique=True,
              postgresql_where=text("status = 'active' and task_id is not null"),
              sqlite_where=text("status = 'active' and task_id is not null")),
        {"schema": V2_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default="active")
    achieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    achieved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


class ProjectTargetTask(Base):
    __tablename__ = "project_target_tasks"
    __table_args__ = ({"schema": V2_SCHEMA},)

    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.project_targets.id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{V2_SCHEMA}.tasks.id", ondelete="CASCADE"), primary_key=True)
