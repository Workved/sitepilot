"""Vendor create/update/delete, backed by the siteops_v2 vendor schema.

`create_vendor` writing here rather than to legacy `public.vendors` is the
root-cause fix for the Vendor Hub gap: a vendor created in the hub used to
exist only in the legacy table, so the project-side vendor picker - which
reads `siteops_v2.vendors` - never saw it, and it could not be mapped to a
project until someone re-ran the one-time legacy import by hand.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import User, UserRole
from app.schemas.requests import VendorIn
from app.services.serializers import public_vendor
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2Vendor

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


@router.post("")
def create_vendor(payload: VendorIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    data = payload.model_dump()
    # Legacy `vendors.category` (single free-text column) has no V2 column -
    # capabilities are the normalized replacement and are set from Vendor
    # Hub's category picker via PUT /contractors/{id}.
    data.pop("category", None)
    vendor = V2Vendor(**data, created_by=actor.id)
    db.add(vendor)
    db.commit()
    return public_vendor(vendor)


@router.put("/{vendor_id}")
def update_vendor(vendor_id: uuid.UUID, payload: VendorIn, _: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = db.get(V2Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    for key, value in payload.model_dump().items():
        if key == "category":
            continue
        setattr(vendor, key, value)
    db.commit()
    return public_vendor(vendor)


@router.delete("/{vendor_id}")
def delete_vendor(vendor_id: uuid.UUID, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin, UserRole.project_manager)), db: Session = Depends(get_db)):
    vendor = db.get(V2Vendor, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    linked_sub_vendor_count = len(db.scalars(select(V2Vendor.id).where(V2Vendor.parent_vendor_id == vendor_id)).all())
    if linked_sub_vendor_count:
        noun = "sub-vendor" if linked_sub_vendor_count == 1 else "sub-vendors"
        verb = "is" if linked_sub_vendor_count == 1 else "are"
        raise HTTPException(409, f"This main vendor cannot be deleted because {linked_sub_vendor_count} {noun} {verb} still linked. Transfer or delete them first, or blacklist the main vendor instead.")
    assigned_task_count = len(db.scalars(select(TaskVendorAssignment.id).where(TaskVendorAssignment.vendor_id == vendor_id)).all())
    if assigned_task_count:
        noun = "task" if assigned_task_count == 1 else "tasks"
        raise HTTPException(409, f"This vendor cannot be deleted because it is assigned to {assigned_task_count} execution {noun}. Reassign those tasks, or blacklist the vendor instead to keep its assignment history.")
    mapped_project_count = len(db.scalars(select(ProjectVendor.id).where(ProjectVendor.vendor_id == vendor_id)).all())
    if mapped_project_count:
        noun = "project" if mapped_project_count == 1 else "projects"
        raise HTTPException(409, f"This vendor cannot be deleted because it is mapped to {mapped_project_count} {noun}. Remove those mappings, or blacklist the vendor instead.")
    db.delete(vendor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This vendor cannot be deleted because it is still linked to operational records. Remove those links, or blacklist the vendor instead.")
    return {"message": "Vendor deleted."}
