"""Bank reconciliation (afletteren), DB service.

All functions flush but never commit; the caller commits on success. `book` and `undo` do
all their writes inside one savepoint, so after a failure nothing of them remains.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.bank.iban import normalize_iban
from app.domain.bank.service import _amount_candidates, _like
from app.domain.ledger import Page, post_entry, reverse_entry, suggest_vat_code
from app.domain.opening.service import list_opening_items
from app.domain.purchase.booking import CREDIT_NOTE, is_supported_vat
from app.domain.purchase.service import open_amount
from app.domain.sales import service as sales_service
from app.domain.reconcile import rules as rules_mod
from app.domain.reconcile.entries import SystemAccounts, build_payment_entry
from app.domain.reconcile.errors import (
    ALREADY_PROCESSED,
    ALREADY_PROCESSED_MESSAGE,
    DUPLICATE_ITEM,
    IGNORED,
    INVALID_AMOUNT,
    ITEM_NOT_FOUND,
    NOT_BOOKED,
    NOT_FOUND,
    NOT_IGNORED,
    RULE_INVALID,
    SUGGESTION_GONE,
    SYSTEM_ACCOUNT_MISSING,
    ReconcileError,
    over_allocated,
)
from app.domain.reconcile.invoice_payments import InvoiceView, PaymentCandidate, payment_candidates
from app.domain.reconcile.matching import suggest
from app.domain.reconcile.types import (
    SIDE_CREDITOR,
    SIDE_DEBTOR,
    SOURCE_OPENING_ITEM,
    SOURCE_PURCHASE_INVOICE,
    SOURCE_SALES_INVOICE,
    SOURCES,
    Allocation,
    AllocationLine,
    DirectLine,
    OpenItem,
    RuleDraft,
    Suggestion,
    TxnView,
)
from app.models import (
    Account,
    BankAccount,
    BankMatch,
    BankTransaction,
    Contact,
    JournalEntry,
    JournalLine,
    OpeningItem,
    Period,
    PurchaseInvoice,
    SalesInvoice,
    VatCode,
)

CREDITORS_CODE = "3000"
DEBTORS_CODE = "1300"
VAT_RECEIVABLE_CODE = "1400"
STATUS_NEW, STATUS_BOOKED, STATUS_IGNORED = "nieuw", "geboekt", "genegeerd"
STATUS_LABELS = {STATUS_NEW: "Te verwerken", STATUS_BOOKED: "Geboekt", STATUS_IGNORED: "Genegeerd"}
DIRECTIONS = ("af", "bij")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- open items (providers) ---------------------------------------------------------------------
def _purchase_items(session: Session, side: str) -> list[OpenItem]:
    """Open inkoopfacturen and creditnota's that are not storno'd (as `open_by_supplier`)."""
    if side != "crediteur":
        return []
    storno = exists().where(JournalEntry.reverses_entry_id == PurchaseInvoice.journal_entry_id)
    rows = session.execute(
        select(PurchaseInvoice, Contact.name, Contact.iban)
        .join(Contact, Contact.id == PurchaseInvoice.contact_id)
        .where(~storno, PurchaseInvoice.total_incl_cents != PurchaseInvoice.paid_cents)
        .order_by(PurchaseInvoice.invoice_date, PurchaseInvoice.id)
    ).all()
    items = []
    for pi, name, iban in rows:
        open_cents = open_amount(pi.kind, pi.total_incl_cents, pi.paid_cents)
        items.append(
            OpenItem(
                source=SOURCE_PURCHASE_INVOICE, source_id=pi.id, contact_id=pi.contact_id,
                contact_name=name, iban=iban, number=pi.invoice_number, date=pi.invoice_date,
                due_date=pi.due_date, open_cents=abs(open_cents), is_credit=pi.kind == CREDIT_NOTE,
            )
        )
    return items


def _sales_items(session: Session, side: str) -> list[OpenItem]:
    """Open verkoopfacturen and creditnota's with something left (not storno'd), using the sales
    service's own definition of 'open' (paid, refunded and set-off amounts)."""
    if side != SIDE_DEBTOR:
        return []
    storno = exists().where(JournalEntry.reverses_entry_id == SalesInvoice.journal_entry_id)
    rows = session.execute(
        select(SalesInvoice, Contact.name, Contact.iban)
        .join(Contact, Contact.id == SalesInvoice.contact_id)
        .where(
            SalesInvoice.status == sales_service.DEFINITIEF,
            ~storno,
            SalesInvoice.total_incl_cents > SalesInvoice.paid_cents,
        )
        .order_by(SalesInvoice.invoice_date, SalesInvoice.id)
    ).all()
    if not rows:
        return []
    to_invoice, by_credit = sales_service._applied_maps(session)
    items = []
    for inv, name, iban in rows:
        credit = inv.kind == sales_service.CREDIT_NOTE
        applied = (by_credit if credit else to_invoice).get(inv.id, 0)
        open_cents = sales_service.open_cents_of(inv.kind, inv.total_incl_cents, inv.paid_cents, applied)
        if open_cents <= 0:
            continue
        items.append(
            OpenItem(
                source=SOURCE_SALES_INVOICE, source_id=inv.id, contact_id=inv.contact_id,
                contact_name=name, iban=iban, number=inv.number, date=inv.invoice_date,
                due_date=inv.due_date, open_cents=open_cents, is_credit=credit, side=SIDE_DEBTOR,
            )
        )
    return items


def _opening_items(session: Session, side: str) -> list[OpenItem]:
    if side not in (SIDE_CREDITOR, SIDE_DEBTOR):
        return []
    rows = list_opening_items(session, side, open_only=True)
    ibans = {}
    if rows:
        ibans = dict(
            session.execute(select(Contact.id, Contact.iban).where(Contact.id.in_({r.contact_id for r in rows}))).all()
        )
    return [
        OpenItem(
            source=SOURCE_OPENING_ITEM, source_id=r.id, contact_id=r.contact_id,
            contact_name=r.relation_name, iban=ibans.get(r.contact_id), number=r.invoice_number,
            date=r.invoice_date, due_date=r.due_date, open_cents=r.open_cents, is_credit=False, side=side,
        )
        for r in rows
    ]


PROVIDERS: list[Callable[[Session, str], list[OpenItem]]] = [_purchase_items, _opening_items, _sales_items]


def list_open_items(
    session: Session, side: str = "crediteur", contact_id: int | None = None, q: str | None = None
) -> list[OpenItem]:
    """Everything still to pay (or to get refunded) on one side, oldest first."""
    items = [i for provider in PROVIDERS for i in provider(session, side)]
    if contact_id is not None:
        items = [i for i in items if i.contact_id == contact_id]
    needle = (q or "").strip().casefold()
    if needle:
        items = [i for i in items if needle in i.contact_name.casefold() or needle in i.number.casefold()]
    return sorted(items, key=lambda i: (i.date, i.source, i.source_id))


def list_all_open_items(
    session: Session, contact_id: int | None = None, q: str | None = None
) -> list[OpenItem]:
    """Open items of both sides (crediteuren and debiteuren), oldest first."""
    items = list_open_items(session, SIDE_CREDITOR, contact_id, q) + list_open_items(
        session, SIDE_DEBTOR, contact_id, q
    )
    return sorted(items, key=lambda i: (i.date, i.source, i.source_id))


def _find_item(session: Session, source: str, source_id: int, side: str = "crediteur") -> OpenItem | None:
    for item in list_open_items(session, side):
        if item.ref == (source, source_id):
            return item
    return None


# --- loading ---------------------------------------------------------------------------------------
def _txn(session: Session, txn_id: int) -> BankTransaction:
    txn = session.get(BankTransaction, txn_id)
    if txn is None:
        raise ReconcileError(NOT_FOUND, "Deze mutatie bestaat niet (meer). Ga terug naar het overzicht.")
    return txn


def to_view(t: BankTransaction) -> TxnView:
    return TxnView(
        id=t.id, booking_date=t.booking_date, amount_cents=t.amount_cents,
        counterparty_name=t.counterparty_name, counterparty_iban=t.counterparty_iban,
        description=t.description or "", bank_reference=t.bank_reference,
    )


def _system_accounts(session: Session, need_debtors: bool = False) -> SystemAccounts:
    ids = dict(
        session.execute(
            select(Account.code, Account.id).where(
                Account.code.in_((CREDITORS_CODE, VAT_RECEIVABLE_CODE, DEBTORS_CODE))
            )
        ).all()
    )
    needed = [(CREDITORS_CODE, "Crediteuren"), (VAT_RECEIVABLE_CODE, "BTW voorbelasting")]
    if need_debtors:
        needed.append((DEBTORS_CODE, "Debiteuren"))
    for code, name in needed:
        if code not in ids:
            raise ReconcileError(
                SYSTEM_ACCOUNT_MISSING,
                f"Rekening {code} {name} ontbreekt in je grootboek, dus deze mutatie kan niet "
                "automatisch geboekt worden. Leg hem vast met een handmatige boeking.",
            )
    return SystemAccounts(
        creditors=ids[CREDITORS_CODE], vat_receivable=ids[VAT_RECEIVABLE_CODE], debtors=ids.get(DEBTORS_CODE)
    )


def _supported_vat_rates(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(VatCode.code, VatCode.rate_bp, VatCode.purchase_rubriek).where(VatCode.is_active.is_(True))
    ).all()
    rubrieken = {code: rub for code, _, rub in rows}
    return {code: rate for code, rate, _ in rows if is_supported_vat(code, rubrieken)}


def _open_transaction(session: Session) -> None:
    # pysqlite only opens a transaction on DML; without it the savepoint below would be
    # the outermost transaction and its RELEASE would commit (see purchase.service).
    session.execute(update(BankTransaction).where(BankTransaction.id.is_(None)).values(status=BankTransaction.status))


def _status_error(status: str) -> ReconcileError:
    if status == STATUS_IGNORED:
        return ReconcileError(
            IGNORED, "Deze mutatie is genegeerd. Zet hem eerst terug als je hem toch wilt boeken."
        )
    return ReconcileError(ALREADY_PROCESSED, ALREADY_PROCESSED_MESSAGE)


# --- suggestions ---------------------------------------------------------------------------------------
def suggestions_for(session: Session, txn_id: int) -> list[Suggestion]:
    """Best first; empty for a transaction that is not `nieuw`."""
    txn = _txn(session, txn_id)
    if txn.status != STATUS_NEW:
        return []
    return suggest(
        to_view(txn),
        list_all_open_items(session),
        rules_mod.active_rule_views(session),
    )


@dataclass(frozen=True)
class ReconcileRow:
    id: int
    bank_account_id: int
    bank_account_name: str
    booking_date: date
    counterparty_name: str | None
    counterparty_iban: str | None
    description: str
    amount_cents: int  # signed: negative = af
    status: str
    suggestion: Suggestion | None = None

    @property
    def direction(self) -> str:
        return "af" if self.amount_cents < 0 else "bij"

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


def _filtered_transactions(*, bank_account_id: int | None, q: str | None, direction: str | None, status: str):
    stmt = select(BankTransaction, BankAccount.name).join(
        BankAccount, BankAccount.id == BankTransaction.bank_account_id
    )
    stmt = stmt.where(BankTransaction.status == status)
    if bank_account_id is not None:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if direction == "af":
        stmt = stmt.where(BankTransaction.amount_cents < 0)
    elif direction == "bij":
        stmt = stmt.where(BankTransaction.amount_cents > 0)
    term = " ".join((q or "").split())
    if term:
        conditions = [
            _like(BankTransaction.counterparty_name, term),
            _like(BankTransaction.description, term),
            _like(BankTransaction.counterparty_iban, normalize_iban(term) or term),
        ]
        amounts = _amount_candidates(term)
        if amounts:
            conditions.append(func.abs(BankTransaction.amount_cents).in_(amounts))
        stmt = stmt.where(or_(*conditions))
    return stmt


def next_to_process(
    session: Session,
    txn_id: int,
    *,
    bank_account_id: int | None = None,
    q: str | None = None,
    direction: str | None = None,
) -> int | None:
    """Id of the transaction to handle after `txn_id` in the list order (newest first), within the
    same filters; wraps around to the first one left. None when nothing is left to process.
    `txn_id` itself may already be processed (just booked or ignored)."""
    stmt = _filtered_transactions(bank_account_id=bank_account_id, q=q, direction=direction, status=STATUS_NEW)
    ordered = stmt.order_by(BankTransaction.booking_date.desc(), BankTransaction.id.desc())
    current = session.get(BankTransaction, txn_id)
    if current is not None:
        after = ordered.where(
            or_(
                BankTransaction.booking_date < current.booking_date,
                (BankTransaction.booking_date == current.booking_date) & (BankTransaction.id < current.id),
            )
        ).limit(1)
        row = session.execute(after).first()
        if row is not None:
            return row[0].id
    row = session.execute(ordered.where(BankTransaction.id != txn_id).limit(1)).first()
    return row[0].id if row is not None else None


def list_to_process(
    session: Session,
    *,
    bank_account_id: int | None = None,
    q: str | None = None,
    direction: str | None = None,
    status: str = STATUS_NEW,
    page: int = 1,
    per_page: int = 50,
) -> Page:
    """Transactions of one status (default `nieuw`), newest first, each with its best
    suggestion (only for `nieuw`). Items are ReconcileRow."""
    stmt = _filtered_transactions(
        bank_account_id=bank_account_id, q=q, direction=direction, status=status
    )

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = min(max(1, page), max(1, -(-total // per_page)))
    rows = session.execute(
        stmt.order_by(BankTransaction.booking_date.desc(), BankTransaction.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    items_cache = list_all_open_items(session) if status == STATUS_NEW and rows else []
    rule_views = rules_mod.active_rule_views(session) if status == STATUS_NEW and rows else []
    out = []
    for t, account_name in rows:
        best = None
        if status == STATUS_NEW:
            found = suggest(to_view(t), items_cache, rule_views)
            best = found[0] if found else None
        out.append(
            ReconcileRow(
                id=t.id, bank_account_id=t.bank_account_id, bank_account_name=account_name,
                booking_date=t.booking_date, counterparty_name=t.counterparty_name,
                counterparty_iban=t.counterparty_iban, description=t.description or "",
                amount_cents=t.amount_cents, status=t.status, suggestion=best,
            )
        )
    return Page(items=out, page=page, per_page=per_page, total=total)


def to_process_count(session: Session, bank_account_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(BankTransaction).where(BankTransaction.status == STATUS_NEW)
    if bank_account_id is not None:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    return session.scalar(stmt) or 0


# --- detail ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MatchRow:
    id: int
    source: str
    source_id: int
    amount_cents: int
    number: str
    contact_name: str
    is_credit: bool
    reversed_at: datetime | None
    side: str = SIDE_CREDITOR


@dataclass(frozen=True)
class TransactionDetail:
    txn: TxnView
    status: str
    bank_account_id: int
    bank_account_name: str
    bank_account_ledger_id: int
    journal_entry_id: int | None
    journal_entry_number: str | None
    matches: list[MatchRow] = field(default_factory=list)  # non-reversed allocations
    default_contact_id: int | None = None  # contact to preselect on the match page

    @property
    def is_direct_booked(self) -> bool:
        return self.status == STATUS_BOOKED and not self.matches

    @property
    def can_undo(self) -> bool:
        return self.status == STATUS_BOOKED and self.journal_entry_id is not None


def _match_rows(session: Session, txn_id: int) -> list[MatchRow]:
    out = []
    for m in session.scalars(
        select(BankMatch)
        .where(BankMatch.bank_transaction_id == txn_id, BankMatch.reversed_at.is_(None))
        .order_by(BankMatch.id)
    ):
        number, name, is_credit = _item_info(session, m.source, m.source_id)
        out.append(
            MatchRow(
                m.id, m.source, m.source_id, m.amount_cents, number, name, is_credit, m.reversed_at,
                _match_side(session, m),
            )
        )
    return out


def _match_side(session: Session, match: BankMatch) -> str:
    if match.source == SOURCE_SALES_INVOICE:
        return SIDE_DEBTOR
    if match.source == SOURCE_OPENING_ITEM:
        return session.get(OpeningItem, match.source_id).side
    return SIDE_CREDITOR


def _item_info(session: Session, source: str, source_id: int) -> tuple[str, str, bool]:
    if source == SOURCE_SALES_INVOICE:
        si = session.get(SalesInvoice, source_id)
        return si.number, session.get(Contact, si.contact_id).name, si.kind == sales_service.CREDIT_NOTE
    if source == SOURCE_PURCHASE_INVOICE:
        pi = session.get(PurchaseInvoice, source_id)
        return pi.invoice_number, session.get(Contact, pi.contact_id).name, pi.kind == CREDIT_NOTE
    oi = session.get(OpeningItem, source_id)
    return oi.invoice_number, session.get(Contact, oi.contact_id).name, False


def get_transaction_detail(session: Session, txn_id: int) -> TransactionDetail:
    t = _txn(session, txn_id)
    ba = session.get(BankAccount, t.bank_account_id)
    entry = session.get(JournalEntry, t.journal_entry_id) if t.journal_entry_id else None
    view = to_view(t)
    default_contact = None
    if t.counterparty_iban:
        default_contact = session.scalar(
            select(Contact.id).where(Contact.iban == normalize_iban(t.counterparty_iban), Contact.is_active.is_(True))
        )
    if default_contact is None and view.counterparty_name:
        from app.domain.relations.validation import normalize_name

        default_contact = session.scalar(
            select(Contact.id).where(
                Contact.name_key == normalize_name(view.counterparty_name), Contact.is_active.is_(True)
            )
        )
    return TransactionDetail(
        txn=view, status=t.status, bank_account_id=ba.id, bank_account_name=ba.name,
        bank_account_ledger_id=ba.account_id, journal_entry_id=t.journal_entry_id,
        journal_entry_number=entry.entry_number if entry else None,
        matches=_match_rows(session, txn_id), default_contact_id=default_contact,
    )


def direct_defaults(session: Session, txn_id: int) -> DirectLine | None:
    """Suggested rekening/btw for booking without invoice: a matching rule, else the last
    direct booking for the same IBAN, else None. The amount is the whole transaction."""
    t = _txn(session, txn_id)
    view = to_view(t)
    for rule in sorted_rules(session, view):
        return DirectLine(rule.account_id, view.abs_cents, rule.vat_code, view.description.strip() or None)
    iban = normalize_iban(t.counterparty_iban)
    if not iban:
        return None
    ba = session.get(BankAccount, t.bank_account_id)
    previous = session.scalars(
        select(BankTransaction)
        .where(
            BankTransaction.status == STATUS_BOOKED,
            BankTransaction.counterparty_iban == iban,
            BankTransaction.id != t.id,
            BankTransaction.journal_entry_id.is_not(None),
        )
        .order_by(BankTransaction.id.desc())
        .limit(20)
    )
    system = _system_accounts(session, need_debtors=True)
    skip = {ba.account_id, system.creditors, system.vat_receivable, system.debtors}
    for p in previous:
        has_match = session.scalar(
            select(BankMatch.id).where(BankMatch.bank_transaction_id == p.id, BankMatch.reversed_at.is_(None)).limit(1)
        )
        if has_match is not None:
            continue
        line = session.scalar(
            select(JournalLine)
            .where(JournalLine.entry_id == p.journal_entry_id, JournalLine.account_id.not_in(skip))
            .order_by(JournalLine.line_no)
            .limit(1)
        )
        if line is not None:
            return DirectLine(line.account_id, view.abs_cents, line.vat_code, view.description.strip() or None)
    return None


def sorted_rules(session: Session, view: TxnView):
    active = rules_mod.active_rule_views(session)
    return [r for r in rules_mod.sort_rules(active) if rules_mod.rule_matches(r, view)]


def default_vat_for(session: Session, account_id: int) -> str | None:
    """The btw-code that belongs to a rekening (Account.default_vat_code), if any."""
    return suggest_vat_code(session, account_id)


# --- booking ---------------------------------------------------------------------------------------------------
def _resolve_allocations(
    session: Session, allocations: Sequence[Allocation]
) -> list[AllocationLine]:
    seen: set[tuple[str, int]] = set()
    open_items = {i.ref: i for i in list_all_open_items(session)} if allocations else {}
    lines = []
    for a in allocations:
        if a.source not in SOURCES:
            raise ReconcileError(ITEM_NOT_FOUND, "Deze factuur kan niet worden gekoppeld.")
        if (a.source, a.source_id) in seen:
            raise ReconcileError(
                DUPLICATE_ITEM, "Je hebt dezelfde factuur twee keer gekozen. Voeg de bedragen samen op één regel."
            )
        seen.add((a.source, a.source_id))
        item = open_items.get((a.source, a.source_id))
        if item is None:
            raise ReconcileError(
                ITEM_NOT_FOUND,
                "Deze factuur staat niet meer open (misschien is hij al betaald of ongedaan gemaakt). "
                "Ververs de pagina en kies opnieuw.",
            )
        if a.amount_cents <= 0:
            raise ReconcileError(INVALID_AMOUNT, f"Vul bij factuur {item.number} een bedrag groter dan nul in.")
        if a.amount_cents > item.open_cents:
            raise over_allocated(item.open_cents)
        lines.append(
            AllocationLine(
                a.source, a.source_id, a.amount_cents, item.is_credit, item.number, item.open_cents, item.side
            )
        )
    return lines


def _fill_vat_defaults(session: Session, direct_lines: Sequence[DirectLine]) -> list[DirectLine]:
    out = []
    for d in direct_lines:
        code = d.vat_code or (suggest_vat_code(session, d.account_id) if d.account_id else None)
        out.append(DirectLine(d.account_id, d.amount_cents, code, d.description))
    return out


def _entry_description(allocations: Sequence[AllocationLine], names: Sequence[str], txn: TxnView, has_direct: bool) -> str:
    if not allocations:
        return (txn.counterparty_name or txn.description or "Bankmutatie").strip()
    text = f"Betaling {', '.join(names)} - {', '.join(a.number for a in allocations)}"
    if has_direct:
        text += " en overig"
    return text


def _add_paid(session: Session, source: str, source_id: int, amount: int) -> None:
    """paid_cents += amount, never above the total (guards a parallel booking)."""
    if source == SOURCE_PURCHASE_INVOICE:
        result = session.execute(
            update(PurchaseInvoice)
            .where(
                PurchaseInvoice.id == source_id,
                PurchaseInvoice.paid_cents + amount <= PurchaseInvoice.total_incl_cents,
            )
            .values(paid_cents=PurchaseInvoice.paid_cents + amount)
        )
    elif source == SOURCE_SALES_INVOICE:
        result = session.execute(
            update(SalesInvoice)
            .where(SalesInvoice.id == source_id, SalesInvoice.paid_cents + amount <= SalesInvoice.total_incl_cents)
            .values(paid_cents=SalesInvoice.paid_cents + amount)
        )
    else:
        result = session.execute(
            update(OpeningItem)
            .where(OpeningItem.id == source_id, OpeningItem.paid_cents + amount <= OpeningItem.amount_cents)
            .values(paid_cents=OpeningItem.paid_cents + amount)
        )
    if result.rowcount != 1:
        raise ReconcileError(
            ITEM_NOT_FOUND,
            "Deze factuur is intussen (gedeeltelijk) betaald. Ververs de pagina en kies opnieuw.",
        )


def _recompute_paid(session: Session, source: str, source_id: int) -> None:
    paid = session.scalar(
        select(func.coalesce(func.sum(BankMatch.amount_cents), 0)).where(
            BankMatch.source == source, BankMatch.source_id == source_id, BankMatch.reversed_at.is_(None)
        )
    )
    model = {SOURCE_PURCHASE_INVOICE: PurchaseInvoice, SOURCE_SALES_INVOICE: SalesInvoice}.get(source, OpeningItem)
    session.execute(update(model).where(model.id == source_id).values(paid_cents=paid))


def _only_vat_current_account(session: Session, entry, bank_ledger_id: int) -> bool:
    """A betaling or teruggave van de btw-aangifte only moves the bank and the rekening-courant btw (3150).
    It changes no aangifte, so a vergrendelde periode is no reason to refuse it."""
    current = session.scalar(select(Account.id).where(Account.code == "3150"))
    others = [l for l in entry.lines if l.account_id != bank_ledger_id]
    return current is not None and bool(others) and all(l.account_id == current and l.vat_code in (None, "GEEN") for l in others)


def book(
    session: Session,
    txn_id: int,
    allocations: Sequence[Allocation] = (),
    direct_lines: Sequence[DirectLine] = (),
    *,
    remember_rule: RuleDraft | None = None,
    rule_id: int | None = None,
    allow_locked_period: bool = False,
) -> JournalEntry:
    """Book one transaction: one balanced entry in the bank's dagboek, `bank_match` rows,
    paid_cents of each item, transaction `geboekt`. Atomic; booking twice fails the second time
    with 'Deze mutatie is al verwerkt.' `allow_locked_period` (explicit user consent) books into a
    vergrendelde periode. `rule_id` (a rule that was followed) counts as used.

    Raises ReconcileError (plain Dutch) or the ledger's LedgerError (locked period, ...).
    """
    t = _txn(session, txn_id)
    if t.status != STATUS_NEW:
        raise _status_error(t.status)
    view = to_view(t)
    bank = session.get(BankAccount, t.bank_account_id)
    alloc_lines = _resolve_allocations(session, allocations)
    needs_debtors = any(a.side == SIDE_DEBTOR for a in alloc_lines)
    directs = _fill_vat_defaults(session, direct_lines)
    names = sorted({_item_info(session, a.source, a.source_id)[1] for a in alloc_lines})
    new_entry = build_payment_entry(
        view,
        bank_account_id=bank.account_id,
        journal_id=bank.journal_id,
        allocations=alloc_lines,
        direct_lines=directs,
        accounts=_system_accounts(session, need_debtors=needs_debtors),
        vat_rates=_supported_vat_rates(session),
        description=_entry_description(alloc_lines, names, view, bool(directs)),
    )
    rule_draft = _prepare_rule(view, directs, remember_rule)
    allow_locked_period = allow_locked_period or _only_vat_current_account(session, new_entry, bank.account_id)

    _open_transaction(session)
    try:
        with session.begin_nested():
            # The guarded update is the lock and the re-check in one: only one caller wins.
            claimed = session.execute(
                update(BankTransaction)
                .where(BankTransaction.id == t.id, BankTransaction.status == STATUS_NEW)
                .values(status=STATUS_BOOKED)
            )
            if claimed.rowcount != 1:
                raise ReconcileError(ALREADY_PROCESSED, ALREADY_PROCESSED_MESSAGE)
            entry = post_entry(session, new_entry, allow_locked_period=allow_locked_period)
            session.execute(
                update(BankTransaction).where(BankTransaction.id == t.id).values(journal_entry_id=entry.id)
            )
            now = _now()
            for a in alloc_lines:
                session.add(
                    BankMatch(
                        bank_transaction_id=t.id, journal_entry_id=entry.id, source=a.source,
                        source_id=a.source_id, amount_cents=a.amount_cents, created_at=now,
                    )
                )
                _add_paid(session, a.source, a.source_id, a.amount_cents)
            session.flush()
            if rule_draft is not None:
                rule = rules_mod.create_rule(session, **rule_draft)
                rules_mod.increment_use(session, rule.id)
            if rule_id is not None:
                rules_mod.increment_use(session, rule_id)
    except IntegrityError as exc:  # a parallel booking of the same item/transaction won the race
        raise ReconcileError(ALREADY_PROCESSED, ALREADY_PROCESSED_MESSAGE) from exc
    session.expire_all()
    return entry


def _prepare_rule(view: TxnView, directs: Sequence[DirectLine], draft: RuleDraft | None) -> dict | None:
    if draft is None:
        return None
    if not directs:
        raise ReconcileError(
            RULE_INVALID, "Je kunt alleen een boeking op een rekening onthouden; kies eerst een rekening."
        )
    first = directs[0]
    iban = normalize_iban(view.counterparty_iban) if draft.use_iban else ""
    name = (draft.name or view.counterparty_name or view.description or "").strip()
    return dict(
        name=name,
        counterparty_iban=iban or None,
        description_contains=draft.description_contains,
        direction=view.direction,
        account_id=first.account_id,
        vat_code=first.vat_code,
        contact_id=draft.contact_id,
    )


def accept(session: Session, txn_id: int, suggestion_key: str) -> JournalEntry:
    """'Akkoord' on a suggestion. The suggestion is recomputed here; posted amounts are never trusted."""
    t = _txn(session, txn_id)
    if t.status != STATUS_NEW:
        raise _status_error(t.status)
    for s in suggestions_for(session, txn_id):
        if s.key == suggestion_key:
            return book(session, txn_id, s.allocations, s.direct_lines, rule_id=s.rule_id)
    raise ReconcileError(
        SUGGESTION_GONE,
        "Deze suggestie klopt niet meer, bijvoorbeeld omdat de factuur intussen is betaald. "
        "Open de mutatie en kies zelf.",
    )


# --- undo / ignore / restore -----------------------------------------------------------------------------------------
def undo(session: Session, txn_id: int) -> JournalEntry:
    """'Ongedaan maken': stornoboeking, matches reversed, paid_cents recomputed, transaction `nieuw` again."""
    t = _txn(session, txn_id)
    if t.status != STATUS_BOOKED or t.journal_entry_id is None:
        raise ReconcileError(NOT_BOOKED, "Deze mutatie is niet geboekt, dus er valt niets ongedaan te maken.")
    entry_id = t.journal_entry_id
    original = session.get(JournalEntry, entry_id)
    orig_period = session.get(Period, original.period_id) if original else None
    if orig_period is not None and orig_period.status != "open":
        raise ReconcileError(
            "PERIOD_LOCKED",
            "Deze boeking valt in een afgesloten periode, dus je kunt haar niet meer ongedaan maken. "
            "Maak de periode eerst weer open, of boek een correctie.",
        )
    _open_transaction(session)
    with session.begin_nested():
        storno = reverse_entry(session, entry_id)  # LedgerError: locked period, already reversed
        now = _now()
        matches = list(
            session.scalars(
                select(BankMatch).where(
                    BankMatch.bank_transaction_id == t.id,
                    BankMatch.journal_entry_id == entry_id,
                    BankMatch.reversed_at.is_(None),
                )
            )
        )
        session.execute(
            update(BankMatch)
            .where(BankMatch.id.in_([m.id for m in matches]))
            .values(reversed_at=now)
        )
        for source, source_id in {(m.source, m.source_id) for m in matches}:
            _recompute_paid(session, source, source_id)
        result = session.execute(
            update(BankTransaction)
            .where(
                BankTransaction.id == t.id,
                BankTransaction.status == STATUS_BOOKED,
                BankTransaction.journal_entry_id == entry_id,
            )
            .values(status=STATUS_NEW, journal_entry_id=None)
        )
        if result.rowcount != 1:
            raise ReconcileError(NOT_BOOKED, "Deze mutatie is al ongedaan gemaakt.")
    session.expire_all()
    return storno


def booked_transaction_for_entry(session: Session, entry_id: int) -> int | None:
    """Id of the bank transaction whose booking this journal entry is, if that booking is still active.
    Such an entry may only be undone via 'Ongedaan maken' on the transaction."""
    return session.scalar(
        select(BankTransaction.id).where(
            BankTransaction.journal_entry_id == entry_id, BankTransaction.status == STATUS_BOOKED
        )
    )


def _switch_status(session: Session, txn_id: int, old: str, new: str, error: ReconcileError) -> None:
    t = _txn(session, txn_id)
    if t.status != old:
        raise error
    result = session.execute(
        update(BankTransaction).where(BankTransaction.id == txn_id, BankTransaction.status == old).values(status=new)
    )
    if result.rowcount != 1:
        raise error
    session.expire_all()


def ignore(session: Session, txn_id: int) -> None:
    """'Negeren': the transaction does not belong in the boekhouding."""
    t = _txn(session, txn_id)
    if t.status != STATUS_NEW:
        raise _status_error(t.status) if t.status == STATUS_BOOKED else ReconcileError(
            IGNORED, "Deze mutatie is al genegeerd."
        )
    _switch_status(session, txn_id, STATUS_NEW, STATUS_IGNORED, ReconcileError(ALREADY_PROCESSED, ALREADY_PROCESSED_MESSAGE))


def restore(session: Session, txn_id: int) -> None:
    """'Terugzetten': an ignored transaction becomes `nieuw` again."""
    _switch_status(
        session, txn_id, STATUS_IGNORED, STATUS_NEW,
        ReconcileError(NOT_IGNORED, "Deze mutatie is niet genegeerd, dus je hoeft hem niet terug te zetten."),
    )


# --- payment of an invoice under review (nakijken) ---------------------------------------------------
def payment_candidates_for_extraction(session: Session, extraction) -> list[PaymentCandidate]:
    """Unprocessed transactions that could be the payment of the invoice read out in `extraction`."""
    total = extraction.total_incl_cents
    if not total or total <= 0:
        return []
    is_credit = extraction.kind == CREDIT_NOTE
    # Pre-filter in SQL on direction and size; the matching rules decide the rest.
    direction = BankTransaction.amount_cents > 0 if is_credit else BankTransaction.amount_cents < 0
    txns = session.scalars(
        select(BankTransaction).where(
            BankTransaction.status == STATUS_NEW,
            direction,
            func.abs(BankTransaction.amount_cents) <= total,
        )
    )
    view = InvoiceView(
        number=extraction.invoice_number, invoice_date=extraction.invoice_date, total_incl_cents=total,
        is_credit=is_credit, supplier_name=extraction.supplier_name, supplier_iban=extraction.supplier_iban,
    )
    return payment_candidates(view, [to_view(t) for t in txns])


def book_payment_for_invoice(session: Session, txn_id: int, invoice: PurchaseInvoice) -> JournalEntry:
    """Link a just-booked inkoopfactuur to a bank transaction: books the payment on the invoice.

    The transaction must still look like a payment of this invoice (same rules as the list
    shown during nakijken); nothing the form posted is trusted beyond the transaction id.
    """
    t = _txn(session, txn_id)
    if t.status != STATUS_NEW:
        raise _status_error(t.status)
    contact = session.get(Contact, invoice.contact_id)
    view = InvoiceView(
        number=invoice.invoice_number, invoice_date=invoice.invoice_date, total_incl_cents=invoice.total_incl_cents,
        is_credit=invoice.kind == CREDIT_NOTE, supplier_name=contact.name, supplier_iban=contact.iban,
    )
    if not payment_candidates(view, [to_view(t)]):
        raise ReconcileError(
            SUGGESTION_GONE, "Deze betaling past niet bij de factuur. Kies een andere betaling of sla dit over."
        )
    return book(session, txn_id, [Allocation(SOURCE_PURCHASE_INVOICE, invoice.id, abs(t.amount_cents))])
