"""`broadcast_service.py`'s three recipient resolvers: WhatsApp is the only
messaging channel, offered whenever the recipient has a number on file.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.broadcast_service import _internal_recipients, _vendor_contact_recipients, _vendor_recipients
from app.vendor_models import ProjectVendor, V2Vendor, V2VendorContact
from datetime import date


class BroadcastChannelAwarenessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2Vendor.__table__, V2VendorContact.__table__, ProjectVendor.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.project_id = uuid.uuid4()

        with self.Session.begin() as session:
            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Test Project", client_name="Client", site_address="Mumbai",
                start_date=date(2026, 8, 1), status="active", created_by=uuid.uuid4(),
            ))

        self.session = self.Session()

    def tearDown(self):
        self.session.close()

    # ---- step 1: _internal_recipients -----------------------------------

    def _add_member(self, *, phone):
        user_id = uuid.uuid4()
        with self.session.begin():
            self.session.add(User(id=user_id, name="Member", email=f"{user_id}@example.com", phone=phone, role=UserRole.supervisor, active=True))
            self.session.flush()
            profile = EmployeeProfile(
                user_id=user_id, employee_code=f"EMP-{user_id.hex[:6]}", designation="Supervisor",
                availability="available",
            )
            self.session.add(profile)
            self.session.flush()
            self.session.add(V2ProjectMembership(
                project_id=self.project_id, employee_id=profile.id, project_role="site_supervisor",
                assigned_by=uuid.uuid4(), assignment_reason="test setup",
            ))
        return user_id

    def test_internal_recipient_on_whatsapp_with_phone_resolves_whatsapp(self):
        self._add_member(phone="+911234567890")
        results = _internal_recipients(self.session, self.project_id, "site_supervisor")
        self.assertIn("whatsapp", results[0]["channels"])

    def test_internal_recipient_with_no_phone_resolves_no_messaging_channel(self):
        self._add_member(phone=None)
        results = _internal_recipients(self.session, self.project_id, "site_supervisor")
        self.assertNotIn("whatsapp", results[0]["channels"])

    # ---- step 2: _vendor_recipients ---------------------------------------

    def _add_vendor(self, *, phone="+911111111111", email="vendor@example.com"):
        vendor = V2Vendor(name="Acme Electric", contact_person="Acme Owner", phone=phone, email=email)
        with self.session.begin():
            self.session.add(vendor)
            self.session.flush()
            self.session.add(ProjectVendor(project_id=self.project_id, vendor_id=vendor.id, mapped_by=uuid.uuid4()))
        return vendor.id

    def test_vendor_with_primary_contact_on_whatsapp_resolves_whatsapp(self):
        vendor_id = self._add_vendor()
        with self.session.begin():
            self.session.add(V2VendorContact(
                vendor_id=vendor_id, name="Primary", phone="+911234567890", is_primary=True,
            ))
        results = _vendor_recipients(self.session, self.project_id)
        self.assertIn("whatsapp", results[0]["channels"])

    def test_vendor_with_no_primary_contact_falls_back_to_vendor_fields(self):
        vendor_id = self._add_vendor(phone="+919999999999")
        with self.session.begin():
            # A non-primary contact on file - should not be used.
            self.session.add(V2VendorContact(vendor_id=vendor_id, name="Not Primary", phone="+911111110000", is_primary=False))
        results = _vendor_recipients(self.session, self.project_id)
        self.assertIn("whatsapp", results[0]["channels"])
        self.assertEqual(results[0]["phone"], "+919999999999")

    def test_vendor_with_multiple_primary_contacts_falls_back_to_vendor_fields(self):
        vendor_id = self._add_vendor(phone="+919999999999")
        with self.session.begin():
            self.session.add(V2VendorContact(vendor_id=vendor_id, name="Primary 1", phone="+911111110000", is_primary=True))
            self.session.add(V2VendorContact(vendor_id=vendor_id, name="Primary 2", phone="+922222220000", is_primary=True))
        results = _vendor_recipients(self.session, self.project_id)
        self.assertEqual(len(results), 1)
        self.assertIn("whatsapp", results[0]["channels"])
        self.assertEqual(results[0]["phone"], "+919999999999")

    # ---- step 3: _vendor_contact_recipients -------------------------------

    def test_vendor_contact_with_phone_resolves_whatsapp(self):
        vendor_id = self._add_vendor()
        with self.session.begin():
            self.session.add(V2VendorContact(vendor_id=vendor_id, name="Contact", phone="+911234567890"))
        results = _vendor_contact_recipients(self.session, self.project_id)
        self.assertEqual(results[0]["channels"], ["whatsapp"])

    def test_vendor_contact_with_no_contact_info_is_skipped_no_channel(self):
        vendor_id = self._add_vendor()
        with self.session.begin():
            self.session.add(V2VendorContact(vendor_id=vendor_id, name="Contact", phone=""))
        results = _vendor_contact_recipients(self.session, self.project_id)
        self.assertEqual(results[0]["channels"], [])


if __name__ == "__main__":
    unittest.main()
