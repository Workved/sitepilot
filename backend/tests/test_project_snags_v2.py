"""Project snag list: who may add/edit/close/delete, the tagged outsider's
narrow access, archived projects, close/reopen, partial edits, attachments
and the WhatsApp switch. Same SQLite-ATTACHed-schema harness as the vendor
tests."""

from __future__ import annotations

import base64
import unittest
import uuid
from datetime import date
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
from app.execution_models import FileObject, OutboxEvent
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.routes.snags_v2 import router as snags_router
from app.snag_models import ProjectSnag, ProjectSnagFile
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OUTSIDER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
GONE_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")
PROJECT_ID = uuid.UUID("1a1a1a1a-1111-4111-8111-11111111111a")
ARCHIVED_ID = uuid.UUID("2b2b2b2b-2222-4222-8222-22222222222b")

USERS = {
    ADMIN_ID: ("Admin", UserRole.admin, True),
    PM_ID: ("Priya PM", UserRole.project_manager, True),
    SUPERVISOR_ID: ("Sam Supervisor", UserRole.supervisor, True),
    EMPLOYEE_ID: ("Eve Employee", UserRole.internal_employee, True),
    OUTSIDER_ID: ("Omar Outside", UserRole.supervisor, True),
    GONE_ID: ("Gone User", UserRole.supervisor, False),
}
# Smallest valid PNG (1x1), so the real content check runs.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class ProjectSnagTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__, V2TemplateTask.__table__,
            V2Project.__table__, V2ProjectMembership.__table__, V2AuditEvent.__table__, FileObject.__table__, OutboxEvent.__table__,
            ProjectSnag.__table__, ProjectSnagFile.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.store = {}
        self.patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, content_type: self.store.__setitem__(key, data)),
            patch("app.services.evidence_storage.read", side_effect=self.store.get),
        ]
        for item in self.patches:
            item.start()

        self.app = FastAPI()
        self.app.include_router(snags_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.act_as(SUPERVISOR_ID)
        self.app.dependency_overrides[current_user] = lambda: self._actor
        self.client = TestClient(self.app)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.client.close()
        self.engine.dispose()

    def act_as(self, user_id):
        name, role, active = USERS[user_id]
        self._actor = User(id=user_id, name=name, email=f"{user_id}@example.com", role=role, active=active)

    def _seed(self):
        with self.Session.begin() as session:
            for user_id, (name, role, active) in USERS.items():
                session.add(User(id=user_id, name=name, email=f"{user_id}@example.com", role=role, active=active))
            session.flush()
            profiles = {}
            for user_id in (PM_ID, SUPERVISOR_ID, EMPLOYEE_ID, OUTSIDER_ID):
                profiles[user_id] = EmployeeProfile(user_id=user_id, employee_code=f"E-{str(user_id)[-1]}", designation="Staff")
                session.add(profiles[user_id])
            for project_id, code, status in ((PROJECT_ID, "P-1", "active"), (ARCHIVED_ID, "P-2", "archived")):
                session.add(V2Project(id=project_id, code=code, name=f"Project {code}", client_name="Client", site_address="Site",
                                      start_date=date(2026, 1, 1), status=status, created_by=ADMIN_ID))
            session.flush()
            for project_id in (PROJECT_ID, ARCHIVED_ID):
                for user_id, role in ((PM_ID, "project_manager"), (SUPERVISOR_ID, "site_supervisor"), (EMPLOYEE_ID, "internal_employee")):
                    session.add(V2ProjectMembership(project_id=project_id, employee_id=profiles[user_id].id, project_role=role,
                                                    assigned_by=ADMIN_ID, assignment_reason="Seed"))

    def _add(self, project_id=PROJECT_ID, **body):
        return self.client.post(f"/api/v2/projects/{project_id}/snags", json={"title": "Touch up paint near cabin 3", **body})

    def _seed_archived_snag(self):
        with self.Session.begin() as session:
            snag = ProjectSnag(project_id=ARCHIVED_ID, title="Old snag", status="open", created_by=SUPERVISOR_ID)
            session.add(snag)
        return snag.id

    # ---- adding --------------------------------------------------------------

    def test_anyone_on_the_project_and_admins_can_add_with_just_a_title(self):
        for user_id in (SUPERVISOR_ID, EMPLOYEE_ID, PM_ID, ADMIN_ID):
            self.act_as(user_id)
            response = self._add()
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["status"], "open")
            self.assertEqual(response.json()["created_by"]["id"], str(user_id))

    def test_people_outside_the_project_cannot_add_or_list(self):
        self.act_as(OUTSIDER_ID)
        self.assertEqual(self._add().status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/projects/{PROJECT_ID}/snags").status_code, 403)

    def test_blank_or_long_title_is_refused(self):
        self.assertEqual(self._add(title="   ").status_code, 422)
        self.assertEqual(self._add(title="x" * 201).status_code, 422)

    def test_can_tag_any_active_user_but_not_an_inactive_one(self):
        self.assertEqual(self._add(assignee_user_id=str(OUTSIDER_ID)).json()["assignee"]["name"], "Omar Outside")
        self.assertEqual(self._add(assignee_user_id=str(GONE_ID)).status_code, 422)

    def test_people_list_has_every_active_user(self):
        names = {person["name"] for person in self.client.get("/api/v2/snags/people").json()}
        self.assertIn("Omar Outside", names)
        self.assertNotIn("Gone User", names)

    # ---- the tagged outsider ---------------------------------------------------

    def test_tagged_outsider_sees_and_closes_only_their_snag(self):
        tagged = self._add(assignee_user_id=str(OUTSIDER_ID)).json()
        self._add(title="Someone else's snag")
        self.act_as(OUTSIDER_ID)
        mine = self.client.get("/api/v2/snags/tagged-to-me").json()
        self.assertEqual([item["id"] for item in mine], [tagged["id"]])
        self.assertTrue(mine[0]["can_close"])
        self.assertFalse(mine[0]["can_edit"])
        self.assertFalse(mine[0]["can_delete"])
        self.assertFalse(mine[0]["can_open_project"])
        self.assertEqual(self.client.patch(f"/api/v2/snags/{tagged['id']}", json={"title": "Changed"}).status_code, 403)
        done = self.client.post(f"/api/v2/snags/{tagged['id']}/status", json={"status": "done", "closing_note": "Painted."})
        self.assertEqual(done.json()["status"], "done")
        self.assertEqual(done.json()["closed_by"]["name"], "Omar Outside")
        self.assertEqual(self.client.get("/api/v2/snags/tagged-to-me").json(), [])

    def test_untagged_outsider_cannot_open_a_snag(self):
        snag = self._add().json()
        self.act_as(OUTSIDER_ID)
        self.assertEqual(self.client.post(f"/api/v2/snags/{snag['id']}/status", json={"status": "done"}).status_code, 403)

    # ---- edit / close / delete rights -------------------------------------------

    def test_member_who_is_not_creator_lead_or_tagged_cannot_edit_or_close(self):
        snag = self._add().json()
        self.act_as(EMPLOYEE_ID)
        self.assertEqual(self.client.patch(f"/api/v2/snags/{snag['id']}", json={"area": "Lobby"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/snags/{snag['id']}/status", json={"status": "done"}).status_code, 403)
        listed = self.client.get(f"/api/v2/projects/{PROJECT_ID}/snags").json()["items"][0]
        self.assertFalse(listed["can_close"])

    def test_pm_can_edit_and_delete_anyones_snag_supervisor_can_edit_not_delete(self):
        self.act_as(EMPLOYEE_ID)
        snag = self._add().json()
        self.act_as(SUPERVISOR_ID)
        self.assertEqual(self.client.patch(f"/api/v2/snags/{snag['id']}", json={"urgent": True}).json()["urgent"], True)
        self.assertEqual(self.client.delete(f"/api/v2/snags/{snag['id']}").status_code, 403)
        self.act_as(PM_ID)
        self.assertEqual(self.client.delete(f"/api/v2/snags/{snag['id']}").status_code, 200)

    def test_partial_edit_changes_only_what_is_sent_and_null_untags(self):
        snag = self._add(area="Cabin 3", assignee_user_id=str(PM_ID)).json()
        updated = self.client.patch(f"/api/v2/snags/{snag['id']}", json={"assignee_user_id": None}).json()
        self.assertIsNone(updated["assignee"])
        self.assertEqual(updated["area"], "Cabin 3")
        self.assertEqual(self.client.patch(f"/api/v2/snags/{snag['id']}", json={"title": None}).status_code, 422)

    def test_close_and_reopen(self):
        snag = self._add().json()
        done = self.client.post(f"/api/v2/snags/{snag['id']}/status", json={"status": "done", "closing_note": "Fixed"}).json()
        self.assertTrue(done["closed_at"])
        self.assertEqual(done["closing_note"], "Fixed")
        reopened = self.client.post(f"/api/v2/snags/{snag['id']}/status", json={"status": "open"}).json()
        self.assertIsNone(reopened["closed_at"])
        self.assertIsNone(reopened["closing_note"])

    def test_archived_projects_are_read_only(self):
        snag_id = self._seed_archived_snag()
        listing = self.client.get(f"/api/v2/projects/{ARCHIVED_ID}/snags").json()
        self.assertTrue(listing["read_only"])
        self.assertFalse(listing["items"][0]["can_close"])
        self.assertEqual(self._add(project_id=ARCHIVED_ID).status_code, 409)
        self.assertEqual(self.client.post(f"/api/v2/snags/{snag_id}/status", json={"status": "done"}).status_code, 409)

    # ---- files ---------------------------------------------------------------

    def test_attach_download_and_remove_a_photo(self):
        snag = self._add(assignee_user_id=str(OUTSIDER_ID)).json()
        self.act_as(OUTSIDER_ID)
        attached = self.client.post(f"/api/v2/snags/{snag['id']}/files", files={"file": ("crack.png", PNG, "image/png")})
        self.assertEqual(attached.status_code, 201, attached.text)
        file_id = attached.json()["files"][0]["id"]
        download = self.client.get(f"/api/v2/snags/{snag['id']}/files/{file_id}")
        self.assertEqual(download.content, PNG)
        self.assertEqual(self.client.delete(f"/api/v2/snags/{snag['id']}/files/{file_id}").json()["files"], [])

    def test_wrong_file_type_is_refused(self):
        snag = self._add().json()
        response = self.client.post(f"/api/v2/snags/{snag['id']}/files", files={"file": ("notes.txt", b"hello", "text/plain")})
        self.assertEqual(response.status_code, 422)

    # ---- notifications and audit ------------------------------------------------

    def test_whatsapp_event_only_when_switched_on_and_not_for_self_tags(self):
        self._add(assignee_user_id=str(PM_ID))
        with self.Session() as session:
            self.assertEqual(session.scalars(select(OutboxEvent)).all(), [])
        with patch.object(settings, "snag_whatsapp_enabled", True):
            self._add(assignee_user_id=str(PM_ID), area="Cabin 3")
            self._add(assignee_user_id=str(SUPERVISOR_ID))  # tagging yourself sends nothing
        with self.Session() as session:
            events = session.scalars(select(OutboxEvent)).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "snag.assigned")
        self.assertEqual(events[0].payload["user_id"], str(PM_ID))
        self.assertEqual(events[0].payload["tagged_by"], "Sam Supervisor")
        self.assertEqual(events[0].payload["area"], "Cabin 3")

    def test_changes_land_in_the_project_activity_log(self):
        snag = self._add().json()
        self.client.post(f"/api/v2/snags/{snag['id']}/status", json={"status": "done"})
        with self.Session() as session:
            actions = session.scalars(select(V2AuditEvent.action).where(V2AuditEvent.project_id == PROJECT_ID)).all()
        self.assertEqual(set(actions), {"SNAG_ADDED", "SNAG_CLOSED"})


if __name__ == "__main__":
    unittest.main()
