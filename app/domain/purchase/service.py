"""Inkoopfactuur boeken and the crediteuren overview (DB service).

All functions flush but never commit; the caller commits on success. `book_extraction`
does all its writes inside one savepoint, so after a failure nothing of it remains,
even if the caller commits anyway.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.domain.documents import get_document, mark_booked
from app.domain.errors import LedgerError
from app.domain.extraction.service import flagged_count
from app.domain.ledger import Page, default_journal_id, post_entry
from app.domain.ledger.service import _check_accounts, _check_vat_codes, _find_period
from app.domain.purchase.booking import (
    CREDIT_NOTE,
    SOURCE_TYPE,
    AccountIds,
    BookingInput,
    BookingLineInput,
    PreviewRow,
    build_entry,
    check_bookable,
    check_content,
    check_state,
    invoice_number_key,
    preview_lines,
)
from app.domain.purchase.errors import (
    ALREADY_BOOKED,
    ALREADY_BOOKED_MESSAGE,
    DUPLICATE_INVOICE,
    NO_JOURNAL,
    NO_JOURNAL_MESSAGE,
    NOT_REVIEWED,
    NOT_REVIEWED_MESSAGE,
    SYSTEM_ACCOUNT_MISSING,
    BookingError,
    duplicate_message,
)
from app.domain.purchase.learned import record_booking
from app.models import (
    Account,
    Contact,
    Document,
    InvoiceExtraction,
    Journal,
    JournalEntry,
    PurchaseInvoice,
    VatCode,
)

CREDITORS_CODE = "3000"
VAT_RECEIVABLE_CODE = "1400"
TABS = ("all", "open")
STATUS_LABELS = {"open": "Open", "betaald": "Betaald", "gestorneerd": "Gestorneerd"}
_MONTHS = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- loading -------------------------------------------------------------------------------------
def _find_extraction(session: Session, document_id: int) -> InvoiceExtraction | None:
    return session.scalar(select(InvoiceExtraction).where(InvoiceExtraction.document_id == document_id))


def _booking_input(session: Session, document: Document, extraction: InvoiceExtraction) -> BookingInput:
    contact = session.get(Contact, extraction.contact_id) if extraction.contact_id else None
    rubrieken = dict(session.execute(select(VatCode.code, VatCode.purchase_rubriek)).all())
    return BookingInput(
        supplier_name=contact.name if contact is not None else extraction.supplier_name,
        contact_id=extraction.contact_id,
        invoice_number=extraction.invoice_number,
        invoice_date=extraction.invoice_date,
        due_date=extraction.due_date,
        kind=extraction.kind,
        currency=extraction.currency,
        total_excl_cents=extraction.total_excl_cents,
        total_vat_cents=extraction.total_vat_cents,
        total_incl_cents=extraction.total_incl_cents,
        lines=tuple(
            BookingLineInput(
                description=ln.description,
                account_id=ln.account_id,
                vat_code=ln.vat_code,
                amount_excl_cents=ln.amount_excl_cents,
                vat_amount_cents=ln.vat_amount_cents,
            )
            for ln in extraction.lines
        ),
        reviewed=extraction.reviewed_at is not None,
        extraction_ok=extraction.status == "ok",
        already_booked=document.status == "geboekt",
        vat_purchase_rubrieken=rubrieken,
    )


def _system_accounts(session: Session) -> AccountIds:
    ids = dict(
        session.execute(
            select(Account.code, Account.id).where(Account.code.in_((CREDITORS_CODE, VAT_RECEIVABLE_CODE)))
        ).all()
    )
    for code, name in ((CREDITORS_CODE, "Crediteuren"), (VAT_RECEIVABLE_CODE, "BTW voorbelasting")):
        if code not in ids:
            raise BookingError(
                SYSTEM_ACCOUNT_MISSING,
                f"Rekening {code} {name} ontbreekt in je grootboek, dus deze factuur kan niet automatisch "
                "geboekt worden. Leg hem vast met een handmatige boeking.",
            )
    return AccountIds(creditors=ids[CREDITORS_CODE], vat_receivable=ids[VAT_RECEIVABLE_CODE])


def _journal_id(session: Session) -> int:
    journal_id = default_journal_id(session, "inkoop")
    if journal_id is None:
        raise BookingError(NO_JOURNAL, NO_JOURNAL_MESSAGE)
    return journal_id


def _not_storno_d():
    return ~exists().where(JournalEntry.reverses_entry_id == PurchaseInvoice.journal_entry_id)


def _check_duplicate(session: Session, data: BookingInput) -> None:
    found = session.scalar(
        select(PurchaseInvoice.id).where(
            PurchaseInvoice.contact_id == data.contact_id,
            PurchaseInvoice.invoice_number_key == invoice_number_key(data.number),
            _not_storno_d(),
        )
    )
    if found is not None:
        raise BookingError(
            DUPLICATE_INVOICE,
            duplicate_message(data.supplier_name or "deze leverancier", data.number),
            field="invoice_number",
        )


def _open_transaction(session: Session) -> None:
    # pysqlite only opens a transaction on DML; without it the savepoint below would be
    # the outermost transaction and its RELEASE would commit (see documents.service).
    session.execute(update(Document).where(Document.id.is_(None)).values(status=Document.status))


# --- booking ---------------------------------------------------------------------------------------
def book_extraction(session: Session, document_id: int) -> PurchaseInvoice:
    """Book a nagekeken extraction: entry in IK, inkoopfactuur, document geboekt, leerfunctie.

    Raises DocumentNotFoundError (404), BookingError, or the ledger's LedgerError (locked
    period, inactive rekening, ...). Nothing is persisted on failure.
    """
    document = get_document(session, document_id)
    if document.status == "geboekt":
        raise BookingError(ALREADY_BOOKED, ALREADY_BOOKED_MESSAGE)
    extraction = _find_extraction(session, document_id)
    if extraction is None:
        raise BookingError(NOT_REVIEWED, NOT_REVIEWED_MESSAGE)
    data = _booking_input(session, document, extraction)
    check_bookable(data)
    new_entry = build_entry(data, _system_accounts(session), _journal_id(session))
    _check_duplicate(session, data)

    _open_transaction(session)
    try:
        with session.begin_nested():
            entry = post_entry(session, new_entry)
            invoice = PurchaseInvoice(
                document_id=document.id,
                contact_id=data.contact_id,
                journal_entry_id=entry.id,
                invoice_number=data.number,
                invoice_number_key=invoice_number_key(data.number),
                invoice_date=data.invoice_date,
                due_date=data.due_date,
                kind=data.booking_kind,
                total_excl_cents=data.total_excl_cents,
                total_vat_cents=data.total_vat_cents,
                total_incl_cents=data.total_incl_cents,
                paid_cents=0,
                created_at=_now(),
            )
            session.add(invoice)
            session.flush()
            # The one allowed update of a booking: its source link, right after posting.
            entry.source_type = SOURCE_TYPE
            entry.source_id = invoice.id
            session.flush()
            mark_booked(session, document.id, entry.id)
            record_booking(session, data.contact_id, data.lines)
    except IntegrityError as exc:  # a parallel submit of the same document won the race
        raise BookingError(ALREADY_BOOKED, ALREADY_BOOKED_MESSAGE) from exc
    return invoice


# --- preview -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BookingPreview:
    """What 'Goedkeuren en boeken' would do; `error` is the first reason it cannot (yet)."""

    document_id: int
    rows: list[PreviewRow]
    supplier_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    total_incl_cents: int | None
    journal_code: str | None
    period_label: str | None
    warnings: list[str] = field(default_factory=list)
    kind: str = "invoice"  # invoice | credit_note
    due_date: date | None = None
    total_excl_cents: int | None = None
    total_vat_cents: int | None = None
    journal_name: str | None = None
    summary: str | None = None  # "Kosten € 100,00, BTW € 21,00, nog te betalen aan ..."
    error: LedgerError | None = None

    @property
    def can_book(self) -> bool:
        return self.error is None

    @property
    def needs_review(self) -> bool:
        """Not nagekeken yet: show 'Eerst nakijken' with a link back."""
        return self.error is not None and self.error.code == NOT_REVIEWED


def period_label(day: date) -> str:
    return f"{_MONTHS[day.month - 1]} {day.year}"


def prepare_booking(session: Session, document_id: int) -> BookingPreview:
    """Read-only preview for the booking screen. Raises only DocumentNotFoundError."""
    document = get_document(session, document_id)
    extraction = _find_extraction(session, document_id)
    if extraction is None:
        error = (
            BookingError(ALREADY_BOOKED, ALREADY_BOOKED_MESSAGE)
            if document.status == "geboekt"
            else BookingError(NOT_REVIEWED, NOT_REVIEWED_MESSAGE)
        )
        return BookingPreview(
            document_id=document.id, rows=[], supplier_name=None, invoice_number=None,
            invoice_date=None, total_incl_cents=None, journal_code=None, period_label=None,
            error=error,
        )
    data = _booking_input(session, document, extraction)
    errors: list[LedgerError] = []

    def attempt(fn):
        try:
            return fn()
        except LedgerError as exc:
            errors.append(exc)
            return None

    attempt(lambda: check_state(data))
    table = None
    content_ok = attempt(lambda: check_content(data) or True)
    accounts = attempt(lambda: _system_accounts(session))
    if content_ok and accounts is not None:
        table = attempt(lambda: preview_lines(data, accounts, _account_labels(session), _vat_labels(session)))
    journal = None
    journal_id = attempt(lambda: _journal_id(session))
    if journal_id is not None:
        journal = session.get(Journal, journal_id)
    label = None
    if data.invoice_date is not None:
        label = period_label(data.invoice_date)
        attempt(lambda: _find_period(session, data.invoice_date))
    if table is not None:
        entry = build_entry(data, accounts, journal_id or 0)
        attempt(lambda: _check_accounts(session, entry.lines, check_active=True))
        attempt(lambda: _check_vat_codes(session, entry.lines, check_active=True))
    if content_ok:
        attempt(lambda: _check_duplicate(session, data))

    warnings = []
    flags = flagged_count(extraction)
    if flags:
        warnings.append(
            f"Bij het nakijken {'is' if flags == 1 else 'zijn'} {flags} "
            f"{'punt' if flags == 1 else 'punten'} gemarkeerd om te controleren. "
            "Twijfel je? Kijk de factuur dan nog even na."
        )
    if data.booking_kind == CREDIT_NOTE:
        warnings.append("Dit is een creditnota: je krijgt geld terug van de leverancier.")

    return BookingPreview(
        document_id=document.id,
        rows=table.rows if table else [],
        supplier_name=data.supplier_name,
        invoice_number=data.number or None,
        invoice_date=data.invoice_date,
        total_incl_cents=data.total_incl_cents,
        journal_code=journal.code if journal else None,
        journal_name=journal.name if journal else None,
        period_label=label,
        warnings=warnings,
        kind=data.booking_kind,
        due_date=data.due_date,
        total_excl_cents=data.total_excl_cents,
        total_vat_cents=data.total_vat_cents,
        summary=table.summary if table else None,
        error=_first_error(errors),
    )


def _first_error(errors: list[LedgerError]) -> LedgerError | None:
    """The state errors (already booked, not reviewed) win; otherwise the first one found."""
    for code in (ALREADY_BOOKED, NOT_REVIEWED):
        for e in errors:
            if e.code == code:
                return e
    return errors[0] if errors else None


def _account_labels(session: Session) -> dict[int, tuple[str, str]]:
    return {id_: (code, name) for id_, code, name in session.execute(select(Account.id, Account.code, Account.name))}


def _vat_labels(session: Session) -> dict[str, str]:
    labels = {}
    for code, rate_bp in session.execute(select(VatCode.code, VatCode.rate_bp)):
        whole, rest = divmod(rate_bp, 100)
        labels[code] = f"{whole}%" if not rest else f"{whole},{rest:02d}".rstrip("0") + "%"
    return labels


# --- lookups -----------------------------------------------------------------------------------------
def find_invoice_for_document(session: Session, document_id: int) -> PurchaseInvoice | None:
    return session.scalar(select(PurchaseInvoice).where(PurchaseInvoice.document_id == document_id))


def find_invoice_for_entry(session: Session, entry_id: int) -> PurchaseInvoice | None:
    return session.scalar(select(PurchaseInvoice).where(PurchaseInvoice.journal_entry_id == entry_id))


# --- crediteuren overview ---------------------------------------------------------------------------------
def open_amount(kind: str, total_incl_cents: int, paid_cents: int) -> int:
    """Still to pay; negative for a creditnota (it reduces what you owe)."""
    amount = total_incl_cents - paid_cents
    return -amount if kind == CREDIT_NOTE else amount


def invoice_status(*, open_cents: int, reversed: bool) -> str:
    """'gestorneerd' | 'betaald' | 'open' (derived at read time)."""
    if reversed:
        return "gestorneerd"
    return "open" if open_cents else "betaald"


@dataclass(frozen=True)
class InvoiceRow:
    id: int
    document_id: int
    journal_entry_id: int
    entry_number: str
    contact_id: int
    supplier_name: str
    invoice_number: str
    invoice_date: date
    due_date: date | None
    kind: str
    total_cents: int  # negative for a creditnota
    open_cents: int  # 0 when gestorneerd or betaald; negative for a creditnota
    status: str  # open | betaald | gestorneerd
    is_overdue: bool  # open and past the vervaldatum
    storno_entry_id: int | None = None

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


@dataclass(frozen=True)
class SupplierOpenRow:
    contact_id: int
    supplier_name: str
    invoice_count: int
    open_cents: int
    overdue_count: int


@dataclass(frozen=True)
class OpenOverview:
    rows: list[SupplierOpenRow]
    total_open_cents: int  # Totaal openstaand
    open_count: int  # Aantal open facturen
    supplier_count: int  # Leveranciers met openstaand


def _invoice_query(q: str | None, open_only: bool):
    storno = aliased(JournalEntry)
    entry = aliased(JournalEntry)
    stmt = (
        select(PurchaseInvoice, Contact.name, entry.entry_number, storno.id)
        .join(Contact, Contact.id == PurchaseInvoice.contact_id)
        .join(entry, entry.id == PurchaseInvoice.journal_entry_id)
        .outerjoin(storno, storno.reverses_entry_id == PurchaseInvoice.journal_entry_id)
    )
    needle = (q or "").strip()
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                Contact.name.ilike(pattern, escape="\\"),
                PurchaseInvoice.invoice_number.ilike(pattern, escape="\\"),
            )
        )
    if open_only:
        stmt = stmt.where(storno.id.is_(None), PurchaseInvoice.total_incl_cents != PurchaseInvoice.paid_cents)
    return stmt


def _row(pi: PurchaseInvoice, name: str, entry_number: str, storno_id: int | None, today: date) -> InvoiceRow:
    reversed_ = storno_id is not None
    open_cents = 0 if reversed_ else open_amount(pi.kind, pi.total_incl_cents, pi.paid_cents)
    status = invoice_status(open_cents=open_cents, reversed=reversed_)
    return InvoiceRow(
        id=pi.id,
        document_id=pi.document_id,
        journal_entry_id=pi.journal_entry_id,
        entry_number=entry_number,
        contact_id=pi.contact_id,
        supplier_name=name,
        invoice_number=pi.invoice_number,
        invoice_date=pi.invoice_date,
        due_date=pi.due_date,
        kind=pi.kind,
        total_cents=-pi.total_incl_cents if pi.kind == CREDIT_NOTE else pi.total_incl_cents,
        open_cents=open_cents,
        status=status,
        is_overdue=status == "open" and pi.due_date is not None and pi.due_date < today,
        storno_entry_id=storno_id,
    )


def list_invoices(
    session: Session,
    q: str | None = None,
    tab: str = "all",
    page: int = 1,
    per_page: int = 50,
    today: date | None = None,
) -> Page:
    """Inkoopfacturen, newest first. tab 'open' hides betaald/gestorneerd. Items are InvoiceRow."""
    today = today or date.today()
    stmt = _invoice_query(q, open_only=tab == "open")
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    page = min(max(1, page), max(1, -(-total // per_page)))  # beyond the last page shows the last page
    rows = session.execute(
        stmt.order_by(PurchaseInvoice.invoice_date.desc(), PurchaseInvoice.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()
    return Page(items=[_row(*r, today) for r in rows], page=page, per_page=per_page, total=total)


def open_by_supplier(session: Session, q: str | None = None, today: date | None = None) -> OpenOverview:
    """What is still to be paid, per leverancier (largest amount first), plus the totals."""
    today = today or date.today()
    per_supplier: dict[int, dict] = {}
    for r in session.execute(_invoice_query(q, open_only=True)).all():
        row = _row(*r, today)
        s = per_supplier.setdefault(
            row.contact_id, dict(name=row.supplier_name, count=0, open=0, overdue=0)
        )
        s["count"] += 1
        s["open"] += row.open_cents
        s["overdue"] += int(row.is_overdue)
    rows = sorted(
        (
            SupplierOpenRow(cid, s["name"], s["count"], s["open"], s["overdue"])
            for cid, s in per_supplier.items()
            if s["open"]
        ),
        key=lambda r: (-r.open_cents, r.supplier_name.lower()),
    )
    return OpenOverview(
        rows=rows,
        total_open_cents=sum(r.open_cents for r in rows),
        open_count=sum(r.invoice_count for r in rows),
        supplier_count=len(rows),
    )
