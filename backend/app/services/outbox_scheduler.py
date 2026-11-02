"""U3 (R18): drains the outbox on a schedule.

`OutboxService.emit` has written a pending `OutboxEvent` for every mutation
since Phase 2, and `MessageDispatchService.process_pending` has always known
how to deliver them - but nothing ever called it outside a test. The events
accumulated forever and no notification the system decided to send was ever
attempted.

This module is the missing caller and nothing more. It changes nothing about
what is emitted, nothing about who resolves as a recipient, and nothing about
where a message goes.

The adapter is chosen per pass by `_build_adapter`: `MetaCloudApiAdapter` once
real credentials (`WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID`) are
configured, `SandboxProviderAdapter` (no network call, no credentials) until
then - so going live is an operator setting real env vars, not a redeploy.
Flipping this on for the first time still delivers the whole accumulated
backlog at once, for work that happened weeks ago - see
`app/scripts/clear_whatsapp_backlog.py`, meant to run immediately before that
first real cutover.

Kept out of `main.py` so a pass and the loop's failure isolation can both be
tested directly, rather than by standing up an app and waiting on wall-clock
timers.
"""

import asyncio
import logging

from app.config import settings
from app.database import SessionLocal
from app.services.message_dispatch import MessageDispatchService, SandboxProviderAdapter, WhatsAppProviderAdapter
from app.services.whatsapp_provider import MetaCloudApiAdapter

logger = logging.getLogger(__name__)

TASK_ATTRIBUTE = "outbox_dispatch_task"


def _build_adapter() -> WhatsAppProviderAdapter:
    if settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
        return MetaCloudApiAdapter()
    return SandboxProviderAdapter()


def run_dispatch_pass() -> int:
    """One dispatch pass, in its own session.

    A session per run rather than one shared across the process lifetime: a
    long-lived session holds a connection open between passes for no reason
    and would carry a failed pass's dirty state into the next one.
    `process_pending` commits per event, so a pass that dies partway leaves
    the events it already finished committed and the rest still pending.
    """
    with SessionLocal() as db:
        return MessageDispatchService(db, adapter=_build_adapter()).process_pending()


async def dispatch_loop(interval_seconds: float, runner=run_dispatch_pass) -> None:
    """Runs dispatch passes forever, until cancelled.

    Sleeps BEFORE the first pass so application startup never waits on the
    database, and so a boot loop cannot turn into a dispatch loop.

    Every failure mode other than cancellation is swallowed and logged. A
    dispatcher that dies on the first bad row stops delivering everything
    behind it, silently, for as long as the process stays up - which is the
    same failure this unit exists to end. Cancellation is re-raised because
    it is how shutdown asks the loop to stop, not an error.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # Off the event loop: `process_pending` is blocking SQLAlchemy,
            # and running it inline would stall every request handler for the
            # duration of the pass.
            processed = await asyncio.to_thread(runner)
            if processed:
                logger.info("Outbox dispatch pass processed %s event(s).", processed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox dispatch pass failed; the schedule continues.")


def start_dispatcher(app) -> bool:
    """Starts the loop as a background task. Returns whether it started.

    Must be called from async context - it needs a running event loop to
    attach the task to.
    """
    if not settings.outbox_dispatch_enabled:
        logger.info("Outbox dispatcher is disabled by configuration; events will accumulate.")
        return False
    if not (settings.whatsapp_access_token and settings.whatsapp_phone_number_id):
        # The sandbox adapter marks every delivery 'sent' without contacting
        # Meta, so without this a missing credential looks like a healthy
        # system in the UI.
        logger.warning(
            "WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set: WhatsApp messages are NOT being "
            "sent - the sandbox adapter only records them as sent."
        )
    task = asyncio.create_task(dispatch_loop(settings.outbox_dispatch_interval_seconds))
    setattr(app.state, TASK_ATTRIBUTE, task)
    return True


async def stop_dispatcher(app) -> None:
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
