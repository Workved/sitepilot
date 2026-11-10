"""DoubleTick WhatsApp sender (`DoubleTickAdapter`) and the
`whatsapp_provider` switch in `outbox_scheduler._build_adapter`.

Mocks `httpx.post` directly (no real network calls), mirroring
`test_telegram_provider.py`'s pattern.
"""

import unittest
from unittest.mock import patch

from app.config import settings
from app.services.message_dispatch import SandboxProviderAdapter
from app.services.message_templates import TEMPLATE_REGISTRY, render_components
from app.services.outbox_scheduler import _build_adapter
from app.services.whatsapp_provider import DoubleTickAdapter, MetaCloudApiAdapter


class _FakeResponse:
    """Minimal stand-in for an `httpx.Response` - only what
    `DoubleTickAdapter.send` reads (`.status_code`, `.content`, `.json()`)."""

    def __init__(self, status_code: int, json_body):
        self.status_code = status_code
        self._json_body = json_body
        self.content = b"x" if json_body is not None else b""

    def json(self):
        return self._json_body


def _status_update_payload() -> dict:
    spec = TEMPLATE_REGISTRY["task.status_changed"]
    fields = {
        "project_name": "Futurex Office",
        "task_label": "T003 - Flooring",
        "before_status_label": "Ready",
        "target_status_label": "In progress",
        "reason": None,
    }
    return {"components": render_components(spec, fields), "language_code": spec.language}


class DoubleTickAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = DoubleTickAdapter(api_key="dt-key", from_number="+918655796446")

    def test_sends_the_template_with_flattened_placeholders(self):
        response = _FakeResponse(201, [{"status": "ENQUEUED", "messageId": "dt-msg-1", "recipient": "+919000000010"}])
        with patch("app.services.whatsapp_provider.httpx.post", return_value=response) as post:
            result = self.adapter.send("+919000000010", "task_status_update", _status_update_payload())

        self.assertTrue(result.ok)
        self.assertEqual(result.provider_message_id, "dt-msg-1")
        _, kwargs = post.call_args
        self.assertEqual(post.call_args.args[0], "https://public.doubletick.io/whatsapp/message/template")
        self.assertEqual(kwargs["headers"], {"Authorization": "dt-key"})
        message = kwargs["json"]["messages"][0]
        self.assertEqual(message["from"], "+918655796446")
        self.assertEqual(message["to"], "+919000000010")
        self.assertEqual(len(message["messageId"]), 36)
        self.assertEqual(message["content"]["templateName"], "task_status_update")
        self.assertEqual(message["content"]["language"], "en")
        self.assertEqual(
            message["content"]["templateData"]["body"]["placeholders"],
            ["Futurex Office", "T003 - Flooring", "Ready", "In progress", "-"],
        )

    def test_a_template_without_variables_sends_no_template_data(self):
        response = _FakeResponse(201, {"status": "SENT", "messageId": "dt-msg-2"})
        with patch("app.services.whatsapp_provider.httpx.post", return_value=response) as post:
            result = self.adapter.send("+919000000010", "hello_world", {"language_code": "en_US", "components": []})

        self.assertTrue(result.ok)
        content = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertNotIn("templateData", content)
        self.assertEqual(content["language"], "en_US")

    def test_falls_back_to_its_own_message_id_when_none_is_returned(self):
        with patch("app.services.whatsapp_provider.httpx.post", return_value=_FakeResponse(201, None)) as post:
            result = self.adapter.send("+919000000010", "task_status_update", _status_update_payload())

        self.assertTrue(result.ok)
        self.assertEqual(result.provider_message_id, post.call_args.kwargs["json"]["messages"][0]["messageId"])

    def test_a_failed_entry_inside_a_201_is_a_failure(self):
        response = _FakeResponse(201, {"messages": [{"status": "FAILED", "errorMessage": "Template not found"}]})
        with patch("app.services.whatsapp_provider.httpx.post", return_value=response):
            result = self.adapter.send("+919000000010", "task_status_update", _status_update_payload())

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "doubletick_failed")
        self.assertEqual(result.failure_reason, "Template not found")

    def test_an_http_error_reports_doubleticks_message(self):
        response = _FakeResponse(401, {"statusCode": 401, "message": "Invalid public api key", "error": "Unauthorized"})
        with patch("app.services.whatsapp_provider.httpx.post", return_value=response):
            result = self.adapter.send("+919000000010", "task_status_update", _status_update_payload())

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "doubletick_401")
        self.assertEqual(result.failure_reason, "Invalid public api key")

    def test_a_validation_error_list_is_joined(self):
        response = _FakeResponse(400, {"statusCode": 400, "message": ["to must be a phone number", "from is required"]})
        with patch("app.services.whatsapp_provider.httpx.post", return_value=response):
            result = self.adapter.send("+919000000010", "task_status_update", _status_update_payload())

        self.assertEqual(result.failure_reason, "to must be a phone number; from is required")

    def test_blocks_tbd_placeholder_templates_without_calling_doubletick(self):
        with patch("app.services.whatsapp_provider.httpx.post") as post:
            result = self.adapter.send("+919000000010", "TBD_project_activated", {"language_code": "en", "components": []})

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "template_unapproved")
        post.assert_not_called()

    def test_a_missing_phone_fails_without_calling_doubletick(self):
        with patch("app.services.whatsapp_provider.httpx.post") as post:
            result = self.adapter.send("", "task_status_update", _status_update_payload())

        self.assertEqual(result.failure_code, "missing_phone")
        post.assert_not_called()

    def test_missing_credentials_fail_as_not_configured(self):
        with patch.object(settings, "doubletick_api_key", ""), patch.object(settings, "doubletick_from_number", ""), \
             patch("app.services.whatsapp_provider.httpx.post") as post:
            result = DoubleTickAdapter().send("+919000000010", "task_status_update", _status_update_payload())

        self.assertEqual(result.failure_code, "not_configured")
        post.assert_not_called()


class BuildAdapterTests(unittest.TestCase):
    def _build(self, provider: str, *, token: str = "", phone_id: str = "", key: str = "", sender: str = ""):
        with patch.object(settings, "whatsapp_provider", provider), \
             patch.object(settings, "whatsapp_access_token", token), \
             patch.object(settings, "whatsapp_phone_number_id", phone_id), \
             patch.object(settings, "doubletick_api_key", key), \
             patch.object(settings, "doubletick_from_number", sender):
            return _build_adapter()

    def test_doubletick_is_chosen_when_configured(self):
        self.assertIsInstance(self._build("doubletick", key="k", sender="+918655796446"), DoubleTickAdapter)

    def test_the_provider_name_is_case_insensitive(self):
        self.assertIsInstance(self._build(" DoubleTick ", key="k", sender="+918655796446"), DoubleTickAdapter)

    def test_doubletick_without_credentials_still_uses_doubletick_not_the_sandbox(self):
        self.assertIsInstance(self._build("doubletick", token="t", phone_id="p"), DoubleTickAdapter)

    def test_an_empty_provider_keeps_the_meta_behaviour(self):
        self.assertIsInstance(self._build("", token="t", phone_id="p"), MetaCloudApiAdapter)
        self.assertIsInstance(self._build(""), SandboxProviderAdapter)


if __name__ == "__main__":
    unittest.main()
