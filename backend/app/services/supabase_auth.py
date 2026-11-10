import hashlib
import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings

_TOKEN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE_TTL_SECONDS = 30


class SupabaseAuthError(Exception):
    def __init__(self, public_message: str, status_code: int = 502):
        self.public_message = public_message
        self.status_code = status_code
        super().__init__(public_message)


def _configuration() -> tuple[str, str, str]:
    url = settings.supabase_url.rstrip("/")
    if not url or not settings.supabase_publishable_key:
        raise SupabaseAuthError("Supabase Auth is not configured on the server.", 503)
    return url, settings.supabase_publishable_key, settings.supabase_secret_key


def _request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, token: str | None = None, admin: bool = False) -> Any:
    url, publishable_key, secret_key = _configuration()
    key = secret_key if admin else publishable_key
    if admin and not key:
        raise SupabaseAuthError("Supabase secret key is not configured on the server.", 503)
    headers = {"apikey": key, "Authorization": f"Bearer {token or key}"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(Request(f"{url}/auth/v1{path}", data=body, headers=headers, method=method), timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("msg") or detail.get("message") or detail.get("error_description")
        except (ValueError, UnicodeDecodeError):
            message = None
        if admin and exc.code in {400, 422} and message:
            raise SupabaseAuthError(message, 409) from exc
        raise SupabaseAuthError(message or "Supabase Auth rejected the request.", exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise SupabaseAuthError("Supabase Auth is temporarily unavailable.", 503) from exc


def verify_access_token(token: str) -> dict[str, Any]:
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
    identity = _request("/user", token=token)
    with _TOKEN_CACHE_LOCK:
        if len(_TOKEN_CACHE) >= 512:
            expired = [key for key, (expires_at, _) in _TOKEN_CACHE.items() if expires_at <= now]
            for key in expired or list(_TOKEN_CACHE)[:128]:
                _TOKEN_CACHE.pop(key, None)
        _TOKEN_CACHE[cache_key] = (now + _TOKEN_CACHE_TTL_SECONDS, identity)
    return identity


def local_dev_login_available() -> bool:
    """Whether the local-only dev login shortcut may run: LOCAL_DEV_LOGIN_ENABLED
    must be explicitly true (only docker-compose.yml sets it) AND SUPABASE_URL
    must point at a local host, so a stray env var alone can never enable it
    against a real deployment."""
    if not settings.local_dev_login_enabled:
        return False
    supabase_url = settings.supabase_url.lower()
    return any(host in supabase_url for host in ("127.0.0.1", "localhost", "host.docker.internal"))


def admin_create_user(*, email: str, password: str, metadata: dict[str, Any], app_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": metadata,
    }
    if app_metadata:
        payload["app_metadata"] = app_metadata
    result = _request("/admin/users", method="POST", admin=True, payload=payload)
    return result.get("user", result)


def admin_update_user(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = _request(f"/admin/users/{user_id}", method="PUT", admin=True, payload=payload)
    return result.get("user", result)


def admin_delete_user(user_id: str) -> None:
    _request(f"/admin/users/{user_id}", method="DELETE", admin=True)


def admin_find_user_by_email(email: str) -> dict[str, Any] | None:
    result = _request("/admin/users?page=1&per_page=1000", admin=True)
    users = result.get("users", result if isinstance(result, list) else [])
    return next((item for item in users if item.get("email", "").lower() == email.lower()), None)


def dev_login_session(email: str) -> dict[str, Any]:
    """Local-dev-only: mints a real session for `email` without a browser
    round trip, via the same magic-link mechanism a real "check your email"
    flow uses - admin_generate_link (service key) issues a one-time code,
    then /verify (anon key, like any client would) exchanges it for a
    session in one direct JSON response. See app/routes/auth.py's
    dev_login for the caller's local-only gating; this function itself
    performs no such check.

    GoTrue's actual `verification_type` on the generate_link response can
    differ from the requested "magiclink" - an email with no existing
    auth.users row comes back "signup" instead, since generate_link also
    creates that row - and /verify only accepts the type it actually issued
    the code under, so this must be read back rather than assumed."""
    link = _request("/admin/generate_link", method="POST", admin=True, payload={"type": "magiclink", "email": email})
    otp = link.get("email_otp")
    verification_type = link.get("verification_type") or "magiclink"
    if not otp:
        raise SupabaseAuthError("Supabase Auth did not return a one-time code.", 502)
    return _request("/verify", method="POST", payload={"type": verification_type, "email": email, "token": otp})

