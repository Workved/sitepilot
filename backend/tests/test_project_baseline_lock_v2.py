from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
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


class ProjectBaselineLockApiTests(unittest.TestCase):
    """U1: baseline lock and execution-layer task/dependency instantiation.

    Follows the SQLite-in-memory-with-ATTACHed-schema harness pattern
    established across the rest of the V2 project test suite.
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

    def _seed(self, task_count: int = 3, dependency_count: int = 2, conditional_last: bool = False):
        with self.Session.begin() as session:
            # Idempotent: a test may call _seed() a second time with
            # different task/dependency shape params (on top of setUp's
            # unconditional default-args call) to get a differently
            # shaped template without re-inserting the same fixed-id users.
            if session.get(User, ADMIN_ID) is None:
                admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
                pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
                supervisor = User(
                    id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                    role=UserRole.supervisor, active=True,
                )
                session.add_all([admin, pm, supervisor])
                session.flush()
                session.add_all([
                    EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                    EmployeeProfile(
                        user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                    ),
                ])
            # Unique code per call: a test may call _seed() a second time
            # (on top of setUp's default-args call) for a differently
            # shaped template, and V2Template.code is unique.
            template = V2Template(code=f"WORKVED-45-{uuid.uuid4().hex[:8]}", name="Workved 45 Day")
            session.add(template)
            session.flush()
            published = V2TemplateVersion(
                template_id=template.id, version_no=1, status="published", duration_days=45,
                content_hash="published-hash", is_current_published=True,
                created_by=ADMIN_ID, published_by=ADMIN_ID, published_at=datetime.now(timezone.utc),
            )
            session.add(published)
            session.flush()
            template_tasks = []
            for i in range(1, task_count + 1):
                applicability = "conditional" if (conditional_last and i == task_count) else "mandatory"
                template_tasks.append(V2TemplateTask(
                    template_version_id=published.id, code=f"T{i:03d}", sequence_no=i, title=f"Task {i}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability=applicability, task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ))
            session.add_all(template_tasks)
            session.flush()
            for i in range(dependency_count):
                session.add(V2TemplateTaskDependency(
                    template_version_id=published.id,
                    predecessor_task_id=template_tasks[i].id,
                    successor_task_id=template_tasks[i + 1].id,
                    dependency_type="finish_to_start", blocking=True,
                    rule_text=f"Rule {i + 1}", sequence_no=i + 1,
                ))
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

    def generate_tasks(self, project_id):
        response = self.client.post(f"/api/v2/projects/{project_id}/generate-tasks")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def generate_dependencies(self, project_id):
        response = self.client.post(f"/api/v2/projects/{project_id}/generate-dependencies")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def activate(self, project_id):
        return self.client.post(f"/api/v2/projects/{project_id}/activate", json={"reason": "Go live."})

    def change_status_active(self, project_id):
        return self.client.post(f"/api/v2/projects/{project_id}/status", json={"status": "active", "reason": "Go live."})

    # ---- Happy path -------------------------------------------------

    def test_activation_locks_baseline_and_instantiates_tasks_via_activate_endpoint(self):
        project = self.create_draft()
        self.generate_tasks(project["id"])
        self.generate_dependencies(project["id"])

        response = self.activate(project["id"])
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            project_id = uuid.UUID(project["id"])
            baselines = list(session.scalars(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id)))
            self.assertEqual(len(baselines), 1)
            baseline = baselines[0]
            self.assertEqual(baseline.task_count, 3)
            self.assertEqual(baseline.dependency_count, 2)

            baseline_tasks = list(session.scalars(select(BaselineTask).where(BaselineTask.baseline_id == baseline.id)))
            self.assertEqual(len(baseline_tasks), 3)
            self.assertTrue(all(bt.content_hash for bt in baseline_tasks))

            tasks = list(session.scalars(select(Task).where(Task.project_id == project_id)))
            self.assertEqual(len(tasks), 3)
            self.assertTrue(all(t.lifecycle_status == "planned" for t in tasks))
            self.assertTrue(all(t.baseline_id == baseline.id for t in tasks))
            self.assertEqual({t.original_code for t in tasks}, {"T001", "T002", "T003"})

            deps = list(session.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id)))
            self.assertEqual(len(deps), 2)
            self.assertTrue(all(d.created_from_baseline for d in deps))
            task_ids = {t.id for t in tasks}
            self.assertTrue(all(d.predecessor_task_id in task_ids and d.successor_task_id in task_ids for d in deps))

            audit = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_BASELINE_LOCKED"))
            self.assertIsNotNone(audit)
            self.assertEqual(audit.after_json["task_count"], 3)

    def test_activation_locks_baseline_via_status_endpoint(self):
        """Both draft->active code paths must call the same baseline-lock
        service, or one silently produces an active project with no
        baseline (the exact gap the plan flags)."""
        project = self.create_draft()
        self.generate_tasks(project["id"])

        response = self.change_status_active(project["id"])
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            project_id = uuid.UUID(project["id"])
            baseline = session.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id))
            self.assertIsNotNone(baseline)
            self.assertEqual(baseline.task_count, 3)
            tasks = list(session.scalars(select(Task).where(Task.project_id == project_id)))
            self.assertEqual(len(tasks), 3)

    def test_excluded_tasks_are_not_copied_into_baseline(self):
        self._seed(task_count=3, dependency_count=2, conditional_last=True)
        project = self.create_draft()
        self.generate_tasks(project["id"])

        with self.Session.begin() as session:
            excluded_task = session.scalar(select(V2ProjectTask).where(V2ProjectTask.original_code == "T003"))
            excluded_task.included = False
            excluded_task.decision_state = "excluded"

        response = self.activate(project["id"])
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            project_id = uuid.UUID(project["id"])
            baseline = session.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id))
            self.assertEqual(baseline.task_count, 2)
            baseline_tasks = list(session.scalars(select(BaselineTask).where(BaselineTask.baseline_id == baseline.id)))
            self.assertEqual({bt.original_code for bt in baseline_tasks}, {"T001", "T002"})
            tasks = list(session.scalars(select(Task).where(Task.project_id == project_id)))
            self.assertEqual({t.original_code for t in tasks}, {"T001", "T002"})

    # ---- Edge cases ---------------------------------------------------

    def test_zero_included_tasks_rejects_activation(self):
        project = self.create_draft()
        # Creation now generates the snapshot, so exclude every task instead
        # of skipping generation - the guard under test is "nothing included
        # to lock", which is still reachable through review decisions.
        with self.Session.begin() as session:
            for task in session.scalars(select(V2ProjectTask).where(V2ProjectTask.project_id == uuid.UUID(project["id"]))):
                task.included = False
                task.decision_state = "excluded"
        response = self.activate(project["id"])
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            project_id = uuid.UUID(project["id"])
            self.assertIsNone(session.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id)))
            self.assertEqual(session.get(V2Project, project_id).status, "draft")

    def test_reactivating_already_active_project_does_not_create_second_baseline(self):
        project = self.create_draft()
        self.generate_tasks(project["id"])
        first = self.activate(project["id"])
        self.assertEqual(first.status_code, 200, first.text)

        second = self.activate(project["id"])
        self.assertEqual(second.status_code, 409, second.text)

        with self.Session() as session:
            project_id = uuid.UUID(project["id"])
            count = session.scalar(select(func.count()).select_from(ProjectBaseline).where(ProjectBaseline.project_id == project_id))
            self.assertEqual(count, 1)

    def test_activation_without_active_pm_or_supervisor_is_rejected_and_creates_no_baseline(self):
        project = self.create_draft()
        self.generate_tasks(project["id"])
        supervisor_membership = next(m for m in project["memberships"] if m["project_role"] == "site_supervisor")
        end_response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships/{supervisor_membership['id']}/end",
            json={"reason": "Testing missing accountable role."},
        )
        self.assertEqual(end_response.status_code, 200, end_response.text)

        response = self.activate(project["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Site Supervisor", response.json()["detail"])
        with self.Session() as session:
            project_id = uuid.UUID(project["id"])
            self.assertIsNone(session.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id)))

    # ---- DB-level immutability -----------------------------------------

    def test_baseline_tasks_are_immutable_at_the_database_level(self):
        """Emulates the Postgres BEFORE UPDATE/DELETE trigger declared in
        supabase/migrations/202608020001_v2_project_baseline_and_tasks.sql
        using an equivalent SQLite trigger, since the unit-test harness runs
        against SQLite. This proves the *mechanism* (a trigger unconditionally
        rejecting mutation) behaves as intended; the production migration
        installs the same logic as a Postgres PL/pgSQL trigger function."""
        project = self.create_draft()
        self.generate_tasks(project["id"])
        response = self.activate(project["id"])
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            baseline_task = session.scalar(select(BaselineTask))
            self.assertIsNotNone(baseline_task)
            baseline_task_id = baseline_task.id

        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER siteops_v2.trg_baseline_tasks_immutable_update "
                "BEFORE UPDATE ON baseline_tasks "
                "BEGIN SELECT RAISE(ABORT, 'baseline_tasks rows are immutable once written'); END"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER siteops_v2.trg_baseline_tasks_immutable_delete "
                "BEFORE DELETE ON baseline_tasks "
                "BEGIN SELECT RAISE(ABORT, 'baseline_tasks rows are immutable once written'); END"
            )

        # Raw driver SQL bypasses the ORM's UUID type decorator, which
        # stores ids as undashed 32-char hex on SQLite - so the WHERE
        # clause must match that on-disk form (.hex), not str()'s dashed
        # form, or it silently matches zero rows and the trigger never fires.
        with self.engine.connect() as connection:
            with self.assertRaises(Exception):
                connection.exec_driver_sql(
                    "UPDATE siteops_v2.baseline_tasks SET title = 'tampered' WHERE id = ?",
                    (baseline_task_id.hex,),
                )

        with self.engine.connect() as connection:
            with self.assertRaises(Exception):
                connection.exec_driver_sql(
                    "DELETE FROM siteops_v2.baseline_tasks WHERE id = ?",
                    (baseline_task_id.hex,),
                )

        with self.Session() as session:
            still_there = session.get(BaselineTask, baseline_task_id)
            self.assertIsNotNone(still_there)
            self.assertNotEqual(still_there.title, "tampered")


if __name__ == "__main__":
    unittest.main()
