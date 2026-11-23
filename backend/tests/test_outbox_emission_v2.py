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
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.projects_v2 import router as projects_router
from app.services.outbox import OutboxService
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2CapabilityCategory, V2Vendor, V2VendorCapability
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
INTERNAL_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
REPLACEMENT_PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb9")
REPLACEMENT_SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc9")


class OutboxEmissionApiTests(unittest.TestCase):
    """Phase 2 U4: outbox event infrastructure and mutation hooks (R6).

    Exercises every instrumented mutation call site's `OutboxService.emit`
    call, plus `OutboxService.emit`'s own idempotency guard directly.
    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_vendor_assignment_v2.py / test_project_role_change_approval_v2.py,
    combining every table those two (plus U3/U4/U5/U6's) test files use
    since this unit's instrumentation spans all of them.
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
            TaskApprovalDecision.__table__,
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskSupportAssignment.__table__,
            SupportAssignmentChange.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
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
        self.app.include_router(project_vendors_router)

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

    def act_as_internal(self) -> None:
        self.act_as(User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 2-task template: T001 (work, standard, category
        'Electrical' - the workhorse task for lifecycle/verification/
        blocker/delay/support/vendor/progress happy-path tests) and T002
        (approval_gate, class_a - simplest path to a 'task.approval_recorded'
        event, no verification prerequisite). Also seeds an Internal
        Employee, a vendor mapped to the 'Electrical' capability, and two
        replacement PM/Supervisor employees for the role-change tests.
        """
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            internal = User(
                id=INTERNAL_ID, name="Internal", email="internal@example.com",
                role=UserRole.internal_employee, active=True,
            )
            replacement_pm = User(
                id=REPLACEMENT_PM_ID, name="PM Replacement", email="pm-replacement@example.com",
                role=UserRole.project_manager, active=True,
            )
            replacement_supervisor = User(
                id=REPLACEMENT_SUPERVISOR_ID, name="Supervisor Replacement", email="supervisor-replacement@example.com",
                role=UserRole.supervisor, active=True,
            )
            session.add_all([admin, pm, supervisor, internal, replacement_pm, replacement_supervisor])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee", availability="available",
                ),
                EmployeeProfile(
                    user_id=REPLACEMENT_PM_ID, employee_code="PM-002", designation="PM", availability="available",
                ),
                EmployeeProfile(
                    user_id=REPLACEMENT_SUPERVISOR_ID, employee_code="SUP-002", designation="Supervisor", availability="available",
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
                ("T001", "work", "standard", "Electrical"),
                ("T002", "approval_gate", "class_a", "Site"),
            ]
            for i, (code, kind, klass, category) in enumerate(specs, start=1):
                session.add(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class=klass, task_kind=kind,
                    evidence_required=False, duration_days=1, phase="Electrical", category=category,
                ))
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            session.add(electrical)
            session.flush()
            vendor = V2Vendor(
                id=uuid.uuid4(), name="Electrical Co", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            session.add(vendor)
            session.flush()
            session.add(V2VendorCapability(vendor_id=vendor.id, category_id=electrical.id))
            self.vendor_id = vendor.id

    # ---- generic helpers -------------------------------------------------

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
        self.act_as_admin()
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

    def task_by_code(self, project_id: str, code: str) -> Task:
        with self.Session() as session:
            return session.scalar(
                select(Task).where(Task.project_id == uuid.UUID(project_id), Task.original_code == code)
            )

    def outbox_rows(self, aggregate_id=None, event_type: str | None = None) -> list[OutboxEvent]:
        with self.Session() as session:
            stmt = select(OutboxEvent)
            if aggregate_id is not None:
                stmt = stmt.where(OutboxEvent.aggregate_id == aggregate_id)
            if event_type is not None:
                stmt = stmt.where(OutboxEvent.event_type == event_type)
            return list(session.scalars(stmt).all())

    def transition(self, project_id: str, task_id, target_status: str, reason: str | None = None):
        body: dict = {"target_status": target_status}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    def submit_progress(self, project_id: str, task_id, note="Work done."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/progress", data={"note": note},
        )

    def verify(self, project_id: str, task_id, decision: str, remarks: str | None = None):
        body: dict = {"decision": decision}
        if remarks is not None:
            body["remarks"] = remarks
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/verify", json=body)

    def approve(self, project_id: str, task_id, decision: str, remarks: str | None = None):
        body: dict = {"decision": decision}
        if remarks is not None:
            body["remarks"] = remarks
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/approve", json=body)

    def drive_to_submitted(self, project_id: str, task_id):
        """Drives a task to `submitted` as the Supervisor.

        An approval-gate task is the exception: it has no Supervisor/PM
        self-execute fallback, so an Internal Employee must be delegated
        before work can start, and from then on only that delegate may
        move it to `in_progress`/`submitted` or log its progress (see
        `TaskLifecycleService._require_role_for_transition` and
        `TaskProgressService._require_progress_actor`). For a gate this
        therefore delegates first and drives the executor-owned steps as
        that Internal Employee.
        """
        with self.Session() as session:
            is_approval_gate = session.get(Task, task_id).task_kind == "approval_gate"

        self.act_as_supervisor()
        ready = self.transition(project_id, task_id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)

        if is_approval_gate:
            self.add_internal_member(project_id)
            assignment = self.assign_support(project_id, task_id)
            self.assertEqual(assignment.status_code, 200, assignment.text)
            self.act_as_internal()

        in_progress = self.transition(project_id, task_id, "in_progress")
        self.assertEqual(in_progress.status_code, 200, in_progress.text)
        sp = self.submit_progress(project_id, task_id)
        self.assertEqual(sp.status_code, 200, sp.text)
        r = self.transition(project_id, task_id, "submitted")
        self.assertEqual(r.status_code, 200, r.text)

    def create_blocker(self, project_id, task_id, type_="material", description="Waiting on rebar delivery."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/blockers",
            json={"type": type_, "description": description},
        )

    def resolve_blocker(self, project_id, task_id, blocker_id):
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/blockers/{blocker_id}/resolve")

    def create_delay(self, project_id, task_id, responsibility_type="internal", reason="Crew shortage.", impact_days=2):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/delays",
            json={"responsibility_type": responsibility_type, "reason": reason, "impact_days": impact_days},
        )

    def add_internal_member(self, project_id: str) -> None:
        self.act_as_pm()
        response = self.client.post(
            f"/api/v2/projects/{project_id}/memberships",
            json={"employee_id": str(self.internal_employee_id), "project_role": "internal_employee", "reason": "Add support staff."},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def assign_support(self, project_id, task_id):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments",
            json={"employee_id": str(self.internal_employee_id), "responsibility": "Material staging."},
        )

    def end_support(self, project_id, task_id, assignment_id, reason_code="workload"):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments/{assignment_id}/end",
            json={"reason_code": reason_code},
        )

    def map_vendor(self, project_id, vendor_id):
        self.act_as_pm()
        return self.client.post(f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)})

    def assign_vendor(self, project_id, task_id, vendor_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment", json={"vendor_id": str(vendor_id)},
        )

    def request_role_change(self, project_id, role_type, replacement_employee_id, reason="Operational requirement."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/role-changes",
            json={"role_type": role_type, "replacement_employee_id": str(replacement_employee_id), "reason": reason},
        )

    def approve_role_change(self, project_id, change_id):
        return self.client.post(f"/api/v2/projects/{project_id}/role-changes/{change_id}/approve")

    def reject_role_change(self, project_id, change_id, reason="Not appropriate."):
        return self.client.post(f"/api/v2/projects/{project_id}/role-changes/{change_id}/reject", json={"reason": reason})

    @property
    def internal_employee_id(self) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == INTERNAL_ID))

    def replacement_pm_employee_id(self) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == REPLACEMENT_PM_ID))

    def replacement_supervisor_employee_id(self) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == REPLACEMENT_SUPERVISOR_ID))

    # ---- 1. happy path: one outbox row per instrumented call site ---------

    def test_task_lifecycle_transition_emits_status_changed(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.act_as_supervisor()
        r = self.transition(project["id"], t001.id, "ready", reason="Ready to start.")
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.status_changed")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].aggregate_type, "task")
        self.assertEqual(rows[0].payload["target_status"], "ready")

    def test_verify_verified_decision_emits_verification_recorded(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)

        # drive_to_submitted submits progress as the Supervisor; verify as
        # Admin instead so this doesn't trip the self-verification block
        # ("a different Supervisor, PM, or Admin must verify it") added on
        # the merged branch - this test only cares that verify() emits the
        # outbox row, not who verifies.
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.verification_recorded")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["decision"], "verified")

    def test_verify_rejected_decision_emits_verification_recorded(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)

        # See note above: verify as Admin, not the Supervisor who submitted.
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "rejected", remarks="Rework the finish.")
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.verification_recorded")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["decision"], "rejected")

    def test_approve_emits_approval_recorded(self):
        project = self.activate_project()
        t002 = self.task_by_code(project["id"], "T002")
        self.drive_to_submitted(project["id"], t002.id)

        self.act_as_pm()
        r = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t002.id, event_type="task.approval_recorded")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["decision"], "approved")

    def test_create_blocker_emits_blocker_created(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.act_as_supervisor()
        r = self.create_blocker(project["id"], t001.id)
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.blocker_created")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload["blocker_id"], r.json()["id"])

    def test_resolve_blocker_emits_blocker_resolved(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.act_as_supervisor()
        created = self.create_blocker(project["id"], t001.id)
        self.assertEqual(created.status_code, 200, created.text)

        r = self.resolve_blocker(project["id"], t001.id, created.json()["id"])
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.blocker_resolved")
        self.assertEqual(len(rows), 1)

    def test_create_delay_emits_delay_recorded(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.act_as_supervisor()
        r = self.create_delay(project["id"], t001.id)
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.delay_recorded")
        self.assertEqual(len(rows), 1)

    def test_assign_support_emits_support_assigned(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.add_internal_member(project["id"])
        self.act_as_supervisor()
        r = self.assign_support(project["id"], t001.id)
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.support_assigned")
        self.assertEqual(len(rows), 1)

    def test_end_support_emits_support_ended(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.add_internal_member(project["id"])
        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], t001.id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        r = self.end_support(project["id"], t001.id, assigned.json()["id"])
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.support_ended")
        self.assertEqual(len(rows), 1)

    def test_request_role_change_emits_role_change_requested(self):
        project = self.activate_project()
        self.act_as_pm()
        r = self.request_role_change(project["id"], "site_supervisor", self.replacement_supervisor_employee_id())
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=uuid.UUID(project["id"]), event_type="project.role_change_requested")
        self.assertEqual(len(rows), 1)

    def test_approve_role_change_emits_role_change_approved(self):
        project = self.activate_project()
        self.act_as_admin()
        requested = self.request_role_change(project["id"], "project_manager", self.replacement_pm_employee_id())
        self.assertEqual(requested.status_code, 200, requested.text)

        r = self.approve_role_change(project["id"], requested.json()["id"])
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=uuid.UUID(project["id"]), event_type="project.role_change_approved")
        self.assertEqual(len(rows), 1)

    def test_reject_role_change_emits_role_change_rejected(self):
        project = self.activate_project()
        self.act_as_pm()
        requested = self.request_role_change(project["id"], "site_supervisor", self.replacement_supervisor_employee_id())
        self.assertEqual(requested.status_code, 200, requested.text)

        r = self.reject_role_change(project["id"], requested.json()["id"])
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=uuid.UUID(project["id"]), event_type="project.role_change_rejected")
        self.assertEqual(len(rows), 1)

    def test_assign_vendor_emits_vendor_assigned(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        mapped = self.map_vendor(project["id"], self.vendor_id)
        self.assertEqual(mapped.status_code, 200, mapped.text)

        r = self.assign_vendor(project["id"], t001.id, self.vendor_id)
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.vendor_assigned")
        self.assertEqual(len(rows), 1)

    def test_submit_progress_emits_evidence_submitted(self):
        """Deliberate addition beyond the plan's literal U4 file list -
        task_progress.py is a Phase 1 mutation service R6/BR-015 explicitly
        requires ('evidence submitted') but the plan's own file list
        omitted it. See the U4 unit report."""
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.act_as_supervisor()
        for target in ("ready", "in_progress"):
            r = self.transition(project["id"], t001.id, target)
            self.assertEqual(r.status_code, 200, r.text)

        r = self.submit_progress(project["id"], t001.id)
        self.assertEqual(r.status_code, 200, r.text)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.evidence_submitted")
        self.assertEqual(len(rows), 1)

    # ---- 2/3. idempotency guard: no duplicate row on repeated key ---------

    def test_emit_same_session_repeated_key_is_a_no_op(self):
        with self.Session() as session:
            svc = OutboxService(session)
            agg_id = uuid.uuid4()
            first = svc.emit(
                event_type="test.event", aggregate_type="test", aggregate_id=agg_id,
                payload={"n": 1}, idempotency_key="test:same-session-dup",
            )
            self.assertIsNotNone(first)

            second = svc.emit(
                event_type="test.event", aggregate_type="test", aggregate_id=agg_id,
                payload={"n": 2}, idempotency_key="test:same-session-dup",
            )
            self.assertIsNone(second)
            session.commit()

        with self.Session() as session:
            rows = session.scalars(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == "test:same-session-dup")
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].payload["n"], 1)

    def test_emit_key_already_committed_by_a_prior_caller_does_not_duplicate(self):
        """Error-path proof: retrying the same logical mutation (a second
        `emit()` call, from a fresh session, against a key a first caller
        already committed) must not silently produce a second row for the
        same logical event - `emit()`'s duplicate-key guard is the
        mechanism this codebase actually relies on for that."""
        agg_id = uuid.uuid4()
        with self.Session() as session:
            OutboxService(session).emit(
                event_type="test.event", aggregate_type="test", aggregate_id=agg_id,
                payload={"attempt": 1}, idempotency_key="test:cross-session-dup",
            )
            session.commit()

        with self.Session() as session:
            retried = OutboxService(session).emit(
                event_type="test.event", aggregate_type="test", aggregate_id=agg_id,
                payload={"attempt": 2}, idempotency_key="test:cross-session-dup",
            )
            self.assertIsNone(retried)
            session.commit()

        with self.Session() as session:
            rows = session.scalars(
                select(OutboxEvent).where(OutboxEvent.idempotency_key == "test:cross-session-dup")
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].payload["attempt"], 1)

    # ---- 4. integration: real HTTP flow, domain state + outbox row --------

    def test_status_transition_http_flow_changes_domain_state_and_emits_exactly_one_row(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.assertEqual(t001.lifecycle_status, "planned")

        self.act_as_supervisor()
        response = self.transition(project["id"], t001.id, "ready", reason="Ready to start.")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["lifecycle_status"], "ready")

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "ready")
            rows = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "task",
                    OutboxEvent.aggregate_id == t001.id,
                    OutboxEvent.event_type == "task.status_changed",
                )
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].payload["target_status"], "ready")
            self.assertEqual(rows[0].status, "pending")

    # ---- 5. integration: transaction-boundary trap proof -------------------

    def test_verify_standard_work_produces_one_verification_and_two_status_changed_rows(self):
        """Proves the transaction-boundary trap was handled correctly:
        verifying a standard work task cascades through TWO nested
        `TaskLifecycleService.transition` calls (submitted -> verified,
        then verified -> completed, each with its own commit), while the
        `task.verification_recorded` emission happens once, before either
        of those commits, riding inside the first one's transaction."""
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)

        # drive_to_submitted itself already drove the task through
        # planned -> ready -> in_progress -> submitted (3 more
        # task.status_changed rows via the real HTTP status endpoint) -
        # capture the count beforehand so the assertions below isolate
        # exactly what verify()'s own two nested transition() calls add.
        status_rows_before = len(self.outbox_rows(aggregate_id=t001.id, event_type="task.status_changed"))

        # drive_to_submitted submits progress as the Supervisor; verify as
        # Admin instead so this doesn't trip the self-verification block
        # added on the merged branch.
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "completed")

            verification_rows = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == t001.id,
                    OutboxEvent.event_type == "task.verification_recorded",
                )
            ).all()
            self.assertEqual(len(verification_rows), 1)
            self.assertEqual(verification_rows[0].payload["decision"], "verified")

            status_rows = session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == t001.id,
                    OutboxEvent.event_type == "task.status_changed",
                )
            ).all()
            # Exactly 2 new rows from this verify() call - not zero (the
            # trap not handled: emit placed after transition() calls would
            # simply never fire since it would never be reached before a
            # HTTPException, or would land outside the committed
            # transaction), not a crash, not a duplicate.
            self.assertEqual(len(status_rows) - status_rows_before, 2)
            target_statuses = [row.payload["target_status"] for row in status_rows]
            self.assertEqual(target_statuses.count("verified"), 1)
            self.assertEqual(target_statuses.count("completed"), 1)
            self.assertEqual(sorted(target_statuses), ["completed", "in_progress", "ready", "submitted", "verified"])

    # ---- 5. rework loops: one event per occurrence ------------------------

    def resubmit_as_supervisor(self, project_id: str, task_id, note: str):
        self.act_as_supervisor()
        sp = self.submit_progress(project_id, task_id, note=note)
        self.assertEqual(sp.status_code, 200, sp.text)
        r = self.transition(project_id, task_id, "submitted")
        self.assertEqual(r.status_code, 200, r.text)

    def test_rework_loop_emits_every_submission_and_every_rejection(self):
        """AE1: before occurrence keys, the second `submitted` and the second
        rejection collapsed onto the first cycle's keys and emitted nothing,
        so the reviewer and the executor were never told."""
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "rejected", remarks="Cable run is crooked.")
        self.assertEqual(r.status_code, 200, r.text)

        self.resubmit_as_supervisor(project["id"], t001.id, note="Re-ran the cable.")

        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "rejected", remarks="Still loose at the box.")
        self.assertEqual(r.status_code, 200, r.text)

        status_rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.status_changed")
        targets = [row.payload["target_status"] for row in status_rows]
        self.assertEqual(targets.count("submitted"), 2)
        self.assertEqual(targets.count("rejected"), 2)
        # First start + one reopen per rejection.
        self.assertEqual(targets.count("in_progress"), 3)

        verification_rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.verification_recorded")
        self.assertEqual(len(verification_rows), 2)
        self.assertEqual(
            sorted(row.payload["remarks"] for row in verification_rows),
            ["Cable run is crooked.", "Still loose at the box."],
        )
        self.assertEqual(len({row.idempotency_key for row in verification_rows}), 2)

    def test_rework_loop_verify_after_rejection_emits_both_decisions(self):
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "rejected", remarks="Redo.")
        self.assertEqual(r.status_code, 200, r.text)
        self.resubmit_as_supervisor(project["id"], t001.id, note="Redone.")
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)

        decisions = sorted(
            row.payload["decision"]
            for row in self.outbox_rows(aggregate_id=t001.id, event_type="task.verification_recorded")
        )
        self.assertEqual(decisions, ["rejected", "verified"])

    def test_pm_rejecting_in_two_cycles_emits_two_approval_events(self):
        project = self.activate_project()
        t002 = self.task_by_code(project["id"], "T002")
        self.drive_to_submitted(project["id"], t002.id)

        for cycle, reason in enumerate(("Permit copy unreadable.", "Wrong permit number."), start=1):
            self.act_as_pm()
            r = self.approve(project["id"], t002.id, "rejected", remarks=reason)
            self.assertEqual(r.status_code, 200, r.text)
            if cycle == 1:
                self.act_as_internal()
                sp = self.submit_progress(project["id"], t002.id, note="Re-uploaded permit.")
                self.assertEqual(sp.status_code, 200, sp.text)
                r = self.transition(project["id"], t002.id, "submitted")
                self.assertEqual(r.status_code, 200, r.text)

        approval_rows = self.outbox_rows(aggregate_id=t002.id, event_type="task.approval_recorded")
        self.assertEqual(len(approval_rows), 2)
        self.assertEqual(
            sorted(row.payload["remarks"] for row in approval_rows),
            ["Permit copy unreadable.", "Wrong permit number."],
        )
        targets = [
            row.payload["target_status"]
            for row in self.outbox_rows(aggregate_id=t002.id, event_type="task.status_changed")
        ]
        self.assertEqual(targets.count("submitted"), 2)

    def test_status_events_name_the_actor_and_mark_decision_driven_steps(self):
        """The intermediate status steps a decision drives carry
        `cause: decision`; user-driven steps do not."""
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)
        self.act_as_admin()
        self.assertEqual(self.verify(project["id"], t001.id, "rejected", remarks="Redo.").status_code, 200)

        rows = self.outbox_rows(aggregate_id=t001.id, event_type="task.status_changed")
        by_target = {}
        for row in rows:
            by_target.setdefault(row.payload["target_status"], []).append(row.payload)
        for target in ("ready", "submitted"):
            self.assertNotIn("cause", by_target[target][0])
            self.assertEqual(by_target[target][0]["actor_user_id"], str(SUPERVISOR_ID))
        self.assertEqual(by_target["rejected"][0]["cause"], "decision")
        reopened = [p for p in by_target["in_progress"] if p["before_status"] == "rejected"]
        self.assertEqual(reopened[0]["cause"], "decision")
        self.assertEqual(reopened[0]["actor_user_id"], str(ADMIN_ID))
        first_start = [p for p in by_target["in_progress"] if p["before_status"] == "ready"]
        self.assertNotIn("cause", first_start[0])

    def test_occurrence_keys_name_their_source_row_and_retry_is_a_no_op(self):
        """The key is the specific occurrence (audit row / decision row), so
        re-emitting that same occurrence still collapses to one event."""
        project = self.activate_project()
        t001 = self.task_by_code(project["id"], "T001")
        self.drive_to_submitted(project["id"], t001.id)
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "rejected", remarks="Redo.")
        self.assertEqual(r.status_code, 200, r.text)

        with self.Session() as session:
            submitted_audit = next(
                audit for audit in session.scalars(
                    select(V2AuditEvent).where(
                        V2AuditEvent.entity_id == t001.id,
                        V2AuditEvent.action == "TASK_STATUS_CHANGED",
                    )
                )
                if audit.after_json["lifecycle_status"] == "submitted"
            )
            verification = session.scalar(select(TaskVerification).where(TaskVerification.task_id == t001.id))

        status_keys = {
            row.idempotency_key
            for row in self.outbox_rows(aggregate_id=t001.id, event_type="task.status_changed")
        }
        submitted_key = f"task:{t001.id}:task.status_changed:submitted:{submitted_audit.id}"
        self.assertIn(submitted_key, status_keys)
        verification_key = f"task:{t001.id}:task.verification_recorded:rejected:{verification.id}"
        self.assertEqual(
            [row.idempotency_key for row in self.outbox_rows(aggregate_id=t001.id, event_type="task.verification_recorded")],
            [verification_key],
        )

        with self.Session() as session:
            for key in (submitted_key, verification_key):
                retried = OutboxService(session).emit(
                    event_type="task.status_changed", aggregate_type="task", aggregate_id=t001.id,
                    payload={}, idempotency_key=key,
                )
                self.assertIsNone(retried)
            session.commit()
        self.assertEqual(
            len([row for row in self.outbox_rows() if row.idempotency_key in (submitted_key, verification_key)]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
