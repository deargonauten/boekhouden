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
        raise InvalidKindError(f"Deze soort boeking ('{entry.kind}') bestaat niet. Kies een gewone boeking.")
    if not isinstance(entry.booking_date, date):
        raise InvalidDateError("Vul een geldige datum in, bijvoorbeeld 31-12-2026.")
    description = entry.description
    if not isinstance(description, str) or not description.strip():
        raise InvalidDescriptionError("Vul een omschrijving in, bijvoorbeeld 'Kantoorbenodigdheden'.")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise InvalidDescriptionError(
            f"De omschrijving is te lang (maximaal {MAX_DESCRIPTION_LENGTH} tekens)."
        )
    if len(entry.lines) < 2:
        raise TooFewLinesError(
            "Een boeking heeft minimaal twee regels nodig: één voor debet en één voor credit."
        )

    total_debit = total_credit = 0
    for number, line in enumerate(entry.lines, start=1):
        debit = require_cents(line.debit_cents)
        credit = require_cents(line.credit_cents)
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise InvalidLineAmountError(
                f"Regel {number}: vul bij debet óf bij credit een bedrag groter dan nul in, "
                "niet allebei en niet leeg."
            )
        total_debit += debit
        total_credit += credit

    if total_debit != total_credit:
        missing_side = "debet" if total_debit < total_credit else "credit"
        raise UnbalancedError(
            "Debet en credit zijn niet gelijk: er ontbreekt "
            f"{format_euro(abs(total_debit - total_credit))} aan de {missing_side}kant. "
            "Pas een bedrag aan of voeg een regel toe. "
            f"(debet {format_euro(total_debit)}, credit {format_euro(total_credit)})."
        )


def build_storno(lines: list[NewLine]) -> list[NewLine]:
    """Equal-and-opposite lines: debit/credit swapped, account, vat_code and description copied."""
    return [
        replace(line, debit_cents=line.credit_cents, credit_cents=line.debit_cents)
        for line in lines
    ]
