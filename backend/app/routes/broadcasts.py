"""Communication module: admin project-wide meeting announcements (R-COMM1).

Admin-only end to end (BR-003's existing role-bypass pattern, same as
admin_visibility_v2.py's Portfolio rollup) - the plan calls for this to stay
Admin-only "for now", so no new permission concept is introduced.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.broadcast_models import Broadcast, BroadcastRecipient, BroadcastTemplate
from app.database import get_db
from app.models import User, UserRole
from app.project_models import V2Project
from app.routes.projects_v2 import get_project
from app.services.broadcast_service import (
    ALL_GROUPS,
    broadcast_detail_json,
    broadcast_summary_json,
    create_broadcast,
    group_counts,
    resolve_recipients,
    send_scheduled_broadcast,
    template_json,
)

router = APIRouter(prefix="/api/v2/broadcasts", tags=["v2-broadcasts"])
ADMIN_ROLES = (UserRole.super_admin, UserRole.admin)


class BroadcastCreateIn(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1)
    meeting_date: date | None = None
    meeting_time: str | None = None
    location_or_link: str | None = None
    agenda: str | None = None
    message_body: str = Field(min_length=1)
    recipient_groups: list[str] = Field(default_factory=list)
    excluded_recipient_keys: list[str] = Field(default_factory=list)
    send_mode: str = Field(pattern="^(now|scheduled)$")
    scheduled_at: datetime | None = None


class TemplateCreateIn(BaseModel):
    name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    agenda: str | None = None
    message_body: str = Field(min_length=1)


class SummaryOut(BaseModel):
    messages_sent: int
    total_recipients: int
    delivery_success_rate: int
    scheduled: int
    failed: int


def _get_broadcast(db: Session, broadcast_id: uuid.UUID) -> Broadcast:
    broadcast = db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Broadcast not found.")
    return broadcast


@router.get("/recipients")
def preview_recipients(
    project_id: uuid.UUID, groups: str = Query("", description="Comma-separated recipient groups"),
    actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db),
):
    project = get_project(db, project_id, actor)
    selected = [item for item in groups.split(",") if item] or list(ALL_GROUPS)
    return {
        "project_id": str(project.id), "counts": group_counts(db, project.id),
        "recipients": resolve_recipients(db, project.id, selected),
    }


@router.get("/templates")
def list_templates(actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    templates = db.scalars(select(BroadcastTemplate).order_by(BroadcastTemplate.created_at.desc())).all()
    return [template_json(item) for item in templates]


@router.post("/templates")
def create_template(payload: TemplateCreateIn, actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    template = BroadcastTemplate(
        name=payload.name.strip(), title=payload.title.strip(),
        agenda=payload.agenda or None, message_body=payload.message_body.strip(), created_by=actor.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template_json(template)


@router.delete("/templates/{template_id}")
def delete_template(template_id: uuid.UUID, actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    template = db.get(BroadcastTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found.")
    db.delete(template)
    db.commit()
    return {"ok": True}


@router.get("/summary", response_model=SummaryOut)
def summary(actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    broadcasts = db.scalars(select(Broadcast)).all()
    sent = [item for item in broadcasts if item.status in ("sent", "partially_failed")]
    scheduled = [item for item in broadcasts if item.status == "scheduled"]
    failed = [item for item in broadcasts if item.status == "failed"]

    recipient_rows = db.execute(select(BroadcastRecipient.delivery_status)).scalars().all()
    total_recipients = len(recipient_rows)
    delivered = sum(1 for status in recipient_rows if status == "sent")
    resolved = sum(1 for status in recipient_rows if status in ("sent", "skipped_no_contact", "failed"))
    success_rate = round(delivered / resolved * 100) if resolved else 0

    return SummaryOut(
        messages_sent=len(sent), total_recipients=total_recipients,
        delivery_success_rate=success_rate, scheduled=len(scheduled), failed=len(failed),
    )


@router.get("")
def list_broadcasts(
    status: str | None = None, project_id: uuid.UUID | None = None, search: str | None = None,
    limit: int = 200, offset: int = 0,
    actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db),
):
    statement = select(Broadcast).join(V2Project, V2Project.id == Broadcast.project_id).order_by(Broadcast.created_at.desc())
    if status:
        statement = statement.where(Broadcast.status == status)
    if project_id:
        statement = statement.where(Broadcast.project_id == project_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(or_(Broadcast.title.ilike(term), V2Project.name.ilike(term)))
    statement = statement.limit(max(1, min(limit, 500))).offset(max(offset, 0))
    return [broadcast_summary_json(db, item) for item in db.scalars(statement).all()]


@router.get("/{broadcast_id}")
def get_broadcast(broadcast_id: uuid.UUID, actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return broadcast_detail_json(db, _get_broadcast(db, broadcast_id))


@router.post("")
def post_broadcast(payload: BroadcastCreateIn, actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    project = get_project(db, payload.project_id, actor)
    broadcast = create_broadcast(
        db, actor, project, title=payload.title, meeting_date=payload.meeting_date, meeting_time=payload.meeting_time,
        location_or_link=payload.location_or_link, agenda=payload.agenda, message_body=payload.message_body,
        groups=payload.recipient_groups, excluded_keys=payload.excluded_recipient_keys,
        send_mode=payload.send_mode, scheduled_at=payload.scheduled_at,
    )
    return broadcast_detail_json(db, broadcast)


@router.post("/{broadcast_id}/send")
def post_send(broadcast_id: uuid.UUID, actor: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    broadcast = send_scheduled_broadcast(db, actor, _get_broadcast(db, broadcast_id))
    return broadcast_detail_json(db, broadcast)
