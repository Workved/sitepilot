"""the one-time `reviewed_at` backfill in
202609250002_v2_task_progress_reviewed_at.sql.

Runs the migration's own UPDATE statement (read from the file, not a copy)
against hand-placed rows with explicit timestamps, so each case is decided by
the data rather than by when the test happened to run. The migration lives
outside the backend image; run with the repo's `supabase/` mounted at
`/supabase` (see the U2 unit report) or from the repo on the host.
"""

from __future__ import annotations

import re
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import TaskApprovalDecision, TaskProgressUpdate, TaskVerification

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "202609250002_v2_task_progress_reviewed_at.sql"

PROJECT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 20, hour, minute)


def backfill_statement() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"^update siteops_v2\.task_progress_updates.*?;", sql, flags=re.S | re.M)
    if match is None:
        raise AssertionError("backfill UPDATE not found in the migration")
    return match.group(0)


class ReviewedAtBackfillTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (TaskProgressUpdate.__table__, TaskVerification.__table__, TaskApprovalDecision.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    # ---- fixtures ---------------------------------------------------------

    def update(self, session, task_id, created, reviewed=None) -> uuid.UUID:
        row = TaskProgressUpdate(
            task_id=task_id, project_id=PROJECT_ID, update_type="note", note="n", submitted_by=USER_ID,
            source="portal", created_at=created, reviewed_at=reviewed,
        )
        session.add(row)
        session.flush()
        return row.id

    def verification(self, session, task_id, update_id, decided, decision="rejected") -> None:
        session.add(TaskVerification(
            task_id=task_id, submission_update_id=update_id, decision=decision, verified_by=USER_ID, verified_at=decided,
        ))

    def approval(self, session, task_id, decided, decision="rejected") -> None:
        session.add(TaskApprovalDecision(task_id=task_id, decision=decision, decided_by=USER_ID, decided_at=decided))

    def run_backfill(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(backfill_statement()))

    def reviewed_at(self, update_id):
        with self.Session() as session:
            return session.scalar(select(TaskProgressUpdate.reviewed_at).where(TaskProgressUpdate.id == update_id))

    # ---- cases -------------------------------------------------------------

    def test_rejected_cycle_is_reviewed_and_the_newer_update_is_not(self):
        task = uuid.uuid4()
        with self.Session.begin() as session:
            first = self.update(session, task, at(9))
            second = self.update(session, task, at(10))
            self.verification(session, task, second, at(11))
            current = self.update(session, task, at(12))
        self.run_backfill()

        self.assertEqual(self.reviewed_at(first), at(11))
        self.assertEqual(self.reviewed_at(second), at(11))
        self.assertIsNone(self.reviewed_at(current))

    def test_each_update_takes_the_first_decision_at_or_after_it(self):
        task = uuid.uuid4()
        with self.Session.begin() as session:
            cycle_one = self.update(session, task, at(9))
            self.verification(session, task, cycle_one, at(10))
            cycle_two = self.update(session, task, at(11))
            self.verification(session, task, cycle_two, at(12))
        self.run_backfill()

        self.assertEqual(self.reviewed_at(cycle_one), at(10))
        self.assertEqual(self.reviewed_at(cycle_two), at(12))

    def test_task_with_no_decisions_keeps_every_update_unreviewed(self):
        task = uuid.uuid4()
        with self.Session.begin() as session:
            ids = [self.update(session, task, at(9)), self.update(session, task, at(10))]
        self.run_backfill()
        self.assertEqual([self.reviewed_at(i) for i in ids], [None, None])

    def test_update_in_the_same_instant_as_a_decision_counts_as_reviewed(self):
        task = uuid.uuid4()
        with self.Session.begin() as session:
            same_instant = self.update(session, task, at(10))
            self.verification(session, task, same_instant, at(10))
        self.run_backfill()
        self.assertEqual(self.reviewed_at(same_instant), at(10))

    def test_pm_decisions_close_cycles_too(self):
        """class_a PM rejection and approval-gate rejection name no update;
        the old consumed-by-verification rule missed them entirely."""
        class_a, gate = uuid.uuid4(), uuid.uuid4()
        with self.Session.begin() as session:
            verified = self.update(session, class_a, at(9))
            self.verification(session, class_a, verified, at(10), decision="verified")
            self.approval(session, class_a, at(11))
            after_pm = self.update(session, class_a, at(12))

            gate_update = self.update(session, gate, at(9))
            self.approval(session, gate, at(10))
        self.run_backfill()

        self.assertEqual(self.reviewed_at(verified), at(10))
        self.assertIsNone(self.reviewed_at(after_pm))
        self.assertEqual(self.reviewed_at(gate_update), at(10))

    def test_other_tasks_decisions_are_ignored(self):
        task, other = uuid.uuid4(), uuid.uuid4()
        with self.Session.begin() as session:
            mine = self.update(session, task, at(9))
            theirs = self.update(session, other, at(8))
            self.verification(session, other, theirs, at(10))
        self.run_backfill()
        self.assertIsNone(self.reviewed_at(mine))

    def test_already_marked_rows_are_left_alone_and_rerun_is_harmless(self):
        task = uuid.uuid4()
        with self.Session.begin() as session:
            premarked = self.update(session, task, at(9), reviewed=at(9, 30))
            later = self.update(session, task, at(9, 45))
            self.verification(session, task, later, at(10))
        self.run_backfill()
        self.run_backfill()
        self.assertEqual(self.reviewed_at(premarked), at(9, 30))
        self.assertEqual(self.reviewed_at(later), at(10))


if __name__ == "__main__":
    unittest.main()
