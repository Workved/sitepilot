from __future__ import annotations
from app.execution_models import ProjectTaskReferenceFile  # noqa: E402

import unittest
import uuid
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
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
from app.routes.projects_v2 import router
from app.template_models import V2Template, V2TemplateExternalGate, V2TemplateExternalGateTask, V2TemplateTask, V2TemplateTaskDependency, V2TemplateVersion
from app.vendor_models import ProjectVendor, V2Vendor
from tests.project_dates import pin_project_creation_today


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")
SUPER_ADMIN_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee5")
PM2_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff6")


class ProjectActivationDeletionApiTests(unittest.TestCase):
    """Phase 8 activation-foundation and controlled-deletion coverage.

    Mirrors the setup pattern established in test_project_create_v2.py so
    this file stays consistent with the rest of the V2 project test suite.
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
            V2TemplateExternalGate.__table__,
            V2TemplateExternalGateTask.__table__,
            V2ProjectExternalGateTask.__table__,
            OutboxEvent.__table__,
            V2Vendor.__table__,
            ProjectVendor.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        self.app = FastAPI()
        self.app.include_router(router)

        def override_db():
            with self.Session() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides[current_user] = lambda: User(
            id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed(self):
        with self.Session.begin() as session:
            admin = User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True)
            pm = User(id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True)
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com",
                role=UserRole.supervisor, active=True,
            )
            employee = User(
                id=EMPLOYEE_ID, name="Employee", email="employee@example.com", role=UserRole.internal_employee, active=True,
            )
            super_admin = User(
                id=SUPER_ADMIN_ID, name="Super Admin", email="super@example.com", role=UserRole.super_admin, active=True,
            )
            pm2 = User(id=PM2_ID, name="PM Two", email="pm2@example.com", role=UserRole.project_manager, active=True)
            session.add_all([admin, pm, supervisor, employee, super_admin, pm2])
            session.flush()
            session.add_all([
                EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available"),
                EmployeeProfile(user_id=PM2_ID, employee_code="PM-002", designation="PM", availability="available"),
                EmployeeProfile(
                    user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
                ),
                EmployeeProfile(
                    user_id=EMPLOYEE_ID, employee_code="EMP-001", designation="Internal Employee", availability="available",
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
                template_version_id=published.id, code="T001", sequence_no=1, title="Existing template task",
                schedule_classification="execution", planned_start_day=1, planned_end_day=1,
                applicability="mandatory", evidence_required=False, duration_days=1,
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
        project = response.json()
        # U1 activation now requires at least one included task snapshot to
        # lock a baseline, so generate the template-derived task(s) for every
        # draft project this fixture produces.
        generate_response = self.client.post(f"/api/v2/projects/{project['id']}/generate-tasks")
        self.assertEqual(generate_response.status_code, 200, generate_response.text)
        return project

    # ---- Activation ----------------------------------------------------

    def test_activate_succeeds_when_eligible_and_writes_single_audit_entry(self):
        project = self.create_draft()
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Setup complete, ready to start."})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertIsNotNone(body["activated_at"])

        with self.Session() as session:
            events = session.scalars(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_ACTIVATED")).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].actor_user_id, ADMIN_ID)
            self.assertTrue(events[0].after_json["template_version_locked"])

    def test_activate_rejects_project_missing_target_handover_date(self):
        # Creation now derives the handover date from the template duration,
        # so this state can no longer be requested - it is cleared directly to
        # keep the activation guard covered for rows that predate that change.
        project = self.create_draft()
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(project["id"])).target_handover_date = None
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Attempt activation."})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("target handover date", response.json()["detail"])
        with self.Session() as session:
            self.assertEqual(session.get(V2Project, uuid.UUID(project["id"])).status, "draft")

    def test_activate_rejects_when_accountable_role_missing(self):
        project = self.create_draft()
        # End the Supervisor membership so activation eligibility fails.
        supervisor_membership = next(m for m in project["memberships"] if m["project_role"] == "site_supervisor")
        end_response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships/{supervisor_membership['id']}/end",
            json={"reason": "Testing missing accountable role."},
        )
        self.assertEqual(end_response.status_code, 200, end_response.text)
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Attempt activation."})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Site Supervisor", response.json()["detail"])

    def test_activate_prevents_duplicate_activation(self):
        project = self.create_draft()
        first = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "First activation."})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Second attempt."})
        self.assertEqual(second.status_code, 409, second.text)
        self.assertIn("already active", second.json()["detail"])
        with self.Session() as session:
            count = session.scalar(select(func.count()).select_from(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_ACTIVATED"))
            self.assertEqual(count, 1)

    # ---- U2: project.activated outbox emission --------------------------

    def test_activate_emits_project_activated_outbox_event(self):
        """3 members (PM, Supervisor, an internal employee) + 1 mapped
        vendor - the U1 resolver's audience for `project.activated`. This
        unit only proves the event itself and its payload; U1's own tests
        cover resolving that payload to actual recipients."""
        project = self.create_draft()
        with self.Session.begin() as session:
            third_employee = session.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == EMPLOYEE_ID))
            vendor = V2Vendor(
                id=uuid.uuid4(), name="Fitout Vendor Co", contact_person="Vendor Contact",
                phone="9000000099", status="active", engagement_type="main",
            )
            session.add(vendor)
            session.flush()
            session.add(ProjectVendor(project_id=uuid.UUID(project["id"]), vendor_id=vendor.id, mapped_by=ADMIN_ID))
            third_employee_id = third_employee.id

        member_response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(third_employee_id), "project_role": "internal_employee", "reason": "Add third member."},
        )
        self.assertEqual(member_response.status_code, 200, member_response.text)

        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Setup complete, ready to start."})
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as session:
            events = session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "project.activated")).all()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.aggregate_type, "project")
            self.assertEqual(event.aggregate_id, uuid.UUID(project["id"]))
            self.assertEqual(event.payload["project_id"], project["id"])
            self.assertEqual(event.status, "pending")

    def test_activate_that_fails_validation_emits_no_event(self):
        project = self.create_draft()
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(project["id"])).target_handover_date = None
        response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Attempt activation."})
        self.assertEqual(response.status_code, 409, response.text)
        with self.Session() as session:
            count = session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "project.activated"))
            self.assertEqual(count, 0)

    def test_re_entering_active_from_on_hold_does_not_re_emit_project_activated(self):
        """Only the draft-to-active `activate_project` route (this unit's
        change) fires `project.activated`. `POST /{project_id}/status` has
        its own independent draft-to-active path (see its U1 comment) and an
        on_hold-to-active path, and this unit does not touch that route at
        all - so re-entering "active" from "on_hold" through it must not
        produce a second event."""
        project = self.create_draft()
        activate_response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(activate_response.status_code, 200, activate_response.text)

        hold_response = self.client.post(
            f"/api/v2/projects/{project['id']}/status", json={"status": "on_hold", "reason": "Pausing for a bit."},
        )
        self.assertEqual(hold_response.status_code, 200, hold_response.text)

        resume_response = self.client.post(
            f"/api/v2/projects/{project['id']}/status", json={"status": "active", "reason": "Resuming."},
        )
        self.assertEqual(resume_response.status_code, 200, resume_response.text)
        self.assertEqual(resume_response.json()["status"], "active")

        with self.Session() as session:
            count = session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "project.activated"))
            self.assertEqual(count, 1)

    def act_as_super_admin(self):
        self.app.dependency_overrides[current_user] = lambda: User(
            id=SUPER_ADMIN_ID, name="Super Admin", email="super@example.com", role=UserRole.super_admin, active=True,
        )

    def test_only_org_admin_can_activate(self):
        project = self.create_draft()
        for role in (UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=ADMIN_ID, name=role.value, email=f"{role.value}@example.com", role=role, active=True,
            )
            response = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Attempt."})
            self.assertIn(response.status_code, (403,), (role, response.text))

    def test_super_admin_can_activate_hold_and_resume(self):
        project = self.create_draft()
        self.act_as_super_admin()
        activate = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(activate.status_code, 200, activate.text)
        self.assertEqual(activate.json()["status"], "active")
        hold = self.client.post(f"/api/v2/projects/{project['id']}/status", json={"status": "on_hold", "reason": "Client pause."})
        self.assertEqual(hold.status_code, 200, hold.text)
        resume = self.client.post(f"/api/v2/projects/{project['id']}/status", json={"status": "active", "reason": "Resuming."})
        self.assertEqual(resume.status_code, 200, resume.text)
        self.assertEqual(resume.json()["status"], "active")
        with self.Session() as session:
            self.assertEqual(session.get(V2Project, uuid.UUID(project["id"])).activated_by, SUPER_ADMIN_ID)

    def test_super_admin_can_assign_and_end_pm_on_draft(self):
        project = self.create_draft()
        with self.Session() as session:
            pm2_profile_id = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == PM2_ID))
        self.act_as_super_admin()
        assign = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(pm2_profile_id), "project_role": "project_manager", "reason": "PM swap before start."},
        )
        self.assertEqual(assign.status_code, 200, assign.text)
        end = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships/{assign.json()['id']}/end", json={"reason": "Undo swap."},
        )
        self.assertEqual(end.status_code, 200, end.text)

    def test_pm_still_cannot_assign_a_pm(self):
        project = self.create_draft()
        with self.Session() as session:
            pm2_profile_id = session.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == PM2_ID))
        self.app.dependency_overrides[current_user] = lambda: User(
            id=PM_ID, name="PM", email="pm@example.com", role=UserRole.project_manager, active=True,
        )
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/memberships",
            json={"employee_id": str(pm2_profile_id), "project_role": "project_manager", "reason": "Self swap."},
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_activation_rolls_back_on_audit_failure_leaving_project_in_draft(self):
        project = self.create_draft()

        def fail_audit(_mapper, _connection, _target):
            raise RuntimeError("audit write failed")

        event.listen(V2AuditEvent, "before_insert", fail_audit)
        try:
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Attempt."})
        finally:
            event.remove(V2AuditEvent, "before_insert", fail_audit)

        with self.Session() as session:
            refreshed = session.get(V2Project, uuid.UUID(project["id"]))
            self.assertEqual(refreshed.status, "draft")
            self.assertIsNone(refreshed.activated_at)

    def test_template_version_reference_is_locked_after_activation(self):
        project = self.create_draft()
        activate = self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        self.assertEqual(activate.status_code, 200, activate.text)
        response = self.client.patch(
            f"/api/v2/projects/{project['id']}",
            json={"template_version_id": str(self.published_version_id), "reason": "Attempt to re-attach template."},
        )
        self.assertEqual(response.status_code, 409, response.text)

    # ---- Deletion --------------------------------------------------------

    def test_delete_draft_hard_deletes_and_removes_restricted_memberships(self):
        project = self.create_draft()
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Draft no longer needed."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["deleted"])
        self.assertEqual(body["deletion_type"], "hard")

        with self.Session() as session:
            self.assertIsNone(session.get(V2Project, uuid.UUID(project["id"])))
            remaining_memberships = session.scalar(
                select(func.count()).select_from(V2ProjectMembership).where(V2ProjectMembership.project_id == uuid.UUID(project["id"]))
            )
            self.assertEqual(remaining_memberships, 0)
            audit = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_DRAFT_DELETED"))
            # Audit integrity: the event row survives the project delete.
            # (V2AuditEvent.project_id is declared ON DELETE SET NULL in the
            # real Postgres schema; this SQLite test harness does not enable
            # FK-action enforcement - matching test_project_create_v2.py's
            # existing setup - so nulling isn't observable here. That part of
            # the guarantee is a database-level constraint, not application
            # code, and is unaffected by this change.)
            self.assertIsNotNone(audit)

    def test_delete_active_project_with_no_execution_activity_archives_instead_of_removing(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Cancelled before work started."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["deletion_type"], "soft")
        self.assertEqual(body["status"], "archived")

        with self.Session() as session:
            refreshed = session.get(V2Project, uuid.UUID(project["id"]))
            self.assertIsNotNone(refreshed, "Active project must be soft-deleted, not removed.")
            self.assertEqual(refreshed.status, "archived")
            audit = session.scalar(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_ARCHIVED"))
            self.assertIsNotNone(audit)

    def test_delete_blocked_when_execution_audit_event_exists(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        with self.Session.begin() as session:
            session.add(V2AuditEvent(
                actor_user_id=PM_ID, action="TASK_VERIFIED", entity_type="task",
                entity_id=uuid.uuid4(), project_id=uuid.UUID(project["id"]), reason="Simulated future execution activity.",
            ))
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Attempt deletion."},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("execution activity", response.json()["detail"])
        with self.Session() as session:
            self.assertEqual(session.get(V2Project, uuid.UUID(project["id"])).status, "active")

    def test_delete_blocked_for_completed_project(self):
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        status_response = self.client.post(
            f"/api/v2/projects/{project['id']}/status", json={"status": "completed", "reason": "Marked complete for test."},
        )
        self.assertEqual(status_response.status_code, 200, status_response.text)
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Attempt deletion."},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Completed", response.json()["detail"])

    def test_completed_transition_stamps_completed_at(self):
        """Feeds app.services.evidence_retention's clock - must be the
        actual completion moment, never target_handover_date, or a delayed
        project could have live evidence swept while still active."""
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Go live."})
        with self.Session() as session:
            self.assertIsNone(session.get(V2Project, uuid.UUID(project["id"])).completed_at)

        status_response = self.client.post(
            f"/api/v2/projects/{project['id']}/status", json={"status": "completed", "reason": "Marked complete for test."},
        )

        self.assertEqual(status_response.status_code, 200, status_response.text)
        completed_at = status_response.json()["completed_at"]
        self.assertIsNotNone(completed_at)
        datetime.fromisoformat(completed_at)  # parseable, whatever the harness's tz-naive sqlite round-trip yields
        with self.Session() as session:
            self.assertIsNotNone(session.get(V2Project, uuid.UUID(project["id"])).completed_at)

    def test_delete_blocked_for_already_archived_project(self):
        project = self.create_draft()
        archive_response = self.client.post(
            f"/api/v2/projects/{project['id']}/status", json={"status": "archived", "reason": "Archiving draft directly."},
        )
        self.assertEqual(archive_response.status_code, 200, archive_response.text)
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Attempt deletion."},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("already been archived", response.json()["detail"])

    def test_delete_requires_matching_confirmation_code(self):
        project = self.create_draft()
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": "WRONG-CODE", "reason": "Attempt deletion."},
        )
        self.assertEqual(response.status_code, 422, response.text)
        with self.Session() as session:
            self.assertIsNotNone(session.get(V2Project, uuid.UUID(project["id"])))

    def test_delete_does_not_touch_template_tables(self):
        project = self.create_draft()
        with self.Session() as session:
            template_count_before = session.scalar(select(func.count()).select_from(V2Template))
            version_count_before = session.scalar(select(func.count()).select_from(V2TemplateVersion))
            task_count_before = session.scalar(select(func.count()).select_from(V2TemplateTask))

        self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Draft no longer needed."},
        )

        with self.Session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(V2Template)), template_count_before)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateVersion)), version_count_before)
            self.assertEqual(session.scalar(select(func.count()).select_from(V2TemplateTask)), task_count_before)

    def test_super_admin_can_delete_draft(self):
        project = self.create_draft()
        self.act_as_super_admin()
        response = self.client.request(
            "DELETE", f"/api/v2/projects/{project['id']}",
            json={"confirmation": project["code"], "reason": "Draft created by mistake."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["deleted"])

    def test_only_org_admin_can_delete(self):
        project = self.create_draft()
        for role in (UserRole.project_manager, UserRole.supervisor, UserRole.internal_employee):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=ADMIN_ID, name=role.value, email=f"{role.value}@example.com", role=role, active=True,
            )
            response = self.client.request(
                "DELETE", f"/api/v2/projects/{project['id']}",
                json={"confirmation": project["code"], "reason": "Attempt."},
            )
            self.assertEqual(response.status_code, 403, (role, response.text))


    # ---- Restore from archive ------------------------------------------

    def archive(self, project):
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/status",
            json={"status": "archived", "reason": "Archived by mistake."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_archived_draft_restores_to_draft(self):
        project = self.create_draft()
        self.archive(project)
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/restore", json={"reason": "Archived in error."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")

    def test_archived_active_project_restores_to_on_hold_not_active(self):
        """Undoing an archive must not silently resume execution."""
        project = self.create_draft()
        self.client.post(f"/api/v2/projects/{project['id']}/activate", json={"reason": "Setup complete, ready to start."})
        self.archive(project)
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/restore", json={"reason": "Archived in error."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "on_hold")

    def test_restore_writes_an_audit_entry_recording_the_target(self):
        project = self.create_draft()
        self.archive(project)
        self.client.post(f"/api/v2/projects/{project['id']}/restore", json={"reason": "Archived in error."})
        with self.Session() as session:
            events = session.scalars(select(V2AuditEvent).where(V2AuditEvent.action == "PROJECT_RESTORED")).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].before_json["status"], "archived")
            self.assertEqual(events[0].after_json["restored_to"], "draft")
            self.assertEqual(events[0].reason, "Archived in error.")

    def test_restore_rejects_a_project_that_is_not_archived(self):
        project = self.create_draft()
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/restore", json={"reason": "Not archived."},
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_super_admin_can_restore(self):
        project = self.create_draft()
        self.archive(project)
        self.act_as_super_admin()
        response = self.client.post(f"/api/v2/projects/{project['id']}/restore", json={"reason": "Archived in error."})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")

    def test_only_org_admin_can_restore(self):
        project = self.create_draft()
        self.archive(project)
        for role in (UserRole.project_manager, UserRole.supervisor):
            self.app.dependency_overrides[current_user] = lambda role=role: User(
                id=ADMIN_ID, name=role.value, email=f"{role.value}@example.com", role=role, active=True,
            )
            response = self.client.post(
                f"/api/v2/projects/{project['id']}/restore", json={"reason": "Attempt restore."},
            )
            self.assertEqual(response.status_code, 403, (role, response.text))

    def test_a_restored_draft_can_be_archived_again(self):
        project = self.create_draft()
        self.archive(project)
        self.client.post(f"/api/v2/projects/{project['id']}/restore", json={"reason": "Archived in error."})
        self.assertEqual(self.archive(project)["status"], "archived")

    # ---- Derived target handover date ----------------------------------
    # Computed from the attached template's duration rather than entered.
    # Day 1 is the start date itself, so the fixture's 45-day template
    # starting 2026-08-01 hands over on 2026-09-14.

    def test_create_derives_the_handover_date_from_the_template_duration(self):
        project = self.create_draft()
        self.assertEqual(project["target_handover_date"], "2026-09-14")

    def test_create_ignores_a_client_supplied_handover_date(self):
        project = self.create_draft(target_handover_date="2027-01-01")
        self.assertEqual(project["target_handover_date"], "2026-09-14")

    def test_create_shifts_the_handover_date_with_the_start_date(self):
        project = self.create_draft(proposed_start_date="2026-09-01")
        # 2026-09-01 + 44 days.
        self.assertEqual(project["target_handover_date"], "2026-10-15")

    def test_update_refuses_to_set_the_handover_date_directly(self):
        project = self.create_draft()
        response = self.client.patch(
            f"/api/v2/projects/{project['id']}",
            json={"target_handover_date": "2027-01-01", "reason": "Push the date out."},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("derived from the template duration", response.json()["detail"])

    def test_update_refuses_to_clear_the_handover_date(self):
        project = self.create_draft()
        response = self.client.patch(
            f"/api/v2/projects/{project['id']}",
            json={"clear_target_handover_date": True, "reason": "Remove the date."},
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_update_heals_a_draft_that_has_no_handover_date(self):
        project = self.create_draft()
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(project["id"])).target_handover_date = None

        response = self.client.patch(
            f"/api/v2/projects/{project['id']}",
            json={"client_name": "Renamed Client", "reason": "Routine details edit."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["target_handover_date"], "2026-09-14")

    def test_a_healed_draft_can_then_be_activated(self):
        project = self.create_draft()
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(project["id"])).target_handover_date = None
        self.client.patch(
            f"/api/v2/projects/{project['id']}",
            json={"client_name": "Renamed Client", "reason": "Routine details edit."},
        )
        response = self.client.post(
            f"/api/v2/projects/{project['id']}/activate", json={"reason": "Setup complete, ready to start."},
        )
        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
