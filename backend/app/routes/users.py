import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import can_create_role, require_roles
from app.database import get_db
from app.models import AccessRequest, AccessRequestEvent, EmployeeProfile, User, UserAccountEvent, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.schemas.requests import MyProfileUpdateIn, UserDeleteIn, UserInviteIn, UserLifecycleIn, UserUpdateIn
from app.services.access_control import access_catalog, manageable_roles
from app.services.outbox import OutboxService
from app.services.serializers import public_user
from app.services.supabase_auth import SupabaseAuthError, admin_delete_user, admin_update_user

router = APIRouter(prefix="/api/users", tags=["users"])


def clean_required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(422, f"{label} is required.")
    return cleaned


def clean_phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    phone = value.strip().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise HTTPException(422, "Use an international mobile number such as +919876543210.")
    return phone


def ensure_manageable(actor: User, target: User | None) -> User:
    if not target or target.role == UserRole.super_admin or target.role not in manageable_roles(actor.role):
        raise HTTPException(403, "You cannot manage this account.")
    return target


def add_event(db: Session, target: User, actor: User, event_type: str, reason: str, from_role: UserRole | None = None, to_role: UserRole | None = None) -> None:
    db.add(UserAccountEvent(
        user_id=target.id,
        event_type=event_type,
        from_role=from_role.value if from_role else None,
        to_role=to_role.value if to_role else None,
        reason=reason,
        actor_id=actor.id,
    ))


def profile_for(db: Session, user_id: uuid.UUID) -> EmployeeProfile | None:
    return db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))


def active_accountability_message(db: Session, target: User) -> str | None:
    active_states = ("draft", "active", "on_hold")
    employee = profile_for(db, target.id)
    if employee:
        v2_project = db.scalar(
            select(V2Project)
            .join(V2ProjectMembership, V2ProjectMembership.project_id == V2Project.id)
            .where(
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
                V2Project.status.in_(active_states),
            )
        )
        if v2_project:
            return "End or replace this employee's active V2 project assignment before offboarding the account."
    # The PM/Supervisor guards that used to follow read the legacy
    # `execution_projects`/`execution_tasks` tables, which nothing had
    # written to since project execution moved to V2 - so they could never
    # fire. The V2 membership check above covers every role's active project
    # assignment, which is what those guards were protecting.
    return None


@router.get("/access")
def user_access(actor: User = Depends(require_roles(*tuple(UserRole))), db: Session = Depends(get_db)):
    managed = manageable_roles(actor.role)
    if managed:
        statement = select(User).order_by(User.active.desc(), User.name)
        if actor.role == UserRole.admin:
            statement = statement.where(or_(User.id == actor.id, User.role.in_(managed)))
        users = [public_user(item, db) for item in db.scalars(statement).all()]
        mode = "manage"
    else:
        users = [public_user(actor, db)]
        mode = "profile"
    return {
        "mode": mode,
        "actor": public_user(actor, db),
        "manageable_roles": [role.value for role in managed],
        "roles": access_catalog(),
        "users": users,
    }


@router.get("/{user_id}/events")
def account_events(user_id: uuid.UUID, actor: User = Depends(require_roles(*tuple(UserRole))), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found.")
    if target.id != actor.id and target.role not in manageable_roles(actor.role):
        raise HTTPException(403, "You cannot view this account history.")
    events = db.scalars(select(UserAccountEvent).where(UserAccountEvent.user_id == user_id).order_by(UserAccountEvent.created_at.desc()).limit(20)).all()
    return [{
        "id": str(item.id),
        "event_type": item.event_type,
        "from_role": item.from_role,
        "to_role": item.to_role,
        "reason": item.reason,
        "created_at": item.created_at.isoformat(),
    } for item in events]


@router.post("/invite")
def invite_user(payload: UserInviteIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    """Pre-registers a roster entry with no password: the person's first
    Google sign-in auto-links to this row by matching email (see
    app.auth.current_user), which is when the account actually activates."""
    if not can_create_role(actor.role, payload.role):
        raise HTTPException(403, "You cannot create this role.")
    name = clean_required(payload.name, "Full name")
    email = clean_required(payload.email, "Email").lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "An account with this email already exists.")
    employee_code = clean_required(payload.employee_code, "Employee code")
    designation = clean_required(payload.designation, "Designation")
    phone = clean_phone(payload.phone)

    user = User(
        name=name,
        email=email,
        phone=phone,
        role=payload.role,
        password_hash=None,
        supabase_user_id=None,
        created_by=actor.id,
    )
    db.add(user)
    try:
        db.flush()
        db.add(EmployeeProfile(
            user_id=user.id,
            employee_code=employee_code.upper(),
            designation=designation,
            department=(payload.department or "").strip() or None,
            # WhatsApp is the primary channel. An Admin can still move a
            # person to Telegram via the channel toggle once they connect.
            active_channel="whatsapp",
        ))
        add_event(db, user, actor, "ACCOUNT_INVITED", "Pre-registered for Google sign-in; awaiting first login.", to_role=payload.role)
        OutboxService(db).emit(
            event_type="user.created",
            aggregate_type="user",
            aggregate_id=user.id,
            payload={"user_id": str(user.id), "name": user.name},
            idempotency_key=f"user:{user.id}:user.created",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email or employee code is already in use.") from exc
    return public_user(user, db)


@router.put("/me/profile")
def update_my_profile(payload: MyProfileUpdateIn, actor: User = Depends(require_roles(*tuple(UserRole))), db: Session = Depends(get_db)):
    actor.name = clean_required(payload.name, "Full name")
    actor.phone = clean_phone(payload.phone)
    if actor.role == UserRole.super_admin and not db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id)):
        # The bootstrap Super Admin is seeded without a profile, and every
        # notification/inbound-reply lookup joins through EmployeeProfile -
        # without one their phone is never used for WhatsApp.
        db.add(EmployeeProfile(
            user_id=actor.id,
            employee_code=f"SUPERADMIN-{actor.id.hex[:8].upper()}",
            designation="Super Admin",
            active_channel="whatsapp",
        ))
    if actor.supabase_user_id:
        try:
            admin_update_user(str(actor.supabase_user_id), {"user_metadata": {"name": actor.name, "siteops_role": actor.role.value}})
        except SupabaseAuthError as exc:
            raise HTTPException(exc.status_code, exc.public_message) from exc
    add_event(db, actor, actor, "SELF_PROFILE_UPDATED", "Personal contact details updated.")
    db.commit()
    return public_user(actor, db)


@router.put("/{user_id}")
def update_user(user_id: uuid.UUID, payload: UserUpdateIn, actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)), db: Session = Depends(get_db)):
    target = ensure_manageable(actor, db.get(User, user_id))
    target_role = payload.role or target.role
    if target_role not in manageable_roles(actor.role):
        raise HTTPException(403, "You cannot assign this role.")
    role_changed = target_role != target.role
    if role_changed and len((payload.reason or "").strip()) < 4:
        raise HTTPException(422, "Provide a reason when changing a role.")

    old_role = target.role
    old_email = target.email
    target.name = clean_required(payload.name, "Full name")
    target.email = clean_required(payload.email, "Email").lower()
    target.phone = clean_phone(payload.phone)
    target.role = target_role
    profile = profile_for(db, target.id)
    if not profile:
        profile = EmployeeProfile(user_id=target.id, employee_code=clean_required(payload.employee_code, "Employee code").upper(), designation=clean_required(payload.designation, "Designation"))
        db.add(profile)
    else:
        profile.employee_code = clean_required(payload.employee_code or profile.employee_code, "Employee code").upper()
        profile.designation = clean_required(payload.designation or profile.designation, "Designation")
    profile.department = (payload.department or "").strip() or None

    # No Supabase identity to sync yet for a pre-registered roster row that
    # hasn't completed its first Google sign-in (`supabase_user_id` is only
    # ever set by `current_user()`'s auto-link on that first login - see
    # `app.auth`). Editing the local roster row is still valid and expected
    # in that window (e.g. correcting a typo'd invite email before the
    # person has signed in) - there is simply nothing on the Supabase side
    # to push the change to yet; it self-resolves once they do sign in,
    # since auto-link matches against whatever email is on this row then.
    if target.supabase_user_id:
        try:
            admin_update_user(str(target.supabase_user_id), {
                "email": target.email,
                "user_metadata": {"name": target.name, "siteops_role": target.role.value},
            })
        except SupabaseAuthError as exc:
            db.rollback()
            raise HTTPException(exc.status_code, exc.public_message) from exc

    add_event(db, target, actor, "ROLE_CHANGED" if role_changed else "PROFILE_UPDATED", (payload.reason or "Profile details updated.").strip(), old_role if role_changed else None, target_role if role_changed else None)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if target.supabase_user_id:
            try:
                admin_update_user(str(target.supabase_user_id), {"email": old_email})
            except SupabaseAuthError:
                pass
        raise HTTPException(409, "Email or employee code is already in use.") from exc
    return public_user(target, db)


def clean_lifecycle_reason(value: str | None) -> str:
    reason = clean_required(value, "Reason")
    if len(reason) < 4:
        raise HTTPException(422, "Provide a meaningful reason of at least four characters.")
    return reason


def set_account_active(db: Session, target: User, actor: User, active: bool, reason: str) -> User:
    if target.active == active:
        return target
    if not active:
        blocked = active_accountability_message(db, target)
        if blocked:
            raise HTTPException(409, blocked)
    # As in update_user above: a pre-registered row that hasn't signed in yet
    # has no Supabase identity to ban/unban - `current_user()`'s own
    # `if not user.active` check (app.auth) already blocks a linked-on-first-
    # login attempt for an offboarded account regardless, so there is nothing
    # unsafe about skipping the Supabase call here.
    if target.supabase_user_id:
        try:
            admin_update_user(str(target.supabase_user_id), {"ban_duration": "none" if active else "876000h"})
        except SupabaseAuthError as exc:
            raise HTTPException(exc.status_code, exc.public_message) from exc
    target.active = active
    add_event(
        db,
        target,
        actor,
        "ACCOUNT_RESTORED" if active else "ACCOUNT_OFFBOARDED",
        reason,
    )
    if not active:
        # R13 is offboard-only: the restore branch above never emits this -
        # only the deactivation branch does.
        OutboxService(db).emit(
            event_type="user.offboarded",
            aggregate_type="user",
            aggregate_id=target.id,
            payload={"user_id": str(target.id), "name": target.name},
            idempotency_key=f"user:{target.id}:user.offboarded:{datetime.now(timezone.utc).isoformat()}",
        )
    db.commit()
    return target


def blocking_user_references(db: Session, user_id: uuid.UUID) -> list[str]:
    """Return operational FK references that make permanent deletion unsafe."""
    allowed_history = {
        ("employee_profiles", "user_id"),
        ("user_account_events", "user_id"),
        ("user_account_events", "actor_id"),
        ("access_requests", "submitted_by"),
        ("access_requests", "reviewed_by"),
        ("access_request_events", "actor_id"),
    }
    labels: list[str] = []
    database = inspect(db.bind)
    for table_name in database.get_table_names():
        for foreign_key in database.get_foreign_keys(table_name):
            if foreign_key.get("referred_table") != "users":
                continue
            for column, referred_column in zip(
                foreign_key.get("constrained_columns") or [],
                foreign_key.get("referred_columns") or [],
            ):
                if referred_column != "id" or (table_name, column) in allowed_history:
                    continue
                found = db.execute(
                    text(f'SELECT 1 FROM "{table_name}" WHERE "{column}" = :user_id LIMIT 1'),
                    {"user_id": user_id},
                ).first()
                if found:
                    labels.append(f"{table_name}.{column}")
    return sorted(set(labels))


@router.post("/{user_id}/offboard")
def offboard_user(
    user_id: uuid.UUID,
    payload: UserLifecycleIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = clean_lifecycle_reason(payload.reason)
    return public_user(set_account_active(db, target, actor, False, reason), db)


@router.post("/{user_id}/restore")
def restore_user(
    user_id: uuid.UUID,
    payload: UserLifecycleIn,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = clean_lifecycle_reason(payload.reason)
    return public_user(set_account_active(db, target, actor, True, reason), db)


@router.patch("/{user_id}/active")
def toggle_user(
    user_id: uuid.UUID,
    active: bool,
    actor: User = Depends(require_roles(UserRole.super_admin, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Backward-compatible lifecycle endpoint; new UI uses offboard/restore with reasons."""
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = "Account restored through legacy lifecycle endpoint." if active else "Account deactivated through legacy lifecycle endpoint."
    return public_user(set_account_active(db, target, actor, active, reason), db)


@router.delete("/{user_id}")
def delete_user(
    user_id: uuid.UUID,
    payload: UserDeleteIn,
    actor: User = Depends(require_roles(UserRole.super_admin)),
    db: Session = Depends(get_db),
):
    target = ensure_manageable(actor, db.get(User, user_id))
    reason = clean_lifecycle_reason(payload.reason)
    if target.active:
        raise HTTPException(409, "Offboard this account before permanent deletion.")
    if payload.confirmation.strip().lower() != target.email.lower():
        raise HTTPException(422, "Enter the user's exact email address to confirm permanent deletion.")

    references = blocking_user_references(db, target.id)
    if references:
        raise HTTPException(
            409,
            "This account has project, task, approval, or system ownership history. Keep it offboarded instead of deleting it.",
        )

    auth_user_id = target.supabase_user_id
    deleted_email = target.email
    related_requests = db.scalars(select(AccessRequest).where(or_(
        AccessRequest.supabase_user_id == auth_user_id,
        func.lower(AccessRequest.email) == target.email.lower(),
    ))).all()
    for access_request in related_requests:
        access_request.status = "cancelled"
        access_request.review_notes = f"Unused account permanently deleted: {reason}"
        db.add(AccessRequestEvent(
            access_request_id=access_request.id,
            event_type="UNUSED_ACCOUNT_DELETED",
            reason=reason,
            actor_id=actor.id,
        ))
    try:
        db.delete(target)
        db.flush()
        if auth_user_id:
            admin_delete_user(str(auth_user_id))
        db.commit()
    except SupabaseAuthError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.public_message) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "This account has linked business history. Keep it offboarded instead of deleting it.",
        ) from exc
    return {"message": f"Unused account {deleted_email} was permanently deleted.", "reason": reason}