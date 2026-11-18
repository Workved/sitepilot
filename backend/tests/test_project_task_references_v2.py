"""Reference material added on a project: to a live task (at creation or
later) and to a draft task (carried onto the live task at activation). Who
can add/remove, what shows on the task, and downloads. Reuses the add-task
harness (activated project, template task T001, PM + Supervisor members)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from sqlalchemy import select

from app.execution_models import ProjectTaskReferenceFile, Task
from app.models import UserRole
from app.routes.project_task_references_v2 import router as references_router

# Imported as modules so pytest doesn't collect their tests here.
from tests import test_project_task_addition_v2 as addition
from tests import test_task_vendor_assignment_v2 as base

PDF = b"%PDF-1.4 approved drawing"


class ProjectTaskReferenceTests(addition.ProjectTaskAdditionTests):
    def setUp(self):
        self.store: dict[str, bytes] = {}
        self.patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, data, _type: self.store.__setitem__(key, data)),
            patch("app.services.evidence_storage.read", side_effect=self.store.get),
        ]
        for item in self.patches:
            item.start()
        super().setUp()
        self.app.include_router(references_router)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        super().tearDown()

    def upload(self, url, name="drawing.pdf", data=PDF, description="Approved drawing"):
        return self.client.post(url, data={"description": description}, files={"file": (name, data, "application/pdf")})

    def live_url(self, task_id):
        return f"/api/v2/projects/{self.project['id']}/tasks/{task_id}/reference-files"

    def detail(self, task_id):
        return self.client.get(f"/api/v2/projects/{self.project['id']}/tasks/{task_id}").json()

    # ---- live tasks ------------------------------------------------------------

    def test_supervisor_attaches_a_file_to_a_new_task_and_everyone_on_the_task_sees_it(self):
        self.act_as(addition.SUPERVISOR)
        task_id = self.add().json()["task_id"]
        response = self.upload(self.live_url(task_id))
        self.assertEqual(response.status_code, 201, response.text)
        ref = response.json()
        self.assertEqual((ref["filename"], ref["description"], ref["source"]), ("drawing.pdf", "Approved drawing", "project"))

        self.act_as_pm()
        files = self.detail(task_id)["reference_files"]
        self.assertEqual([f["filename"] for f in files], ["drawing.pdf"])
        download = self.client.get(f"{self.live_url(task_id)}/{ref['id']}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, PDF)

    def test_files_can_be_added_later_to_any_live_task_including_template_tasks(self):
        t001 = self.task_by_code(self.project["id"], "T001")
        self.act_as_pm()
        self.assertEqual(self.upload(self.live_url(t001.id), name="revised.pdf").status_code, 201)
        self.assertEqual([f["filename"] for f in self.detail(t001.id)["reference_files"]], ["revised.pdf"])

    def test_who_can_add_and_remove(self):
        t001 = self.task_by_code(self.project["id"], "T001")
        self.act_as(addition.OUTSIDER_PM)
        self.assertEqual(self.upload(self.live_url(t001.id)).status_code, 403)
        self.act_as(base.User(id=uuid.uuid4(), name="Emp", email="e@example.com", role=UserRole.internal_employee, active=True))
        self.assertEqual(self.upload(self.live_url(t001.id)).status_code, 403)

        self.act_as_admin()
        ref = self.upload(self.live_url(t001.id)).json()
        self.act_as(addition.OUTSIDER_PM)
        remove_url = f"/api/v2/projects/{self.project['id']}/task-reference-files/{ref['id']}"
        self.assertEqual(self.client.delete(remove_url).status_code, 403)
        self.act_as(addition.SUPERVISOR)
        self.assertEqual(self.client.delete(remove_url).status_code, 200)
        self.assertEqual(self.detail(t001.id)["reference_files"], [])
        self.assertEqual(self.client.delete(remove_url).status_code, 404)

    def test_bad_files_are_refused_and_nothing_is_stored(self):
        t001 = self.task_by_code(self.project["id"], "T001")
        self.act_as_admin()
        self.assertEqual(self.upload(self.live_url(t001.id), name="virus.exe", data=b"MZ...").status_code, 422)
        self.assertEqual(self.upload(self.live_url(t001.id), name="fake.pdf", data=b"not a pdf").status_code, 422)
        self.assertEqual(self.upload(self.live_url(t001.id), description="x" * 501).status_code, 422)
        self.assertEqual(self.store, {})

    # ---- draft tasks -------------------------------------------------------------

    def test_draft_task_file_shows_in_review_and_follows_the_task_at_activation(self):
        draft = self.create_draft(project_name="Next fitout")
        created = self.client.post(f"/api/v2/projects/{draft['id']}/tasks", json={
            "title": "Glass partition", "phase": "Electrical", "category": "Wiring and conduits",
            "planned_start_day": 2, "planned_end_day": 3, "reason": "Client asked",
        })
        self.assertEqual(created.status_code, 201, created.text)
        project_task_id = created.json()["task_id"]
        self.act_as(addition.SUPERVISOR)
        uploaded = self.upload(f"/api/v2/projects/{draft['id']}/project-tasks/{project_task_id}/reference-files", name="glass.pdf")
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

        self.act_as_admin()
        review = self.client.get(f"/api/v2/projects/{draft['id']}/template-review/tasks?page=1&page_size=20").json()["items"]
        manual = next(item for item in review if item["id"] == project_task_id)
        self.assertEqual([f["filename"] for f in manual["reference_files"]], ["glass.pdf"])

        self.assertEqual(self.client.post(f"/api/v2/projects/{draft['id']}/activate", json={"reason": "Go live."}).status_code, 200)
        with self.Session() as session:
            live = session.scalar(select(Task).where(Task.project_id == uuid.UUID(draft["id"]), Task.title == "Glass partition"))
            link = session.scalar(select(ProjectTaskReferenceFile))
            self.assertEqual(link.task_id, live.id)
        files = self.client.get(f"/api/v2/projects/{draft['id']}/tasks/{live.id}").json()["reference_files"]
        self.assertEqual([f["filename"] for f in files], ["glass.pdf"])

        # Once started, a draft-task upload is refused; the live task takes files instead.
        again = self.upload(f"/api/v2/projects/{draft['id']}/project-tasks/{project_task_id}/reference-files")
        self.assertEqual(again.status_code, 409)


for _name in dir(addition.ProjectTaskAdditionTests):
    if _name.startswith("test_") and _name not in ProjectTaskReferenceTests.__dict__:
        setattr(ProjectTaskReferenceTests, _name, None)
