"""Project snag list: the small leftover jobs on a project, kept as a quick
checklist separate from the schedule.

Who may do what (one place, so every endpoint agrees):

* See a project's snags, and add one: Admin/Super Admin, or anyone with an
  active membership on the project (any project role).
* See a single snag: the above, plus the person it is tagged to - who may be
  outside the project and then sees only their own snags.
* Close / reopen: the tagged person, whoever added it, the project's PM or
  Supervisor, and admins.
* Edit details (title, area, notes, due date, urgency, tag): whoever added
  it, the project's PM or Supervisor, and admins.
* Attach a file: anyone who can see the snag. Remove a file: whoever
  uploaded it, plus everyone who may edit the snag.
* Delete: whoever added it, the project's PM, and admins.
* Archived projects are read-only.

A snag can be tagged to any active SiteOps user. When the tag changes to
someone other than the actor, and `settings.snag_whatsapp_enabled` is on, a
`snag.assigned` outbox event WhatsApps them; it is off until the template is
approved in Meta, and the snag shows on their "Tagged to you" list either way.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import FileObject
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services import evidence_storage
from app.services.outbox import OutboxService
from app.services.template_reference_files import read_reference_bytes, validate_reference_file
from app.snag_models import ProjectSnag, ProjectSnagFile

ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}
READ_ONLY_STATUSES = {"archived"}
ROLE_LABELS = {
    "super_admin": "Super Admin", "admin": "Admin", "project_manager": "Project Manager",
    "supervisor": "Supervisor", "internal_employee": "Internal Employee",
}


def _now():
    return datetime.now(timezone.utc)


class SnagService:
    def __init__(self, db: Session):
        self.db = db
        self._roles_cache: dict[tuple, set[str]] = {}

    # ---- access ------------------------------------------------------------

    def project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        key = (project_id, actor.id)
        if key not in self._roles_cache:
            rows = self.db.scalars(
                select(V2ProjectMembership.project_role)
                .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
                .where(EmployeeProfile.user_id == actor.id, V2ProjectMembership.project_id == project_id, V2ProjectMembership.ends_at.is_(None))
            ).all()
            self._roles_cache[key] = set(rows)
        return self._roles_cache[key]

    def _is_admin(self, actor: User) -> bool:
        return actor.role in ADMIN_ROLES

    def can_view_project(self, project: V2Project, actor: User) -> bool:
        return self._is_admin(actor) or bool(self.project_roles(project.id, actor))

    def permissions(self, snag: ProjectSnag, project: V2Project, actor: User) -> dict:
        admin = self._is_admin(actor)
        roles = self.project_roles(project.id, actor)
        lead = admin or bool(roles & {"project_manager", "site_supervisor"})
        creator = snag.created_by == actor.id
        tagged = snag.assignee_user_id == actor.id
        writable = project.status not in READ_ONLY_STATUSES
        can_see = admin or bool(roles) or tagged
        return {
            "can_edit": writable and (creator or lead),
            "can_close": writable and (creator or lead or tagged),
            "can_attach": writable and can_see,
            "can_delete": writable and (creator or admin or "project_manager" in roles),
            # A tagged outsider sees the snag but not the project page.
            "can_open_project": admin or bool(roles),
        }

    def _project(self, project_id: uuid.UUID) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        return project

    def _snag(self, snag_id: uuid.UUID, actor: User) -> tuple[ProjectSnag, V2Project]:
        snag = self.db.get(ProjectSnag, snag_id)
        if not snag:
            raise HTTPException(404, "Snag not found.")
        project = self._project(snag.project_id)
        if not (self.can_view_project(project, actor) or snag.assignee_user_id == actor.id):
            raise HTTPException(403, "You can't see this snag.")
        return snag, project

    def _require_writable(self, project: V2Project) -> None:
        if project.status in READ_ONLY_STATUSES:
            raise HTTPException(409, "This project is archived; its snag list is read-only.")

    def _assignee(self, user_id: uuid.UUID | None) -> User | None:
        if user_id is None:
            return None
        user = self.db.get(User, user_id)
        if not user or not user.active:
            raise HTTPException(422, "Tag someone with an active SiteOps account.")
        return user

    # ---- serialisation -----------------------------------------------------

    def _files(self, snag_ids) -> dict[uuid.UUID, list[dict]]:
        ids = list(snag_ids)
        if not ids:
            return {}
        rows = self.db.execute(
            select(ProjectSnagFile, FileObject).join(FileObject, FileObject.id == ProjectSnagFile.file_id)
            .where(ProjectSnagFile.snag_id.in_(ids)).order_by(ProjectSnagFile.created_at)
        ).all()
        grouped: dict[uuid.UUID, list[dict]] = {}
        for link, file_object in rows:
            grouped.setdefault(link.snag_id, []).append({
                "id": str(link.id), "filename": file_object.original_filename, "mime_type": file_object.mime_type,
                "size_bytes": file_object.size_bytes, "uploaded_by": str(link.uploaded_by) if link.uploaded_by else None,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            })
        return grouped

    def serialize_many(self, snags: list[ProjectSnag], actor: User, projects: dict[uuid.UUID, V2Project] | None = None) -> list[dict]:
        projects = dict(projects or {})
        for snag in snags:
            if snag.project_id not in projects:
                projects[snag.project_id] = self.db.get(V2Project, snag.project_id)
        user_ids = {uid for snag in snags for uid in (snag.assignee_user_id, snag.created_by, snag.closed_by) if uid}
        users = {user.id: user for user in self.db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
        files = self._files(snag.id for snag in snags)

        def person(user_id):
            user = users.get(user_id)
            return {"id": str(user.id), "name": user.name, "role": user.role.value, "role_label": ROLE_LABELS.get(user.role.value, user.role.value)} if user else None

        out = []
        for snag in snags:
            project = projects[snag.project_id]
            out.append({
                "id": str(snag.id), "project_id": str(project.id), "project_name": project.name, "project_code": project.code,
                "title": snag.title, "area": snag.area, "notes": snag.notes,
                "due_date": snag.due_date.isoformat() if snag.due_date else None, "urgent": snag.urgent,
                "status": snag.status, "assignee": person(snag.assignee_user_id), "created_by": person(snag.created_by),
                "created_at": snag.created_at.isoformat() if snag.created_at else None,
                "updated_at": snag.updated_at.isoformat() if snag.updated_at else None,
                "closed_at": snag.closed_at.isoformat() if snag.closed_at else None,
                "closed_by": person(snag.closed_by), "closing_note": snag.closing_note,
                "files": files.get(snag.id, []),
                **self.permissions(snag, project, actor),
            })
        return out

    def serialize(self, snag: ProjectSnag, actor: User) -> dict:
        return self.serialize_many([snag], actor)[0]

    # ---- audit / notify ----------------------------------------------------

    def _audit(self, actor: User, project: V2Project, action: str, snag: ProjectSnag, reason: str, before=None, after=None) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id, action=action, entity_type="snag", entity_id=snag.id, project_id=project.id,
            before_json=before, after_json=after, reason=reason,
        ))

    def _notify_tagged(self, snag: ProjectSnag, project: V2Project, actor: User) -> None:
        if not settings.snag_whatsapp_enabled or not snag.assignee_user_id or snag.assignee_user_id == actor.id:
            return
        OutboxService(self.db).emit(
            event_type="snag.assigned", aggregate_type="user", aggregate_id=snag.assignee_user_id,
            payload={"user_id": str(snag.assignee_user_id), "snag_id": str(snag.id), "snag_title": snag.title,
                     "project_name": project.name, "tagged_by": actor.name, "area": snag.area or "-"},
            idempotency_key=f"snag.assigned:{snag.id}:{snag.assignee_user_id}:{_now().isoformat()}",
        )

    # ---- reads ---------------------------------------------------------------

    def list_for_project(self, project_id: uuid.UUID, actor: User) -> dict:
        project = self._project(project_id)
        if not self.can_view_project(project, actor):
            raise HTTPException(403, "You do not have access to this project.")
        snags = self.db.scalars(
            select(ProjectSnag).where(ProjectSnag.project_id == project_id)
            .order_by(ProjectSnag.status, ProjectSnag.urgent.desc(), ProjectSnag.created_at.desc())
        ).all()
        return {
            "project_id": str(project.id), "read_only": project.status in READ_ONLY_STATUSES,
            "can_add": project.status not in READ_ONLY_STATUSES,
            "items": self.serialize_many(snags, actor, {project.id: project}),
        }

    def tagged_to(self, actor: User) -> list[dict]:
        snags = self.db.scalars(
            select(ProjectSnag).where(ProjectSnag.assignee_user_id == actor.id, ProjectSnag.status == "open")
            .order_by(ProjectSnag.urgent.desc(), ProjectSnag.due_date.is_(None), ProjectSnag.due_date, ProjectSnag.created_at)
        ).all()
        return self.serialize_many(snags, actor)

    def people(self) -> list[dict]:
        users = self.db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
        return [{"id": str(user.id), "name": user.name, "role": user.role.value, "role_label": ROLE_LABELS.get(user.role.value, user.role.value)} for user in users]

    # ---- writes --------------------------------------------------------------

    def create(self, project_id: uuid.UUID, actor: User, data: dict) -> dict:
        project = self._project(project_id)
        if not self.can_view_project(project, actor):
            raise HTTPException(403, "Only people on this project, or an admin, can add snags.")
        self._require_writable(project)
        self._assignee(data.get("assignee_user_id"))
        snag = ProjectSnag(project_id=project.id, created_by=actor.id, status="open", **data)
        self.db.add(snag)
        self.db.flush()
        self._audit(actor, project, "SNAG_ADDED", snag, f"Snag added: {snag.title}", after={"title": snag.title, "assignee_user_id": str(snag.assignee_user_id) if snag.assignee_user_id else None})
        self._notify_tagged(snag, project, actor)
        self.db.commit()
        self.db.refresh(snag)
        return self.serialize(snag, actor)

    def update(self, snag_id: uuid.UUID, actor: User, changes: dict) -> dict:
        snag, project = self._snag(snag_id, actor)
        if not self.permissions(snag, project, actor)["can_edit"]:
            self._require_writable(project)
            raise HTTPException(403, "Only whoever added this snag, the project's PM or Supervisor, or an admin can edit it.")
        if "title" in changes and changes["title"] is None:
            raise HTTPException(422, "Give the snag a short title.")
        if "urgent" in changes and changes["urgent"] is None:
            changes.pop("urgent")
        retagged = "assignee_user_id" in changes and changes["assignee_user_id"] != snag.assignee_user_id
        if retagged:
            self._assignee(changes["assignee_user_id"])
        before = {key: str(getattr(snag, key)) if getattr(snag, key) is not None else None for key in changes}
        for key, value in changes.items():
            setattr(snag, key, value)
        self._audit(actor, project, "SNAG_UPDATED", snag, f"Snag updated: {snag.title}", before=before,
                    after={key: str(value) if value is not None else None for key, value in changes.items()})
        if retagged:
            self._notify_tagged(snag, project, actor)
        self.db.commit()
        self.db.refresh(snag)
        return self.serialize(snag, actor)

    def set_status(self, snag_id: uuid.UUID, actor: User, status: str, closing_note: str | None) -> dict:
        snag, project = self._snag(snag_id, actor)
        if not self.permissions(snag, project, actor)["can_close"]:
            self._require_writable(project)
            raise HTTPException(403, "Only the tagged person, whoever added it, the PM or Supervisor, or an admin can close this snag.")
        if status == snag.status:
            return self.serialize(snag, actor)
        if status == "done":
            snag.status, snag.closed_at, snag.closed_by, snag.closing_note = "done", _now(), actor.id, closing_note
            action, reason = "SNAG_CLOSED", f"Snag closed: {snag.title}"
        else:
            snag.status, snag.closed_at, snag.closed_by, snag.closing_note = "open", None, None, None
            action, reason = "SNAG_REOPENED", f"Snag reopened: {snag.title}"
        self._audit(actor, project, action, snag, reason, after={"status": snag.status, "closing_note": closing_note})
        self.db.commit()
        self.db.refresh(snag)
        return self.serialize(snag, actor)

    def delete(self, snag_id: uuid.UUID, actor: User) -> dict:
        snag, project = self._snag(snag_id, actor)
        if not self.permissions(snag, project, actor)["can_delete"]:
            self._require_writable(project)
            raise HTTPException(403, "Only whoever added this snag, the project's PM, or an admin can delete it.")
        self._audit(actor, project, "SNAG_DELETED", snag, f"Snag deleted: {snag.title}", before={"title": snag.title, "status": snag.status})
        self.db.delete(snag)
        self.db.commit()
        return {"message": "Snag deleted."}

    # ---- files -------------------------------------------------------------

    def add_file(self, snag_id: uuid.UUID, actor: User, *, data: bytes, filename: str | None, content_type: str | None) -> dict:
        snag, project = self._snag(snag_id, actor)
        if not self.permissions(snag, project, actor)["can_attach"]:
            self._require_writable(project)
            raise HTTPException(403, "You can't add files to this snag.")
        extension, mime_type, clean_name = validate_reference_file(data, filename, content_type)
        storage_key = f"project-snags/{project.id}/{uuid.uuid4().hex}{extension}"
        evidence_storage.write(storage_key, data, mime_type)
        file_object = FileObject(storage_key=storage_key, original_filename=clean_name, mime_type=mime_type,
                                 size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest(), uploaded_by=actor.id)
        self.db.add(file_object)
        self.db.flush()
        self.db.add(ProjectSnagFile(snag_id=snag.id, file_id=file_object.id, uploaded_by=actor.id))
        self._audit(actor, project, "SNAG_FILE_ADDED", snag, f"File added to snag: {clean_name}", after={"filename": clean_name})
        self.db.commit()
        return self.serialize(snag, actor)

    def _file_link(self, snag: ProjectSnag, link_id: uuid.UUID) -> tuple[ProjectSnagFile, FileObject]:
        link = self.db.get(ProjectSnagFile, link_id)
        if not link or link.snag_id != snag.id:
            raise HTTPException(404, "File not found on this snag.")
        file_object = self.db.get(FileObject, link.file_id)
        if not file_object:
            raise HTTPException(404, "File not found on this snag.")
        return link, file_object

    def read_file(self, snag_id: uuid.UUID, link_id: uuid.UUID, actor: User) -> tuple[FileObject, bytes]:
        snag, _ = self._snag(snag_id, actor)
        _, file_object = self._file_link(snag, link_id)
        return file_object, read_reference_bytes(file_object)

    def remove_file(self, snag_id: uuid.UUID, link_id: uuid.UUID, actor: User) -> dict:
        snag, project = self._snag(snag_id, actor)
        self._require_writable(project)
        link, file_object = self._file_link(snag, link_id)
        if not (link.uploaded_by == actor.id or self.permissions(snag, project, actor)["can_edit"]):
            raise HTTPException(403, "Only whoever uploaded this file, or someone who can edit the snag, can remove it.")
        self._audit(actor, project, "SNAG_FILE_REMOVED", snag, f"File removed from snag: {file_object.original_filename}", before={"filename": file_object.original_filename})
        self.db.delete(link)
        self.db.commit()
        return self.serialize(snag, actor)
