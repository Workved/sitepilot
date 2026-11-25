"""Vendor feedback on finished SiteOps projects, and the work-history list it
hangs off.

Rules (one place, so the hub payload and the write endpoints agree):

* A vendor's SiteOps work history is every project they were mapped to
  where the work is over: the project is completed/archived, or the vendor
  no longer has an active mapping there (removed part-way). Before this,
  only removed mappings were listed, so a project that finished with the
  vendor still on it - the normal case - never appeared at all.
* Feedback can be left only on such an entry.
* Admin/Super Admin may review any project. A PM or Site Supervisor may
  review a project they were assigned to (a past assignment counts: someone
  replaced mid-project still saw the vendor work). Internal employees may
  not review.
* One review per person per vendor per project; the author edits it, the
  author or an admin removes it.
* Everyone who can see the vendor can read every review - the point is to
  help whoever picks a vendor for the next project.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.vendor_models import ProjectVendor, V2Vendor, V2VendorProjectFeedback

FINISHED_PROJECT_STATUSES = {"completed", "archived"}
REVIEW_PROJECT_ROLES = ("project_manager", "site_supervisor")
ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}
ROLE_LABELS = {
    "super_admin": "Super Admin",
    "admin": "Admin",
    "project_manager": "Project manager",
    "site_supervisor": "Site supervisor",
}


@dataclass
class WorkEntry:
    vendor_id: uuid.UUID
    project: V2Project
    mapping_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    removed: bool


def work_history(db: Session, vendor_ids=None, project_id=None) -> list[WorkEntry]:
    """Finished vendor/project pairs, newest first. A vendor mapped to the
    same project more than once collapses to one entry spanning all of it."""
    statement = select(ProjectVendor, V2Project).join(V2Project, V2Project.id == ProjectVendor.project_id)
    if vendor_ids is not None:
        if not vendor_ids:
            return []
        statement = statement.where(ProjectVendor.vendor_id.in_(vendor_ids))
    if project_id is not None:
        statement = statement.where(ProjectVendor.project_id == project_id)
    grouped: dict[tuple, list] = {}
    for link, project in db.execute(statement).all():
        grouped.setdefault((link.vendor_id, project.id), []).append((link, project))

    entries = []
    for (vendor_id, _), rows in grouped.items():
        project = rows[0][1]
        links = [link for link, _ in rows]
        active = any(link.ends_at is None for link in links)
        finished = project.status in FINISHED_PROJECT_STATUSES
        if active and not finished:
            continue
        latest = max(links, key=lambda link: link.created_at)
        if active:
            ended_at = project.completed_at
        else:
            ended_at = max(link.ends_at for link in links)
        entries.append(WorkEntry(
            vendor_id=vendor_id, project=project, mapping_id=latest.id,
            started_at=min(link.created_at for link in links), ended_at=ended_at,
            removed=not active and not finished,
        ))
    entries.sort(key=lambda entry: entry.ended_at or entry.started_at, reverse=True)
    return entries


def review_role_by_project(db: Session, actor: User) -> dict[uuid.UUID, str]:
    """Projects a non-admin may review, with the role they held there
    (PM wins if they held both at different times)."""
    profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
    if not profile:
        return {}
    rows = db.execute(
        select(V2ProjectMembership.project_id, V2ProjectMembership.project_role)
        .where(V2ProjectMembership.employee_id == profile.id, V2ProjectMembership.project_role.in_(REVIEW_PROJECT_ROLES))
    ).all()
    roles: dict[uuid.UUID, str] = {}
    for project_id, role in rows:
        if roles.get(project_id) != "project_manager":
            roles[project_id] = role
    return roles


def reviewer_role(db: Session, actor: User, project_id: uuid.UUID, cache: dict | None = None) -> str | None:
    if actor.role in ADMIN_ROLES:
        return actor.role.value
    if actor.role not in (UserRole.project_manager, UserRole.supervisor):
        return None
    roles = cache if cache is not None else review_role_by_project(db, actor)
    return roles.get(project_id)


def ensure_can_review(db: Session, actor: User, vendor_id: uuid.UUID, project_id: uuid.UUID) -> str:
    vendor = db.get(V2Vendor, vendor_id)
    project = db.get(V2Project, project_id)
    if not vendor or not project:
        raise HTTPException(404, "Vendor or project not found.")
    if not db.scalar(select(ProjectVendor.id).where(ProjectVendor.vendor_id == vendor_id, ProjectVendor.project_id == project_id).limit(1)):
        raise HTTPException(409, "This vendor never worked on that project.")
    if not work_history(db, vendor_ids=[vendor_id], project_id=project_id):
        raise HTTPException(409, "Feedback opens once the project is completed, or the vendor has been removed from it.")
    role = reviewer_role(db, actor, project_id)
    if not role:
        raise HTTPException(403, "Only an admin, or this project's PM or Site Supervisor, can leave feedback.")
    return role


def serialize_feedback(item: V2VendorProjectFeedback, author_names: dict, project_names: dict) -> dict:
    return {
        "id": str(item.id), "vendor_id": str(item.vendor_id), "project_id": str(item.project_id),
        "project_name": project_names.get(item.project_id),
        "author_user_id": str(item.author_user_id) if item.author_user_id else None,
        "author_name": author_names.get(item.author_user_id) or "Former user",
        "author_role": item.author_role, "author_role_label": ROLE_LABELS.get(item.author_role, item.author_role),
        "rating": item.rating, "quality": item.quality, "timeliness": item.timeliness, "conduct": item.conduct,
        "would_rehire": item.would_rehire, "comment": item.comment,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def feedback_for_vendors(db: Session, vendor_ids) -> list[dict]:
    if not vendor_ids:
        return []
    items = db.scalars(
        select(V2VendorProjectFeedback).where(V2VendorProjectFeedback.vendor_id.in_(vendor_ids))
        .order_by(V2VendorProjectFeedback.created_at.desc())
    ).all()
    author_ids = {item.author_user_id for item in items if item.author_user_id}
    project_ids = {item.project_id for item in items}
    author_names = dict(db.execute(select(User.id, User.name).where(User.id.in_(author_ids))).all()) if author_ids else {}
    project_names = dict(db.execute(select(V2Project.id, V2Project.name).where(V2Project.id.in_(project_ids))).all()) if project_ids else {}
    return [serialize_feedback(item, author_names, project_names) for item in items]


def feedback_response(db: Session, item: V2VendorProjectFeedback) -> dict:
    author = db.get(User, item.author_user_id) if item.author_user_id else None
    project = db.get(V2Project, item.project_id)
    return serialize_feedback(item, {author.id: author.name} if author else {}, {project.id: project.name} if project else {})


def pending_reviews(db: Session, actor: User) -> list[dict]:
    """Finished vendor/project pairs this PM or Supervisor could review and
    hasn't yet - the "rate your vendors" nudge. Admins get none: they can
    review everything, which would make the list noise."""
    if actor.role not in (UserRole.project_manager, UserRole.supervisor):
        return []
    roles = review_role_by_project(db, actor)
    if not roles:
        return []
    done = set(db.execute(
        select(V2VendorProjectFeedback.vendor_id, V2VendorProjectFeedback.project_id)
        .where(V2VendorProjectFeedback.author_user_id == actor.id)
    ).all())
    pending = []
    vendor_names: dict[uuid.UUID, str] = {}
    for project_id in roles:
        for entry in work_history(db, project_id=project_id):
            if (entry.vendor_id, project_id) in done:
                continue
            if entry.vendor_id not in vendor_names:
                vendor = db.get(V2Vendor, entry.vendor_id)
                vendor_names[entry.vendor_id] = vendor.name if vendor else "Vendor"
            pending.append({
                "vendor_id": str(entry.vendor_id), "vendor_name": vendor_names[entry.vendor_id],
                "project_id": str(project_id), "project_name": entry.project.name, "project_code": entry.project.code,
                "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
            })
    pending.sort(key=lambda item: item["ended_at"] or "", reverse=True)
    return pending
