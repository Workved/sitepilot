"""Task / project targets and the schedule-change history. Rules live in
app/services/targets.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.schemas.targets import TargetAchievedIn, TargetCreateIn, TargetUpdateIn
from app.services.targets import TargetService

router = APIRouter(prefix="/api/v2", tags=["v2-targets"])


@router.get("/projects/{project_id}/targets")
def list_targets(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return TargetService(db).list(project_id, actor)


@router.post("/projects/{project_id}/targets", status_code=201)
def create_target(project_id: uuid.UUID, payload: TargetCreateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return TargetService(db).create(project_id, actor, payload.model_dump())


@router.get("/projects/{project_id}/schedule-changes")
def schedule_changes(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return TargetService(db).schedule_changes(project_id, actor)


@router.patch("/targets/{target_id}")
def update_target(target_id: uuid.UUID, payload: TargetUpdateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return TargetService(db).update(target_id, actor, payload.model_dump(exclude_unset=True))


@router.post("/targets/{target_id}/clear")
def clear_target(target_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return TargetService(db).clear(target_id, actor)


@router.post("/targets/{target_id}/achieved")
def set_target_achieved(target_id: uuid.UUID, payload: TargetAchievedIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return TargetService(db).set_achieved(target_id, actor, payload.achieved)
