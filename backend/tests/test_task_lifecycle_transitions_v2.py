from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import datetime, timedelta, timezone

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


class TaskLifecycleTransitionsApiTests(unittest.TestCase):
    """U2: task lifecycle state machine (BR-009), against real execution
    tasks produced by U1's baseline-lock activation flow.

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_project_baseline_lock_v2.py.
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
            OutboxEvent.__table__,
            TaskSupportAssignment.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__,
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
        """Seeds a 4-task template: T001 -> T002 -> T003 (work, chained
        finish_to_start), and T004 (milestone) depending on T003. All are
        mandatory so they are all baseline-included at activation."""
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
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
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

            specs = [
                ("T001", "work"),
                ("T002", "work"),
                ("T003", "work"),
                ("T004", "milestone"),
            ]
            template_tasks = []
            for i, (code, kind) in enumerate(specs, start=1):
                template_tasks.append(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class="standard", task_kind=kind,
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ))
            session.add_all(template_tasks)
            session.flush()

            # T001 -> T002 -> T003 -> T004, all blocking finish_to_start.
            for i in range(len(template_tasks) - 1):
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

    def activate_project(self) -> dict:
        project = self.create_draft()
        response = self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/generate-dependencies")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
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

    def submit_progress(self, project_id: str, task_id, note="Work done."):
        # Submitted as Admin (not the current actor, usually the
        # Supervisor) so a later `verify()` call as Supervisor doesn't trip
        # TaskVerificationService's self-verification guard - no role rule
        # authorizes verifying your own submitted progress.
        previous_actor = self._current_actor
        self.act_as_admin()
        try:
            return self.client.post(
                f"/api/v2/projects/{project_id}/tasks/{task_id}/progress", data={"note": note},
            )
        finally:
            self.act_as(previous_actor)

    def verify(self, project_id: str, task_id, decision: str = "verified", remarks: str | None = None):
        # `verified`/`completed` are decision-service-only targets (U2's
        # transition() rejects them via the raw /status endpoint) - tests
        # that need a standard work task to reach `completed` go through
        # /verify, exactly like the real Supervisor verification flow.
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/verify",
            json={"decision": decision, "remarks": remarks},
        )

    # ---- happy path -----------------------------------------------------

    def test_work_task_moves_through_planned_ready_in_progress_submitted(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]
        self.assertEqual(t001.lifecycle_status, "planned")

        self.act_as_supervisor()
        r1 = self.transition(project["id"], t001.id, "ready", reason="Ready to start.")
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r1.json()["lifecycle_status"], "ready")

        r2 = self.transition(project["id"], t001.id, "in_progress", reason="Crew on site.")
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["lifecycle_status"], "in_progress")

        progress = self.submit_progress(project["id"], t001.id)
        self.assertEqual(progress.status_code, 200, progress.text)

        r3 = self.transition(project["id"], t001.id, "submitted", reason="Work done, submitting.")
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertEqual(r3.json()["lifecycle_status"], "submitted")

        with self.Session() as session:
            events = session.scalars(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_type == "task", V2AuditEvent.entity_id == t001.id,
                )
            ).all()
            self.assertEqual(len(events), 3)
            self.assertTrue(all(e.action == "TASK_STATUS_CHANGED" for e in events))

    def test_submitting_a_work_task_without_a_logged_progress_update_is_rejected(self):
        # Regression test: a Supervisor self-executing a task (no Internal
        # Employee assigned) could previously click straight through
        # ready -> in_progress -> submitted without ever logging a progress
        # update, stranding the task at `submitted` with no valid Verify or
        # Reject path out (both require a TaskProgressUpdate to act on).
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]

        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready", reason="Ready to start.")
        self.transition(project["id"], t001.id, "in_progress", reason="Crew on site.")

        response = self.transition(project["id"], t001.id, "submitted", reason="Skipping progress log.")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("progress update", response.text)

        with self.Session() as session:
            refreshed = session.get(Task, t001.id)
            self.assertEqual(refreshed.lifecycle_status, "in_progress")

    def test_resubmitting_after_rejection_without_a_new_progress_update_is_rejected(self):
        # Regression test: after a rejection reopens the task to
        # `in_progress`, its one existing TaskProgressUpdate is already
        # "spent" (a TaskVerification row now references it as the rejected
        # submission). Submit for review must not be immediately clickable
        # again on that same, already-decided evidence - it needs a fresh
        # progress update logged for the new work cycle.
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]

        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready", reason="Ready to start.")
        self.transition(project["id"], t001.id, "in_progress", reason="Crew on site.")

        first_progress = self.submit_progress(project["id"], t001.id, note="Initial attempt.")
        self.assertEqual(first_progress.status_code, 200, first_progress.text)

        submitted = self.transition(project["id"], t001.id, "submitted", reason="Submitting for review.")
        self.assertEqual(submitted.status_code, 200, submitted.text)

        rejected = self.verify(project["id"], t001.id, decision="rejected", remarks="Needs correction.")
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["task"]["lifecycle_status"], "in_progress")

        # No new progress update logged - resubmitting on the same, already-
        # rejected evidence must be blocked.
        stale_resubmit = self.transition(project["id"], t001.id, "submitted", reason="Resubmitting without changes.")
        self.assertEqual(stale_resubmit.status_code, 409, stale_resubmit.text)
        self.assertIn("new progress update", stale_resubmit.text)

        # Logging a genuinely new progress update unblocks it.
        second_progress = self.submit_progress(project["id"], t001.id, note="Corrected per feedback.")
        self.assertEqual(second_progress.status_code, 200, second_progress.text)

        fresh_resubmit = self.transition(project["id"], t001.id, "submitted", reason="Resubmitting with correction.")
        self.assertEqual(fresh_resubmit.status_code, 200, fresh_resubmit.text)
        self.assertEqual(fresh_resubmit.json()["lifecycle_status"], "submitted")

    # ---- milestone auto-completion --------------------------------------

    def test_milestone_auto_completes_once_last_blocking_predecessor_is_satisfied(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001, t002, t003, t004 = tasks["T001"], tasks["T002"], tasks["T003"], tasks["T004"]
        self.assertEqual(t004.task_kind, "milestone")

        self.act_as_supervisor()
        for task in (t001, t002, t003):
            r = self.transition(project["id"], task.id, "ready")
            self.assertEqual(r.status_code, 200, r.text)
            r = self.transition(project["id"], task.id, "in_progress")
            self.assertEqual(r.status_code, 200, r.text)
            sp = self.submit_progress(project["id"], task.id)
            self.assertEqual(sp.status_code, 200, sp.text)
            r = self.transition(project["id"], task.id, "submitted")
            self.assertEqual(r.status_code, 200, r.text)
            # Standard work auto-completes (submitted -> verified ->
            # completed) inside TaskVerificationService.verify itself.
            r = self.verify(project["id"], task.id)
            self.assertEqual(r.status_code, 200, f"failed verifying {task.original_code}: {r.text}")
            self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

        with self.Session() as session:
            milestone = session.get(Task, t004.id)
            self.assertEqual(milestone.lifecycle_status, "completed")
            audit = session.scalar(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_type == "task",
                    V2AuditEvent.entity_id == t004.id,
                    V2AuditEvent.source == "system",
                )
            )
            self.assertIsNotNone(audit)
            self.assertEqual(audit.after_json["lifecycle_status"], "completed")

            # The milestone cascade keeps its own per-task key: exactly one
            # "completed" event for the milestone, not one per predecessor.
            milestone_events = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == t004.id,
                    OutboxEvent.event_type == "task.status_changed",
                )
            ).all()
            self.assertEqual(len(milestone_events), 1)
            self.assertEqual(milestone_events[0].payload["target_status"], "completed")

    # ---- edge cases -------------------------------------------------------

    def test_transition_not_in_allow_list_is_rejected(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]
        self.act_as_supervisor()
        response = self.transition(project["id"], t001.id, "submitted", reason="Skip ahead.")
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "planned")

    def test_in_progress_rejected_when_no_active_supervisor(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]

        self.act_as_supervisor()
        r = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(r.status_code, 200, r.text)

        # End the active Supervisor membership directly at the DB level:
        # U6 blocks ending an accountable PM/Supervisor role via the API on
        # an active project (must go through the role-change request/
        # approval flow instead), but this test only needs the "no active
        # supervisor" *state* to exercise the lifecycle transition's
        # accountability check, not the membership-end API itself.
        self.act_as_admin()
        with self.Session.begin() as session:
            supervisor_membership = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project["id"]),
                    V2ProjectMembership.project_role == "site_supervisor",
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
            supervisor_membership.ends_at = datetime.now(timezone.utc)

        response = self.transition(project["id"], t001.id, "in_progress", reason="Start work.")
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "ready")

    def test_in_progress_blocked_by_unsatisfied_predecessor_then_succeeds_once_satisfied(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001, t002 = tasks["T001"], tasks["T002"]

        # Per the plan (R8/BR-011), the predecessor-satisfied check gates
        # both `ready` and `in_progress`, not just `in_progress`.
        self.act_as_supervisor()
        blocked = self.transition(project["id"], t002.id, "ready")
        self.assertEqual(blocked.status_code, 409, blocked.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t002.id).lifecycle_status, "planned")

        # Satisfy the predecessor: T001 all the way to completed.
        for target in ("ready", "in_progress"):
            r = self.transition(project["id"], t001.id, target)
            self.assertEqual(r.status_code, 200, r.text)
        sp = self.submit_progress(project["id"], t001.id)
        self.assertEqual(sp.status_code, 200, sp.text)
        r = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(r.status_code, 200, r.text)
        r = self.verify(project["id"], t001.id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

        ready = self.transition(project["id"], t002.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        unblocked = self.transition(project["id"], t002.id, "in_progress", reason="Start work.")
        self.assertEqual(unblocked.status_code, 200, unblocked.text)
        self.assertEqual(unblocked.json()["lifecycle_status"], "in_progress")

    def test_cancel_without_reason_is_rejected(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]
        self.act_as_admin()
        response = self.transition(project["id"], t001.id, "cancelled")
        self.assertEqual(response.status_code, 422, response.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "planned")

        with_reason = self.transition(project["id"], t001.id, "cancelled", reason="Scope removed by client.")
        self.assertEqual(with_reason.status_code, 200, with_reason.text)
        self.assertEqual(with_reason.json()["lifecycle_status"], "cancelled")

    # ---- U9: activation dates the schedule -------------------------------

    def test_activation_resolves_day_offsets_into_calendar_dates(self):
        """Proves the wiring, not the arithmetic - the conversion rule itself
        is covered by test_project_schedule_dates_v2.py."""
        project = self.activate_project()
        with self.Session() as session:
            db_project = session.get(V2Project, uuid.UUID(project["id"]))
            tasks = list(session.scalars(
                select(Task).where(Task.project_id == db_project.id)
            ))
            execution_tasks = [t for t in tasks if t.schedule_classification != "pre_activation"]
            self.assertTrue(execution_tasks, "expected at least one execution task")
            for task in execution_tasks:
                self.assertIsNotNone(
                    task.planned_start_date,
                    f"{task.original_code} was instantiated without a planned start date",
                )
                expected = db_project.start_date + timedelta(days=task.planned_start_day - 1)
                self.assertEqual(task.planned_start_date, expected)
                # The frozen baseline must survive activation untouched.
                self.assertIsNotNone(task.planned_start_day)

    # ---- U10: recorded actuals -------------------------------------------

    def test_starting_a_task_records_its_actual_start(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project["id"], t001.id, "ready").status_code, 200)
        self.assertEqual(self.transition(project["id"], t001.id, "in_progress").status_code, 200)
        with self.Session() as session:
            task = session.get(Task, t001.id)
            self.assertIsNotNone(task.actual_start_at)
            self.assertIsNone(task.actual_finish_at)

    def test_completing_a_task_records_its_actual_finish(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready")
        self.transition(project["id"], t001.id, "in_progress")
        self.submit_progress(project["id"], t001.id)
        self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(self.verify(project["id"], t001.id).status_code, 200)
        with self.Session() as session:
            task = session.get(Task, t001.id)
            self.assertEqual(task.lifecycle_status, "completed")
            self.assertIsNotNone(task.actual_start_at)
            self.assertIsNotNone(task.actual_finish_at)
            self.assertGreaterEqual(task.actual_finish_at, task.actual_start_at)

    def test_a_rejected_and_restarted_task_keeps_its_original_actual_start(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready")
        self.transition(project["id"], t001.id, "in_progress")
        with self.Session() as session:
            first_start = session.get(Task, t001.id).actual_start_at
        self.assertIsNotNone(first_start)

        self.submit_progress(project["id"], t001.id)
        self.transition(project["id"], t001.id, "submitted")
        rejected = self.verify(project["id"], t001.id, decision="rejected", remarks="Redo the edge trim.")
        self.assertEqual(rejected.status_code, 200, rejected.text)

        with self.Session() as session:
            task = session.get(Task, t001.id)
            # Rejection reopens the task through in_progress; the date work
            # actually began must survive that second pass.
            self.assertEqual(task.lifecycle_status, "in_progress")
            self.assertEqual(task.actual_start_at, first_start)

    def test_a_cancelled_task_records_no_actual_finish(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready")
        self.transition(project["id"], t001.id, "in_progress")
        # Cancellation is Admin/PM authority, not the Supervisor's.
        self.act_as_admin()
        cancelled = self.transition(project["id"], t001.id, "cancelled", reason="Client dropped the scope.")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        with self.Session() as session:
            task = session.get(Task, t001.id)
            self.assertEqual(task.lifecycle_status, "cancelled")
            self.assertIsNotNone(task.actual_start_at)
            self.assertIsNone(task.actual_finish_at)

    def test_a_task_never_started_records_no_actuals(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project["id"], t001.id, "ready").status_code, 200)
        with self.Session() as session:
            task = session.get(Task, t001.id)
            self.assertIsNone(task.actual_start_at)
            self.assertIsNone(task.actual_finish_at)

    def test_an_auto_completed_milestone_records_actuals(self):
        """The cascade writes lifecycle_status directly, so it carries its
        own actuals rather than inheriting transition()'s."""
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t004 = tasks["T004"]
        self.act_as_supervisor()
        for code in ("T001", "T002", "T003"):
            task = tasks[code]
            self.transition(project["id"], task.id, "ready")
            self.transition(project["id"], task.id, "in_progress")
            self.submit_progress(project["id"], task.id)
            self.transition(project["id"], task.id, "submitted")
            self.verify(project["id"], task.id)

        with self.Session() as session:
            milestone = session.get(Task, t004.id)
            self.assertEqual(milestone.lifecycle_status, "completed")
            self.assertIsNotNone(milestone.actual_finish_at)
            self.assertIsNotNone(milestone.actual_start_at)


if __name__ == "__main__":
    unittest.main()
