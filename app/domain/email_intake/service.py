"""Run an email intake: mailbox -> documents in the inbox.

One transaction per mail. The mailbox is only changed (moved/marked) after the commit, so a
failure leaves the mail untouched and unread. Documents are never deleted from here.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.documents.service import add_document
from app.domain.documents.storage import DocumentStorage
from app.domain.email_intake.errors import (
    EmailConnectFailedError,
    EmailIntakeError,
    EmailLoginFailedError,
)
from app.domain.email_intake.mailbox import MailboxClient, build_mailbox
from app.domain.email_intake.parsing import extract_attachments, read_mail_info
from app.domain.errors import DocumentError, DocumentStorageFailedError
from app.models import EmailMessage

logger = logging.getLogger("app.email_intake")

MAX_MAIL_BYTES = 50 * 1024 * 1024
MOVE_FAILED_MESSAGE = "Mail is opgeslagen maar kon niet naar de map Verwerkt worden verplaatst"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class IntakeReport:
    status: str = "klaar"  # "klaar" | "fout" (the whole run failed, see error_*)
    mails_seen: int = 0
    mails_processed: int = 0
    documents_new: int = 0
    documents_duplicate: int = 0
    attachments_skipped: int = 0
    mails_without_attachments: int = 0
    mails_failed: int = 0
    problems: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    def summary(self) -> str:
        """One plain-Dutch sentence about the run."""
        if self.status == "fout":
            return self.error_message or "Ophalen is mislukt."
        parts: list[str] = []
        if self.documents_new:
            n = self.documents_new
            parts.append(f"{n} nieuw{'e' if n != 1 else ''} document{'en' if n != 1 else ''} uit je mailbox gehaald")
        if self.documents_duplicate:
            parts.append(
                f"{self.documents_duplicate} stond er al"
                if self.documents_duplicate == 1
                else f"{self.documents_duplicate} stonden er al"
            )
        if self.mails_without_attachments:
            n = self.mails_without_attachments
            parts.append(f"{n} mail{'s' if n != 1 else ''} zonder PDF of foto {'is' if n == 1 else 'zijn'} overgeslagen")
        if not parts:
            return "Geen nieuwe mail met facturen gevonden."
        return "Klaar: " + ", ".join(parts) + "."


@dataclass(frozen=True)
class Busy:
    """Returned by `IntakeRunner.run_now()` when a run is already in progress."""

    status: str = "bezig"


@dataclass(frozen=True)
class ConnectionResult:
    unread_count: int
    folder: str


def _source_ref(info) -> str:
    return f"{info.from_addr or 'onbekend'} - {info.subject or '(geen onderwerp)'}"[:400]


def _label(info) -> str:
    return info.subject or "(geen onderwerp)"


def _process_mail(
    session_factory: Callable[[], Session],
    storage: DocumentStorage,
    mailbox: MailboxClient,
    uid: str,
    report: IntakeReport,
    ctx: dict[str, str],
) -> None:
    raw = mailbox.fetch(uid)
    info = read_mail_info(raw)
    ctx["label"] = _label(info)
    with session_factory() as session:
        existing = session.scalar(select(EmailMessage).where(EmailMessage.message_key == info.message_key))
        if existing is None:
            result = extract_attachments(raw)
            new = dup = 0
            skipped = [(s.filename, s.reason) for s in result.skipped]
            try:
                for cand in result.candidates:
                    try:
                        added = add_document(
                            session,
                            storage,
                            cand.content,
                            cand.filename,
                            source="email",
                            source_ref=_source_ref(info),
                            received_at=info.received_at,
                        )
                    except DocumentStorageFailedError:
                        raise
                    except DocumentError as exc:
                        skipped.append((cand.filename, exc.message))
                        continue
                    if added.outcome == "created":
                        new += 1
                    else:
                        dup += 1
                outcome = "opgeslagen" if new else ("alleen_dubbel" if dup else "geen_bijlage")
                existing = EmailMessage(
                    message_key=info.message_key,
                    from_addr=info.from_addr,
                    subject=info.subject,
                    received_at=info.received_at,
                    processed_at=_now(),
                    outcome=outcome,
                    documents_new=new,
                    documents_duplicate=dup,
                    attachments_skipped=len(skipped),
                    moved=False,
                )
                session.add(existing)
                session.commit()
            except BaseException:
                session.rollback()
                raise
            report.mails_processed += 1
            report.documents_new += new
            report.documents_duplicate += dup
            report.attachments_skipped += len(skipped)
            if outcome == "geen_bijlage":
                report.mails_without_attachments += 1
            for filename, reason in skipped:
                report.problems.append(f"In de mail '{_label(info)}' is '{filename}' overgeslagen: {reason}.")
        else:
            report.mails_processed += 1

        try:
            mailbox.mark_processed(uid)
        except EmailIntakeError as exc:
            logger.warning("could not move mail %s: %s", uid, exc.message)
            report.problems.append(f"{MOVE_FAILED_MESSAGE}: '{_label(info)}'. Dit wordt de volgende keer opnieuw geprobeerd.")
            return
        existing.moved = True
        session.commit()


def run_intake(
    session_factory: Callable[[], Session],
    storage: DocumentStorage,
    mailbox: MailboxClient,
    *,
    max_messages: int,
) -> IntakeReport:
    """Process unread mails of the mailbox, oldest first. Raises EmailIntakeError on connection-level failure."""
    report = IntakeReport()
    try:
        mailbox.connect()
        unseen = mailbox.list_unseen()[: max(0, max_messages)]
        report.mails_seen = len(unseen)
        for uid, size in unseen:
            if size > MAX_MAIL_BYTES:
                report.mails_failed += 1
                report.problems.append(
                    "Een mail is te groot (meer dan 50 MB) om op te halen. Hij staat nog in je mailbox; "
                    "haal de bijlage er handmatig uit en voeg die toe via Bestand toevoegen."
                )
                continue
            ctx: dict[str, str] = {}
            try:
                _process_mail(session_factory, storage, mailbox, uid, report, ctx)
            except (EmailConnectFailedError, EmailLoginFailedError):
                raise  # the connection itself is gone: abort the run
            except Exception:
                logger.exception("mail %s could not be stored", uid)
                report.mails_failed += 1
                label = ctx.get("label")
                what = f"De mail '{label}'" if label else "Een mail"
                report.problems.append(
                    f"{what} kon niet worden opgeslagen; hij staat nog in je mailbox en wordt de "
                    "volgende keer opnieuw geprobeerd."
                )
    finally:
        mailbox.close()
        report.finished_at = _now()
    return report


def test_connection(
    settings: Settings, mailbox_factory: Callable[[Settings], MailboxClient] = build_mailbox
) -> ConnectionResult:
    """Connect, log in, select the folder and count unread mails. Stores and moves nothing."""
    mailbox = mailbox_factory(settings)
    try:
        mailbox.connect()
        return ConnectionResult(unread_count=len(mailbox.list_unseen()), folder=settings.imap_folder)
    finally:
        mailbox.close()


test_connection.__test__ = False  # not a pytest test


def recent_messages(session: Session, limit: int = 10) -> list[EmailMessage]:
    return list(
        session.scalars(
            select(EmailMessage).order_by(EmailMessage.processed_at.desc(), EmailMessage.id.desc()).limit(limit)
        )
    )
