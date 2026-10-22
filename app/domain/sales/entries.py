"""Pure journal entry of a verkoopfactuur / creditnota (no DB)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.ledger import NewEntry, NewLine
from app.domain.ledger.entries import MAX_DESCRIPTION_LENGTH
from app.domain.sales.numbering import format_number  # noqa: F401  (re-exported)
from app.domain.sales.types import CREDIT_NOTE, SOURCE_TYPE, VatGroup  # noqa: F401

DEBTORS_CODE = "1300"
VAT_HIGH_CODE = "3100"
VAT_LOW_CODE = "3110"
_VAT_ACCOUNT_BY_RATE = {2100: "vat_high", 900: "vat_low"}


@dataclass(frozen=True)
class SalesAccounts:
    debtors: int  # 1300 Debiteuren
    vat_high: int  # 3100 BTW af te dragen hoog (21%)
    vat_low: int  # 3110 BTW af te dragen laag (9%)


@dataclass(frozen=True)
class EntryLine:
    account_id: int  # revenue account
    vat_code: str
    line_excl_cents: int


def build_entry(
    *,
    kind: str,
    number: str,
    invoice_date: date,
    customer_name: str,
    lines: Sequence[EntryLine],
    groups: Sequence[VatGroup],
    total_incl_cents: int,
    accounts: SalesAccounts,
    journal_id: int,
) -> NewEntry:
    """Invoice: debit 1300, credit omzet (with vat code = grondslag) and BTW (no vat code).
    Credit note: the same lines with debit and credit swapped. Lines of 0 are left out."""
    credit_note = kind == CREDIT_NOTE

    def side(account_id: int, cents: int, vat_code: str | None) -> NewLine:
        # invoice: omzet/BTW are credit; credit note: debit
        return NewLine(
            account_id=account_id,
            debit_cents=cents if credit_note else 0,
            credit_cents=0 if credit_note else cents,
            vat_code=vat_code,
        )

    entry_lines = [
        NewLine(
            account_id=accounts.debtors,
            debit_cents=0 if credit_note else total_incl_cents,
            credit_cents=total_incl_cents if credit_note else 0,
        )
    ]
    for line in lines:
        if line.line_excl_cents > 0:
            entry_lines.append(side(line.account_id, line.line_excl_cents, line.vat_code))
    for group in groups:
        if group.vat_cents > 0:
            vat_account = getattr(accounts, _VAT_ACCOUNT_BY_RATE[group.rate_bp])
            entry_lines.append(side(vat_account, group.vat_cents, None))
    return NewEntry(
        journal_id=journal_id,
        booking_date=invoice_date,
        description=f"{customer_name} - {number}"[:MAX_DESCRIPTION_LENGTH],
        lines=entry_lines,
        reference=number,
    )
