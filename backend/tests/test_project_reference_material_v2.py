"""Template Builder Phase 2, project side: a project's tasks and approvals
show the reference material and "what proof is needed?" instructions of the
template version the project is pinned to, downloadable only by people who
can open that project. Runs the real create -> generate -> activate flow."""

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
    ProjectExternalApprovalEvidence,
    ProjectExternalApprovalSubmission,
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
    V2ProjectExternalGateApplicabilityDecision,
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
    V2TemplateGateReferenceFile,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateTaskReferenceFile,
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

USERS = {
    "admin": (ADMIN_ID, UserRole.admin),
    "pm": (PM_ID, UserRole.project_manager),
    "supervisor": (SUPERVISOR_ID, UserRole.supervisor),
    "outsider": (OUTSIDER_ID, UserRole.supervisor),
    "internal": (INTERNAL_ID, UserRole.internal_employee),
}


class ProjectReferenceMaterialTests(unittest.TestCase):
    def setUp(self):
        pin_project_creation_today(self)
        self.store: dict[str, bytes] = {}
        self.patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, _type: self.store.__setitem__(key, data)),
            patch("app.services.evidence_storage.read", side_effect=self.store.get),
        ]
        for item in self.patches:
            item.start()
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Template.__table__, V2TemplateVersion.__table__,
            V2TemplateTask.__table__, V2TemplateTaskDependency.__table__, V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__, FileObject.__table__, V2TemplateTaskReferenceFile.__table__,
            V2TemplateGateReferenceFile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2ProjectTask.__table__, V2ProjectTaskDependency.__table__, V2ProjectExternalGate.__table__,
            V2ProjectExternalGateTask.__table__, V2ProjectExternalGateApplicabilityDecision.__table__,
            V2AuditEvent.__table__, ProjectBaseline.__table__, BaselineTask.__table__, Task.__table__, ProjectTaskReferenceFile.__table__,
            ProjectExternalApproval.__table__, ProjectExternalApprovalTask.__table__,
            ProjectExternalApprovalSubmission.__table__, ProjectExternalApprovalEvidence.__table__,
            TaskDependency.__table__, TaskSupportAssignment.__table__, TaskProgressUpdate.__table__,
            TaskEvidence.__table__, OutboxEvent.__table__, TaskVerification.__table__, TaskApprovalDecision.__table__,
            TaskBlocker.__table__, TaskDelayEvent.__table__,
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
        self.act_as("admin")
        self.app.dependency_overrides[current_user] = lambda: self.actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        for item in self.patches:
            item.stop()

    def act_as(self, who: str) -> None:
        user_id, role = USERS[who]
        self.actor = User(id=user_id, name=who, email=f"{who}@example.com", role=role, active=True)

    # ---- seeding -------------------------------------------------------------

    def _reference(self, session, owner, key: str, data: bytes, description: str):
        file_object = FileObject(storage_key=f"template-references/{key}", original_filename=key, mime_type="application/pdf",
                                 size_bytes=len(data), checksum=key, uploaded_by=ADMIN_ID)
        session.add(file_object)
        session.flush()
        self.store[file_object.storage_key] = data
        if isinstance(owner, V2TemplateTask):
            link = V2TemplateTaskReferenceFile(template_task_id=owner.id, file_id=file_object.id, description=description, created_by=ADMIN_ID)
        else:
            link = V2TemplateGateReferenceFile(gate_id=owner.id, file_id=file_object.id, description=description, created_by=ADMIN_ID)
        session.add(link)
        session.flush()
        return link

    def _version(self, session, template, version_no, *, task_text, gate_text, current):
        version = V2TemplateVersion(template_id=template.id, version_no=version_no, status="published", duration_days=45,
                                    content_hash=f"hash-{version_no}", is_current_published=current, created_by=ADMIN_ID,
                                    published_by=ADMIN_ID, published_at=datetime.now(timezone.utc))
        session.add(version)
        session.flush()
        task = V2TemplateTask(template_version_id=version.id, code="T001", sequence_no=1, title="Flooring",
                              schedule_classification="execution", planned_start_day=1, planned_end_day=2,
                              applicability="mandatory", task_class="standard", task_kind="work",
                              evidence_required=True, evidence_instructions=task_text, duration_days=2)
        gate = V2TemplateExternalGate(template_version_id=version.id, code="E001", approval_name="Fire NOC",
                                      evidence_instructions=gate_text, mapping_classification="exact",
                                      requires_configuration=False, sequence_no=1, required_by_type="before_linked_tasks")
        session.add_all([task, gate])
        session.flush()
        session.add(V2TemplateExternalGateTask(gate_id=gate.id, template_task_id=task.id))
        return version, task, gate

    def _seed(self):
        with self.Session.begin() as session:
            session.add_all([User(id=uid, name=who, email=f"{who}@example.com", role=role, active=True) for who, (uid, role) in USERS.items()])
            session.flush()
            for who in ("pm", "supervisor", "outsider", "internal"):
                session.add(EmployeeProfile(user_id=USERS[who][0], employee_code=who.upper(), designation=who, availability="available"))
            template = V2Template(code="FIT-45", name="Fitout")
            session.add(template)
            session.flush()
            v1, task1, gate1 = self._version(session, template, 1, task_text="Photos of the levelled floor",
                                             gate_text="Stamped NOC copy", current=True)
            self.task_ref = self._reference(session, task1, "flooring-spec.pdf", b"%PDF-v1-spec", "Approved flooring spec")
            self.gate_ref = self._reference(session, gate1, "noc-form.pdf", b"%PDF-v1-noc", "NOC application form")
            self.v1_id, self.template_id = v1.id, template.id
            self.task_ref_id, self.gate_ref_id = self.task_ref.id, self.gate_ref.id

    # ---- flow helpers -----------------------------------------------------------

    def activated_project(self) -> dict:
        response = self.client.post("/api/v2/projects", json={
            "project_name": "Futurex Fitout", "client": "Example Client", "location": "Mumbai",
            "proposed_start_date": "2026-08-01", "target_handover_date": "2026-09-14",
            "pm_user_id": str(PM_ID), "supervisor_user_id": str(SUPERVISOR_ID), "template_version_id": str(self.v1_id),
        })
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        for step in ("generate-tasks", "generate-dependencies", "generate-gates"):
            result = self.client.post(f"/api/v2/projects/{project['id']}/{step}")
            self.assertEqual(result.status_code, 200, result.text)
        with self.Session() as session:
            gate_id = session.scalar(select(V2ProjectExternalGate.id).where(V2ProjectExternalGate.project_id == uuid.UUID(project["id"])))
        decided = self.client.post(f"/api/v2/projects/{project['id']}/gates/{gate_id}/applicability-decisions", json={"decision": "applicable"})
        self.assertEqual(decided.status_code, 200, decided.text)
        activated = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(activated.status_code, 200, activated.text)
        return project

    def task_and_approval(self, project_id: str) -> tuple[uuid.UUID, uuid.UUID]:
        with self.Session() as session:
            task_id = session.scalar(select(Task.id).where(Task.project_id == uuid.UUID(project_id)))
            approval_id = session.scalar(select(ProjectExternalApproval.id).where(ProjectExternalApproval.project_id == uuid.UUID(project_id)))
        return task_id, approval_id

    # ---- what a project shows ------------------------------------------------------

    def test_new_project_shows_its_versions_instructions_and_reference_files(self):
        project = self.activated_project()
        task_id, approval_id = self.task_and_approval(project["id"])

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task_id}").json()
        self.assertEqual(detail["evidence_instructions"], "Photos of the levelled floor")
        self.assertEqual([(r["filename"], r["description"]) for r in detail["reference_files"]],
                         [("flooring-spec.pdf", "Approved flooring spec")])

        approvals = self.client.get(f"/api/v2/projects/{project['id']}/external-approvals").json()
        approval = next(a for a in approvals if a["id"] == str(approval_id))
        self.assertEqual(approval["evidence_instructions"], "Stamped NOC copy")
        self.assertEqual([r["filename"] for r in approval["reference_files"]], ["noc-form.pdf"])

    def test_a_newer_template_version_does_not_change_an_existing_project(self):
        project = self.activated_project()
        task_id, approval_id = self.task_and_approval(project["id"])
        with self.Session.begin() as session:
            template = session.get(V2Template, self.template_id)
            session.execute(V2TemplateVersion.__table__.update().values(is_current_published=False))
            _v2, task2, gate2 = self._version(session, template, 2, task_text="NEW task text", gate_text="NEW gate text", current=True)
            self._reference(session, task2, "new-spec.pdf", b"%PDF-v2", "New spec")
            self._reference(session, gate2, "new-form.pdf", b"%PDF-v2-noc", "New form")

        detail = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task_id}").json()
        self.assertEqual(detail["evidence_instructions"], "Photos of the levelled floor")
        self.assertEqual([r["filename"] for r in detail["reference_files"]], ["flooring-spec.pdf"])
        approval = next(a for a in self.client.get(f"/api/v2/projects/{project['id']}/external-approvals").json()
                        if a["id"] == str(approval_id))
        self.assertEqual(approval["evidence_instructions"], "Stamped NOC copy")
        self.assertEqual([r["filename"] for r in approval["reference_files"]], ["noc-form.pdf"])

    # ---- who can download -------------------------------------------------------------

    def test_project_members_and_admins_can_download_reference_files(self):
        project = self.activated_project()
        task_id, approval_id = self.task_and_approval(project["id"])
        task_url = f"/api/v2/projects/{project['id']}/tasks/{task_id}/reference-files/{self.task_ref_id}"
        approval_url = f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/reference-files/{self.gate_ref_id}"
        for who in ("admin", "pm", "supervisor"):
            with self.subTest(who=who):
                self.act_as(who)
                task_file = self.client.get(task_url)
                self.assertEqual(task_file.status_code, 200, task_file.text)
                self.assertEqual(task_file.content, b"%PDF-v1-spec")
                self.assertIn("attachment", task_file.headers["content-disposition"])
                self.assertEqual(task_file.headers["x-content-type-options"], "nosniff")
                self.assertEqual(self.client.get(approval_url).content, b"%PDF-v1-noc")

    def test_people_outside_the_project_cannot_download(self):
        project = self.activated_project()
        task_id, approval_id = self.task_and_approval(project["id"])
        self.act_as("outsider")
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task_id}/reference-files/{self.task_ref_id}").status_code, 403)
        self.assertEqual(self.client.get(
            f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/reference-files/{self.gate_ref_id}").status_code, 403)
        self.act_as("internal")  # an Internal Employee who is not on this project
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task_id}/reference-files/{self.task_ref_id}").status_code, 403)

    def test_internal_employees_only_reach_material_for_work_they_are_assigned(self):
        project = self.activated_project()
        task_id, approval_id = self.task_and_approval(project["id"])
        with self.Session() as session:
            internal_employee = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == INTERNAL_ID))
        self.act_as("pm")
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/memberships", json={
            "employee_id": str(internal_employee), "project_role": "internal_employee", "reason": "Support."}).status_code, 200)
        task_url = f"/api/v2/projects/{project['id']}/tasks/{task_id}/reference-files/{self.task_ref_id}"
        approval_url = f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/reference-files/{self.gate_ref_id}"

        # On the project, but not assigned to this task or approval.
        self.act_as("internal")
        self.assertEqual(self.client.get(task_url).status_code, 403)
        self.assertEqual(self.client.get(approval_url).status_code, 403)

        self.act_as("admin")
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/tasks/{task_id}/support-assignments",
                                          json={"employee_id": str(internal_employee), "responsibility": "Execution."}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/assign",
                                          json={"assignee_user_id": str(INTERNAL_ID)}).status_code, 200)
        self.act_as("internal")
        self.assertEqual(self.client.get(task_url).status_code, 200)
        self.assertEqual(self.client.get(approval_url).status_code, 200)

    def test_a_reference_must_belong_to_that_task_or_approval(self):
        project = self.activated_project()
        task_id, approval_id = self.task_and_approval(project["id"])
        # The approval's file through the task route, and the task's file through the approval route.
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task_id}/reference-files/{self.gate_ref_id}").status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/reference-files/{self.task_ref_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task_id}/reference-files/{uuid.uuid4()}").status_code, 404)

    # ---- no proof enforcement on approvals -------------------------------------------------

    def test_approval_submission_still_accepts_a_note_without_files(self):
        project = self.activated_project()
        _task_id, approval_id = self.task_and_approval(project["id"])
        with self.Session() as session:
            internal_employee = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == INTERNAL_ID))
        self.act_as("pm")
        added = self.client.post(f"/api/v2/projects/{project['id']}/memberships", json={
            "employee_id": str(internal_employee), "project_role": "internal_employee", "reason": "Liaison."})
        self.assertEqual(added.status_code, 200, added.text)
        self.act_as("admin")
        assigned = self.client.post(f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/assign",
                                    json={"assignee_user_id": str(INTERNAL_ID)})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.act_as("internal")
        submitted = self.client.post(f"/api/v2/projects/{project['id']}/external-approvals/{approval_id}/submission",
                                     data={"note": "Applied at the fire office."})
        self.assertEqual(submitted.status_code, 200, submitted.text)


if __name__ == "__main__":
    unittest.main()
