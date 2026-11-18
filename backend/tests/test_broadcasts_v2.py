from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.broadcast_models import Broadcast, BroadcastRecipient, BroadcastTemplate
from app.database import get_db
from app.execution_models import MessageDelivery, OutboxEvent
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.routes.broadcasts import router as broadcasts_router
from app.services.message_dispatch import ProviderSendResult
from app.vendor_models import ProjectVendor, V2Vendor, V2VendorContact

ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
EMPLOYEE_NO_PHONE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class BroadcastsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2Vendor.__table__, V2VendorContact.__table__, ProjectVendor.__table__, V2AuditEvent.__table__,
            Broadcast.__table__, BroadcastRecipient.__table__, BroadcastTemplate.__table__,
            OutboxEvent.__table__, MessageDelivery.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.project_id = uuid.uuid4()
        self.vendor_id = uuid.uuid4()

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(id=PM_ID, name="Niddhi", email="niddhi@example.com", phone="+919876500001", role=UserRole.project_manager, active=True))
            session.add(User(id=SUPERVISOR_ID, name="Rahul", email="rahul@example.com", phone="+919876500002", role=UserRole.supervisor, active=True))
            session.add(User(id=EMPLOYEE_ID, name="Deepak", email="deepak@example.com", phone="+919876500003", role=UserRole.internal_employee, active=True))
            session.add(User(id=EMPLOYEE_NO_PHONE_ID, name="Amit", email="amit@example.com", phone=None, role=UserRole.internal_employee, active=True))
            session.flush()
            for user_id, code in ((PM_ID, "EMP-PM"), (SUPERVISOR_ID, "EMP-SUP"), (EMPLOYEE_ID, "EMP-1"), (EMPLOYEE_NO_PHONE_ID, "EMP-2")):
                session.add(EmployeeProfile(user_id=user_id, employee_code=code, designation="Staff", availability="available"))
            session.flush()

            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Test Project 1", client_name="Client", site_address="Mumbai",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))
            session.flush()

            pm_employee = session.query(EmployeeProfile).filter_by(user_id=PM_ID).one()
            sup_employee = session.query(EmployeeProfile).filter_by(user_id=SUPERVISOR_ID).one()
            emp1 = session.query(EmployeeProfile).filter_by(user_id=EMPLOYEE_ID).one()
            emp2 = session.query(EmployeeProfile).filter_by(user_id=EMPLOYEE_NO_PHONE_ID).one()
            for employee, role in ((pm_employee, "project_manager"), (sup_employee, "site_supervisor"), (emp1, "internal_employee"), (emp2, "internal_employee")):
                session.add(V2ProjectMembership(
                    project_id=self.project_id, employee_id=employee.id, project_role=role,
                    assigned_by=ADMIN_ID, assignment_reason="Initial assignment.",
                ))

            session.add(V2Vendor(
                id=self.vendor_id, name="ABC Civil Works", contact_person="Vendor Owner", phone="+919876500010",
                whatsapp="+919876500010", email="abc@vendor.example", status="active", engagement_type="main", created_by=ADMIN_ID,
            ))
            session.flush()
            session.add(V2VendorContact(vendor_id=self.vendor_id, name="Suresh", designation="Site Contact", phone="+919876500011", is_primary=True))
            session.add(ProjectVendor(project_id=self.project_id, vendor_id=self.vendor_id, mapped_by=ADMIN_ID))

        self.app = FastAPI()
        self.app.include_router(broadcasts_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as_pm(self):
        self._current_actor = User(id=PM_ID, name="Niddhi", email="niddhi@example.com", role=UserRole.project_manager, active=True)

    # ---- recipient resolution ----------------------------------------

    def test_recipient_counts_and_preview_reflect_project_assignments(self):
        response = self.client.get(f"/api/v2/broadcasts/recipients?project_id={self.project_id}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["counts"], {
            "project_manager": 1, "site_supervisor": 1, "internal_employee": 2, "vendor": 1, "vendor_contact": 1,
        })
        names = {item["name"] for item in body["recipients"]}
        self.assertEqual(names, {"Niddhi", "Rahul", "Deepak", "Amit", "Vendor Owner", "Suresh"})

        amit = next(item for item in body["recipients"] if item["name"] == "Amit")
        self.assertEqual(amit["channels"], ["in_app", "email"])  # no phone -> no whatsapp, but still in-app+email
        niddhi = next(item for item in body["recipients"] if item["name"] == "Niddhi")
        self.assertIn("whatsapp", niddhi["channels"])

    def test_recipient_preview_scoped_to_selected_groups(self):
        response = self.client.get(f"/api/v2/broadcasts/recipients?project_id={self.project_id}&groups=vendor,vendor_contact")
        self.assertEqual(response.status_code, 200, response.text)
        names = {item["name"] for item in response.json()["recipients"]}
        self.assertEqual(names, {"Vendor Owner", "Suresh"})

    # ---- create + send now --------------------------------------------

    def test_send_now_marks_broadcast_sent_and_logs_audit(self):
        response = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id), "title": "Kickoff Meeting", "meeting_date": "2026-08-20",
            "meeting_time": "10:00", "location_or_link": "Site office", "agenda": "Discuss schedule",
            "message_body": "Please join the kickoff meeting.", "recipient_groups": ["project_manager", "site_supervisor", "internal_employee", "vendor", "vendor_contact"],
            "excluded_recipient_keys": [], "send_mode": "now",
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "sent")
        self.assertEqual(body["recipient_count"], 6)
        self.assertEqual(body["delivery_summary"]["sent"], 6)
        self.assertIsNotNone(body["sent_at"])

        with self.Session() as session:
            events = session.query(V2AuditEvent).filter_by(project_id=self.project_id, action="BROADCAST_SENT").all()
            self.assertEqual(len(events), 1)

    def test_excluded_recipient_is_not_persisted(self):
        preview = self.client.get(f"/api/v2/broadcasts/recipients?project_id={self.project_id}").json()
        deepak_key = next(item["key"] for item in preview["recipients"] if item["name"] == "Deepak")

        response = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id), "title": "Update", "message_body": "Body",
            "recipient_groups": ["internal_employee"], "excluded_recipient_keys": [deepak_key], "send_mode": "now",
        })
        body = response.json()
        self.assertEqual(body["recipient_count"], 1)
        self.assertEqual(body["recipients"][0]["name"], "Amit")

    def test_broadcast_with_zero_contactable_recipients_fails(self):
        response = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id), "title": "No-op", "message_body": "Body",
            "recipient_groups": ["internal_employee"],
            "excluded_recipient_keys": [f"internal_employee:{EMPLOYEE_ID}", f"internal_employee:{EMPLOYEE_NO_PHONE_ID}"],
            "send_mode": "now",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "failed")

    # ---- scheduled ------------------------------------------------------

    def test_scheduled_broadcast_stays_pending_until_sent(self):
        scheduled_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        create = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id), "title": "Site Walkthrough", "message_body": "Body",
            "recipient_groups": ["project_manager"], "send_mode": "scheduled", "scheduled_at": scheduled_at,
        })
        self.assertEqual(create.status_code, 200, create.text)
        body = create.json()
        self.assertEqual(body["status"], "scheduled")
        self.assertEqual(body["recipients"][0]["delivery_status"], "pending")

        send = self.client.post(f"/api/v2/broadcasts/{body['id']}/send")
        self.assertEqual(send.status_code, 200, send.text)
        sent_body = send.json()
        self.assertEqual(sent_body["status"], "sent")
        self.assertEqual(sent_body["recipients"][0]["delivery_status"], "sent")

    def test_scheduled_without_scheduled_at_is_rejected(self):
        response = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id), "title": "Bad", "message_body": "Body",
            "recipient_groups": ["project_manager"], "send_mode": "scheduled",
        })
        self.assertEqual(response.status_code, 422, response.text)

    # ---- list / summary / templates --------------------------------------

    def test_summary_and_list_reflect_sent_broadcast(self):
        self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id), "title": "Kickoff", "message_body": "Body",
            "recipient_groups": ["project_manager", "internal_employee"], "send_mode": "now",
        })
        summary = self.client.get("/api/v2/broadcasts/summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        summary_body = summary.json()
        self.assertEqual(summary_body["messages_sent"], 1)
        self.assertEqual(summary_body["total_recipients"], 3)
        self.assertEqual(summary_body["delivery_success_rate"], 100)

        listing = self.client.get("/api/v2/broadcasts")
        self.assertEqual(len(listing.json()), 1)
        self.assertEqual(listing.json()[0]["project_name"], "Test Project 1")

    def test_template_create_and_list(self):
        created = self.client.post("/api/v2/broadcasts/templates", json={
            "name": "Weekly Sync", "title": "Weekly Sync Meeting", "agenda": "Progress review", "message_body": "Join us.",
        })
        self.assertEqual(created.status_code, 200, created.text)
        listing = self.client.get("/api/v2/broadcasts/templates")
        self.assertEqual(len(listing.json()), 1)
        self.assertEqual(listing.json()[0]["name"], "Weekly Sync")

    # ---- access control ---------------------------------------------------

    def test_non_admin_cannot_access_broadcasts(self):
        self.act_as_pm()
        response = self.client.get(f"/api/v2/broadcasts/recipients?project_id={self.project_id}")
        self.assertEqual(response.status_code, 403)

    # ---- Milestone 1 Phase 2: provider integration, failures, retries -----

    def test_send_now_creates_outbox_event_and_message_deliveries(self):
        response = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id),
            "title": "Safety Briefing",
            "message_body": "Mandatory PPE on site.",
            "recipient_groups": ["project_manager", "site_supervisor", "vendor_contact"],
            "excluded_recipient_keys": [],
            "send_mode": "now",
        })
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            outbox_events = list(session.scalars(select(OutboxEvent)).all())
            self.assertEqual(len(outbox_events), 1)
            self.assertEqual(outbox_events[0].event_type, "broadcast.message_dispatched")

            deliveries = list(session.scalars(select(MessageDelivery)).all())
            self.assertEqual(len(deliveries), 3)
            for delivery in deliveries:
                self.assertEqual(delivery.status, "sent")
                self.assertEqual(delivery.channel, "whatsapp")
                self.assertIsNotNone(delivery.provider_message_id)

    def test_provider_failure_marks_recipient_failed_and_broadcast_partially_failed(self):
        class _FailSupervisorAdapter:
            def __init__(self):
                self.calls = []

            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                self.calls.append(recipient_phone)
                if recipient_phone == "+919876500002":  # Supervisor Rahul
                    return ProviderSendResult(ok=False, failure_code="500", failure_reason="Meta API error")
                return ProviderSendResult(ok=True, provider_message_id=f"wamid.{recipient_phone}")

        fake_adapter = _FailSupervisorAdapter()
        with patch("app.services.broadcast_service._default_whatsapp_adapter", return_value=fake_adapter):
            response = self.client.post("/api/v2/broadcasts", json={
                "project_id": str(self.project_id),
                "title": "Urgent Notice",
                "message_body": "Check scaffolding.",
                "recipient_groups": ["project_manager", "site_supervisor"],
                "excluded_recipient_keys": [],
                "send_mode": "now",
            })

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "partially_failed")
        self.assertEqual(body["delivery_summary"]["sent"], 1)
        self.assertEqual(body["delivery_summary"]["failed"], 1)
        by_name = {r["name"]: r for r in body["recipients"]}
        self.assertEqual(by_name["Niddhi"]["delivery_status"], "sent")
        self.assertEqual(by_name["Rahul"]["delivery_status"], "failed")
        self.assertIsNone(by_name["Rahul"]["delivered_at"])

    def test_retry_partially_failed_broadcast_only_resends_failed_recipients_no_duplicates(self):
        calls: list[str] = []

        class _FlakyAdapter:
            def __init__(self, fail_phone: str | None):
                self.fail_phone = fail_phone

            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                calls.append(recipient_phone)
                if self.fail_phone and recipient_phone == self.fail_phone:
                    return ProviderSendResult(ok=False, failure_code="network_error", failure_reason="Timeout")
                return ProviderSendResult(ok=True, provider_message_id=f"wamid.{uuid.uuid4().hex}")

        with patch("app.services.broadcast_service._default_whatsapp_adapter", return_value=_FlakyAdapter("+919876500002")):
            created = self.client.post("/api/v2/broadcasts", json={
                "project_id": str(self.project_id),
                "title": "Retry Test",
                "message_body": "Body",
                "recipient_groups": ["project_manager", "site_supervisor"],
                "excluded_recipient_keys": [],
                "send_mode": "now",
            }).json()

        self.assertEqual(created["status"], "partially_failed")
        self.assertCountEqual(calls, ["+919876500001", "+919876500002"])

        calls.clear()
        with patch("app.services.broadcast_service._default_whatsapp_adapter", return_value=_FlakyAdapter(None)):
            retried = self.client.post(f"/api/v2/broadcasts/{created['id']}/send")

        self.assertEqual(retried.status_code, 200, retried.text)
        retried_body = retried.json()
        self.assertEqual(retried_body["status"], "sent")
        # Niddhi (+919876500001) already succeeded on first pass and must NOT be sent a duplicate message!
        self.assertEqual(calls, ["+919876500002"])

        # Attempting to send an already fully-'sent' broadcast returns 409
        second_retry = self.client.post(f"/api/v2/broadcasts/{created['id']}/send")
        self.assertEqual(second_retry.status_code, 409)

    def test_telegram_recipient_dispatches_via_telegram_adapter(self):
        with self.Session.begin() as session:
            pm_profile = session.query(EmployeeProfile).filter_by(user_id=PM_ID).one()
            pm_profile.active_channel = "telegram"
            pm_profile.telegram_chat_id = "tg-chat-999"

        tg_calls: list[tuple[str, dict]] = []
        wa_calls: list[str] = []

        class _SpyTelegramAdapter:
            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                tg_calls.append((recipient_phone, payload))
                return ProviderSendResult(ok=True, provider_message_id="tg-msg-1")

        class _SpyWhatsAppAdapter:
            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                wa_calls.append(recipient_phone)
                return ProviderSendResult(ok=True, provider_message_id="wa-msg-1")

        with patch("app.services.broadcast_service._default_telegram_adapter", return_value=_SpyTelegramAdapter()), \
             patch("app.services.broadcast_service._default_whatsapp_adapter", return_value=_SpyWhatsAppAdapter()):
            response = self.client.post("/api/v2/broadcasts", json={
                "project_id": str(self.project_id),
                "title": "Channel Routing",
                "message_body": "Check Telegram vs WhatsApp.",
                "recipient_groups": ["project_manager", "site_supervisor"],
                "excluded_recipient_keys": [],
                "send_mode": "now",
            })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(tg_calls), 1)
        self.assertEqual(tg_calls[0][0], "tg-chat-999")
        self.assertIn("Channel Routing", tg_calls[0][1]["text"])
        self.assertEqual(wa_calls, ["+919876500002"])

    def test_telegram_preferred_recipient_without_linked_chat_gets_whatsapp(self):
        # Previously this person was skipped on every channel but still
        # counted as 'sent' via the in-app/email fallback.
        with self.Session.begin() as session:
            pm_profile = session.query(EmployeeProfile).filter_by(user_id=PM_ID).one()
            pm_profile.active_channel = "telegram"
            pm_profile.telegram_chat_id = None

        tg_calls: list[str] = []
        wa_calls: list[str] = []

        class _SpyTelegramAdapter:
            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                tg_calls.append(recipient_phone)
                return ProviderSendResult(ok=True, provider_message_id="tg-msg-1")

        class _SpyWhatsAppAdapter:
            provider_name = "meta"

            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                wa_calls.append(recipient_phone)
                return ProviderSendResult(ok=True, provider_message_id=f"wamid-{len(wa_calls)}")

        with patch("app.services.broadcast_service._default_telegram_adapter", return_value=_SpyTelegramAdapter()), \
             patch("app.services.broadcast_service._default_whatsapp_adapter", return_value=_SpyWhatsAppAdapter()):
            response = self.client.post("/api/v2/broadcasts", json={
                "project_id": str(self.project_id),
                "title": "Channel Fallback",
                "message_body": "Unlinked Telegram falls back to WhatsApp.",
                "recipient_groups": ["project_manager"],
                "excluded_recipient_keys": [],
                "send_mode": "now",
            })

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(tg_calls, [])
        self.assertEqual(len(wa_calls), 1)
        with self.Session() as session:
            [delivery] = session.scalars(select(MessageDelivery)).all()
            self.assertEqual((delivery.channel, delivery.provider, delivery.status), ("whatsapp", "meta", "sent"))

    def test_inactive_user_excluded_from_broadcast_recipients_and_blocked_on_scheduled_send(self):
        # 1. Schedule a broadcast while Supervisor Rahul is active
        scheduled_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        created = self.client.post("/api/v2/broadcasts", json={
            "project_id": str(self.project_id),
            "title": "Offboarded Check",
            "message_body": "Body",
            "recipient_groups": ["project_manager", "site_supervisor"],
            "send_mode": "scheduled",
            "scheduled_at": scheduled_at,
        }).json()
        self.assertEqual(created["recipient_count"], 2)

        # 2. Deactivate Supervisor Rahul before the scheduled broadcast sends
        with self.Session.begin() as session:
            session.get(User, SUPERVISOR_ID).active = False

        # Preview recipients now excludes deactivated Rahul even with active membership row
        preview = self.client.get(f"/api/v2/broadcasts/recipients?project_id={self.project_id}").json()
        preview_names = {r["name"] for r in preview["recipients"]}
        self.assertNotIn("Rahul", preview_names)

        # 3. Sending the already-scheduled broadcast must NOT send to deactivated Rahul
        wa_calls: list[str] = []

        class _SpyWhatsAppAdapter:
            def send(self, recipient_phone: str, template: str, payload: dict) -> ProviderSendResult:
                wa_calls.append(recipient_phone)
                return ProviderSendResult(ok=True, provider_message_id="wa-msg-1")

        with patch("app.services.broadcast_service._default_whatsapp_adapter", return_value=_SpyWhatsAppAdapter()):
            sent = self.client.post(f"/api/v2/broadcasts/{created['id']}/send").json()

        self.assertEqual(wa_calls, ["+919876500001"])  # PM Niddhi only, never Rahul
        by_name = {r["name"]: r for r in sent["recipients"]}
        self.assertEqual(by_name["Niddhi"]["delivery_status"], "sent")
        self.assertEqual(by_name["Rahul"]["delivery_status"], "failed")


if __name__ == "__main__":
    unittest.main()
