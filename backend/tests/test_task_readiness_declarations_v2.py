"""Plan Phase 3 (3a): readiness declarations.

Pins `TaskReadinessDeclarationService` against
real execution tasks produced by U1's baseline-lock activation flow.
Follows the same SQLite-ATTACHed-schema harness pattern as
`test_task_blockers_delays_v2.py` / `test_task_support_assignment_v2.py`.

- Declarations are an append-only advisory overlay: they never touch
  `Task.lifecycle_status`, and `task_readiness.py`'s derived projection is
  never read by/for a declaration.
- Readiness declarations: any active project member may declare; an
  unknown `status` is rejected (422); a non-member is rejected (403); two
  declarations for the same task both persist.
"""


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
    TaskReadinessDeclaration,
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
INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
SECOND_INTERNAL_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")


class TaskReadinessDeclarationApiTests(unittest.TestCase):
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
            TaskReadinessDeclaration.__table__,
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

    def act_as_internal(self) -> None:
        self.act_as(User(
            id=INTERNAL_ID, name="Internal One", email="internal1@example.com",
            role=UserRole.internal_employee, active=True,
        ))

    def act_as_second_internal(self) -> None:
        self.act_as(User(
            id=SECOND_INTERNAL_ID, name="Internal Two", email="internal2@example.com",
            role=UserRole.internal_employee, active=True,
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
            internal = User(
                id=INTERNAL_ID, name="Internal One", email="internal1@example.com",
                role=UserRole.internal_employee, active=True,
            )
            second_internal = User(
                id=SECOND_INTERNAL_ID, name="Internal Two", email="internal2@example.com",
                role=UserRole.internal_employee, active=True,
            )
            session.add_all([admin, pm, supervisor, outsider, internal, second_internal])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Site Assistant", availability="available",
                ),
                EmployeeProfile(
                    user_id=SECOND_INTERNAL_ID, employee_code="INT-002", designation="Site Assistant", availability="available",
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

    def employee_id_for(self, user_id: uuid.UUID) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id))

    def add_internal_member(self, project_id: str, user_id: uuid.UUID) -> None:
        self.act_as_pm()
        response = self.client.post(
            f"/api/v2/projects/{project_id}/memberships",
            json={
                "employee_id": str(self.employee_id_for(user_id)),
                "project_role": "internal_employee",
                "reason": "Add support staff.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def declare_readiness(self, project_id, task_id, status="ready", note=None):
        payload = {"status": status}
        if note is not None:
            payload["note"] = note
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/readiness-declarations", json=payload,
        )

    # ---- readiness declarations: happy path --------------------------------

    def test_active_member_declares_readiness(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.declare_readiness(project["id"], task.id, status="ready", note="Crew and materials on site.")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["note"], "Crew and materials on site.")
        self.assertEqual(body["declared_by"], str(SUPERVISOR_ID))

        with self.Session() as session:
            rows = session.scalars(select(TaskReadinessDeclaration).where(TaskReadinessDeclaration.task_id == task.id)).all()
            self.assertEqual(len(rows), 1)

            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id, OutboxEvent.event_type == "task.readiness_declared")
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "task")
            self.assertEqual(events[0].payload["status"], "ready")

    def test_readiness_declaration_rejects_unknown_status(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.declare_readiness(project["id"], task.id, status="unknown_status")
        self.assertEqual(response.status_code, 422, response.text)

    def test_readiness_declaration_rejects_non_member(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_outsider()
        response = self.declare_readiness(project["id"], task.id, status="issue")
        self.assertEqual(response.status_code, 403, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskReadinessDeclaration).limit(1)), None)

    def test_readiness_declarations_are_append_only(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        first = self.declare_readiness(project["id"], task.id, status="issue", note="Missing materials.")
        self.assertEqual(first.status_code, 200, first.text)

        second = self.declare_readiness(project["id"], task.id, status="ready", note="Materials arrived.")
        self.assertEqual(second.status_code, 200, second.text)

        self.assertNotEqual(first.json()["id"], second.json()["id"])

        with self.Session() as session:
            rows = session.scalars(
                select(TaskReadinessDeclaration).where(TaskReadinessDeclaration.task_id == task.id)
            ).all()
            self.assertEqual(len(rows), 2)
            statuses = sorted(row.status for row in rows)
            self.assertEqual(statuses, ["issue", "ready"])

    def test_readiness_declaration_never_touches_lifecycle_status(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.declare_readiness(project["id"], task.id, status="need_help")
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "planned")


if __name__ == "__main__":
    unittest.main()
