from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import ast
import inspect
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
from app.execution_models import BaselineTask, OutboxEvent, ProjectBaseline, Task, TaskDependency, ProjectExternalApproval, ProjectExternalApprovalTask
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
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import (
    ProjectVendor,
    TaskVendorAssignment,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorCapability,
    VendorAcknowledgement,
)
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


class VendorAcknowledgementApiTests(unittest.TestCase):
    """Phase 2 U3: vendor acknowledgement of a task assignment (R4).

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_vendor_assignment_v2.py.
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
            ProjectBaseline.__table__,
            BaselineTask.__table__,
            Task.__table__,
            ProjectTaskReferenceFile.__table__,
            ProjectExternalApproval.__table__,
            ProjectExternalApprovalTask.__table__,
            TaskDependency.__table__,
            V2Vendor.__table__,
            V2CapabilityCategory.__table__,
            V2VendorCapability.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
            VendorAcknowledgement.__table__,
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

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work/standard, category
        'Electrical'), one active electrical vendor."""
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
            session.add(V2TemplateTask(
                template_version_id=published.id, code="T001", sequence_no=1, title="Task T001",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", task_class="standard", task_kind="work",
                evidence_required=False, duration_days=1, phase="Electrical", category="Wiring",
            ))
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            session.add(electrical)
            session.flush()

            vendor_electrical = V2Vendor(
                id=uuid.uuid4(), name="Electrical Co", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            session.add(vendor_electrical)
            session.flush()
            session.add(V2VendorCapability(vendor_id=vendor_electrical.id, category_id=electrical.id))
            self.vendor_electrical_id = vendor_electrical.id

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

    def map_and_assign_vendor(self, project_id, task_id) -> str:
        self.act_as_pm()
        map_response = self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(self.vendor_electrical_id)},
        )
        self.assertEqual(map_response.status_code, 200, map_response.text)
        assign_response = self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment",
            json={"vendor_id": str(self.vendor_electrical_id)},
        )
        self.assertEqual(assign_response.status_code, 200, assign_response.text)
        return assign_response.json()["id"]

    def acknowledge(self, project_id, task_id, assignment_id, response, note=None):
        payload = {"response": response}
        if note is not None:
            payload["note"] = note
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/acknowledge",
            json=payload,
        )

    # ---- happy paths ------------------------------------------------------

    def test_pm_logs_accepted_moves_assignment_to_acknowledged(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        response = self.acknowledge(project["id"], task.id, assignment_id, "accepted")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["response"], "accepted")
        self.assertEqual(body["channel"], "portal")

        assign_check = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignment/{assignment_id}/acknowledge",
            json={"response": "accepted"},
        )
        # Already resolved now - a second attempt must 409.
        self.assertEqual(assign_check.status_code, 409, assign_check.text)

    def test_pm_logs_declined_moves_assignment_to_declined(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        response = self.acknowledge(project["id"], task.id, assignment_id, "declined")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["response"], "declined")

        second = self.acknowledge(project["id"], task.id, assignment_id, "accepted")
        self.assertEqual(second.status_code, 409, second.text)

    def test_pm_logs_clarification_requested_status_stays_pending_ack(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        response = self.acknowledge(
            project["id"], task.id, assignment_id, "clarification_requested", note="Need scope clarification.",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["response"], "clarification_requested")

        with self.Session() as session:
            assignment = session.get(TaskVendorAssignment, uuid.UUID(assignment_id))
            self.assertEqual(assignment.status, "pending_ack")
            ack_rows = session.scalars(
                select(VendorAcknowledgement).where(
                    VendorAcknowledgement.task_vendor_assignment_id == assignment.id
                )
            ).all()
            self.assertEqual(len(ack_rows), 1)

    # ---- edge case ----------------------------------------------------

    def test_clarification_then_accept_succeeds_and_both_rows_persist(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        first = self.acknowledge(project["id"], task.id, assignment_id, "clarification_requested")
        self.assertEqual(first.status_code, 200, first.text)

        second = self.acknowledge(project["id"], task.id, assignment_id, "accepted")
        self.assertEqual(second.status_code, 200, second.text)

        with self.Session() as session:
            assignment = session.get(TaskVendorAssignment, uuid.UUID(assignment_id))
            self.assertEqual(assignment.status, "acknowledged")
            ack_rows = session.scalars(
                select(VendorAcknowledgement)
                .where(VendorAcknowledgement.task_vendor_assignment_id == assignment.id)
                .order_by(VendorAcknowledgement.created_at)
            ).all()
            self.assertEqual(len(ack_rows), 2)
            self.assertEqual(ack_rows[0].response, "clarification_requested")
            self.assertEqual(ack_rows[1].response, "accepted")

    # ---- error paths ------------------------------------------------------

    def test_acknowledging_already_resolved_assignment_is_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_pm()
        first = self.acknowledge(project["id"], task.id, assignment_id, "accepted")
        self.assertEqual(first.status_code, 200, first.text)

        second = self.acknowledge(project["id"], task.id, assignment_id, "declined")
        self.assertEqual(second.status_code, 409, second.text)

    def test_non_pm_non_admin_actor_cannot_acknowledge(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        assignment_id = self.map_and_assign_vendor(project["id"], task.id)

        self.act_as_supervisor()
        response = self.acknowledge(project["id"], task.id, assignment_id, "accepted")

        self.assertEqual(response.status_code, 403, response.text)

    # ---- integration: non-interference with Phase 1 accountability -------

    def test_no_import_of_lifecycle_or_verification_services(self):
        import app.routes.project_vendors_v2 as project_vendors_route_module
        import app.services.vendor_acknowledgement as vendor_acknowledgement_service_module

        forbidden_module_fragments = ("task_lifecycle", "task_verification")
        for module in (project_vendors_route_module, vendor_acknowledgement_service_module):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            for imported in imported_modules:
                for forbidden in forbidden_module_fragments:
                    self.assertNotIn(
                        forbidden, imported,
                        f"{module.__name__} must not import {imported} (Phase 1 accountability path).",
                    )


if __name__ == "__main__":
    unittest.main()
