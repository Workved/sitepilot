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
    TaskApprovalDecision,
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
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
SECOND_PM_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
INTERNAL_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff5")


class TaskVerificationApprovalApiTests(unittest.TestCase):
    """U4: Supervisor verification and PM approval decisions (BR-008),
    against real execution tasks produced by U1's baseline-lock activation
    flow. Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_lifecycle_transitions_v2.py / test_task_progress_evidence_v2.py.
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
            TaskProgressUpdate.__table__,
            FileObject.__table__,
            TaskEvidence.__table__,
            TaskVerification.__table__,
            TaskApprovalDecision.__table__,
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

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    def act_as_pm(self) -> None:
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))

    def act_as_outsider(self) -> None:
        self.act_as(User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
            role=UserRole.supervisor, active=True,
        ))

    def act_as_internal(self) -> None:
        self.act_as(User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 5-task template:
        T001 (work, standard), T002 (work, class_a), T003 (approval_gate,
        class_a) all standalone, plus T004 (work, standard) depending on
        T002 (blocking finish_to_start) - used for the predecessor-unblock
        integration test. A second PM (SECOND_PM_ID) is also seeded (but
        not given project membership at project-creation time) so tests
        can add them as a project member later for the fallback-verifier
        scenario. An Internal Employee (INTERNAL_ID) is seeded for the
        same reason: T003's approval-gate work cannot start until it is
        delegated to one (see `drive_to_submitted`).
        """
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
            second_pm = User(
                id=SECOND_PM_ID, name="PM Two", email="pm2@example.com",
                role=UserRole.project_manager, active=True,
            )
            internal = User(
                id=INTERNAL_ID, name="Internal", email="internal@example.com",
                role=UserRole.internal_employee, active=True,
            )
            session.add_all([admin, pm, supervisor, outsider, second_pm, internal])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee",
                    availability="available",
                ),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=SECOND_PM_ID, employee_code="PM-002", designation="PM", availability="available",
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
                ("T001", "work", "standard"),
                ("T002", "work", "class_a"),
                ("T003", "approval_gate", "class_a"),
                ("T004", "work", "standard"),
            ]
            template_tasks = []
            for i, (code, kind, klass) in enumerate(specs, start=1):
                template_tasks.append(V2TemplateTask(
                    template_version_id=published.id, code=code, sequence_no=i, title=f"Task {code}",
                    schedule_classification="execution", planned_start_day=i, planned_end_day=i,
                    applicability="mandatory", task_class=klass, task_kind=kind,
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ))
            session.add_all(template_tasks)
            session.flush()

            # T002 (class_a work) blocks T004 (standard work) - used to
            # test that a Class A predecessor only unblocks once PM-approved
            # (not merely Supervisor-verified).
            session.add(V2TemplateTaskDependency(
                template_version_id=published.id,
                predecessor_task_id=template_tasks[1].id,
                successor_task_id=template_tasks[3].id,
                dependency_type="finish_to_start", blocking=True,
                rule_text="T002 blocks T004", sequence_no=1,
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

    @property
    def internal_employee_id(self) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == INTERNAL_ID))

    def add_internal_member(self, project_id: str) -> None:
        """Idempotent - a test may drive more than one approval gate in the
        same project, and the Internal Employee only needs one active
        project membership for all of them."""
        with self.Session() as session:
            already_member = session.scalar(
                select(V2ProjectMembership.id).where(
                    V2ProjectMembership.project_id == uuid.UUID(project_id),
                    V2ProjectMembership.employee_id == self.internal_employee_id,
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
        if already_member:
            return
        self.act_as_pm()
        response = self.client.post(
            f"/api/v2/projects/{project_id}/memberships",
            json={
                "employee_id": str(self.internal_employee_id),
                "project_role": "internal_employee",
                "reason": "Delegate approval-gate execution.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def assign_support(self, project_id: str, task_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments",
            json={"employee_id": str(self.internal_employee_id), "responsibility": "Execute approval gate."},
        )

    def drive_to_submitted(self, project_id: str, task_id, submitted_by="pm"):
        """`submitted_by` controls who logs the progress being verified -
        default "pm" so a test calling `verify` as the Supervisor
        afterward exercises the normal case (TaskVerificationService.verify
        rejects a verifier who is also the submitter). Pass "supervisor"
        for tests that specifically need the Supervisor to be free to
        verify their own submission's *absence* of conflict, e.g. a test
        where the PM is the one verifying as a fallback.

        An approval-gate task ignores `submitted_by`: it has no
        Supervisor/PM self-execute fallback, so an Internal Employee must
        be delegated before work can start, and from then on only that
        delegate may move it to `in_progress`/`submitted` or log its
        progress (see `TaskLifecycleService._require_role_for_transition`
        and `TaskProgressService._require_progress_actor`). `submitted_by`
        only selects among the self-execute actors, none of which apply to
        a gate."""
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
        else:
            self.act_as_supervisor()

        in_progress = self.transition(project_id, task_id, "in_progress")
        self.assertEqual(in_progress.status_code, 200, in_progress.text)

        if not is_approval_gate:
            if submitted_by == "pm":
                self.act_as_pm()
            elif submitted_by == "admin":
                self.act_as_admin()
        sp = self.submit_progress(project_id, task_id)
        self.assertEqual(sp.status_code, 200, sp.text)

        if not is_approval_gate:
            self.act_as_supervisor()
        r = self.transition(project_id, task_id, "submitted")
        self.assertEqual(r.status_code, 200, r.text)

    # ---- happy paths ----------------------------------------------------

    def test_supervisor_verifies_standard_work_task_and_it_completes(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "completed")
            verifications = session.scalars(
                select(TaskVerification).where(TaskVerification.task_id == t001.id)
            ).all()
            self.assertEqual(len(verifications), 1)
            self.assertEqual(verifications[0].decision, "verified")

    def test_class_a_work_requires_verification_then_pm_approval_to_complete(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id)

        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "verified")

        self.act_as_pm()
        approve_response = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        self.assertEqual(approve_response.json()["task"]["lifecycle_status"], "completed")
        self.assertIsNotNone(approve_response.json()["verification_id"])

        with self.Session() as session:
            self.assertEqual(session.get(Task, t002.id).lifecycle_status, "completed")

    def test_pm_approves_approval_gate_directly_without_verification(self):
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)

        with self.Session() as session:
            self.assertEqual(
                session.scalar(select(TaskVerification).where(TaskVerification.task_id == t003.id)), None,
            )

        self.act_as_pm()
        r = self.approve(project["id"], t003.id, "approved")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")
        self.assertIsNone(r.json()["verification_id"])

    # ---- edge cases: role gating -----------------------------------------

    def test_non_supervisor_cannot_verify(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_outsider()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 403, r.text)

    def test_submitter_cannot_self_verify_but_a_different_verifier_can(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        # Supervisor executes and submits this task themselves (no
        # Internal Employee assigned) - no role rule authorizes them to
        # also verify their own submission.
        self.drive_to_submitted(project["id"], t001.id, submitted_by="supervisor")

        self.act_as_supervisor()
        self_verify = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(self_verify.status_code, 409, self_verify.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "submitted")

        # A different authorized verifier (PM, standing in as fallback) can.
        self.act_as_pm()
        different_verifier = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(different_verifier.status_code, 200, different_verifier.text)
        self.assertEqual(different_verifier.json()["task"]["lifecycle_status"], "completed")

    def test_unclassified_task_kind_can_still_be_verified_and_completes(self):
        # task_kind is nullable at the DB level - a task whose template row
        # never had a kind assigned during authoring (e.g. a legacy import
        # gap) must still be completable via the normal Supervisor
        # verification path, not left permanently stuck at `submitted`.
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        with self.Session.begin() as session:
            session.get(Task, t001.id).task_kind = None

        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

    def test_unclassified_task_class_completes_on_verification_not_stuck_awaiting_pm(self):
        # task_class is nullable, same as task_kind. Only "class_a" needs
        # PM approval - task_approval.py.approve() rejects anything else,
        # so a null task_class must auto-complete on verify() the same as
        # "standard", or it would be stuck at `verified` forever with no
        # PM mechanism able to move it forward.
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        with self.Session.begin() as session:
            session.get(Task, t001.id).task_class = None

        self.drive_to_submitted(project["id"], t001.id)
        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

    def test_admin_may_self_verify_as_blanket_override(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        # Admin both submits the progress and verifies it - Admin retains
        # its blanket override even for the self-verification guard.
        self.drive_to_submitted(project["id"], t001.id, submitted_by="admin")

        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "completed")

    def _end_membership(self, project_id: str, role: str) -> None:
        """Simulates a role being unavailable on the project: ends its
        active membership row, same shape a real reassignment leaves
        behind. Used to distinguish a genuine BR-007 fallback from an
        Admin override in the decision_mode tests below."""
        with self.Session.begin() as session:
            membership = session.scalar(
                select(V2ProjectMembership).where(
                    V2ProjectMembership.project_id == uuid.UUID(project_id),
                    V2ProjectMembership.project_role == role,
                    V2ProjectMembership.ends_at.is_(None),
                )
            )
            membership.ends_at = datetime.now(timezone.utc)

    def test_normal_supervisor_verification_is_tagged_role_normal(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id, submitted_by="pm")
        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        with self.Session() as session:
            row = session.scalar(select(TaskVerification).where(TaskVerification.task_id == t001.id))
            self.assertEqual(row.decision_mode, "role_normal")

    def test_admin_verifying_with_an_active_supervisor_is_tagged_override(self):
        # activate_project() always assigns a Supervisor, so an Admin acting
        # here is bypassing someone genuinely available, not covering an
        # absence - decision_mode must say so, distinct from a real fallback.
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id, submitted_by="pm")
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["decision_mode"], "admin_override")
        with self.Session() as session:
            row = session.scalar(select(TaskVerification).where(TaskVerification.task_id == t001.id))
            self.assertEqual(row.decision_mode, "admin_override")

    def test_admin_verifying_with_no_active_supervisor_is_tagged_fallback(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id, submitted_by="pm")
        # Only now does the Supervisor become unavailable - drive_to_submitted
        # itself needs an active Supervisor for the ready/in_progress steps.
        self._end_membership(project["id"], "site_supervisor")
        self.act_as_admin()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["decision_mode"], "admin_fallback")

    def test_admin_approving_with_an_active_pm_is_tagged_override(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id, submitted_by="admin")
        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)

        self.act_as_admin()
        r = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["decision_mode"], "admin_override")

    def test_admin_approving_with_no_active_pm_is_tagged_fallback(self):
        project = self.activate_project()
        self._end_membership(project["id"], "project_manager")
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id, submitted_by="admin")
        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)

        self.act_as_admin()
        r = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["decision_mode"], "admin_fallback")

    def test_non_pm_cannot_approve_class_a_or_gate(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id)
        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)

        self.act_as_outsider()
        approve_response = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(approve_response.status_code, 403, approve_response.text)

        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)
        self.act_as_outsider()
        gate_response = self.approve(project["id"], t003.id, "approved")
        self.assertEqual(gate_response.status_code, 403, gate_response.text)

    def test_verifying_task_not_in_submitted_status_is_rejected(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        # T001 still "planned" - never driven to submitted.
        self.act_as_supervisor()
        r = self.verify(project["id"], t001.id, "verified")
        self.assertEqual(r.status_code, 409, r.text)

    # ---- rejection ---------------------------------------------------------

    def test_rejection_without_reason_is_rejected_with_reason_reopens_task(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.drive_to_submitted(project["id"], t001.id)

        self.act_as_supervisor()
        no_reason = self.verify(project["id"], t001.id, "rejected")
        self.assertEqual(no_reason.status_code, 422, no_reason.text)

        with_reason = self.verify(project["id"], t001.id, "rejected", remarks="Rework the finish.")
        self.assertEqual(with_reason.status_code, 200, with_reason.text)
        self.assertEqual(with_reason.json()["task"]["lifecycle_status"], "in_progress")

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "in_progress")

    def test_approval_rejection_without_reason_is_rejected_with_reason_reopens_task(self):
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)

        self.act_as_pm()
        no_reason = self.approve(project["id"], t003.id, "rejected")
        self.assertEqual(no_reason.status_code, 422, no_reason.text)

        with_reason = self.approve(project["id"], t003.id, "rejected", remarks="Missing signature.")
        self.assertEqual(with_reason.status_code, 200, with_reason.text)
        self.assertEqual(with_reason.json()["task"]["lifecycle_status"], "in_progress")

    # ---- fallback verifier cannot also approve ------------------------------

    def test_fallback_pm_verifier_cannot_also_approve_but_a_different_actor_can(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id, submitted_by="supervisor")

        # PM verifies as a Supervisor fallback (not the active Supervisor) -
        # the project's active PM is a permitted verifier per
        # TaskVerificationService._require_verifier, but is not the active
        # Supervisor, so this is the "fallback verifier" case BR-008 flags.
        self.act_as_pm()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "verified")

        # The same PM cannot also record this task's approval decision.
        same_pm = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(same_pm.status_code, 409, same_pm.text)

        # A different authorized actor (Admin) can.
        self.act_as_admin()
        different_actor = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(different_actor.status_code, 200, different_actor.text)
        self.assertEqual(different_actor.json()["task"]["lifecycle_status"], "completed")

    def test_super_admin_fallback_verifier_cannot_also_approve(self):
        """Super Admin holds Admin's project authority but no separation-of-duty
        bypass: having verified in the Supervisor's place, it cannot approve."""
        super_admin = User(
            id=uuid.UUID("abababab-abab-4bab-8bab-abababababab"), name="Super Admin",
            email="super@example.com", role=UserRole.super_admin, active=True,
        )
        with self.Session.begin() as session:
            session.add(super_admin)
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id, submitted_by="supervisor")

        self.act_as(super_admin)
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        same_actor = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(same_actor.status_code, 409, same_actor.text)

        self.act_as_pm()
        different_actor = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(different_actor.status_code, 200, different_actor.text)

    # ---- integration: predecessor decision unblocks successor ---------------

    def test_class_a_predecessor_only_unblocks_successor_once_pm_approved(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t002, t004 = tasks["T002"], tasks["T004"]

        self.drive_to_submitted(project["id"], t002.id)
        self.act_as_supervisor()
        r = self.verify(project["id"], t002.id, "verified")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["lifecycle_status"], "verified")

        # T002 is merely "verified" (Supervisor-verified, not yet
        # PM-approved) - per BR-008, Class A predecessors require PM
        # approval (completed), so T004 must still be blocked. Per the
        # plan (R8/BR-011), the predecessor-satisfied check gates both
        # `ready` and `in_progress`, not just `in_progress`.
        self.act_as_supervisor()
        still_blocked = self.transition(project["id"], t004.id, "ready")
        self.assertEqual(still_blocked.status_code, 409, still_blocked.text)

        # PM approves T002 -> completed.
        self.act_as_pm()
        approve_response = self.approve(project["id"], t002.id, "approved")
        self.assertEqual(approve_response.status_code, 200, approve_response.text)
        self.assertEqual(approve_response.json()["task"]["lifecycle_status"], "completed")

        # Now T004 unblocks.
        self.act_as_supervisor()
        ready = self.transition(project["id"], t004.id, "ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        unblocked = self.transition(project["id"], t004.id, "in_progress")
        self.assertEqual(unblocked.status_code, 200, unblocked.text)
        self.assertEqual(unblocked.json()["lifecycle_status"], "in_progress")

    # ---- review cycle: only progress logged since the last decision counts ----

    NEW_PROGRESS_REFUSAL = "Log a new progress update"

    def progress_rows(self, task_id) -> list[TaskProgressUpdate]:
        with self.Session() as session:
            return list(session.scalars(select(TaskProgressUpdate).where(TaskProgressUpdate.task_id == task_id)))

    def start_as_supervisor(self, project_id: str, task_id) -> None:
        self.act_as_supervisor()
        for status in ("ready", "in_progress"):
            self.assertEqual(self.transition(project_id, task_id, status).status_code, 200)

    def submit_with_notes(self, project_id: str, task_id, *notes: str) -> None:
        """PM logs every note (so the Supervisor can verify), Supervisor submits."""
        self.act_as_pm()
        for note in notes:
            self.assertEqual(self.submit_progress(project_id, task_id, note=note).status_code, 200)
        self.act_as_supervisor()
        self.assertEqual(self.transition(project_id, task_id, "submitted").status_code, 200)

    def test_every_update_of_a_rejected_cycle_is_marked_reviewed(self):
        """The decision covers every update of the cycle, not just the latest
        one a verification names."""
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start_as_supervisor(project["id"], t001.id)
        self.submit_with_notes(project["id"], t001.id, "First item.", "Second item.", "Third item.")

        self.act_as_supervisor()
        self.assertEqual(self.verify(project["id"], t001.id, "rejected", remarks="Redo.").status_code, 200)

        rows = self.progress_rows(t001.id)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.reviewed_at is not None for row in rows))

    def test_rejected_cycle_cannot_be_resubmitted_until_new_progress_is_logged(self):
        """AE2: before U2 only the latest update was consumed, so an older
        update of the rejected cycle still satisfied the resubmission."""
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start_as_supervisor(project["id"], t001.id)
        self.submit_with_notes(project["id"], t001.id, "Earlier note.", "Later note.")
        self.assertEqual(self.verify(project["id"], t001.id, "rejected", remarks="Redo.").status_code, 200)

        refused = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn(self.NEW_PROGRESS_REFUSAL, refused.json()["detail"])

        self.act_as_pm()
        self.assertEqual(self.submit_progress(project["id"], t001.id, note="Reworked.").status_code, 200)
        self.act_as_supervisor()
        self.assertEqual(self.transition(project["id"], t001.id, "submitted").status_code, 200)

    def test_class_a_pm_rejection_requires_new_progress_before_resubmission(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.drive_to_submitted(project["id"], t002.id)
        self.act_as_supervisor()
        self.assertEqual(self.verify(project["id"], t002.id, "verified").status_code, 200)
        self.act_as_pm()
        rejected = self.approve(project["id"], t002.id, "rejected", remarks="Wrong finish grade.")
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["task"]["lifecycle_status"], "in_progress")

        self.act_as_supervisor()
        refused = self.transition(project["id"], t002.id, "submitted")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn(self.NEW_PROGRESS_REFUSAL, refused.json()["detail"])

        self.act_as_pm()
        self.assertEqual(self.submit_progress(project["id"], t002.id, note="Regraded.").status_code, 200)
        self.act_as_supervisor()
        self.assertEqual(self.transition(project["id"], t002.id, "submitted").status_code, 200)

    def test_approval_gate_first_submission_needs_progress(self):
        """R19: an intentional shared change - approval-gate tasks used to be
        submittable with no progress at all."""
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.act_as_supervisor()
        self.assertEqual(self.transition(project["id"], t003.id, "ready").status_code, 200)
        self.add_internal_member(project["id"])
        self.assertEqual(self.assign_support(project["id"], t003.id).status_code, 200)
        self.act_as_internal()
        self.assertEqual(self.transition(project["id"], t003.id, "in_progress").status_code, 200)

        refused = self.transition(project["id"], t003.id, "submitted")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn(self.NEW_PROGRESS_REFUSAL, refused.json()["detail"])

        self.assertEqual(self.submit_progress(project["id"], t003.id, note="Permit filed.").status_code, 200)
        self.assertEqual(self.transition(project["id"], t003.id, "submitted").status_code, 200)

    def test_approval_gate_pm_rejection_requires_new_progress_before_resubmission(self):
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)
        self.act_as_pm()
        self.assertEqual(self.approve(project["id"], t003.id, "rejected", remarks="Unsigned copy.").status_code, 200)

        self.act_as_internal()
        refused = self.transition(project["id"], t003.id, "submitted")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn(self.NEW_PROGRESS_REFUSAL, refused.json()["detail"])

        self.assertEqual(self.submit_progress(project["id"], t003.id, note="Signed copy.").status_code, 200)
        self.assertEqual(self.transition(project["id"], t003.id, "submitted").status_code, 200)

    def test_an_approving_decision_also_closes_the_cycle(self):
        project = self.activate_project()
        t003 = self.tasks_by_code(project["id"])["T003"]
        self.drive_to_submitted(project["id"], t003.id)
        self.act_as_pm()
        self.assertEqual(self.approve(project["id"], t003.id, "approved").status_code, 200)
        self.assertTrue(all(row.reviewed_at is not None for row in self.progress_rows(t003.id)))


if __name__ == "__main__":
    unittest.main()
