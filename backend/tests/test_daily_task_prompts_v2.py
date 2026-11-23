"""Plan Phase 6 (second half): `EscalationService.emit_gate_due_reminders`
(the gate due-date reminder, added to `escalation.py` in this same phase for
cohesion with the rest of that module's `ProjectExternalApproval` handling).
The task reminders that used to live here are covered by
test_task_reminders.py.

Mirrors `test_escalation_v2.py`'s SQLite in-memory harness (ATTACHed
`siteops_v2` schema) closely - real `Task`/`ProjectExternalApproval` rows
built directly, an explicit `now` passed to every call, no HTTP/baseline-
lock flow needed.

Covers, for each of the five methods:
- happy path: a qualifying task/approval gets its event emitted.
- a non-qualifying task/approval is skipped.
- same-day idempotency: calling the same method twice with two different
  `now` values on the SAME calendar date does not double-emit; calling
  again with `now` on the NEXT calendar date DOES emit again.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    OutboxEvent,
    ProjectExternalApproval,
    Task,
    TaskProgressUpdate,
)
from app.models import User, UserRole
from app.project_models import V2Project
from app.services.escalation import EscalationService
from app.template_models import V2Template, V2TemplateVersion


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
ASSIGNEE_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


class DailyTaskPromptsAndGateReminderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            Task.__table__,
            TaskProgressUpdate.__table__,
            ProjectExternalApproval.__table__,
            OutboxEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.project_id = uuid.uuid4()
        self.today = date(2026, 8, 20)
        self.now = datetime(2026, 8, 20, 9, 0, 0, tzinfo=timezone.utc)
        # Inside the configured midday/EOD windows (settings.
        # daily_task_prompts_midday_hour_utc/eod_hour_utc) - emit_midday_checks
        # and emit_eod_checks only actually fire once `now.hour` reaches
        # these, so tests exercising them use these instead of `self.now`.
        self.midday_now = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
        self.eod_now = datetime(2026, 8, 20, 18, 0, 0, tzinfo=timezone.utc)

        with self.Session.begin() as session:
            session.add(User(id=ADMIN_ID, name="Admin", email="admin@example.com", role=UserRole.admin, active=True))
            session.add(User(
                id=ASSIGNEE_ID, name="Assignee", email="assignee@example.com",
                role=UserRole.project_manager, active=True,
            ))
            session.add(V2Project(
                id=self.project_id, code="PRJ-1", name="Project 1", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=ADMIN_ID,
            ))

    def tearDown(self):
        self.engine.dispose()

    # ---- fixtures --------------------------------------------------------

    def make_task(self, session, code: str, **overrides) -> Task:
        defaults = dict(
            id=uuid.uuid4(), project_id=self.project_id,
            baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
            original_code=code, template_sequence=1, title=f"Task {code}",
            schedule_classification="execution", applicability="mandatory",
            lifecycle_status="planned", planned_start_date=self.today,
            created_at=self.now - timedelta(hours=48),
        )
        defaults.update(overrides)
        task = Task(**defaults)
        session.add(task)
        return task

    def make_approval(self, session, **overrides) -> ProjectExternalApproval:
        defaults = dict(
            id=uuid.uuid4(), project_id=self.project_id, project_gate_id=uuid.uuid4(),
            status="assigned", assigned_to_user_id=ASSIGNEE_ID, assigned_by=ADMIN_ID,
            assigned_at=self.now - timedelta(days=2),
            due_at=self.today + timedelta(days=1),
        )
        defaults.update(overrides)
        approval = ProjectExternalApproval(**defaults)
        session.add(approval)
        return approval

    def outbox_events(self, session, event_type: str, aggregate_id: uuid.UUID) -> list[OutboxEvent]:
        return list(session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == event_type, OutboxEvent.aggregate_id == aggregate_id,
            )
        ).all())

    # ---- EscalationService.emit_gate_due_reminders --------------------------

    def test_approval_due_tomorrow_gets_reminder(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session, due_at=self.today + timedelta(days=1))
        approval_id = approval.id

        with self.Session() as session:
            result = EscalationService(session).emit_gate_due_reminders(self.now)
        self.assertEqual([a.id for a in result], [approval_id])

        with self.Session() as session:
            events = self.outbox_events(session, "project_external_approval.due_reminder", approval_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].aggregate_type, "project_external_approval")
            self.assertEqual(events[0].payload["approval_id"], str(approval_id))

    def test_approval_due_in_three_days_is_not_flagged(self):
        with self.Session.begin() as session:
            self.make_approval(session, due_at=self.today + timedelta(days=3))

        with self.Session() as session:
            result = EscalationService(session).emit_gate_due_reminders(self.now)
        self.assertEqual(result, [])

    def test_unassigned_approval_due_tomorrow_is_not_flagged(self):
        with self.Session.begin() as session:
            self.make_approval(
                session, due_at=self.today + timedelta(days=1),
                status="submitted", decided_by=None, decided_at=None,
            )

        with self.Session() as session:
            result = EscalationService(session).emit_gate_due_reminders(self.now)
        self.assertEqual(result, [])

    def test_gate_due_reminder_same_day_idempotent_next_day_emits_again(self):
        with self.Session.begin() as session:
            approval = self.make_approval(session, due_at=self.today + timedelta(days=1))
        approval_id = approval.id

        with self.Session() as session:
            first = EscalationService(session).emit_gate_due_reminders(self.now)
        with self.Session() as session:
            second = EscalationService(session).emit_gate_due_reminders(self.now + timedelta(hours=6))
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

        with self.Session() as session:
            self.assertEqual(
                len(self.outbox_events(session, "project_external_approval.due_reminder", approval_id)), 1,
            )

        # The next calendar day, the approval's due_at is no longer
        # "tomorrow" relative to `now` - update due_at forward so the
        # qualifying condition is still true a day later, proving the
        # idempotency key (not the underlying condition) was what blocked
        # the second same-day call.
        with self.Session() as session:
            approval = session.get(ProjectExternalApproval, approval_id)
            approval.due_at = self.today + timedelta(days=2)
            session.add(approval)
            session.commit()

        next_day = self.now + timedelta(days=1)
        with self.Session() as session:
            third = EscalationService(session).emit_gate_due_reminders(next_day)
        self.assertEqual([a.id for a in third], [approval_id])

        with self.Session() as session:
            self.assertEqual(
                len(self.outbox_events(session, "project_external_approval.due_reminder", approval_id)), 2,
            )


if __name__ == "__main__":
    unittest.main()
