"""Beginbalans (DB service): book, correct (storno + new) and read the opening balance.

Functions flush but never commit; the caller commits on success. `book_opening_balance`
does all its writes inside one savepoint, so after a failure nothing of it remains (and
no entry number is used), even if the caller commits anyway.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, aliased

from app.domain.ledger import default_journal_id, post_entry, reverse_entry
from app.domain.opening.build import (
    CREDITEUR,
    DEBITEUR,
    SIDES,
    AccountRef,
    OpeningInput,
    OpeningItemInput,
    OpeningSummary,
    SystemIds,
    row_labels,
    build_entry,
    check_input,
    invoice_number_key,
    item_error,
    merged_balances,
    summarize,
)
from app.domain.opening.errors import (
    ITEM_PAID,
    NO_FISCAL_YEAR,
    NO_FISCAL_YEAR_MESSAGE,
    NO_JOURNAL,
    NO_JOURNAL_MESSAGE,
    NOT_FIRST_YEAR,
    SYSTEM_ACCOUNT_MISSING,
    UNCHANGED,
    UNCHANGED_MESSAGE,
    OpeningError,
    item_paid_message,
    not_first_year_message,
)
from app.models import Account, Contact, FiscalYear, JournalEntry, JournalLine, OpeningItem, Period

SOURCE_TYPE = "beginbalans"
DEBTORS_CODE = "1300"
CREDITORS_CODE = "3000"
EQUITY_CODE = "2000"
_SYSTEM_CODES = (DEBTORS_CODE, CREDITORS_CODE, EQUITY_CODE)
_TYPE_ORDER = ("asset", "liability")
STATUS_LABELS = {"open": "Open", "betaald": "Betaald", "vervangen": "Vervangen"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- read models ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OpeningBalanceRow:
    account_id: int
    code: str
    name: str
    type: str  # asset | liability
    amount_cents: int  # as entered: > 0 normal, < 0 e.g. bank rood / afschrijvingen


@dataclass(frozen=True)
class OpeningItemRow:
    id: int
    side: str  # debiteur | crediteur
    contact_id: int
    relation_name: str
    invoice_number: str
    invoice_date: date
    due_date: date | None
    amount_cents: int
    paid_cents: int
    open_cents: int  # 0 when betaald or vervangen
    status: str  # open | betaald | vervangen
    is_overdue: bool  # open and past the vervaldatum
    journal_entry_id: int

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


@dataclass(frozen=True)
class OpeningView:
    fiscal_year_id: int
    year: int
    start_date: date
    entry_id: int
    entry_number: str
    balances: list[OpeningBalanceRow]
    items: list[OpeningItemRow]
    assets_cents: int  # totaal bezittingen (incl. debiteuren)
    liabilities_cents: int  # totaal schulden (incl. crediteuren)
    equity_cents: int  # eigen vermogen (berekend)
    period_locked: bool = False  # first period locked: read-only, no aanpassen

    def to_input(self) -> OpeningInput:
        """The input that produced this beginbalans (to prefill the form)."""
        return OpeningInput(
            balances=[(b.account_id, b.amount_cents) for b in self.balances],
            items=[
                OpeningItemInput(i.side, i.contact_id, i.invoice_number, i.invoice_date, i.due_date, i.amount_cents)
                for i in self.items
            ],
        )


# --- lookups -------------------------------------------------------------------------------
def first_fiscal_year(session: Session) -> FiscalYear | None:
    """The earliest boekjaar: the only one that gets a beginbalans."""
    return session.scalar(select(FiscalYear).order_by(FiscalYear.start_date, FiscalYear.year).limit(1))


def first_period_locked(session: Session) -> bool:
    """True when the first period of the first boekjaar is locked (beginbalans read-only)."""
    fy = first_fiscal_year(session)
    if fy is None:
        return False
    status = session.scalar(
        select(Period.status).where(Period.fiscal_year_id == fy.id, Period.start_date <= fy.start_date,
                                    Period.end_date >= fy.start_date)
    )
    return status is not None and status != "open"


def allowed_accounts(session: Session) -> list[AccountRef]:
    """Active, postable asset/liability accounts except 1300/3000; assets first, by code."""
    accounts = session.scalars(
        select(Account).where(
            Account.is_active.is_(True),
            Account.is_postable.is_(True),
            Account.type.in_(_TYPE_ORDER),
            Account.code.not_in((DEBTORS_CODE, CREDITORS_CODE)),
        )
    )
    refs = [AccountRef(a.id, a.code, a.name, a.type) for a in accounts]
    return sorted(refs, key=lambda r: (_TYPE_ORDER.index(r.type), r.code))


def _system_ids(session: Session) -> SystemIds:
    ids = dict(session.execute(select(Account.code, Account.id).where(Account.code.in_(_SYSTEM_CODES))).all())
    for code, name in ((DEBTORS_CODE, "Debiteuren"), (CREDITORS_CODE, "Crediteuren"),
                       (EQUITY_CODE, "Ondernemingsvermogen / Kapitaal")):
        if code not in ids:
            raise OpeningError(
                SYSTEM_ACCOUNT_MISSING,
                f"Rekening {code} {name} ontbreekt in je grootboek, dus de beginbalans kan niet "
                "automatisch geboekt worden. Leg hem vast met een handmatige boeking in het memoriaal.",
            )
    return SystemIds(debtors=ids[DEBTORS_CODE], creditors=ids[CREDITORS_CODE], equity=ids[EQUITY_CODE])


def _account_labels(session: Session, ids) -> dict[int, AccountRef]:
    return {
        a.id: AccountRef(a.id, a.code, a.name, a.type)
        for a in session.scalars(select(Account).where(Account.id.in_(list(ids))))
    }


def _active_entry(session: Session, fiscal_year_id: int) -> JournalEntry | None:
    storno = aliased(JournalEntry)
    return session.scalar(
        select(JournalEntry)
        .outerjoin(storno, storno.reverses_entry_id == JournalEntry.id)
        .where(
            JournalEntry.kind == "opening",
            JournalEntry.source_type == SOURCE_TYPE,
            JournalEntry.source_id == fiscal_year_id,
            storno.id.is_(None),
        )
        .order_by(JournalEntry.id.desc())
        .limit(1)
    )


def _require_year(session: Session, year: int | None) -> FiscalYear:
    fy = first_fiscal_year(session)
    if fy is None:
        raise OpeningError(NO_FISCAL_YEAR, NO_FISCAL_YEAR_MESSAGE)
    if year is not None and year != fy.year:
        raise OpeningError(NOT_FIRST_YEAR, not_first_year_message(year, fy.year))
    return fy


# --- items -----------------------------------------------------------------------------------
def _item_query():
    storno = aliased(JournalEntry)
    return (
        select(OpeningItem, Contact.name, storno.id)
        .join(Contact, Contact.id == OpeningItem.contact_id)
        .outerjoin(storno, storno.reverses_entry_id == OpeningItem.journal_entry_id)
    )


def _item_row(item: OpeningItem, name: str, storno_id: int | None, today: date) -> OpeningItemRow:
    replaced = storno_id is not None
    open_cents = 0 if replaced else item.amount_cents - item.paid_cents
    status = "vervangen" if replaced else ("open" if open_cents else "betaald")
    return OpeningItemRow(
        id=item.id,
        side=item.side,
        contact_id=item.contact_id,
        relation_name=name,
        invoice_number=item.invoice_number,
        invoice_date=item.invoice_date,
        due_date=item.due_date,
        amount_cents=item.amount_cents,
        paid_cents=item.paid_cents,
        open_cents=open_cents,
        status=status,
        is_overdue=status == "open" and item.due_date is not None and item.due_date < today,
        journal_entry_id=item.journal_entry_id,
    )


def list_opening_items(
    session: Session, side: str, open_only: bool = True, *, today: date | None = None
) -> list[OpeningItemRow]:
    """Openstaande posten of the beginbalans for one side, oldest invoice first.

    open_only: only posten of the active beginbalans with something left to pay.
    """
    today = today or date.today()
    stmt = _item_query().where(OpeningItem.side == side)
    rows = [
        _item_row(i, n, s, today)
        for i, n, s in session.execute(stmt.order_by(OpeningItem.invoice_date, OpeningItem.id)).all()
    ]
    return [r for r in rows if r.status == "open"] if open_only else rows


# --- read model ------------------------------------------------------------------------------
def get_opening_balance(session: Session, *, today: date | None = None) -> OpeningView | None:
    """The active beginbalans of the first boekjaar, or None when there is none."""
    fy = first_fiscal_year(session)
    if fy is None:
        return None
    entry = _active_entry(session, fy.id)
    if entry is None:
        return None
    today = today or date.today()
    lines = session.execute(
        select(JournalLine, Account)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry.id)
        .order_by(JournalLine.line_no)
    ).all()
    per_account: dict[int, tuple[Account, int]] = {}
    for line, account in lines:
        if account.code in _SYSTEM_CODES:
            continue
        sign = 1 if account.type == "asset" else -1
        _, amount = per_account.get(account.id, (account, 0))
        per_account[account.id] = (account, amount + sign * (line.debit_cents - line.credit_cents))
    balances = sorted(
        (OpeningBalanceRow(a.id, a.code, a.name, a.type, amt) for a, amt in per_account.values() if amt),
        key=lambda b: (_TYPE_ORDER.index(b.type) if b.type in _TYPE_ORDER else 9, b.code),
    )
    items = [
        _item_row(i, n, s, today)
        for i, n, s in session.execute(
            _item_query().where(OpeningItem.journal_entry_id == entry.id).order_by(OpeningItem.id)
        ).all()
    ]
    items.sort(key=lambda r: SIDES.index(r.side))
    assets = sum(b.amount_cents for b in balances if b.type == "asset") + sum(
        i.amount_cents for i in items if i.side == DEBITEUR
    )
    liabilities = sum(b.amount_cents for b in balances if b.type == "liability") + sum(
        i.amount_cents for i in items if i.side == CREDITEUR
    )
    return OpeningView(
        fiscal_year_id=fy.id,
        year=fy.year,
        start_date=fy.start_date,
        entry_id=entry.id,
        entry_number=entry.entry_number,
        balances=balances,
        items=items,
        assets_cents=assets,
        liabilities_cents=liabilities,
        equity_cents=assets - liabilities,
        period_locked=first_period_locked(session),
    )


def preview(session: Session, data: OpeningInput) -> OpeningSummary:
    """Totals for the live summary; never raises for incomplete rows."""
    return summarize(data, {a.id: a for a in allowed_accounts(session)})


# --- booking ---------------------------------------------------------------------------------
def _contacts(session: Session, data: OpeningInput) -> dict[int, Contact]:
    """Load the relaties of the posten; raise for an unknown or archived one."""
    ids = {i.contact_id for i in data.items if i.contact_id is not None}
    found = {c.id: c for c in session.scalars(select(Contact).where(Contact.id.in_(ids)))} if ids else {}
    for label, item in zip(row_labels(data.items), data.items):
        if item.contact_id is None:
            continue  # check_input reports it
        contact = found.get(item.contact_id)
        if contact is None:
            raise item_error(label, "Deze relatie bestaat niet meer. Kies een andere relatie.")
        if not contact.is_active:
            raise item_error(
                label,
                f"Relatie {contact.name} is gearchiveerd. Zet de relatie weer aan onder Relaties "
                "of kies een andere.",
            )
    return found


def _normalized(data: OpeningInput):
    balances = tuple(sorted(merged_balances(data.balances).items()))
    items = tuple(
        sorted(
            (i.side, i.contact_id, i.invoice_number.strip(), i.invoice_date, i.due_date, i.amount_cents)
            for i in data.items
        )
    )
    return balances, items


def _set_contact_flags(session: Session, data: OpeningInput, contacts: dict[int, Contact]) -> None:
    """A debiteur post makes the relatie a klant, a crediteur post a leverancier."""
    for item in data.items:
        contact = contacts[item.contact_id]
        attr = "is_customer" if item.side == DEBITEUR else "is_supplier"
        if not getattr(contact, attr):
            setattr(contact, attr, True)
            contact.updated_at = _now()
    session.flush()


def _open_transaction(session: Session) -> None:
    # pysqlite only opens a transaction on DML; without it the savepoint below would be
    # the outermost transaction and its RELEASE would commit (see documents.service).
    session.execute(update(FiscalYear).where(FiscalYear.id.is_(None)).values(status=FiscalYear.status))


def book_opening_balance(session: Session, data: OpeningInput, *, year: int | None = None) -> JournalEntry:
    """Book the beginbalans of the first boekjaar; when one exists, replace it (storno + new).

    `year`, if given, must be the first boekjaar (else NOT_FIRST_YEAR). Raises OpeningError
    or the ledger's LedgerError (locked period, inactive rekening). Nothing persists on failure.
    """
    fy = _require_year(session, year)
    journal_id = default_journal_id(session, "memoriaal")
    if journal_id is None:
        raise OpeningError(NO_JOURNAL, NO_JOURNAL_MESSAGE)
    allowed = {a.id: a for a in allowed_accounts(session)}
    contacts = _contacts(session, data)
    names = {cid: c.name for cid, c in contacts.items()}
    check_input(
        data,
        allowed,
        fy.start_date,
        contact_names=names,
        account_labels=_account_labels(session, merged_balances(data.balances)),
    )
    new_entry = build_entry(data, allowed, _system_ids(session), journal_id, fy.year, fy.start_date, names)

    old = _active_entry(session, fy.id)
    if old is not None:
        current = get_opening_balance(session)
        if current is not None and _normalized(current.to_input()) == _normalized(data):
            raise OpeningError(UNCHANGED, UNCHANGED_MESSAGE)
        for item in session.scalars(
            select(OpeningItem).where(OpeningItem.journal_entry_id == old.id).order_by(OpeningItem.id)
        ):
            if item.paid_cents > 0:
                raise OpeningError(ITEM_PAID, item_paid_message(item.invoice_number))

    _open_transaction(session)
    with session.begin_nested():
        if old is not None:
            reverse_entry(
                session,
                old.id,
                booking_date=fy.start_date,
                description=f"Storno beginbalans {fy.year} (aangepast)",
            )
        entry = post_entry(session, new_entry)
        # The one allowed update of a booking: its source link, right after posting.
        entry.source_type = SOURCE_TYPE
        entry.source_id = fy.id
        session.flush()
        now = _now()
        for item in data.items:
            number = item.invoice_number.strip()
            session.add(
                OpeningItem(
                    fiscal_year_id=fy.id,
                    journal_entry_id=entry.id,
                    contact_id=item.contact_id,
                    side=item.side,
                    invoice_number=number,
                    invoice_number_key=invoice_number_key(number),
                    invoice_date=item.invoice_date,
                    due_date=item.due_date,
                    amount_cents=item.amount_cents,
                    paid_cents=0,
                    created_at=now,
                )
            )
        session.flush()
        _set_contact_flags(session, data, contacts)
    return entry
