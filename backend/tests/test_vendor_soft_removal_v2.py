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
    BaselineTask,
    FileObject,
    OutboxEvent,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
    TaskDependency,
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
from app.routes.project_vendors_v2 import router as project_vendors_router
from app.routes.project_vendors_v2 import vendors_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import (
    V2Template,
    V2TemplateExternalGate,
    V2TemplateExternalGateTask,
    V2TemplateTask,
    V2TemplateTaskDependency,
    V2TemplateVersion,
)
from app.vendor_models import V2VendorContact, VendorContactProject
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
OUTSIDER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class VendorSoftRemovalApiTests(unittest.TestCase):
    """Vendor unassignment/removal (soft removal) - ends_at on ProjectVendor
    and TaskVendorAssignment, mirroring the project_memberships/
    task_support_assignments pattern. Follows the same SQLite-ATTACHed-
    schema harness as test_task_vendor_assignment_v2.py."""

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
            V2VendorContact.__table__,
            VendorContactProject.__table__,
            TaskVendorAssignment.__table__,
            VendorAcknowledgement.__table__,
            FileObject.__table__,
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
        self.app.include_router(vendors_router)

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

    def act_as_outsider(self) -> None:
        self.act_as(User(
            id=OUTSIDER_ID, name="Outsider", email="outsider@example.com",
            role=UserRole.supervisor, active=True,
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
            session.add_all([admin, pm, supervisor, outsider])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=OUTSIDER_ID, employee_code="OUT-001", designation="Supervisor", availability="available",
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
                    evidence_required=False, duration_days=1, phase="Electrical", category="Wiring",
                ),
                V2TemplateTask(
                    template_version_id=published.id, code="T002", sequence_no=2, title="Task T002",
                    schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                    applicability="mandatory", task_class="standard", task_kind="work",
                    evidence_required=False, duration_days=1, phase="Electrical", category="Wiring",
                ),
            ])
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            session.add(electrical)
            session.flush()

            main_vendor = V2Vendor(
                id=uuid.uuid4(), name="Acme Electricals", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            other_vendor = V2Vendor(
                id=uuid.uuid4(), name="Other Electricals", contact_person="Sunil", phone="9000000004",
                status="active", engagement_type="main",
            )
            session.add_all([main_vendor, other_vendor])
            session.flush()
            sub_vendor = V2Vendor(
                id=uuid.uuid4(), name="Acme Sub Electricals", contact_person="Kiran", phone="9000000003",
                status="active", engagement_type="sub_vendor", parent_vendor_id=main_vendor.id,
            )
            session.add(sub_vendor)
            session.flush()
            session.add_all([
                V2VendorCapability(vendor_id=main_vendor.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=other_vendor.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=sub_vendor.id, category_id=electrical.id),
            ])

            self.main_vendor_id = main_vendor.id
            self.other_vendor_id = other_vendor.id
            self.sub_vendor_id = sub_vendor.id

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

    def activate_project(self, **overrides) -> dict:
        project = self.create_draft(**overrides)
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

    def map_vendor(self, project_id, vendor_id):
        self.act_as_pm()
        return self.client.post(f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)})

    def assign_vendor(self, project_id, task_id, vendor_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment", json={"vendor_id": str(vendor_id)},
        )

    def unassign_task(self, project_id, task_id, assignment_id, reason="No longer needed on this task."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment/{assignment_id}/unassign",
            json={"reason": reason},
        )

    def remove_project_vendor(self, project_id, vendor_id, reason="Unable to meet revised timeline."):
        return self.client.post(
            f"/api/v2/projects/{project_id}/vendors/{vendor_id}/remove", json={"reason": reason},
        )

    # ---- task-level unassignment -----------------------------------------

    def test_unassign_from_task_preserves_project_mapping(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]

        self.act_as_pm()
        response = self.unassign_task(project["id"], task.id, assignment_id)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json()["ends_at"])
        with self.Session() as session:
            mapping = session.scalar(select(ProjectVendor).where(ProjectVendor.vendor_id == self.main_vendor_id))
            self.assertIsNone(mapping.ends_at)  # project mapping untouched

    def test_unassign_requires_reason(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]

        self.act_as_pm()
        response = self.unassign_task(project["id"], task.id, assignment_id, reason="")

        self.assertEqual(response.status_code, 422, response.text)

    def test_outsider_cannot_unassign(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]

        self.act_as_outsider()
        response = self.unassign_task(project["id"], task.id, assignment_id)

        self.assertEqual(response.status_code, 403, response.text)

    def test_admin_can_unassign(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]

        self.act_as_admin()
        response = self.unassign_task(project["id"], task.id, assignment_id)

        self.assertEqual(response.status_code, 200, response.text)

    def test_ended_task_assignment_cannot_be_acknowledged(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]
        self.act_as_pm()
        self.assertEqual(self.unassign_task(project["id"], task.id, assignment_id).status_code, 200)

        response = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignment/{assignment_id}/acknowledge",
            json={"response": "accepted"},
        )

        self.assertEqual(response.status_code, 409, response.text)

    def test_reassignment_of_another_vendor_still_works_after_unassignment(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.assertEqual(self.map_vendor(project["id"], self.other_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]
        self.act_as_pm()
        self.assertEqual(self.unassign_task(project["id"], task.id, assignment_id).status_code, 200)

        response = self.assign_vendor(project["id"], task.id, self.other_vendor_id)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["vendor_id"], str(self.other_vendor_id))

    def test_task_vendor_unassigned_emits_notification_on_active_project(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]

        self.act_as_pm()
        self.assertEqual(self.unassign_task(project["id"], task.id, assignment_id).status_code, 200)

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "task.vendor_unassigned")
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].payload["vendor_id"], str(self.main_vendor_id))

    # ---- project-level removal --------------------------------------------

    def test_project_removal_ends_all_active_task_assignments(self):
        project = self.activate_project()
        task1 = self.task_by_code(project["id"], "T001")
        task2 = self.task_by_code(project["id"], "T002")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment1_id = self.assign_vendor(project["id"], task1.id, self.main_vendor_id).json()["id"]
        assignment2_id = self.assign_vendor(project["id"], task2.id, self.main_vendor_id).json()["id"]

        self.act_as_pm()
        response = self.remove_project_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json()["ends_at"])
        with self.Session() as session:
            a1 = session.get(TaskVendorAssignment, uuid.UUID(assignment1_id))
            a2 = session.get(TaskVendorAssignment, uuid.UUID(assignment2_id))
            self.assertIsNotNone(a1.ends_at)
            self.assertIsNotNone(a2.ends_at)

    def test_project_removal_writes_per_task_audit_plus_project_audit(self):
        project = self.activate_project()
        task1 = self.task_by_code(project["id"], "T001")
        task2 = self.task_by_code(project["id"], "T002")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.assign_vendor(project["id"], task1.id, self.main_vendor_id)
        self.assign_vendor(project["id"], task2.id, self.main_vendor_id)

        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        with self.Session() as session:
            task_audits = session.scalars(
                select(V2AuditEvent).where(V2AuditEvent.action == "VENDOR_TASK_UNASSIGNED")
            ).all()
            project_audits = session.scalars(
                select(V2AuditEvent).where(V2AuditEvent.action == "VENDOR_REMOVED_FROM_PROJECT")
            ).all()
            self.assertEqual(len(task_audits), 2)
            self.assertEqual(len(project_audits), 1)
            for audit in task_audits:
                self.assertIn("Ended due to project-level vendor removal", audit.reason)

    def test_acknowledgement_history_survives_removal(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        assignment_id = self.assign_vendor(project["id"], task.id, self.main_vendor_id).json()["id"]
        self.act_as_pm()
        self.assertEqual(
            self.client.post(
                f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignment/{assignment_id}/acknowledge",
                json={"response": "accepted"},
            ).status_code, 200,
        )

        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        with self.Session() as session:
            acks = session.scalars(
                select(VendorAcknowledgement).where(VendorAcknowledgement.task_vendor_assignment_id == uuid.UUID(assignment_id))
            ).all()
            self.assertEqual(len(acks), 1)
            self.assertEqual(acks[0].response, "accepted")

    def test_removal_requires_reason(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)

        self.act_as_pm()
        response = self.remove_project_vendor(project["id"], self.main_vendor_id, reason="")

        self.assertEqual(response.status_code, 422, response.text)

    def test_outsider_cannot_remove_vendor(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)

        self.act_as_outsider()
        response = self.remove_project_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 403, response.text)

    def test_admin_can_remove_vendor(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)

        self.act_as_admin()
        response = self.remove_project_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 200, response.text)

    def test_removal_on_active_project_emits_notification(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)

        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "project.vendor_removed")
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].payload["vendor_id"], str(self.main_vendor_id))

    def test_removal_on_draft_project_emits_no_notification(self):
        project = self.create_draft()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)

        self.act_as_pm()
        response = self.remove_project_vendor(project["id"], self.main_vendor_id)
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            events = session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "project.vendor_removed")
            ).all()
            self.assertEqual(events, [])

    # ---- ended mapping cannot be treated as active ------------------------

    def test_ended_mapping_blocks_new_task_assignment(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        response = self.assign_vendor(project["id"], task.id, self.main_vendor_id)

        self.assertEqual(response.status_code, 422, response.text)

    def test_vendor_can_be_remapped_after_removal(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        response = self.map_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            active = session.scalars(
                select(ProjectVendor).where(
                    ProjectVendor.vendor_id == self.main_vendor_id, ProjectVendor.ends_at.is_(None),
                )
            ).all()
            self.assertEqual(len(active), 1)

    def test_list_project_vendors_excludes_ended_by_default(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        response = self.client.get(f"/api/v2/projects/{project['id']}/vendors")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_list_project_vendors_includes_ended_when_requested(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.main_vendor_id).status_code, 200)

        response = self.client.get(f"/api/v2/projects/{project['id']}/vendors?include_ended=true")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertIsNotNone(body[0]["ends_at"])

    # ---- sub-vendor invariant ----------------------------------------------

    def test_removing_main_vendor_blocked_while_active_sub_vendor_mapped(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.assertEqual(self.map_vendor(project["id"], self.sub_vendor_id).status_code, 200)

        self.act_as_pm()
        response = self.remove_project_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            mapping = session.scalar(select(ProjectVendor).where(ProjectVendor.vendor_id == self.main_vendor_id))
            self.assertIsNone(mapping.ends_at)

    def test_removing_main_vendor_succeeds_once_sub_vendor_already_removed(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.main_vendor_id).status_code, 200)
        self.assertEqual(self.map_vendor(project["id"], self.sub_vendor_id).status_code, 200)
        self.act_as_pm()
        self.assertEqual(self.remove_project_vendor(project["id"], self.sub_vendor_id).status_code, 200)

        response = self.remove_project_vendor(project["id"], self.main_vendor_id)

        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
