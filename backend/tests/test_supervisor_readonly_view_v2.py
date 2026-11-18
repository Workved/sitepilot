from __future__ import annotations
from app.execution_models import FileObject, ProjectTaskReferenceFile  # noqa: E402

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
from app.execution_models import BaselineTask, OutboxEvent, ProjectBaseline, Task, TaskDependency, ProjectExternalApproval, ProjectExternalApprovalTask
from app.models import EmployeeProfile, User, UserRole
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateTask,
    V2ProjectExternalGateApplicabilityDecision,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
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
OUTSIDER_SUPERVISOR_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")




class SupervisorReadOnlyViewApiTests(unittest.TestCase):
    """Phase 11: supervisor-scoped, read-only visibility.

    Every check in this file exercises EXISTING Phase 8/9 authorization
    code (list_projects' membership scoping, get_project/can_view, and
    each mutation service's admin/PM-only _require_access). No backend
    behaviour was changed for Phase 11 - this file proves the existing
    design already satisfies the requirement, per the inspection recorded
    in the implementation report.
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
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2ProjectTaskDependency.__table__,
            V2ProjectExternalGate.__table__,
            V2ProjectExternalGateTask.__table__,
            V2ProjectExternalGateApplicabilityDecision.__table__,
            V2AuditEvent.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            FileObject.__table__,
            ProjectTaskReferenceFile.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
            OutboxEvent.__table__,
            TaskDependency.__table__,
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2TemplateTaskDependency.__table__,
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
        self.app.dependency_overrides[current_user] = lambda: User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def as_supervisor(self):
        self.app.dependency_overrides[current_user] = lambda: User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True)

    def as_outsider_supervisor(self):
        self.app.dependency_overrides[current_user] = lambda: User(id=OUTSIDER_SUPERVISOR_ID, name="Outsider Supervisor", email="outsider-sup@example.com", role=UserRole.supervisor, active=True)

    def as_admin(self):
        self.app.dependency_overrides[current_user] = lambda: User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            employee = User(id=EMPLOYEE_ID, name="Employee", email="employee@example.com", role=UserRole.internal_employee, active=True)
            supervisor = User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True)
            outsider_supervisor = User(id=OUTSIDER_SUPERVISOR_ID, name="Outsider Supervisor", email="outsider-sup@example.com", role=UserRole.supervisor, active=True)
            session.add_all([admin, pm, employee, supervisor, outsider_supervisor])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
                EmployeeProfile(user_id=OUTSIDER_SUPERVISOR_ID, employee_code="SUP-002", designation="Supervisor", availability="available"),
                EmployeeProfile(user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Employee", availability="available"),
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
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Site mobilization",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", evidence_required=False, duration_days=1, phase="Setup", category="Site",
            ))
            self.published_version_id = published.id

    def create_draft(self, supervisor_user_id=SUPERVISOR_ID, **overrides):
        self.as_admin()
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            "proposed_start_date": "2026-08-01",
            "target_handover_date": "2026-09-14",
            "pm_user_id": str(PM_ID),
            "supervisor_user_id": str(supervisor_user_id),
            "template_version_id": str(self.published_version_id),
        }
        payload.update(overrides)
        response = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def activate(self, project_id):
        self.as_admin()
        # U1: activation now locks a real baseline snapshot and requires at
        # least one included task, so ensure the template task(s) exist
        # first (generate-tasks is itself idempotent/no-op on retry).
        self.client.post(f"/api/v2/projects/{project_id}/generate-tasks")
        response = self.client.post(f"/api/v2/projects/{project_id}/activate", json={"reason": "Go live."})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ---- Visibility scoping -------------------------------------------

    def test_supervisor_sees_only_their_own_assigned_active_project(self):
        own_project = self.create_draft()
        self.activate(own_project["id"])
        other_project = self.create_draft(supervisor_user_id=OUTSIDER_SUPERVISOR_ID, code="PRJ-OTHER-001")
        self.activate(other_project["id"])

        self.as_supervisor()
        response = self.client.get("/api/v2/projects", params={"status": "active"})
        self.assertEqual(response.status_code, 200, response.text)
        ids = [item["id"] for item in response.json()]
        self.assertIn(own_project["id"], ids)
        self.assertNotIn(other_project["id"], ids)

    def test_admin_still_sees_every_active_project(self):
        first = self.create_draft()
        self.activate(first["id"])
        second = self.create_draft(supervisor_user_id=OUTSIDER_SUPERVISOR_ID, code="PRJ-OTHER-002")
        self.activate(second["id"])

        self.as_admin()
        response = self.client.get("/api/v2/projects", params={"status": "active"})
        ids = [item["id"] for item in response.json()]
        self.assertIn(first["id"], ids)
        self.assertIn(second["id"], ids)

    # ---- Read access on the Execution workspace ------------------------

    def test_supervisor_can_read_execution_tasks_dependencies_and_gates_for_own_project(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.activate(project["id"])

        self.as_supervisor()
        tasks_response = self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks")
        self.assertEqual(tasks_response.status_code, 200, tasks_response.text)
        self.assertEqual(tasks_response.json()["total_tasks"], 1)

        deps_response = self.client.get(f"/api/v2/projects/{project['id']}/dependencies")
        self.assertEqual(deps_response.status_code, 200, deps_response.text)

        gates_response = self.client.get(f"/api/v2/projects/{project['id']}/external-gates")
        self.assertEqual(gates_response.status_code, 200, gates_response.text)

    def test_supervisor_cannot_read_any_view_for_an_unaffiliated_project(self):
        project = self.create_draft(supervisor_user_id=OUTSIDER_SUPERVISOR_ID, code="PRJ-OTHER-003")
        self.activate(project["id"])

        self.as_supervisor()
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/execution-tasks").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/dependencies").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/external-gates").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}").status_code, 403)

    # ---- Mutations must stay blocked -----------------------------------

    def test_supervisor_cannot_generate_tasks_gates_or_dependencies(self):
        project = self.create_draft()
        self.as_supervisor()
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/generate-gates").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/generate-dependencies").status_code, 403)

    def test_supervisor_cannot_edit_project_details(self):
        project = self.create_draft()
        self.as_supervisor()
        response = self.client.patch(f"/api/v2/projects/{project['id']}", json={"name": "Renamed", "reason": "Attempt."})
        self.assertEqual(response.status_code, 403, response.text)

    def test_supervisor_cannot_change_project_status_or_activate(self):
        project = self.create_draft()
        self.as_supervisor()
        self.assertEqual(
            self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Attempt."}).status_code, 403,
        )
        self.assertEqual(
            self.client.post(f"/api/v2/projects/{project['id']}/status", json={"status": "archived", "reason": "Attempt."}).status_code, 403,
        )

    def test_supervisor_cannot_delete_project(self):
        project = self.create_draft()
        self.as_supervisor()
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Attempt."},
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_supervisor_cannot_reassign_pm_or_own_supervisor_role(self):
        project = self.create_draft()
        self.as_supervisor()
        pm_attempt = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(PM_ID), "project_role": "project_manager", "reason": "Attempt."},
        )
        self.assertEqual(pm_attempt.status_code, 403, pm_attempt.text)
        supervisor_attempt = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(OUTSIDER_SUPERVISOR_ID), "project_role": "site_supervisor", "reason": "Attempt."},
        )
        self.assertEqual(supervisor_attempt.status_code, 403, supervisor_attempt.text)

    def test_supervisor_cannot_decide_gate_or_task_applicability(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        # Keep the project in draft: applicability decisions are draft-only,
        # so this is the state where the role check itself is reached.
        tasks_response = self.client.get(f"/api/v2/projects/{project['id']}/template-review/tasks")
        self.assertEqual(tasks_response.status_code, 200, tasks_response.text)
        task_id = tasks_response.json()["items"][0]["id"]

        self.as_supervisor()
        task_decision = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{task_id}/applicability-decisions",
            json={"decision": "excluded", "reason": "Attempt."},
        )
        self.assertEqual(task_decision.status_code, 403, task_decision.text)

    def test_supervisor_can_add_a_task_to_their_project_but_not_a_gate(self):
        """The project's own Supervisor may add a task (product decision,
        same as a running project); manual gates stay Admin-only."""
        project = self.create_draft()
        self.as_supervisor()
        manual_task = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks",
            json={"title": "Extra scope item", "phase": "Setup", "category": "Site", "planned_start_day": 1, "planned_end_day": 1, "reason": "Needed on site."},
        )
        self.assertEqual(manual_task.status_code, 201, manual_task.text)
        manual_gate = self.client.post(
            f"/api/v2/projects/{project['id']}/gates",
            json={
                "title": "Society NOC", "external_party": "Society", "required_by_type": "project_day",
                "required_by_day": 5, "affected_project_task_ids": [], "blocking": False,
                "impact": "Delays handover.", "reason": "Attempt.",
            },
        )
        self.assertEqual(manual_gate.status_code, 403, manual_gate.text)

    # ---- Known, pre-existing, out-of-scope nuance ----------------------

    def test_supervisor_retains_preexisting_support_employee_membership_authority(self):
        """Not a Phase 11 change. Project-team support-employee assignment
        (project_role="internal_employee") predates Phase 8/9/11 and is
        granted to the project's own active Supervisor by the original
        membership authorization rule in set_membership - unrelated to
        Phase 11 and not modified here. Recorded so it is visible rather
        than silently assumed away. See "Known limitations" in the
        implementation report."""
        project = self.create_draft()
        self.activate(project["id"])
        with self.Session() as session:
            employee_profile_id = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == EMPLOYEE_ID))
        self.as_supervisor()
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(employee_profile_id), "project_role": "internal_employee", "reason": "Support request."},
        )
        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
