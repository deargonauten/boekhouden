"""Single-flight runner shared by the Inbox button and the background poller."""

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.documents.storage import DocumentStorage
from app.domain.email_intake.errors import EMAIL_IMAP_ERROR, EmailImapError, EmailIntakeError
from app.domain.email_intake.mailbox import MailboxClient, build_mailbox
from app.domain.email_intake.service import Busy, IntakeReport, _now, run_intake

logger = logging.getLogger("app.email_intake")


class IntakeRunner:
    """`session_factory` returns a new Session per call (e.g. a sessionmaker bound to the engine)."""

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        mailbox_factory: Callable[[Settings], MailboxClient] = build_mailbox,
    ):
        self._settings = settings
        self._session_factory = session_factory
        self._mailbox_factory = mailbox_factory
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._last_report: IntakeReport | None = None

    @property
    def last_report(self) -> IntakeReport | None:
        with self._state_lock:
            return self._last_report

    @property
    def running(self) -> bool:
        return self._run_lock.locked()

    def run_now(self) -> IntakeReport | Busy:
        """Run one intake. Returns `Busy` (status "bezig") at once when a run is in progress."""
        if not self._run_lock.acquire(blocking=False):
            return Busy()
        try:
            report = self._run()
            with self._state_lock:
                self._last_report = report
            return report
        finally:
            self._run_lock.release()

    def _run(self) -> IntakeReport:
        started = _now()
        try:
            mailbox = self._mailbox_factory(self._settings)
            storage = DocumentStorage(self._settings.documents_dir)
            return run_intake(
                self._session_factory,
                storage,
                mailbox,
                max_messages=self._settings.imap_max_messages_per_run,
            )
        except EmailIntakeError as exc:
            error = exc
        except Exception:
            logger.exception("email intake failed unexpectedly")
            error = EmailImapError()
        return IntakeReport(
            status="fout",
            started_at=started,
            finished_at=_now(),
            error_code=error.code if error.code else EMAIL_IMAP_ERROR,
            error_message=error.message,
        )
