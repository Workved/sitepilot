"""Vendor people on projects and tasks: attaching a vendor contact to a
project (optionally per trade category), naming a task's point person, who
may do each, and who task messages reach.

Reuses the task-assignment harness (real activated project with task T001,
phase "Electrical") from test_task_vendor_assignment_v2.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.execution_models import OutboxEvent
from app.models import EmployeeProfile, User, UserRole
from app.services.message_dispatch import MessageDispatchService
from app.routes.communication import router as hub_router
from app.vendor_models import (
    TaskVendorAssignment,
    V2VendorPastProject,
    V2CapabilityCategory,
    V2Vendor,
    V2VendorContact,
    VendorContactProject,
)
# Imported as a module, not by name: a TestCase class name in this module's
# namespace would make pytest collect and run the parent's tests here too.
from tests import test_task_vendor_assignment_v2 as base

SUPERVISOR_ID = base.SUPERVISOR_ID

OUTSIDER_SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccc99")
EMPLOYEE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeee77")


class VendorContactAssignmentTests(base.TaskVendorAssignmentApiTests):
    def _seed(self):
        V2VendorPastProject.__table__.create(self.engine)  # read by the Vendor Hub endpoint
        super()._seed()
        with self.Session.begin() as session:
            session.add_all([
                User(id=OUTSIDER_SUPERVISOR_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True),
                User(id=EMPLOYEE_ID, name="Employee", email="employee@example.com", role=UserRole.internal_employee, active=True),
            ])
            session.flush()
            session.add(EmployeeProfile(user_id=OUTSIDER_SUPERVISOR_ID, employee_code="SUP-099", designation="Supervisor", availability="available"))
            primary = V2VendorContact(vendor_id=self.vendor_electrical_id, name="Ravi", phone="+919000000001", is_primary=True)
            member = V2VendorContact(vendor_id=self.vendor_electrical_id, name="Ramesh", designation="Ceiling lead", phone="+919000000011")
            other_vendor_contact = V2VendorContact(vendor_id=self.vendor_plumbing_id, name="Meena", phone="+919000000002", is_primary=True)
            sub_vendor = V2Vendor(
                id=uuid.uuid4(), name="Electrical Sub Co", contact_person="Sonu", phone="9000000009",
                status="active", engagement_type="sub_vendor", parent_vendor_id=self.vendor_electrical_id,
            )
            session.add_all([primary, member, other_vendor_contact, sub_vendor])
            session.flush()
            sub_contact = V2VendorContact(vendor_id=sub_vendor.id, name="Sonu", phone="+919000000019", is_primary=True)
            session.add(sub_contact)
            session.flush()
            self.primary_id = primary.id
            self.member_id = member.id
            self.other_vendor_contact_id = other_vendor_contact.id
            self.sub_contact_id = sub_contact.id
            self.electrical_category_id = session.scalar(select(V2CapabilityCategory.id).where(V2CapabilityCategory.name == "Electrical"))
            self.plumbing_category_id = session.scalar(select(V2CapabilityCategory.id).where(V2CapabilityCategory.name == "Plumbing"))

    # ---- helpers ---------------------------------------------------------

    def act_as_supervisor(self):
        self.act_as(User(id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True))

    def act_as_outsider(self):
        self.act_as(User(id=OUTSIDER_SUPERVISOR_ID, name="Outsider", email="outsider@example.com", role=UserRole.supervisor, active=True))

    def act_as_employee(self):
        self.act_as(User(id=EMPLOYEE_ID, name="Employee", email="employee@example.com", role=UserRole.internal_employee, active=True))

    def mapped_project(self):
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.vendor_electrical_id).status_code, 200)
        return project

    def attach(self, project_id, contact_id, category_ids=(), note=None):
        return self.client.post(
            f"/api/v2/projects/{project_id}/vendor-contacts",
            json={"contact_id": str(contact_id), "category_ids": [str(c) for c in category_ids], "note": note},
        )

    def delegate(self, project_id, task_id, vendor_id, contact_id=None):
        self.act_as_pm()
        body = {"vendor_id": str(vendor_id)}
        if contact_id is not None:
            body["contact_id"] = str(contact_id)
        return self.client.post(f"/api/v2/projects/{project_id}/tasks/{task_id}/vendor-assignment", json=body)

    # ---- attaching people to a project -----------------------------------

    def test_supervisor_on_project_attaches_person_per_category(self):
        project = self.mapped_project()
        self.act_as_supervisor()
        response = self.attach(project["id"], self.member_id, [self.electrical_category_id, self.plumbing_category_id], "Handles ceiling")
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual({row["category_id"] for row in rows}, {str(self.electrical_category_id), str(self.plumbing_category_id)})
        self.assertTrue(all(row["note"] == "Handles ceiling" for row in rows))

        # Attaching again is idempotent: no duplicate active rows.
        again = self.attach(project["id"], self.member_id, [self.electrical_category_id])
        self.assertEqual(len(again.json()), 2)

    def test_empty_categories_means_all_work(self):
        project = self.mapped_project()
        self.act_as_admin()
        rows = self.attach(project["id"], self.member_id).json()
        self.assertEqual([row["category_id"] for row in rows], [None])

    def test_access_rules(self):
        project = self.mapped_project()
        self.act_as_outsider()
        self.assertEqual(self.attach(project["id"], self.member_id).status_code, 403)
        self.act_as_employee()
        self.assertEqual(self.attach(project["id"], self.member_id).status_code, 403)
        self.act_as_pm()
        self.assertEqual(self.attach(project["id"], self.member_id).status_code, 200)

    def test_vendor_must_be_on_project(self):
        project = self.mapped_project()
        self.act_as_admin()
        response = self.attach(project["id"], self.other_vendor_contact_id)
        self.assertEqual(response.status_code, 422)
        self.assertIn("not mapped", response.json()["detail"])

    def test_sub_vendor_person_allowed_through_parent_mapping(self):
        project = self.mapped_project()
        self.act_as_admin()
        self.assertEqual(self.attach(project["id"], self.sub_contact_id).status_code, 200)

    def test_bad_category_and_unknown_contact(self):
        project = self.mapped_project()
        self.act_as_admin()
        self.assertEqual(self.attach(project["id"], self.member_id, [uuid.uuid4()]).status_code, 400)
        self.assertEqual(self.attach(project["id"], uuid.uuid4()).status_code, 404)

    def test_end_attachment_keeps_history(self):
        project = self.mapped_project()
        self.act_as_admin()
        row = self.attach(project["id"], self.member_id).json()[0]
        ended = self.client.post(f"/api/v2/projects/{project['id']}/vendor-contacts/{row['id']}/end")
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertIsNotNone(ended.json()["ends_at"])
        self.assertEqual(self.client.post(f"/api/v2/projects/{project['id']}/vendor-contacts/{row['id']}/end").status_code, 404)
        with self.Session() as session:
            self.assertEqual(len(session.scalars(select(VendorContactProject)).all()), 1)

    def test_project_vendor_list_shows_people_attached_first(self):
        project = self.mapped_project()
        self.act_as_admin()
        self.attach(project["id"], self.member_id, [self.electrical_category_id])
        vendors = self.client.get(f"/api/v2/projects/{project['id']}/vendors").json()
        contacts = next(v for v in vendors if v["vendor_id"] == str(self.vendor_electrical_id))["contacts"]
        self.assertEqual([c["name"] for c in contacts], ["Ramesh", "Ravi"])
        self.assertEqual(contacts[0]["attachments"][0]["category_name"], "Electrical")
        self.assertEqual(contacts[1]["attachments"], [])

    # ---- task point person --------------------------------------------------

    def test_delegate_with_point_person(self):
        project = self.mapped_project()
        task = self.task_by_code(project["id"], "T001")
        response = self.delegate(project["id"], task.id, self.vendor_electrical_id, self.member_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["contact_id"], str(self.member_id))

        listed = self.client.get(f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignments").json()
        self.assertEqual(listed[0]["contact_name"], "Ramesh")
        self.assertEqual(listed[0]["contact_phone"], "+919000000011")

        with self.Session() as session:
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "task.vendor_assigned"))
        self.assertEqual(event.payload["contact_id"], str(self.member_id))

    def test_point_person_must_belong_to_vendor(self):
        project = self.mapped_project()
        task = self.task_by_code(project["id"], "T001")
        response = self.delegate(project["id"], task.id, self.vendor_electrical_id, self.other_vendor_contact_id)
        self.assertEqual(response.status_code, 422)

    def test_supervisor_changes_and_clears_point_person(self):
        project = self.mapped_project()
        task = self.task_by_code(project["id"], "T001")
        assignment = self.delegate(project["id"], task.id, self.vendor_electrical_id).json()
        url = f"/api/v2/projects/{project['id']}/tasks/{task.id}/vendor-assignment/{assignment['id']}/contact"

        self.act_as_supervisor()
        changed = self.client.put(url, json={"contact_id": str(self.member_id)})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["contact_id"], str(self.member_id))
        self.assertEqual(self.client.put(url, json={"contact_id": str(self.other_vendor_contact_id)}).status_code, 422)
        cleared = self.client.put(url, json={"contact_id": None})
        self.assertIsNone(cleared.json()["contact_id"])

        self.act_as_outsider()
        self.assertEqual(self.client.put(url, json={"contact_id": str(self.member_id)}).status_code, 403)

    # ---- Vendor Hub: a person's projects and tasks -------------------------

    def test_hub_lists_each_persons_projects_and_tasks(self):
        self.app.include_router(hub_router)
        project = self.mapped_project()
        task = self.task_by_code(project["id"], "T001")
        self.act_as_admin()
        self.attach(project["id"], self.member_id, [self.electrical_category_id], "Ceiling crew")
        self.delegate(project["id"], task.id, self.vendor_electrical_id, self.member_id)

        self.act_as_admin()
        hub = self.client.get("/api/communication-hub").json()
        self.assertEqual(
            [(row["contact_id"], row["category_name"], row["note"]) for row in hub["contact_projects"]],
            [(str(self.member_id), "Electrical", "Ceiling crew")],
        )
        self.assertEqual([(row["contact_id"], row["task_title"]) for row in hub["contact_tasks"]], [(str(self.member_id), "Task T001")])

        # A supervisor who isn't on the project doesn't see it.
        self.act_as_outsider()
        hidden = self.client.get("/api/communication-hub").json()
        self.assertEqual(hidden["contact_projects"], [])
        self.assertEqual(hidden["contact_tasks"], [])

    # ---- who task messages reach --------------------------------------------

    def _dispatcher(self, session):
        return MessageDispatchService(session)

    def test_messages_go_to_point_person_and_primary(self):
        with self.Session() as session:
            dispatcher = self._dispatcher(session)
            both = dispatcher._vendor_task_recipients(self.vendor_electrical_id, self.member_id)
            self.assertEqual([r.vendor_contact_id for r in both], [self.member_id, self.primary_id])
            same = dispatcher._vendor_task_recipients(self.vendor_electrical_id, self.primary_id)
            self.assertEqual([r.vendor_contact_id for r in same], [self.primary_id])
            none_set = dispatcher._vendor_task_recipients(self.vendor_electrical_id, None)
            self.assertEqual([r.vendor_contact_id for r in none_set], [self.primary_id])
            wrong_vendor = dispatcher._vendor_task_recipients(self.vendor_electrical_id, self.other_vendor_contact_id)
            self.assertEqual([r.vendor_contact_id for r in wrong_vendor], [self.primary_id])

    def test_assignment_event_and_reminder_reach_point_person(self):
        project = self.mapped_project()
        task = self.task_by_code(project["id"], "T001")
        self.delegate(project["id"], task.id, self.vendor_electrical_id, self.member_id)
        with self.Session() as session:
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "task.vendor_assigned"))
            dispatcher = self._dispatcher(session)
            event_contacts = [r.vendor_contact_id for r in dispatcher._resolve_vendor_task_event_recipients(event)]
            self.assertEqual(event_contacts, [self.member_id, self.primary_id])
            reminder_contacts = [r.vendor_contact_id for r in dispatcher._resolve_vendor_recipient_for_task(task)]
            self.assertEqual(reminder_contacts, [self.member_id, self.primary_id])

            # The point person is read live from the assignment, so a later
            # change is what the next message uses.
            assignment = session.scalar(select(TaskVendorAssignment))
            assignment.contact_id = None
            session.commit()
            self.assertEqual([r.vendor_contact_id for r in dispatcher._resolve_vendor_task_event_recipients(event)], [self.primary_id])


# This class reuses the parent's harness only; don't run the parent's tests
# a second time under this class.
for _name in dir(base.TaskVendorAssignmentApiTests):
    if _name.startswith("test_") and _name not in VendorContactAssignmentTests.__dict__:
        setattr(VendorContactAssignmentTests, _name, None)
