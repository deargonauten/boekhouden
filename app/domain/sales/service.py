"""Verkoopfacturen (DB service): concept, finalize, credit notes, open amounts and debiteuren.

All functions flush but never commit; the caller commits on success. `finalize` does all its
writes inside one savepoint, so after a failure nothing of it remains (no number is lost).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.company import get_company_profile
from app.domain.documents.storage import DocumentStorage
from app.domain.errors import LedgerError
from app.domain.ledger import Page, default_journal_id, post_entry
from app.domain.opening.service import list_opening_items
from app.domain.sales import pdf as sales_pdf
from app.domain.sales.amounts import add_to_bucket, ageing_bucket, compute_totals, due_date as calc_due_date
from app.domain.sales.entries import (
    DEBTORS_CODE,
    VAT_HIGH_CODE,
    VAT_LOW_CODE,
    EntryLine,
    SalesAccounts,
    build_entry,
)
from app.domain.sales.errors import (
    CREDIT_NOT_ALLOWED,
    IMMUTABLE,
    IMMUTABLE_MESSAGE,
    INVALID_INPUT,
    NO_JOURNAL,
    NO_JOURNAL_MESSAGE,
    NOT_FOUND,
    PDF_FAILED,
    PDF_FAILED_MESSAGE,
    SYSTEM_ACCOUNT_MISSING,
    UNSUPPORTED_VAT,
    UNSUPPORTED_VAT_MESSAGE,
    SalesError,
)
from app.domain.sales.numbering import next_number
from app.domain.sales.types import (
    ALLOWED_VAT_CODES,
    BUCKET_LABELS,
    CONCEPT,
    CREDIT_NOTE,
    DEFINITIEF,
    INVOICE,
    SOURCE_TYPE,
    AgeingRow,
    DocumentLine,
    InvoiceDocument,
    LineInput,
    Totals,
    VatGroup,
)
from app.domain.sales.validation import (
    MAX_NOTE_LENGTH,
    FinalizeInput,
    check_credit_lines,
    check_finalizable,
)
from app.models import (
    Account,
    Contact,
    JournalEntry,
    SalesCreditApplication,
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceVat,
    SalesReminder,
    VatCode,
)

DEFAULT_PAYMENT_TERM_DAYS = 30
STATUS_LABELS = {
    "concept": "Concept",
    "openstaand": "Openstaand",
    "te_laat": "Te laat",
    "deels_betaald": "Deels betaald",
    "betaald": "Betaald",
    "gecrediteerd": "Gecrediteerd",
    "verrekend": "Verrekend",
    "gestorneerd": "Gestorneerd",
}
STATUS_FILTERS = ("alle", "concept", "openstaand", "te_laat", "betaald")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today() -> date:
    return date.today()


# --- small pure helpers ----------------------------------------------------------------------
def open_cents_of(kind: str, total_cents: int, paid_cents: int, applied_cents: int) -> int:
    """Still open, positive for both kinds.

    Invoice: what the klant still has to pay. Credit note: what you still owe back to the klant
    (not yet set off against the original and not yet refunded). Never below zero.
    """
    return max(total_cents - paid_cents - applied_cents, 0)


def derive_status(
    *,
    kind: str,
    status: str,
    total_cents: int,
    paid_cents: int,
    applied_cents: int,
    due_date: date | None,
    today: date,
    reversed: bool,
) -> str:
    """concept | openstaand | te_laat | deels_betaald | betaald | gecrediteerd | verrekend (credit note) | gestorneerd."""
    if status == CONCEPT:
        return "concept"
    if reversed:
        return "gestorneerd"
    open_cents = open_cents_of(kind, total_cents, paid_cents, applied_cents)
    if open_cents == 0:
        if paid_cents == 0 and applied_cents > 0:
            return "gecrediteerd" if kind == INVOICE else "verrekend"
        return "betaald"
    if kind == INVOICE and due_date is not None and due_date < today:
        return "te_laat"
    if paid_cents > 0 or applied_cents > 0:
        return "deels_betaald"
    return "openstaand"


# --- loading helpers ---------------------------------------------------------------------------
def _get(session: Session, invoice_id: int, *, refresh: bool = False) -> SalesInvoice:
    invoice = session.get(SalesInvoice, invoice_id, populate_existing=refresh)
    if invoice is None:
        raise SalesError(NOT_FOUND, "Deze factuur bestaat niet (meer). Ga terug naar Verkoop.")
    return invoice


def get_invoice(session: Session, invoice_id: int) -> SalesInvoice:
    return _get(session, invoice_id)


def _not_storno_d():
    return ~exists().where(JournalEntry.reverses_entry_id == SalesInvoice.journal_entry_id)


def storno_entry_id(session: Session, invoice: SalesInvoice) -> int | None:
    if invoice.journal_entry_id is None:
        return None
    return session.scalar(
        select(JournalEntry.id).where(JournalEntry.reverses_entry_id == invoice.journal_entry_id)
    )


def _reversed_ids(session: Session) -> set[int]:
    return set(
        session.scalars(
            select(SalesInvoice.id).where(
                exists().where(JournalEntry.reverses_entry_id == SalesInvoice.journal_entry_id)
            )
        )
    )


def _applied_maps(session: Session) -> tuple[dict[int, int], dict[int, int]]:
    """(applied per invoice, applied per credit note); applications of storno'd credit notes
    do not count (that credit note no longer reduces the debt), and a credit note's applications
    to a storno'd invoice are released (that invoice no longer has a debt to set off)."""
    reversed_ids = _reversed_ids(session)
    to_invoice: dict[int, int] = {}
    by_credit: dict[int, int] = {}
    for credit_id, invoice_id, amount in session.execute(
        select(
            SalesCreditApplication.credit_note_id,
            SalesCreditApplication.invoice_id,
            SalesCreditApplication.amount_cents,
        )
    ):
        if invoice_id not in reversed_ids:
            by_credit[credit_id] = by_credit.get(credit_id, 0) + amount
        if credit_id not in reversed_ids:
            to_invoice[invoice_id] = to_invoice.get(invoice_id, 0) + amount
    return to_invoice, by_credit


def applied_cents(session: Session, invoice: SalesInvoice) -> int:
    """Credit-note settlement already applied to this invoice (or taken from this credit note)."""
    to_invoice, by_credit = _applied_maps(session)
    return (by_credit if invoice.kind == CREDIT_NOTE else to_invoice).get(invoice.id, 0)


def open_amount(session: Session, invoice: "SalesInvoice | int") -> int:
    """Open amount in cents, positive for both kinds (see `open_cents_of`).

    0 for a concept and for a storno'd document. Invoice: total - paid_cents - verrekend.
    Credit note: total - verrekend - refunded (paid_cents of the credit note).
    """
    if isinstance(invoice, int):
        invoice = _get(session, invoice)
    if invoice.status != DEFINITIEF or storno_entry_id(session, invoice) is not None:
        return 0
    return open_cents_of(invoice.kind, invoice.total_incl_cents, invoice.paid_cents, applied_cents(session, invoice))


def _rates(session: Session) -> dict[str, int]:
    return dict(session.execute(select(VatCode.code, VatCode.rate_bp)).all())


def _line_inputs(invoice: SalesInvoice) -> list[LineInput]:
    return [
        LineInput(
            description=l.description,
            quantity_milli=l.quantity_milli,
            unit_price_cents=l.unit_price_cents,
            vat_code=l.vat_code,
            account_id=l.account_id,
            unit=l.unit,
            original_line_id=l.original_line_id,
        )
        for l in invoice.lines
    ]


# --- suggested defaults ------------------------------------------------------------------------
@dataclass(frozen=True)
class SalesDefaults:
    invoice_date: date
    payment_term_days: int
    due_date: date
    term_source: str  # "klant" | "standaard"


def suggest_defaults(session: Session, contact_id: int | None, today: date | None = None) -> SalesDefaults:
    """Invoice date today; betaaltermijn of the klant, else 30 days; due date = date + term."""
    today = today or _today()
    contact = session.get(Contact, contact_id) if contact_id else None
    if contact is not None and contact.payment_term_days is not None:
        days, source = contact.payment_term_days, "klant"
    else:
        days, source = DEFAULT_PAYMENT_TERM_DAYS, "standaard"
    return SalesDefaults(today, days, calc_due_date(today, days), source)


def suggest_revenue_account(session: Session, vat_code: str) -> int | None:
    """The active, postable revenue account whose default btw-code is `vat_code` (lowest code)."""
    return session.scalar(
        select(Account.id)
        .where(
            Account.type == "revenue",
            Account.is_active.is_(True),
            Account.is_postable.is_(True),
            Account.default_vat_code == vat_code,
        )
        .order_by(Account.code)
        .limit(1)
    )


def default_line(session: Session, vat_code: str = "NL_21") -> LineInput:
    """An empty line with the suggested omzetrekening for the btw-code, unit 'stuk'."""
    return LineInput("", 1000, 0, vat_code, suggest_revenue_account(session, vat_code))


def revenue_accounts(session: Session) -> list[Account]:
    """Choosable omzetrekeningen (active, postable revenue accounts)."""
    return list(
        session.scalars(
            select(Account)
            .where(Account.type == "revenue", Account.is_active.is_(True), Account.is_postable.is_(True))
            .order_by(Account.code)
        )
    )


def compute_concept_totals(session: Session, lines: Sequence[LineInput]) -> Totals:
    """Live totals for the editor (no writes)."""
    return compute_totals(lines, _rates(session))


# --- concept -----------------------------------------------------------------------------------
@dataclass
class ConceptInput:
    """Everything the concept editor posts. For a credit note only `quantity_milli` of lines
    (matched by `original_line_id`), the dates, reference and note can change."""

    contact_id: int
    invoice_date: date
    lines: Sequence[LineInput] = ()
    payment_term_days: int | None = None  # None: the klant's term, else 30
    due_date: date | None = None  # only used when due_date_manual
    due_date_manual: bool = False
    service_date: date | None = None
    reference: str | None = None
    note: str | None = None


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


def _check_contact(session: Session, contact_id: int | None) -> Contact:
    contact = session.get(Contact, contact_id) if contact_id else None
    if contact is None:
        raise SalesError(INVALID_INPUT, "Kies eerst een klant voor deze factuur.", field="contact")
    return contact


def _apply_header(session: Session, invoice: SalesInvoice, data: ConceptInput) -> None:
    contact = _check_contact(session, data.contact_id)
    if data.note and len(data.note) > MAX_NOTE_LENGTH:
        raise SalesError(INVALID_INPUT, f"De opmerking is te lang (maximaal {MAX_NOTE_LENGTH} tekens).", field="note")
    if data.payment_term_days is not None and not 0 <= data.payment_term_days <= 365:
        raise SalesError(
            INVALID_INPUT, "De betaaltermijn is een aantal dagen tussen 0 en 365.", field="payment_term_days"
        )
    invoice.contact_id = contact.id
    invoice.invoice_date = data.invoice_date
    invoice.service_date = data.service_date
    invoice.reference = _clean(data.reference)
    invoice.note = _clean(data.note)
    if invoice.kind == CREDIT_NOTE:  # a credit note is not payable by the klant
        invoice.payment_term_days, invoice.due_date, invoice.due_date_manual = 0, data.invoice_date, False
        return
    term = data.payment_term_days
    if term is None:
        term = suggest_defaults(session, contact.id, data.invoice_date).payment_term_days
    invoice.payment_term_days = term
    if data.due_date_manual and data.due_date is not None:
        invoice.due_date, invoice.due_date_manual = data.due_date, True
    else:
        invoice.due_date, invoice.due_date_manual = calc_due_date(data.invoice_date, term), False


def _fill_account(session: Session, line: LineInput) -> LineInput:
    if line.account_id is None:
        return replace(line, account_id=suggest_revenue_account(session, line.vat_code))
    return line


def _check_concept_line(line: LineInput, index: int) -> None:
    n = index + 1
    if line.vat_code not in ALLOWED_VAT_CODES:
        raise SalesError(UNSUPPORTED_VAT, UNSUPPORTED_VAT_MESSAGE, field=f"line-{index}-vat_code")
    if line.quantity_milli <= 0:
        raise SalesError(INVALID_INPUT, f"Regel {n}: het aantal moet groter zijn dan nul.", field=f"line-{index}-quantity")
    if line.unit_price_cents < 0:
        raise SalesError(INVALID_INPUT, f"Regel {n}: de prijs mag niet negatief zijn.", field=f"line-{index}-price")


def _credit_lines(session: Session, invoice: SalesInvoice, wanted: Sequence[LineInput]) -> list[LineInput]:
    """Credit note lines = original lines with the (lowered) quantities asked for."""
    original = _get(session, invoice.credited_invoice_id)
    originals = {l.id: l for l in original.lines}
    credited = _credited_milli(session, original.id, exclude_id=invoice.id)
    check_credit_lines(
        [(l.original_line_id, l.quantity_milli) for l in wanted],
        {lid: (l.quantity_milli, credited.get(lid, 0)) for lid, l in originals.items()},
    )
    result = []
    for line in wanted:
        o = originals[line.original_line_id]
        result.append(
            LineInput(o.description, line.quantity_milli, o.unit_price_cents, o.vat_code, o.account_id, o.unit, o.id)
        )
    return result


def _write_lines(session: Session, invoice: SalesInvoice, lines: Sequence[LineInput], rates: dict[str, int]) -> Totals:
    invoice.lines.clear()  # delete-orphan: the old lines are deleted
    session.flush()
    totals = compute_totals(lines, rates)
    for position, (line, amount) in enumerate(zip(lines, totals.line_excl_cents)):
        invoice.lines.append(
            SalesInvoiceLine(
                position=position,
                description=line.description.strip(),
                quantity_milli=line.quantity_milli,
                unit=(line.unit or "stuk").strip() or "stuk",
                unit_price_cents=line.unit_price_cents,
                vat_code=line.vat_code,
                account_id=line.account_id,
                line_excl_cents=amount,
                original_line_id=line.original_line_id,
            )
        )
    invoice.total_excl_cents = totals.total_excl_cents
    invoice.total_vat_cents = totals.total_vat_cents
    invoice.total_incl_cents = totals.total_incl_cents
    return totals


def _require_concept(invoice: SalesInvoice) -> None:
    if invoice.status != CONCEPT:
        raise SalesError(IMMUTABLE, IMMUTABLE_MESSAGE)


def create_concept(session: Session, data: ConceptInput) -> SalesInvoice:
    """A new concept invoice (no number). Lines may be empty; see `save_concept`."""
    now = _now()
    invoice = SalesInvoice(
        kind=INVOICE, status=CONCEPT, contact_id=data.contact_id, invoice_date=data.invoice_date,
        payment_term_days=0, due_date=data.invoice_date, created_at=now, updated_at=now,
    )
    _apply_header(session, invoice, data)
    session.add(invoice)
    session.flush()
    return save_concept(session, invoice.id, data)


def save_concept(session: Session, invoice_id: int, data: ConceptInput) -> SalesInvoice:
    """Replace header and lines of a concept. Missing omzetrekeningen are suggested from the
    btw-code. Raises SalesError(IMMUTABLE) for a definitief document."""
    invoice = _get(session, invoice_id)
    _require_concept(invoice)
    lines = [_fill_account(session, l) for l in data.lines]
    if invoice.kind == CREDIT_NOTE:
        lines = _credit_lines(session, invoice, data.lines)
    for i, line in enumerate(lines):
        _check_concept_line(line, i)
    rates = _rates(session)
    compute_totals(lines, rates)  # fail before anything is changed
    _apply_header(session, invoice, data)
    _write_lines(session, invoice, lines, rates)
    invoice.updated_at = _now()
    session.flush()
    return invoice


def delete_concept(session: Session, invoice_id: int) -> None:
    """Delete a concept (no number was consumed). A definitief document can never be deleted."""
    invoice = _get(session, invoice_id)
    _require_concept(invoice)
    session.delete(invoice)  # its lines go with it
    session.flush()


def _credited_milli(session: Session, original_id: int, exclude_id: int | None = None) -> dict[int, int]:
    """Quantity already credited per original line, over finalized (not storno'd) credit notes."""
    stmt = (
        select(SalesInvoiceLine.original_line_id, func.sum(SalesInvoiceLine.quantity_milli))
        .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
        .where(
            SalesInvoice.credited_invoice_id == original_id,
            SalesInvoice.status == DEFINITIEF,
            _not_storno_d(),
            SalesInvoiceLine.original_line_id.is_not(None),
        )
        .group_by(SalesInvoiceLine.original_line_id)
    )
    if exclude_id is not None:
        stmt = stmt.where(SalesInvoice.id != exclude_id)
    return {lid: int(qty) for lid, qty in session.execute(stmt)}


def create_credit_concept(session: Session, invoice_id: int, today: date | None = None) -> SalesInvoice:
    """Concept credit note for a finalized invoice, prefilled with the lines that can still be
    credited (same account, btw-code and price)."""
    today = today or _today()
    original = _get(session, invoice_id)
    if original.kind != INVOICE or original.status != DEFINITIEF:
        raise SalesError(CREDIT_NOT_ALLOWED, "Een creditnota maak je bij een definitieve factuur, niet bij een concept of een andere creditnota.")
    if storno_entry_id(session, original) is not None:
        raise SalesError(CREDIT_NOT_ALLOWED, "Deze factuur is gestorneerd; daar kun je geen creditnota meer bij maken.")
    credited = _credited_milli(session, original.id)
    remaining = [(l, l.quantity_milli - credited.get(l.id, 0)) for l in original.lines]
    remaining = [(l, q) for l, q in remaining if q > 0]
    if not remaining:
        raise SalesError(CREDIT_NOT_ALLOWED, "Deze factuur is al helemaal gecrediteerd.")
    now = _now()
    note = SalesInvoice(
        kind=CREDIT_NOTE, status=CONCEPT, contact_id=original.contact_id, credited_invoice_id=original.id,
        invoice_date=today, payment_term_days=0, due_date=today, created_at=now, updated_at=now,
    )
    session.add(note)
    session.flush()
    rates = _rates(session)
    _write_lines(
        session,
        note,
        [
            LineInput(l.description, q, l.unit_price_cents, l.vat_code, l.account_id, l.unit, l.id)
            for l, q in remaining
        ],
        rates,
    )
    session.flush()
    return note


# --- finalize ------------------------------------------------------------------------------------
def _open_transaction(session: Session) -> None:
    # pysqlite only opens a transaction on DML; this no-op UPDATE takes the write lock up front
    # (so two finalizes queue up) and makes the savepoint below an inner one.
    session.execute(update(SalesInvoice).where(SalesInvoice.id.is_(None)).values(status=SalesInvoice.status))


def _system_accounts(session: Session) -> SalesAccounts:
    ids = dict(
        session.execute(
            select(Account.code, Account.id).where(Account.code.in_((DEBTORS_CODE, VAT_HIGH_CODE, VAT_LOW_CODE)))
        ).all()
    )
    for code, name in ((DEBTORS_CODE, "Debiteuren"), (VAT_HIGH_CODE, "BTW af te dragen hoog"), (VAT_LOW_CODE, "BTW af te dragen laag")):
        if code not in ids:
            raise SalesError(
                SYSTEM_ACCOUNT_MISSING,
                f"Rekening {code} {name} ontbreekt in je grootboek, dus de factuur kan niet geboekt worden. "
                "Zet de rekening terug onder Instellingen > Grootboek.",
            )
    return SalesAccounts(ids[DEBTORS_CODE], ids[VAT_HIGH_CODE], ids[VAT_LOW_CODE])


def _journal_id(session: Session) -> int:
    journal_id = default_journal_id(session, "verkoop")
    if journal_id is None:
        raise SalesError(NO_JOURNAL, NO_JOURNAL_MESSAGE)
    return journal_id


def _latest_final_date(session: Session, year: int, exclude_id: int) -> date | None:
    return session.scalar(
        select(func.max(SalesInvoice.invoice_date)).where(
            SalesInvoice.status == DEFINITIEF, SalesInvoice.number_year == year, SalesInvoice.id != exclude_id
        )
    )


def _snapshot(invoice: SalesInvoice, company, contact: Contact) -> None:
    invoice.seller_name = company.legal_name
    invoice.seller_address_line = company.address_line
    invoice.seller_postal_code = company.postal_code
    invoice.seller_city = company.city
    invoice.seller_country = company.country or "NL"
    invoice.seller_kvk = company.kvk
    invoice.seller_btw_id = company.btw_id
    invoice.seller_iban = company.iban
    invoice.seller_email = company.email
    invoice.seller_phone = company.phone
    invoice.buyer_name = contact.name
    invoice.buyer_address_line = contact.address_line
    invoice.buyer_postal_code = contact.postal_code
    invoice.buyer_city = contact.city
    invoice.buyer_country = contact.country or "NL"
    invoice.buyer_btw_number = contact.btw_number
    invoice.buyer_kvk = contact.kvk


def _document(
    session: Session, invoice: SalesInvoice, lines: Sequence[SalesInvoiceLine], groups: Sequence[VatGroup],
    rates: dict[str, int], *, is_concept: bool | None = None,
) -> InvoiceDocument:
    original = session.get(SalesInvoice, invoice.credited_invoice_id) if invoice.credited_invoice_id else None
    s = lambda v: v or ""  # noqa: E731
    return InvoiceDocument(
        kind=invoice.kind,
        number=invoice.number or "",
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        payment_term_days=invoice.payment_term_days,
        seller_name=s(invoice.seller_name),
        seller_address_line=s(invoice.seller_address_line),
        seller_postal_code=s(invoice.seller_postal_code),
        seller_city=s(invoice.seller_city),
        seller_country=s(invoice.seller_country),
        seller_kvk=s(invoice.seller_kvk),
        seller_btw_id=s(invoice.seller_btw_id),
        seller_iban=s(invoice.seller_iban),
        seller_email=invoice.seller_email,
        seller_phone=invoice.seller_phone,
        buyer_name=s(invoice.buyer_name),
        buyer_address_line=s(invoice.buyer_address_line),
        buyer_postal_code=s(invoice.buyer_postal_code),
        buyer_city=s(invoice.buyer_city),
        buyer_country=s(invoice.buyer_country),
        buyer_btw_number=invoice.buyer_btw_number,
        buyer_kvk=invoice.buyer_kvk,
        lines=tuple(
            DocumentLine(l.description, l.quantity_milli, l.unit, l.unit_price_cents, l.vat_code,
                         rates.get(l.vat_code, 0), l.line_excl_cents)
            for l in lines
        ),
        vat_groups=tuple(groups),
        total_excl_cents=invoice.total_excl_cents,
        total_vat_cents=invoice.total_vat_cents,
        total_incl_cents=invoice.total_incl_cents,
        service_date=invoice.service_date,
        reference=invoice.reference,
        note=invoice.note,
        credited_number=original.number if original else None,
        credited_date=original.invoice_date if original else None,
        is_concept=invoice.status == CONCEPT if is_concept is None else is_concept,
    )


def build_document(session: Session, invoice_id: int) -> InvoiceDocument:
    """Snapshot for the PDF. A definitief document is read from its frozen data; a concept is
    rendered from the current company and klant data, with `is_concept=True` and no number."""
    invoice = _get(session, invoice_id)
    rates = _rates(session)
    if invoice.status == DEFINITIEF:
        groups = [VatGroup(v.vat_code, v.rate_bp, v.base_cents, v.vat_cents) for v in invoice.vat_rows]
        groups.sort(key=lambda g: (-g.rate_bp, g.vat_code))
        return _document(session, invoice, invoice.lines, groups, rates)
    company = get_company_profile(session)
    contact = _check_contact(session, invoice.contact_id)
    # transient copy (never added to the session) that carries the live company/klant data
    shadow = SalesInvoice(**{c.name: getattr(invoice, c.name) for c in SalesInvoice.__table__.columns})
    _snapshot(shadow, company, contact)
    totals = compute_totals(_line_inputs(invoice), rates)
    return _document(session, shadow, invoice.lines, totals.groups, rates)


def finalize(session: Session, invoice_id: int, *, storage: DocumentStorage | None = None) -> SalesInvoice:
    """Make a concept definitief, in one transaction: validate, snapshot, number, post the entry,
    store the PDF. Raises SalesError / LedgerError with a plain Dutch message; on any failure
    nothing is persisted and no number is used. `storage` defaults to the configured
    documents directory."""
    _open_transaction(session)
    invoice = _get(session, invoice_id, refresh=True)
    _require_concept(invoice)
    company = get_company_profile(session)
    contact = _check_contact(session, invoice.contact_id)
    rates = _rates(session)
    lines = _line_inputs(invoice)
    totals = compute_totals(lines, rates)
    accounts = {a.id for a in revenue_accounts(session)}
    is_credit = invoice.kind == CREDIT_NOTE
    original = None
    if is_credit:
        original = _get(session, invoice.credited_invoice_id, refresh=True)
        if original.status != DEFINITIEF or storno_entry_id(session, original) is not None:
            raise SalesError(CREDIT_NOT_ALLOWED, "De oorspronkelijke factuur is gestorneerd of niet definitief; er kan geen creditnota meer bij.")
        credited = _credited_milli(session, original.id, exclude_id=invoice.id)
        check_credit_lines(
            [(l.original_line_id, l.quantity_milli) for l in lines],
            {l.id: (l.quantity_milli, credited.get(l.id, 0)) for l in original.lines},
        )
        totals = _cap_credit_totals(session, original, invoice, lines, totals)
    check_finalizable(
        FinalizeInput(
            kind=invoice.kind,
            company=company,
            buyer_name=contact.name,
            buyer_address_line=contact.address_line,
            buyer_postal_code=contact.postal_code,
            buyer_city=contact.city,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            lines=lines,
            valid_account_ids=accounts,
            total_incl_cents=totals.total_incl_cents,
            latest_final_date=_latest_final_date(session, invoice.invoice_date.year, invoice.id),
            note=invoice.note,
        )
    )
    sys_accounts = _system_accounts(session)
    journal_id = _journal_id(session)
    if storage is None:
        from app.config import get_settings

        storage = DocumentStorage(get_settings().documents_dir)

    year = invoice.invoice_date.year
    with session.begin_nested():  # any failure below also rolls back the number counter
        seq, number = next_number(session, year)
        invoice.number, invoice.number_year, invoice.number_seq = number, year, seq
        _snapshot(invoice, company, contact)
        for line, amount in zip(invoice.lines, totals.line_excl_cents):
            line.line_excl_cents = amount
        invoice.total_excl_cents = totals.total_excl_cents
        invoice.total_vat_cents = totals.total_vat_cents
        invoice.total_incl_cents = totals.total_incl_cents
        for old in session.scalars(select(SalesInvoiceVat).where(SalesInvoiceVat.invoice_id == invoice.id)):
            session.delete(old)
        session.flush()
        for g in totals.groups:
            session.add(SalesInvoiceVat(invoice_id=invoice.id, vat_code=g.vat_code, rate_bp=g.rate_bp,
                                        base_cents=g.base_cents, vat_cents=g.vat_cents))
        session.flush()
        new_entry = build_entry(
            kind=invoice.kind,
            number=number,
            invoice_date=invoice.invoice_date,
            customer_name=contact.name,
            lines=[EntryLine(l.account_id, l.vat_code, l.line_excl_cents) for l in invoice.lines],
            groups=totals.groups,
            total_incl_cents=totals.total_incl_cents,
            accounts=sys_accounts,
            journal_id=journal_id,
        )
        entry = post_entry(session, new_entry)
        invoice.journal_entry_id = entry.id
        session.flush()
        # The one allowed update of a booking: its source link, right after posting.
        entry.source_type = SOURCE_TYPE
        entry.source_id = invoice.id
        session.flush()
        try:
            # the status flips to definitief only below (rollback must stay possible), so say it here
            pdf_bytes = sales_pdf.render_invoice_pdf(
                _document(session, invoice, invoice.lines, totals.groups, rates, is_concept=False))
            stored = storage.write(pdf_bytes, "pdf")
        except LedgerError:
            raise
        except Exception as exc:
            raise SalesError(PDF_FAILED, PDF_FAILED_MESSAGE) from exc
        invoice.pdf_sha256, invoice.pdf_path = stored.sha256, _relative_path(storage, stored.path)
        if is_credit and original is not None:
            applied = min(totals.total_incl_cents, open_amount(session, original))
            if applied > 0:
                session.add(SalesCreditApplication(credit_note_id=invoice.id, invoice_id=original.id,
                                                   amount_cents=applied, created_at=_now()))
        now = _now()
        invoice.finalized_at = invoice.updated_at = now
        invoice.status = DEFINITIEF
        try:
            session.flush()
        except IntegrityError as exc:  # e.g. a parallel finalize took the same number
            raise SalesError(PDF_FAILED, "De factuur kon niet worden vastgelegd. Probeer het opnieuw.") from exc
    return invoice


def _cap_credit_totals(
    session: Session, original: SalesInvoice, credit: SalesInvoice, lines: Sequence[LineInput], totals: Totals
) -> Totals:
    """Cumulative money limit of the credit notes of one invoice (the quantity limit is checked
    separately). Every credit rounds on its own, so several partial credits could add up to a cent
    or two more than the invoice. A line amount is therefore capped at what is left of the
    original line, and the VAT of a btw-code at what is left of the original VAT; so the last
    partial credit takes the remainder."""
    line_left = {l.id: l.line_excl_cents for l in original.lines}
    vat_left = {v.vat_code: v.vat_cents for v in original.vat_rows}
    others = (
        select(SalesInvoice.id)
        .where(SalesInvoice.credited_invoice_id == original.id, SalesInvoice.status == DEFINITIEF,
               SalesInvoice.id != credit.id, _not_storno_d())
    )
    for lid, amount in session.execute(
        select(SalesInvoiceLine.original_line_id, func.sum(SalesInvoiceLine.line_excl_cents))
        .where(SalesInvoiceLine.invoice_id.in_(others), SalesInvoiceLine.original_line_id.is_not(None))
        .group_by(SalesInvoiceLine.original_line_id)
    ):
        line_left[lid] = line_left.get(lid, 0) - int(amount)
    for code, amount in session.execute(
        select(SalesInvoiceVat.vat_code, func.sum(SalesInvoiceVat.vat_cents))
        .where(SalesInvoiceVat.invoice_id.in_(others)).group_by(SalesInvoiceVat.vat_code)
    ):
        vat_left[code] = vat_left.get(code, 0) - int(amount)

    amounts, bases = [], {}
    for line, amount in zip(lines, totals.line_excl_cents):
        amount = max(min(amount, line_left.get(line.original_line_id, amount)), 0)
        if line.original_line_id in line_left:
            line_left[line.original_line_id] -= amount
        amounts.append(amount)
        bases[line.vat_code] = bases.get(line.vat_code, 0) + amount
    groups = tuple(
        VatGroup(g.vat_code, g.rate_bp, bases.get(g.vat_code, 0),
                 max(min(_vat_of(bases.get(g.vat_code, 0), g.rate_bp), vat_left.get(g.vat_code, g.vat_cents)), 0))
        for g in totals.groups
    )
    excl, vat = sum(g.base_cents for g in groups), sum(g.vat_cents for g in groups)
    return Totals(tuple(amounts), groups, excl, vat, excl + vat)


def _vat_of(base_cents: int, rate_bp: int) -> int:
    return (2 * base_cents * rate_bp + 10000) // 20000


def _relative_path(storage: DocumentStorage, path: Path) -> str:
    try:
        return str(Path(path).relative_to(storage.root))
    except ValueError:
        return str(path)


def pdf_file_path(storage: DocumentStorage, invoice: SalesInvoice) -> Path | None:
    """Where the stored PDF of a definitief document lives (None for a concept)."""
    if not invoice.pdf_sha256:
        return None
    return storage.path_for(invoice.pdf_sha256, "pdf")


# --- read model -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class DocumentRow:
    id: int
    kind: str
    status: str  # derived, see `derive_status`
    number: str | None
    invoice_date: date
    due_date: date | None
    contact_id: int
    contact_name: str
    total_cents: int  # negative for a creditnota
    open_cents: int  # negative for a creditnota (what you still owe back)
    is_overdue: bool
    reminder_count: int = 0
    journal_entry_id: int | None = None
    storno_entry_id: int | None = None
    credited_number: str | None = None

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def is_credit_note(self) -> bool:
        return self.kind == CREDIT_NOTE


def _reminder_counts(session: Session) -> dict[int, int]:
    return {i: int(c) for i, c in session.execute(
        select(SalesReminder.invoice_id, func.count()).group_by(SalesReminder.invoice_id))}


def _rows(session: Session, today: date, q: str | None = None, contact_id: int | None = None) -> list[DocumentRow]:
    to_invoice, by_credit = _applied_maps(session)
    reversed_ids = _reversed_ids(session)
    reminders = _reminder_counts(session)
    storno = {
        reverses: eid
        for reverses, eid in session.execute(
            select(JournalEntry.reverses_entry_id, JournalEntry.id).where(JournalEntry.reverses_entry_id.is_not(None))
        )
    }
    stmt = select(SalesInvoice, Contact.name).join(Contact, Contact.id == SalesInvoice.contact_id)
    if contact_id is not None:
        stmt = stmt.where(SalesInvoice.contact_id == contact_id)
    needle = (q or "").strip()
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(or_(Contact.name.ilike(pattern, escape="\\"), SalesInvoice.number.ilike(pattern, escape="\\")))
    numbers = dict(session.execute(select(SalesInvoice.id, SalesInvoice.number)).all())
    result = []
    for inv, name in session.execute(stmt.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.id.desc())):
        credit = inv.kind == CREDIT_NOTE
        applied = (by_credit if credit else to_invoice).get(inv.id, 0)
        reversed_ = inv.id in reversed_ids
        status = derive_status(kind=inv.kind, status=inv.status, total_cents=inv.total_incl_cents,
                               paid_cents=inv.paid_cents, applied_cents=applied, due_date=inv.due_date,
                               today=today, reversed=reversed_)
        open_ = 0 if inv.status == CONCEPT or reversed_ else open_cents_of(inv.kind, inv.total_incl_cents, inv.paid_cents, applied)
        sign = -1 if credit else 1
        result.append(
            DocumentRow(
                id=inv.id, kind=inv.kind, status=status, number=inv.number, invoice_date=inv.invoice_date,
                due_date=inv.due_date if inv.status == DEFINITIEF and not credit else None,
                contact_id=inv.contact_id, contact_name=name,
                total_cents=sign * inv.total_incl_cents, open_cents=sign * open_,
                is_overdue=status == "te_laat", reminder_count=reminders.get(inv.id, 0),
                journal_entry_id=inv.journal_entry_id,
                storno_entry_id=storno.get(inv.journal_entry_id) if inv.journal_entry_id else None,
                credited_number=numbers.get(inv.credited_invoice_id) if inv.credited_invoice_id else None,
            )
        )
    return result


def list_documents(
    session: Session,
    q: str | None = None,
    status: str = "alle",
    page: int = 1,
    per_page: int = 50,
    today: date | None = None,
) -> Page:
    """All documents, newest first. status: alle | concept | openstaand (open, not late) |
    te_laat | betaald (betaald and gecrediteerd). Items are DocumentRow."""
    today = today or _today()
    rows = _rows(session, today, q)
    if status == "concept":
        rows = [r for r in rows if r.status == "concept"]
    elif status == "openstaand":
        rows = [r for r in rows if r.status in ("openstaand", "deels_betaald")]
    elif status == "te_laat":
        rows = [r for r in rows if r.status == "te_laat"]
    elif status == "betaald":
        rows = [r for r in rows if r.status in ("betaald", "gecrediteerd", "verrekend")]
    total = len(rows)
    page = min(max(1, page), max(1, -(-total // per_page)))
    return Page(items=rows[(page - 1) * per_page : page * per_page], page=page, per_page=per_page, total=total)


@dataclass(frozen=True)
class SalesStats:
    total_open_cents: int  # Totaal openstaand (invoices minus open credit, plus beginbalans)
    overdue_cents: int  # Waarvan te laat
    open_count: int  # Aantal open facturen
    concept_count: int  # Concepten


@dataclass(frozen=True)
class DebtorItem:
    """One open item of a klant: a sales invoice, a credit note, or a beginbalans post."""

    source: str  # sales_invoice | opening_item
    id: int
    contact_id: int
    contact_name: str
    kind: str  # invoice | credit_note
    number: str
    invoice_date: date
    due_date: date | None
    open_cents: int  # negative for a creditnota
    bucket: str
    days_overdue: int
    reminder_count: int = 0

    @property
    def is_overdue(self) -> bool:
        return self.bucket != "not_due" and self.kind == INVOICE


@dataclass(frozen=True)
class DebtorRow(AgeingRow):
    invoice_count: int = 0
    reminder_count: int = 0
    opening_count: int = 0


def _open_items(session: Session, today: date, contact_id: int | None = None) -> list[DebtorItem]:
    items = []
    for r in _rows(session, today, contact_id=contact_id):
        if r.status in ("concept", "gestorneerd") or r.open_cents == 0:
            continue
        credit = r.is_credit_note
        due = None if credit else r.due_date
        bucket = "not_due" if credit or due is None else ageing_bucket(due, today)
        items.append(
            DebtorItem("sales_invoice", r.id, r.contact_id, r.contact_name, r.kind, r.number or "", r.invoice_date,
                       due, r.open_cents, bucket, max((today - due).days, 0) if due else 0, r.reminder_count)
        )
    for o in list_opening_items(session, "debiteur", open_only=True, today=today):
        if contact_id is not None and o.contact_id != contact_id:
            continue
        due = o.due_date or o.invoice_date
        items.append(
            DebtorItem("opening_item", o.id, o.contact_id, o.relation_name, INVOICE, o.invoice_number,
                       o.invoice_date, o.due_date, o.open_cents, ageing_bucket(due, today), max((today - due).days, 0))
        )
    return items


def debtor_open_items(session: Session, contact_id: int, today: date | None = None) -> list[DebtorItem]:
    """The open invoices, credit notes and beginbalans posten of one klant, oldest first."""
    items = _open_items(session, today or _today(), contact_id)
    return sorted(items, key=lambda i: (i.invoice_date, i.id))


def debiteuren_overview(session: Session, today: date | None = None) -> list[DebtorRow]:
    """Per klant what is still open, split in ouderdom buckets by days past the vervaldatum.
    Largest amount first. Credit notes with open credit reduce the 'Nog niet vervallen' bucket."""
    today = today or _today()
    per: dict[int, DebtorRow] = {}
    for item in _open_items(session, today):
        row = per.get(item.contact_id) or DebtorRow(item.contact_id, item.contact_name)
        row = add_to_bucket(row, item.bucket, item.open_cents)
        row = replace(
            row,
            invoice_count=row.invoice_count + (1 if item.kind == INVOICE else 0),
            reminder_count=row.reminder_count + (1 if item.reminder_count else 0),
            opening_count=row.opening_count + (1 if item.source == "opening_item" else 0),
        )
        per[item.contact_id] = row
    return sorted((r for r in per.values() if r.total_cents), key=lambda r: (-r.total_cents, r.contact_name.lower()))


def debtor_totals(rows: Sequence[AgeingRow]) -> AgeingRow:
    """The totals row of the ouderdomsanalyse."""
    total = AgeingRow(0, "Totaal")
    for bucket in BUCKET_LABELS:
        for r in rows:
            total = add_to_bucket(total, bucket, getattr(r, f"{bucket}_cents"))
    return total


def stats(session: Session, today: date | None = None) -> SalesStats:
    today = today or _today()
    items = _open_items(session, today)
    concepts = session.scalar(select(func.count()).select_from(SalesInvoice).where(SalesInvoice.status == CONCEPT))
    return SalesStats(
        total_open_cents=sum(i.open_cents for i in items),
        overdue_cents=sum(i.open_cents for i in items if i.is_overdue),
        open_count=sum(1 for i in items if i.kind == INVOICE),
        concept_count=int(concepts or 0),
    )


@dataclass(frozen=True)
class ReminderRow:
    id: int
    level: int
    reminder_date: date
    new_due_date: date
    open_cents: int
    has_pdf: bool


@dataclass
class InvoiceDetail:
    invoice: SalesInvoice
    contact: Contact
    status: str
    open_cents: int  # positive for both kinds
    applied_cents: int
    journal_entry_number: str | None
    storno_entry_id: int | None
    original: SalesInvoice | None = None  # credit note: the invoice it corrects
    credit_notes: list[SalesInvoice] = field(default_factory=list)  # invoice: its finalized credit notes
    applications: list[SalesCreditApplication] = field(default_factory=list)
    reminders: list[ReminderRow] = field(default_factory=list)
    can_credit: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


def get_detail(session: Session, invoice_id: int, today: date | None = None) -> InvoiceDetail:
    from app.domain.sales.errors import STORNO_WARNING

    today = today or _today()
    invoice = _get(session, invoice_id)
    storno_id = storno_entry_id(session, invoice)
    applied = applied_cents(session, invoice)
    status = derive_status(kind=invoice.kind, status=invoice.status, total_cents=invoice.total_incl_cents,
                           paid_cents=invoice.paid_cents, applied_cents=applied, due_date=invoice.due_date,
                           today=today, reversed=storno_id is not None)
    entry_number = (
        session.scalar(select(JournalEntry.entry_number).where(JournalEntry.id == invoice.journal_entry_id))
        if invoice.journal_entry_id else None
    )
    detail = InvoiceDetail(
        invoice=invoice,
        contact=session.get(Contact, invoice.contact_id),
        status=status,
        open_cents=open_amount(session, invoice),
        applied_cents=applied,
        journal_entry_number=entry_number,
        storno_entry_id=storno_id,
        original=session.get(SalesInvoice, invoice.credited_invoice_id) if invoice.credited_invoice_id else None,
    )
    if invoice.kind == INVOICE:
        detail.credit_notes = list(session.scalars(
            select(SalesInvoice).where(SalesInvoice.credited_invoice_id == invoice.id, SalesInvoice.status == DEFINITIEF)
            .order_by(SalesInvoice.id)))
    detail.applications = list(session.scalars(
        select(SalesCreditApplication)
        .where((SalesCreditApplication.invoice_id == invoice.id) | (SalesCreditApplication.credit_note_id == invoice.id))
        .order_by(SalesCreditApplication.id)))
    detail.reminders = [
        ReminderRow(r.id, r.level, r.reminder_date, r.new_due_date, r.open_cents, bool(r.pdf_sha256))
        for r in session.scalars(select(SalesReminder).where(SalesReminder.invoice_id == invoice.id).order_by(SalesReminder.id))
    ]
    detail.can_credit = (
        invoice.kind == INVOICE and invoice.status == DEFINITIEF and storno_id is None
        and any(q > 0 for q in _remaining_creditable(session, invoice).values())
    )
    if storno_id is not None:
        detail.warnings.append(STORNO_WARNING)
    return detail


def _remaining_creditable(session: Session, original: SalesInvoice) -> dict[int, int]:
    credited = _credited_milli(session, original.id)
    return {l.id: l.quantity_milli - credited.get(l.id, 0) for l in original.lines}
