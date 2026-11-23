from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

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
from app.execution_models import (
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    BaselineTask,
    FileObject,
    OutboxEvent,
    ProjectBaseline,
    Task,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskEvidence,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
    V2ProjectExternalGateTask,
)
from app.routes.execution_tasks_v2 import router as execution_tasks_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
VENDOR_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


class TaskBlockersDelaysApiTests(unittest.TestCase):
    """U5: blocker and delay capture (R5/BR-010), against real execution
    tasks produced by U1's baseline-lock activation flow.

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_progress_evidence_v2.py.
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
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__,
            TaskEvidence.__table__,
            TaskVerification.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            OutboxEvent.__table__,
            TaskSupportAssignment.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2ProjectExternalGateTask.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(projects_router)
        self.app.include_router(execution_tasks_router)

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

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    def act_as_outsider(self) -> None:
        self.act_as(User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work). Also seeds an OUTSIDER user
        with an EmployeeProfile but no membership on the created project, to
        exercise the "no active project membership" edge cases."""
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

            template_task = V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", task_class="standard", task_kind="work",
                evidence_required=False, duration_days=1, phase="Setup", category="Site",
            )
            session.add(template_task)
            session.flush()
            self.published_version_id = published.id

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

    def task_t001(self, project_id: str) -> Task:
        with self.Session() as session:
            return session.scalar(
                select(Task).where(Task.project_id == uuid.UUID(project_id), Task.original_code == "T001")
            )

    def transition(self, project_id: str, task_id, target_status: str, reason: str | None = None):
        body = {"target_status": target_status}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    def move_to_in_progress(self, project_id: str, task_id) -> None:
        """Test-setup helper only - moves a task to in_progress via U2's
        TaskLifecycleService (through the real HTTP route) so U5's
        blocker/delay tests can prove they never touch lifecycle_status."""
        self.act_as_supervisor()
        r1 = self.transition(project_id, task_id, "ready")
        self.assertEqual(r1.status_code, 200, r1.text)
        r2 = self.transition(project_id, task_id, "in_progress", reason="Crew on site.")
        self.assertEqual(r2.status_code, 200, r2.text)

    def create_blocker(self, project_id, task_id, type_="material", description="Waiting on rebar delivery.", owner_employee_id=None):
        payload = {"type": type_, "description": description}
        if owner_employee_id is not None:
            payload["owner_employee_id"] = str(owner_employee_id)
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/blockers", json=payload)

    def resolve_blocker(self, project_id, task_id, blocker_id):
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/blockers/{blocker_id}/resolve")

    def create_delay(self, project_id, task_id, responsibility_type="internal", reason="Crew shortage.", impact_days=2, responsible_vendor_id=None):
        payload = {
            "responsibility_type": responsibility_type,
            "reason": reason,
            "impact_days": impact_days,
        }
        if responsible_vendor_id is not None:
            payload["responsible_vendor_id"] = str(responsible_vendor_id)
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/delays", json=payload)

    # ---- happy path: blockers ---------------------------------------------

    def test_log_blocker_creates_row(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.create_blocker(project["id"], task.id, type_="material", description="Waiting on rebar delivery.")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["type"], "material")
        self.assertEqual(body["description"], "Waiting on rebar delivery.")
        self.assertIsNone(body["resolved_at"])
        self.assertIsNone(body["resolved_by"])

        with self.Session() as session:
            rows = session.scalars(select(TaskBlocker).where(TaskBlocker.task_id == task.id)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].type, "material")
            # the reporter is recorded for every
            # channel, the Web App included.
            self.assertEqual(rows[0].reported_by, SUPERVISOR_ID)

    def test_resolve_blocker_sets_resolved_at_and_resolved_by(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        created = self.create_blocker(project["id"], task.id)
        self.assertEqual(created.status_code, 200, created.text)
        blocker_id = created.json()["id"]

        response = self.resolve_blocker(project["id"], task.id, blocker_id)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNotNone(body["resolved_at"])
        self.assertEqual(body["resolved_by"], str(SUPERVISOR_ID))

        with self.Session() as session:
            row = session.get(TaskBlocker, uuid.UUID(blocker_id))
            self.assertIsNotNone(row.resolved_at)
            self.assertEqual(row.resolved_by, SUPERVISOR_ID)

    def test_resolve_already_resolved_blocker_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        created = self.create_blocker(project["id"], task.id)
        blocker_id = created.json()["id"]
        first = self.resolve_blocker(project["id"], task.id, blocker_id)
        self.assertEqual(first.status_code, 200, first.text)

        second = self.resolve_blocker(project["id"], task.id, blocker_id)
        self.assertEqual(second.status_code, 409, second.text)

    def test_only_accountable_supervisor_pm_or_admin_can_resolve_blocker(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        created = self.create_blocker(project["id"], task.id)
        blocker_id = created.json()["id"]

        self.act_as_outsider()
        response = self.resolve_blocker(project["id"], task.id, blocker_id)
        self.assertEqual(response.status_code, 403, response.text)

        self.act_as_pm()
        response = self.resolve_blocker(project["id"], task.id, blocker_id)
        self.assertEqual(response.status_code, 200, response.text)

    # ---- happy path: delays ------------------------------------------------

    def test_log_delay_creates_row(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_pm()
        response = self.create_delay(
            project["id"], task.id, responsibility_type="approval", reason="Awaiting client sign-off.", impact_days=3,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["responsibility_type"], "approval")
        self.assertEqual(body["impact_days"], 3)
        self.assertIsNone(body["responsible_vendor_id"])

        with self.Session() as session:
            rows = session.scalars(select(TaskDelayEvent).where(TaskDelayEvent.task_id == task.id)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].reason, "Awaiting client sign-off.")

    # ---- edge case: no mutual exclusion with lifecycle_status --------------

    def test_task_can_be_in_progress_with_unresolved_blocker_and_delay_simultaneously(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.move_to_in_progress(project["id"], task.id)

        self.act_as_supervisor()
        blocker_response = self.create_blocker(project["id"], task.id)
        self.assertEqual(blocker_response.status_code, 200, blocker_response.text)

        delay_response = self.create_delay(project["id"], task.id)
        self.assertEqual(delay_response.status_code, 200, delay_response.text)

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "in_progress")

            blockers = session.scalars(select(TaskBlocker).where(TaskBlocker.task_id == task.id)).all()
            self.assertEqual(len(blockers), 1)
            self.assertIsNone(blockers[0].resolved_at)

            delays = session.scalars(select(TaskDelayEvent).where(TaskDelayEvent.task_id == task.id)).all()
            self.assertEqual(len(delays), 1)

        # And the task remains free to keep transitioning forward - blocker/
        # delay presence never gated the lifecycle machine.
        self.act_as_supervisor()
        progress_response = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{task.id}/progress", data={"note": "Work done despite open blocker."},
        )
        self.assertEqual(progress_response.status_code, 200, progress_response.text)
        r = self.transition(project["id"], task.id, "submitted", reason="Work submitted despite open blocker.")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["lifecycle_status"], "submitted")

    # ---- edge case: vendor id required-when-vendor validation --------------

    def test_delay_vendor_responsibility_without_vendor_id_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_pm()
        response = self.create_delay(project["id"], task.id, responsibility_type="vendor", responsible_vendor_id=None)
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskDelayEvent).limit(1)), None)

    def test_delay_non_vendor_responsibility_with_vendor_id_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_pm()
        response = self.create_delay(
            project["id"], task.id, responsibility_type="internal", responsible_vendor_id=VENDOR_ID,
        )
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskDelayEvent).limit(1)), None)

    def test_delay_vendor_responsibility_with_vendor_id_succeeds(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_pm()
        response = self.create_delay(
            project["id"], task.id, responsibility_type="vendor", reason="Vendor missed delivery window.",
            responsible_vendor_id=VENDOR_ID,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["responsible_vendor_id"], str(VENDOR_ID))

    # ---- error path: no project membership ---------------------------------

    def test_actor_with_no_active_membership_cannot_log_blocker(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_outsider()
        response = self.create_blocker(project["id"], task.id)
        self.assertEqual(response.status_code, 403, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskBlocker).limit(1)), None)

    def test_actor_with_no_active_membership_cannot_resolve_blocker(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        created = self.create_blocker(project["id"], task.id)
        blocker_id = created.json()["id"]

        self.act_as_outsider()
        response = self.resolve_blocker(project["id"], task.id, blocker_id)
        self.assertEqual(response.status_code, 403, response.text)

    def test_actor_with_no_active_membership_cannot_log_delay(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_outsider()
        response = self.create_delay(project["id"], task.id)
        self.assertEqual(response.status_code, 403, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskDelayEvent).limit(1)), None)


if __name__ == "__main__":
    unittest.main()
