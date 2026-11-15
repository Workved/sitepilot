from __future__ import annotations

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
from app.execution_models import BaselineTask, FileObject, OutboxEvent, ProjectBaseline, Task, TaskDependency, ProjectExternalApproval, ProjectExternalApprovalTask
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
from app.routes.project_vendors_v2 import vendors_router
from app.routes.projects_v2 import router as projects_router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
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


class TaskVendorAssignmentApiTests(unittest.TestCase):
    """Phase 2 U2: task vendor delegation (R3), against real execution tasks
    produced by U1's baseline-lock activation flow.

    Follows the same SQLite-ATTACHed-schema harness pattern as
    test_task_support_assignment_v2.py / test_task_blockers_delays_v2.py.
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

    # ---- seeding -------------------------------------------------------

    def _seed(self):
        """Seeds a 1-task template: T001 (work/standard, phase 'Electrical',
        category 'Wiring and conduits' - capability matching is against
        PHASE, not the finer-grained category, so the category is
        deliberately something no vendor capability is ever named), plus
        four vendors covering the happy/mismatch/unmapped/inactive
        scenarios."""
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
                evidence_required=False, duration_days=1, phase="Electrical", category="Wiring and conduits",
            ))
            session.flush()
            self.published_version_id = published.id

            electrical = V2CapabilityCategory(name="Electrical")
            plumbing = V2CapabilityCategory(name="Plumbing")
            wiring_and_conduits = V2CapabilityCategory(name="Wiring and conduits")
            session.add_all([electrical, plumbing, wiring_and_conduits])
            session.flush()

            vendor_electrical = V2Vendor(
                id=uuid.uuid4(), name="Electrical Co", contact_person="Ravi", phone="9000000001",
                status="active", engagement_type="main",
            )
            vendor_plumbing = V2Vendor(
                id=uuid.uuid4(), name="Plumbing Co", contact_person="Meena", phone="9000000002",
                status="active", engagement_type="main",
            )
            vendor_unmapped = V2Vendor(
                id=uuid.uuid4(), name="Unmapped Electrical Co", contact_person="Kiran", phone="9000000003",
                status="active", engagement_type="main",
            )
            vendor_soon_inactive = V2Vendor(
                id=uuid.uuid4(), name="Soon Inactive Co", contact_person="Sunil", phone="9000000004",
                status="active", engagement_type="main",
            )
            # Holds a capability matching the task's CATEGORY string
            # ("Wiring and conduits"), not its phase ("Electrical") - proves
            # matching is phase-based, not category-based (regression guard
            # for the bug where no vendor could ever match any task because
            # category matching required a capability named after the
            # finer-grained category, which no vendor taxonomy defines).
            vendor_category_only_match = V2Vendor(
                id=uuid.uuid4(), name="Category-Only Match Co", contact_person="Asha", phone="9000000005",
                status="active", engagement_type="main",
            )
            session.add_all([
                vendor_electrical, vendor_plumbing, vendor_unmapped, vendor_soon_inactive, vendor_category_only_match,
            ])
            session.flush()

            session.add_all([
                V2VendorCapability(vendor_id=vendor_electrical.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=vendor_plumbing.id, category_id=plumbing.id),
                V2VendorCapability(vendor_id=vendor_unmapped.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=vendor_soon_inactive.id, category_id=electrical.id),
                V2VendorCapability(vendor_id=vendor_category_only_match.id, category_id=wiring_and_conduits.id),
            ])

            self.vendor_electrical_id = vendor_electrical.id
            self.vendor_plumbing_id = vendor_plumbing.id
            self.vendor_unmapped_id = vendor_unmapped.id
            self.vendor_soon_inactive_id = vendor_soon_inactive.id
            self.vendor_category_only_match_id = vendor_category_only_match.id

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

    def map_vendor(self, project_id, vendor_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/vendors", json={"vendor_id": str(vendor_id)},
        )

    def assign_vendor(self, project_id, task_id, vendor_id):
        self.act_as_pm()
        return self.client.post(
            f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment",
            json={"vendor_id": str(vendor_id)},
        )

    # ---- happy path -----------------------------------------------------

    def test_pm_assigns_mapped_matching_capability_vendor_to_task(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        map_response = self.map_vendor(project["id"], self.vendor_electrical_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_electrical_id)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["task_id"], str(task.id))
        self.assertEqual(body["vendor_id"], str(self.vendor_electrical_id))
        self.assertEqual(body["status"], "pending_ack")

    # ---- edge cases -----------------------------------------------------

    def test_capability_mismatch_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        map_response = self.map_vendor(project["id"], self.vendor_plumbing_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_plumbing_id)

        self.assertEqual(response.status_code, 422, response.text)

    def test_matching_the_task_category_but_not_its_phase_is_still_rejected(self):
        # Regression guard: matching must key off Task.phase ("Electrical"),
        # never Task.category ("Wiring and conduits") - a vendor whose only
        # capability equals the category string is not a valid match.
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(task.phase, "Electrical")
        self.assertEqual(task.category, "Wiring and conduits")

        map_response = self.map_vendor(project["id"], self.vendor_category_only_match_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_category_only_match_id)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Electrical", response.text)

    def test_unmapped_vendor_rejected(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        # Deliberately never mapped via map_vendor().
        response = self.assign_vendor(project["id"], task.id, self.vendor_unmapped_id)

        self.assertIn(response.status_code, (404, 422), response.text)

    # ---- error paths ------------------------------------------------------

    def test_inactive_vendor_rejected_even_if_previously_mapped(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        map_response = self.map_vendor(project["id"], self.vendor_soon_inactive_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        with self.Session.begin() as session:
            vendor = session.get(V2Vendor, self.vendor_soon_inactive_id)
            vendor.status = "blacklisted"
            vendor.blacklist_reason = "Quality issues"

        response = self.assign_vendor(project["id"], task.id, self.vendor_soon_inactive_id)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("blacklisted", response.json()["detail"])

    # ---- integration: non-interference with Phase 1 accountability -------

    def test_assignment_does_not_touch_lifecycle_status_or_accountability_code(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        status_before = task.lifecycle_status

        map_response = self.map_vendor(project["id"], self.vendor_electrical_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)

        response = self.assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        self.assertEqual(response.status_code, 200, response.text)

        task_after = self.task_by_code(project["id"], "T001")
        self.assertEqual(task_after.lifecycle_status, status_before)

        # Structural proof (per the plan): this unit's new service/route
        # files must not *import* Phase 1's accountability-resolution
        # services at all - parsed via `ast` (not a plain substring check)
        # so that mentioning "task_lifecycle" in prose/docstrings (as this
        # module's own header comment does, to explain the constraint)
        # doesn't produce a false positive.
        import app.routes.project_vendors_v2 as project_vendors_route_module
        import app.services.project_vendor as project_vendor_service_module
        import app.services.task_vendor_assignment as task_vendor_assignment_service_module

        forbidden_module_fragments = ("task_lifecycle", "task_verification")
        for module in (
            project_vendors_route_module,
            project_vendor_service_module,
            task_vendor_assignment_service_module,
        ):
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


    # ---- read endpoint: list_task_vendor_assignments ---------------------

    def test_list_task_vendor_assignments_reflects_assignment_and_acknowledgement(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.map_vendor(project["id"], self.vendor_electrical_id).status_code, 200)
        assign_response = self.assign_vendor(project["id"], task.id, self.vendor_electrical_id)
        self.assertEqual(assign_response.status_code, 200, assign_response.text)
        assignment_id = assign_response.json()["id"]

        self.act_as_pm()
        ack_response = self.client.post(
            f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignment/{assignment_id}/acknowledge",
            json={"response": "accepted"},
        )
        self.assertEqual(ack_response.status_code, 200, ack_response.text)

        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignments")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["vendor_name"], "Electrical Co")
        self.assertEqual(body[0]["status"], "acknowledged")
        self.assertEqual(len(body[0]["acknowledgements"]), 1)
        self.assertEqual(body[0]["acknowledgements"][0]["response"], "accepted")

    def test_list_task_vendor_assignments_empty_before_any_assignment(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        self.act_as_pm()
        response = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignments")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    # ---- capability-category vocabulary and vendor capability editing ----

    def test_capability_categories_are_auto_seeded_from_published_template_phases(self):
        # T001's published-template phase is "Electrical" - the vocabulary
        # a vendor's capabilities can be set from must include it, or an
        # Admin has no way to make a vendor eligible for this task at all.
        self.act_as_pm()
        response = self.client.get("/api/v2/vendors/capability-categories")

        self.assertEqual(response.status_code, 200, response.text)
        names = [item["name"] for item in response.json()]
        self.assertIn("Electrical", names)
        # Pre-existing categories from the vendor-capability fixtures
        # (Plumbing, Wiring and conduits) are untouched, not replaced.
        self.assertIn("Plumbing", names)

    def test_capability_categories_endpoint_is_idempotent(self):
        self.act_as_pm()
        first = self.client.get("/api/v2/vendors/capability-categories")
        second = self.client.get("/api/v2/vendors/capability-categories")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(sorted(item["name"] for item in first.json()), sorted(item["name"] for item in second.json()))

    def test_pm_sets_vendor_capabilities_and_it_unlocks_delegation(self):
        project = self.activate_project()
        task = self.task_by_code(project["id"], "T001")

        self.act_as_pm()
        electrical_category_id = next(
            item["id"] for item in self.client.get("/api/v2/vendors/capability-categories").json()
            if item["name"] == "Electrical"
        )

        set_response = self.client.post(
            f"/api/v2/vendors/{self.vendor_plumbing_id}/capabilities",
            json={"category_ids": [electrical_category_id]},
        )
        self.assertEqual(set_response.status_code, 200, set_response.text)
        self.assertEqual(set_response.json()["capability_categories"], ["Electrical"])

        map_response = self.map_vendor(project["id"], self.vendor_plumbing_id)
        self.assertEqual(map_response.status_code, 200, map_response.text)
        assign_response = self.assign_vendor(project["id"], task.id, self.vendor_plumbing_id)
        self.assertEqual(assign_response.status_code, 200, assign_response.text)

    def test_setting_vendor_capabilities_replaces_the_existing_set(self):
        self.act_as_pm()
        categories = self.client.get("/api/v2/vendors/capability-categories").json()
        electrical_id = next(item["id"] for item in categories if item["name"] == "Electrical")
        plumbing_id = next(item["id"] for item in categories if item["name"] == "Plumbing")

        first = self.client.post(
            f"/api/v2/vendors/{self.vendor_electrical_id}/capabilities", json={"category_ids": [plumbing_id]},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["capability_categories"], ["Plumbing"])

        second = self.client.post(
            f"/api/v2/vendors/{self.vendor_electrical_id}/capabilities", json={"category_ids": [electrical_id]},
        )
        self.assertEqual(second.status_code, 200, second.text)
        # Only the new set - "Plumbing" from the first call is gone, not
        # accumulated alongside it.
        self.assertEqual(second.json()["capability_categories"], ["Electrical"])

    def test_internal_employee_cannot_set_vendor_capabilities(self):
        self.act_as(User(
            id=uuid.uuid4(), name="Internal", email="internal@example.com",
            role=UserRole.internal_employee, active=True,
        ))
        response = self.client.post(f"/api/v2/vendors/{self.vendor_electrical_id}/capabilities", json={"category_ids": []})

        self.assertEqual(response.status_code, 403, response.text)

    def test_setting_an_invalid_capability_category_is_rejected(self):
        self.act_as_pm()
        response = self.client.post(
            f"/api/v2/vendors/{self.vendor_electrical_id}/capabilities",
            json={"category_ids": [str(uuid.uuid4())]},
        )

        self.assertEqual(response.status_code, 422, response.text)

    def test_setting_capabilities_on_an_unknown_vendor_is_rejected(self):
        self.act_as_pm()
        response = self.client.post(f"/api/v2/vendors/{uuid.uuid4()}/capabilities", json={"category_ids": []})

        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
