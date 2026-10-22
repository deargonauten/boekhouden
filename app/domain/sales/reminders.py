"""Betalingsherinneringen: when allowed, which level, the Dutch text, and creating one.

A reminder is a letter the owner sends himself: it makes no journal entry and changes no
amounts (no fees, no interest). `create_reminder` flushes but never commits.
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.documents.storage import DocumentStorage
from app.domain.ledger import LedgerError
from app.domain.money import format_euro
from app.domain.sales import pdf as sales_pdf
from app.domain.sales.errors import PDF_FAILED, PDF_FAILED_MESSAGE, REMINDER_NOT_ALLOWED, SalesError
from app.domain.sales.service import applied_cents, derive_status, open_amount, storno_entry_id
from app.domain.sales.service import get_invoice as _get
from app.domain.sales.types import CONCEPT, CREDIT_NOTE, ReminderDocument, ReminderDraft
from app.models import Contact, SalesInvoice, SalesReminder

LEVEL_TITLES = {1: "Betalingsherinnering", 2: "Tweede herinnering", 3: "Laatste aanmaning"}
MAX_LEVEL = 3
DEFAULT_EXTRA_DAYS = 14


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_level(existing_levels: Iterable[int]) -> int:
    """1 for the first reminder, then one more each time; level 3 text repeats after that."""
    return min(max(existing_levels, default=0) + 1, MAX_LEVEL)


def reminder_blocker(*, kind: str, status: str) -> str | None:
    """Plain Dutch reason why no reminder can be made for a document with this derived
    status (see `service.derive_status`), or None when it can."""
    if kind == CREDIT_NOTE:
        return "Bij een creditnota hoort geen herinnering."
    if status == CONCEPT:
        return "Van een concept maak je geen herinnering. Maak de factuur eerst definitief."
    if status == "gestorneerd":
        return "Deze factuur is gestorneerd; er valt niets meer te betalen."
    if status in ("betaald", "gecrediteerd", "verrekend"):
        return "Deze factuur is al betaald."
    if status in ("openstaand", "deels_betaald"):
        return "Deze factuur is nog niet te laat."
    return None  # te_laat


def eligible(*, kind: str, status: str) -> bool:
    return reminder_blocker(kind=kind, status=status) is None


def reminder_text(
    level: int,
    *,
    customer_name: str,
    invoice_number: str,
    invoice_date: date,
    due_date: date,
    open_cents: int,
    new_due_date: date,
    iban: str,
    seller_name: str,
) -> str:
    """The proposed letter. Always names invoice number, date, original vervaldatum, open
    amount, new vervaldatum and IBAN. Level 1 friendly, 2 firm, 3 final."""
    level = min(max(level, 1), MAX_LEVEL)
    facts = (
        f"Factuur {invoice_number} van {invoice_date:%d-%m-%Y} had een vervaldatum van {due_date:%d-%m-%Y}. "
        f"Het openstaande bedrag is {format_euro(open_cents)}."
    )
    pay = (
        f"Wil je het bedrag uiterlijk {new_due_date:%d-%m-%Y} overmaken naar {iban} "
        f"onder vermelding van {invoice_number}?"
    )
    if level == 1:
        body = (
            f"Volgens onze administratie hebben we nog geen betaling ontvangen. {facts}\n\n"
            f"Misschien is het aan je aandacht ontsnapt. {pay} "
            "Heb je al betaald, dan kun je dit bericht negeren."
        )
    elif level == 2:
        body = (
            f"Op onze eerdere herinnering hebben we nog geen betaling ontvangen. {facts}\n\n"
            f"{pay} Als je binnen deze termijn niet betaalt, nemen we contact met je op. "
            "Heb je al betaald, laat het ons dan weten."
        )
    else:
        body = (
            f"Ondanks eerdere herinneringen hebben we nog geen betaling ontvangen. {facts}\n\n"
            f"Dit is de laatste aanmaning. {pay} "
            "Betaal je niet op tijd, dan kunnen we verdere stappen nemen om het bedrag te innen. "
            "Heb je al betaald, neem dan direct contact met ons op."
        )
    return f"Beste {customer_name},\n\n{body}\n\nMet vriendelijke groet,\n{seller_name}"


def _check(session: Session, invoice: SalesInvoice, today: date) -> int:
    """Open amount if a reminder is allowed, else SalesError with the plain reason."""
    status = derive_status(
        kind=invoice.kind, status=invoice.status, total_cents=invoice.total_incl_cents,
        paid_cents=invoice.paid_cents, applied_cents=applied_cents(session, invoice),
        due_date=invoice.due_date, today=today,
        reversed=storno_entry_id(session, invoice) is not None,
    )
    reason = reminder_blocker(kind=invoice.kind, status=status)
    if reason:
        raise SalesError(REMINDER_NOT_ALLOWED, reason)
    return open_amount(session, invoice)


def _levels(session: Session, invoice_id: int) -> list[int]:
    return list(session.scalars(select(SalesReminder.level).where(SalesReminder.invoice_id == invoice_id)))


def draft_reminder(
    session: Session,
    invoice_id: int,
    today: date | None = None,
    *,
    reminder_date: date | None = None,
    new_due_date: date | None = None,
) -> ReminderDraft:
    """The proposal shown before creating: next level, date today, new vervaldatum +14 days."""
    today = today or date.today()
    invoice = _get(session, invoice_id)
    open_cents = _check(session, invoice, today)
    contact = session.get(Contact, invoice.contact_id)
    level = next_level(_levels(session, invoice.id))
    reminder_date = reminder_date or today
    new_due_date = new_due_date or reminder_date + timedelta(days=DEFAULT_EXTRA_DAYS)
    title = LEVEL_TITLES[level]
    text = reminder_text(
        level, customer_name=invoice.buyer_name or contact.name, invoice_number=invoice.number,
        invoice_date=invoice.invoice_date, due_date=invoice.due_date, open_cents=open_cents,
        new_due_date=new_due_date, iban=invoice.seller_iban or "", seller_name=invoice.seller_name or "",
    )
    return ReminderDraft(
        invoice_id=invoice.id, invoice_number=invoice.number, level=level, title=title,
        reminder_date=reminder_date, new_due_date=new_due_date, open_cents=open_cents, body_text=text,
        contact_name=contact.name, contact_email=contact.email,
        mailto_subject=f"{title} factuur {invoice.number}",
    )


def create_reminder(
    session: Session,
    invoice_id: int,
    *,
    reminder_date: date | None = None,
    new_due_date: date | None = None,
    today: date | None = None,
    storage: DocumentStorage | None = None,
) -> SalesReminder:
    """Store the reminder (append-only row + PDF). `new_due_date` must be after `reminder_date`."""
    draft = draft_reminder(session, invoice_id, today, reminder_date=reminder_date, new_due_date=new_due_date)
    if draft.new_due_date <= draft.reminder_date:
        raise SalesError(
            REMINDER_NOT_ALLOWED,
            "De nieuwe vervaldatum moet na de datum van de herinnering liggen.",
            field="new_due_date",
        )
    invoice = _get(session, invoice_id)
    if storage is None:
        from app.config import get_settings

        storage = DocumentStorage(get_settings().documents_dir)
    s = lambda v: v or ""  # noqa: E731
    doc = ReminderDocument(
        level=draft.level, title=draft.title, reminder_date=draft.reminder_date,
        new_due_date=draft.new_due_date, open_cents=draft.open_cents, body_text=draft.body_text,
        invoice_number=invoice.number, invoice_date=invoice.invoice_date, due_date=invoice.due_date,
        seller_name=s(invoice.seller_name), seller_address_line=s(invoice.seller_address_line),
        seller_postal_code=s(invoice.seller_postal_code), seller_city=s(invoice.seller_city),
        seller_country=s(invoice.seller_country), seller_kvk=s(invoice.seller_kvk),
        seller_btw_id=s(invoice.seller_btw_id), seller_iban=s(invoice.seller_iban),
        buyer_name=s(invoice.buyer_name), buyer_address_line=s(invoice.buyer_address_line),
        buyer_postal_code=s(invoice.buyer_postal_code), buyer_city=s(invoice.buyer_city),
        buyer_country=s(invoice.buyer_country), seller_email=invoice.seller_email,
        seller_phone=invoice.seller_phone,
    )
    try:
        stored = storage.write(sales_pdf.render_reminder_pdf(doc), "pdf")
    except LedgerError:
        raise
    except Exception as exc:
        raise SalesError(PDF_FAILED, PDF_FAILED_MESSAGE) from exc
    try:
        path = str(stored.path.relative_to(storage.root))
    except ValueError:
        path = str(stored.path)
    reminder = SalesReminder(
        invoice_id=invoice.id, level=draft.level, reminder_date=draft.reminder_date,
        new_due_date=draft.new_due_date, open_cents=draft.open_cents, body_text=draft.body_text,
        pdf_sha256=stored.sha256, pdf_path=path, created_at=_now(),
    )
    session.add(reminder)
    session.flush()
    return reminder
