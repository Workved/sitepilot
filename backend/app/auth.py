from datetime import datetime, timedelta, timezone
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserAccountEvent, UserRole
from app.services.supabase_auth import SupabaseAuthError, local_dev_login_available, verify_access_token

bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required.")
    try:
        auth_identity = verify_access_token(credentials.credentials)
        supabase_user_id = uuid.UUID(auth_identity["id"])
    except SupabaseAuthError as exc:
        if exc.status_code >= 500:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_message) from exc
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please login again.") from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please login again.") from exc

    user = db.scalar(select(User).where(User.supabase_user_id == supabase_user_id))
    if not user:
        # Covers a pre-registered roster entry (app.routes.users.invite_user)
        # meeting its Supabase identity for the first time - e.g. the first
        # Google sign-in for that email, which Supabase has no prior record
        # of and so cannot link to an existing auth identity on its own.
        # Only for identities whose email nobody could have claimed: Google
        # (it never lets a user claim an address they don't own), or an
        # account an Admin created with a password (tagged with this row's
        # id in app_metadata, which only the service key can write). With
        # email/password sign-in enabled, anyone can self-register a
        # Supabase identity for any address, so a bare email match would let
        # them take over a pre-registered row.
        identity_email = str(auth_identity.get("email") or "").strip().lower()
        if identity_email:
            user = db.scalar(select(User).where(
                func.lower(User.email) == identity_email,
                User.supabase_user_id.is_(None),
            ))
            if user and not _may_link_by_email(auth_identity, user):
                user = None
            if user:
                user.supabase_user_id = supabase_user_id
                db.add(UserAccountEvent(
                    user_id=user.id,
                    event_type="ACCOUNT_LINKED",
                    from_role=None,
                    to_role=user.role.value,
                    reason="First sign-in linked this pre-registered account to its login identity.",
                    actor_id=user.id,
                ))
                db.commit()
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account isn't set up in SiteOps yet. Contact your administrator.")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is inactive. Contact your Admin or Super Admin.")
    now = datetime.now(timezone.utc)
    if not user.activated_at:
        user.activated_at = now
        db.add(UserAccountEvent(
            user_id=user.id,
            event_type="ACCOUNT_ACTIVATED",
            from_role=None,
            to_role=user.role.value,
            reason="Account activated on first authenticated portal session.",
            actor_id=user.id,
        ))
    if not user.last_login_at or user.last_login_at < now - timedelta(minutes=5):
        user.last_login_at = now
    if db.is_modified(user):
        db.commit()
    return user


def _may_link_by_email(auth_identity: dict, user: User) -> bool:
    app_metadata = auth_identity.get("app_metadata") or {}
    providers = set(app_metadata.get("providers") or [])
    providers.add(app_metadata.get("provider"))
    if "google" in providers:
        return True
    if app_metadata.get("siteops_user_id") == str(user.id):
        return True
    # Local dev login mints sessions through Supabase's email link flow, so
    # its identities look like email sign-ups; it only ever runs against a
    # local Supabase stack.
    return local_dev_login_available()


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission for this action.")
        return user
    return dependency


def can_create_role(actor_role: UserRole, target_role: UserRole) -> bool:
    if actor_role == UserRole.super_admin:
        return target_role in {UserRole.admin, UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee}
    if actor_role == UserRole.admin:
        return target_role in {UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee}
    return False
