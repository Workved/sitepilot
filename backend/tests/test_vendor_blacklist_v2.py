"""Vendor blacklist: the only vendor status. Who can blacklist / remove it,
what blacklisting ends (quietly), what it blocks, and how it shows in the
Vendor Hub data. Reuses the vendor-people harness (activated project with
task T001, main vendor "Electrical Co" with contacts and a sub-vendor)."""

from __future__ import annotations

from sqlalchemy import select

from app.execution_models import OutboxEvent
from app.routes.communication import router as hub_router
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2Vendor, VendorContactProject

# Imported as a module so pytest doesn't collect the parent classes here.
from tests import test_vendor_contact_assignments_v2 as people


class VendorBlacklistTests(people.VendorContactAssignmentTests):
    def setUp(self):
        super().setUp()
        self.app.include_router(hub_router)

    def blacklist(self, vendor_id, reason="Poor workmanship on site"):
        return self.client.post(f"/api/communication-hub/vendors/{vendor_id}/blacklist", json={"reason": reason})

    def unblacklist(self, vendor_id, reason="Issue resolved"):
        return self.client.post(f"/api/communication-hub/vendors/{vendor_id}/unblacklist", json={"reason": reason})

    def sub_vendor_id(self):
        with self.Session() as session:
            return session.scalar(select(V2Vendor.id).where(V2Vendor.parent_vendor_id == self.vendor_electrical_id))

    def busy_project(self):
        """Main vendor and its sub-vendor on the project, a person assigned,
        and the main vendor delegated task T001."""
        project = self.mapped_project()
        self.assertEqual(self.map_vendor(project["id"], self.sub_vendor_id()).status_code, 200)
        task = self.task_by_code(project["id"], "T001")
        self.act_as_admin()
        self.attach(project["id"], self.member_id)
        self.assertEqual(self.delegate(project["id"], task.id, self.vendor_electrical_id, self.member_id).status_code, 200)
        return project, task

    # ---- who ------------------------------------------------------------------

    def test_supervisor_pm_and_admin_can_blacklist_employee_cannot(self):
        self.act_as_employee()
        self.assertEqual(self.blacklist(self.vendor_plumbing_id).status_code, 403)
        for act in (self.act_as_supervisor, self.act_as_pm, self.act_as_admin):
            act()
            self.assertEqual(self.blacklist(self.vendor_plumbing_id).status_code, 200)
            self.act_as_admin()
            self.assertEqual(self.unblacklist(self.vendor_plumbing_id).status_code, 200)

    def test_only_admins_can_remove_from_blacklist(self):
        self.act_as_supervisor()
        self.blacklist(self.vendor_plumbing_id)
        for act in (self.act_as_supervisor, self.act_as_pm):
            act()
            self.assertEqual(self.unblacklist(self.vendor_plumbing_id).status_code, 403)
        self.act_as_admin()
        self.assertEqual(self.unblacklist(self.vendor_plumbing_id).status_code, 200)

    def test_reason_required_and_no_double_blacklist(self):
        self.act_as_admin()
        self.assertEqual(self.blacklist(self.vendor_plumbing_id, "  ").status_code, 422)
        self.assertEqual(self.blacklist(self.vendor_plumbing_id).status_code, 200)
        self.assertEqual(self.blacklist(self.vendor_plumbing_id).status_code, 409)
        self.assertEqual(self.unblacklist(self.vendor_plumbing_id, "ok").status_code, 422)
        self.assertEqual(self.unblacklist(self.vendor_electrical_id).status_code, 409)

    # ---- what it ends -----------------------------------------------------------

    def test_blacklisting_ends_current_work_for_vendor_and_sub_vendors_quietly(self):
        project, _task = self.busy_project()
        with self.Session() as session:
            events_before = session.scalars(select(OutboxEvent.event_type)).all()

        self.act_as_supervisor()
        response = self.blacklist(self.vendor_electrical_id)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sub_vendors_blocked"], 1)
        self.assertEqual(body["task_assignments_ended"], 1)
        self.assertEqual(body["people_assignments_ended"], 1)
        self.assertEqual(body["projects_ended"], 1)

        with self.Session() as session:
            self.assertEqual(session.scalars(select(ProjectVendor).where(ProjectVendor.ends_at.is_(None))).all(), [])
            self.assertEqual(session.scalars(select(TaskVendorAssignment).where(TaskVendorAssignment.ends_at.is_(None))).all(), [])
            self.assertEqual(session.scalars(select(VendorContactProject).where(VendorContactProject.ends_at.is_(None))).all(), [])
            # History kept: rows ended, not deleted.
            self.assertEqual(len(session.scalars(select(ProjectVendor)).all()), 2)
            # Nothing sent to the vendor (the removal template would carry the reason).
            self.assertEqual(session.scalars(select(OutboxEvent.event_type)).all(), events_before)

    # ---- what it blocks ----------------------------------------------------------

    def test_blacklisted_vendor_and_its_sub_vendors_cannot_take_new_work(self):
        project = self.activate_project()
        self.act_as_admin()
        self.blacklist(self.vendor_electrical_id)

        mapped = self.map_vendor(project["id"], self.vendor_electrical_id)
        self.assertEqual(mapped.status_code, 422)
        self.assertIn("blacklisted", mapped.json()["detail"])
        sub = self.map_vendor(project["id"], self.sub_vendor_id())
        self.assertEqual(sub.status_code, 422)
        self.assertIn("main vendor is blacklisted", sub.json()["detail"])

        self.act_as_pm()
        offered = {v["id"] for v in self.client.get("/api/v2/vendors").json()}
        self.assertNotIn(str(self.vendor_electrical_id), offered)
        self.assertNotIn(str(self.sub_vendor_id()), offered)
        self.assertIn(str(self.vendor_plumbing_id), offered)

    def test_removing_from_blacklist_allows_new_work_but_restores_nothing(self):
        project, _task = self.busy_project()
        self.act_as_admin()
        self.blacklist(self.vendor_electrical_id)
        self.assertEqual(self.unblacklist(self.vendor_electrical_id).status_code, 200)
        with self.Session() as session:
            self.assertEqual(session.scalars(select(ProjectVendor).where(ProjectVendor.ends_at.is_(None))).all(), [])
        self.assertEqual(self.map_vendor(project["id"], self.vendor_electrical_id).status_code, 200)

    def test_editing_profile_never_changes_blacklist(self):
        self.act_as_admin()
        self.blacklist(self.vendor_plumbing_id)
        response = self.client.put(f"/api/communication-hub/contractors/{self.vendor_plumbing_id}", json={
            "name": "Plumbing Co Renamed", "engagement_type": "main", "status": "active", "category_ids": [str(self.plumbing_category_id)],
        })
        self.assertEqual(response.status_code, 200, response.text)
        with self.Session() as session:
            vendor = session.get(V2Vendor, self.vendor_plumbing_id)
            self.assertEqual((vendor.name, vendor.status), ("Plumbing Co Renamed", "blacklisted"))

    # ---- Vendor Hub data ------------------------------------------------------------

    def test_hub_shows_blacklist_details_and_blocked_sub_vendors(self):
        self.act_as_supervisor()
        self.blacklist(self.vendor_electrical_id, "Left site mid-job")
        self.act_as_admin()
        vendors = {v["id"]: v for v in self.client.get("/api/communication-hub").json()["vendors"]}
        main = vendors[str(self.vendor_electrical_id)]
        self.assertTrue(main["blacklisted"])
        self.assertEqual(main["blacklist_reason"], "Left site mid-job")
        self.assertEqual(main["blacklisted_by_name"], "Supervisor")
        self.assertIsNotNone(main["blacklisted_at"])
        sub = vendors[str(self.sub_vendor_id())]
        self.assertFalse(sub["blacklisted"])
        self.assertTrue(sub["blocked_by_parent"])
        other = vendors[str(self.vendor_plumbing_id)]
        self.assertFalse(other["blacklisted"] or other["blocked_by_parent"])


# Reuse the parent's harness only; don't rerun its tests under this class.
for _name in dir(people.VendorContactAssignmentTests):
    if _name.startswith("test_") and _name not in VendorBlacklistTests.__dict__:
        setattr(VendorBlacklistTests, _name, None)
