"""Controle voor aangifte: read-only checks over one btw-periode (advisory, never blocking).

One private function per check; each returns a `Check`. Hrefs are plain strings built from the
URL constants below so the routes do not need to know them. Money is integer cents.
"""

from datetime import date

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.domain.checks.types import (
    LEVEL_FOUT,
    LEVEL_LET_OP,
    LEVEL_OK,
    Check,
    CheckItem,
    CheckReport,
)
from app.domain.money import format_euro
from app.domain.vat.periods import VatPeriod, period_range
from app.models import (
    Account,
    BankTransaction,
    Contact,
    Document,
    Journal,
    JournalEntry,
    JournalLine,
    SalesInvoice,
)

MAX_ITEMS = 5

BANK_URL = "/bank/afletteren"
BANK_TXN_URL = "/bank/transacties/{id}/afletteren"
ENTRY_URL = "/boeken/{id}"
ENTRIES_URL = "/boeken"
INBOX_URL = "/inbox"
DOCUMENT_URL = "/inbox/{id}"
SALES_URL = "/verkoop"
INVOICE_URL = "/verkoop/{id}"


def run_checks(session: Session, period: VatPeriod, *, today: date | None = None) -> CheckReport:
    """All checks for `period`. `today` is accepted for callers that pass a clock; the checks
    themselves depend only on the period."""
    start, end = period_range(period)
    return CheckReport(
        period=period,
        checks=(
            _bank_ongeboekt(session, start, end),
            _onevenwichtig(session, start, end),
            _boeking_zonder_document(session, start, end),
            _inbox_ongeboekt(session, end),
            _concept_facturen(session, end),
        ),
    )


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _build(
    key: str,
    title: str,
    level: str,
    count: int,
    items: list[CheckItem],
    ok_text: str,
    problem_text: str,
    fix_href: str,
    fix_label: str,
    amount_cents: int | None = None,
) -> Check:
    return Check(
        key=key,
        title=title,
        explanation=ok_text if count == 0 else problem_text,
        level=LEVEL_OK if count == 0 else level,
        count=count,
        items=tuple(items[:MAX_ITEMS]),
        fix_href=fix_href,
        fix_label=fix_label,
        amount_cents=amount_cents,
    )


def _bank_ongeboekt(session: Session, start: date, end: date) -> Check:
    in_period = and_(
        BankTransaction.status == "nieuw",
        BankTransaction.booking_date >= start,
        BankTransaction.booking_date <= end,
    )
    count, total = session.execute(
        select(func.count(), func.coalesce(func.sum(func.abs(BankTransaction.amount_cents)), 0)).where(in_period)
    ).one()
    rows = session.execute(
        select(BankTransaction).where(in_period).order_by(BankTransaction.booking_date, BankTransaction.id).limit(MAX_ITEMS)
    ).scalars()
    items = [
        CheckItem(
            f"{t.booking_date:%d-%m-%Y} {t.counterparty_name or t.description or 'Bankmutatie'}: {format_euro(t.amount_cents)}",
            BANK_TXN_URL.format(id=t.id),
        )
        for t in rows
    ]
    n = int(count)
    return _build(
        "bank_ongeboekt",
        "Bankmutaties die je nog niet hebt verwerkt",
        LEVEL_FOUT,
        n,
        items,
        "Alle bankmutaties in deze periode zijn verwerkt.",
        f"Er {_plural(n, 'staat 1 bankmutatie', f'staan {n} bankmutaties')} in deze periode die je nog niet "
        f"hebt verwerkt (samen {format_euro(int(total))}). "
        f"Verwerk {_plural(n, 'hem', 'ze')} eerst, anders ontbreekt er btw in je aangifte.",
        BANK_URL,
        "Bankmutaties verwerken",
        amount_cents=int(total),
    )


def _difference_label(entry: JournalEntry, debit: int, credit: int, has_lines: bool) -> str:
    head = f"{entry.entry_number} {entry.description}"
    if not has_lines:
        return f"{head}: deze boeking heeft geen regels. Maak hem ongedaan of vul hem aan."
    missing = abs(debit - credit)
    side = "credit" if debit > credit else "debet"
    euros, cents = divmod(missing, 100)
    amount = f"€{euros:,}".replace(",", ".") + f",{cents:02d}"
    return f"{head}: Debet en credit zijn niet gelijk: er ontbreekt {amount} aan de {side}kant."


def _onevenwichtig(session: Session, start: date, end: date) -> Check:
    debit = func.coalesce(func.sum(JournalLine.debit_cents), 0)
    credit = func.coalesce(func.sum(JournalLine.credit_cents), 0)
    n_lines = func.count(JournalLine.id)
    stmt = (
        select(JournalEntry, debit, credit, n_lines)
        .outerjoin(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(JournalEntry.booking_date >= start, JournalEntry.booking_date <= end)
        .group_by(JournalEntry.id)
        .having((debit != credit) | (n_lines == 0))
        .order_by(JournalEntry.booking_date, JournalEntry.id)
    )
    rows = session.execute(stmt).all()
    items = [
        CheckItem(_difference_label(e, int(d), int(c), int(n) > 0), ENTRY_URL.format(id=e.id))
        for e, d, c, n in rows[:MAX_ITEMS]
    ]
    n = len(rows)
    return _build(
        "onevenwichtig",
        "Boekingen die niet kloppen",
        LEVEL_FOUT,
        n,
        items,
        "Alle boekingen in deze periode kloppen: debet en credit zijn gelijk.",
        f"{_plural(n, 'Er is 1 boeking', f'Er zijn {n} boekingen')} waarvan debet en credit niet gelijk zijn. "
        "Open de boeking en maak hem ongedaan (storno), of boek hem opnieuw goed.",
        ENTRIES_URL,
        "Boekingen bekijken",
    )


def _boeking_zonder_document(session: Session, start: date, end: date) -> Check:
    """Manual/bank direct bookings (no source_type) touching cost or revenue, without a linked document.

    The bank direct-booking flow (reconcile) posts without a source_type, so it falls under the
    same `source_type IS NULL` filter. Settlement of invoices only touches 1300/3000/bank, which
    are not cost or revenue accounts, so those entries drop out through the account-type filter.
    """
    reversal = aliased(JournalEntry)
    reversed_already = exists().where(reversal.reverses_entry_id == JournalEntry.id)
    has_document = exists().where(Document.journal_entry_id == JournalEntry.id)
    has_cost_or_revenue = exists().where(
        JournalLine.entry_id == JournalEntry.id,
        JournalLine.account_id == Account.id,
        Account.type.in_(("expense", "revenue")),
    )
    conditions = [
        JournalEntry.booking_date >= start,
        JournalEntry.booking_date <= end,
        JournalEntry.kind == "normal",
        JournalEntry.source_type.is_(None),
        Journal.type != "memoriaal",
        has_cost_or_revenue,
        ~has_document,
        ~reversed_already,
    ]
    base = select(JournalEntry).join(Journal, Journal.id == JournalEntry.journal_id).where(*conditions)
    count = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    entries = session.scalars(base.order_by(JournalEntry.booking_date, JournalEntry.id).limit(MAX_ITEMS)).all()
    totals = {}
    if entries:
        totals = dict(
            session.execute(
                select(JournalLine.entry_id, func.sum(JournalLine.debit_cents))
                .where(JournalLine.entry_id.in_([e.id for e in entries]))
                .group_by(JournalLine.entry_id)
            ).all()
        )
    items = [
        CheckItem(
            f"{e.entry_number} {e.description} ({e.booking_date:%d-%m-%Y}, {format_euro(int(totals.get(e.id) or 0))})",
            ENTRY_URL.format(id=e.id),
        )
        for e in entries
    ]
    return _build(
        "boeking_zonder_document",
        "Boekingen zonder bon of factuur",
        LEVEL_LET_OP,
        count,
        items,
        "Bij je handmatige kosten en opbrengsten in deze periode hoort een bon of factuur.",
        f"{_plural(count, 'Bij 1 boeking', f'Bij {count} boekingen')} van kosten of opbrengsten zit geen bon of "
        "factuur. Voeg het stuk toe via de inbox, want je moet het 7 jaar bewaren. "
        "Is er echt geen bon (bijvoorbeeld bankkosten), dan kun je dit laten staan.",
        ENTRIES_URL,
        "Boekingen bekijken",
    )


def _inbox_ongeboekt(session: Session, end: date) -> Check:
    # received_at is a datetime: "date <= end" means before the start of the next day.
    cond = and_(Document.status.in_(("nieuw", "herkend")), func.date(Document.received_at) <= end.isoformat())
    count = session.scalar(select(func.count()).select_from(Document).where(cond)) or 0
    docs = session.scalars(select(Document).where(cond).order_by(Document.received_at, Document.id).limit(MAX_ITEMS))
    items = [
        CheckItem(f"{d.original_filename} (ontvangen {d.received_at:%d-%m-%Y})", DOCUMENT_URL.format(id=d.id))
        for d in docs
    ]
    return _build(
        "inbox_ongeboekt",
        "Documenten in je inbox die nog niet zijn geboekt",
        LEVEL_LET_OP,
        count,
        items,
        "Er liggen geen onverwerkte bonnen of facturen in je inbox.",
        f"Er {_plural(count, 'ligt 1 document', f'liggen {count} documenten')} in je inbox die je nog niet hebt "
        "geboekt. Dat kan invloed hebben op je btw: boek ze of gooi ze weg als ze niet nodig zijn.",
        INBOX_URL,
        "Naar de inbox",
    )


def _concept_facturen(session: Session, end: date) -> Check:
    cond = and_(SalesInvoice.status == "concept", SalesInvoice.invoice_date <= end)
    count = session.scalar(select(func.count()).select_from(SalesInvoice).where(cond)) or 0
    rows = session.execute(
        select(SalesInvoice, Contact.name)
        .join(Contact, Contact.id == SalesInvoice.contact_id)
        .where(cond)
        .order_by(SalesInvoice.invoice_date, SalesInvoice.id)
        .limit(MAX_ITEMS)
    ).all()
    items = [
        CheckItem(
            f"Concept voor {name} ({inv.invoice_date:%d-%m-%Y}, {format_euro(inv.total_incl_cents)})",
            INVOICE_URL.format(id=inv.id),
        )
        for inv, name in rows
    ]
    return _build(
        "concept_facturen",
        "Conceptfacturen",
        LEVEL_LET_OP,
        count,
        items,
        "Je hebt geen conceptfacturen liggen.",
        f"Je hebt {_plural(count, '1 conceptfactuur', f'{count} conceptfacturen')} met een datum tot en met het einde "
        "van deze periode. Een conceptfactuur telt nog niet mee in je btw. "
        "Maak hem definitief of gooi hem weg.",
        SALES_URL,
        "Naar de verkoopfacturen",
    )
