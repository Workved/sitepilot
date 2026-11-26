"""Project snag list endpoints. Rules live in app/services/snags.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.schemas.snags import SnagCreateIn, SnagStatusIn, SnagUpdateIn
from app.services.snags import SnagService
from app.services.template_reference_files import reference_file_response

router = APIRouter(prefix="/api/v2", tags=["v2-snags"])
MAX_READ = 10 * 1024 * 1024 + 1  # one byte past the cap, so oversize is refused


@router.get("/projects/{project_id}/snags")
def list_project_snags(project_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return SnagService(db).list_for_project(project_id, actor)


@router.post("/projects/{project_id}/snags", status_code=201)
def create_snag(project_id: uuid.UUID, payload: SnagCreateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return SnagService(db).create(project_id, actor, payload.model_dump())


@router.get("/snags/tagged-to-me")
def snags_tagged_to_me(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return SnagService(db).tagged_to(actor)


@router.get("/snags/people")
def snag_people(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everyone a snag can be tagged to: active SiteOps users, name and role only."""
    return SnagService(db).people()


@router.patch("/snags/{snag_id}")
def update_snag(snag_id: uuid.UUID, payload: SnagUpdateIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    # Only the fields actually sent change; an explicit null clears one.
    return SnagService(db).update(snag_id, actor, payload.model_dump(exclude_unset=True))


@router.post("/snags/{snag_id}/status")
def set_snag_status(snag_id: uuid.UUID, payload: SnagStatusIn, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return SnagService(db).set_status(snag_id, actor, payload.status, payload.closing_note)


@router.delete("/snags/{snag_id}")
def delete_snag(snag_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return SnagService(db).delete(snag_id, actor)


@router.post("/snags/{snag_id}/files", status_code=201)
async def add_snag_file(snag_id: uuid.UUID, file: UploadFile = File(...), actor: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read(MAX_READ)
    return SnagService(db).add_file(snag_id, actor, data=data, filename=file.filename, content_type=file.content_type)


@router.get("/snags/{snag_id}/files/{file_id}")
def download_snag_file(snag_id: uuid.UUID, file_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    file_object, content = SnagService(db).read_file(snag_id, file_id, actor)
    return reference_file_response(file_object, content)


@router.delete("/snags/{snag_id}/files/{file_id}")
def remove_snag_file(snag_id: uuid.UUID, file_id: uuid.UUID, actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return SnagService(db).remove_file(snag_id, file_id, actor)
