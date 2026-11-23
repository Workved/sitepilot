"""U7: a task flagged evidence-required cannot reach review without evidence.

`Task.evidence_required` has travelled template -> baseline -> execution task
-> API since the beginning and has never been enforced. These tests pin the
server-side precondition, which the board (U22) mirrors but does not replace.

Deliberately a separate file from test_task_lifecycle_transitions_v2.py and
test_task_progress_evidence_v2.py: every template task in both is authored
`evidence_required=False`, so the branch under test is unreachable from either
and a green run there proves nothing about this unit.
"""


from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

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

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)

PNG_UPLOAD = {"evidence": ("bay3.png", TINY_PNG_BYTES, "image/png")}


class TaskEvidenceRequiredApiTests(unittest.TestCase):
    def setUp(self):
        pin_project_creation_today(self)
        self.evidence_store: dict[str, bytes] = {}
        self._storage_patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, content_type: self.evidence_store.__setitem__(key, data)),
            patch("app.services.evidence_storage.read", side_effect=self.evidence_store.get),
            patch("app.services.evidence_storage.delete", side_effect=lambda key: self.evidence_store.pop(key, None)),
        ]
        for storage_patch in self._storage_patches:
            storage_patch.start()

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
            TaskBlocker.__table__,
            TaskDelayEvent.__table__,
            TaskApprovalDecision.__table__,
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
        for storage_patch in self._storage_patches:
            storage_patch.stop()

    # ---- actors --------------------------------------------------------

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_pm(self) -> None:
        self.act_as(User(
            id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True,
        ))

    def act_as_supervisor(self) -> None:
        self.act_as(User(
            id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
            role=UserRole.supervisor, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Two independent work tasks differing only in `evidence_required`,
        so the flag is the single variable between them."""
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

            session.add_all([
                V2TemplateTask(
                    template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                    schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=True, duration_days=1, phase="Setup", category="Site",
                ),
                V2TemplateTask(
                    template_version_id=published.id, code="T002", sequence_no=2, title="Task T002",
                    schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=1, phase="Setup", category="Site",
                ),
            ])
            self.published_version_id = published.id

    # ---- harness -------------------------------------------------------

    def create_draft(self, **overrides):
        payload = {
            "project_name": "Futurex Fitout",
            "client": "Example Client",
            "location": "Mumbai",
            # Deliberately in the past: a future-dated project would trip
            # U14's early-start reason requirement, which is not what these
            # tests are measuring.
            "proposed_start_date": "2026-01-05",
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

    def submit_progress(self, project_id: str, task_id, note="Work done.", files=None):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/progress",
            data={"note": note},
            files=files,
        )

    def verify(self, project_id: str, task_id, decision: str, remarks: str | None = None):
        body: dict = {"decision": decision}
        if remarks is not None:
            body["remarks"] = remarks
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/verify", json=body)

    def start(self, project_id: str, task_id) -> None:
        self.act_as_supervisor()
        for status in ("ready", "in_progress"):
            response = self.transition(project_id, task_id, status)
            self.assertEqual(response.status_code, 200, response.text)

    def log_progress(self, project_id: str, task_id, note="Work done.", files=None) -> None:
        """The PM logs progress so a later `verify` by the Supervisor is not a
        self-verification, which TaskVerificationService refuses."""
        self.act_as_pm()
        response = self.submit_progress(project_id, task_id, note=note, files=files)
        self.assertEqual(response.status_code, 200, response.text)
        self.act_as_supervisor()

    # ---- the flag is enforced -------------------------------------------

    def test_evidence_required_task_with_a_note_only_update_cannot_be_submitted(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.assertTrue(t001.evidence_required)
        self.start(project["id"], t001.id)
        self.log_progress(project["id"], t001.id, note="Bay 3 poured.")

        response = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(response.status_code, 409, response.text)

        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "in_progress")

    def test_evidence_required_task_with_a_file_carrying_update_can_be_submitted(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start(project["id"], t001.id)
        self.log_progress(project["id"], t001.id, note="Bay 3 poured.", files=PNG_UPLOAD)

        response = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["lifecycle_status"], "submitted")

    def test_task_not_flagged_evidence_required_can_be_submitted_with_a_note_only(self):
        project = self.activate_project()
        t002 = self.tasks_by_code(project["id"])["T002"]
        self.assertFalse(t002.evidence_required)
        self.start(project["id"], t002.id)
        self.log_progress(project["id"], t002.id, note="Snag list cleared.")

        response = self.transition(project["id"], t002.id, "submitted")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["lifecycle_status"], "submitted")

    # ---- what the refusal says ------------------------------------------

    def test_the_refusal_names_evidence_as_the_missing_item(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start(project["id"], t001.id)
        self.log_progress(project["id"], t001.id, note="Bay 3 poured.")

        detail = self.transition(project["id"], t001.id, "submitted").json()["detail"]
        self.assertEqual(
            detail,
            "This task requires evidence. Attach a file to a new progress update "
            "before submitting this task for review.",
        )

    def test_a_task_with_no_progress_update_reports_missing_progress_not_missing_evidence(self):
        """The board disambiguates on the backend's own wording, so the two
        refusals must not read alike even though both mention evidence."""
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start(project["id"], t001.id)

        response = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertEqual(
            detail,
            "Log a new progress update (a note and/or evidence) before submitting this task for review.",
        )
        self.assertNotIn("requires evidence", detail)

    # ---- already-reviewed evidence does not count again ------------------

    def test_evidence_on_an_already_reviewed_update_cannot_carry_a_resubmission(self):
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start(project["id"], t001.id)
        self.log_progress(project["id"], t001.id, note="First pour.", files=PNG_UPLOAD)
        self.assertEqual(self.transition(project["id"], t001.id, "submitted").status_code, 200)

        rejected = self.verify(project["id"], t001.id, "rejected", remarks="Finish is not acceptable.")
        self.assertEqual(rejected.status_code, 200, rejected.text)
        with self.Session() as session:
            self.assertEqual(session.get(Task, t001.id).lifecycle_status, "in_progress")

        # A fresh note-only update clears the missing-progress precondition, so
        # only the evidence rule can be what refuses this - and the one file on
        # record is the file the rejection already decided on.
        self.log_progress(project["id"], t001.id, note="Reworked the finish.")
        response = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("requires evidence", response.json()["detail"])

        # New evidence, and the resubmission goes through.
        self.log_progress(project["id"], t001.id, note="Rework photographed.", files=PNG_UPLOAD)
        allowed = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(allowed.status_code, 200, allowed.text)

    def test_a_rejected_photo_that_was_not_the_latest_update_cannot_carry_a_resubmission(self):
        """AE2: a verification names only the latest
        update, so before `reviewed_at` a photo logged earlier in the rejected
        cycle - followed by a note - still counted as fresh evidence."""
        project = self.activate_project()
        t001 = self.tasks_by_code(project["id"])["T001"]
        self.start(project["id"], t001.id)
        self.log_progress(project["id"], t001.id, note="Pour photographed.", files=PNG_UPLOAD)
        self.log_progress(project["id"], t001.id, note="Curing started.")
        self.assertEqual(self.transition(project["id"], t001.id, "submitted").status_code, 200)
        self.assertEqual(
            self.verify(project["id"], t001.id, "rejected", remarks="Honeycombing on the face.").status_code, 200,
        )

        no_progress = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(no_progress.status_code, 409, no_progress.text)
        self.assertIn("Log a new progress update", no_progress.json()["detail"])

        self.log_progress(project["id"], t001.id, note="Patched the face.")
        note_only = self.transition(project["id"], t001.id, "submitted")
        self.assertEqual(note_only.status_code, 409, note_only.text)
        self.assertIn("requires evidence", note_only.json()["detail"])

        self.log_progress(project["id"], t001.id, note="Patch photographed.", files=PNG_UPLOAD)
        self.assertEqual(self.transition(project["id"], t001.id, "submitted").status_code, 200)


if __name__ == "__main__":
    unittest.main()
