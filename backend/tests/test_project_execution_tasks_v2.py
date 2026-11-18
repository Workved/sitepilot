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
from app.execution_models import BaselineTask, OutboxEvent, ProjectBaseline, Task, TaskDependency, ProjectExternalApproval, ProjectExternalApprovalTask
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
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
OUTSIDER_PM_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class ProjectExecutionTasksApiTests(unittest.TestCase):
    """Phase 9: read-only task baseline for activated projects."""

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
            OutboxEvent.__table__,
            TaskDependency.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2ProjectExternalGateTask.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            outsider_pm = User(
                id=OUTSIDER_PM_ID, name="Outsider PM", email="outsider@example.com",
                role=UserRole.project_manager, active=True,
            )
            session.add_all([admin, pm, supervisor, outsider_pm])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_PM_ID, employee_code="PM-002", designation="PM", availability="available",
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
            session.add_all([
                V2TemplateTask(
                    template_version_id=published.id, code="T001", sequence_no=1, title="Site mobilization",
                    schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                    applicability="mandatory", evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ),
                V2TemplateTask(
                    template_version_id=published.id, code="T002", sequence_no=2, title="Electrical rough-in",
                    schedule_classification="execution", planned_start_day=2, planned_end_day=3,
                    applicability="conditional", evidence_required=True, duration_days=2, phase="Fit-out", category="Electrical",
                ),
            ])
            self.published_version_id = published.id

    def create_draft(self):
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
        response = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def activate(self, project_id):
        response = self.client.post(f"/api/v2/projects/{project_id}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_returns_task_baseline_for_activated_project_with_counts(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.activate(project["id"])

        response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["project_name"], "Futurex Fitout")
        self.assertEqual(body["total_tasks"], 2)
        self.assertEqual(body["included_task_count"], 2)
        self.assertEqual(body["excluded_task_count"], 0)
        self.assertEqual([task["code"] for task in body["tasks"]], ["T001", "T002"])
        self.assertEqual(body["tasks"][0]["lifecycle_status"], "draft")
        self.assertEqual(body["tasks"][1]["applicability"], "conditional")

    def test_blocks_projects_that_have_not_been_activated(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        # Project is still draft - never activated.
        response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("not been activated", response.json()["detail"])

    def test_activation_without_included_tasks_is_rejected(self):
        """U1: activation locks a real baseline snapshot and rejects a project
        with zero included tasks to snapshot. Creation now generates the
        snapshot automatically, so the reachable form of this state is every
        task excluded during review rather than never generating them."""
        project = self.create_draft()
        with self.Session.begin() as session:
            for task in session.scalars(select(V2ProjectTask).where(V2ProjectTask.project_id == uuid.UUID(project["id"]))):
                task.included = False
                task.decision_state = "excluded"
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 409, response.text)

    def test_unaffiliated_project_manager_cannot_view_another_projects_tasks(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.activate(project["id"])

        self.app.dependency_overrides[current_user] = lambda: User(
            id=OUTSIDER_PM_ID, name="Outsider PM", email="outsider@example.com",
            role=UserRole.project_manager, active=True,
        )
        response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        self.assertEqual(response.status_code, 403, response.text)

    def test_assigned_supervisor_can_view_the_task_baseline(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.activate(project["id"])

        self.app.dependency_overrides[current_user] = lambda: User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        )
        response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total_tasks"], 2)

    def test_unauthenticated_request_is_rejected(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.activate(project["id"])
        self.app.dependency_overrides.pop(current_user, None)
        response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        self.assertEqual(response.status_code, 401, response.text)

    def test_response_has_no_mutation_affordance_fields(self):
        """Sanity check that this read-only endpoint never returns anything
        resembling a status-change, evidence or assignment payload."""
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.activate(project["id"])
        response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        body = response.json()
        for task in body["tasks"]:
            self.assertNotIn("assigned_supervisor_id", task)
            self.assertNotIn("proof_url", task)
            self.assertNotIn("submitted_at", task)
            self.assertNotIn("status", task)  # only lifecycle_status/decision_state, never a mutable "status"


if __name__ == "__main__":
    unittest.main()
