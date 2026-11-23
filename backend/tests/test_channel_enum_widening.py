"""Channel/source CHECK constraints on `TaskProgressUpdate.source` and
`VendorAcknowledgement.channel`. 'telegram' stays a valid stored value so
rows recorded before the Telegram channel was removed keep loading, but the
API (`VendorAcknowledgementIn.channel`) no longer accepts it.

FK targets (tasks/projects/task_vendor_assignments/users) are not created
in this minimal harness - SQLite does not enforce foreign keys unless a
PRAGMA is set, and this file's scope is the CHECK constraint alone, not
the full referential chain (already covered by other test files).
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import TaskProgressUpdate
from app.models import User  # noqa: F401 - registers `users` in metadata for FK resolution below
from app.project_models import V2Project  # noqa: F401 - registers `siteops_v2.projects` for FK resolution below
from app.schemas.vendor_assignment import VendorAcknowledgementIn
from app.vendor_models import VendorAcknowledgement


class ChannelEnumWideningModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (TaskProgressUpdate.__table__, VendorAcknowledgement.__table__):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def test_task_progress_update_accepts_telegram_source(self):
        with self.Session.begin() as session:
            session.add(TaskProgressUpdate(
                task_id=uuid.uuid4(), project_id=uuid.uuid4(), update_type="note",
                submitted_by=uuid.uuid4(), source="telegram",
            ))

    def test_vendor_acknowledgement_accepts_telegram_channel(self):
        with self.Session.begin() as session:
            session.add(VendorAcknowledgement(
                task_vendor_assignment_id=uuid.uuid4(), response="accepted",
                channel="telegram", recorded_by=uuid.uuid4(),
            ))

    def test_existing_values_still_validate(self):
        with self.Session.begin() as session:
            for source in ("portal", "whatsapp", "system"):
                session.add(TaskProgressUpdate(
                    task_id=uuid.uuid4(), project_id=uuid.uuid4(), update_type="note",
                    submitted_by=uuid.uuid4(), source=source,
                ))
            for channel in ("portal", "whatsapp", "system"):
                session.add(VendorAcknowledgement(
                    task_vendor_assignment_id=uuid.uuid4(), response="accepted",
                    channel=channel, recorded_by=uuid.uuid4(),
                ))

    def test_unsupported_source_value_is_still_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as session:
                session.add(TaskProgressUpdate(
                    task_id=uuid.uuid4(), project_id=uuid.uuid4(), update_type="note",
                    submitted_by=uuid.uuid4(), source="sms",
                ))

    def test_unsupported_channel_value_is_still_rejected(self):
        with self.assertRaises(IntegrityError):
            with self.Session.begin() as session:
                session.add(VendorAcknowledgement(
                    task_vendor_assignment_id=uuid.uuid4(), response="accepted",
                    channel="sms", recorded_by=uuid.uuid4(),
                ))


class VendorAcknowledgementInSchemaTests(unittest.TestCase):
    def test_telegram_is_no_longer_accepted_from_clients(self):
        with self.assertRaises(ValidationError):
            VendorAcknowledgementIn(response="accepted", channel="telegram")

    def test_still_defaults_to_portal(self):
        payload = VendorAcknowledgementIn(response="accepted")
        self.assertEqual(payload.channel, "portal")


if __name__ == "__main__":
    unittest.main()
