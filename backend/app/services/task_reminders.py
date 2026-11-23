"""Scheduled task reminders on Indian Standard Time.

Replaces the four UTC daily prompts. Every reminder has a fixed Asia/Kolkata
send time, a latest time it may still go out (a pass that runs after that is
too late for it to make sense), the tasks it concerns, and the task states
that mute it:

  reminder           IST window     tasks                                  event
  prestart_warning   09:00-13:00    start tomorrow, planned/ready          task.prestart_warning
  readiness_check    18:30-23:59    start tomorrow, planned/ready          task.readiness_check
  start_check        09:00-13:00    start today, planned/ready             task.start_check
  midday_check       13:30-18:00    in progress, no open blocker           task.midday_check
  eod_check          18:30-23:59    in progress, no open blocker           task.eod_check
  sla_overdue        06:30-12:00    due yesterday (EOD + 12h), still in    task.sla_overdue
                                    progress or rework, no open blocker
  sla_escalation     09:30-18:00    due yesterday (EOD + 15h), same        task.sla_escalated

"Today" is always the Asia/Kolkata calendar date of the pass's own `now`,
never UTC and never the server's local clock. IST has no daylight saving, so
a fixed +05:30 offset is exact (and needs no tz database on the server).
Task dates are plain DATE columns, so comparing them with that IST date is
the same as the SQL `(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date`,
while keeping `now` injectable for tests.

At most once: before a reminder's outbox event is written, a
`TaskReminderLog` row (task, reminder, IST date) is inserted in the same
transaction. Its unique key turns a repeat - another pass, another server,
a retry - into an IntegrityError (Postgres 23505) that is rolled back and
skipped, so nothing is sent twice. Delivery then goes through the outbox like
every other message.

Only active projects and non-milestone tasks are considered. Recipients are
decided by dispatch, not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.execution_models import Task, TaskBlocker, TaskReminderLog
from app.project_models import V2Project
from app.services.outbox import OutboxService

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30), "IST")

NOT_STARTED = ("planned", "ready")
IN_PROGRESS = ("in_progress",)
# Work still on the executor: not submitted, verified, approved, completed or
# cancelled. `rejected` is rework.
STILL_OPEN = ("in_progress", "rejected")


@dataclass(frozen=True)
class Reminder:
    reminder_type: str
    event_type: str
    send_at: time
    last_at: time
    statuses: tuple[str, ...]
    # Which task date the reminder is about, relative to IST today: +1 =
    # starts tomorrow, 0 = starts today, -1 = was due yesterday. None = every
    # day while the task is in `statuses`.
    anchor: str | None = None
    days_from_today: int = 0
    mute_when_blocked: bool = False


REMINDERS = (
    Reminder("prestart_warning", "task.prestart_warning", time(9, 0), time(13, 0), NOT_STARTED, "planned_start_date", 1),
    Reminder("readiness_check", "task.readiness_check", time(18, 30), time(23, 59, 59), NOT_STARTED, "planned_start_date", 1),
    Reminder("start_check", "task.start_check", time(9, 0), time(13, 0), NOT_STARTED, "planned_start_date", 0),
    Reminder("midday_check", "task.midday_check", time(13, 30), time(18, 0), IN_PROGRESS, mute_when_blocked=True),
    Reminder("eod_check", "task.eod_check", time(18, 30), time(23, 59, 59), IN_PROGRESS, mute_when_blocked=True),
    Reminder("sla_overdue", "task.sla_overdue", time(6, 30), time(12, 0), STILL_OPEN, "planned_end_date", -1, True),
    Reminder("sla_escalation", "task.sla_escalated", time(9, 30), time(18, 0), STILL_OPEN, "planned_end_date", -1, True),
)


def ist_now(now: datetime) -> datetime:
    """`now` as Asia/Kolkata wall-clock time. A naive `now` is taken as UTC."""
    aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return aware.astimezone(IST)


class TaskReminderService:
    def __init__(self, db: Session):
        self.db = db

    def send_due_reminders(self, now: datetime) -> list[tuple[str, Task]]:
        """Every reminder whose IST window contains `now`, for every task it
        concerns and that was not already reminded today. Returns
        (reminder_type, task) for each reminder newly queued."""
        local = ist_now(now)
        queued: list[tuple[str, Task]] = []
        for reminder in REMINDERS:
            if not (reminder.send_at <= local.time() <= reminder.last_at):
                continue
            for task, scheduled_for in self._due_tasks(reminder, local.date()):
                if self._queue(reminder, task, scheduled_for):
                    queued.append((reminder.reminder_type, task))
        return queued

    def _due_tasks(self, reminder: Reminder, today: date) -> list[tuple[Task, date]]:
        query = (
            select(Task)
            .join(V2Project, V2Project.id == Task.project_id)
            .where(
                V2Project.status == "active",
                Task.lifecycle_status.in_(reminder.statuses),
                or_(Task.task_kind.is_(None), Task.task_kind != "milestone"),
            )
        )
        target = today + timedelta(days=reminder.days_from_today)
        if reminder.anchor is not None:
            query = query.where(getattr(Task, reminder.anchor) == target)
        if reminder.mute_when_blocked:
            query = query.where(~exists().where(TaskBlocker.task_id == Task.id, TaskBlocker.resolved_at.is_(None)))
        tasks = self.db.scalars(query.order_by(Task.project_id, Task.template_sequence)).all()
        # A dated reminder belongs to its task date; a daily check to today.
        return [(task, target if reminder.anchor is not None else today) for task in tasks]

    def _queue(self, reminder: Reminder, task: Task, scheduled_for: date) -> bool:
        """Log first, then the outbox event, in one transaction. A duplicate
        log row means this reminder already went out: nothing is written."""
        try:
            self.db.add(TaskReminderLog(
                task_id=task.id, reminder_type=reminder.reminder_type, scheduled_for_date=scheduled_for,
            ))
            self.db.flush()
            event = OutboxService(self.db).emit(
                event_type=reminder.event_type,
                aggregate_type="task",
                aggregate_id=task.id,
                payload={
                    "task_id": str(task.id),
                    "project_id": str(task.project_id),
                    "lifecycle_status": task.lifecycle_status,
                    "planned_start_date": task.planned_start_date.isoformat() if task.planned_start_date else None,
                    "planned_end_date": task.planned_end_date.isoformat() if task.planned_end_date else None,
                    "reminder_type": reminder.reminder_type,
                    "scheduled_for_date": scheduled_for.isoformat(),
                },
                idempotency_key=f"task:{task.id}:{reminder.event_type}:{scheduled_for.isoformat()}",
            )
            self.db.commit()
            # None: an event with this key already exists (e.g. sent by the
            # previous scheduler earlier today) - logged, nothing new sent.
            return event is not None
        except IntegrityError:
            # 23505 on the reminder log (or the outbox key): already sent.
            self.db.rollback()
            return False
        except Exception:
            logger.exception(
                "Failed to queue %s for task %s (project %s); skipping it.",
                reminder.reminder_type, task.id, task.project_id,
            )
            self.db.rollback()
            return False
