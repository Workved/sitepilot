from __future__ import annotations
from app.execution_models import FileObject, ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership, V2ProjectTask
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
INTERNAL_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")


class ProjectTemplateReviewApiTests(unittest.TestCase):
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
            FileObject.__table__,
            ProjectTaskReferenceFile.__table__,
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
            "other_pm": User(id=OTHER_PM_ID, name="Other PM", email="other-pm@example.com", role=UserRole.project_manager, active=True),
            "supervisor": User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True),
            "super_admin": User(id=SUPER_ADMIN_ID, name="Super Admin", email="super@example.com", role=UserRole.super_admin, active=True),
            "internal": User(id=INTERNAL_ID, name="Internal Employee", email="internal@example.com", role=UserRole.internal_employee, active=True),
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
                content_hash="review-api-template",
                is_current_published=True,
                created_by=ADMIN_ID,
                published_by=ADMIN_ID,
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            session.flush()

            source_tasks = []
            for sequence in range(1, 100):
                pre_activation = sequence <= 7
                start_day = None if pre_activation else min(sequence - 7, 45)
                source_tasks.append(V2TemplateTask(
                    template_version_id=version.id,
                    code=f"T{sequence:03d}",
                    sequence_no=sequence,
                    title=f"Task T{sequence:03d}",
                    description=f"Review description {sequence}",
                    schedule_classification="pre_activation" if pre_activation else "execution",
                    planned_start_day=start_day,
                    planned_end_day=start_day,
                    phase="Pre-Activation" if pre_activation else "Execution",
                    category="MEP" if sequence == 98 else ("Governance" if pre_activation else "Interior"),
                    applicability="conditional" if sequence == 98 else "mandatory",
                    evidence_required=False,
                    duration_days=None if pre_activation else 1,
                ))
            session.add_all(source_tasks)
            session.flush()

            project = V2Project(
                code="PRJ-REVIEW-001",
                name="Review API Project",
                client_name="Client",
                site_address="Mumbai",
                start_date=date(2026, 8, 1),
                template_version_id=version.id,
                status="draft",
                created_by=ADMIN_ID,
            )
            session.add(project)
            session.flush()
            session.add(V2ProjectMembership(
                project_id=project.id,
                employee_id=pm_profile.id,
                project_role="project_manager",
                assigned_by=ADMIN_ID,
                assignment_reason="Assigned for review",
            ))
            generated = []
            for source in source_tasks:
                excluded = source.code == "T098"
                generated.append(V2ProjectTask(
                    project_id=project.id,
                    template_version_id=version.id,
                    template_task_id=source.id,
                    original_code=source.code,
                    template_sequence=source.sequence_no,
                    title=source.title,
                    description=source.description,
                    schedule_classification=source.schedule_classification,
                    planned_start_day=source.planned_start_day,
                    planned_end_day=source.planned_end_day,
                    phase=source.phase,
                    category=source.category,
                    applicability=source.applicability,
                    evidence_required=source.evidence_required,
                    duration_days=source.duration_days,
                    source_type="template",
                    lifecycle_status="draft",
                    included=not excluded,
                    decision_state="excluded" if excluded else "pending_review",
                ))
            session.add_all(generated)
            session.flush()
            self.project_id = project.id
        return users

    def get_tasks(self, params=None):
        return self.client.get(
            f"/api/v2/projects/{self.project_id}/template-review/tasks",
            params=params or {},
        )

    def get_summary(self):
        return self.client.get(f"/api/v2/projects/{self.project_id}/template-review/summary")

    def test_admin_sees_all_tasks_in_deterministic_review_order(self):
        response = self.get_tasks({"page_size": 100})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["pagination"], {"page": 1, "page_size": 100, "total": 99, "total_pages": 1})
        self.assertEqual(len(body["items"]), 99)
        self.assertEqual(body["items"][0]["code"], "T001")
        self.assertEqual(body["items"][6]["code"], "T007")
        self.assertEqual(body["items"][7]["code"], "T008")
        self.assertEqual(body["items"][-1]["code"], "T099")
        self.assertEqual(body["items"][0]["source"], "template")
        self.assertEqual(body["items"][0]["decision_state"], "pending_review")

    def test_filters_search_and_pagination(self):
        cases = [
            ({"search": "  t008  "}, 1),
            ({"search": "review description 8"}, 11),
            ({"phase": " execution "}, 92),
            ({"category": " governance "}, 7),
            ({"category": "mep"}, 1),
            ({"applicability": "conditional"}, 1),
            ({"included": "false"}, 1),
            ({"included": "true"}, 98),
            ({"source": " TEMPLATE "}, 99),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                response = self.get_tasks({**params, "page_size": 100})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["pagination"]["total"], expected)
        page = self.get_tasks({"page": 2, "page_size": 20}).json()
        self.assertEqual(page["pagination"], {"page": 2, "page_size": 20, "total": 99, "total_pages": 5})
        self.assertEqual(len(page["items"]), 20)

    def test_summary_counts_are_database_derived(self):
        response = self.get_summary()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "project_id": str(self.project_id),
            "total": 99,
            "included": 98,
            "excluded": 1,
            "pending_review": 98,
            "decided": 1,
            "mandatory": 98,
            "conditional": 1,
        })

    def test_assigned_pm_allowed_and_unassigned_pm_denied(self):
        self.actor = self.users["pm"]
        self.assertEqual(self.get_tasks({"page_size": 100}).status_code, 200)
        self.assertEqual(self.get_summary().status_code, 200)
        self.actor = self.users["other_pm"]
        self.assertEqual(self.get_tasks().status_code, 403)
        self.assertEqual(self.get_summary().status_code, 403)

    def test_super_admin_can_review_generated_tasks(self):
        self.actor = self.users["super_admin"]
        self.assertEqual(self.get_tasks().status_code, 200)
        self.assertEqual(self.get_summary().status_code, 200)

    def test_other_roles_are_denied(self):
        for key in ("supervisor", "internal"):
            with self.subTest(role=key):
                self.actor = self.users[key]
                self.assertEqual(self.get_tasks().status_code, 403)
                self.assertEqual(self.get_summary().status_code, 403)

    def test_list_query_count_is_bounded_without_n_plus_one(self):
        self.actor = self.users["pm"]
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.get_tasks({"page_size": 100})
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(response.status_code, 200, response.text)
        # 4 for the page itself, plus one batched lookup of reference files
        # added on the project (one query for the whole page, not per task).
        self.assertLessEqual(len(statements), 5, statements)


if __name__ == "__main__":
    unittest.main()
