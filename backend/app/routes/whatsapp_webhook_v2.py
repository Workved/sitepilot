"""Phase 2 U6: inbound WhatsApp webhook receiver (R8/R9).

THE SIGNATURE-VERIFICATION GATE: the raw request body bytes (never the
Pydantic-parsed JSON - FastAPI/Pydantic auto-parsing would consume the body
before we can hash it) are read via `await request.body()` and HMAC-SHA256'd
with `settings.whatsapp_webhook_secret`, then compared - using
`hmac.compare_digest` (constant-time, never `==`, to avoid a timing-attack
surface) - against the hex digest in the `X-Hub-Signature-256` header
(format `sha256=<hex digest>`, matching Meta's actual webhook convention).
If the header is missing, malformed, `settings.whatsapp_webhook_secret` is
empty, or the digest doesn't match, this returns 401 IMMEDIATELY - before
the JSON body is parsed, before any database query, before any
`inbound_messages` row is written. Only a signature-verified request ever
reaches `InboundMessageService.process`.

THE VERIFICATION HANDSHAKE (GET): before Meta will deliver anything to this
URL, registering it in Meta for Developers > WhatsApp > Configuration
requires answering one GET request with `?hub.mode=subscribe&hub.verify_
token=<token>&hub.challenge=<n>` by echoing `hub.challenge` back verbatim -
proving whoever owns the URL also knows the token entered in Meta's
dashboard. `settings.whatsapp_webhook_verify_token` is that token (distinct
from `whatsapp_webhook_secret`, which signs the POST deliveries themselves,
not this one-time handshake).

Expected JSON payload shape - Meta's real WhatsApp Cloud API webhook body
(https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/):

    {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "<waba_id>",
        "changes": [{
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "..."},
            "messages": [{
              "from": "919000000001",
              "id": "wamid.HBgLMTIzNDU2Nzg5MAA=",
              "timestamp": "1700000000",
              "type": "text",
              "text": {"body": "ACCEPT 1a2b3c4d"}
            }]
          }
        }]
      }]
    }

`messages[].from` arrives as bare digits with no leading `+` (Meta's
convention) - every phone number this codebase stores is E.164 with a
leading `+` (enforced at write time, e.g. `app.routes.users`'s "+919876543210"
validation), so it is prefixed with `+` before being handed to
`InboundMessageService`, which matches by raw string equality against those
stored values (see that module's docstring for why no further normalization
is applied). A `changes[].value` with `statuses` instead of `messages` is a
delivery/read receipt, not an inbound message - skipped, not an error. Meta
may batch multiple entries/changes/messages in one delivery; every message
found is processed.

`"image"`/`"document"` message types (U9) have their `id`/`mime_type`
(document-only: `filename`) metadata pulled out by `_extract_media_metadata`
below - parsing only, never a `download_inbound_media` (`whatsapp_media.py`)
call from this module; downloading is a separate, later-triggered concern
(see that function's own docstring), decided by `InboundMessageService`
(U10) once it knows there is an open evidence session to attach the result
to AND the mime_type is one this feature accepts. `message_text` for these
types is still `""`, same as any other non-`"text"` type - `InboundMessageService`
treats that as "no text", not necessarily "Unrecognized command": an
attachment with metadata still routes into an open session; a message with
neither text nor media metadata (a location pin, a reaction, etc.) is what
actually gets rejected as "Unrecognized command."

The payload's top-level `errors[]` array (distinct from
`entry[].changes[].value.messages[]`) carries Meta-side delivery failures
(e.g. error 131052, "unable to download media sent by the user") - not a
message, nothing to route to `InboundMessageService`; logged and skipped,
matching this module's "never surfaced as 4xx/5xx" discipline.

On success (200) each message's outcome is recorded internally on its own
`inbound_messages` row (`processing_status`); it is never surfaced back to
the provider as a 4xx/5xx for a business-level failure (unmatched phone
number, ambiguous match, invalid command, a rejected task transition,
etc.) - providers retry non-2xx responses, and an unmatched/invalid inbound
message should never trigger infinite provider retries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.execution_models import MessageDelivery
from app.services.inbound_message import InboundMessageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/whatsapp", tags=["v2-whatsapp-webhook"])

_MEDIA_MESSAGE_TYPES = ("image", "document")
_SUPPORTED_CALLBACK_STATUSES = ("sent", "delivered", "read", "failed")
_STATUS_PROGRESSION_RANK = {
    "queued": 0,
    "sending": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
}


def _verify_signature(raw_body: bytes, signature_header: str | None) -> None:
    if not settings.whatsapp_webhook_secret:
        raise HTTPException(401, "Invalid webhook signature.")
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(401, "Invalid webhook signature.")

    provided_digest = signature_header[len("sha256="):]
    expected_digest = hmac.new(
        settings.whatsapp_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided_digest, expected_digest):
        raise HTTPException(401, "Invalid webhook signature.")


def _extract_messages(payload: dict) -> list[dict]:
    """Pulls every `messages[]` entry out of Meta's nested envelope,
    tolerating any level being absent/malformed (a `statuses`-only change,
    an empty `entry` list, etc.) rather than raising - a webhook body this
    route doesn't recognize the shape of is simply "no messages found",
    never a 4xx (see module docstring's "never surfaced as 4xx/5xx" rule)."""
    messages: list[dict] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            for message in value.get("messages") or []:
                if isinstance(message, dict):
                    messages.append(message)
    return messages


def _extract_errors(payload: dict) -> list[dict]:
    """Pulls the payload's top-level `errors[]` array - Meta-side delivery
    failures (e.g. error 131052) that are not an inbound message at all and
    have nothing to route to `InboundMessageService`. Tolerates a missing/
    malformed `errors` key the same way `_extract_messages` tolerates a
    malformed envelope - "no errors found", never a 4xx."""
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return []
    return [error for error in errors if isinstance(error, dict)]


def _extract_statuses(payload: dict) -> list[dict]:
    """Pulls every `statuses[]` entry out of Meta's nested
    `entry[].changes[].value.statuses` envelope, tolerating any missing or
    malformed level without raising."""
    statuses: list[dict] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            for status_item in value.get("statuses") or []:
                if isinstance(status_item, dict):
                    statuses.append(status_item)
    return statuses


def _parse_status_timestamp(raw_timestamp: object) -> datetime:
    """Parses Meta's Unix epoch seconds timestamp string/int into a UTC
    datetime, falling back to current UTC time if absent or malformed."""
    if raw_timestamp is not None:
        try:
            return datetime.fromtimestamp(int(str(raw_timestamp)), tz=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            try:
                parsed = datetime.fromisoformat(str(raw_timestamp))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return datetime.now(timezone.utc)


def _apply_status_update(db: Session, status_item: dict) -> bool:
    """Applies a single Meta WhatsApp status callback (`sent`, `delivered`,
    `read`, `failed`) to its matching `MessageDelivery` row.

    Enforces monotonic forward progression (`read` never reverts to
    `delivered` or `sent`; `delivered` never reverts to `sent`; already
    `delivered`/`read` rows never revert to `failed`) and idempotency on
    duplicate callbacks. Unknown `provider_message_id` callbacks are logged
    safely without exposing sensitive payload or recipient data.
    """
    provider_message_id = status_item.get("id")
    raw_status = status_item.get("status")
    if not provider_message_id or not isinstance(provider_message_id, str):
        return False
    if raw_status not in _SUPPORTED_CALLBACK_STATUSES:
        return False

    try:
        delivery = db.scalar(
            select(MessageDelivery).where(MessageDelivery.provider_message_id == provider_message_id)
        )
    except OperationalError:
        db.rollback()
        return False

    if delivery is None:
        logger.warning(
            "WhatsApp status callback for unknown provider_message_id=%s (status=%s)",
            provider_message_id,
            raw_status,
        )
        return False

    event_ts = _parse_status_timestamp(status_item.get("timestamp"))
    current_status = delivery.status

    if raw_status == "sent":
        if _STATUS_PROGRESSION_RANK.get(current_status, -1) < _STATUS_PROGRESSION_RANK["sent"]:
            delivery.status = "sent"
            db.add(delivery)
            return True
        return False

    if raw_status == "delivered":
        changed = False
        if delivery.delivered_at is None:
            delivery.delivered_at = event_ts
            changed = True
        if _STATUS_PROGRESSION_RANK.get(current_status, -1) < _STATUS_PROGRESSION_RANK["delivered"]:
            delivery.status = "delivered"
            changed = True
        if changed:
            db.add(delivery)
        return changed

    if raw_status == "read":
        changed = False
        if delivery.read_at is None:
            delivery.read_at = event_ts
            changed = True
        if current_status != "read":
            delivery.status = "read"
            changed = True
        if changed:
            db.add(delivery)
        return changed

    if raw_status == "failed":
        if current_status in ("delivered", "read"):
            return False
        delivery.status = "failed"
        if delivery.failed_at is None:
            delivery.failed_at = event_ts
        errors = status_item.get("errors")
        first_err = (
            next((err for err in errors if isinstance(err, dict)), None)
            if isinstance(errors, list)
            else None
        )
        if first_err is not None:
            code = first_err.get("code")
            title = first_err.get("title") or first_err.get("message")
            error_data = first_err.get("error_data")
            details = error_data.get("details") if isinstance(error_data, dict) else None
            delivery.failure_code = str(code) if code is not None else (delivery.failure_code or "provider_failed")
            reason_parts = [str(part) for part in (title, details) if part]
            delivery.failure_reason = (
                ": ".join(reason_parts)
                if reason_parts
                else (delivery.failure_reason or "WhatsApp delivery failed.")
            )
            delivery.error_details = first_err
        else:
            delivery.failure_code = delivery.failure_code or "provider_failed"
            delivery.failure_reason = delivery.failure_reason or "WhatsApp delivery failed."
        db.add(delivery)
        return True

    return False


def _process_whatsapp_statuses(db: Session, payload: dict) -> int:
    """Processes all status callbacks in the webhook payload and commits any
    updates."""
    statuses = _extract_statuses(payload)
    if not statuses:
        return 0
    updated = 0
    for status_item in statuses:
        if _apply_status_update(db, status_item):
            updated += 1
    if updated > 0:
        db.commit()
    return updated


def _extract_media_metadata(message: dict) -> dict | None:
    """For an `"image"`/`"document"` inbound message, pulls `id`/
    `mime_type` (and, document-only, `filename`) out of the type-specific
    object - WITHOUT calling `download_inbound_media`
    (`app.services.whatsapp_media`); parsing and downloading are separate
    concerns; see that function's own docstring for why. Returns `None` for
    any other message type, or a media message whose type-specific object
    is missing/malformed."""
    message_type = message.get("type")
    if message_type not in _MEDIA_MESSAGE_TYPES:
        return None
    media_object = message.get(message_type)
    if not isinstance(media_object, dict):
        return None
    metadata = {"id": media_object.get("id"), "mime_type": media_object.get("mime_type")}
    if message_type == "document":
        metadata["filename"] = media_object.get("filename")
    return metadata


@router.get("/inbound")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if (
        mode == "subscribe"
        and settings.whatsapp_webhook_verify_token
        and token == settings.whatsapp_webhook_verify_token
        and challenge is not None
    ):
        # Meta expects the raw challenge string back, not JSON.
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "Webhook verification failed.")


@router.post("/inbound")
async def receive_inbound_whatsapp_message(request: Request, db: Session = Depends(get_db)):
    # Read raw bytes BEFORE any JSON parsing - required for the signature
    # computation to match what the provider actually signed.
    raw_body = await request.body()
    _verify_signature(raw_body, request.headers.get("X-Hub-Signature-256"))

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Malformed JSON payload.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(422, "Malformed JSON payload.")

    for error in _extract_errors(payload):
        # Meta-side delivery failure (e.g. 131052) - not a message, nothing
        # to route to InboundMessageService. Logged and skipped, never
        # surfaced as a 4xx/5xx.
        logger.warning("WhatsApp webhook delivered a top-level error: %s", error)

    _process_whatsapp_statuses(db, payload)

    for message in _extract_messages(payload):
        provider_message_id = message.get("id")
        sender_phone = message.get("from")
        if not provider_message_id or not sender_phone:
            continue  # Malformed individual message - skip it, not the whole batch.

        message_text = ""
        if message.get("type") == "text":
            message_text = (message.get("text") or {}).get("body") or ""

        # U10: image/document metadata extracted above is threaded straight
        # into InboundMessageService.process() - it decides whether/how to
        # act on it (an open evidence session's attachment, or ignored
        # otherwise); this route only ever parses, never downloads.
        _media_metadata = _extract_media_metadata(message)

        InboundMessageService(db).process(
            str(provider_message_id), f"+{sender_phone}", str(message_text), _media_metadata,
        )

    return {"status": "received"}
