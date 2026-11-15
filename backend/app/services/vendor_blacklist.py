"""Vendor blacklist - the only vendor status a person can set.

A vendor on the list is simply a vendor (stored as status 'active', never
shown). Blacklisting needs a reason and:

* ends the vendor's current project mappings, task assignments and
  people-on-project rows - and, for a main vendor, those of its sub-vendors,
  which are blocked while their main vendor is blacklisted. Rows are ended
  (`ends_at`), never deleted, so the history stays;
* sends the vendor nothing. Deliberately not `ProjectVendorService.
  remove_vendor`: that emits `project.vendor_removed`, whose WhatsApp
  template carries the removal reason - here, the blacklist reason;
* blocks new project mappings, task assignments and sub-vendors (checked in
  `ProjectVendorService.map_vendor`, `TaskVendorAssignmentService.
  assign_vendor` and `require_main_vendor`, via `vendor_block_reason`).

Who: Super Admin, Admin, Project Manager and Supervisor can blacklist; only
Super Admin and Admin can remove a vendor from the blacklist.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.project_models import V2AuditEvent
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2Vendor,
    V2VendorContact,
    VendorContactProject,
)

BLACKLIST_ROLES = (UserRole.super_admin, UserRole.admin, UserRole.project_manager, UserRole.supervisor)
UNBLACKLIST_ROLES = (UserRole.super_admin, UserRole.admin)


def vendor_block_reason(db: Session, vendor: V2Vendor) -> str | None:
    """Why this vendor can't take new work, or None. A sub-vendor is
    blocked while its main vendor is blacklisted."""
    if vendor.status == "blacklisted":
        return "This vendor is blacklisted."
    if vendor.parent_vendor_id:
        parent = db.get(V2Vendor, vendor.parent_vendor_id)
        if parent is not None and parent.status == "blacklisted":
            return "This sub-vendor's main vendor is blacklisted."
    return None


def _clean_reason(reason: str | None, action: str) -> str:
    clean = (reason or "").strip()
    if len(clean) < 4:
        raise HTTPException(422, f"Give a reason (at least 4 characters) to {action}.")
    return clean


class VendorBlacklistService:
    def __init__(self, db: Session):
        self.db = db

    def _audit(self, actor: User, action: str, entity_type: str, entity_id: uuid.UUID, reason: str, project_id=None, before=None, after=None) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id, action=action, entity_type=entity_type, entity_id=entity_id,
            project_id=project_id, before_json=before, after_json=after, reason=reason,
        ))

    def _end_current_work(self, vendor_ids: list[uuid.UUID], actor: User, reason: str, now: datetime) -> dict:
        mappings = self.db.scalars(
            select(ProjectVendor).where(ProjectVendor.vendor_id.in_(vendor_ids), ProjectVendor.ends_at.is_(None))
        ).all()
        assignments = self.db.scalars(
            select(TaskVendorAssignment).where(TaskVendorAssignment.vendor_id.in_(vendor_ids), TaskVendorAssignment.ends_at.is_(None))
        ).all()
        contact_ids = self.db.scalars(select(V2VendorContact.id).where(V2VendorContact.vendor_id.in_(vendor_ids))).all()
        people = self.db.scalars(
            select(VendorContactProject).where(VendorContactProject.contact_id.in_(contact_ids), VendorContactProject.ends_at.is_(None))
        ).all() if contact_ids else []

        audit_reason = f"Ended because the vendor was blacklisted: {reason}"
        for row in assignments:
            row.ends_at = now
            self._audit(actor, "VENDOR_TASK_UNASSIGNED", "task_vendor_assignment", row.id, audit_reason, row.project_id,
                        {"vendor_id": str(row.vendor_id), "task_id": str(row.task_id), "ends_at": None},
                        {"vendor_id": str(row.vendor_id), "task_id": str(row.task_id), "ends_at": now.isoformat()})
        for row in mappings:
            row.ends_at = now
            self._audit(actor, "VENDOR_REMOVED_FROM_PROJECT", "project_vendor", row.id, audit_reason, row.project_id,
                        {"vendor_id": str(row.vendor_id), "ends_at": None},
                        {"vendor_id": str(row.vendor_id), "ends_at": now.isoformat()})
        for row in people:
            row.ends_at = now
        return {
            "projects_ended": len({row.project_id for row in mappings}),
            "task_assignments_ended": len(assignments),
            "people_assignments_ended": len(people),
        }

    def blacklist(self, vendor_id: uuid.UUID, reason: str, actor: User) -> dict:
        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")
        if vendor.status == "blacklisted":
            raise HTTPException(409, "This vendor is already blacklisted.")
        clean = _clean_reason(reason, "blacklist this vendor")
        now = datetime.now(timezone.utc)

        sub_vendor_ids = self.db.scalars(select(V2Vendor.id).where(V2Vendor.parent_vendor_id == vendor.id)).all()
        ended = self._end_current_work([vendor.id, *sub_vendor_ids], actor, clean, now)

        vendor.status = "blacklisted"
        vendor.blacklist_reason = clean
        vendor.blacklisted_at = now
        vendor.blacklisted_by = actor.id
        self._audit(actor, "vendor_blacklisted", "vendor", vendor.id, clean,
                    before={"status": "active"},
                    after={"status": "blacklisted", "sub_vendors_blocked": len(sub_vendor_ids), **ended})
        self.db.commit()
        return {"id": str(vendor.id), "status": vendor.status, "sub_vendors_blocked": len(sub_vendor_ids), **ended}

    def unblacklist(self, vendor_id: uuid.UUID, reason: str, actor: User) -> dict:
        vendor = self.db.get(V2Vendor, vendor_id)
        if not vendor:
            raise HTTPException(404, "Vendor not found.")
        if vendor.status != "blacklisted":
            raise HTTPException(409, "This vendor is not blacklisted.")
        clean = _clean_reason(reason, "remove this vendor from the blacklist")
        before = {
            "status": "blacklisted", "blacklist_reason": vendor.blacklist_reason,
            "blacklisted_at": vendor.blacklisted_at.isoformat() if vendor.blacklisted_at else None,
            "blacklisted_by": str(vendor.blacklisted_by) if vendor.blacklisted_by else None,
        }
        vendor.status = "active"
        vendor.blacklist_reason = None
        vendor.blacklisted_at = None
        vendor.blacklisted_by = None
        self._audit(actor, "vendor_unblacklisted", "vendor", vendor.id, clean, before=before, after={"status": "active"})
        self.db.commit()
        return {"id": str(vendor.id), "status": vendor.status}
