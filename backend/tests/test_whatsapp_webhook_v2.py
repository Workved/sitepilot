"""Phase 2 U9: inbound webhook parsing for `image`/`document` message types
and the top-level `errors[]` array (`app.routes.whatsapp_webhook_v2`).

The existing all-text-message webhook scenarios (signature gate,
verification handshake, identity matching, multi-message batching, etc.)
already live in `test_inbound_message_matching_v2.py` and are unchanged by
this unit - re-run there, not duplicated here.

This file covers only what U9 added:
    - `_extract_media_metadata` / `_extract_errors`, unit-tested directly
      (no DB, no HTTP) since they are pure parsing helpers.
    - An end-to-end image/document webhook delivery: parsed without ever
      calling `download_inbound_media` itself in this route (parsing and
      downloading are separate concerns - see `whatsapp_media.py`); since
      U10, the parsed metadata is threaded into `InboundMessageService`,
      which decides whether a download is warranted (an open evidence
      session's attachment) - see test_inbound_message_matching_v2.py for
      that session-routing behavior, this file only pins the route's own
      parse-don't-download boundary.
    - An `errors[]`-only delivery: handled without raising and without
      reaching `InboundMessageService.process()`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import get_db
from app.execution_models import GateEvidenceSession, InboundMessage, MessageDelivery, OutboxEvent
from app.models import EmployeeProfile, User, UserRole
from app.routes.whatsapp_webhook_v2 import (
    _extract_errors,
    _extract_media_metadata,
    _extract_statuses,
    router as whatsapp_webhook_router,
)
from app.vendor_models import V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"

WEBHOOK_SECRET = "test-webhook-secret"
EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
EMPLOYEE_PHONE = "+9000000099"


# ---- pure parsing helpers: no DB, no HTTP -----------------------------------


class ExtractMediaMetadataTests(unittest.TestCase):
    def test_text_message_has_no_media_metadata(self):
        self.assertIsNone(_extract_media_metadata({"type": "text", "text": {"body": "hi"}}))

    def test_image_message_extracts_id_and_mime_type(self):
        message = {"type": "image", "image": {"id": "media-1", "mime_type": "image/jpeg", "sha256": "abc"}}
        self.assertEqual(_extract_media_metadata(message), {"id": "media-1", "mime_type": "image/jpeg"})

    def test_document_message_also_extracts_filename(self):
        message = {
            "type": "document",
            "document": {"id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf"},
        }
        self.assertEqual(
            _extract_media_metadata(message),
            {"id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf"},
        )

    def test_image_message_has_no_filename_key(self):
        message = {"type": "image", "image": {"id": "media-1", "mime_type": "image/jpeg"}}
        self.assertNotIn("filename", _extract_media_metadata(message))

    def test_malformed_or_missing_media_object_does_not_raise(self):
        self.assertIsNone(_extract_media_metadata({"type": "image", "image": "not-a-dict"}))
        self.assertIsNone(_extract_media_metadata({"type": "image"}))
        self.assertIsNone(_extract_media_metadata({"type": "location", "location": {"latitude": 1}}))


class ExtractErrorsTests(unittest.TestCase):
    def test_no_errors_key_returns_empty_list(self):
        self.assertEqual(_extract_errors({}), [])

    def test_extracts_top_level_errors_array(self):
        payload = {"errors": [{"code": 131052, "title": "Unable to download media sent by the user"}]}
        self.assertEqual(_extract_errors(payload), [{"code": 131052, "title": "Unable to download media sent by the user"}])

    def test_non_dict_entries_and_non_list_shapes_are_tolerated(self):
        self.assertEqual(_extract_errors({"errors": ["not-a-dict", {"code": 1}]}), [{"code": 1}])
        self.assertEqual(_extract_errors({"errors": "not-a-list"}), [])


# ---- end-to-end webhook delivery: media parsing + top-level errors ----------


class WebhookMediaAndErrorsApiTests(unittest.TestCase):
    """Minimal harness: just enough schema for `InboundMessageService` to
    run its identity-matching queries (`users`/`employee_profiles`/
    `siteops_v2.vendor_contacts`) and write an `inbound_messages` row -
    same ATTACH-DATABASE-for-cross-schema-FKs pattern as
    `test_inbound_message_matching_v2.py`, trimmed to only what this file's
    scenarios touch."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2VendorContact.__table__, InboundMessage.__table__,
            GateEvidenceSession.__table__, OutboxEvent.__table__, MessageDelivery.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed_employee()

        self._original_webhook_secret = settings.whatsapp_webhook_secret
        settings.whatsapp_webhook_secret = WEBHOOK_SECRET

        self.app = FastAPI()
        self.app.include_router(whatsapp_webhook_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def _seed_employee(self) -> None:
        """A single active employee whose phone matches this file's media
        webhook payloads, so those deliveries resolve to a matched
        identity (and thus "rejected" - unrecognized command - rather
        than "unmatched"), exercising the same downstream path a real
        image/document delivery from a known sender would take."""
        with self.Session.begin() as session:
            session.add(User(
                id=EMPLOYEE_ID, name="Field Employee", email="field@example.com",
                role=UserRole.supervisor, active=True, phone=EMPLOYEE_PHONE,
            ))
            session.flush()
            profile = EmployeeProfile(
                user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Supervisor", availability="available",
            )
            session.add(profile)
            session.flush()
            self.employee_profile_id = profile.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.whatsapp_webhook_secret = self._original_webhook_secret

    def post_signed(self, envelope: dict):
        raw_body = json.dumps(envelope).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
        )

    def inbound_rows(self) -> list[InboundMessage]:
        with self.Session() as session:
            return list(session.scalars(select(InboundMessage)).all())

    @patch("app.services.whatsapp_media.download_inbound_media")
    def test_image_message_parsed_without_downloading_media(self, mock_download):
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "phone-1"},
                        "messages": [{
                            "from": "9000000099",
                            "id": "wamid.image-1",
                            "timestamp": "1700000000",
                            "type": "image",
                            "image": {"id": "media-1", "mime_type": "image/jpeg"},
                        }],
                    },
                }],
            }],
        }

        response = self.post_signed(envelope)

        self.assertEqual(response.status_code, 200, response.text)
        mock_download.assert_not_called()

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].provider_message_id, "wamid.image-1")
        # U10 threads this metadata through to InboundMessageService, which
        # routes a bare attachment into the sender's open evidence session
        # if one exists - this employee has none, so it is rejected with
        # that distinct reason rather than "Unrecognized command.", and
        # still never calls download_inbound_media for it (no session to
        # download into).
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "You have no open evidence session. Send GATEOPEN <ref> first.")

    @patch("app.services.whatsapp_media.download_inbound_media")
    def test_document_message_parsed_without_downloading_media(self, mock_download):
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "phone-1"},
                        "messages": [{
                            "from": "9000000099",
                            "id": "wamid.document-1",
                            "timestamp": "1700000000",
                            "type": "document",
                            "document": {
                                "id": "media-2", "mime_type": "application/pdf", "filename": "report.pdf",
                            },
                        }],
                    },
                }],
            }],
        }

        response = self.post_signed(envelope)

        self.assertEqual(response.status_code, 200, response.text)
        mock_download.assert_not_called()

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        # Same U10 routing as the image case above - no open session for
        # this employee, so this is rejected before download_inbound_media
        # is ever called.
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "You have no open evidence session. Send GATEOPEN <ref> first.")

    @patch("app.routes.whatsapp_webhook_v2.InboundMessageService")
    def test_top_level_errors_array_is_handled_without_calling_inbound_service(self, mock_service_cls):
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [],
            "errors": [{"code": 131052, "title": "Unable to download media sent by the user"}],
        }

        response = self.post_signed(envelope)

        self.assertEqual(response.status_code, 200, response.text)
        mock_service_cls.assert_not_called()
        self.assertEqual(self.inbound_rows(), [])

    # ---- Milestone 1 Phase 1: WhatsApp status callback processing ----------

    def _seed_delivery(self, provider_message_id: str, status: str = "sent") -> uuid.UUID:
        with self.Session.begin() as session:
            ev = OutboxEvent(
                event_type="task.status_changed",
                aggregate_type="task",
                aggregate_id=uuid.uuid4(),
                payload={"target_status": "ready"},
                idempotency_key=f"status-test:{uuid.uuid4()}",
                status="dispatched",
            )
            session.add(ev)
            session.flush()
            delivery = MessageDelivery(
                outbox_event_id=ev.id,
                recipient_employee_id=self.employee_profile_id,
                recipient_vendor_contact_id=None,
                recipient_phone=EMPLOYEE_PHONE,
                template="task_status_update",
                channel="whatsapp",
                provider="meta",
                provider_message_id=provider_message_id,
                status=status,
                attempt_count=1,
            )
            session.add(delivery)
            session.flush()
            return delivery.id

    def _get_delivery(self, delivery_id: uuid.UUID) -> MessageDelivery:
        with self.Session() as session:
            return session.get(MessageDelivery, delivery_id)

    def _status_envelope(self, *statuses: dict) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-1",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "phone-1"},
                        "statuses": list(statuses),
                    },
                }],
            }],
        }

    def test_extract_statuses_parses_nested_statuses_and_tolerates_malformed_input(self):
        self.assertEqual(_extract_statuses({}), [])
        self.assertEqual(_extract_statuses({"entry": "invalid"}), [])
        envelope = self._status_envelope({"id": "wamid.1", "status": "delivered"})
        self.assertEqual(_extract_statuses(envelope), [{"id": "wamid.1", "status": "delivered"}])

    def test_status_callback_rejects_invalid_or_missing_signature(self):
        delivery_id = self._seed_delivery("wamid.sig-test", status="sent")
        envelope = self._status_envelope({"id": "wamid.sig-test", "status": "delivered", "timestamp": "1700000100"})
        raw_body = json.dumps(envelope).encode("utf-8")

        missing_sig = self.client.post(
            "/api/v2/whatsapp/inbound", content=raw_body, headers={"Content-Type": "application/json"},
        )
        self.assertEqual(missing_sig.status_code, 401)

        bad_sig = self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=deadbeef"},
        )
        self.assertEqual(bad_sig.status_code, 401)
        self.assertEqual(self._get_delivery(delivery_id).status, "sent")

    def test_sent_delivered_and_read_callbacks_advance_status_and_record_timestamps(self):
        delivery_id = self._seed_delivery("wamid.lifecycle-1", status="sending")

        # 1. sent callback
        r1 = self.post_signed(self._status_envelope({
            "id": "wamid.lifecycle-1", "status": "sent", "timestamp": "1700000010",
        }))
        self.assertEqual(r1.status_code, 200)
        d1 = self._get_delivery(delivery_id)
        self.assertEqual(d1.status, "sent")
        self.assertIsNone(d1.delivered_at)
        self.assertIsNone(d1.read_at)

        # 2. delivered callback
        r2 = self.post_signed(self._status_envelope({
            "id": "wamid.lifecycle-1", "status": "delivered", "timestamp": "1700000020",
        }))
        self.assertEqual(r2.status_code, 200)
        d2 = self._get_delivery(delivery_id)
        self.assertEqual(d2.status, "delivered")
        self.assertIsNotNone(d2.delivered_at)
        self.assertEqual(int(d2.delivered_at.replace(tzinfo=timezone.utc).timestamp()), 1700000020)
        self.assertIsNone(d2.read_at)

        # 3. read callback
        r3 = self.post_signed(self._status_envelope({
            "id": "wamid.lifecycle-1", "status": "read", "timestamp": "1700000030",
        }))
        self.assertEqual(r3.status_code, 200)
        d3 = self._get_delivery(delivery_id)
        self.assertEqual(d3.status, "read")
        self.assertIsNotNone(d3.delivered_at)
        self.assertIsNotNone(d3.read_at)
        self.assertEqual(int(d3.read_at.replace(tzinfo=timezone.utc).timestamp()), 1700000030)

    def test_failed_status_callback_records_failure_code_reason_timestamp_and_error_details(self):
        delivery_id = self._seed_delivery("wamid.fail-1", status="sent")
        error_obj = {
            "code": 131047,
            "title": "Re-engagement message",
            "error_data": {"details": "More than 24 hours have passed since the customer last replied"},
        }
        response = self.post_signed(self._status_envelope({
            "id": "wamid.fail-1",
            "status": "failed",
            "timestamp": "1700000050",
            "errors": [error_obj],
        }))
        self.assertEqual(response.status_code, 200)
        delivery = self._get_delivery(delivery_id)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.failure_code, "131047")
        self.assertIn("Re-engagement message", delivery.failure_reason)
        self.assertIn("More than 24 hours", delivery.failure_reason)
        self.assertIsNotNone(delivery.failed_at)
        self.assertEqual(delivery.error_details, error_obj)

    def test_duplicate_status_callbacks_are_idempotent(self):
        delivery_id = self._seed_delivery("wamid.dup-1", status="sent")
        payload = self._status_envelope({
            "id": "wamid.dup-1", "status": "delivered", "timestamp": "1700000100",
        })
        self.assertEqual(self.post_signed(payload).status_code, 200)
        first_delivered_at = self._get_delivery(delivery_id).delivered_at

        # Second identical callback with a later timestamp must not overwrite delivered_at or error
        payload_dup = self._status_envelope({
            "id": "wamid.dup-1", "status": "delivered", "timestamp": "1700000999",
        })
        self.assertEqual(self.post_signed(payload_dup).status_code, 200)
        delivery = self._get_delivery(delivery_id)
        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.delivered_at, first_delivered_at)

    def test_out_of_order_callbacks_never_move_status_backward(self):
        delivery_id = self._seed_delivery("wamid.ooo-1", status="sent")

        # 'read' arrives first
        self.post_signed(self._status_envelope({
            "id": "wamid.ooo-1", "status": "read", "timestamp": "1700000200",
        }))
        self.assertEqual(self._get_delivery(delivery_id).status, "read")

        # Out-of-order 'delivered' arrives after 'read': status stays 'read', delivered_at is backfilled
        self.post_signed(self._status_envelope({
            "id": "wamid.ooo-1", "status": "delivered", "timestamp": "1700000150",
        }))
        after_delivered = self._get_delivery(delivery_id)
        self.assertEqual(after_delivered.status, "read")
        self.assertIsNotNone(after_delivered.delivered_at)

        # Out-of-order 'sent' arrives after 'read' and 'delivered': status stays 'read'
        self.post_signed(self._status_envelope({
            "id": "wamid.ooo-1", "status": "sent", "timestamp": "1700000100",
        }))
        self.assertEqual(self._get_delivery(delivery_id).status, "read")

        # Out-of-order 'failed' after 'read' must not revert a read message
        self.post_signed(self._status_envelope({
            "id": "wamid.ooo-1", "status": "failed", "timestamp": "1700000250",
        }))
        self.assertEqual(self._get_delivery(delivery_id).status, "read")

        # Also verify 'delivered' never reverts to 'sent'
        delivery2_id = self._seed_delivery("wamid.ooo-2", status="delivered")
        self.post_signed(self._status_envelope({
            "id": "wamid.ooo-2", "status": "sent", "timestamp": "1700000100",
        }))
        self.assertEqual(self._get_delivery(delivery2_id).status, "delivered")

    def test_unknown_provider_message_id_logs_safely_without_exposing_sensitive_data(self):
        secret_phone = "919876543210"
        with self.assertLogs("app.routes.whatsapp_webhook_v2", level="WARNING") as captured:
            response = self.post_signed(self._status_envelope({
                "id": "wamid.unknown-xyz",
                "status": "delivered",
                "timestamp": "1700000300",
                "recipient_id": secret_phone,
            }))
        self.assertEqual(response.status_code, 200)
        joined_logs = "\n".join(captured.output)
        self.assertIn("wamid.unknown-xyz", joined_logs)
        self.assertNotIn(secret_phone, joined_logs)


if __name__ == "__main__":
    unittest.main()
