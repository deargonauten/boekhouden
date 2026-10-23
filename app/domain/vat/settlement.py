"""Afrekening van een ingediende btw-aangifte: de btw-rekeningen van de periode gaan naar 3150.

Zo staat wat je aan de Belastingdienst moet betalen (of terugkrijgt) op één rekening, en kan de
bankbetaling daar tegenover worden geboekt. De aangifte zelf komt uit de btw-codes op de regels en
verandert hierdoor niet (de afrekenregels hebben geen btw-code).
"""

from datetime import date

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session

from app.domain.ledger import NewEntry, NewLine, post_entry
from app.domain.vat.periods import VatPeriod, period_range
from app.models import Account, Journal, JournalEntry, JournalLine

SETTLED_CODES = ("3100", "3110", "3120", "3130", "3140", "1400", "1410")
CURRENT_ACCOUNT_CODE = "3150"
JOURNAL_CODE = "MEM"
SOURCE_TYPE = "vat_settlement"
DESCRIPTION_PREFIX = "Afrekening btw-aangifte"


def is_settlement_entry():
    """SQL condition: the entry is an afrekening. Entries from before the source tag are found by description."""
    return or_(JournalEntry.source_type == SOURCE_TYPE, JournalEntry.description.like(f"{DESCRIPTION_PREFIX} %"))


def not_settlement_entry():
    return and_(or_(JournalEntry.source_type.is_(None), JournalEntry.source_type != SOURCE_TYPE),
                not_(JournalEntry.description.like(f"{DESCRIPTION_PREFIX} %")))


def net_movement(session: Session, account_id: int, start: date, end: date) -> int:
    """Debit minus credit of an account for entries dated in [start, end]."""
    return session.scalar(
        select(func.coalesce(func.sum(JournalLine.debit_cents - JournalLine.credit_cents), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.account_id == account_id, JournalEntry.booking_date.between(start, end))
    )


def settle_vat_period(
    session: Session, period: VatPeriod, *, extra: dict[str, int] | None = None, return_id: int | None = None,
) -> JournalEntry | None:
    """Post one memoriaalboeking dated on the last day of the period; None when there is nothing to settle.

    `extra` (account code -> debit minus credit) adds the btw of taken-along suppleties, which sits in an
    earlier, already settled period."""
    start, end = period_range(period)
    accounts = {
        code: id_ for code, id_ in session.execute(
            select(Account.code, Account.id).where(Account.code.in_((*SETTLED_CODES, CURRENT_ACCOUNT_CODE)))
        )
    }
    current = accounts.get(CURRENT_ACCOUNT_CODE)
    journal = session.scalar(select(Journal.id).where(Journal.code == JOURNAL_CODE))
    if current is None or journal is None:
        return None

    lines: list[NewLine] = []
    total = 0
    for code in SETTLED_CODES:
        if code not in accounts:
            continue
        net = net_movement(session, accounts[code], start, end) + (extra or {}).get(code, 0)
        if net == 0:
            continue
        total += net
        lines.append(NewLine(accounts[code], debit_cents=max(-net, 0), credit_cents=max(net, 0),
                             description=f"Afrekening btw {period.label}"))
    if not lines:
        return None
    lines.append(NewLine(current, debit_cents=max(total, 0), credit_cents=max(-total, 0),
                         description=f"Btw-aangifte {period.label}"))
    entry = post_entry(session, NewEntry(
        journal_id=journal, booking_date=end, description=f"{DESCRIPTION_PREFIX} {period.label}", lines=lines,
    ))
    if return_id is not None:
        entry.source_type, entry.source_id = SOURCE_TYPE, return_id  # the one allowed update of a booking
        session.flush()
    return entry
