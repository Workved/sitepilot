"""U14: starting a task ahead of its planned start date requires a reason.

Deliberately a separate file from test_task_lifecycle_transitions_v2.py.
That file pins its project start date in the past, so every one of its tasks
is already late and the early-start branch is unreachable from it - a green
run there proves nothing about this unit. Every project here starts in the
future, so its tasks are genuinely early.
"""


from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

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
    TaskApprovalDecision,
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
    V2ProjectExternalGateTask,
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
)
from app.routes.execution_tasks_v2 import router as execution_tasks_router
from app.routes.projects_v2 import router as projects_router
from tests.template_reference_tables import TEMPLATE_REFERENCE_LINK_TABLES
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")

# Far enough ahead that no timezone ambiguity in the "is this early?"
# comparison can reach it - the service's grace band is a single day.
DAYS_AHEAD = 30


def as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on DateTime(timezone=True) columns; the values
    written are always UTC, so read them back as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class TaskEarlyStartApiTests(unittest.TestCase):
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
            # Postgres's btrim(); SQLite has no such builtin.
            dbapi_connection.create_function(
                "btrim", 1, lambda value: value.strip() if value is not None else None
            )

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
            OutboxEvent.__table__,
            # The task list and detail endpoints summarize blockers, delays
            # and approval decisions, so those tables must exist for a read
            # of either to run at all.
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskApprovalDecision.__table__,
            TaskSupportAssignment.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__, *TEMPLATE_REFERENCE_LINK_TABLES,
            TaskEvidence.__table__,
            TaskVerification.__table__,
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

    # ---- actors --------------------------------------------------------

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_admin(self) -> None:
        self.act_as(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Two independent work tasks (no dependency edges), so a test can
        start either one without first satisfying a predecessor."""
        with self.Session.begin() as session:
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
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor",
                    availability="available",
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

            # T001 plans day 1, T002 plans day 20 - the plan's verification
            # case is "a task planned for day 20 started on day 5".
            session.add_all([
                V2TemplateTask(
                    template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                    schedule_classification="execution", planned_start_day=1, planned_end_day=2,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=2, phase="Setup", category="Site",
                ),
                V2TemplateTask(
                    template_version_id=published.id, code="T002", sequence_no=2, title="Task T002",
                    schedule_classification="execution", planned_start_day=20, planned_end_day=22,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=3, phase="Setup", category="Site",
                ),
            ])
            self.published_version_id = published.id

    # ---- harness -------------------------------------------------------

    def create_draft(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            "proposed_start_date": (date.today() + timedelta(days=DAYS_AHEAD)).isoformat(),
            "pm_user_id": str(PM_ID),
            "supervisor_user_id": str(SUPERVISOR_ID),
            "template_version_id": str(self.published_version_id),
        }
        payload.update(overrides)
        response = self.client.post("/api/v2/projects", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def activate_project(self, **overrides) -> dict:
        project = self.create_draft(**overrides)
        for step in ("generate-tasks", "generate-dependencies", "activate"):
            body = {"reason": "Go live."} if step == "activate" else None
            response = self.client.post(f"/api/v2/projects/{project['id']}/{step}", json=body)
            self.assertEqual(response.status_code, 200, response.text)
        return project

    def tasks_by_code(self, project_id: str) -> dict[str, Task]:
        with self.Session() as session:
            rows = session.scalars(select(Task).where(Task.project_id == uuid.UUID(project_id))).all()
            return {t.original_code: t for t in rows}

    def transition(self, project_id: str, task_id, target_status: str, reason: str | None = None):
        body: dict = {"target_status": target_status}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    def set_planned_start(self, task_id, value: date | None) -> None:
        """Repoint one task's planned start without re-deriving the whole
        schedule - the derivation rule is U9's and is tested there; what
        matters here is only how the transition reads the resulting date."""
        with self.Session.begin() as session:
            task = session.get(Task, task_id)
            task.planned_start_date = value
            if value is None:
                task.planned_end_date = None

    def start(self, project_id: str, task_id, reason: str | None = None):
        ready = self.transition(project_id, task_id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        return self.transition(project_id, task_id, "in_progress", reason=reason)

    # ---- early start is refused without a reason ------------------------

    def test_starting_before_planned_start_without_a_reason_is_refused(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.act_as_supervisor()

        response = self.start(project["id"], t001.id)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("reason is required", response.text)

        with self.Session() as session:
            task = session.get(Task, t001.id)
            # Refused before anything was written, exactly like cancellation.
            self.assertEqual(task.lifecycle_status, "ready")
            self.assertIsNone(task.actual_start_at)
            self.assertIsNone(task.early_start_reason)

    def test_starting_before_planned_start_with_a_reason_succeeds(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.act_as_supervisor()

        response = self.start(project["id"], t002.id, reason="Client released the floor early.")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["lifecycle_status"], "in_progress")

    def test_early_start_reason_is_persisted_and_audited(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.act_as_supervisor()
        reason = "Scaffold crew freed up three weeks ahead of plan."

        self.assertEqual(self.start(project["id"], t002.id, reason=reason).status_code, 200)

        with self.Session() as session:
            task = session.get(Task, t002.id)
            self.assertEqual(task.early_start_reason, reason)
            event = session.scalar(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_type == "task",
                    V2AuditEvent.entity_id == t002.id,
                    V2AuditEvent.after_json["lifecycle_status"].as_string() == "in_progress",
                )
            )
            self.assertIsNotNone(event)
            self.assertEqual(event.reason, reason)
            self.assertEqual(event.after_json.get("early_start_reason"), reason)

    # ---- starts that are not early --------------------------------------

    def test_starting_on_the_planned_start_date_needs_no_reason(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.set_planned_start(t001.id, date.today())
        self.act_as_supervisor()

        response = self.start(project["id"], t001.id)
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            self.assertIsNone(session.get(Task, t001.id).early_start_reason)

    def test_starting_after_the_planned_start_date_needs_no_reason(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.set_planned_start(t001.id, date.today() - timedelta(days=5))
        self.act_as_supervisor()

        response = self.start(project["id"], t001.id)
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            self.assertIsNone(session.get(Task, t001.id).early_start_reason)

    def test_a_task_with_no_planned_start_date_needs_no_reason(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.set_planned_start(t001.id, None)
        self.act_as_supervisor()

        response = self.start(project["id"], t001.id)
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            task = session.get(Task, t001.id)
            self.assertIsNone(task.early_start_reason)
            self.assertIsNotNone(task.actual_start_at)

    # ---- what an early start records ------------------------------------

    def test_an_early_start_records_its_actual_start_as_today(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.act_as_supervisor()

        before = datetime.now(timezone.utc)
        self.assertEqual(
            self.start(project["id"], t002.id, reason="Materials landed early.").status_code, 200,
        )
        after = datetime.now(timezone.utc)

        with self.Session() as session:
            task = session.get(Task, t002.id)
            actual_start = as_utc(task.actual_start_at)
            self.assertGreaterEqual(actual_start, before)
            self.assertLessEqual(actual_start, after)
            # The whole point: the actual is when work began, not the date
            # the plan said it would.
            self.assertLess(actual_start.date(), task.planned_start_date)

    def test_an_early_start_leaves_the_baseline_day_offsets_unchanged(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        baseline = (t002.planned_start_day, t002.planned_end_day, t002.planned_start_date, t002.planned_end_date)
        self.assertEqual(baseline[0], 20)
        self.act_as_supervisor()

        self.assertEqual(
            self.start(project["id"], t002.id, reason="Access granted early.").status_code, 200,
        )

        with self.Session() as session:
            task = session.get(Task, t002.id)
            self.assertEqual(
                (task.planned_start_day, task.planned_end_day, task.planned_start_date, task.planned_end_date),
                baseline,
            )

    # ---- the task API carries the planned dates --------------------------

    def test_task_list_and_detail_expose_the_planned_dates(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        start = (date.today() + timedelta(days=DAYS_AHEAD + 19)).isoformat()
        end = (date.today() + timedelta(days=DAYS_AHEAD + 21)).isoformat()

        listing = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(listing.status_code, 200, listing.text)
        row = next(item for item in listing.json() if item["original_code"] == "T002")
        self.assertEqual(row["planned_start_date"], start)
        self.assertEqual(row["planned_end_date"], end)

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t002.id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["planned_start_date"], start)
        self.assertEqual(detail.json()["planned_end_date"], end)

    # ---- the reason is readable, not just recorded ------------------------

    def test_the_detail_response_exposes_the_early_start_reason(self):
        """The reason was written to the row and to the audit event and then
        exposed on no read schema at all - captured from the user and
        readable by nobody. A stored fact with no read path is indis-
        tinguishable from one that was never stored."""
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.act_as_supervisor()
        reason = "Client released the floor three weeks early."

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t002.id}")
        self.assertIsNone(detail.json()["early_start_reason"])

        self.assertEqual(self.start(project["id"], t002.id, reason=reason).status_code, 200)

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t002.id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["early_start_reason"], reason)

    def test_an_ordinary_start_leaves_the_early_start_reason_empty(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.set_planned_start(t001.id, date.today())
        self.act_as_supervisor()

        self.assertEqual(self.start(project["id"], t001.id).status_code, 200)

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        self.assertIsNone(detail.json()["early_start_reason"])


if __name__ == "__main__":
    unittest.main()
