"""Telegram Bot API adapter.

Implements a Telegram-equivalent send surface to `whatsapp_provider.py`'s
`MetaCloudApiAdapter` - not the same `WhatsAppProviderAdapter` protocol
(`send(recipient_phone, template, payload)`), since Telegram has no
Meta-style named-template system (KTD8 in
`docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md`).
This module only sends - callers own retries, persistence, and recipient
resolution, mirroring `whatsapp_provider.py`'s own scope.

Standalone at this point (U1): nothing calls this yet. Wiring it into
`MessageDispatchService` as a real per-recipient adapter option, and
resolving how event payloads become Telegram text/buttons instead of
Meta template components, is deferred to U9/U10/KTD8's open question
(see the plan's Deferred / Open Questions section) - out of scope here.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.message_dispatch import ProviderSendResult
from app.services.whatsapp_media import MediaDownloadResult

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

# The bot's @username never changes for a given bot token, so `getMe` is
# asked once per token per process (connect links are `t.me/<username>`).
_BOT_USERNAMES: dict[str, str] = {}


class TelegramProviderAdapter:
    """Sends Telegram messages via the Bot API's `sendMessage` method.

    Credentials default to `app.config.settings` (env-sourced) but can be
    overridden per-instance, mirroring `MetaCloudApiAdapter`'s pattern.
    """

    provider_name = "telegram"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.access_token = access_token or settings.telegram_access_token
        self.timeout = timeout

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
        """U10 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md):
        satisfies the same `WhatsAppProviderAdapter.send(...)` shape
        `MessageDispatchService`'s channel-to-adapter mapping (U9) calls
        uniformly for every channel, so this adapter can sit in that
        mapping alongside the WhatsApp adapter.

        `recipient_phone` here is actually the recipient's Telegram chat
        id - dispatch resolves the right identifier per channel (U10) and
        passes it through this same parameter name, which is the adapter
        Protocol's name, not a claim about what value it carries.

        `payload` is plain text dispatch has already resolved (KTD8: no
        Meta-template rendering for Telegram) under the `"text"` key, not
        a Meta-style components array. `template` is accepted for Protocol
        conformance but unused - Telegram has no named-template registry
        to look it up in.
        """
        if payload.get("buttons"):
            return self.send_with_buttons(
                recipient_phone, payload.get("text", ""), payload["buttons"], parse_mode=payload.get("parse_mode"),
            )
        return self.send_text(recipient_phone, payload.get("text", ""), parse_mode=payload.get("parse_mode"))

    def send_text(self, chat_id: str, text: str, parse_mode: str | None = None) -> ProviderSendResult:
        """Sends a text message. No inline keyboard. `parse_mode` (e.g.
        "HTML") is only sent when given, so plain-text callers are unchanged."""
        return self._send(chat_id, text, reply_markup=None, parse_mode=parse_mode)

    def send_with_buttons(
        self, chat_id: str, text: str, buttons: list[list[dict]], parse_mode: str | None = None,
    ) -> ProviderSendResult:
        """Sends a text message with an inline keyboard.

        `buttons` is a list of button rows, each row a list of
        `{"text": ..., "callback_data": ...}` dicts, matching Telegram's
        own `inline_keyboard` shape directly - no translation layer.
        """
        reply_markup = {"inline_keyboard": buttons}
        return self._send(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

    def answer_callback_query(self, callback_query_id: str, text: str) -> bool:
        """Stops the pressed button's loading spinner and shows `text` as a
        short toast. Best-effort: a failure is logged, never raised."""
        return self._call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text[:200]})

    def bot_username(self) -> str | None:
        """The bot's @username (without the @), for building a
        `https://t.me/<username>?start=<token>` link. None when the bot is
        not configured or Telegram can't be reached - callers fall back to
        the typed `/start <token>` command."""
        if not self.access_token:
            return None
        cached = _BOT_USERNAMES.get(self.access_token)
        if cached:
            return cached
        try:
            response = httpx.post(f"{TELEGRAM_API_BASE}/bot{self.access_token}/getMe", json={}, timeout=self.timeout)
            data = response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            # The exception text can carry the request URL, which holds the bot token.
            logger.warning("Telegram getMe failed: %s", type(exc).__name__)
            return None
        username = (data.get("result") or {}).get("username") if data.get("ok") else None
        if username:
            _BOT_USERNAMES[self.access_token] = username
        return username

    def remove_buttons(self, chat_id: str, message_id: int) -> bool:
        """Removes the inline keyboard from an already-sent message, so a
        completed action's buttons can't be pressed again. Best-effort."""
        return self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )

    # ---- files ------------------------------------------------------------
    # Failure reasons never include the request URL: it carries the bot token,
    # and a reason is stored (inbound rejection reason, delivery failure).

    def download_file(self, file_id: str, max_bytes: int | None = None) -> MediaDownloadResult:
        """Downloads an inbound file's bytes: `getFile` resolves the file's
        path on Telegram's servers, then the bytes are fetched from it. A
        size `getFile` reports above `max_bytes` stops before the download."""
        if not self.access_token:
            return MediaDownloadResult(ok=False, failure_code="not_configured", failure_reason="Telegram access token not set.")
        if not file_id:
            return MediaDownloadResult(ok=False, failure_code="media_not_found", failure_reason="No file id in the message.")
        try:
            response = httpx.post(
                f"{TELEGRAM_API_BASE}/bot{self.access_token}/getFile", json={"file_id": file_id}, timeout=self.timeout,
            )
            data = response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            return MediaDownloadResult(ok=False, failure_code="network_error", failure_reason="Telegram could not be reached.")
        result = data.get("result") or {}
        file_path = result.get("file_path")
        if response.status_code >= 400 or not data.get("ok", False) or not file_path:
            return MediaDownloadResult(
                ok=False, failure_code="media_not_found",
                failure_reason=data.get("description") or "Telegram did not return the file.",
            )
        size = result.get("file_size")
        if max_bytes is not None and isinstance(size, int) and size > max_bytes:
            return MediaDownloadResult(ok=False, failure_code="too_large", failure_reason="The file is too large.")
        try:
            file_response = httpx.get(
                f"{TELEGRAM_API_BASE}/file/bot{self.access_token}/{file_path}", timeout=max(self.timeout, 30.0),
            )
        except httpx.HTTPError:
            return MediaDownloadResult(ok=False, failure_code="network_error", failure_reason="Telegram could not be reached.")
        if file_response.status_code >= 400:
            return MediaDownloadResult(
                ok=False, failure_code="media_not_found", failure_reason=f"Telegram file download failed (HTTP {file_response.status_code}).",
            )
        return MediaDownloadResult(ok=True, bytes=file_response.content)

    def send_photo(self, chat_id: str, data: bytes, filename: str, mime_type: str, caption: str | None = None) -> ProviderSendResult:
        return self._send_file("sendPhoto", "photo", chat_id, data, filename, mime_type, caption)

    def send_document(self, chat_id: str, data: bytes, filename: str, mime_type: str, caption: str | None = None) -> ProviderSendResult:
        return self._send_file("sendDocument", "document", chat_id, data, filename, mime_type, caption)

    def _send_file(
        self, method: str, field: str, chat_id: str, data: bytes, filename: str, mime_type: str, caption: str | None,
    ) -> ProviderSendResult:
        """Uploads bytes the application already holds (multipart), so the
        recipient never gets a link into evidence storage."""
        if not chat_id:
            return ProviderSendResult(ok=False, failure_code="missing_chat_id", failure_reason="Recipient has no Telegram chat id on file.")
        if not self.access_token:
            return ProviderSendResult(ok=False, failure_code="not_configured", failure_reason="Telegram access token not set.")
        form = {"chat_id": chat_id}
        if caption:
            form["caption"] = caption[:1024]  # Telegram's caption limit
        try:
            response = httpx.post(
                f"{TELEGRAM_API_BASE}/bot{self.access_token}/{method}",
                data=form, files={field: (filename, data, mime_type)}, timeout=max(self.timeout, 60.0),
            )
            body = response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            return ProviderSendResult(ok=False, failure_code="network_error", failure_reason="Telegram could not be reached.")
        if response.status_code >= 400 or not body.get("ok", False):
            return ProviderSendResult(
                ok=False,
                failure_code=str(body.get("error_code", response.status_code)),
                failure_reason=body.get("description") or f"HTTP {response.status_code}",
            )
        message_id = (body.get("result") or {}).get("message_id")
        return ProviderSendResult(ok=True, provider_message_id=str(message_id) if message_id is not None else None)

    def _call(self, method: str, body: dict) -> bool:
        if not self.access_token:
            return False
        url = f"{TELEGRAM_API_BASE}/bot{self.access_token}/{method}"
        try:
            response = httpx.post(url, json=body, timeout=self.timeout)
            data = response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Telegram %s failed: %s", method, exc)
            return False
        if response.status_code >= 400 or not data.get("ok", False):
            logger.warning("Telegram %s failed: %s", method, data.get("description") or response.status_code)
            return False
        return True

    def _send(self, chat_id: str, text: str, *, reply_markup: dict | None, parse_mode: str | None = None) -> ProviderSendResult:
        if not chat_id:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_chat_id",
                failure_reason="Recipient has no Telegram chat id on file.",
            )
        if not self.access_token:
            return ProviderSendResult(
                ok=False,
                failure_code="not_configured",
                failure_reason="Telegram access token not set.",
            )

        url = f"{TELEGRAM_API_BASE}/bot{self.access_token}/sendMessage"
        body: dict = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        if parse_mode:
            body["parse_mode"] = parse_mode

        try:
            response = httpx.post(url, json=body, timeout=self.timeout)
        except httpx.HTTPError as exc:
            return ProviderSendResult(ok=False, failure_code="network_error", failure_reason=str(exc))

        data = response.json() if response.content else {}

        if response.status_code >= 400 or not data.get("ok", False):
            return ProviderSendResult(
                ok=False,
                failure_code=str(data.get("error_code", response.status_code)),
                failure_reason=data.get("description") or f"HTTP {response.status_code}",
            )

        result = data.get("result") or {}
        message_id = result.get("message_id")
        return ProviderSendResult(ok=True, provider_message_id=str(message_id) if message_id is not None else None)
