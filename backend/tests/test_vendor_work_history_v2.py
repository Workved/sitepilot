"""Vendor Work history: hand-entered past projects (create/edit/delete and
who may do it) plus ended SiteOps project mappings, both surfaced through
GET /api/communication-hub. Same SQLite-ATTACHed-schema harness as the other
vendor tests."""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.routes.communication import router as hub_router
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion
from app.vendor_models import (
    ProjectVendor,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    V2VendorContact,
    V2VendorPastProject,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


# IDs keep at least one hex letter: SQLite gives the "UUID" column type
# numeric affinity, so an all-digit ID would be stored as a number.
SUPER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa0")
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OTHER_SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc4")
EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd5")
VENDOR_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
CATEGORY_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff1")
VISIBLE_PROJECT_ID = uuid.UUID("1a1a1a1a-1111-4111-8111-11111111111a")
HIDDEN_PROJECT_ID = uuid.UUID("2b2b2b2b-2222-4222-8222-22222222222b")

USERS = {
    SUPER_ID: ("Super", UserRole.super_admin),
    ADMIN_ID: ("Admin", UserRole.admin),
    PM_ID: ("PM", UserRole.project_manager),
    SUPERVISOR_ID: ("Supervisor", UserRole.supervisor),
    OTHER_SUPERVISOR_ID: ("Other Supervisor", UserRole.supervisor),
    EMPLOYEE_ID: ("Employee", UserRole.internal_employee),
}


class VendorWorkHistoryTests(unittest.TestCase):
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
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2AuditEvent.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            V2VendorContact.__table__,
            ProjectVendor.__table__,
            V2VendorPastProject.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(hub_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.act_as(ADMIN_ID)
        self.app.dependency_overrides[current_user] = lambda: self._actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as(self, user_id: uuid.UUID) -> None:
        name, role = USERS[user_id]
        self._actor = User(id=user_id, name=name, email=f"{name.lower().replace(' ', '')}@example.com", role=role, active=True)

    def _seed(self):
        with self.Session.begin() as session:
            for user_id, (name, role) in USERS.items():
                session.add(User(id=user_id, name=name, email=f"{name.lower().replace(' ', '')}@example.com", role=role, active=True))
            session.flush()
            supervisor_profile = EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="E-1", designation="Supervisor")
            session.add(supervisor_profile)
            session.add(V2CapabilityCategory(id=CATEGORY_ID, name="Electrical"))
            session.add(V2Vendor(id=VENDOR_ID, name="Acme Electric", contact_person="Ravi", phone="+919876543210", created_by=ADMIN_ID))
            for project_id, code, name in ((VISIBLE_PROJECT_ID, "P-1", "Tower A"), (HIDDEN_PROJECT_ID, "P-2", "Mall B")):
                session.add(V2Project(
                    id=project_id, code=code, name=name, client_name="Client", site_address="Site",
                    start_date=date(2025, 1, 1), status="active", created_by=ADMIN_ID,
                ))
            session.flush()
            session.add(V2ProjectMembership(
                project_id=VISIBLE_PROJECT_ID, employee_id=supervisor_profile.id, project_role="supervisor",
                assigned_by=ADMIN_ID, assignment_reason="Seed",
            ))
            ended = datetime(2025, 6, 30, tzinfo=timezone.utc)
            for project_id in (VISIBLE_PROJECT_ID, HIDDEN_PROJECT_ID):
                session.add(ProjectVendor(project_id=project_id, vendor_id=VENDOR_ID, mapped_by=ADMIN_ID, ends_at=ended))

    def _add(self, **overrides):
        body = {
            "project_name": "Old Office Fit-out", "client_name": "Infra Ltd", "location": "Pune",
            "category_id": str(CATEGORY_ID), "work_description": "Full wiring", "start_month": "2023-02",
            "end_month": "2023-09", "approx_value": "1250000", "notes": "",
        }
        body.update(overrides)
        return self.client.post(f"/api/communication-hub/vendors/{VENDOR_ID}/past-projects", json=body)

    # ---- create --------------------------------------------------------

    def test_admin_adds_past_project_and_it_shows_in_hub(self):
        response = self._add()
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        self.assertEqual(created["project_name"], "Old Office Fit-out")
        self.assertEqual(created["start_month"], "2023-02")
        self.assertEqual(created["end_month"], "2023-09")
        self.assertEqual(created["category_name"], "Electrical")
        self.assertEqual(created["approx_value"], 1250000.0)
        self.assertIsNone(created["notes"])
        self.assertEqual(created["created_by_name"], "Admin")

        hub = self.client.get("/api/communication-hub").json()
        self.assertEqual([item["id"] for item in hub["past_projects"]], [created["id"]])

        with self.Session() as session:
            actions = session.scalars(select(V2AuditEvent.action)).all()
        self.assertIn("vendor_past_project_added", actions)

    def test_pm_and_supervisor_can_add(self):
        for user_id in (PM_ID, SUPERVISOR_ID, SUPER_ID):
            self.act_as(user_id)
            self.assertEqual(self._add(project_name=f"Job by {user_id}").status_code, 200)

    def test_internal_employee_cannot_add(self):
        self.act_as(EMPLOYEE_ID)
        self.assertEqual(self._add().status_code, 403)

    def test_rejects_blank_name_bad_months_and_negative_value(self):
        self.assertEqual(self._add(project_name="   ").status_code, 422)
        self.assertEqual(self._add(start_month="2024-05", end_month="2024-01").status_code, 422)
        self.assertEqual(self._add(start_month="May 2024").status_code, 422)
        self.assertEqual(self._add(approx_value="-5").status_code, 422)

    def test_unknown_vendor_and_category(self):
        missing = self.client.post(f"/api/communication-hub/vendors/{uuid.uuid4()}/past-projects", json={"project_name": "X"})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self._add(category_id=str(uuid.uuid4())).status_code, 400)

    def test_only_name_is_required(self):
        response = self.client.post(f"/api/communication-hub/vendors/{VENDOR_ID}/past-projects", json={"project_name": "Bare entry", "category_id": "", "approx_value": "", "start_month": ""})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["start_month"])

    # ---- edit / delete permissions ------------------------------------

    def test_creator_can_edit_and_delete_own_entry(self):
        self.act_as(SUPERVISOR_ID)
        entry = self._add().json()
        updated = self.client.put(f"/api/communication-hub/past-projects/{entry['id']}", json={"project_name": "Renamed", "end_month": "2023-12"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["project_name"], "Renamed")
        self.assertIsNone(updated.json()["client_name"])
        self.assertEqual(self.client.delete(f"/api/communication-hub/past-projects/{entry['id']}").status_code, 200)
        with self.Session() as session:
            self.assertEqual(session.scalars(select(V2VendorPastProject)).all(), [])

    def test_other_non_admin_cannot_edit_or_delete(self):
        self.act_as(SUPERVISOR_ID)
        entry = self._add().json()
        for user_id in (OTHER_SUPERVISOR_ID, PM_ID):
            self.act_as(user_id)
            self.assertEqual(self.client.put(f"/api/communication-hub/past-projects/{entry['id']}", json={"project_name": "Hijack"}).status_code, 403)
            self.assertEqual(self.client.delete(f"/api/communication-hub/past-projects/{entry['id']}").status_code, 403)

    def test_admin_can_edit_and_delete_anyones_entry(self):
        self.act_as(SUPERVISOR_ID)
        entry = self._add().json()
        self.act_as(ADMIN_ID)
        self.assertEqual(self.client.put(f"/api/communication-hub/past-projects/{entry['id']}", json={"project_name": "Fixed"}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/communication-hub/past-projects/{entry['id']}").status_code, 200)

    def test_missing_entry_is_404(self):
        self.assertEqual(self.client.put(f"/api/communication-hub/past-projects/{uuid.uuid4()}", json={"project_name": "X"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/communication-hub/past-projects/{uuid.uuid4()}").status_code, 404)

    # ---- hub payload ---------------------------------------------------

    def test_past_projects_sorted_most_recent_first(self):
        self._add(project_name="Older", start_month="2020-01", end_month="2020-06")
        self._add(project_name="Newer", start_month="2024-01", end_month="2024-03")
        self._add(project_name="Undated", start_month="", end_month="")
        names = [item["project_name"] for item in self.client.get("/api/communication-hub").json()["past_projects"]]
        self.assertEqual(names, ["Newer", "Older", "Undated"])

    def test_ended_siteops_projects_listed_with_visibility_rules(self):
        admin_history = self.client.get("/api/communication-hub").json()["project_history"]
        self.assertEqual({item["project_name"] for item in admin_history}, {"Tower A", "Mall B"})
        self.assertTrue(all(item["ended_at"] for item in admin_history))

        self.act_as(SUPERVISOR_ID)
        supervisor_history = self.client.get("/api/communication-hub").json()["project_history"]
        self.assertEqual([item["project_name"] for item in supervisor_history], ["Tower A"])


if __name__ == "__main__":
    unittest.main()
