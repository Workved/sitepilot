"""Vendor categories - an Admin-managed list.

A vendor category is also a template phase: a vendor can be given a task only
when one of its categories matches the task's phase
(`TaskVendorAssignmentService._vendor_matches_task_category`). So the same
list feeds the vendor pickers and the template task form.

Rules that keep vendor matching working:

* names are unique, case-insensitively;
* a category already used as a task phase (in any template or project) can't
  be renamed - existing tasks keep the old phase text, so renaming would stop
  their vendors matching. Add a new category and hide the old one instead;
* "remove" deletes a category only when no vendor has it and no task uses it
  as a phase; otherwise it is hidden: gone from pickers, kept by vendors that
  already have it, and still matching their tasks.

Only Super Admin and Admin manage the list.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution_models import Task
from app.models import User
from app.project_models import V2AuditEvent, V2ProjectTask
from app.template_models import V2TemplateTask
from app.vendor_models import V2CapabilityCategory, V2VendorCapability

MAX_NAME = 80


def clean_name(name: str | None) -> str:
    clean = " ".join((name or "").split())
    if len(clean) < 2:
        raise HTTPException(422, "Give the category a name (at least 2 characters).")
    if len(clean) > MAX_NAME:
        raise HTTPException(422, f"Keep the name to {MAX_NAME} characters or fewer.")
    return clean


def phase_use_count(db: Session, name: str) -> int:
    """How many template, draft-project and live tasks use this as their phase."""
    lowered = name.strip().lower()
    total = 0
    for column in (V2TemplateTask.phase, V2ProjectTask.phase, Task.phase):
        total += db.scalar(select(func.count()).where(func.lower(func.trim(column)) == lowered)) or 0
    return total


def vendor_counts(db: Session) -> dict[uuid.UUID, int]:
    return dict(db.execute(
        select(V2VendorCapability.category_id, func.count()).group_by(V2VendorCapability.category_id)
    ).all())


class VendorCategoryService:
    def __init__(self, db: Session):
        self.db = db

    def _find_by_name(self, name: str, exclude_id: uuid.UUID | None = None) -> V2CapabilityCategory | None:
        query = select(V2CapabilityCategory).where(func.lower(func.trim(V2CapabilityCategory.name)) == name.lower())
        if exclude_id:
            query = query.where(V2CapabilityCategory.id != exclude_id)
        return self.db.scalar(query)

    def _get(self, category_id: uuid.UUID) -> V2CapabilityCategory:
        category = self.db.get(V2CapabilityCategory, category_id)
        if category is None:
            raise HTTPException(404, "Category not found.")
        return category

    def _audit(self, actor: User, action: str, category: V2CapabilityCategory | None, category_id: uuid.UUID, before=None, after=None) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id, action=action, entity_type="vendor_category", entity_id=category_id,
            source="portal", before_json=before, after_json=after, reason=f"Vendor category {action.lower().replace('_', ' ')}.",
        ))

    def create(self, name: str, actor: User) -> tuple[V2CapabilityCategory, bool]:
        """Returns (category, created). Adding a hidden category's name shows it again."""
        clean = clean_name(name)
        existing = self._find_by_name(clean)
        if existing is not None:
            if existing.active:
                raise HTTPException(409, f"\"{existing.name}\" already exists.")
            existing.active = True
            self._audit(actor, "VENDOR_CATEGORY_SHOWN", existing, existing.id, {"active": False}, {"active": True})
            self.db.commit()
            return existing, False
        category = V2CapabilityCategory(name=clean, active=True, created_by=actor.id)
        self.db.add(category)
        self.db.flush()
        self._audit(actor, "VENDOR_CATEGORY_ADDED", category, category.id, after={"name": clean})
        self.db.commit()
        return category, True

    def update(self, category_id: uuid.UUID, actor: User, *, name: str | None = None, active: bool | None = None) -> V2CapabilityCategory:
        category = self._get(category_id)
        before = {"name": category.name, "active": category.active}
        if name is not None:
            clean = clean_name(name)
            if clean != category.name:
                if clean.lower() != category.name.strip().lower():
                    if self._find_by_name(clean, exclude_id=category.id) is not None:
                        raise HTTPException(409, f"\"{clean}\" already exists.")
                    used = phase_use_count(self.db, category.name)
                    if used:
                        raise HTTPException(409, (
                            f"\"{category.name}\" is the phase of {used} task{'s' if used != 1 else ''}, so renaming it would stop "
                            "their vendors matching. Add a new category and hide this one instead."
                        ))
                category.name = clean
        if active is not None:
            category.active = active
        self._audit(actor, "VENDOR_CATEGORY_UPDATED", category, category.id, before, {"name": category.name, "active": category.active})
        self.db.commit()
        return category

    def remove(self, category_id: uuid.UUID, actor: User) -> dict:
        """Delete when nothing uses it; otherwise hide it."""
        category = self._get(category_id)
        vendors = vendor_counts(self.db).get(category.id, 0)
        tasks = phase_use_count(self.db, category.name)
        if vendors or tasks:
            category.active = False
            self._audit(actor, "VENDOR_CATEGORY_HIDDEN", category, category.id, {"active": True}, {"active": False, "vendors": vendors, "tasks": tasks})
            self.db.commit()
            reasons = [f"{vendors} vendor{'s' if vendors != 1 else ''} have it" if vendors else None,
                       f"{tasks} task{'s' if tasks != 1 else ''} use it as their phase" if tasks else None]
            return {"id": str(category.id), "deleted": False, "hidden": True,
                    "message": f"\"{category.name}\" was hidden, not deleted, because {' and '.join(r for r in reasons if r)}."}
        name = category.name
        self.db.delete(category)
        self._audit(actor, "VENDOR_CATEGORY_DELETED", None, category_id, before={"name": name})
        self.db.commit()
        return {"id": str(category_id), "deleted": True, "hidden": False, "message": f"\"{name}\" was deleted."}
