from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.config import settings
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
INTERNAL_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TaskProgressEvidenceApiTests(unittest.TestCase):
    """U3: progress updates and evidence submission (R3), against real
    execution tasks produced by U1's baseline-lock activation flow.

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_lifecycle_transitions_v2.py.
    """

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
            TaskSupportAssignment.__table__,
            TaskProgressUpdate.__table__,
            FileObject.__table__,
            TaskEvidence.__table__,
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
        for storage_patch in self._storage_patches:
            storage_patch.stop()

    def act_as(self, user: User) -> None:
        self._current_actor = user

    def act_as_admin(self) -> None:
        self.act_as(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))

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

    def act_as_internal_employee(self) -> None:
        self.act_as(User(
            id=INTERNAL_ID, name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        ))

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work). Also seeds an OUTSIDER user
        with an EmployeeProfile but no membership on the created project, to
        exercise the "no active project membership" edge cases."""
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
                id=INTERNAL_ID, name="Internal", email="internal@example.com",
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
                    user_id=INTERNAL_ID, employee_code="INT-001", designation="Internal Employee", availability="available",
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
        """T001, already `in_progress`: progress may only be logged on work
        in progress (TaskProgressService), and these tests are about
        progress/evidence rules, not the lifecycle that gets a task there."""
        with self.Session.begin() as session:
            task = session.scalar(
                select(Task).where(Task.project_id == uuid.UUID(project_id), Task.original_code == "T001")
            )
            task.lifecycle_status = "in_progress"
        return task

    @property
    def internal_employee_id(self) -> uuid.UUID:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == INTERNAL_ID))

    def add_internal_member(self, project_id: str) -> None:
        previous_actor = self._current_actor
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
        response = self.client.post(
            f"/api/v2/projects/{project_id}/memberships",
            json={
                "employee_id": str(self.internal_employee_id),
                "project_role": "internal_employee",
                "reason": "Add support staff.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self._current_actor = previous_actor

    def assign_support(self, project_id: str, task_id):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/support-assignments",
            json={"employee_id": str(self.internal_employee_id), "responsibility": "Execution."},
        )

    def submit_progress(self, project_id: str, task_id, note=None, status_claim=None, files=None):
        data = {}
        if note is not None:
            data["note"] = note
        if status_claim is not None:
            data["status_claim"] = status_claim
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/progress",
            data=data,
            files=files,
        )

    # ---- happy path -----------------------------------------------------

    def test_submit_progress_with_evidence_creates_progress_update_and_file_rows(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(
            project["id"], task.id, note="Formwork complete for bay 3.",
            files={"evidence": ("bay3.png", TINY_PNG_BYTES, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["update_type"], "evidence")
        self.assertEqual(body["note"], "Formwork complete for bay 3.")
        self.assertEqual(len(body["evidence"]), 1)
        # Compressed on upload (app.services.evidence_image): every
        # accepted image is standardized to JPEG, so an uploaded PNG comes
        # back as image/jpeg, not the original mime type.
        self.assertEqual(body["evidence"][0]["mime_type"], "image/jpeg")
        self.assertEqual(body["evidence"][0]["original_filename"], "bay3.png")

        with self.Session() as session:
            updates = session.scalars(select(TaskProgressUpdate).where(TaskProgressUpdate.task_id == task.id)).all()
            self.assertEqual(len(updates), 1)
            files = session.scalars(select(FileObject)).all()
            self.assertEqual(len(files), 1)
            evidence_rows = session.scalars(select(TaskEvidence)).all()
            self.assertEqual(len(evidence_rows), 1)
            self.assertIn(files[0].storage_key, self.evidence_store)
            # Stored bytes are the compressed JPEG re-encode, not a byte-
            # for-byte copy of the uploaded PNG.
            self.assertNotEqual(self.evidence_store[files[0].storage_key], TINY_PNG_BYTES)
            self.assertTrue(files[0].storage_key.endswith(".jpg"))

    def test_submit_text_only_progress_without_evidence_succeeds(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(project["id"], task.id, note="Crew on site, no issues.")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["update_type"], "note")
        self.assertEqual(body["evidence"], [])

        with self.Session() as session:
            self.assertEqual(session.scalar(select(FileObject).limit(1)), None)

    # ---- edge cases -------------------------------------------------------

    def test_disallowed_mime_type_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(
            project["id"], task.id, note="Bad file.",
            files={"evidence": ("payload.exe", b"not-a-real-image", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskProgressUpdate).limit(1)), None)

    def test_oversized_file_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        oversized = b"\x00" * (10 * 1024 * 1024 + 1)
        response = self.submit_progress(
            project["id"], task.id, note="Too big.",
            files={"evidence": ("huge.png", oversized, "image/png")},
        )
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskProgressUpdate).limit(1)), None)

    def test_no_note_and_no_evidence_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(project["id"], task.id)
        self.assertEqual(response.status_code, 422, response.text)

    # ---- permission: assigned Internal Employee owns progress logging -----

    def test_supervisor_cannot_log_progress_once_an_internal_employee_is_assigned(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        self.add_internal_member(project["id"])

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], task.id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        response = self.submit_progress(project["id"], task.id, note="Supervisor trying to log on their behalf.")
        self.assertEqual(response.status_code, 403, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskProgressUpdate).limit(1)), None)

    def test_assigned_internal_employee_can_log_progress(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        self.add_internal_member(project["id"])

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], task.id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        self.act_as_internal_employee()
        response = self.submit_progress(project["id"], task.id, note="Formwork complete.")
        self.assertEqual(response.status_code, 200, response.text)

    def test_unassigned_internal_employee_cannot_log_progress_on_a_task_assigned_to_someone_else(self):
        # A second Internal Employee, project member but never
        # support-assigned to THIS task, must not be able to log progress
        # on it - only the assigned one may, per _require_progress_actor.
        other_id = uuid.uuid4()
        with self.Session.begin() as session:
            other = User(
                id=other_id, name="Other Internal", email="other-internal@example.com",
                role=UserRole.internal_employee, active=True,
            )
            session.add(other)
            session.flush()
            session.add(EmployeeProfile(
                user_id=other_id, employee_code="INT-002", designation="Internal Employee", availability="available",
            ))

        project = self.activate_project()
        task = self.task_t001(project["id"])
        self.add_internal_member(project["id"])

        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
        with self.Session() as session:
            other_employee_id = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == other_id))
        membership = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(other_employee_id), "project_role": "internal_employee", "reason": "Add second employee."},
        )
        self.assertEqual(membership.status_code, 200, membership.text)

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], task.id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        self.act_as(User(id=other_id, name="Other Internal", email="other-internal@example.com", role=UserRole.internal_employee, active=True))
        response = self.submit_progress(project["id"], task.id, note="Not my task.")
        self.assertEqual(response.status_code, 403, response.text)

    def test_admin_can_log_progress_even_with_an_assigned_internal_employee(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        self.add_internal_member(project["id"])

        self.act_as_supervisor()
        assigned = self.assign_support(project["id"], task.id)
        self.assertEqual(assigned.status_code, 200, assigned.text)

        self.act_as_admin()
        response = self.submit_progress(project["id"], task.id, note="Admin override.")
        self.assertEqual(response.status_code, 200, response.text)

    # ---- error path: no active project membership -------------------------

    def test_actor_with_no_active_membership_cannot_submit_progress(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_outsider()
        response = self.submit_progress(project["id"], task.id, note="Should not be allowed.")
        self.assertEqual(response.status_code, 403, response.text)

        with self.Session() as session:
            self.assertEqual(session.scalar(select(TaskProgressUpdate).limit(1)), None)

    def test_actor_with_no_active_membership_cannot_download_evidence(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(
            project["id"], task.id, note="Evidence for download test.",
            files={"evidence": ("bay3.png", TINY_PNG_BYTES, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        file_id = response.json()["evidence"][0]["file_id"]

        self.act_as_outsider()
        download = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/evidence/{file_id}")
        self.assertEqual(download.status_code, 403, download.text)

    # ---- integration: authenticated download ------------------------------

    def test_authorized_download_succeeds_and_unauthorized_download_is_rejected(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(
            project["id"], task.id, note="Evidence for download test.",
            files={"evidence": ("bay3.png", TINY_PNG_BYTES, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        file_id = response.json()["evidence"][0]["file_id"]

        # Authorized: the submitting Supervisor can download.
        download = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/evidence/{file_id}")
        self.assertEqual(download.status_code, 200, download.text)
        # Compressed on upload - downloaded bytes are the stored JPEG
        # re-encode, not the originally-uploaded PNG.
        self.assertNotEqual(download.content, TINY_PNG_BYTES)
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")
        self.assertIn("attachment", download.headers["content-disposition"])

        # Authorized: PM (an active project member) can also download.
        self.act_as(User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True))
        pm_download = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/evidence/{file_id}")
        self.assertEqual(pm_download.status_code, 200, pm_download.text)

        # Unauthorized: an actor with no membership on this project is rejected.
        self.act_as_outsider()
        outsider_download = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/evidence/{file_id}")
        self.assertEqual(outsider_download.status_code, 403, outsider_download.text)

    def test_evidence_never_lands_on_local_disk(self):
        """Sanity check that submitting evidence never touches the local
        filesystem at all - it goes straight to `evidence_storage`'s
        Supabase Storage bucket, never a path under the public `/uploads`
        StaticFiles mount (settings.upload_dir)."""
        project = self.activate_project()
        task = self.task_t001(project["id"])

        self.act_as_supervisor()
        response = self.submit_progress(
            project["id"], task.id, note="Evidence for disk-isolation check.",
            files={"evidence": ("bay3.png", TINY_PNG_BYTES, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            file_object = session.scalars(select(FileObject)).first()
        storage_key = file_object.storage_key

        upload_dir = Path(settings.upload_dir)
        if upload_dir.is_dir():
            self.assertEqual(list(upload_dir.rglob(f"*{storage_key}*")), [])

    # ---- progress only while in_progress --------------

    def test_progress_is_refused_outside_in_progress_and_leaves_nothing_behind(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        self.act_as_supervisor()

        for status in ("planned", "ready", "submitted", "verified", "completed"):
            with self.subTest(status=status):
                with self.Session.begin() as session:
                    session.get(Task, task.id).lifecycle_status = status
                response = self.submit_progress(
                    project["id"], task.id, note="Should not be stored.",
                    files={"evidence": ("bay3.png", TINY_PNG_BYTES, "image/png")},
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn("only be logged while the task is in progress", response.json()["detail"])
                self.assertIn(status, response.json()["detail"])

        with self.Session() as session:
            self.assertEqual(session.scalars(select(TaskProgressUpdate)).all(), [])
            self.assertEqual(session.scalars(select(FileObject)).all(), [])
        # Refused before the storage write, not cleaned up after it.
        self.assertEqual(self.evidence_store, {})

    def test_progress_is_accepted_in_progress(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        self.act_as_supervisor()
        response = self.submit_progress(project["id"], task.id, note="Bay 3 done.")
        self.assertEqual(response.status_code, 200, response.text)

    def test_admin_is_held_to_the_same_state_rule(self):
        project = self.activate_project()
        task = self.task_t001(project["id"])
        with self.Session.begin() as session:
            session.get(Task, task.id).lifecycle_status = "submitted"
        self.act_as_admin()
        response = self.submit_progress(project["id"], task.id, note="Admin late note.")
        self.assertEqual(response.status_code, 409, response.text)


if __name__ == "__main__":
    unittest.main()
