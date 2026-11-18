from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import ast
import hashlib
import hmac
import inspect
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

from app.auth import current_user
from app.config import settings
from app.database import get_db
from app.execution_models import (
    BaselineTask,
    FileObject,
    GateEvidenceSession,
    GateEvidenceSessionAttachment,
    InboundMessage,
    OutboxEvent,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalStatusCheck,
    ProjectExternalApprovalSubmission,
    ProjectExternalApprovalTask,
    ProjectGateAcknowledgement,
    Task,
    TaskDependency,
    TaskSupportAssignment,
)
from app.models import EmployeeProfile, User, UserRole
from app.services.project_gate_submission import MAX_EVIDENCE_SIZE_BYTES
from app.services.whatsapp_media import MediaDownloadResult
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
    V2ProjectExternalGateTask,
)
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.projects_v2 import router as projects_router
from app.routes.whatsapp_webhook_v2 import router as whatsapp_webhook_router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    V2VendorContact,
    VendorAcknowledgement,
)
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
INTERNAL_EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
SUPER_ADMIN_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")

SUPERVISOR_PHONE = "+9000000011"
INTERNAL_EMPLOYEE_PHONE = "+9000000012"
ADMIN_PHONE = "+9000000013"
SUPER_ADMIN_PHONE = "+9000000014"
UNKNOWN_PHONE = "+9999999999"
VENDOR_ELECTRICAL_CONTACT_PHONE = "+9100000001"
VENDOR_OTHER_CONTACT_PHONE = "+9100000002"
AMBIGUOUS_PHONE = "+9200000001"

WEBHOOK_SECRET = "test-webhook-secret"
WEBHOOK_VERIFY_TOKEN = "test-verify-token"

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class InboundMessageMatchingApiTests(unittest.TestCase):
    """Phase 2 U6: inbound WhatsApp message matching (R8/R9).

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_vendor_acknowledgement_v2.py / test_task_lifecycle_transitions_v2.py.
    """

    def setUp(self):
        pin_project_creation_today(self)
        # U10: evidence attachments write through the same
        # app.services.evidence_storage module project_gate_submission.py's
        # portal path uses - patched to an in-memory dict, same pattern as
        # test_project_gate_submission_v2.py. download_inbound_media
        # (whatsapp_media.py) is patched at its inbound_message.py import
        # site so a test never makes a real Graph API call; individual
        # tests override `self.mock_download_inbound_media.return_value`
        # for a specific outcome (failure / oversized / mime_type).
        self.evidence_store: dict[str, bytes] = {}
        self._storage_patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, content_type: self.evidence_store.__setitem__(key, data)),
            patch("app.services.evidence_storage.read", side_effect=self.evidence_store.get),
            patch("app.services.evidence_storage.delete", side_effect=lambda key: self.evidence_store.pop(key, None)),
        ]
        for storage_patch in self._storage_patches:
            storage_patch.start()
        self.addCleanup(lambda: [p.stop() for p in self._storage_patches])

        self._download_patch = patch("app.services.inbound_message.download_inbound_media")
        self.mock_download_inbound_media = self._download_patch.start()
        self.mock_download_inbound_media.return_value = MediaDownloadResult(
            ok=True, bytes=TINY_PNG_BYTES, mime_type="image/jpeg",
        )
        self.addCleanup(self._download_patch.stop)

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            V2ProjectExternalGate.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectTaskReferenceFile.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
            ProjectGateAcknowledgement.__table__,
            ProjectExternalApprovalStatusCheck.__table__,
            ProjectExternalApprovalSubmission.__table__,
            ProjectExternalApprovalEvidence.__table__,
            FileObject.__table__,
            GateEvidenceSession.__table__,
            GateEvidenceSessionAttachment.__table__,
            TaskDependency.__table__,
            TaskSupportAssignment.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            V2VendorContact.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
            VendorAcknowledgement.__table__,
            InboundMessage.__table__,
            OutboxEvent.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2ProjectExternalGateTask.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self._original_webhook_secret = settings.whatsapp_webhook_secret
        settings.whatsapp_webhook_secret = WEBHOOK_SECRET
        self._original_verify_token = settings.whatsapp_webhook_verify_token
        settings.whatsapp_webhook_verify_token = WEBHOOK_VERIFY_TOKEN

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(project_vendors_router)
        self.app.include_router(whatsapp_webhook_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self._current_actor = User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True,
        )
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        settings.whatsapp_webhook_secret = self._original_webhook_secret
        settings.whatsapp_webhook_verify_token = self._original_verify_token

    def act_as_admin(self) -> None:
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def act_as_pm(self) -> None:
        self._current_actor = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work/standard, category
        'Electrical'). PM (phone unset), Supervisor (phone
        SUPERVISOR_PHONE). Two vendors, each with one contact: vendor
        'Electrical Co' (contact phone VENDOR_ELECTRICAL_CONTACT_PHONE) and
        vendor 'Other Co' (contact phone VENDOR_OTHER_CONTACT_PHONE) - used
        to prove a vendor contact cannot reference an assignment belonging
        to a different vendor. An OUTSIDER employee and a second vendor
        contact both share AMBIGUOUS_PHONE, to exercise the "matches more
        than one identity" case.
        """
        with self.Session.begin() as session:
            admin = User(
                id=ADMIN_ID, name="Admin", email="admin@example.com",
                role=UserRole.admin, active=True, phone=ADMIN_PHONE,
            )
            super_admin = User(
                id=SUPER_ADMIN_ID, name="Super Admin", email="superadmin@example.com",
                role=UserRole.super_admin, active=True, phone=SUPER_ADMIN_PHONE,
            )
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True, phone=SUPERVISOR_PHONE,
            )
            outsider = User(
                id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
                role=UserRole.supervisor, active=True, phone=AMBIGUOUS_PHONE,
            )
            internal_employee = User(
                id=INTERNAL_EMPLOYEE_ID, name="Internal Employee", email="internal@example.com",
                role=UserRole.internal_employee, active=True, phone=INTERNAL_EMPLOYEE_PHONE,
            )
            session.add_all([admin, super_admin, pm, supervisor, outsider, internal_employee])
            session.flush()
            internal_employee_profile = EmployeeProfile(
                user_id=INTERNAL_EMPLOYEE_ID, employee_code="INT-001", designation="Internal Employee", availability="available",
            )
            session.add_all([
                # U12: KTD11 - every `User` gets an `EmployeeProfile`
                # regardless of role, Admin/Super Admin included, so
                # GATEDECIDE (employee-identity, role-gated) matches them
                # via the same `_match_employees` join every other
                # employee command uses.
                EmployeeProfile(user_id=ADMIN_ID, employee_code="ADM-001", designation="Admin", availability="available"),
                EmployeeProfile(
                    user_id=SUPER_ADMIN_ID, employee_code="SADM-001", designation="Super Admin", availability="available",
                ),
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
                ),
                internal_employee_profile,
            ])
            session.flush()
            self.internal_employee_profile_id = internal_employee_profile.id
            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id, version_no=1, status="published", duration_days=45,
                content_hash="published-hash", is_current_published=True,
                created_by=ADMIN_ID, published_by=ADMIN_ID, published_at=datetime.now(timezone.utc),
            )
            session.add(published)
            session.flush()
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", task_class="standard", task_kind="work",
                evidence_required=False, duration_days=1, phase="Electrical", category="Wiring",
            ))
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            session.add(electrical)
            session.flush()

            vendor_electrical = V2Vendor(
                id=uuid.uuid4(), name="Electrical Co", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            vendor_other = V2Vendor(
                id=uuid.uuid4(), name="Other Co", contact_person="Sunil", phone="9000000002",
                status="active", engagement_type="main",
            )
            session.add_all([vendor_electrical, vendor_other])
            session.flush()
            session.add(V2VendorCapability(vendor_id=vendor_electrical.id, category_id=electrical.id))
            self.vendor_electrical_id = vendor_electrical.id
            self.vendor_other_id = vendor_other.id

            vendor_electrical_contact = V2VendorContact(
                vendor_id=vendor_electrical.id, name="Ravi", phone=VENDOR_ELECTRICAL_CONTACT_PHONE, is_primary=True,
            )
            vendor_other_contact = V2VendorContact(
                vendor_id=vendor_other.id, name="Sunil", phone=VENDOR_OTHER_CONTACT_PHONE, is_primary=True,
            )
            # A second vendor contact sharing AMBIGUOUS_PHONE with the
            # OUTSIDER employee above - proves cross-table ambiguity is
            # detected, not just same-table duplicate matches.
            ambiguous_vendor_contact = V2VendorContact(
                vendor_id=vendor_other.id, name="Ambiguous", phone=AMBIGUOUS_PHONE, is_primary=False,
            )
            session.add_all([vendor_electrical_contact, vendor_other_contact, ambiguous_vendor_contact])

    def create_draft(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            "proposed_start_date": "2026-08-01",
            "target_handover_date": "2026-09-14",
            "pm_user_id": str(PM_ID),
            "supervisor_user_id": str(SUPERVISOR_ID),
            "template_version_id": str(self.published_version_id),
        }
        payload.update(overrides)
        self.act_as_admin()
        response = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def activate_project(self) -> dict:
        project = self.create_draft()
        response = self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/generate-dependencies")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200, response.text)
        return project

    def task_by_code(self, project_id: str, code: str) -> Task:
        with self.Session() as session:
            return session.scalar(
                select(Task).where(Task.project_id == uuid.UUID(project_id), Task.original_code == code)
            )

    def map_and_assign_vendor(self, project_id, task_id, vendor_id) -> str:
        self.act_as_pm()
        map_response = self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)},
        )
        self.assertEqual(map_response.status_code, 200, map_response.text)
        assign_response = self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment",
            json={"vendor_id": str(vendor_id)},
        )
        self.assertEqual(assign_response.status_code, 200, assign_response.text)
        return assign_response.json()["id"]

    def assignment_ref(self, assignment_id: str) -> str:
        return assignment_id.replace("-", "")[:8]

    def make_gate_approval(self, project_id: str, *, assigned_to_user_id, sequence: int = 1) -> ProjectExternalApproval:
        """U6: seeds a `V2ProjectExternalGate` + its runtime
        `ProjectExternalApproval` directly (the WORKVED-45 template used by
        this test class defines no external gates), mirroring
        `test_project_gate_acknowledgement_v2.py`'s own `make_approval`
        helper."""
        with self.Session.begin() as session:
            gate = V2ProjectExternalGate(
                id=uuid.uuid4(), project_id=uuid.UUID(project_id),
                original_code=f"E{sequence:03d}", template_sequence=sequence,
                approval_name=f"Fire NOC {sequence}", mapping_classification="exact",
                applicability_state="applicable", blocking=True,
                accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            approval = ProjectExternalApproval(
                id=uuid.uuid4(), project_id=gate.project_id, project_gate_id=gate.id,
                status="assigned", assigned_to_user_id=assigned_to_user_id,
                assigned_by=PM_ID, assigned_at=datetime.now(timezone.utc),
            )
            session.add(approval)
            session.flush()
            approval_id = approval.id
        with self.Session() as session:
            return session.get(ProjectExternalApproval, approval_id)

    def set_approval_submitted(self, approval_id) -> ProjectExternalApproval:
        """U12: `ProjectGateDecisionService.decide` only accepts a
        `submitted` gate - moves a `make_gate_approval`-seeded row there
        directly (bypassing the full GATEOPEN/GATECLOSE evidence flow,
        which is not what these decide()-focused tests are exercising)."""
        with self.Session.begin() as session:
            approval = session.get(ProjectExternalApproval, approval_id)
            approval.status = "submitted"
        with self.Session() as session:
            return session.get(ProjectExternalApproval, approval_id)

    # ---- webhook helpers -------------------------------------------------

    def post_inbound(self, payload: dict, secret: str | None = None, header: str | None = ...):
        """Wraps the test's logical {provider_message_id, sender_phone,
        message_text} into Meta's real webhook envelope shape - `from`
        carries no leading `+` (Meta's own convention), mirroring what
        `whatsapp_webhook_v2.py` actually receives in production; the route
        itself is responsible for re-adding `+` to match stored E.164
        numbers."""
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "test-waba-id",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "test-phone-number-id"},
                        "messages": [{
                            "from": payload["sender_phone"].lstrip("+"),
                            "id": payload["provider_message_id"],
                            "timestamp": "1700000000",
                            "type": "text",
                            "text": {"body": payload["message_text"]},
                        }],
                    },
                }],
            }],
        }
        raw_body = json.dumps(envelope).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if header is ...:
            signing_secret = secret if secret is not None else WEBHOOK_SECRET
            digest = hmac.new(signing_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            headers["X-Hub-Signature-256"] = f"sha256={digest}"
        elif header is not None:
            headers["X-Hub-Signature-256"] = header
        return self.client.post("/api/v2/whatsapp/inbound", content=raw_body, headers=headers)

    def post_inbound_image(
        self, provider_message_id: str, sender_phone: str, media_id: str = "media-id-1",
        mime_type: str = "image/jpeg",
    ):
        """U10: an `"image"` inbound message - `_extract_media_metadata`
        pulls its `id`/`mime_type` out of the message payload itself (Meta
        really does include a top-level `mime_type` on the message's
        `image`/`document` object, ahead of the later media-lookup call
        that also returns one)."""
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "test-waba-id",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "test-phone-number-id"},
                        "messages": [{
                            "from": sender_phone.lstrip("+"),
                            "id": provider_message_id,
                            "timestamp": "1700000000",
                            "type": "image",
                            "image": {"id": media_id, "mime_type": mime_type},
                        }],
                    },
                }],
            }],
        }
        raw_body = json.dumps(envelope).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
        )

    def open_gate_session(self, approval: ProjectExternalApproval, actor_id) -> GateEvidenceSession:
        with self.Session.begin() as session:
            gate_session = GateEvidenceSession(approval_id=approval.id, employee_id=actor_id)
            session.add(gate_session)
            session.flush()
            gate_session_id = gate_session.id
        with self.Session() as session:
            return session.get(GateEvidenceSession, gate_session_id)

    def gate_session_rows(self) -> list[GateEvidenceSession]:
        with self.Session() as session:
            return list(session.scalars(select(GateEvidenceSession)).all())

    def gate_session_attachment_rows(self) -> list[GateEvidenceSessionAttachment]:
        with self.Session() as session:
            return list(session.scalars(select(GateEvidenceSessionAttachment)).all())

    def file_object_rows(self) -> list[FileObject]:
        with self.Session() as session:
            return list(session.scalars(select(FileObject)).all())

    def submission_rows(self) -> list[ProjectExternalApprovalSubmission]:
        with self.Session() as session:
            return list(session.scalars(select(ProjectExternalApprovalSubmission)).all())

    def inbound_rows(self) -> list[InboundMessage]:
        with self.Session() as session:
            return list(session.scalars(select(InboundMessage)).all())

    def acknowledgement_rows(self) -> list[VendorAcknowledgement]:
        with self.Session() as session:
            return list(session.scalars(select(VendorAcknowledgement)).all())

    def gate_acknowledgement_rows(self) -> list[ProjectGateAcknowledgement]:
        with self.Session() as session:
            return list(session.scalars(select(ProjectGateAcknowledgement)).all())

    def outbox_rows(self) -> list[OutboxEvent]:
        with self.Session() as session:
            return list(session.scalars(select(OutboxEvent)).all())

    def gate_status_check_rows(self) -> list[ProjectExternalApprovalStatusCheck]:
        with self.Session() as session:
            return list(session.scalars(select(ProjectExternalApprovalStatusCheck)).all())

    # ---- happy paths ------------------------------------------------------

    def test_vendor_contact_accept_produces_identical_acknowledgement_row(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        response = self.post_inbound({
            "provider_message_id": "wamid.accept-1",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"ACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "processed")
        self.assertEqual(rows[0].matched_identity_type, "vendor_contact")

        acks = self.acknowledgement_rows()
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0].task_vendor_assignment_id, uuid.UUID(assignment_id))
        self.assertEqual(acks[0].response, "accepted")
        self.assertEqual(acks[0].channel, "whatsapp")
        # Same downstream state VendorAcknowledgementService always
        # produces on 'accepted': the parent assignment resolves.
        with self.Session() as session:
            assignment = session.get(TaskVendorAssignment, uuid.UUID(assignment_id))
            self.assertEqual(assignment.status, "acknowledged")

    def test_status_cancel_is_refused_on_whatsapp_even_for_an_admin(self):
        """Telegram task plan U3: cancellation needs a real typed reason and
        stays in the Web App for every messaging channel - the typed command
        used to supply "Reported via WhatsApp." as that reason."""
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        response = self.post_inbound({
            "provider_message_id": "wamid.cancel-1",
            "sender_phone": ADMIN_PHONE,
            "message_text": f"STATUS {task.original_code} cancelled",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "Cancellation is only available in the Web App.")
        with self.Session() as session:
            self.assertEqual(session.get(Task, task.id).lifecycle_status, "planned")

    def test_employee_status_transition_produces_identical_lifecycle_change(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(task.lifecycle_status, "planned")

        response = self.post_inbound({
            "provider_message_id": "wamid.status-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)
        self.assertEqual(rows[0].matched_identity_type, "employee")

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "ready")
            audit_rows = session.scalars(
                select(V2AuditEvent).where(V2AuditEvent.entity_id == task.id)
            ).all()
            self.assertTrue(any(row.action == "TASK_STATUS_CHANGED" for row in audit_rows))
            outbox_rows = session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id)
            ).all()
            self.assertTrue(len(outbox_rows) >= 1)

    def test_internal_employee_support_assigned_can_drive_status_command(self):
        """Phase 1b: `_STATUS_DRIVING_ROLES` now includes `internal_employee`
        - brings the WhatsApp STATUS path in line with what
        `TaskLifecycleService._require_role_for_transition` already permits
        on the portal: an Internal Employee actively support-assigned to a
        task may drive its `in_progress`/`submitted` transitions."""
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        # Move the task to 'ready' first (Supervisor-driven) so
        # 'in_progress' - an executor-driven target - is a legal next step.
        ready_response = self.post_inbound({
            "provider_message_id": "wamid.pre-ready",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(ready_response.status_code, 200, ready_response.text)

        with self.Session.begin() as session:
            session.add(V2ProjectMembership(
                project_id=uuid.UUID(project["id"]), employee_id=self.internal_employee_profile_id,
                project_role="internal_employee", assigned_by=PM_ID, assignment_reason="seed",
            ))
            session.add(TaskSupportAssignment(
                task_id=task.id, project_id=uuid.UUID(project["id"]), employee_id=self.internal_employee_profile_id,
                responsibility="Executes the work.", status="active", assigned_by=PM_ID,
            ))

        response = self.post_inbound({
            "provider_message_id": "wamid.internal-status-1",
            "sender_phone": INTERNAL_EMPLOYEE_PHONE,
            "message_text": f"STATUS {task.original_code} in_progress",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        latest = rows[-1]
        self.assertEqual(latest.processing_status, "processed", latest.rejection_reason)
        self.assertEqual(latest.matched_identity_type, "employee")

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "in_progress")

    def test_status_ignores_same_task_code_in_archived_project(self):
        # Every project carries the template's codes, so lingering membership
        # in an archived project must not make the live project's code ambiguous.
        old_project = self.activate_project()
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(old_project["id"])).status = "archived"
        live_project = self.activate_project()
        live_task = self.task_by_code(live_project["id"], "T001")
        old_task = self.task_by_code(old_project["id"], "T001")

        response = self.post_inbound({
            "provider_message_id": "wamid.status-archived-dup",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "STATUS T001 ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        latest = self.inbound_rows()[-1]
        self.assertEqual(latest.processing_status, "processed", latest.rejection_reason)
        with self.Session() as session:
            self.assertEqual(session.get(Task, live_task.id).lifecycle_status, "ready")
            self.assertEqual(session.get(Task, old_task.id).lifecycle_status, "planned")

    # ---- the signature gate -----------------------------------------------

    def test_missing_signature_rejected_before_any_db_write(self):
        response = self.post_inbound(
            {
                "provider_message_id": "wamid.no-sig",
                "sender_phone": SUPERVISOR_PHONE,
                "message_text": "STATUS T001 ready",
            },
            header=None,
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.inbound_rows(), [])

    def test_invalid_signature_rejected_before_any_db_write(self):
        response = self.post_inbound(
            {
                "provider_message_id": "wamid.bad-sig",
                "sender_phone": SUPERVISOR_PHONE,
                "message_text": "STATUS T001 ready",
            },
            header="sha256=" + ("0" * 64),
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.inbound_rows(), [])

    def test_signature_computed_with_wrong_secret_rejected(self):
        response = self.post_inbound(
            {
                "provider_message_id": "wamid.wrong-secret",
                "sender_phone": SUPERVISOR_PHONE,
                "message_text": "STATUS T001 ready",
            },
            secret="not-the-real-secret",
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.inbound_rows(), [])

    # ---- the verification handshake (GET) ----------------------------------

    def test_webhook_verification_echoes_challenge_on_matching_token(self):
        response = self.client.get(
            "/api/v2/whatsapp/inbound",
            params={"hub.mode": "subscribe", "hub.verify_token": WEBHOOK_VERIFY_TOKEN, "hub.challenge": "12345"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.text, "12345")

    def test_webhook_verification_rejects_wrong_token(self):
        response = self.client.get(
            "/api/v2/whatsapp/inbound",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong-token", "hub.challenge": "12345"},
        )
        self.assertEqual(response.status_code, 403)

    def test_webhook_verification_rejects_non_subscribe_mode(self):
        response = self.client.get(
            "/api/v2/whatsapp/inbound",
            params={"hub.mode": "unsubscribe", "hub.verify_token": WEBHOOK_VERIFY_TOKEN, "hub.challenge": "12345"},
        )
        self.assertEqual(response.status_code, 403)

    # ---- real Meta envelope edge cases --------------------------------------

    def test_status_only_delivery_receipt_is_a_no_op(self):
        """A `changes[].value` carrying `statuses` (a delivery/read receipt)
        instead of `messages` is not an inbound message - accepted with 200,
        no `InboundMessage` row written, per the module docstring."""
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "test-waba-id",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "test-phone-number-id"},
                        "statuses": [{"id": "wamid.status-1", "status": "delivered"}],
                    },
                }],
            }],
        }
        raw_body = json.dumps(envelope).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows(), [])

    def test_multiple_messages_in_one_delivery_are_all_processed(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "test-waba-id",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "test-phone-number-id"},
                        "messages": [
                            {
                                "from": SUPERVISOR_PHONE.lstrip("+"),
                                "id": "wamid.batch-1",
                                "timestamp": "1700000000",
                                "type": "text",
                                "text": {"body": f"STATUS {task.original_code} ready"},
                            },
                            {
                                "from": UNKNOWN_PHONE.lstrip("+"),
                                "id": "wamid.batch-2",
                                "timestamp": "1700000001",
                                "type": "text",
                                "text": {"body": "STATUS T001 ready"},
                            },
                        ],
                    },
                }],
            }],
        }
        raw_body = json.dumps(envelope).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
        )
        self.assertEqual(response.status_code, 200, response.text)

        rows = {row.provider_message_id: row for row in self.inbound_rows()}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows["wamid.batch-1"].processing_status, "processed", rows["wamid.batch-1"].rejection_reason)
        self.assertEqual(rows["wamid.batch-2"].processing_status, "unmatched")

    def test_non_text_message_type_is_rejected_not_crashed(self):
        """A message type that is neither `text` nor an image/document
        attachment (location, reaction, etc.) carries no `.text.body` -
        `message_text` falls back to `""`, and `_extract_media_metadata`
        returns `None` for it too - genuinely empty, so
        `InboundMessageService` rejects it as "Unrecognized command" rather
        than this route raising on a missing field. (An `"image"`/
        `"document"` message is NOT "empty" in this sense - see U10's
        session-fallback-routing tests in test_inbound_message_matching_v2.py's
        evidence-session section below.)"""
        envelope = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "test-waba-id",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "test-phone-number-id"},
                        "messages": [{
                            "from": SUPERVISOR_PHONE.lstrip("+"),
                            "id": "wamid.location-1",
                            "timestamp": "1700000000",
                            "type": "location",
                            "location": {"latitude": 12.9, "longitude": 77.6},
                        }],
                    },
                }],
            }],
        }
        raw_body = json.dumps(envelope).encode("utf-8")
        digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/api/v2/whatsapp/inbound",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
        )
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "Unrecognized command.")

    # ---- identity-matching edge cases --------------------------------------

    def test_unrecognized_phone_number_is_unmatched_with_no_state_mutation(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        response = self.post_inbound({
            "provider_message_id": "wamid.unknown-phone",
            "sender_phone": UNKNOWN_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "unmatched")
        self.assertIsNone(rows[0].matched_identity_type)
        self.assertEqual(rows[0].rejection_reason, "No identity matched this phone number.")

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "planned")

    def test_phone_matching_multiple_identities_is_unmatched_never_auto_resolved(self):
        response = self.post_inbound({
            "provider_message_id": "wamid.ambiguous",
            "sender_phone": AMBIGUOUS_PHONE,
            "message_text": "STATUS T001 ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "unmatched")
        self.assertIsNone(rows[0].matched_identity_type)
        self.assertIsNone(rows[0].matched_identity_id)
        self.assertIn("more than one identity", rows[0].rejection_reason)

    def test_vendor_contact_referencing_other_vendors_assignment_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        response = self.post_inbound({
            "provider_message_id": "wamid.wrong-vendor",
            "sender_phone": VENDOR_OTHER_CONTACT_PHONE,
            "message_text": f"ACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This assignment does not belong to your vendor.")
        self.assertEqual(self.acknowledgement_rows(), [])

        with self.Session() as session:
            assignment = session.get(TaskVendorAssignment, uuid.UUID(assignment_id))
            self.assertEqual(assignment.status, "pending_ack")

    # ---- identity-type command scoping (BR-015) ----------------------------

    def test_vendor_contact_sending_employee_only_command_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        response = self.post_inbound({
            "provider_message_id": "wamid.vendor-status",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"STATUS {task.original_code} ready",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "planned")

    def test_employee_sending_vendor_only_command_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        response = self.post_inbound({
            "provider_message_id": "wamid.employee-accept",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"ACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        self.assertEqual(self.acknowledgement_rows(), [])

    # ---- gate acknowledgement commands (U6) --------------------------------

    def test_assignee_gateaccept_produces_identical_acknowledgement_row(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gateaccept-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)
        self.assertEqual(rows[0].matched_identity_type, "employee")

        acks = self.gate_acknowledgement_rows()
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0].approval_id, approval.id)
        self.assertEqual(acks[0].response, "accepted")
        self.assertEqual(acks[0].recorded_by, SUPERVISOR_ID)

    def test_assignee_gatedecline_produces_identical_acknowledgement_row(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatedecline-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEDECLINE {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)

        acks = self.gate_acknowledgement_rows()
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0].response, "declined")

    def test_non_assignee_employee_gateaccept_is_rejected(self):
        """The Internal Employee is a real member of this project (so the
        service's access check passes) but is not the specific assignee -
        `ProjectGateAcknowledgementService._require_assignee` (U5) rejects
        it, with no acknowledgement row ever created."""
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        with self.Session.begin() as session:
            session.add(V2ProjectMembership(
                project_id=uuid.UUID(project["id"]), employee_id=self.internal_employee_profile_id,
                project_role="internal_employee", assigned_by=PM_ID, assignment_reason="seed",
            ))

        response = self.post_inbound({
            "provider_message_id": "wamid.gateaccept-non-assignee",
            "sender_phone": INTERNAL_EMPLOYEE_PHONE,
            "message_text": f"GATEACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(
            rows[0].rejection_reason,
            "Only the employee this external approval is assigned to can record an acknowledgement for it.",
        )
        self.assertEqual(self.gate_acknowledgement_rows(), [])

    def test_gateaccept_unresolvable_ref_is_rejected(self):
        project = self.activate_project()
        self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)

        response = self.post_inbound({
            "provider_message_id": "wamid.gateaccept-bad-ref",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "GATEACCEPT ffffffff",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "No unique assignment matched this reference.")
        self.assertEqual(self.gate_acknowledgement_rows(), [])

    def test_vendor_contact_sending_gateaccept_is_rejected(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.vendor-gateaccept",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"GATEACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        self.assertEqual(self.gate_acknowledgement_rows(), [])

    # ---- gate status-check commands (U7) -----------------------------------

    def test_assignee_gatestatus_on_track_no_note_records_status_check(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatestatus-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATESTATUS {ref} on_track",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)
        self.assertEqual(rows[0].matched_identity_type, "employee")

        checks = self.gate_status_check_rows()
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].approval_id, approval.id)
        self.assertEqual(checks[0].health, "on_track")
        self.assertIsNone(checks[0].note)
        self.assertEqual(checks[0].recorded_by, SUPERVISOR_ID)

    def test_assignee_gatestatus_blocked_with_note_records_health_and_note(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatestatus-2",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATESTATUS {ref} blocked waiting on society signature",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)

        checks = self.gate_status_check_rows()
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].health, "blocked")
        self.assertEqual(checks[0].note, "waiting on society signature")

    def test_gatestatus_invalid_health_is_rejected_no_row_created(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatestatus-invalid",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATESTATUS {ref} stuck",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "Unknown external-approval status-check health.")
        self.assertEqual(self.gate_status_check_rows(), [])

    def test_non_assignee_employee_gatestatus_is_rejected(self):
        """Mirrors `test_non_assignee_employee_gateaccept_is_rejected`: the
        Internal Employee is a real project member (the service's own
        access check passes) but is not the specific assignee -
        `ProjectGateStatusCheckService._require_assignee` rejects it, with
        no status-check row ever created. No new inbound-layer logic is
        involved - this is the service's existing check firing unchanged."""
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        with self.Session.begin() as session:
            session.add(V2ProjectMembership(
                project_id=uuid.UUID(project["id"]), employee_id=self.internal_employee_profile_id,
                project_role="internal_employee", assigned_by=PM_ID, assignment_reason="seed",
            ))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatestatus-non-assignee",
            "sender_phone": INTERNAL_EMPLOYEE_PHONE,
            "message_text": f"GATESTATUS {ref} on_track",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(
            rows[0].rejection_reason,
            "Only the employee this external approval is assigned to can record a status check for it.",
        )
        self.assertEqual(self.gate_status_check_rows(), [])

    def test_vendor_contact_sending_gatestatus_is_rejected(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.vendor-gatestatus",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"GATESTATUS {ref} on_track",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        self.assertEqual(self.gate_status_check_rows(), [])

    # ---- evidence session commands (U10) -----------------------------------

    def test_gateopen_against_assigned_gate_creates_session(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gateopen-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEOPEN {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)
        self.assertEqual(rows[0].matched_identity_type, "employee")

        sessions = self.gate_session_rows()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].approval_id, approval.id)
        self.assertEqual(sessions[0].employee_id, SUPERVISOR_ID)
        self.assertIsNone(sessions[0].closed_at)
        self.assertIsNone(sessions[0].expired_at)

    def test_gateclose_with_accumulated_evidence_finalizes_submission(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        gate_session = self.open_gate_session(approval, SUPERVISOR_ID)

        note_response = self.post_inbound({
            "provider_message_id": "wamid.gateclose-note",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "Fire NOC obtained from society office.",
        })
        self.assertEqual(note_response.status_code, 200, note_response.text)

        close_response = self.post_inbound({
            "provider_message_id": "wamid.gateclose-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "GATECLOSE all done",
        })
        self.assertEqual(close_response.status_code, 200, close_response.text)

        rows = {row.provider_message_id: row for row in self.inbound_rows()}
        self.assertEqual(
            rows["wamid.gateclose-note"].processing_status, "processed", rows["wamid.gateclose-note"].rejection_reason,
        )
        self.assertEqual(
            rows["wamid.gateclose-1"].processing_status, "processed", rows["wamid.gateclose-1"].rejection_reason,
        )

        submissions = self.submission_rows()
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0].note, "Fire NOC obtained from society office.\nall done")

        with self.Session() as session:
            refreshed_session = session.get(GateEvidenceSession, gate_session.id)
            self.assertIsNotNone(refreshed_session.closed_at)
            refreshed_approval = session.get(ProjectExternalApproval, approval.id)
            self.assertEqual(refreshed_approval.status, "submitted")

    def test_gateclose_with_no_open_session_is_rejected(self):
        project = self.activate_project()
        self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)

        response = self.post_inbound({
            "provider_message_id": "wamid.gateclose-no-session",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "GATECLOSE",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "You have no open evidence session to close.")
        self.assertEqual(self.submission_rows(), [])

    def test_plain_text_with_open_session_appends_to_note(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        gate_session = self.open_gate_session(approval, SUPERVISOR_ID)

        response = self.post_inbound({
            "provider_message_id": "wamid.session-text-1",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "society signed off this morning",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)

        with self.Session() as session:
            refreshed_session = session.get(GateEvidenceSession, gate_session.id)
            self.assertEqual(refreshed_session.note, "society signed off this morning")
            self.assertIsNone(refreshed_session.closed_at)

    def test_image_attachment_with_open_session_is_downloaded_stored_and_linked(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        gate_session = self.open_gate_session(approval, SUPERVISOR_ID)

        response = self.post_inbound_image("wamid.session-image-1", SUPERVISOR_PHONE, media_id="media-abc")
        self.assertEqual(response.status_code, 200, response.text)
        self.mock_download_inbound_media.assert_called_once_with("media-abc")

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)

        file_objects = self.file_object_rows()
        self.assertEqual(len(file_objects), 1)
        self.assertEqual(file_objects[0].mime_type, "image/jpeg")
        self.assertEqual(file_objects[0].size_bytes, len(TINY_PNG_BYTES))
        self.assertTrue(file_objects[0].storage_key.startswith(f"{approval.id}-"))
        self.assertEqual(self.evidence_store[file_objects[0].storage_key], TINY_PNG_BYTES)

        attachments = self.gate_session_attachment_rows()
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].session_id, gate_session.id)
        self.assertEqual(attachments[0].file_id, file_objects[0].id)

    def test_oversized_attachment_is_rejected_distinct_reason_no_file_object(self):
        """Covers KTD18: an oversized download is discarded, never written
        to storage or turned into a `FileObject`, and reported with a
        rejection reason distinct from an unsupported-mime-type or a
        download-failure rejection."""
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.open_gate_session(approval, SUPERVISOR_ID)

        oversized_bytes = b"x" * (MAX_EVIDENCE_SIZE_BYTES + 1)
        self.mock_download_inbound_media.return_value = MediaDownloadResult(
            ok=True, bytes=oversized_bytes, mime_type="image/jpeg",
        )

        response = self.post_inbound_image("wamid.session-image-big", SUPERVISOR_PHONE, media_id="media-big")
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "Attachment is too large; evidence must be 10 MB or smaller.")
        self.assertEqual(self.file_object_rows(), [])
        self.assertEqual(self.gate_session_attachment_rows(), [])

    def test_unsupported_mime_type_attachment_is_rejected_without_download(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.open_gate_session(approval, SUPERVISOR_ID)

        response = self.post_inbound_image(
            "wamid.session-image-bad-mime", SUPERVISOR_PHONE, media_id="media-zip", mime_type="application/zip",
        )
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "Unsupported attachment type; evidence must be JPG, PNG, WebP, or PDF.")
        self.mock_download_inbound_media.assert_not_called()
        self.assertEqual(self.file_object_rows(), [])

    def test_image_attachment_with_no_open_session_is_rejected_even_if_mime_supported(self):
        project = self.activate_project()
        self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)

        response = self.post_inbound_image("wamid.no-session-image", SUPERVISOR_PHONE, media_id="media-fine")
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "You have no open evidence session. Send GATEOPEN <ref> first.")
        self.mock_download_inbound_media.assert_not_called()
        self.assertEqual(self.file_object_rows(), [])

    def test_vendor_contact_sending_gateopen_is_rejected(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.vendor-gateopen",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"GATEOPEN {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        self.assertEqual(self.gate_session_rows(), [])

    # ---- gate decision commands (U12) --------------------------------------

    def test_admin_gatedecide_approve_approves_submitted_gate(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.set_approval_submitted(approval.id)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatedecide-approve",
            "sender_phone": ADMIN_PHONE,
            "message_text": f"GATEDECIDE {ref} APPROVE",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)
        self.assertEqual(rows[0].matched_identity_type, "employee")

        with self.Session() as session:
            refreshed = session.get(ProjectExternalApproval, approval.id)
            self.assertEqual(refreshed.status, "approved")
            self.assertEqual(refreshed.decided_by, ADMIN_ID)
            self.assertIsNotNone(refreshed.decided_at)

    def test_super_admin_gatedecide_reject_records_reason_and_reopens(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.set_approval_submitted(approval.id)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatedecide-reject",
            "sender_phone": SUPER_ADMIN_PHONE,
            "message_text": f"GATEDECIDE {ref} REJECT missing society NOC",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "processed", rows[0].rejection_reason)

        with self.Session() as session:
            refreshed = session.get(ProjectExternalApproval, approval.id)
            # ProjectGateDecisionService.decide's own two-step reject-then-
            # reopen transition (see that module's docstring): the gate ends
            # up back at 'assigned' with decided_by/decided_at reset to
            # null, but rejection_reason survives the reset.
            self.assertEqual(refreshed.status, "assigned")
            self.assertIsNone(refreshed.decided_by)
            self.assertIsNone(refreshed.decided_at)
            self.assertEqual(refreshed.rejection_reason, "missing society NOC")

    def test_non_admin_employee_gatedecide_is_rejected_before_service_called(self):
        """The role gate fires FIRST, before the <ref> is even resolved -
        a distinct rejection reason from BR-015's cross-identity wording,
        and the approval/decision state is untouched."""
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.set_approval_submitted(approval.id)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.gatedecide-non-admin",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEDECIDE {ref} APPROVE",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your role.")

        with self.Session() as session:
            refreshed = session.get(ProjectExternalApproval, approval.id)
            self.assertEqual(refreshed.status, "submitted")
            self.assertIsNone(refreshed.decided_by)
            self.assertIsNone(refreshed.decided_at)
            self.assertEqual(
                session.scalars(
                    select(ProjectExternalApprovalSubmission).where(
                        ProjectExternalApprovalSubmission.approval_id == approval.id
                    )
                ).all(),
                [],
            )

    def test_gatedecide_against_non_submitted_gate_is_rejected_by_service(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))  # still 'assigned', never submitted

        response = self.post_inbound({
            "provider_message_id": "wamid.gatedecide-not-submitted",
            "sender_phone": ADMIN_PHONE,
            "message_text": f"GATEDECIDE {ref} APPROVE",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(
            rows[0].rejection_reason,
            "This external approval is assigned; only a submitted gate can be decided.",
        )
        with self.Session() as session:
            refreshed = session.get(ProjectExternalApproval, approval.id)
            self.assertEqual(refreshed.status, "assigned")
            self.assertIsNone(refreshed.decided_by)

    def test_vendor_contact_sending_gatedecide_is_rejected(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.set_approval_submitted(approval.id)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.vendor-gatedecide",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"GATEDECIDE {ref} APPROVE",
        })
        self.assertEqual(response.status_code, 200, response.text)

        rows = self.inbound_rows()
        self.assertEqual(rows[0].processing_status, "rejected")
        self.assertEqual(rows[0].rejection_reason, "This command is not available for your identity type.")
        with self.Session() as session:
            refreshed = session.get(ProjectExternalApproval, approval.id)
            self.assertEqual(refreshed.status, "submitted")
            self.assertIsNone(refreshed.decided_by)

    # ---- gate command WhatsApp confirmations (U15) -------------------------

    def confirmation_events(self, event_type: str) -> list[OutboxEvent]:
        return [row for row in self.outbox_rows() if row.event_type == event_type]

    def test_gateaccept_emits_accepted_confirmation_to_sender(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-gateaccept",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "processed")

        events = self.confirmation_events("gate_confirmation.accepted")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].aggregate_type, "gate_command_confirmation")
        self.assertEqual(events[0].aggregate_id, approval.id)
        self.assertEqual(events[0].payload["actor_user_id"], str(SUPERVISOR_ID))
        self.assertEqual(events[0].payload["gate_name"], "Fire NOC 1")
        with self.Session() as session:
            db_project = session.get(V2Project, uuid.UUID(project["id"]))
            self.assertEqual(events[0].payload["project_name"], db_project.name)

    def test_gatedecline_emits_declined_confirmation_to_sender(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-gatedecline",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEDECLINE {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "processed")

        events = self.confirmation_events("gate_confirmation.declined")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["actor_user_id"], str(SUPERVISOR_ID))

    def test_gatestatus_emits_status_recorded_confirmation_with_health(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-gatestatus",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATESTATUS {ref} blocked awaiting signature",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "processed")

        events = self.confirmation_events("gate_confirmation.status_recorded")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["health"], "blocked")
        self.assertEqual(events[0].payload["actor_user_id"], str(SUPERVISOR_ID))

    def test_gateopen_emits_session_opened_confirmation(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-gateopen",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATEOPEN {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "processed")

        events = self.confirmation_events("gate_confirmation.session_opened")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["actor_user_id"], str(SUPERVISOR_ID))

    def test_gateclose_emits_session_closed_confirmation(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.open_gate_session(approval, SUPERVISOR_ID)

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-gateclose",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": "GATECLOSE all done",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "processed")

        events = self.confirmation_events("gate_confirmation.session_closed")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["actor_user_id"], str(SUPERVISOR_ID))

    def test_gatedecide_emits_decided_confirmation_with_decision_to_admin(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        self.set_approval_submitted(approval.id)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-gatedecide",
            "sender_phone": ADMIN_PHONE,
            "message_text": f"GATEDECIDE {ref} APPROVE",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "processed")

        events = self.confirmation_events("gate_confirmation.decided")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["decision"], "approved")
        # Resolved to the deciding Admin themselves, not the gate's assignee
        # (SUPERVISOR_ID) - this is the sender-facing confirmation, distinct
        # from U5's Admin-facing project_external_approval.* events.
        self.assertEqual(events[0].payload["actor_user_id"], str(ADMIN_ID))

    def test_rejected_gate_command_emits_no_confirmation_event(self):
        """A non-assignee GATEACCEPT (rejected by the service's own
        `_require_assignee`) never reaches `_emit_gate_confirmation` -
        the rejection path is entirely unchanged by this unit."""
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        with self.Session.begin() as session:
            session.add(V2ProjectMembership(
                project_id=uuid.UUID(project["id"]), employee_id=self.internal_employee_profile_id,
                project_role="internal_employee", assigned_by=PM_ID, assignment_reason="seed",
            ))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-rejected",
            "sender_phone": INTERNAL_EMPLOYEE_PHONE,
            "message_text": f"GATEACCEPT {ref}",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "rejected")
        self.assertEqual([row for row in self.outbox_rows() if row.event_type.startswith("gate_confirmation.")], [])

    def test_invalid_gatestatus_health_emits_no_confirmation_event(self):
        project = self.activate_project()
        approval = self.make_gate_approval(project["id"], assigned_to_user_id=SUPERVISOR_ID)
        ref = self.assignment_ref(str(approval.id))

        response = self.post_inbound({
            "provider_message_id": "wamid.confirm-invalid-status",
            "sender_phone": SUPERVISOR_PHONE,
            "message_text": f"GATESTATUS {ref} stuck",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.inbound_rows()[0].processing_status, "rejected")
        self.assertEqual(self.confirmation_events("gate_confirmation.status_recorded"), [])

    # ---- duplicate delivery -------------------------------------------------

    def test_duplicate_provider_message_id_is_processed_exactly_once(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        ref = self.assignment_ref(assignment_id)

        payload = {
            "provider_message_id": "wamid.dup-1",
            "sender_phone": VENDOR_ELECTRICAL_CONTACT_PHONE,
            "message_text": f"ACCEPT {ref}",
        }
        first = self.post_inbound(payload)
        self.assertEqual(first.status_code, 200, first.text)

        second = self.post_inbound(payload)
        self.assertEqual(second.status_code, 200, second.text)

        rows = self.inbound_rows()
        self.assertEqual(len(rows), 1)

        acks = self.acknowledgement_rows()
        self.assertEqual(len(acks), 1)

    # ---- proof: no parallel business logic ---------------------------------

    def test_no_duplicated_business_logic_in_new_files(self):
        """Static-inspection proof (not just behavioral): the new files
        call the SAME TaskLifecycleService.transition /
        VendorAcknowledgementService.record_acknowledgement methods Phase
        1/Phase 2 U3's portal routes call, and never directly assign
        Task.lifecycle_status or TaskVendorAssignment.status themselves."""
        import app.routes.whatsapp_webhook_v2 as webhook_route_module
        import app.services.inbound_message as inbound_service_module

        for module in (webhook_route_module, inbound_service_module):
            source = inspect.getsource(module)
            self.assertNotIn(".lifecycle_status =", source, f"{module.__name__} must not directly assign lifecycle_status.")
            self.assertNotIn("assignment.status =", source, f"{module.__name__} must not directly assign assignment status.")

        service_source = inspect.getsource(inbound_service_module)
        self.assertIn("TaskLifecycleService(self.db).transition(", service_source)
        self.assertIn("VendorAcknowledgementService(self.db).record_acknowledgement(", service_source)

        # AST-level proof: no direct attribute assignment to `.status` or
        # `.lifecycle_status` anywhere in the service module.
        tree = ast.parse(service_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr in ("lifecycle_status", "status"):
                        self.fail(f"Direct mutating assignment to .{target.attr} found in inbound_message.py")


if __name__ == "__main__":
    unittest.main()
