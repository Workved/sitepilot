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


class ExecutionTasksReadApiTests(unittest.TestCase):
    """Read-side endpoints TaskExecutionBoard depends on: a project-scoped
    task list (`GET /{project_id}/tasks`) and a per-task detail view
    (`GET /{project_id}/tasks/{task_id}`), neither of which existed before -
    only mutation endpoints did. Same SQLite-ATTACHed-schema harness as
    test_task_lifecycle_transitions_v2.py."""

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
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
        self.app.dependency_overrides[current_user] = lambda: self._current_actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def act_as_admin(self):
        self._current_actor = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)

    def act_as_supervisor(self):
        self._current_actor = User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True,
        )

    def act_as_outsider(self):
        self._current_actor = User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True,
        )

    def _seed(self):
        """Two work tasks, T001 -> T002 (blocking finish_to_start), both mandatory/standard."""
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True)
            outsider = User(id=OUTSIDER_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True)
            session.add_all([admin, pm, supervisor, outsider])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available"),
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

    def create_draft(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
            "proposed_start_date": "2026-08-01", "target_handover_date": "2026-09-14",
            "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID),
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

    def transition(self, project_id, task_id, target_status, reason=None):
        body = {"target_status": target_status}
        if reason is not None:
            body["reason"] = reason
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/status", json=body)

    # ---- list endpoint --------------------------------------------------

    def test_list_returns_all_tasks_in_sequence_with_current_status(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])

        self.act_as_supervisor()
        self.transition(project["id"], tasks["T001"].id, "ready")

        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual([row["original_code"] for row in body], ["T001", "T002"])
        self.assertEqual(body[0]["lifecycle_status"], "ready")
        self.assertEqual(body[1]["lifecycle_status"], "planned")
        self.assertEqual(body[0]["open_blocker_count"], 0)
        self.assertEqual(body[0]["active_support_count"], 0)
        self.assertEqual(body[0]["approval"]["approval_status"], "not_started")
        self.assertEqual(body[1]["approval"]["approval_status"], "not_started")

    def test_list_reflects_open_blocker_and_active_support_counts(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])

        self.act_as_supervisor()
        blocker = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{tasks['T001'].id}/blockers",
            json={"type": "material", "description": "Waiting on cement delivery."},
        )
        self.assertEqual(blocker.status_code, 200, blocker.text)

        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        body = {row["original_code"]: row for row in response.json()}
        self.assertEqual(body["T001"]["open_blocker_count"], 1)

        self.act_as_supervisor()
        resolve = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{tasks['T001'].id}/blockers/{blocker.json()['id']}/resolve"
        )
        self.assertEqual(resolve.status_code, 200, resolve.text)
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        body = {row["original_code"]: row for row in response.json()}
        self.assertEqual(body["T001"]["open_blocker_count"], 0)

    def test_list_denies_actor_without_project_membership(self):
        project = self.activate_project()
        self.act_as_outsider()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks")
        self.assertEqual(response.status_code, 403, response.text)

    # ---- detail endpoint --------------------------------------------------

    def test_detail_includes_predecessors_progress_and_decisions(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001, t002 = tasks["T001"], tasks["T002"]

        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready")
        self.transition(project["id"], t001.id, "in_progress")
        # Submitted as Admin, not the Supervisor who will verify below - no
        # role rule authorizes verifying your own submitted progress.
        self.act_as_admin()
        progress = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/progress",
            data={"note": "Work completed, ready for review."},
        )
        self.assertEqual(progress.status_code, 200, progress.text)
        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "submitted")
        verify = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/verify",
            json={"decision": "verified"},
        )
        self.assertEqual(verify.status_code, 200, verify.text)

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        body = detail.json()
        self.assertEqual(body["lifecycle_status"], "completed")
        self.assertEqual(len(body["progress_updates"]), 1)
        self.assertEqual(body["progress_updates"][0]["note"], "Work completed, ready for review.")
        # The verification closed this cycle, so the board's submit rule sees
        # the update as already reviewed.
        self.assertIsNotNone(body["progress_updates"][0]["reviewed_at"])
        self.assertEqual(len(body["verifications"]), 1)
        self.assertEqual(body["verifications"][0]["decision"], "verified")
        # The frontend relies on this to tell an already-decided progress
        # update apart from a fresh one (TaskExecutionBoard's
        # needsFreshProgressUpdate) - it must name the actual update decided
        # on, not just be present.
        self.assertEqual(body["verifications"][0]["submission_update_id"], body["progress_updates"][0]["id"])
        self.assertEqual(body["blockers"], [])
        self.assertEqual(body["support_assignments"], [])
        # T001 is standard work: verification only, no PM approval, and it
        # has just completed - approval metadata should reflect that.
        self.assertEqual(body["approval"]["task_class"], "standard")
        self.assertEqual(body["approval"]["approval_summary"], "supervisor_verification")
        self.assertFalse(body["approval"]["approval_required"])
        self.assertEqual(body["approval"]["approval_status"], "approved")
        self.assertFalse(body["actor_is_assigned_support"])

        detail_t002 = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t002.id}")
        predecessor_codes = [p["original_code"] for p in detail_t002.json()["predecessors"]]
        self.assertEqual(predecessor_codes, ["T001"])
        self.assertTrue(detail_t002.json()["predecessors"][0]["blocking"])

    def test_detail_includes_audit_trail_and_resolved_actor_names(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]

        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "ready")
        self.transition(project["id"], t001.id, "in_progress")
        # Submitted as Admin, not the Supervisor who will verify below - no
        # role rule authorizes verifying your own submitted progress.
        self.act_as_admin()
        self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/progress",
            data={"note": "Work completed."},
        )
        self.act_as_supervisor()
        self.transition(project["id"], t001.id, "submitted")
        verify = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/verify",
            json={"decision": "verified"},
        )
        self.assertEqual(verify.status_code, 200, verify.text)

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        body = detail.json()
        self.assertEqual(body["lifecycle_status"], "completed")

        # Every status transition (ready, in_progress, submitted, verified,
        # completed) has its own audit event, actor-attributed by name.
        self.assertEqual(len(body["audit_events"]), 5)
        completed_event = next(e for e in body["audit_events"] if e["after_status"] == "completed")
        self.assertEqual(completed_event["actor_name"], "Supervisor")

        self.assertEqual(body["verifications"][0]["verified_by_name"], "Supervisor")

    def test_cancellation_reason_and_actor_are_recoverable_from_audit_events(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])
        t001 = tasks["T001"]

        self.act_as_admin()
        cancel = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{t001.id}/status",
            json={"target_status": "cancelled", "reason": "Scope removed by client."},
        )
        self.assertEqual(cancel.status_code, 200, cancel.text)

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{t001.id}")
        body = detail.json()
        self.assertEqual(body["lifecycle_status"], "cancelled")

        cancellation_event = next(e for e in body["audit_events"] if e["after_status"] == "cancelled")
        self.assertEqual(cancellation_event["reason"], "Scope removed by client.")
        self.assertEqual(cancellation_event["actor_name"], "Admin")

    def test_detail_404_for_unknown_task_and_403_for_outsider(self):
        project = self.activate_project()
        tasks = self.tasks_by_code(project["id"])

        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404, response.text)

        self.act_as_outsider()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{tasks['T001'].id}")
        self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
