"""Real Meta WhatsApp Cloud API adapter (Graph API).

Implements the same `WhatsAppProviderAdapter` protocol as
`SandboxProviderAdapter` (see `app.services.message_dispatch`), so it is a
drop-in replacement - `MessageDispatchService(db, adapter=MetaCloudApiAdapter())`.
`app.services.outbox_scheduler._build_adapter` is what actually constructs
this, once `whatsapp_access_token`/`whatsapp_phone_number_id` are configured
- an operator setting real env vars, not a code change. This module only
sends - callers own retries, persistence, and recipient resolution.

Only template messages are supported (`type: "template"` in the Graph API
request body), never free-form text: WhatsApp's Cloud API rejects a
business-initiated free-form text message outside a 24h customer-service
session (error 131047), so a template is the only message shape that
reliably sends on a fresh test number. `hello_world` is the one template
every WhatsApp Business Account has pre-approved from creation - it is what
`backend/app/scripts/test_whatsapp_send.py` uses to prove connectivity
before any custom template exists.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from app.config import settings
from app.services.message_dispatch import ProviderSendResult
from app.services.message_templates import is_placeholder_template

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"


class MetaCloudApiAdapter:
    """Sends WhatsApp template messages via Meta's Graph API.

    Credentials default to `app.config.settings` (env-sourced) but can be
    overridden per-instance, e.g. for a one-off script run against a
    different test number without touching `.env`.
    """

    provider_name = "meta"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        api_version: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.access_token = access_token or settings.whatsapp_access_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_number_id
        self.api_version = api_version or settings.whatsapp_api_version
        self.timeout = timeout

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
        if not recipient_phone:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_phone",
                failure_reason="Recipient has no phone number on file.",
            )
        if not template or is_placeholder_template(template):
            logger.warning(
                "WhatsApp template %r is an unapproved TBD placeholder; blocking Graph API send.",
                template,
            )
            return ProviderSendResult(
                ok=False,
                failure_code="template_unapproved",
                failure_reason=f"WhatsApp template '{template}' is a TBD placeholder and is not yet approved in Meta Business Manager.",
            )
        if not self.access_token or not self.phone_number_id:
            return ProviderSendResult(
                ok=False,
                failure_code="not_configured",
                failure_reason="WhatsApp access token / phone number id not set.",
            )

        url = f"{GRAPH_API_BASE}/{self.api_version}/{self.phone_number_id}/messages"
        body = self._build_body(recipient_phone, template, payload)

        try:
            response = httpx.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return ProviderSendResult(ok=False, failure_code="network_error", failure_reason=str(exc))

        data = response.json() if response.content else {}

        if response.status_code >= 400:
            error = data.get("error", {})
            return ProviderSendResult(
                ok=False,
                failure_code=str(error.get("code", response.status_code)),
                failure_reason=error.get("message") or f"HTTP {response.status_code}",
            )

        messages = data.get("messages") or []
        provider_message_id = messages[0].get("id") if messages else None
        return ProviderSendResult(ok=True, provider_message_id=provider_message_id)

    @staticmethod
    def _build_body(recipient_phone: str, template: str, payload: dict) -> dict:
        language_code = payload.get("language_code", "en_US")
        template_body: dict = {"name": template, "language": {"code": language_code}}
        components = payload.get("components")
        if components:
            template_body["components"] = components
        return {
            "messaging_product": "whatsapp",
            "to": recipient_phone,
            "type": "template",
            "template": template_body,
        }


DOUBLETICK_TEMPLATE_URL = "https://public.doubletick.io/whatsapp/message/template"

# Per-message statuses DoubleTick reports for a message it accepted. A
# `FAILED` entry (template not found, placeholder count mismatch, ...) comes
# back inside a 201 response, so the HTTP status alone is not enough.
_DOUBLETICK_ACCEPTED = {"SENT", "ENQUEUED", "QUEUED", "ACCEPTED"}


class DoubleTickAdapter:
    """Sends WhatsApp template messages through DoubleTick's public API.

    For a WhatsApp number onboarded through DoubleTick (a client-owned
    WABA): Meta answers a direct Graph API send from any other app with
    error 10 / subcode 2593181, so the send has to go through DoubleTick.
    The templates themselves are the same Meta-approved ones, so the
    `components` that `render_components` builds are converted to
    DoubleTick's flat `placeholders` list instead of being re-rendered.

    Same `WhatsAppProviderAdapter` protocol and guards as
    `MetaCloudApiAdapter`; `outbox_scheduler._build_adapter` picks it when
    `whatsapp_provider` is "doubletick".
    """

    provider_name = "doubletick"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        from_number: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key or settings.doubletick_api_key
        self.from_number = from_number or settings.doubletick_from_number
        self.timeout = timeout

    def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
        if not recipient_phone:
            return ProviderSendResult(
                ok=False,
                failure_code="missing_phone",
                failure_reason="Recipient has no phone number on file.",
            )
        if not template or is_placeholder_template(template):
            logger.warning(
                "WhatsApp template %r is an unapproved TBD placeholder; blocking DoubleTick send.",
                template,
            )
            return ProviderSendResult(
                ok=False,
                failure_code="template_unapproved",
                failure_reason=f"WhatsApp template '{template}' is a TBD placeholder and is not yet approved in Meta Business Manager.",
            )
        if not self.api_key or not self.from_number:
            return ProviderSendResult(
                ok=False,
                failure_code="not_configured",
                failure_reason="DoubleTick API key / sender number not set.",
            )

        message_id = str(uuid.uuid4())
        body = self._build_body(self.from_number, recipient_phone, template, payload, message_id)

        try:
            response = httpx.post(
                DOUBLETICK_TEMPLATE_URL,
                json=body,
                # DoubleTick takes the raw key, with no "Bearer " prefix.
                headers={"Authorization": self.api_key},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return ProviderSendResult(ok=False, failure_code="network_error", failure_reason=str(exc))

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}

        if response.status_code >= 400:
            reason = data.get("message") if isinstance(data, dict) else None
            if isinstance(reason, list):
                reason = "; ".join(str(item) for item in reason)
            return ProviderSendResult(
                ok=False,
                failure_code=f"doubletick_{response.status_code}",
                failure_reason=reason or f"HTTP {response.status_code}",
            )

        result = self._first_result(data)
        status = str(result.get("status") or "").upper()
        if status and status not in _DOUBLETICK_ACCEPTED:
            return ProviderSendResult(
                ok=False,
                failure_code=f"doubletick_{status.lower()}",
                failure_reason=result.get("errorMessage") or result.get("message") or f"DoubleTick status {status}",
            )
        return ProviderSendResult(ok=True, provider_message_id=result.get("messageId") or message_id)

    @staticmethod
    def _build_body(from_number: str, recipient_phone: str, template: str, payload: dict, message_id: str) -> dict:
        content: dict = {"templateName": template, "language": payload.get("language_code", "en")}
        placeholders = [
            parameter.get("text", "")
            for component in payload.get("components") or []
            if component.get("type") == "body"
            for parameter in component.get("parameters") or []
        ]
        if placeholders:
            content["templateData"] = {"body": {"placeholders": placeholders}}
        return {
            "messages": [
                {
                    "from": from_number,
                    "to": recipient_phone,
                    "messageId": message_id,
                    "content": content,
                }
            ]
        }

    @staticmethod
    def _first_result(data: object) -> dict:
        """DoubleTick documents one result per message but not the
        envelope, so accept a bare list, a `messages`/`data` list, or the
        single result object itself."""
        if isinstance(data, dict):
            for key in ("messages", "data", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}

