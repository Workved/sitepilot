from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import OutboxEvent
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectExternalGateTask, V2ProjectMembership, V2ProjectTask, V2ProjectTaskDependency
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.project_vendors_v2 import vendors_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import V2VendorContact, VendorContactProject
from app.vendor_models import ProjectVendor, V2CapabilityCategory, V2Vendor, V2VendorCapability
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class ProjectVendorMappingApiTests(unittest.TestCase):
    """Phase 2 U2: project-vendor mapping (R2).

    Follows the SQLite-in-memory-with-ATTACHed-schema harness pattern used
    across the rest of the V2 test suite (see
    test_task_support_assignment_v2.py). Only a project draft (PM +
    Supervisor active memberships assigned at creation) is needed here - no
    template task generation or activation is required, since mapping does
    not touch the execution-layer `tasks` table.
    """

    def setUp(self):
        pin_project_creation_today(self)
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # V2ProjectExternalGate's broad-text check constraint uses
            # Postgres's btrim(); SQLite has no such builtin, so register
            # an equivalent for this test harness only.
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2AuditEvent.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            ProjectVendor.__table__,
            V2VendorContact.__table__,
            VendorContactProject.__table__,
            OutboxEvent.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2TemplateTaskDependency.__table__,
            V2ProjectExternalGate.__table__,
            V2ProjectExternalGateTask.__table__,
            V2ProjectTaskDependency.__table__,
            V2TemplateTask.__table__,
            V2ProjectTask.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(project_vendors_router)
        self.app.include_router(vendors_router)

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

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_admin(self) -> None:
        self.act_as(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    def act_as_outsider(self) -> None:
        self.act_as(User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            outsider = User(
                id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
                role=UserRole.supervisor, active=True,
            )
            session.add_all([admin, pm, supervisor, outsider])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
                ),
            ])
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
            # Creating a project now generates its task snapshot, and a
            # template with no tasks is rejected outright - this fixture only
            # needs a project to hang vendor mappings off, so one task is enough.
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Seed task",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", evidence_required=False, duration_days=1,
            ))
            session.flush()
            self.published_version_id = published.id

            main_vendor = V2Vendor(
                id=uuid.uuid4(), name="Acme Electricals", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            inactive_vendor = V2Vendor(
                id=uuid.uuid4(), name="Dormant Vendor", contact_person="Meena", phone="9000000002",
                status="blacklisted", blacklist_reason="Quality issues", engagement_type="main",
            )
            session.add_all([main_vendor, inactive_vendor])
            session.flush()
            sub_vendor = V2Vendor(
                id=uuid.uuid4(), name="Acme Sub Electricals", contact_person="Kiran", phone="9000000003",
                status="active", engagement_type="sub_vendor", parent_vendor_id=main_vendor.id,
            )
            session.add(sub_vendor)
            session.flush()
            self.main_vendor_id = main_vendor.id
            self.inactive_vendor_id = inactive_vendor.id
            self.sub_vendor_id = sub_vendor.id

            electrical = V2CapabilityCategory(name="Electrical")
            session.add(electrical)
            session.flush()
            session.add(V2VendorCapability(vendor_id=main_vendor.id, category_id=electrical.id))

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

    def map_vendor(self, project_id, vendor_id):
        return self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)},
        )

    def activate(self, project_id):
        # This file's harness doesn't set up the full activation chain
        # (baseline locking, task instantiation) - only project.status
        # matters to the code path under test here (map_vendor's Active-
        # only outbox guard), so flip it directly, same convention as
        # test_project_manual_task_v2.py's setup.
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(project_id)).status = "active"

    # ---- happy path -----------------------------------------------------

    def test_pm_maps_active_vendor_to_project(self):
        project = self.create_draft()
        self.act_as_pm()

        response = self.map_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["project_id"], project["id"])
        self.assertEqual(body["vendor_id"], str(self.main_vendor_id))
        self.assertEqual(body["mapped_by"], str(PM_ID))

        with self.Session() as session:
            row = session.get(ProjectVendor, uuid.UUID(body["id"]))
            self.assertIsNotNone(row)
            self.assertEqual(str(row.vendor_id), str(self.main_vendor_id))

    # ---- sub-vendor edge cases -------------------------------------------

    def test_sub_vendor_rejected_when_parent_not_mapped(self):
        project = self.create_draft()
        self.act_as_pm()

        response = self.map_vendor(project["id"], self.sub_vendor_id)

        self.assertEqual(response.status_code, 422, response.text)

    def test_sub_vendor_accepted_when_parent_already_mapped(self):
        project = self.create_draft()
        self.act_as_pm()

        parent_response = self.map_vendor(project["id"], self.main_vendor_id)
        self.assertEqual(parent_response.status_code, 200, parent_response.text)

        sub_response = self.map_vendor(project["id"], self.sub_vendor_id)

        self.assertEqual(sub_response.status_code, 200, sub_response.text)
        body = sub_response.json()
        self.assertEqual(body["vendor_id"], str(self.sub_vendor_id))

    # ---- error paths ------------------------------------------------------

    def test_inactive_vendor_cannot_be_mapped(self):
        project = self.create_draft()
        self.act_as_pm()

        response = self.map_vendor(project["id"], self.inactive_vendor_id)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("blacklisted", response.json()["detail"])

    def test_non_pm_non_admin_cannot_map_vendor(self):
        project = self.create_draft()
        self.act_as_outsider()

        response = self.map_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 403, response.text)

    # ---- read endpoints (frontend read surface) --------------------------

    def test_list_vendors_returns_active_vendors_with_capabilities(self):
        self.act_as_pm()

        response = self.client.get("/api/v2/vendors")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # `inactive_vendor` (blacklisted) is excluded - blacklisted vendors aren't offered.
        ids = {row["id"] for row in body}
        self.assertIn(str(self.main_vendor_id), ids)
        self.assertIn(str(self.sub_vendor_id), ids)
        self.assertNotIn(str(self.inactive_vendor_id), ids)
        main_row = next(row for row in body if row["id"] == str(self.main_vendor_id))
        self.assertEqual(main_row["capability_categories"], ["Electrical"])
        sub_row = next(row for row in body if row["id"] == str(self.sub_vendor_id))
        self.assertEqual(sub_row["capability_categories"], [])

    def test_list_project_vendors_returns_only_this_projects_mappings(self):
        project = self.create_draft()
        other_project = self.create_draft(project_name="Other Project")
        self.act_as_pm()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.assertEqual(self.map_vendor(other_project["id"], self.main_vendor_id).status_code, 200)

        response = self.client.get(f"/api/v2/projects/{project['id']}/vendors")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["vendor_id"], str(self.main_vendor_id))
        self.assertEqual(body[0]["vendor_name"], "Acme Electricals")

    def test_list_project_vendors_empty_before_any_mapping(self):
        project = self.create_draft()
        self.act_as_pm()

        response = self.client.get(f"/api/v2/projects/{project['id']}/vendors")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    # ---- U3 (WhatsApp gate workflow): project.vendor_mapped emission -----
    #
    # Local-testing follow-up (2026-09-18): a Draft project is planning/
    # setup - mapping a vendor here must NOT notify the execution team (see
    # `project_vendor.map_vendor`'s Active-only guard). This replaces a
    # prior version of this test that asserted the OPPOSITE (an event on a
    # Draft-phase mapping), which was itself proof of the bug being fixed,
    # not a spec.

    def test_mapping_a_vendor_on_a_draft_project_emits_no_event(self):
        project = self.create_draft()
        self.act_as_pm()

        response = self.map_vendor(project["id"], self.main_vendor_id)
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "project.vendor_mapped")
            ).all()
            self.assertEqual(events, [])

    def test_mapping_a_vendor_on_an_active_project_emits_project_vendor_mapped_event(self):
        project = self.create_draft()
        self.activate(project["id"])
        self.act_as_pm()

        response = self.map_vendor(project["id"], self.main_vendor_id)
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "project.vendor_mapped")
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "project")
            self.assertEqual(str(events[0].aggregate_id), project["id"])
            self.assertEqual(events[0].payload["project_id"], project["id"])
            self.assertEqual(events[0].payload["vendor_id"], str(self.main_vendor_id))
            # A distinct event type from the person-joins case (KTD19) - no
            # employee_id/project_role key ever appears in this payload.
            self.assertNotIn("employee_id", events[0].payload)

    def test_mapping_an_inactive_vendor_emits_no_event(self):
        project = self.create_draft()
        self.act_as_pm()

        response = self.map_vendor(project["id"], self.inactive_vendor_id)

        self.assertEqual(response.status_code, 422, response.text)
        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "project.vendor_mapped")
            ).all()
            self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
