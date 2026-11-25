"""Vendor feedback on finished SiteOps projects: when it opens, who may write
it, the low-score reason rule, one review per person, edit/delete rights,
what the hub shows, and the pending-review nudge. Same SQLite-ATTACHed-schema
harness as the other vendor tests."""

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
    V2VendorProjectFeedback,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


# IDs keep at least one hex letter (SQLite numeric affinity, see other tests).
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc4")
EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd5")
VENDOR_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
OTHER_VENDOR_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee2")
DONE_PROJECT_ID = uuid.UUID("1a1a1a1a-1111-4111-8111-11111111111a")     # completed, vendor still mapped
LIVE_PROJECT_ID = uuid.UUID("2b2b2b2b-2222-4222-8222-22222222222b")     # active, vendor mapped
REMOVED_PROJECT_ID = uuid.UUID("3c3c3c3c-3333-4333-8333-33333333333c")  # active, vendor removed

USERS = {
    ADMIN_ID: ("Admin", UserRole.admin),
    PM_ID: ("Priya PM", UserRole.project_manager),
    SUPERVISOR_ID: ("Sam Supervisor", UserRole.supervisor),
    OUTSIDER_SUPERVISOR_ID: ("Other Supervisor", UserRole.supervisor),
    EMPLOYEE_ID: ("Employee", UserRole.internal_employee),
}

GOOD = {"rating": 4, "quality": 5, "timeliness": 3, "conduct": 4, "would_rehire": "yes", "comment": "Neat wiring."}


class VendorFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__,
            V2TemplateTask.__table__, V2Project.__table__, V2ProjectMembership.__table__, V2AuditEvent.__table__,
            V2Vendor.__table__, V2CapabilityCategory.__table__, V2VendorCapability.__table__, V2VendorContact.__table__,
            ProjectVendor.__table__, V2VendorPastProject.__table__, V2VendorProjectFeedback.__table__,
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

    def act_as(self, user_id):
        name, role = USERS[user_id]
        self._actor = User(id=user_id, name=name, email=f"{user_id}@example.com", role=role, active=True)

    def _seed(self):
        with self.Session.begin() as session:
            for user_id, (name, role) in USERS.items():
                session.add(User(id=user_id, name=name, email=f"{user_id}@example.com", role=role, active=True))
            session.flush()
            profiles = {}
            for user_id in (PM_ID, SUPERVISOR_ID, OUTSIDER_SUPERVISOR_ID, EMPLOYEE_ID):
                profiles[user_id] = EmployeeProfile(user_id=user_id, employee_code=f"E-{str(user_id)[-1]}", designation="Staff")
                session.add(profiles[user_id])
            session.add(V2Vendor(id=VENDOR_ID, name="Acme Electric", contact_person="Ravi", phone="+919876543210", created_by=ADMIN_ID))
            session.add(V2Vendor(id=OTHER_VENDOR_ID, name="Bright Paints", contact_person="Anil", phone="+919876543211", created_by=ADMIN_ID))
            for project_id, code, name, status in (
                (DONE_PROJECT_ID, "P-1", "Tower A", "completed"),
                (LIVE_PROJECT_ID, "P-2", "Mall B", "active"),
                (REMOVED_PROJECT_ID, "P-3", "Clinic C", "active"),
            ):
                session.add(V2Project(id=project_id, code=code, name=name, client_name="Client", site_address="Site",
                                      start_date=date(2026, 1, 1), status=status, created_by=ADMIN_ID,
                                      completed_at=datetime(2026, 6, 30, tzinfo=timezone.utc) if status == "completed" else None))
            session.flush()
            # PM and Supervisor on every project; the employee only as support.
            for project_id in (DONE_PROJECT_ID, LIVE_PROJECT_ID, REMOVED_PROJECT_ID):
                for user_id, role in ((PM_ID, "project_manager"), (SUPERVISOR_ID, "site_supervisor"), (EMPLOYEE_ID, "internal_employee")):
                    session.add(V2ProjectMembership(project_id=project_id, employee_id=profiles[user_id].id, project_role=role,
                                                    assigned_by=ADMIN_ID, assignment_reason="Seed"))
            session.add(ProjectVendor(project_id=DONE_PROJECT_ID, vendor_id=VENDOR_ID, mapped_by=ADMIN_ID))
            session.add(ProjectVendor(project_id=DONE_PROJECT_ID, vendor_id=OTHER_VENDOR_ID, mapped_by=ADMIN_ID))
            session.add(ProjectVendor(project_id=LIVE_PROJECT_ID, vendor_id=VENDOR_ID, mapped_by=ADMIN_ID))
            session.add(ProjectVendor(project_id=REMOVED_PROJECT_ID, vendor_id=VENDOR_ID, mapped_by=ADMIN_ID,
                                      ends_at=datetime(2026, 3, 1, tzinfo=timezone.utc)))

    def _review(self, project_id=DONE_PROJECT_ID, vendor_id=VENDOR_ID, **body):
        return self.client.post(f"/api/communication-hub/vendors/{vendor_id}/projects/{project_id}/feedback", json={**GOOD, **body})

    def _hub(self):
        return self.client.get("/api/communication-hub").json()

    # ---- work history now includes finished projects ---------------------

    def test_history_lists_completed_and_removed_but_not_live_projects(self):
        history = [item for item in self._hub()["project_history"] if item["vendor_id"] == str(VENDOR_ID)]
        by_name = {item["project_name"]: item for item in history}
        self.assertEqual(set(by_name), {"Tower A", "Clinic C"})
        self.assertFalse(by_name["Tower A"]["removed"])
        self.assertTrue(by_name["Clinic C"]["removed"])
        self.assertTrue(by_name["Tower A"]["ended_at"].startswith("2026-06-30"))

    # ---- when and who --------------------------------------------------

    def test_admin_pm_and_supervisor_can_review_a_finished_project(self):
        for user_id, role in ((ADMIN_ID, "admin"), (PM_ID, "project_manager"), (SUPERVISOR_ID, "site_supervisor")):
            self.act_as(user_id)
            response = self._review()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["author_role"], role)

    def test_removed_vendor_can_be_reviewed_while_project_is_still_running(self):
        self.assertEqual(self._review(project_id=REMOVED_PROJECT_ID).status_code, 200)

    def test_live_work_cannot_be_reviewed_yet(self):
        response = self._review(project_id=LIVE_PROJECT_ID)
        self.assertEqual(response.status_code, 409)
        self.assertIn("once the project is completed", response.json()["detail"])

    def test_outsiders_and_employees_cannot_review(self):
        self.act_as(OUTSIDER_SUPERVISOR_ID)
        self.assertEqual(self._review().status_code, 403)
        self.act_as(EMPLOYEE_ID)
        self.assertEqual(self._review().status_code, 403)

    def test_replaced_supervisor_keeps_the_right_to_review(self):
        with self.Session.begin() as session:
            membership = session.scalar(select(V2ProjectMembership).join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
                                        .where(EmployeeProfile.user_id == SUPERVISOR_ID, V2ProjectMembership.project_id == DONE_PROJECT_ID))
            membership.ends_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        self.act_as(SUPERVISOR_ID)
        self.assertEqual(self._review().status_code, 200)

    def test_vendor_never_on_project_is_refused(self):
        self.assertEqual(self._review(project_id=REMOVED_PROJECT_ID, vendor_id=OTHER_VENDOR_ID).status_code, 409)

    # ---- content rules ---------------------------------------------------

    def test_low_rating_or_no_rehire_needs_a_comment(self):
        self.assertEqual(self._review(rating=2, comment="").status_code, 422)
        self.assertEqual(self._review(would_rehire="no", comment="  ").status_code, 422)
        self.assertEqual(self._review(rating=2, would_rehire="no", comment="Left site dirty twice.").status_code, 200)

    def test_scores_are_one_to_five_and_optional(self):
        self.assertEqual(self._review(rating=6).status_code, 422)
        self.assertEqual(self._review(quality=0).status_code, 422)
        self.assertEqual(self._review(quality=None, timeliness=None, conduct=None, comment=None).status_code, 200)

    def test_one_review_per_person(self):
        self.assertEqual(self._review().status_code, 200)
        self.assertEqual(self._review(rating=5).status_code, 409)

    # ---- edit / delete ---------------------------------------------------

    def test_author_edits_others_cannot_admin_can_delete(self):
        self.act_as(SUPERVISOR_ID)
        feedback_id = self._review().json()["id"]
        updated = self.client.put(f"/api/communication-hub/feedback/{feedback_id}", json={**GOOD, "rating": 5})
        self.assertEqual(updated.json()["rating"], 5)

        self.act_as(PM_ID)
        self.assertEqual(self.client.put(f"/api/communication-hub/feedback/{feedback_id}", json=GOOD).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/communication-hub/feedback/{feedback_id}").status_code, 403)

        self.act_as(ADMIN_ID)
        self.assertEqual(self.client.put(f"/api/communication-hub/feedback/{feedback_id}", json=GOOD).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/communication-hub/feedback/{feedback_id}").status_code, 200)
        self.assertEqual(self._hub()["vendor_feedback"], [])

    def test_changes_are_audited(self):
        self._review()
        with self.Session() as session:
            actions = session.scalars(select(V2AuditEvent.action)).all()
        self.assertIn("vendor_feedback_added", actions)

    # ---- reading ---------------------------------------------------------

    def test_everyone_who_sees_the_vendor_reads_every_review(self):
        self.act_as(SUPERVISOR_ID)
        self._review(comment="Good crew.")
        self.act_as(OUTSIDER_SUPERVISOR_ID)
        feedback = self._hub()["vendor_feedback"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]["author_name"], "Sam Supervisor")
        self.assertEqual(feedback[0]["author_role_label"], "Site supervisor")
        self.assertEqual(feedback[0]["project_name"], "Tower A")

    def test_can_review_flag_follows_the_rules(self):
        self.act_as(OUTSIDER_SUPERVISOR_ID)
        self.assertFalse(any(item["can_review"] for item in self._hub()["project_history"]))
        self.act_as(SUPERVISOR_ID)
        self.assertTrue(all(item["can_review"] for item in self._hub()["project_history"]))

    # ---- nudge -------------------------------------------------------------

    def test_pending_lists_unreviewed_finished_work_for_pm_and_supervisor(self):
        self.act_as(SUPERVISOR_ID)
        pending = self.client.get("/api/communication-hub/feedback/pending").json()
        self.assertEqual({(item["vendor_name"], item["project_name"]) for item in pending},
                         {("Acme Electric", "Tower A"), ("Bright Paints", "Tower A"), ("Acme Electric", "Clinic C")})
        self._review()
        pending = self.client.get("/api/communication-hub/feedback/pending").json()
        self.assertNotIn(("Acme Electric", "Tower A"), {(item["vendor_name"], item["project_name"]) for item in pending})

        self.act_as(ADMIN_ID)
        self.assertEqual(self.client.get("/api/communication-hub/feedback/pending").json(), [])


if __name__ == "__main__":
    unittest.main()
