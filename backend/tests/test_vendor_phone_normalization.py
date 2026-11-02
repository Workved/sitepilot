from __future__ import annotations

import unittest
import uuid

from pydantic import ValidationError

from app.schemas.requests import VendorContactIn, VendorIn, normalize_phone


class VendorPhoneNormalizationTests(unittest.TestCase):
    """Vendor numbers are stored in E.164 so outbound WhatsApp can reach
    them and inbound replies (`+<from>`) match by exact string."""

    def test_formatting_is_stripped(self):
        self.assertEqual(normalize_phone(" +91 98765-43210 "), "+919876543210")
        self.assertEqual(normalize_phone("+91 (987) 654.3210"), "+919876543210")

    def test_leading_double_zero_becomes_plus(self):
        self.assertEqual(normalize_phone("00919876543210"), "+919876543210")

    def test_blank_is_none(self):
        self.assertIsNone(normalize_phone(None))
        self.assertIsNone(normalize_phone("   "))

    def test_number_without_country_code_is_rejected(self):
        for value in ("9876543210", "919876543210", "+0123456789", "abc"):
            with self.assertRaises(ValueError, msg=value):
                normalize_phone(value)

    def test_vendor_payload_is_normalized(self):
        vendor = VendorIn(
            name="Acme", category="civil", contact_person="Ravi", phone="+91 98765 43210", whatsapp="",
        )
        self.assertEqual((vendor.phone, vendor.whatsapp), ("+919876543210", None))

    def test_vendor_payload_requires_a_phone(self):
        with self.assertRaises(ValidationError):
            VendorIn(name="Acme", category="civil", contact_person="Ravi", phone=" ")

    def test_vendor_contact_payload_is_normalized_and_validated(self):
        contact = VendorContactIn(vendor_id=uuid.uuid4(), name="Ravi", phone="+91-98765-43210", whatsapp="0091 98765 43211")
        self.assertEqual((contact.phone, contact.whatsapp), ("+919876543210", "+919876543211"))
        with self.assertRaises(ValidationError):
            VendorContactIn(vendor_id=uuid.uuid4(), name="Ravi", phone="98765 43210")


if __name__ == "__main__":
    unittest.main()
