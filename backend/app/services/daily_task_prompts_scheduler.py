"""Plan Phase 6 (second half): runs the task reminders and the task-side
escalation sweep in one pass, mirroring `outbox_scheduler.py`'s shape
exactly - see that module's docstring for the shape's own rationale.

Merged on purpose, not split into two files: the plan's own framing is that
the reminders (`TaskReminderService.send_due_reminders`, Asia/Kolkata times) and the task-side escalation sweep
(`EscalationService.sweep_task_followups`/`sweep_task_escalations`) are the
same "what does this task need right now" pass over the same task set, so
one scheduler captures `now` once and threads that single instant through
every call in the pass rather than reading the clock fresh per call.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal
from app.services.escalation import EscalationService
from app.services.task_reminders import TaskReminderService

logger = logging.getLogger(__name__)

TASK_ATTRIBUTE = "daily_task_prompts_task"


def run_daily_task_prompts_pass() -> int:
    """One pass, in its own session - see outbox_scheduler.py's
    `run_dispatch_pass` for why a pass owns its own session rather than
    sharing one across the process lifetime.

    `now` is captured once here and threaded through every call in this
    pass, so a readiness check and the task-escalation sweep that follows
    it in the same pass reason about the exact same instant rather than two
    clock reads that could straddle a day boundary. Returns the total
    number of tasks that had an event emitted across all three calls.

    Each call is isolated from the others: one call raising (a bug, a
    transient DB error) is logged and skipped rather than aborting the rest
    of the pass - without this, a failure in the reminders would silently
    also skip both escalation sweeps for that entire tick.
    """
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        reminders = TaskReminderService(db)
        escalation = EscalationService(db)
        processed = 0
        for label, call in (
            # every IST task reminder (pre-start, readiness,
            # start, midday, EOD, overdue, escalation).
            ("send_due_reminders", lambda: reminders.send_due_reminders(now)),
            ("sweep_task_followups", lambda: escalation.sweep_task_followups(now)),
            ("sweep_task_escalations", lambda: escalation.sweep_task_escalations(now)),
        ):
            try:
                processed += len(call())
            except Exception:
                logger.exception("Daily task prompts pass: %s failed; continuing with the rest of the pass.", label)
                db.rollback()
        return processed


async def daily_task_prompts_loop(interval_seconds: float, runner=run_daily_task_prompts_pass) -> None:
    """Sleeps before the first pass so application startup never waits on
    the database. Every failure mode other than cancellation is swallowed
    and logged, so one bad pass never ends the schedule."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # Off the event loop: this pass is blocking SQLAlchemy, and
            # running it inline would stall every request handler for the
            # duration of the pass.
            processed = await asyncio.to_thread(runner)
            if processed:
                logger.info("Daily task prompts pass processed %s event(s).", processed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily task prompts pass failed; the schedule continues.")


def start_daily_task_prompts_scheduler(app) -> bool:
    """Starts the loop as a background task. Returns whether it started.

    Must be called from async context - it needs a running event loop to
    attach the task to.
    """
    if not settings.daily_task_prompts_enabled:
        logger.info("Daily task prompts scheduler is disabled by configuration; prompts will never fire.")
        return False
    task = asyncio.create_task(daily_task_prompts_loop(settings.daily_task_prompts_interval_seconds))
    setattr(app.state, TASK_ATTRIBUTE, task)
    return True


async def stop_daily_task_prompts_scheduler(app) -> None:
    """Cancels the loop and waits for it to finish.

    Without this a reload or a test that builds an app leaves the task
    running against a closed loop, which surfaces later as an unrelated and
    very confusing warning.
    """
    task = getattr(app.state, TASK_ATTRIBUTE, None)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    setattr(app.state, TASK_ATTRIBUTE, None)
