"""U15: readiness and variance travel with the task API.

The board must not recompute readiness. A second copy of the dependency and
approval rules in the frontend would drift from the engine the backend
enforces, and a board that disagrees with the portal is worse than no board.
So these tests pin the payload, not the arithmetic - `test_task_readiness_v2.py`
already owns the engine's behaviour, and one test here asserts the response
agrees with that engine rather than restating its rules.

Three things are pinned that a naive implementation gets wrong:

- **The list resolves readiness in one batched pass.** The obvious
  implementation calls a per-task readiness function inside the response
  loop, which is an N+1 that grows with the project. Counted with a
  `before_cursor_execute` listener, the same technique
  `test_task_readiness_v2.py` uses - a timing assertion passes on a fast
  machine no matter how many queries ran.
- **Internal-employee filtering is unchanged.** Readiness must not become a
  side channel that leaks tasks the actor may not see.
- **Exposing readiness changes no status.** Readiness is advisory this
  release (R5, KTD1); reading the list or the detail must leave every
  lifecycle status exactly where it was.

Same SQLite-ATTACHed-schema harness as `test_execution_tasks_read_v2.py`, so
these assertions prove the response shape, not the migration's constraints.
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
    BaselineTask,
    FileObject,
    OutboxEvent,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    SupportAssignmentChange,
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
    ProjectRoleChange,
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
from app.services.task_delay_variance import variance_for_task
from app.services.task_readiness import BLOCKED, READY, REASON_APPROVAL, REASON_DEPENDENCY, TaskReadinessService
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
INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")

# The project starts well in the past, so every task's planned end has
# already passed and variance is deterministically "late" rather than
# depending on the day the suite happens to run.
DAYS_BEHIND = 40


class ReadinessReadApiTestCase(unittest.TestCase):
    """Two-task project (T001 -> T002, blocking finish_to_start) plus an
    Internal Employee who can be support-assigned to one of them."""

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
            # The gate tables' broad-text CHECK uses Postgres's btrim(),
            # which SQLite has no builtin for. Same shim as the other v2
            # route tests.
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
            ProjectRoleChange.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectTaskReferenceFile.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
            TaskDependency.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__, *TEMPLATE_REFERENCE_LINK_TABLES,
            TaskEvidence.__table__,
            TaskVerification.__table__,
            TaskApprovalDecision.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskSupportAssignment.__table__,
            SupportAssignmentChange.__table__,
            OutboxEvent.__table__,
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
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True
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

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    def act_as_internal(self) -> None:
        self.act_as(User(
            id=INTERNAL_ID, name="Internal One", email="internal1@example.com",
            role=UserRole.internal_employee, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        with self.Session.begin() as session:
            session.add_all([
                User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
                User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True),
                User(
                    id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                    role=UserRole.supervisor, active=True,
                ),
                User(
                    id=INTERNAL_ID, name="Internal One", email="internal1@example.com",
                    role=UserRole.internal_employee, active=True,
                ),
            ])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor",
                    availability="available",
                ),
                EmployeeProfile(
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Site Assistant",
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

            template_tasks = []
            for i, code in enumerate(("T001", "T002"), start=1):
                template_tasks.append(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ))
            session.add_all(template_tasks)
            session.flush()
            session.add(V2TemplateTaskDependency(
                template_version_id=published.id,
                predecessor_task_id=template_tasks[0].id, successor_task_id=template_tasks[1].id,
                dependency_type="finish_to_start", blocking=True, rule_text="Rule 1", sequence_no=1,
            ))
            self.published_version_id = published.id

    # ---- helpers -------------------------------------------------------

    def activate_project(self, name: str = "Futurex Fitout") -> dict:
        start = date.today() - timedelta(days=DAYS_BEHIND)
        self.act_as_admin()
        response = self.client.post("/api/v2/projects", json={
            "project_name": name, "client": "Example Client", "location": "Mumbai",
            "proposed_start_date": start.isoformat(),
            "target_handover_date": (start + timedelta(days=45)).isoformat(),
            "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
            "template_version_id": str(self.published_version_id),
        })
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        for step in ("generate-tasks", "generate-dependencies"):
            step_response = self.client.post(f"/api/v2/projects/{project['id']}/{step}")
            self.assertEqual(step_response.status_code, 200, step_response.text)
        activate = self.client.post(
            f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."}
        )
        self.assertEqual(activate.status_code, 200, activate.text)
        return project

    def tasks_by_code(self, project_id: str) -> dict[str, Task]:
        with self.Session() as session:
            rows = session.scalars(select(Task).where(Task.project_id == uuid.UUID(project_id))).all()
            return {task.original_code: task for task in rows}

    def employee_id_for(self, user_id: uuid.UUID) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id))

    def add_internal_member(self, project_id: str) -> None:
        self.act_as_pm()
        response = self.client.post(f"/api/v2/projects/{project_id}/memberships", json={
            "employee_id": str(self.employee_id_for(INTERNAL_ID)),
            "project_role": "internal_employee",
            "reason": "Add support staff.",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def assign_support(self, project_id: str, task_id) -> None:
        self.act_as_supervisor()
        response = self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments",
            json={"employee_id": str(self.employee_id_for(INTERNAL_ID)), "responsibility": "Material staging."},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def cover_task_with_approval(
        self, project_id: str, task_id, *, status: str = "unassigned", blocking: bool = True
    ) -> uuid.UUID:
        """An execution-layer external approval mapped to one task.

        Inserted directly rather than driven through gate instantiation: the
        approval's own creation path is U11/U14's subject, and what this file
        pins is that the reason reaches the response naming this approval.
        """
        approval_id = uuid.uuid4()
        with self.Session.begin() as session:
            session.add(ProjectExternalApproval(
                id=approval_id,
                project_id=uuid.UUID(project_id),
                project_gate_id=uuid.uuid4(),
                status=status,
                blocking=blocking,
                coverage_state="exact",
            ))
            session.flush()
            session.add(ProjectExternalApprovalTask(
                id=uuid.uuid4(),
                project_id=uuid.UUID(project_id),
                approval_id=approval_id,
                task_id=task_id,
            ))
        return approval_id

    def add_unresolved_approval(self, project_id: str, coverage_text: str) -> uuid.UUID:
        """An approval whose coverage could not be resolved (R10).

        It has no coverage links by definition, so it can never surface as a
        task's readiness reason - only as the project-level signal.
        """
        approval_id = uuid.uuid4()
        with self.Session.begin() as session:
            session.add(ProjectExternalApproval(
                id=approval_id,
                project_id=uuid.UUID(project_id),
                project_gate_id=uuid.uuid4(),
                status="unassigned",
                blocking=True,
                coverage_state="unresolved",
                coverage_text=coverage_text,
            ))
        return approval_id

    def list_tasks(self, project_id: str) -> dict[str, dict]:
        response = self.client.get(f"/api/v2/projects/{project_id}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        return {row["original_code"]: row for row in response.json()}

    def detail(self, project_id: str, task_id) -> dict:
        response = self.client.get(f"/api/v2/projects/{project_id}/tasks/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class ReadinessOnTheTaskListTests(ReadinessReadApiTestCase):
    def test_the_list_carries_readiness_for_every_task(self):
        project = self.activate_project()
        rows = self.list_tasks(project["id"])
        self.assertEqual(set(rows), {"T001", "T002"})
        for code, row in rows.items():
            with self.subTest(code=code):
                self.assertIn("readiness", row)
                self.assertIn("state", row["readiness"])
        # T001 has nothing in front of it; T002 waits on T001's finish.
        self.assertEqual(rows["T001"]["readiness"]["state"], READY)
        self.assertEqual(rows["T002"]["readiness"]["state"], BLOCKED)

    def test_a_blocking_reason_on_the_list_names_the_specific_predecessor(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        reasons = self.list_tasks(project["id"])["T002"]["readiness"]["reasons"]
        self.assertEqual(len(reasons), 1)
        self.assertEqual(reasons[0]["kind"], REASON_DEPENDENCY)
        self.assertEqual(reasons[0]["subject_id"], str(t001.id))
        self.assertIn("T001", reasons[0]["detail"])
        self.assertTrue(reasons[0]["blocking"])

    def test_the_list_carries_each_tasks_computed_variance(self):
        project = self.activate_project()
        rows = self.list_tasks(project["id"])
        tasks = self.tasks_by_code(project["id"])
        for code, row in rows.items():
            with self.subTest(code=code):
                expected = variance_for_task(tasks[code])
                self.assertEqual(row["variance"]["status"], expected.status)
                self.assertEqual(row["variance"]["variance_days"], expected.variance_days)
                self.assertEqual(row["variance"]["days"], expected.days)
                self.assertEqual(row["variance"]["measured_against"], expected.measured_against)
        # The project started 40 days ago against a 45-day template, so both
        # planned ends are behind us and the variance is unambiguously late.
        self.assertEqual(rows["T001"]["variance"]["status"], "late")
        self.assertGreater(rows["T001"]["variance"]["variance_days"], 0)
        self.assertEqual(rows["T001"]["variance"]["measured_against"], "today")

    def test_the_list_carries_the_planned_dates_and_the_actuals_together(self):
        """One payload for the board and U16's timeline - the promise and
        what execution actually recorded against it."""
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        self.act_as_supervisor()
        self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{tasks['T001'].id}/status",
            json={"target_status": "ready"},
        )
        self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{tasks['T001'].id}/status",
            json={"target_status": "in_progress"},
        )
        row = self.list_tasks(project["id"])["T001"]
        self.assertIsNotNone(row["planned_start_date"])
        self.assertIsNotNone(row["planned_end_date"])
        self.assertIsNotNone(row["actual_start_at"])
        self.assertIsNone(row["actual_finish_at"])

    def test_the_list_carries_the_projects_unresolved_approvals(self):
        project = self.activate_project()
        unresolved_id = self.add_unresolved_approval(
            project["id"], "All structural works require the municipal NOC."
        )
        rows = self.list_tasks(project["id"])
        surfaced = rows["T001"]["project_unresolved_approvals"]
        self.assertEqual(len(surfaced), 1)
        self.assertEqual(surfaced[0]["approval_id"], str(unresolved_id))
        self.assertEqual(surfaced[0]["status"], "unassigned")
        self.assertTrue(surfaced[0]["blocking"])
        self.assertEqual(surfaced[0]["coverage_text"], "All structural works require the municipal NOC.")
        # A project fact, so every row reports the same one - and an
        # unresolved approval never blocks a task, because it covers none.
        self.assertEqual(rows["T002"]["project_unresolved_approvals"], surfaced)
        self.assertEqual(
            [reason["kind"] for reason in rows["T001"]["readiness"]["reasons"]], []
        )

    def test_a_project_with_no_unresolved_approvals_reports_an_empty_list(self):
        project = self.activate_project()
        self.assertEqual(self.list_tasks(project["id"])["T001"]["project_unresolved_approvals"], [])

    def test_reading_the_list_changes_no_lifecycle_status(self):
        """R5/KTD1: readiness is advisory. Rendering it must transition nothing."""
        project = self.activate_project()
        before = {code: task.lifecycle_status for code, task in self.tasks_by_code(project["id"]).items()}
        self.list_tasks(project["id"])
        after = {code: task.lifecycle_status for code, task in self.tasks_by_code(project["id"]).items()}
        self.assertEqual(before, after)


class ReadinessOnTheTaskDetailTests(ReadinessReadApiTestCase):
    def test_the_detail_carries_readiness_and_its_reasons(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        body = self.detail(project["id"], tasks["T002"].id)
        self.assertEqual(body["readiness"]["state"], BLOCKED)
        self.assertEqual(len(body["readiness"]["reasons"]), 1)
        self.assertEqual(body["readiness"]["reasons"][0]["subject_id"], str(tasks["T001"].id))
        self.assertEqual(body["readiness"]["advisories"], [])

        ready = self.detail(project["id"], tasks["T001"].id)
        self.assertEqual(ready["readiness"]["state"], READY)
        self.assertEqual(ready["readiness"]["reasons"], [])

    def test_a_blocking_reason_names_the_specific_unassigned_approval(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        approval_id = self.cover_task_with_approval(project["id"], t001.id)

        body = self.detail(project["id"], t001.id)
        self.assertEqual(body["readiness"]["state"], BLOCKED)
        reasons = body["readiness"]["reasons"]
        self.assertEqual(len(reasons), 1)
        self.assertEqual(reasons[0]["kind"], REASON_APPROVAL)
        self.assertEqual(reasons[0]["subject_id"], str(approval_id))
        self.assertIn("unassigned", reasons[0]["detail"])
        self.assertIn(str(approval_id), reasons[0]["detail"])

    def test_a_non_blocking_unsatisfied_fact_is_an_advisory_not_a_blocker(self):
        """The PM deliberately marked this approval non-blocking; reporting
        the task it covers as blocked would override that decision."""
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        approval_id = self.cover_task_with_approval(project["id"], t001.id, blocking=False)

        body = self.detail(project["id"], t001.id)
        self.assertEqual(body["readiness"]["state"], READY)
        self.assertEqual(body["readiness"]["reasons"], [])
        self.assertEqual(len(body["readiness"]["advisories"]), 1)
        advisory = body["readiness"]["advisories"][0]
        self.assertEqual(advisory["subject_id"], str(approval_id))
        self.assertFalse(advisory["blocking"])

        # And the list row agrees with the panel it opens.
        row = self.list_tasks(project["id"])["T001"]
        self.assertEqual(row["readiness"], body["readiness"])

    def test_the_detail_carries_variance_and_the_actuals(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        body = self.detail(project["id"], t001.id)
        expected = variance_for_task(self.tasks_by_code(project["id"])["T001"])
        self.assertEqual(body["variance"]["status"], expected.status)
        self.assertEqual(body["variance"]["variance_days"], expected.variance_days)
        self.assertIsNone(body["actual_start_at"])
        self.assertIsNone(body["actual_finish_at"])


class ReadinessMatchesTheEngineTests(ReadinessReadApiTestCase):
    def test_the_response_matches_the_readiness_services_own_output(self):
        """The response is a projection of the engine, not a second opinion."""
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        self.cover_task_with_approval(project["id"], tasks["T002"].id)
        self.cover_task_with_approval(project["id"], tasks["T001"].id, blocking=False)

        rows = self.list_tasks(project["id"])
        with self.Session() as session:
            engine_result = TaskReadinessService(session).for_project(uuid.UUID(project["id"]))

        for code, task in tasks.items():
            with self.subTest(code=code):
                expected = engine_result.tasks[task.id]
                row_readiness = rows[code]["readiness"]
                self.assertEqual(row_readiness["state"], expected.state)
                self.assertEqual(
                    [reason["subject_id"] for reason in row_readiness["reasons"]],
                    [str(reason.subject_id) for reason in expected.reasons],
                )
                self.assertEqual(
                    [reason["detail"] for reason in row_readiness["reasons"]],
                    [reason.detail for reason in expected.reasons],
                )
                self.assertEqual(
                    [reason["subject_id"] for reason in row_readiness["advisories"]],
                    [str(reason.subject_id) for reason in expected.advisories],
                )
                # And the detail panel answers exactly as the row did.
                self.assertEqual(self.detail(project["id"], task.id)["readiness"], row_readiness)


class InternalEmployeeReadinessVisibilityTests(ReadinessReadApiTestCase):
    def test_an_internal_employee_sees_readiness_only_for_their_own_tasks(self):
        project = self.activate_project()
        self.add_internal_member(project["id"])
        tasks = self.tasks_by_code(project["id"])
        self.assign_support(project["id"], tasks["T002"].id)

        self.act_as_internal()
        rows = self.list_tasks(project["id"])
        self.assertEqual(set(rows), {"T002"})
        # Readiness still reasons over the predecessor they cannot see - a
        # blocker does not stop blocking because the actor lacks visibility
        # of it - so the reason names T001 even though T001's row is absent.
        reasons = rows["T002"]["readiness"]["reasons"]
        self.assertEqual(reasons[0]["subject_id"], str(tasks["T001"].id))

        detail = self.detail(project["id"], tasks["T002"].id)
        self.assertEqual(detail["readiness"], rows["T002"]["readiness"])

        # The unassigned task's readiness is not reachable either way.
        forbidden = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{tasks['T001'].id}")
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

    def test_an_internal_employee_with_no_assignment_sees_no_readiness_at_all(self):
        project = self.activate_project()
        self.add_internal_member(project["id"])
        self.act_as_internal()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])


class ReadinessListQueryCountTests(ReadinessReadApiTestCase):
    """A 99-task list must resolve in a bounded number of queries.

    The regression this pins is a per-task readiness call inside the
    response loop. Counted with a `before_cursor_execute` listener rather
    than timed - the technique `test_task_readiness_v2.py` uses - because a
    timing assertion passes on a fast machine no matter how many queries ran.
    """

    # get_project's project/membership lookups, the task list, the two
    # summary-count aggregates, and readiness's four batched selects. Raise
    # this only for a query that is genuinely constant in the project size.
    QUERY_BUDGET = 12

    def _grow_project_to(self, project_id: str, total_tasks: int) -> None:
        """Adds plain execution tasks until the project has `total_tasks`.

        Inserted directly rather than through a 99-task template: what is
        under test is how the endpoint scales with row count, and template
        authoring is not part of that.
        """
        with self.Session.begin() as session:
            existing = session.scalars(
                select(Task).where(Task.project_id == uuid.UUID(project_id))
            ).all()
            template_row = existing[0]
            for sequence in range(len(existing) + 1, total_tasks + 1):
                session.add(Task(
                    id=uuid.uuid4(),
                    project_id=template_row.project_id,
                    baseline_id=template_row.baseline_id,
                    baseline_task_id=uuid.uuid4(),
                    original_code=f"G{sequence:03d}",
                    template_sequence=sequence,
                    title=f"Generated task {sequence}",
                    schedule_classification="execution",
                    applicability="mandatory",
                    task_class="standard",
                    task_kind="work",
                    lifecycle_status="planned",
                    planned_start_date=template_row.planned_start_date,
                    planned_end_date=template_row.planned_end_date,
                ))

    def _queries_for_list(self, project_id: str) -> tuple[int, int, list[str]]:
        statements: list[str] = []

        @event.listens_for(self.engine, "before_cursor_execute")
        def count(_conn, _cursor, statement, _params, _context, _executemany):
            statements.append(statement)

        try:
            response = self.client.get(f"/api/v2/projects/{project_id}/tasks")
        finally:
            event.remove(self.engine, "before_cursor_execute", count)
        self.assertEqual(response.status_code, 200, response.text)
        return len(response.json()), len(statements), statements

    def test_a_99_task_list_resolves_within_a_bounded_query_count(self):
        project = self.activate_project()
        self._grow_project_to(project["id"], 99)
        self.act_as_admin()

        row_count, query_count, statements = self._queries_for_list(project["id"])
        self.assertEqual(row_count, 99)
        self.assertLessEqual(
            query_count,
            self.QUERY_BUDGET,
            f"the task list issued {query_count} queries for 99 tasks:\n" + "\n".join(statements),
        )

    def test_the_query_count_does_not_grow_with_the_project(self):
        """The stronger form: the same budget at 2 tasks and at 99."""
        small = self.activate_project(name="Small Project")
        large = self.activate_project(name="Large Project")
        self._grow_project_to(large["id"], 99)
        self.act_as_admin()

        small_rows, small_queries, _ = self._queries_for_list(small["id"])
        large_rows, large_queries, statements = self._queries_for_list(large["id"])
        self.assertEqual((small_rows, large_rows), (2, 99))
        self.assertEqual(
            small_queries,
            large_queries,
            f"query count grew from {small_queries} to {large_queries}:\n" + "\n".join(statements),
        )


if __name__ == "__main__":
    unittest.main()
