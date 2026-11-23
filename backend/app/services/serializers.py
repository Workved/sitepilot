from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User
from app.vendor_models import V2Vendor


def public_user(user: User, db: Session | None = None) -> dict:
    profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user.id)) if db else None
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role.value,
        "active": user.active,
        "activation_status": "offboarded" if not user.active else ("active" if user.activated_at else "setup_pending"),
        "activated_at": user.activated_at.isoformat() if user.activated_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "employee_profile": {
            "id": str(profile.id),
            "employee_code": profile.employee_code,
            "designation": profile.designation,
            "department": profile.department,
            "availability": profile.availability,
            # WhatsApp is the only messaging channel: a person is reachable
            # once they have a phone number on file.
            "messaging_ready": bool(user.phone),
        } if profile else None,
    }


def public_vendor(vendor: V2Vendor) -> dict:
    # `category` and `migration_status` are gone with the legacy vendor
    # table: capabilities replaced the single free-text category column, and
    # `migration_pending` is not a valid V2 engagement_type (vendors in that
    # legacy state were never imported).
    return {
        "id": str(vendor.id),
        "name": vendor.name,
        "contact_person": vendor.contact_person,
        "phone": vendor.phone,
        "whatsapp": vendor.whatsapp,
        "notes": vendor.notes,
        "status": vendor.status,
        "engagement_type": vendor.engagement_type,
        "parent_vendor_id": str(vendor.parent_vendor_id) if vendor.parent_vendor_id else None,
    }
