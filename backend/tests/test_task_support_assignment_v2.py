from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402
from app.vendor_models import TaskVendorAssignment, V2Vendor  # noqa: E402,F811

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
    V2ProjectMembership,
    V2ProjectTask,
    V2ProjectTaskDependency,
    V2ProjectExternalGateTask,
)
from app.routes.execution_tasks_v2 import router as execution_tasks_router
from app.routes.projects_v2 import router as projects_router
from tests.template_reference_tables import TEMPLATE_REFERENCE_LINK_TABLES
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


class TaskSupportAssignmentApiTests(unittest.TestCase):
    """U6: task-level support-employee assignment (BR-005), against real
    execution tasks produced by U1's baseline-lock activation flow.
    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_blockers_delays_v2.py.
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
            ProjectRoleChange.__table__,
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectTaskReferenceFile.__table__,
            V2Vendor.__table__,
            TaskVendorAssignment.__table__,
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
        """Seeds a 2-task template: T001 (work), T002 (approval_gate), plus
        two Internal Employees (one added as a project member at
        create-time via generate/activate flow, a second seeded but not a
        project member for the "non-member cannot be support" edge case)."""
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

            specs = [("T001", "work", "standard"), ("T002", "approval_gate", "class_a")]
            for i, (code, kind, klass) in enumerate(specs, start=1):
                session.add(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class=klass, task_kind=kind,
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ))
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

    def task_by_code(self, project_id: str, code: str) -> Task:
        with self.Session() as session:
            return session.scalar(
                select(Task).where(Task.project_id == uuid.UUID(project_id), Task.original_code == code)
            )

    def assign_support(self, project_id, task_id, employee_id, responsibility="Material staging."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments",
            json={"employee_id": str(employee_id), "responsibility": responsibility},
        )

    def end_support(self, project_id, task_id, assignment_id, reason_code="workload", replacement_employee_id=None):
        body = {"reason_code": reason_code}
        if replacement_employee_id is not None:
            body["replacement_employee_id"] = str(replacement_employee_id)
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments/{assignment_id}/end",
            json=body,
        )

    def transition(self, project_id, task_id, target_status: str, reason: str | None = None):
        body: dict = {"target_status": target_status}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    # ---- happy paths ----------------------------------------------------

    def test_supervisor_assigns_support_employee_to_work_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        response = self.assign_support(project["id"], t001.id, internal_employee_id)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["employee_id"], str(internal_employee_id))
        self.assertEqual(body["status"], "active")
        self.assertIsNone(body["ends_at"])

        with self.Session() as session:
            rows = session.scalars(select(TaskSupportAssignment).where(TaskSupportAssignment.task_id == t001.id)).all()
            self.assertEqual(len(rows), 1)

    def test_pm_assigns_followup_support_to_approval_gate_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t002 = self.task_by_code(project["id"], "T002")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_pm()
        response = self.assign_support(project["id"], t002.id, internal_employee_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["employee_id"], str(internal_employee_id))

    def test_supervisor_cannot_assign_support_to_approval_gate(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t002 = self.task_by_code(project["id"], "T002")

        self.act_as_supervisor()
        response = self.assign_support(project["id"], t002.id, self.employee_id_for(INTERNAL_ID))
        self.assertEqual(response.status_code, 403, response.text)

    def test_pm_cannot_assign_support_to_work_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_pm()
        response = self.assign_support(project["id"], t001.id, self.employee_id_for(INTERNAL_ID))
        self.assertEqual(response.status_code, 403, response.text)

    # ---- edge cases -------------------------------------------------------

    def test_internal_employee_cannot_be_assigned_twice_for_overlapping_periods(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        first = self.assign_support(project["id"], t001.id, internal_employee_id)
        self.assertEqual(first.status_code, 200, first.text)

        second = self.assign_support(project["id"], t001.id, internal_employee_id)
        self.assertEqual(second.status_code, 409, second.text)

    def test_non_internal_employee_cannot_be_assigned_as_support(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_supervisor()
        # PM (not an internal_employee) attempted as support.
        response = self.assign_support(project["id"], t001.id, self.employee_id_for(PM_ID))
        self.assertEqual(response.status_code, 422, response.text)

    def test_non_project_member_internal_employee_cannot_be_assigned_as_support(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        # SECOND_INTERNAL_ID never added as a project member.
        self.act_as_supervisor()
        response = self.assign_support(project["id"], t001.id, self.employee_id_for(SECOND_INTERNAL_ID))
        self.assertEqual(response.status_code, 422, response.text)

    # ---- end support --------------------------------------------------------

    def test_end_support_assignment_sets_ends_at_and_status(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        created = self.assign_support(project["id"], t001.id, internal_employee_id)
        assignment_id = created.json()["id"]

        response = self.end_support(project["id"], t001.id, assignment_id)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ended")
        self.assertIsNotNone(body["ends_at"])

        with self.Session() as session:
            changes = session.scalars(select(SupportAssignmentChange)).all()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].previous_employee_id, internal_employee_id)

    def test_end_support_with_replacement_reassigns_atomically(self):
        # Phase 2 (whatsapp-model-alignment plan): a single end-support call
        # with replacement_employee_id set both ends the old assignment and
        # creates the new one in one atomic request, rather than requiring a
        # separate end + assign round trip.
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        self.add_internal_member(project["id"], SECOND_INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        original_employee_id = self.employee_id_for(INTERNAL_ID)
        replacement_employee_id = self.employee_id_for(SECOND_INTERNAL_ID)

        self.act_as_supervisor()
        created = self.assign_support(project["id"], t001.id, original_employee_id)
        assignment_id = created.json()["id"]

        response = self.end_support(
            project["id"], t001.id, assignment_id, replacement_employee_id=replacement_employee_id,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["employee_id"], str(replacement_employee_id))
        self.assertEqual(body["status"], "active")
        self.assertIsNone(body["ends_at"])

        with self.Session() as session:
            rows = session.scalars(
                select(TaskSupportAssignment).where(TaskSupportAssignment.task_id == t001.id)
            ).all()
            self.assertEqual(len(rows), 2)
            by_status = {row.status: row for row in rows}
            self.assertEqual(by_status["ended"].employee_id, original_employee_id)
            self.assertEqual(by_status["active"].employee_id, replacement_employee_id)

            changes = session.scalars(select(SupportAssignmentChange)).all()
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].previous_employee_id, original_employee_id)
            self.assertEqual(changes[0].replacement_employee_id, replacement_employee_id)

    # ---- error path: no project membership ---------------------------------

    def test_actor_with_no_membership_cannot_assign_support(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_outsider()
        response = self.assign_support(project["id"], t001.id, self.employee_id_for(INTERNAL_ID))
        self.assertEqual(response.status_code, 403, response.text)

    # ---- assigned-employee-driven start/submit -----------------------------

    def test_assigned_internal_employee_can_start_and_submit_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        ready = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assign_support(project["id"], t001.id, internal_employee_id)

        self.act_as_internal()
        started = self.transition(project["id"], t001.id, "in_progress")
        self.assertEqual(started.status_code, 200, started.text)
        progress = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/progress", data={"note": "Work done."},
        )
        self.assertEqual(progress.status_code, 200, progress.text)
        submitted = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["lifecycle_status"], "submitted")

    def test_supervisor_cannot_start_or_submit_when_internal_employee_assigned(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        ready = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assign_support(project["id"], t001.id, internal_employee_id)

        # Supervisor must not silently take over execution once an Internal
        # Employee is assigned - only that employee (or Admin) can start it.
        blocked = self.transition(project["id"], t001.id, "in_progress")
        self.assertEqual(blocked.status_code, 403, blocked.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "ready")

    def test_unassigned_internal_employee_cannot_start_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        self.add_internal_member(project["id"], SECOND_INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        ready = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assign_support(project["id"], t001.id, internal_employee_id)

        # A different Internal Employee (not the one assigned) cannot start it.
        self.act_as_second_internal()
        blocked = self.transition(project["id"], t001.id, "in_progress")
        self.assertEqual(blocked.status_code, 403, blocked.text)

    def test_supervisor_can_start_and_submit_when_no_internal_employee_assigned(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_supervisor()
        ready = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        started = self.transition(project["id"], t001.id, "in_progress")
        self.assertEqual(started.status_code, 200, started.text)
        progress = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/progress", data={"note": "Work done."},
        )
        self.assertEqual(progress.status_code, 200, progress.text)
        submitted = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(submitted.status_code, 200, submitted.text)

    def test_unassigned_internal_employee_cannot_start_task_with_no_assignment(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_supervisor()
        ready = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)

        # No support assignment exists yet - only Supervisor/PM/Admin may
        # start the task themselves.
        self.act_as_internal()
        blocked = self.transition(project["id"], t001.id, "in_progress")
        self.assertEqual(blocked.status_code, 403, blocked.text)

    def test_assigned_internal_employee_can_mark_planned_task_ready(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_supervisor()
        self.assign_support(project["id"], t001.id, self.employee_id_for(INTERNAL_ID))

        # A busy Supervisor mustn't block the assigned employee from starting.
        self.act_as_internal()
        ready = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        started = self.transition(project["id"], t001.id, "in_progress")
        self.assertEqual(started.status_code, 200, started.text)

    def test_unassigned_internal_employee_cannot_mark_task_ready(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        self.add_internal_member(project["id"], SECOND_INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_supervisor()
        self.assign_support(project["id"], t001.id, self.employee_id_for(INTERNAL_ID))

        self.act_as_second_internal()
        blocked = self.transition(project["id"], t001.id, "ready")
        self.assertEqual(blocked.status_code, 403, blocked.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "planned")

    # ---- Internal Employee visibility is scoped to their own assignments -

    def test_internal_employee_task_list_only_shows_actively_assigned_tasks(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        t002 = self.task_by_code(project["id"], "T002")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], t001.id, internal_employee_id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        self.act_as_internal()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        codes = [item["original_code"] for item in response.json()]
        self.assertEqual(codes, ["T001"])
        self.assertNotIn(t002.original_code, codes)

        # Every other role keeps the full, unfiltered project task list.
        self.act_as_supervisor()
        full_list = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(sorted(item["original_code"] for item in full_list.json()), ["T001", "T002"])

    def test_internal_employee_with_no_assignment_sees_an_empty_task_list(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)

        self.act_as_internal()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_internal_employee_cannot_open_detail_of_an_unassigned_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")

        self.act_as_internal()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        self.assertEqual(response.status_code, 403, response.text)

    def test_internal_employee_can_open_detail_of_their_own_assigned_task(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], t001.id, internal_employee_id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        self.act_as_internal()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["original_code"], "T001")

    def test_internal_employee_loses_task_visibility_once_their_support_assignment_ends(self):
        project = self.activate_project()
        self.add_internal_member(project["id"], INTERNAL_ID)
        t001 = self.task_by_code(project["id"], "T001")
        internal_employee_id = self.employee_id_for(INTERNAL_ID)

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], t001.id, internal_employee_id)
        self.assertEqual(assigned.status_code, 200, assigned.text)
        assignment_id = assigned.json()["id"]
        ended = self.end_support(project["id"], t001.id, assignment_id)
        self.assertEqual(ended.status_code, 200, ended.text)

        self.act_as_internal()
        list_response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(list_response.json(), [])
        detail_response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        self.assertEqual(detail_response.status_code, 403, detail_response.text)


if __name__ == "__main__":
    unittest.main()
