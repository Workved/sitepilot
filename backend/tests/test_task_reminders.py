"""Scheduled task reminders on Asia/Kolkata time
(app/services/task_reminders.py) and who receives them (message_dispatch.py).
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
    FileObject,
    InboundMessage,
    OutboxEvent,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskDependency,
    TaskEvidence,
    TaskProgressUpdate,
    TaskReadinessDeclaration,
    TaskReminderLog,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.message_dispatch import MessageDispatchService
from app.services.task_reminders import IST, TaskReminderService
from app.template_models import V2TemplateVersion  # noqa: F401 - FK target for V2Project
from app.vendor_models import TaskVendorAssignment, V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


TODAY = date(2026, 9, 28)


def ist(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


class ReminderHarness(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__, ProjectExternalApproval.__table__, ProjectExternalApprovalTask.__table__,
            Task.__table__, TaskDependency.__table__, TaskSupportAssignment.__table__, TaskVerification.__table__,
            TaskApprovalDecision.__table__, V2AuditEvent.__table__, OutboxEvent.__table__, InboundMessage.__table__,
            V2VendorContact.__table__, TaskProgressUpdate.__table__, TaskEvidence.__table__, FileObject.__table__,
            TaskBlocker.__table__, TaskReminderLog.__table__, TaskReadinessDeclaration.__table__,
            TaskDelayEvent.__table__, TaskVendorAssignment.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()

        with self.session.begin():
            self.admin = self._person("Niddhi", UserRole.admin)
            self.supervisor = self._person("Deepak", UserRole.supervisor)
            self.employee = self._person("Rohan", UserRole.internal_employee)
            self.pm = self._person("Prachit", UserRole.project_manager)

            self.project = self._project("PRJ-A")
            self.other_project = self._project("PRJ-B")
            self._member(self.project, self.supervisor, "site_supervisor")
            self._member(self.project, self.pm, "project_manager")
            self._member(self.other_project, self.supervisor, "site_supervisor")
            self._member(self.project, self.employee, "internal_employee")

            yesterday = date.today() - timedelta(days=1)
            self.task = self._task(self.project, "T001", "planned", yesterday)
            self.session.add(TaskSupportAssignment(
                task_id=self.task.id, project_id=self.project.id, employee_id=self.employee[1].id,
                responsibility="Execution", assigned_by=self.supervisor[0].id,
            ))

    def tearDown(self):
        self.session.close()

    def _person(self, name, role):
        user = User(
            id=uuid.uuid4(), name=name, email=f"{name.lower()}@example.com", phone="+919000000000",
            role=role, active=True,
        )
        self.session.add(user)
        self.session.flush()
        profile = EmployeeProfile(user_id=user.id, employee_code=f"E-{name}", designation=name, availability="available")
        self.session.add(profile)
        self.session.flush()
        return user, profile

    def _project(self, code):
        project = V2Project(
            code=code, name=code, client_name="Client", site_address="Site", start_date=date(2026, 9, 1),
            status="active", created_by=self.admin[0].id,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def _member(self, project, person, role):
        self.session.add(V2ProjectMembership(
            project_id=project.id, employee_id=person[1].id, project_role=role, assigned_by=self.admin[0].id,
            assignment_reason="seed",
        ))

    def _task(self, project, code, status, planned_start):
        task = Task(
            project_id=project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(), original_code=code,
            template_sequence=1, title=f"Task {code}", schedule_classification="execution", applicability="mandatory",
            task_kind="work", lifecycle_status=status, planned_start_date=planned_start,
        )
        self.session.add(task)
        self.session.flush()
        return task

    def make_task(self, code, status="planned", start=None, end=None, project=None, **extra) -> Task:
        with self.session.begin():
            task = self._task(project or self.project, code, status, start)
            task.planned_end_date = end
            for key, value in extra.items():
                setattr(task, key, value)
        return task

    def run_at(self, when: datetime) -> list[tuple[str, str]]:
        sent = TaskReminderService(self.session).send_due_reminders(when)
        return [(reminder, task.original_code) for reminder, task in sent]

    def events(self, event_type: str) -> list[OutboxEvent]:
        self.session.expire_all()
        return list(self.session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == event_type)))


class ReminderScheduleTests(ReminderHarness):
    def test_times_are_indian_standard_time_not_utc(self):
        self.make_task("S1", start=TODAY)
        # 03:29 UTC is 08:59 IST - too early; 03:30 UTC is 09:00 IST.
        self.assertEqual(self.run_at(datetime(2026, 9, 28, 3, 29, tzinfo=timezone.utc)), [])
        self.assertEqual(self.run_at(datetime(2026, 9, 28, 3, 30, tzinfo=timezone.utc)), [("start_check", "S1")])

    def test_the_ist_date_decides_today_across_the_utc_midnight(self):
        # 20:00 UTC on the 27th is 01:30 IST on the 28th: a task starting on
        # the 28th is "today", not "tomorrow".
        self.make_task("S1", start=TODAY)
        self.make_task("S2", start=TODAY + timedelta(days=1))
        sent = self.run_at(datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc) + timedelta(hours=13))  # 14:30 IST 28th
        self.assertEqual(sent, [])  # nothing is scheduled at 14:30 for not-started tasks
        self.assertEqual(self.run_at(ist(9, 5)), [("prestart_warning", "S2"), ("start_check", "S1")])

    def test_day_before_start_gets_the_warning_in_the_morning_and_the_readiness_check_in_the_evening(self):
        self.make_task("S1", start=TODAY + timedelta(days=1))
        self.assertEqual(self.run_at(ist(9, 0)), [("prestart_warning", "S1")])
        self.assertEqual(self.run_at(ist(18, 30)), [("readiness_check", "S1")])
        [readiness] = self.events("task.readiness_check")
        self.assertEqual(readiness.payload["scheduled_for_date"], (TODAY + timedelta(days=1)).isoformat())

    def test_start_check_is_muted_once_the_task_has_started(self):
        self.make_task("S1", status="in_progress", start=TODAY)
        self.make_task("S2", status="ready", start=TODAY)
        self.assertEqual(self.run_at(ist(9, 0)), [("start_check", "S2")])

    def test_a_reminder_is_not_sent_after_its_window(self):
        self.make_task("S1", start=TODAY)
        self.assertEqual(self.run_at(ist(13, 1)), [])

    def test_midday_and_eod_go_to_in_progress_work_only(self):
        self.make_task("W1", status="in_progress")
        self.make_task("W2", status="submitted")
        self.make_task("W3", status="completed")
        self.make_task("W4", status="cancelled")
        self.assertEqual(self.run_at(ist(13, 30)), [("midday_check", "W1")])
        self.assertEqual(self.run_at(ist(18, 30)), [("eod_check", "W1")])

    def test_open_blocker_mutes_midday_eod_and_overdue(self):
        task = self.make_task("W1", status="in_progress", end=TODAY - timedelta(days=1))
        with self.session.begin():
            self.session.add(TaskBlocker(
                task_id=task.id, project_id=self.project.id, type="Material", description="Tiles not delivered",
            ))
        for when in (ist(13, 30), ist(18, 30), ist(6, 30), ist(9, 30)):
            with self.subTest(when=when):
                self.assertEqual(self.run_at(when), [])

    def test_overdue_warning_at_0630_and_escalation_at_0930_the_day_after_it_was_due(self):
        self.make_task("W1", status="in_progress", end=TODAY - timedelta(days=1))
        self.make_task("W2", status="rejected", end=TODAY - timedelta(days=1))
        self.make_task("W3", status="submitted", end=TODAY - timedelta(days=1))
        self.make_task("W4", status="in_progress", end=TODAY)  # due today: not overdue yet
        self.assertEqual(self.run_at(ist(6, 29)), [])
        self.assertEqual(self.run_at(ist(6, 30)), [("sla_overdue", "W1"), ("sla_overdue", "W2")])
        self.assertEqual(
            [r for r in self.run_at(ist(9, 30)) if r[0] == "sla_escalation"],
            [("sla_escalation", "W1"), ("sla_escalation", "W2")],
        )

    def test_each_reminder_goes_out_at_most_once_a_day(self):
        self.make_task("W1", status="in_progress")
        self.assertEqual(self.run_at(ist(13, 30)), [("midday_check", "W1")])
        self.assertEqual(self.run_at(ist(13, 35)), [])
        self.assertEqual(self.run_at(ist(17, 55)), [])
        self.assertEqual(len(self.events("task.midday_check")), 1)
        # The next IST day is a new reminder.
        self.assertEqual(self.run_at(ist(13, 30, TODAY + timedelta(days=1))), [("midday_check", "W1")])
        self.assertEqual(len(self.session.scalars(select(TaskReminderLog)).all()), 2)

    def test_an_existing_log_row_blocks_the_send(self):
        task = self.make_task("W1", status="in_progress")
        with self.session.begin():
            self.session.add(TaskReminderLog(task_id=task.id, reminder_type="midday_check", scheduled_for_date=TODAY))
        self.assertEqual(self.run_at(ist(13, 30)), [])
        self.assertEqual(self.events("task.midday_check"), [])

    def test_inactive_projects_and_milestones_get_no_reminders(self):
        self.make_task("M1", status="in_progress", task_kind="milestone")
        with self.session.begin():
            self.session.get(type(self.other_project), self.other_project.id).status = "archived"
        self.make_task("A1", status="in_progress", project=self.other_project)
        self.assertEqual(self.run_at(ist(13, 30)), [])


class ReminderAudienceTests(ReminderHarness):
    def recipients(self, event_type: str) -> set:
        event = OutboxEvent(
            event_type=event_type, aggregate_type="task", aggregate_id=self.task.id,
            payload={"task_id": str(self.task.id), "project_id": str(self.project.id)},
            idempotency_key=str(uuid.uuid4()), status="pending",
        )
        return {r.employee_id for r in MessageDispatchService(self.session)._resolve_recipients(event)}

    def test_prestart_warning_goes_to_the_assignee_and_the_supervisor(self):
        self.assertEqual(self.recipients("task.prestart_warning"), {self.employee[1].id, self.supervisor[1].id})

    def test_overdue_warning_goes_to_the_assignee(self):
        self.assertEqual(self.recipients("task.sla_overdue"), {self.employee[1].id})

    def test_escalation_goes_to_the_pm_and_admins(self):
        self.assertEqual(self.recipients("task.sla_escalated"), {self.pm[1].id, self.admin[1].id})

    def test_start_check_keeps_its_audience(self):
        self.assertEqual(
            self.recipients("task.start_check"), {self.employee[1].id, self.supervisor[1].id, self.pm[1].id},
        )
