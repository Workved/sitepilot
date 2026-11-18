from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateTask, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
OTHER_PM_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
SUPERVISOR_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")


class ProjectManualTaskApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2TemplateTask.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectTask.__table__,
            V2AuditEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.users = self._seed()
        self.actor = self.users["admin"]
        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: self.actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        users = {
            "admin": User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True),
            "pm": User(id=PM_ID, name="Assigned PM", email="pm@example.com", role=UserRole.project_manager, active=True),
            "other_pm": User(id=OTHER_PM_ID, name="Other PM", email="other@example.com", role=UserRole.project_manager, active=True),
            "supervisor": User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True),
            "super_admin": User(id=SUPER_ADMIN_ID, name="Super Admin", email="super@example.com", role=UserRole.super_admin, active=True),
        }
        with self.Session.begin() as session:
            session.add_all(users.values())
            pm_profile = EmployeeProfile(
                user_id=PM_ID,
                employee_code="PM-001",
                designation="Project Manager",
                availability="available",
            )
            other_pm_profile = EmployeeProfile(
                user_id=OTHER_PM_ID,
                employee_code="PM-002",
                designation="Project Manager",
                availability="available",
            )
            session.add_all([pm_profile, other_pm_profile])
            session.flush()

            template = V2Template(code="WORKVED-45", name="Workved 45 Day")
            session.add(template)
            session.flush()
            version = V2TemplateVersion(
                template_id=template.id,
                version_no=1,
                status="published",
                duration_days=45,
                content_hash="manual-task-test",
                is_current_published=True,
                created_by=ADMIN_ID,
                published_by=ADMIN_ID,
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()
            template_task = V2TemplateTask(
                template_version_id=version.id,
                code="T001",
                sequence_no=1,
                title="Pre-Activation source",
                description="Approved template description",
                schedule_classification="pre_activation",
                phase="Pre-Activation",
                category="Project Setup",
                applicability="mandatory",
                evidence_required=False,
            )
            session.add(template_task)
            session.flush()

            project = V2Project(
                code="PRJ-MANUAL-001",
                name="Manual Task Project",
                client_name="Client",
                site_address="Mumbai",
                start_date=date(2026, 8, 1),
                template_version_id=version.id,
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            session.add(
                V2ProjectMembership(
                    project_id=project.id,
                    employee_id=pm_profile.id,
                    project_role="project_manager",
                    assigned_by=ADMIN_ID,
                    assignment_reason="Assigned for task review",
                )
            )
            project_task = V2ProjectTask(
                project_id=project.id,
                template_version_id=version.id,
                template_task_id=template_task.id,
                original_code="T001",
                template_sequence=1,
                title=template_task.title,
                description=template_task.description,
                schedule_classification="pre_activation",
                phase=template_task.phase,
                category=template_task.category,
                applicability="mandatory",
                source_type="template",
                lifecycle_status="draft",
                included=True,
                decision_state="pending_review",
            )
            session.add(project_task)
            session.flush()
            self.project_id = project.id
            self.template_id = template.id
            self.version_id = version.id
            self.template_task_id = template_task.id
        return users

    @staticmethod
    def payload(**overrides):
        value = {
            "title": "Client-specific mock-up review",
            "phase": "Execution",
            "category": "Client Coordination",
            "planned_start_day": 5,
            "planned_end_day": 6,
            "reason": "Required for this project's client review.",
        }
        value.update(overrides)
        return value

    def create_task(self, **overrides):
        return self.client.post(
            f"/api/v2/projects/{self.project_id}/tasks",
            json=self.payload(**overrides),
        )

    def test_admin_creates_manual_task_with_audit_and_template_unchanged(self):
        with self.Session() as session:
            template_before = session.get(V2TemplateTask, self.template_task_id)
            snapshot = (template_before.title, template_before.description, template_before.category)
            template_count = session.scalar(select(func.count()).select_from(V2TemplateTask))

        response = self.create_task()
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["code"], "MANUAL-001")
        self.assertEqual(body["sequence"], 2)
        self.assertEqual(body["source_type"], "project_manual")
        self.assertEqual(body["duration_days"], 2)
        self.assertTrue(body["included"])
        self.assertEqual(body["decision_state"], "included")

        with self.Session() as session:
            task = session.get(V2ProjectTask, uuid.UUID(body["task_id"]))
            self.assertIsNone(task.template_task_id)
            self.assertIsNone(task.description)
            self.assertEqual(task.schedule_classification, "execution")
            audit = session.get(V2AuditEvent, uuid.UUID(body["audit_event_id"]))
            self.assertEqual(audit.action, "PROJECT_MANUAL_TASK_CREATED")
            self.assertEqual(audit.actor_user_id, ADMIN_ID)
            self.assertEqual(audit.reason, self.payload()["reason"])
            self.assertEqual(audit.after_json["source_type"], "project_manual")
            template_after = session.get(V2TemplateTask, self.template_task_id)
            self.assertEqual(
                (template_after.title, template_after.description, template_after.category),
                snapshot,
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(V2TemplateTask)),
                template_count,
            )

    def test_generated_codes_are_unique_and_duplicate_conflicts_without_partial_write(self):
        first = self.create_task()
        self.assertEqual(first.status_code, 201, first.text)
        second = self.create_task(title="Second manual task")
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["code"], "MANUAL-002")
        self.assertEqual(second.json()["sequence"], 3)

        with patch(
            "app.services.project_manual_task.ProjectManualTaskService._next_code_and_sequence",
            return_value=("MANUAL-001", 4),
        ):
            duplicate = self.create_task(title="Collision")
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        with self.Session() as session:
            manual_count = session.scalar(
                select(func.count()).select_from(V2ProjectTask).where(
                    V2ProjectTask.project_id == self.project_id,
                    V2ProjectTask.source_type == "project_manual",
                )
            )
            collision_audits = session.scalar(
                select(func.count()).select_from(V2AuditEvent).where(
                    V2AuditEvent.project_id == self.project_id,
                    V2AuditEvent.reason == self.payload(title="Collision")["reason"],
                    V2AuditEvent.entity_type == "project_task",
                )
            )
            self.assertEqual(manual_count, 2)
            self.assertEqual(collision_audits, 2)


    def test_audit_failure_rolls_back_manual_task(self):
        def fail_audit(_mapper, _connection, _target):
            raise RuntimeError("audit write failed")

        event.listen(V2AuditEvent, "before_insert", fail_audit)
        try:
            with self.assertRaises(RuntimeError):
                self.create_task()
        finally:
            event.remove(V2AuditEvent, "before_insert", fail_audit)
        with self.Session() as session:
            manual_tasks = list(session.scalars(select(V2ProjectTask).where(
                V2ProjectTask.project_id == self.project_id,
                V2ProjectTask.source_type == "project_manual",
            )).all())
            audits = list(session.scalars(select(V2AuditEvent).where(
                V2AuditEvent.project_id == self.project_id,
            )).all())
            self.assertEqual(manual_tasks, [])
            self.assertEqual(audits, [])

    def test_invalid_days_and_extra_description_are_rejected_with_zero_writes(self):
        reversed_days = self.create_task(planned_start_day=8, planned_end_day=7)
        self.assertEqual(reversed_days.status_code, 422, reversed_days.text)
        beyond_duration = self.create_task(planned_start_day=45, planned_end_day=46)
        self.assertEqual(beyond_duration.status_code, 422, beyond_duration.text)
        extra = self.create_task(description="Generated descriptions are not editable here.")
        self.assertEqual(extra.status_code, 422, extra.text)
        with self.Session() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(V2ProjectTask).where(
                        V2ProjectTask.project_id == self.project_id,
                        V2ProjectTask.source_type == "project_manual",
                    )
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(V2AuditEvent).where(
                        V2AuditEvent.project_id == self.project_id,
                    )
                ),
                0,
            )

    def test_admin_or_the_projects_own_pm_can_add_tasks_and_active_project_is_locked(self):
        """Admin, or the project's own PM / Supervisor, can add a task while
        it is Draft. Only Admin can also add it to the template."""
        self.actor = self.users["pm"]
        self.assertEqual(self.create_task(title="PM task").status_code, 201)
        to_template = self.create_task(title="PM template task", add_to_template=True)
        self.assertEqual(to_template.status_code, 403, to_template.text)
        self.assertIn("Only Admin can add a task to the template", to_template.json()["detail"])

        # Not on this project: no.
        self.actor = self.users["other_pm"]
        self.assertEqual(self.create_task(title="Other PM task").status_code, 403)
        self.actor = self.users["supervisor"]
        self.assertEqual(self.create_task(title="Supervisor task").status_code, 403)
        self.actor = self.users["super_admin"]
        self.assertEqual(self.create_task(title="Super Admin task").status_code, 201)

        self.actor = self.users["admin"]
        with self.Session.begin() as session:
            session.get(V2Project, self.project_id).status = "active"
        locked = self.create_task(title="Late manual task")
        self.assertEqual(locked.status_code, 409, locked.text)

    def test_review_order_and_source_filter_include_manual_task(self):
        created = self.create_task()
        self.assertEqual(created.status_code, 201, created.text)
        review = self.client.get(
            f"/api/v2/projects/{self.project_id}/template-review/tasks?page=1&page_size=20"
        )
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual([item["code"] for item in review.json()["items"]], ["T001", "MANUAL-001"])

        manual_only = self.client.get(
            f"/api/v2/projects/{self.project_id}/template-review/tasks"
            "?source=project_manual&page=1&page_size=20"
        )
        self.assertEqual(manual_only.status_code, 200, manual_only.text)
        self.assertEqual(manual_only.json()["pagination"]["total"], 1)
        self.assertEqual(manual_only.json()["items"][0]["source"], "project_manual")


    def test_model_enforces_manual_provenance_constraints(self):
        table = V2ProjectTask.__table__
        self.assertTrue(table.c.template_task_id.nullable)
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn("'project_manual'", checks["ck_v2_project_tasks_source_type"])
        self.assertIn("template_task_id is null", checks["ck_v2_project_tasks_source_reference"])

if __name__ == "__main__":
    unittest.main()
