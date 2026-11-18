"""Adding a task to a project after it started: to this project only, or
(Admin) to this project and its template. Reuses the task-vendor harness
(template WORKVED-45 v1, 45 days, task T001; project starts 2026-08-01 with
PM and Supervisor members)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.execution_models import BaselineTask, OutboxEvent, ProjectBaseline, Task, TaskDependency
from app.models import User, UserRole
from app.project_models import V2AuditEvent, V2Project
from app.routes.execution_tasks_v2 import router as execution_router
from app.services.message_dispatch import MessageDispatchService
import app.main  # noqa: F401 - registers every model on Base.metadata
from app.database import Base
from app.template_models import V2TemplateTask, V2TemplateVersion

# Imported as a module so pytest doesn't collect the parent's tests here.
from tests import test_task_vendor_assignment_v2 as base

SUPERVISOR = User(id=base.SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True)
OUTSIDER_PM = User(id=uuid.UUID("aaaaaaaa-0000-4000-8000-0000000000ef"), name="Other PM", email="other@example.com", role=UserRole.project_manager, active=True)


class ProjectTaskAdditionTests(base.TaskVendorAssignmentApiTests):
    def setUp(self):
        super().setUp()
        # The execution endpoints read blockers, readiness and more: create
        # every remaining table.
        Base.metadata.create_all(self.engine, checkfirst=True)
        self.app.include_router(execution_router)
        self.project = self.activate_project()

    def add(self, **overrides):
        payload = {
            "title": "Extra false-ceiling patch", "description": "Client asked for it in the lobby",
            "phase": "Electrical", "category": "Wiring and conduits",
            "planned_start_date": "2026-08-05", "planned_end_date": "2026-08-07",
            "evidence_required": True, "reason": "Client request on site visit",
        }
        payload.update(overrides)
        return self.client.post(f"/api/v2/projects/{self.project['id']}/running-tasks", json=payload)

    def added_task(self, task_id) -> Task:
        with self.Session() as session:
            return session.get(Task, uuid.UUID(task_id))

    def current_versions(self):
        with self.Session() as session:
            return session.scalars(select(V2TemplateVersion).order_by(V2TemplateVersion.version_no)).all()

    # ---- this project only --------------------------------------------------

    def test_supervisor_adds_a_task_to_their_running_project(self):
        self.act_as(SUPERVISOR)
        response = self.add()
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["code"], "MANUAL-001")
        self.assertIsNone(body["template"])

        task = self.added_task(body["task_id"])
        self.assertFalse(task.created_from_baseline)
        self.assertIsNone(task.baseline_task_id)
        self.assertEqual((task.planned_start_day, task.planned_end_day, task.duration_days), (5, 7, 3))
        self.assertEqual(str(task.planned_start_date), "2026-08-05")
        self.assertEqual(task.lifecycle_status, "planned")
        self.assertTrue(task.evidence_required)
        self.assertEqual((task.added_by, task.added_reason), (base.SUPERVISOR_ID, "Client request on site visit"))

        with self.Session() as session:
            # The locked plan is untouched.
            self.assertEqual(session.scalar(select(ProjectBaseline.task_count)), 1)
            self.assertEqual(len(session.scalars(select(BaselineTask)).all()), 1)
            self.assertEqual(session.scalar(select(V2AuditEvent.action).where(V2AuditEvent.entity_id == task.id)), "TASK_ADDED_AFTER_START")
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "task.added"))
            self.assertEqual(event.aggregate_id, task.id)
            # The template is untouched.
            self.assertEqual(len(session.scalars(select(V2TemplateVersion)).all()), 1)

        listed = {row["original_code"]: row for row in self.client.get(f"/api/v2/projects/{self.project['id']}/tasks").json()}
        self.assertTrue(listed["MANUAL-001"]["added_after_start"])
        self.assertFalse(listed["T001"]["added_after_start"])
        detail = self.client.get(f"/api/v2/projects/{self.project['id']}/tasks/{task.id}").json()
        self.assertEqual((detail["added_by_name"], detail["added_reason"]), ("Supervisor", "Client request on site visit"))

    def test_pm_admin_can_add_but_not_outsiders_or_wrong_states(self):
        self.act_as_pm()
        self.assertEqual(self.add().status_code, 201)
        self.act_as_admin()
        second = self.add(title="Second")
        self.assertEqual(second.json()["code"], "MANUAL-002")
        self.act_as(OUTSIDER_PM)
        self.assertEqual(self.add().status_code, 403)

        self.act_as_admin()
        early = self.add(planned_start_date="2026-07-30")
        self.assertEqual(early.status_code, 422)
        self.assertEqual(self.add(planned_start_date="2026-08-09", planned_end_date="2026-08-08").status_code, 422)

        draft = self.create_draft(project_name="Not started")
        response = self.client.post(f"/api/v2/projects/{draft['id']}/running-tasks", json={
            "title": "x", "phase": "Electrical", "category": "Wiring", "planned_start_date": "2026-08-05",
            "planned_end_date": "2026-08-05", "reason": "Needed",
        })
        self.assertEqual(response.status_code, 409)
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(self.project["id"])).status = "completed"
        self.assertEqual(self.add().status_code, 409)

    def test_starts_after_another_task(self):
        t001 = self.task_by_code(self.project["id"], "T001")
        self.act_as_pm()
        response = self.add(after_task_id=str(t001.id))
        self.assertEqual(response.status_code, 201, response.text)
        with self.Session() as session:
            dependency = session.scalar(select(TaskDependency).where(TaskDependency.successor_task_id == uuid.UUID(response.json()["task_id"])))
            self.assertEqual((dependency.predecessor_task_id, dependency.dependency_type, dependency.created_from_baseline), (t001.id, "finish_to_start", False))
        detail = self.client.get(f"/api/v2/projects/{self.project['id']}/tasks/{response.json()['task_id']}").json()
        self.assertEqual([p["original_code"] for p in detail["predecessors"]], ["T001"])
        self.assertEqual(self.add(after_task_id=str(uuid.uuid4())).status_code, 422)

    def test_notification_goes_to_pm_and_supervisor_but_not_whoever_added_it(self):
        self.act_as(SUPERVISOR)
        task_id = self.add().json()["task_id"]
        with self.Session() as session:
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "task.added"))
            recipients = MessageDispatchService(session)._resolve_recipients(event)
            pm_employee = session.scalar(select(base.EmployeeProfile.id).where(base.EmployeeProfile.user_id == base.PM_ID))
            self.assertEqual({r.employee_id for r in recipients}, {pm_employee})
        self.assertTrue(task_id)

    # ---- and the template ------------------------------------------------------

    def test_admin_adds_to_project_and_publishes_a_new_template_version(self):
        self.act_as_admin()
        response = self.add(add_to_template=True)
        self.assertEqual(response.status_code, 201, response.text)
        template = response.json()["template"]
        self.assertTrue(template["added"], template)
        self.assertEqual((template["version_no"], template["task_code"]), (2, "T002"))

        v1, v2 = self.current_versions()
        self.assertFalse(v1.is_current_published)
        self.assertTrue(v2.is_current_published)
        self.assertEqual(v2.status, "published")
        with self.Session() as session:
            new_task = session.scalar(select(V2TemplateTask).where(V2TemplateTask.template_version_id == v2.id, V2TemplateTask.code == "T002"))
            self.assertEqual((new_task.title, new_task.planned_start_day, new_task.planned_end_day, new_task.phase), ("Extra false-ceiling patch", 5, 7, "Electrical"))
            self.assertTrue(new_task.evidence_required)
            self.assertEqual(len(session.scalars(select(V2TemplateTask).where(V2TemplateTask.template_version_id == v2.id)).all()), 2)
            # This project stays on the version it started from.
            self.assertEqual(session.get(V2Project, uuid.UUID(self.project["id"])).template_version_id, v1.id)

        # A new project gets the task.
        new_project = self.create_draft(project_name="Next fitout", template_version_id=str(v2.id))
        codes = [t["code"] for t in self.client.get(f"/api/v2/projects/{new_project['id']}/template-review/tasks?page=1&page_size=20").json()["items"]]
        self.assertIn("T002", codes)

    def test_only_admin_can_add_to_template_and_nothing_is_saved_when_refused(self):
        self.act_as_pm()
        response = self.add(add_to_template=True)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Only Admin can add a task to the template", response.json()["detail"])
        with self.Session() as session:
            self.assertIsNone(session.scalar(select(Task).where(Task.original_code == "MANUAL-001")))

    def test_template_option_refused_when_task_runs_past_template_length(self):
        self.act_as_admin()
        response = self.add(add_to_template=True, planned_start_date="2026-09-10", planned_end_date="2026-09-20")
        self.assertEqual(response.status_code, 422)
        self.assertIn("45 days", response.json()["detail"])
        with self.Session() as session:
            self.assertIsNone(session.scalar(select(Task).where(Task.original_code == "MANUAL-001")))
        # Fine for this project only.
        self.assertEqual(self.add(planned_start_date="2026-09-10", planned_end_date="2026-09-20").status_code, 201)


# Reuse the parent's harness only; don't rerun its tests under this class.
for _name in dir(base.TaskVendorAssignmentApiTests):
    if _name.startswith("test_") and _name not in ProjectTaskAdditionTests.__dict__:
        setattr(ProjectTaskAdditionTests, _name, None)
