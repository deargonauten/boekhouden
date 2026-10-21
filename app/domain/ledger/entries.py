"""Pure entry shapes and validation (no DB). Account/VAT/period checks live in the service."""

from dataclasses import dataclass, field, replace
from datetime import date

from app.domain.errors import (
    InvalidDateError,
    InvalidDescriptionError,
    InvalidKindError,
    InvalidLineAmountError,
    TooFewLinesError,
    UnbalancedError,
)
from app.domain.money import format_euro, require_cents

ENTRY_KINDS = ("normal", "opening", "storno")
MAX_DESCRIPTION_LENGTH = 255


@dataclass
class NewLine:
    account_id: int
    debit_cents: int = 0
    credit_cents: int = 0
    description: str | None = None
    vat_code: str | None = None


@dataclass
class NewEntry:
    journal_id: int
    booking_date: date
    description: str
    lines: list[NewLine] = field(default_factory=list)
    reference: str | None = None
    kind: str = "normal"


def validate_entry(entry: NewEntry) -> None:
    """Check shape, amounts and balance. Raises TypeError for non-int amounts, LedgerError otherwise."""
    if entry.kind not in ENTRY_KINDS:
        raise InvalidKindError(f"Onbekend soort boeking: '{entry.kind}'.")
    if not isinstance(entry.booking_date, date):
        raise InvalidDateError("Een boekingsdatum is verplicht.")
    description = entry.description
    if not isinstance(description, str) or not description.strip():
        raise InvalidDescriptionError("Een omschrijving is verplicht.")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise InvalidDescriptionError(
            f"De omschrijving mag maximaal {MAX_DESCRIPTION_LENGTH} tekens bevatten."
        )
    if len(entry.lines) < 2:
        raise TooFewLinesError("Een boeking heeft minimaal twee regels nodig.")

    total_debit = total_credit = 0
    for number, line in enumerate(entry.lines, start=1):
        debit = require_cents(line.debit_cents)
        credit = require_cents(line.credit_cents)
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise InvalidLineAmountError(
                f"Regel {number}: vul precies één van debet of credit in met een bedrag groter dan nul."
            )
        total_debit += debit
        total_credit += credit

    if total_debit != total_credit:
        raise UnbalancedError(
            f"De boeking is niet in evenwicht: debet {format_euro(total_debit)}, "
            f"credit {format_euro(total_credit)} (verschil {format_euro(abs(total_debit - total_credit))})."
        )


def build_storno(lines: list[NewLine]) -> list[NewLine]:
    """Equal-and-opposite lines: debit/credit swapped, account, vat_code and description copied."""
    return [
        replace(line, debit_cents=line.credit_cents, credit_cents=line.debit_cents)
        for line in lines
    ]
