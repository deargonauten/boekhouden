import asyncio
import imaplib
import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.background import (
    run_email_poller,
    start_email_poller,
    stop_email_poller,
)
from app.config import Settings
from app.domain.email_intake import EmailIntakeError
from app.domain.email_intake.errors import EmailLoginFailedError
from app.main import create_app

LOGGER = "app.email_intake"


class FakeRunner:
    """Stands in for IntakeRunner: each call pops the next outcome.

    An outcome that is an exception instance is raised; anything else is
    returned as the run result.
    """

    def __init__(self, outcomes=None, delay=0.0):
        self.outcomes = list(outcomes or [])
        self.delay = delay
        self.calls = 0
        self.last_report = None

    def run_now(self):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if not self.outcomes:
            return "ok"
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def login_error() -> EmailIntakeError:
    return EmailLoginFailedError(
        "Inloggen bij de mailbox is mislukt. Controleer gebruikersnaam en "
        "wachtwoord in je .env-bestand."
    )


def imap_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        _env_file=None,
        database_path=tmp_path / "data" / "test.db",
        documents_dir=tmp_path / "data" / "documents",
        bank_dir=tmp_path / "data" / "bank",
        imap_host="imap.example.test",
        imap_user="facturen@example.test",
        imap_password="geheim-wachtwoord-123",
        imap_poll_interval_minutes=5,
    )
    values.update(overrides)
    return Settings(**values)


def app_with(settings: Settings, runner) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.email_runner = runner
    return app


# --- run loop -------------------------------------------------------------


def test_loop_repeats_after_each_run(caplog):
    runner = FakeRunner()

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 0.01, first_delay_seconds=0)
        )
        for _ in range(200):
            if runner.calls >= 3:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert runner.calls >= 3


def test_loop_waits_before_first_run():
    runner = FakeRunner()

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 0.01, first_delay_seconds=0.2)
        )
        await asyncio.sleep(0.05)
        calls_during_delay = runner.calls
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return calls_during_delay

    assert asyncio.run(scenario()) == 0


def test_error_does_not_kill_the_loop(caplog):
    runner = FakeRunner(outcomes=[login_error(), RuntimeError("boem"), "ok"])
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 0.01, first_delay_seconds=0)
        )
        for _ in range(200):
            if runner.calls >= 5:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert runner.calls >= 5


def test_same_error_is_logged_once_until_it_changes(caplog):
    same = [login_error() for _ in range(3)]
    runner = FakeRunner(outcomes=[*same, "ok", login_error()])
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 0.005, first_delay_seconds=0)
        )
        for _ in range(400):
            if runner.calls >= 6:
                break
            await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    login_logs = [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]
    # Three identical failures -> one log line; a success resets, so the
    # next failure is logged again.
    assert len(login_logs) == 2
    assert all("Inloggen" in r.getMessage() for r in login_logs)


def test_error_message_does_not_leak_password(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    runner = FakeRunner(outcomes=[login_error()])

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 1, first_delay_seconds=0)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert "geheim-wachtwoord-123" not in caplog.text


def test_unexpected_exception_is_logged_by_type_only(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    runner = FakeRunner(outcomes=[ValueError("bevat geheim-wachtwoord-123")])

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 1, first_delay_seconds=0)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert runner.calls == 1
    assert "ValueError" in caplog.text
    assert "geheim-wachtwoord-123" not in caplog.text


# --- start / stop ---------------------------------------------------------


def test_no_task_when_interval_is_zero(tmp_path):
    settings = imap_settings(tmp_path, imap_poll_interval_minutes=0)
    runner = FakeRunner()

    async def scenario():
        return start_email_poller(app_with(settings, runner))

    assert asyncio.run(scenario()) is None


def test_no_task_when_mailbox_not_configured(tmp_path):
    settings = imap_settings(tmp_path, imap_host=None)
    runner = FakeRunner()

    async def scenario():
        return start_email_poller(app_with(settings, runner))

    assert asyncio.run(scenario()) is None


def test_task_starts_when_configured_with_interval(tmp_path):
    settings = imap_settings(tmp_path, imap_poll_interval_minutes=1)
    runner = FakeRunner()

    async def scenario():
        task = start_email_poller(app_with(settings, runner))
        assert isinstance(task, asyncio.Task)
        await stop_email_poller(task)
        return task

    task = asyncio.run(scenario())
    assert task.cancelled()


def test_stop_returns_quickly_while_a_run_is_in_progress(tmp_path):
    runner = FakeRunner(delay=0.3)

    async def scenario():
        task = asyncio.create_task(
            run_email_poller(runner, 0.01, first_delay_seconds=0)
        )
        await asyncio.sleep(0.05)  # run_now is now blocking in its thread
        started = time.monotonic()
        await stop_email_poller(task)
        return time.monotonic() - started

    elapsed = asyncio.run(scenario())
    assert elapsed < 0.25


def test_stop_accepts_none():
    asyncio.run(stop_email_poller(None))


# --- app wiring -----------------------------------------------------------


def test_create_app_without_mailbox_never_connects(test_settings, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("geen netwerkverbinding in tests")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", forbidden)
    app = create_app(test_settings)
    assert app.state.email_runner is not None
    with TestClient(app):
        pass


def test_lifespan_runs_poller_and_cancels_it_on_shutdown(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("geen netwerkverbinding in tests")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", forbidden)
    settings = imap_settings(tmp_path, imap_poll_interval_minutes=1)
    app = create_app(settings)
    runner = FakeRunner()
    app.state.email_runner = runner

    with TestClient(app):
        task = app.state.email_poller
        assert isinstance(task, asyncio.Task)
        assert not task.done()

    # The first run waits 10 seconds after start; leaving early means no run.
    assert runner.calls == 0
    assert task.done()


def test_lifespan_without_interval_has_no_poller(tmp_path):
    settings = imap_settings(tmp_path, imap_poll_interval_minutes=0)
    app = create_app(settings)
    with TestClient(app):
        assert app.state.email_poller is None
