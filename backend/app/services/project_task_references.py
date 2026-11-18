"""Reference material added on a project, not its template.

Template reference files are read through the template the project is pinned
to and are never touched here. These are the extra files an Admin, or the
project's own PM or Supervisor, attaches:

* to a draft project task while the project is set up (`project_task_id`);
  activation then links each row to the live task made from it (`task_id`);
* to a live task, when the task is created or any time after (`task_id`).

Only project-added files can be removed; template files stay as published.
Files follow the same rules as template reference files (type, size, content
check - `validate_reference_file`) and live in the same private storage.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import FileObject, ProjectTaskReferenceFile, Task
from app.models import User
from app.project_models import V2AuditEvent, V2Project, V2ProjectTask
from app.services import evidence_storage
from app.services.project_task_addition import RUNNING_STATUSES, require_task_adder
from app.services.template_reference_files import MAX_DESCRIPTION_LENGTH, validate_reference_file


def _item(link: ProjectTaskReferenceFile, file_object: FileObject) -> dict:
    return {
        "id": link.id,
        "file_id": file_object.id,
        "filename": file_object.original_filename,
        "mime_type": file_object.mime_type,
        "size_bytes": file_object.size_bytes,
        "checksum": file_object.checksum,
        "description": link.description,
        "created_at": link.created_at,
        "source": "project",
    }


def project_files_by_task(db: Session, task_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    ids = list(task_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(ProjectTaskReferenceFile, FileObject)
        .join(FileObject, FileObject.id == ProjectTaskReferenceFile.file_id)
        .where(ProjectTaskReferenceFile.task_id.in_(ids))
        .order_by(ProjectTaskReferenceFile.created_at, ProjectTaskReferenceFile.id)
    ).all()
    grouped: dict[uuid.UUID, list[dict]] = {}
    for link, file_object in rows:
        grouped.setdefault(link.task_id, []).append(_item(link, file_object))
    return grouped


def project_files_by_project_task(db: Session, project_task_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    ids = list(project_task_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(ProjectTaskReferenceFile, FileObject)
        .join(FileObject, FileObject.id == ProjectTaskReferenceFile.file_id)
        .where(ProjectTaskReferenceFile.project_task_id.in_(ids))
        .order_by(ProjectTaskReferenceFile.created_at, ProjectTaskReferenceFile.id)
    ).all()
    grouped: dict[uuid.UUID, list[dict]] = {}
    for link, file_object in rows:
        grouped.setdefault(link.project_task_id, []).append(_item(link, file_object))
    return grouped


def link_draft_files_to_live_tasks(db: Session, task_by_project_task_id: dict[uuid.UUID, Task]) -> None:
    """Activation: files added to draft tasks follow them onto the live tasks."""
    if not task_by_project_task_id:
        return
    rows = db.scalars(select(ProjectTaskReferenceFile).where(
        ProjectTaskReferenceFile.project_task_id.in_(list(task_by_project_task_id)),
        ProjectTaskReferenceFile.task_id.is_(None),
    )).all()
    for row in rows:
        row.task_id = task_by_project_task_id[row.project_task_id].id


def project_reference_link(db: Session, task: Task, reference_id: uuid.UUID) -> FileObject | None:
    row = db.execute(
        select(ProjectTaskReferenceFile, FileObject)
        .join(FileObject, FileObject.id == ProjectTaskReferenceFile.file_id)
        .where(ProjectTaskReferenceFile.id == reference_id, ProjectTaskReferenceFile.task_id == task.id)
    ).first()
    return row[1] if row else None


class ProjectTaskReferenceService:
    def __init__(self, db: Session):
        self.db = db

    def _project(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        require_task_adder(self.db, project, actor)
        return project

    def _store(self, project: V2Project, actor: User, *, data: bytes, filename: str | None, content_type: str | None) -> FileObject:
        extension, mime_type, clean_name = validate_reference_file(data, filename, content_type)
        storage_key = f"project-references/{project.id}/{uuid.uuid4().hex}{extension}"
        evidence_storage.write(storage_key, data, mime_type)
        file_object = FileObject(
            storage_key=storage_key, original_filename=clean_name, mime_type=mime_type,
            size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest(), uploaded_by=actor.id,
        )
        self.db.add(file_object)
        self.db.flush()
        return file_object

    @staticmethod
    def _description(description: str | None) -> str | None:
        clean = (description or "").strip() or None
        if clean and len(clean) > MAX_DESCRIPTION_LENGTH:
            raise HTTPException(422, f"The description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.")
        return clean

    def _audit(self, actor: User, project: V2Project, action: str, link_id: uuid.UUID, after=None, before=None) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id, action=action, entity_type="project_task_reference_file", entity_id=link_id,
            project_id=project.id, source="portal", before_json=before, after_json=after,
            reason="Reference material added on the project." if action.endswith("ADDED") else "Reference material removed.",
        ))

    def add_to_task(self, project_id: uuid.UUID, task_id: uuid.UUID, actor: User, *, data: bytes, filename: str | None,
                    content_type: str | None, description: str | None) -> dict:
        project = self._project(project_id, actor)
        if project.status not in RUNNING_STATUSES:
            raise HTTPException(409, "Reference files can be added to tasks of an active or on-hold project.")
        task = self.db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id))
        if task is None:
            raise HTTPException(404, "Task not found.")
        clean = self._description(description)
        file_object = self._store(project, actor, data=data, filename=filename, content_type=content_type)
        link = ProjectTaskReferenceFile(project_id=project.id, task_id=task.id, file_id=file_object.id, description=clean, created_by=actor.id)
        self.db.add(link)
        self.db.flush()
        self._audit(actor, project, "TASK_REFERENCE_FILE_ADDED", link.id, after={
            "task_id": str(task.id), "filename": file_object.original_filename, "size_bytes": file_object.size_bytes,
        })
        self.db.commit()
        return _item(link, file_object)

    def add_to_project_task(self, project_id: uuid.UUID, project_task_id: uuid.UUID, actor: User, *, data: bytes,
                            filename: str | None, content_type: str | None, description: str | None) -> dict:
        project = self._project(project_id, actor)
        if project.status != "draft":
            raise HTTPException(409, "This project has started - add the file to the live task instead.")
        project_task = self.db.scalar(select(V2ProjectTask).where(V2ProjectTask.id == project_task_id, V2ProjectTask.project_id == project.id))
        if project_task is None:
            raise HTTPException(404, "Task not found.")
        clean = self._description(description)
        file_object = self._store(project, actor, data=data, filename=filename, content_type=content_type)
        link = ProjectTaskReferenceFile(project_id=project.id, project_task_id=project_task.id, file_id=file_object.id, description=clean, created_by=actor.id)
        self.db.add(link)
        self.db.flush()
        self._audit(actor, project, "TASK_REFERENCE_FILE_ADDED", link.id, after={
            "project_task_id": str(project_task.id), "filename": file_object.original_filename, "size_bytes": file_object.size_bytes,
        })
        self.db.commit()
        return _item(link, file_object)

    def remove(self, project_id: uuid.UUID, reference_id: uuid.UUID, actor: User) -> dict:
        project = self._project(project_id, actor)
        link = self.db.scalar(select(ProjectTaskReferenceFile).where(
            ProjectTaskReferenceFile.id == reference_id, ProjectTaskReferenceFile.project_id == project.id,
        ))
        if link is None:
            # A template file has no row here: it can't be removed on a project.
            raise HTTPException(404, "Reference file not found on this project (template files can't be removed here).")
        if project.status in {"completed", "archived"}:
            raise HTTPException(409, "Reference files of a completed or archived project can't be changed.")
        before = {"task_id": str(link.task_id) if link.task_id else None,
                  "project_task_id": str(link.project_task_id) if link.project_task_id else None, "file_id": str(link.file_id)}
        # The link only; the stored file stays (it may be referenced by audit).
        self.db.delete(link)
        self._audit(actor, project, "TASK_REFERENCE_FILE_REMOVED", reference_id, before=before)
        self.db.commit()
        return {"reference_id": str(reference_id), "deleted": True}
