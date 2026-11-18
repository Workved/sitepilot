"""Admin-managed vendor categories (which are also template phases): add,
rename, hide/show, remove-or-hide, who may, and that matching keeps working.
Reuses the task-vendor harness: template phase "Electrical" (task T001),
categories Electrical / Plumbing / Wiring and conduits, vendors holding them."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import User, UserRole
from app.project_models import V2AuditEvent
from app.vendor_models import V2CapabilityCategory

# Imported as a module so pytest doesn't collect the parent's tests here.
from tests import test_task_vendor_assignment_v2 as base

URL = "/api/v2/vendors/capability-categories"
SUPERVISOR = User(id=base.SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", role=UserRole.supervisor, active=True)


class VendorCategoryTests(base.TaskVendorAssignmentApiTests):
    def category_id(self, name):
        with self.Session() as session:
            return session.scalar(select(V2CapabilityCategory.id).where(V2CapabilityCategory.name == name))

    def names(self, include_hidden=False):
        return [c["name"] for c in self.client.get(URL, params={"include_hidden": include_hidden}).json()]

    def test_admin_adds_a_category_and_it_is_offered_everywhere(self):
        self.act_as_admin()
        response = self.client.post(URL, json={"name": "  Glass   Works "})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual((response.json()["name"], response.json()["active"]), ("Glass Works", True))
        self.assertIn("Glass Works", self.names())
        # Duplicate, any case.
        self.assertEqual(self.client.post(URL, json={"name": "glass works"}).status_code, 409)
        self.assertEqual(self.client.post(URL, json={"name": "x"}).status_code, 422)
        with self.Session() as session:
            self.assertEqual(session.scalar(select(V2AuditEvent.action).where(V2AuditEvent.entity_type == "vendor_category")), "VENDOR_CATEGORY_ADDED")

    def test_only_admins_manage_categories(self):
        for act in (self.act_as_pm, lambda: self.act_as(SUPERVISOR)):
            act()
            self.assertEqual(self.client.post(URL, json={"name": "Glass Works"}).status_code, 403)
            self.assertEqual(self.client.patch(f"{URL}/{self.category_id('Plumbing')}", json={"name": "Pipes"}).status_code, 403)
            self.assertEqual(self.client.delete(f"{URL}/{self.category_id('Plumbing')}").status_code, 403)
            # Everyone can still read the list (vendor pickers, template form).
            self.assertEqual(self.client.get(URL).status_code, 200)

    def test_rename_allowed_unless_the_name_is_a_task_phase(self):
        self.act_as_admin()
        renamed = self.client.patch(f"{URL}/{self.category_id('Plumbing')}", json={"name": "Plumbing & Drainage"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "Plumbing & Drainage")
        # "Electrical" is the phase of template task T001: renaming would break matching.
        refused = self.client.patch(f"{URL}/{self.category_id('Electrical')}", json={"name": "Electricals"})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("Add a new category and hide this one", refused.json()["detail"])
        self.assertEqual(self.client.patch(f"{URL}/{self.category_id('Plumbing & Drainage')}", json={"name": "Wiring and Conduits"}).status_code, 409)

    def test_remove_deletes_unused_but_hides_used_and_hidden_still_matches(self):
        self.act_as_admin()
        unused = self.client.post(URL, json={"name": "Signage"}).json()
        gone = self.client.delete(f"{URL}/{unused['id']}").json()
        self.assertEqual((gone["deleted"], gone["hidden"]), (True, False))
        self.assertNotIn("Signage", self.names(include_hidden=True))

        # Electrical: vendors have it and a task uses it as its phase.
        hidden = self.client.delete(f"{URL}/{self.category_id('Electrical')}").json()
        self.assertEqual((hidden["deleted"], hidden["hidden"]), (False, True))
        self.assertIn("hidden, not deleted", hidden["message"])
        self.assertNotIn("Electrical", self.names())
        self.assertIn("Electrical", self.names(include_hidden=True))

        # A vendor that already had it can still be given the Electrical task.
        project = self.activate_project()
        self.assertEqual(self.map_vendor(project["id"], self.vendor_electrical_id).status_code, 200)
        task = self.task_by_code(project["id"], "T001")
        self.assertEqual(self.assign_vendor(project["id"], task.id, self.vendor_electrical_id).status_code, 200)

        # Adding the name again shows it again.
        self.act_as_admin()
        shown = self.client.post(URL, json={"name": "electrical"})
        self.assertEqual(shown.status_code, 201)
        self.assertTrue(shown.json()["active"])
        self.assertIn("Electrical", self.names())

    def test_hide_and_show_directly(self):
        self.act_as_admin()
        plumbing = self.category_id("Plumbing")
        self.assertFalse(self.client.patch(f"{URL}/{plumbing}", json={"active": False}).json()["active"])
        self.assertNotIn("Plumbing", self.names())
        self.assertTrue(self.client.patch(f"{URL}/{plumbing}", json={"active": True}).json()["active"])
        self.assertEqual(self.client.patch(f"{URL}/{uuid.uuid4()}", json={"active": True}).status_code, 404)

    def test_list_reports_vendor_counts(self):
        self.act_as_admin()
        counts = {c["name"]: c["vendor_count"] for c in self.client.get(URL).json()}
        self.assertEqual(counts["Electrical"], 3)
        self.assertEqual(counts["Plumbing"], 1)


for _name in dir(base.TaskVendorAssignmentApiTests):
    if _name.startswith("test_") and _name not in VendorCategoryTests.__dict__:
        setattr(VendorCategoryTests, _name, None)
