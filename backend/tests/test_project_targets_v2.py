"""Task and project targets: who may set/change/clear, met/missed/due-soon,
replace history, project targets (linked tasks or manual), archived projects,
schedule-change history and the WhatsApp switch."""

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
from app.config import settings
from app.database import get_db
from app.execution_models import OutboxEvent, Task, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.routes.targets_v2 import router as targets_router
from app.target_models import ProjectTarget, ProjectTargetTask
from app.template_models import V2Template, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
OUTSIDER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
PROJECT_ID = uuid.UUID("1a1a1a1a-1111-4111-8111-11111111111a")
ARCHIVED_ID = uuid.UUID("2b2b2b2b-2222-4222-8222-22222222222b")
USERS = {
    ADMIN_ID: ("Admin", UserRole.admin), PM_ID: ("Priya PM", UserRole.project_manager),
    SUPERVISOR_ID: ("Sam Supervisor", UserRole.supervisor), EMPLOYEE_ID: ("Eve Employee", UserRole.internal_employee),
    OUTSIDER_ID: ("Omar Outside", UserRole.supervisor),
}
TODAY = datetime.now(timezone.utc).date()


class ProjectTargetTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__, V2Project.__table__,
                      V2ProjectMembership.__table__, Task.__table__, TaskSupportAssignment.__table__, V2AuditEvent.__table__,
                      OutboxEvent.__table__, ProjectTarget.__table__, ProjectTargetTask.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()
        self.app = FastAPI()
        self.app.include_router(targets_router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.act_as(SUPERVISOR_ID)
        self.app.dependency_overrides[current_user] = lambda: self._actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as(self, user_id):
        name, role = USERS[user_id]
        self._actor = User(id=user_id, name=name, email=f"{user_id}@example.com", role=role, active=True)

    def _task(self, session, project_id, code, **overrides):
        fields = {"lifecycle_status": "planned", "planned_start_date": TODAY, "planned_end_date": TODAY + timedelta(days=5), **overrides}
        task = Task(project_id=project_id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(), original_code=code,
                    template_sequence=int(code[1:]), title=f"Task {code}", schedule_classification="execution", applicability="mandatory",
                    evidence_required=False, **fields)
        session.add(task)
        session.flush()
        return task.id

    def _seed(self):
        with self.Session.begin() as session:
            for user_id, (name, role) in USERS.items():
                session.add(User(id=user_id, name=name, email=f"{user_id}@example.com", role=role, active=True))
            session.flush()
            profiles = {}
            for user_id in (PM_ID, SUPERVISOR_ID, EMPLOYEE_ID, OUTSIDER_ID):
                profiles[user_id] = EmployeeProfile(user_id=user_id, employee_code=f"E-{str(user_id)[-1]}", designation="Staff")
                session.add(profiles[user_id])
            for project_id, code, status in ((PROJECT_ID, "P-1", "active"), (ARCHIVED_ID, "P-2", "archived")):
                session.add(V2Project(id=project_id, code=code, name=f"Project {code}", client_name="C", site_address="S",
                                      start_date=TODAY, status=status, created_by=ADMIN_ID))
            session.flush()
            for project_id in (PROJECT_ID, ARCHIVED_ID):
                for user_id, role in ((PM_ID, "project_manager"), (SUPERVISOR_ID, "site_supervisor"), (EMPLOYEE_ID, "internal_employee")):
                    session.add(V2ProjectMembership(project_id=project_id, employee_id=profiles[user_id].id, project_role=role,
                                                    assigned_by=ADMIN_ID, assignment_reason="Seed"))
            self.t1 = self._task(session, PROJECT_ID, "T001")
            self.t2 = self._task(session, PROJECT_ID, "T002")
            self.done_early = self._task(session, PROJECT_ID, "T003", lifecycle_status="completed",
                                         actual_finish_at=datetime.combine(TODAY - timedelta(days=3), datetime.min.time(), tzinfo=timezone.utc))
            self.archived_task = self._task(session, ARCHIVED_ID, "T009")
            session.add(TaskSupportAssignment(project_id=PROJECT_ID, task_id=self.t1, employee_id=profiles[EMPLOYEE_ID].id,
                                              status="active", assigned_by=SUPERVISOR_ID, responsibility="Help"))

    def _set(self, task_id=None, days=3, **body):
        payload = {"kind": "task", "task_id": str(task_id or self.t1), "target_date": (TODAY + timedelta(days=days)).isoformat(), **body}
        return self.client.post(f"/api/v2/projects/{PROJECT_ID}/targets", json=payload)

    def _items(self):
        return self.client.get(f"/api/v2/projects/{PROJECT_ID}/targets").json()["items"]

    # ---- who ---------------------------------------------------------------

    def test_anyone_on_the_project_can_set_outsiders_cannot(self):
        for user_id in (EMPLOYEE_ID, PM_ID, ADMIN_ID):
            self.act_as(user_id)
            self.assertEqual(self._set().status_code, 201)
        self.act_as(OUTSIDER_ID)
        self.assertEqual(self._set().status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/projects/{PROJECT_ID}/targets").status_code, 403)

    def test_only_setter_lead_or_admin_can_change_or_clear(self):
        self.act_as(EMPLOYEE_ID)
        target = self._set(note="Client visit").json()
        self.assertTrue(target["can_manage"])
        self.act_as(OUTSIDER_ID)
        self.assertEqual(self.client.post(f"/api/v2/targets/{target['id']}/clear").status_code, 403)
        self.act_as(PM_ID)
        self.assertEqual(self.client.patch(f"/api/v2/targets/{target['id']}", json={"note": "Moved visit"}).json()["note"], "Moved visit")
        self.assertEqual(self.client.post(f"/api/v2/targets/{target['id']}/clear").json()["status"], "cleared")

    def test_member_who_did_not_set_it_cannot_manage(self):
        target = self._set().json()
        self.act_as(EMPLOYEE_ID)
        self.assertFalse(self._items()[0]["can_manage"])
        self.assertEqual(self.client.post(f"/api/v2/targets/{target['id']}/clear").status_code, 403)

    # ---- task targets --------------------------------------------------------

    def test_new_target_replaces_the_old_one_and_keeps_history(self):
        first = self._set(days=3).json()
        second = self._set(days=6).json()
        items = {item["id"]: item for item in self._items()}
        self.assertEqual(items[first["id"]]["status"], "replaced")
        self.assertEqual(items[second["id"]]["status"], "active")
        self.assertEqual(self.client.patch(f"/api/v2/targets/{second['id']}", json={"target_date": TODAY.isoformat()}).status_code, 409)

    def test_status_open_due_soon_missed_met(self):
        self.assertEqual(self._set(days=10).json()["outcome"]["state"], "open")
        self.assertEqual(self._set(days=1).json()["outcome"]["state"], "due_soon")
        missed = self._set(task_id=self.t2, days=-2).json()["outcome"]
        self.assertEqual((missed["state"], missed["days"]), ("missed", 2))
        with self.Session.begin() as session:
            task = session.get(Task, self.t2)
            task.lifecycle_status, task.actual_finish_at = "completed", datetime.now(timezone.utc)
        late = [item for item in self._items() if item["task_id"] == str(self.t2)][0]["outcome"]
        self.assertEqual((late["state"], late["days"]), ("missed", 2))

    def test_finished_tasks_cannot_get_a_target(self):
        self.assertEqual(self._set(task_id=self.done_early).status_code, 409)

    def test_task_from_another_project_is_refused(self):
        self.assertEqual(self._set(task_id=self.archived_task).status_code, 422)

    # ---- project targets -----------------------------------------------------

    def test_project_target_follows_linked_tasks(self):
        response = self.client.post(f"/api/v2/projects/{PROJECT_ID}/targets", json={
            "kind": "project", "title": "Client walkthrough", "target_date": TODAY.isoformat(), "task_ids": [str(self.done_early), str(self.t2)]})
        self.assertEqual(response.status_code, 201, response.text)
        outcome = response.json()["outcome"]
        self.assertEqual((outcome["state"], outcome["done"], outcome["total"]), ("due_soon", 1, 2))
        with self.Session.begin() as session:
            task = session.get(Task, self.t2)
            task.lifecycle_status, task.actual_finish_at = "completed", datetime.now(timezone.utc)
        self.assertEqual(self._items()[0]["outcome"]["state"], "met")
        self.assertEqual(self.client.post(f"/api/v2/targets/{response.json()['id']}/achieved", json={"achieved": True}).status_code, 409)

    def test_project_target_without_tasks_is_marked_achieved_by_hand(self):
        target = self.client.post(f"/api/v2/projects/{PROJECT_ID}/targets", json={
            "kind": "project", "title": "Site cleared for handover", "target_date": (TODAY + timedelta(days=4)).isoformat()}).json()
        done = self.client.post(f"/api/v2/targets/{target['id']}/achieved", json={"achieved": True}).json()
        self.assertEqual(done["outcome"]["state"], "met")
        self.assertEqual(done["achieved_by_name"], "Sam Supervisor")

    def test_project_target_needs_a_title(self):
        response = self.client.post(f"/api/v2/projects/{PROJECT_ID}/targets", json={"kind": "project", "target_date": TODAY.isoformat()})
        self.assertEqual(response.status_code, 422)

    # ---- archived / history / notify ---------------------------------------------

    def test_archived_projects_are_read_only(self):
        response = self.client.post(f"/api/v2/projects/{ARCHIVED_ID}/targets", json={"kind": "task", "task_id": str(self.archived_task), "target_date": TODAY.isoformat()})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.client.get(f"/api/v2/projects/{ARCHIVED_ID}/targets").json()["can_add"])

    def test_schedule_changes_report_the_original_plan(self):
        with self.Session.begin() as session:
            for before, after, when in (
                ({"planned_start_date": "2026-11-01", "planned_end_date": "2026-11-05"}, {"planned_start_date": "2026-11-04", "planned_end_date": "2026-11-08"}, 1),
                ({"planned_start_date": "2026-11-04", "planned_end_date": "2026-11-08"}, {"planned_start_date": "2026-11-07", "planned_end_date": "2026-11-11"}, 2),
            ):
                session.add(V2AuditEvent(actor_user_id=PM_ID, action="TASK_RESCHEDULED", entity_type="task", entity_id=self.t1, project_id=PROJECT_ID,
                                         before_json=before, after_json=after, reason=f"Move {when}", occurred_at=datetime(2026, 11, when, tzinfo=timezone.utc)))
        changes = self.client.get(f"/api/v2/projects/{PROJECT_ID}/schedule-changes").json()
        self.assertEqual(changes[0]["original_start"], "2026-11-01")
        self.assertEqual(changes[0]["times_moved"], 2)
        self.assertEqual((changes[0]["last_reason"], changes[0]["last_by"]), ("Move 2", "Priya PM"))

    def test_whatsapp_only_when_switched_on_and_to_responsible_people(self):
        self._set()
        with self.Session() as session:
            self.assertEqual(session.scalars(select(OutboxEvent)).all(), [])
        self.act_as(PM_ID)
        with patch.object(settings, "target_whatsapp_enabled", True):
            self._set(task_id=self.t1, days=4)
        with self.Session() as session:
            recipients = sorted(event.payload["user_id"] for event in session.scalars(select(OutboxEvent)).all())
        self.assertEqual(recipients, sorted([str(SUPERVISOR_ID), str(EMPLOYEE_ID)]))

    def test_changes_land_in_the_activity_log(self):
        target = self._set().json()
        self.client.post(f"/api/v2/targets/{target['id']}/clear")
        with self.Session() as session:
            actions = set(session.scalars(select(V2AuditEvent.action).where(V2AuditEvent.project_id == PROJECT_ID)).all())
        self.assertEqual(actions, {"TARGET_SET", "TARGET_CLEARED"})


if __name__ == "__main__":
    unittest.main()
