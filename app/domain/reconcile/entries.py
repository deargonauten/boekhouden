"""The journal entry of one reconciled bank transaction (pure, no database).

Transaction af:  debit 3000 per invoice allocation (credit 3000 per creditnota), debit the
                 chosen accounts (+ 1400 voorbelasting), credit the bank account.
Transaction bij: debit the bank account, credit 3000 per creditnota allocation (debit per
                 invoice in a mix), credit the chosen accounts (without btw).
Integer cents only; the btw of a direct line is computed once per line and rounded half up.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.ledger.entries import MAX_DESCRIPTION_LENGTH, NewEntry, NewLine, validate_entry
from app.domain.money import require_cents
from app.domain.reconcile.errors import (
    ACCOUNT_REQUIRED,
    INVALID_AMOUNT,
    NOTHING_TO_BOOK,
    UNSUPPORTED_VAT,
    UNSUPPORTED_VAT_MESSAGE,
    VAT_ON_INCOMING,
    VAT_ON_INCOMING_MESSAGE,
    VAT_REQUIRED,
    WRONG_DIRECTION,
    WRONG_DIRECTION_AF_MESSAGE,
    WRONG_DIRECTION_BIJ_MESSAGE,
    ReconcileError,
    not_distributed,
    over_allocated,
    over_distributed,
)
from app.domain.reconcile.types import AllocationLine, DirectLine, TxnView


@dataclass(frozen=True)
class SystemAccounts:
    creditors: int  # 3000 Crediteuren
    vat_receivable: int  # 1400 BTW voorbelasting


def split_vat(amount_incl_cents: int, rate_bp: int) -> tuple[int, int]:
    """(excl, vat) of an amount incl. btw; vat rounded half up."""
    divisor = 10000 + rate_bp
    vat = (amount_incl_cents * rate_bp + divisor // 2) // divisor
    return amount_incl_cents - vat, vat


def _check_allocations(txn: TxnView, allocations: Sequence[AllocationLine]) -> None:
    for a in allocations:
        require_cents(a.amount_cents)
        if a.amount_cents <= 0:
            raise ReconcileError(INVALID_AMOUNT, f"Vul bij factuur {a.number} een bedrag groter dan nul in.")
        if a.amount_cents > a.open_cents:
            raise over_allocated(a.open_cents)
    if allocations:
        if txn.direction == "af" and all(a.is_credit for a in allocations):
            raise ReconcileError(WRONG_DIRECTION, WRONG_DIRECTION_AF_MESSAGE)
        if txn.direction == "bij" and not any(a.is_credit for a in allocations):
            raise ReconcileError(WRONG_DIRECTION, WRONG_DIRECTION_BIJ_MESSAGE)


def _check_direct(txn: TxnView, direct_lines: Sequence[DirectLine], vat_rates: Mapping[str, int]) -> None:
    for d in direct_lines:
        if d.account_id is None:
            raise ReconcileError(ACCOUNT_REQUIRED, "Kies een rekening voor deze regel.")
        require_cents(d.amount_cents)
        if d.amount_cents <= 0:
            raise ReconcileError(INVALID_AMOUNT, "Vul bij elke regel een bedrag groter dan nul in.")
        if not d.vat_code:
            raise ReconcileError(VAT_REQUIRED, "Kies een btw-code voor deze regel (bijvoorbeeld 'Geen BTW').")
        if d.vat_code not in vat_rates:
            raise ReconcileError(UNSUPPORTED_VAT, UNSUPPORTED_VAT_MESSAGE)
        if txn.direction == "bij" and vat_rates[d.vat_code] != 0:
            raise ReconcileError(VAT_ON_INCOMING, VAT_ON_INCOMING_MESSAGE)


def net_distributed(txn: TxnView, allocations: Sequence[AllocationLine], direct_lines: Sequence[DirectLine]) -> int:
    """How much of the transaction is accounted for (invoices count with the direction of the money)."""
    sign_credit = -1 if txn.direction == "af" else 1
    total = sum(d.amount_cents for d in direct_lines)
    for a in allocations:
        total += a.amount_cents * (sign_credit if a.is_credit else -sign_credit)
    return total


def build_payment_entry(
    txn: TxnView,
    *,
    bank_account_id: int,
    journal_id: int,
    allocations: Sequence[AllocationLine],
    direct_lines: Sequence[DirectLine],
    accounts: SystemAccounts,
    vat_rates: Mapping[str, int],
    description: str | None = None,
) -> NewEntry:
    """Balanced entry in the bank's dagboek. `vat_rates` holds only the supported btw-codes
    (code -> rate in basis points). Raises ReconcileError (plain Dutch) when it cannot be built."""
    require_cents(txn.amount_cents)
    if not allocations and not direct_lines:
        raise ReconcileError(
            NOTHING_TO_BOOK, "Kies eerst een factuur of een rekening om deze mutatie op te boeken."
        )
    _check_allocations(txn, allocations)
    _check_direct(txn, direct_lines, vat_rates)

    remainder = txn.abs_cents - net_distributed(txn, allocations, direct_lines)
    if remainder > 0:
        raise not_distributed(remainder)
    if remainder < 0:
        raise over_distributed(-remainder)

    outgoing = txn.direction == "af"
    text = (description or txn.description or txn.counterparty_name or "Bankmutatie").strip()
    text = (text or "Bankmutatie")[:MAX_DESCRIPTION_LENGTH]

    def line(account_id: int, cents: int, debit: bool, desc: str | None, vat_code: str | None = None) -> NewLine:
        return NewLine(
            account_id,
            debit_cents=cents if debit else 0,
            credit_cents=0 if debit else cents,
            description=(desc or text)[:MAX_DESCRIPTION_LENGTH],
            vat_code=vat_code,
        )

    lines: list[NewLine] = []
    for a in allocations:
        # An invoice reduces what you owe (debit 3000), a creditnota increases it back (credit 3000).
        lines.append(line(accounts.creditors, a.amount_cents, debit=not a.is_credit, desc=f"Betaling {a.number}"))
    vat_per_code: dict[str, int] = {}
    for d in direct_lines:
        excl, vat = split_vat(d.amount_cents, vat_rates[d.vat_code])
        lines.append(line(d.account_id, excl, debit=outgoing, desc=d.description, vat_code=d.vat_code))
        if vat:
            vat_per_code[d.vat_code] = vat_per_code.get(d.vat_code, 0) + vat
    for code, vat in vat_per_code.items():
        lines.append(line(accounts.vat_receivable, vat, debit=True, desc=f"Voorbelasting {code}"))
    lines.append(line(bank_account_id, txn.abs_cents, debit=not outgoing, desc=text))

    reference = ", ".join(a.number for a in allocations) or txn.bank_reference
    entry = NewEntry(
        journal_id=journal_id,
        booking_date=txn.booking_date,
        description=text,
        lines=lines,
        reference=reference,
    )
    validate_entry(entry)
    return entry
