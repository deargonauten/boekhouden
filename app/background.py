"""Background polling of the factuurmailbox while the app runs.

The loop uses the same IntakeRunner as the "Nu ophalen" button, so the runner's
lock keeps a manual and an automatic run from overlapping. Errors never end the
loop; they are logged once per distinct error.
"""

import asyncio
import contextlib
import logging
from typing import Protocol

from fastapi import FastAPI

from app.domain.email_intake import EmailIntakeError

logger = logging.getLogger("app.email_intake")

FIRST_RUN_DELAY_SECONDS = 10


class _Runner(Protocol):
    def run_now(self): ...


def start_email_poller(app: FastAPI) -> asyncio.Task | None:
    """Start the poller task when a mailbox is configured and an interval is set.

    Must be called from a running event loop (the app lifespan).
    """
    settings = app.state.settings
    if not settings.imap_configured or settings.imap_poll_interval_minutes < 1:
        return None
    return asyncio.get_running_loop().create_task(
        run_email_poller(
            app.state.email_runner,
            settings.imap_poll_interval_minutes * 60,
        ),
        name="email-poller",
    )


async def stop_email_poller(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def run_email_poller(
    runner: _Runner,
    interval_seconds: float,
    *,
    first_delay_seconds: float = FIRST_RUN_DELAY_SECONDS,
) -> None:
    """Run the intake, then sleep the interval after each run (runs never overlap)."""
    last_error: tuple | None = None
    await asyncio.sleep(first_delay_seconds)
    while True:
        last_error = await _run_once(runner, last_error)
        await asyncio.sleep(interval_seconds)


async def _run_once(runner: _Runner, last_error: tuple | None) -> tuple | None:
    """Run one intake in a worker thread; return the error key, or None on success."""
    try:
        report = await asyncio.to_thread(runner.run_now)
    except asyncio.CancelledError:
        raise
    except EmailIntakeError as exc:
        key = ("intake", exc.code)
        if key != last_error:
            logger.warning("Automatisch ophalen mislukt: %s", exc.message)
        return key
    except Exception as exc:  # the loop must survive anything
        key = ("unexpected", type(exc).__name__)
        if key != last_error:
            # Exception text is not logged: it may echo server responses.
            logger.error(
                "Automatisch ophalen mislukt met een onverwachte fout (%s).",
                type(exc).__name__,
            )
        return key
    # The real runner reports connection-level failures as a returned report.
    if getattr(report, "status", None) == "fout":
        key = ("intake", getattr(report, "error_code", None))
        if key != last_error:
            logger.warning("Automatisch ophalen mislukt: %s", getattr(report, "error_message", None))
        return key
    return None
