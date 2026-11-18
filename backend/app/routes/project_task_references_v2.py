"""Reference material added on a project: upload to a draft project task or a
live task, and remove what was added. Downloads of live-task files go through
the existing GET .../tasks/{task_id}/reference-files/{reference_id}. See
app/services/project_task_references.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.services.project_task_references import ProjectTaskReferenceService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-project-task-references"])

MAX_READ = 10 * 1024 * 1024 + 1  # one byte past the cap, so oversize is refused


@router.post("/{project_id}/tasks/{task_id}/reference-files", status_code=201)
async def add_task_reference_file(
    project_id: uuid.UUID, task_id: uuid.UUID,
    description: str | None = Form(default=None), file: UploadFile = File(...),
    actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    data = await file.read(MAX_READ)
    return ProjectTaskReferenceService(db).add_to_task(
        project_id, task_id, actor, data=data, filename=file.filename, content_type=file.content_type, description=description,
    )


@router.post("/{project_id}/project-tasks/{project_task_id}/reference-files", status_code=201)
async def add_project_task_reference_file(
    project_id: uuid.UUID, project_task_id: uuid.UUID,
    description: str | None = Form(default=None), file: UploadFile = File(...),
    actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    data = await file.read(MAX_READ)
    return ProjectTaskReferenceService(db).add_to_project_task(
        project_id, project_task_id, actor, data=data, filename=file.filename, content_type=file.content_type, description=description,
    )


@router.delete("/{project_id}/task-reference-files/{reference_id}")
def remove_task_reference_file(
    project_id: uuid.UUID, reference_id: uuid.UUID,
    actor: User = Depends(current_user), db: Session = Depends(get_db),
):
    return ProjectTaskReferenceService(db).remove(project_id, reference_id, actor)
