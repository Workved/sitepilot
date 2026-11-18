"""Plan Phase 4: task rescheduling with audit.

Pins `TaskRescheduleService`/`POST /{project_id}/tasks/{task_id}/reschedule`,
against a real execution task produced by the baseline-lock activation flow
(same harness pattern as `test_task_readiness_declarations_v2.py`).

- Happy path: `planned_start_date`/`planned_end_date` change on the `Task`
  row, a `TASK_RESCHEDULED` `V2AuditEvent` is written with the exact
  before/after dates, and a `task.rescheduled` outbox event is emitted.
- `new_planned_end_date < new_planned_start_date` is rejected (422) before
  any write - mirrors `ck_v2_tasks_planned_end_after_start`'s own direction.
- A blank/whitespace-only reason is rejected (422) before any write.
- Only Supervisor/PM/Admin may reschedule; a non-member and a bare project
  member without scheduling authority are rejected (403/404).
- This service never touches `Task.lifecycle_status`.
- Follow-on: a reschedule shows up in a subsequently generated weekly
  report's `schedule_revisions`.
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
from app.report_models import ReportSnapshot
from app.routes.execution_tasks_v2 import router as execution_tasks_router
from app.routes.projects_v2 import router as projects_router
from app.routes.reports_v2 import router as reports_router
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
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


class TaskRescheduleApiTests(unittest.TestCase):
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
            ProjectRoleChange.__table__,
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
            TaskSupportAssignment.__table__,
            SupportAssignmentChange.__table__,
            OutboxEvent.__table__,
            ReportSnapshot.__table__,
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
        self.app.include_router(reports_router)

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
            session.add_all([admin, pm, supervisor, outsider, internal])
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

    def reschedule(self, project_id, task_id, new_start, new_end, reason="Client requested a delay."):
        payload = {
            "new_planned_start_date": new_start.isoformat(),
            "new_planned_end_date": new_end.isoformat(),
        }
        if reason is not None:
            payload["reason"] = reason
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/reschedule", json=payload,
        )

    # ---- happy path -----------------------------------------------------

    def test_supervisor_reschedules_task(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        before_start, before_end = task.planned_start_date, task.planned_end_date
        new_start = date(2026, 9, 1)
        new_end = date(2026, 9, 5)

        self.act_as_supervisor()
        response = self.reschedule(project["id"], task.id, new_start, new_end, reason="Vendor delivery delayed.")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["planned_start_date"], new_start.isoformat())
        self.assertEqual(body["planned_end_date"], new_end.isoformat())
        self.assertEqual(body["lifecycle_status"], "planned")

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.planned_start_date, new_start)
            self.assertEqual(refreshed.planned_end_date, new_end)
            # Reschedule never touches lifecycle_status.
            self.assertEqual(refreshed.lifecycle_status, "planned")

            audit_rows = session.scalars(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_type == "task",
                    V2AuditEvent.entity_id == task.id,
                    V2AuditEvent.action == "TASK_RESCHEDULED",
                )
            ).all()
            self.assertEqual(len(audit_rows), 1)
            audit = audit_rows[0]
            self.assertEqual(audit.actor_user_id, SUPERVISOR_ID)
            self.assertEqual(audit.reason, "Vendor delivery delayed.")
            self.assertEqual(
                audit.before_json,
                {
                    "planned_start_date": before_start.isoformat() if before_start else None,
                    "planned_end_date": before_end.isoformat() if before_end else None,
                },
            )
            self.assertEqual(
                audit.after_json,
                {"planned_start_date": new_start.isoformat(), "planned_end_date": new_end.isoformat()},
            )

            events = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == task.id, OutboxEvent.event_type == "task.rescheduled",
                )
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "task")
            self.assertEqual(events[0].payload["planned_start_date"], new_start.isoformat())
            self.assertEqual(events[0].payload["planned_end_date"], new_end.isoformat())
            self.assertEqual(events[0].payload["reason"], "Vendor delivery delayed.")

    def test_pm_reschedules_task(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_pm()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 2))
        self.assertEqual(response.status_code, 200, response.text)

    def test_admin_reschedules_task(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_admin()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 2))
        self.assertEqual(response.status_code, 200, response.text)

    def test_reschedule_allows_a_second_legitimate_reschedule(self):
        """A task can legitimately be rescheduled more than once - the
        idempotency key must not collide on the second call."""
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        first = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 2))
        self.assertEqual(first.status_code, 200, first.text)
        second = self.reschedule(project["id"], task.id, date(2026, 9, 10), date(2026, 9, 12))
        self.assertEqual(second.status_code, 200, second.text)

        with self.Session() as session:
            audit_rows = session.scalars(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_type == "task",
                    V2AuditEvent.entity_id == task.id,
                    V2AuditEvent.action == "TASK_RESCHEDULED",
                )
            ).all()
            self.assertEqual(len(audit_rows), 2)

            events = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == task.id, OutboxEvent.event_type == "task.rescheduled",
                )
            ).all()
            self.assertEqual(len(events), 2)

    # ---- validation -------------------------------------------------------

    def test_end_before_start_rejected_before_any_write(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        before_start, before_end = task.planned_start_date, task.planned_end_date

        self.act_as_supervisor()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 5), date(2026, 9, 1))
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.planned_start_date, before_start)
            self.assertEqual(refreshed.planned_end_date, before_end)
            self.assertIsNone(session.scalar(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_id == task.id, V2AuditEvent.action == "TASK_RESCHEDULED",
                ).limit(1)
            ))
            self.assertIsNone(session.scalar(
                select(OutboxEvent).where(OutboxEvent.event_type == "task.rescheduled").limit(1)
            ))

    def test_end_equal_to_start_is_allowed(self):
        """Mirrors the DB CHECK constraint's own `>=` (inclusive) direction."""
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        same_day = date(2026, 9, 1)
        response = self.reschedule(project["id"], task.id, same_day, same_day)
        self.assertEqual(response.status_code, 200, response.text)

    def test_blank_reason_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 5), reason="   ")
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as session:
            self.assertIsNone(session.scalar(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_id == task.id, V2AuditEvent.action == "TASK_RESCHEDULED",
                ).limit(1)
            ))

    def test_missing_reason_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 5), reason=None)
        self.assertEqual(response.status_code, 422, response.text)

    # ---- access control -----------------------------------------------------

    def test_non_member_cannot_reschedule(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_outsider()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 5))
        self.assertEqual(response.status_code, 403, response.text)

        with self.Session() as session:
            self.assertIsNone(session.scalar(
                select(V2AuditEvent).where(
                    V2AuditEvent.entity_id == task.id, V2AuditEvent.action == "TASK_RESCHEDULED",
                ).limit(1)
            ))

    def test_internal_employee_without_scheduling_authority_cannot_reschedule(self):
        """An Internal Employee is a valid project member for execution
        purposes but not a scheduling authority - reschedule needs
        Supervisor/PM/Admin specifically, not just "any active member"."""
        project = self.activate_project()
        self.act_as_pm()
        internal_employee_id = None
        with self.Session() as session:
            internal_employee_id = session.scalar(
                select(EmployeeProfile.id).where(EmployeeProfile.user_id == INTERNAL_ID)
            )
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={
                "employee_id": str(internal_employee_id),
                "project_role": "internal_employee",
                "reason": "Add support staff.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        task = self.task_t001(project["id"])

        self.act_as_internal()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 5))
        self.assertEqual(response.status_code, 403, response.text)

    def test_reschedule_never_touches_lifecycle_status(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 5))
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            refreshed = session.get(Task, task.id)
            self.assertEqual(refreshed.lifecycle_status, "planned")

    # ---- report follow-on ------------------------------------------------

    def test_reschedule_appears_in_weekly_report_schedule_revisions(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.reschedule(project["id"], task.id, date(2026, 9, 1), date(2026, 9, 5), reason="Site delay.")
        self.assertEqual(response.status_code, 200, response.text)

        self.act_as_admin()
        now = datetime.now(timezone.utc)
        report_response = self.client.post(
            f"/api/v2/projects/{project['id']}/reports",
            json={
                "report_type": "weekly",
                "period_start": (now - timedelta(days=1)).isoformat(),
                "period_end": (now + timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(report_response.status_code, 200, report_response.text)
        payload = report_response.json()["payload_json"]
        revisions = payload["schedule_revisions"]
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["task_id"], str(task.id))
        self.assertEqual(revisions[0]["planned_start_date"], "2026-09-01")
        self.assertEqual(revisions[0]["planned_end_date"], "2026-09-05")
        self.assertEqual(revisions[0]["reason"], "Site delay.")


if __name__ == "__main__":
    unittest.main()
