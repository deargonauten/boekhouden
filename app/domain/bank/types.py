"""Shared types for the bank statement import (bankafschriften).

Money is always integer cents. Positive = bij (money in), negative = af.
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.domain.errors import LedgerError

UNKNOWN_FORMAT = "UNKNOWN_FORMAT"
PARSE_ERROR = "PARSE_ERROR"
WRONG_ACCOUNT = "WRONG_ACCOUNT"
ALREADY_IMPORTED = "ALREADY_IMPORTED"
EMPTY = "EMPTY"
FILE_TOO_BIG = "FILE_TOO_BIG"
BAD_IBAN = "BAD_IBAN"
ACCOUNT_IN_USE = "ACCOUNT_IN_USE"

MAX_FILE_BYTES = 10 * 1024 * 1024

BANKS = ("ing", "rabobank", "abn_amro", "bunq", "overig")
FORMATS = ("camt053", "mt940", "csv")


class BankImportError(LedgerError):
    """A bank import failure. `message` is plain Dutch: what is wrong and what to do."""

    code = PARSE_ERROR

    def __init__(self, code: str, message: str):
        super().__init__(code, message)


@dataclass(frozen=True)
class ParsedTransaction:
    booking_date: date
    amount_cents: int  # signed, never zero
    value_date: date | None = None
    currency: str = "EUR"
    counterparty_name: str | None = None
    counterparty_iban: str | None = None  # normalised
    description: str = ""
    end_to_end_id: str | None = None
    bank_reference: str | None = None
    balance_after_cents: int | None = None
    raw: str = ""


@dataclass(frozen=True)
class ParsedStatement:
    account_iban: str | None
    currency: str
    opening_cents: int | None
    closing_cents: int | None
    transactions: tuple[ParsedTransaction, ...]
    format: str  # camt053 | mt940 | csv
    bank: str | None = None  # ing | rabobank | abn_amro | bunq | None

    @property
    def balance_difference_cents(self) -> int | None:
        """closing - (opening + sum(transactions)); None when balances are unknown, 0 when consistent."""
        if self.opening_cents is None or self.closing_cents is None:
            return None
        total = sum(t.amount_cents for t in self.transactions)
        return self.closing_cents - (self.opening_cents + total)


@dataclass(frozen=True)
class PreviewRow:
    """One parsed transaction in a preview. `index` is its position in the file (0-based)
    and is the id used for the "Toch importeren" opt-in."""

    index: int
    transaction: ParsedTransaction
    dedupe_key: str
    occurrence: int
    matched_transaction_id: int | None = None  # stored row that made it existing / maybe-duplicate


@dataclass(frozen=True)
class ImportPreview:
    batch_id: int
    bank_account_id: int
    original_filename: str
    sha256: str
    format_label: str  # e.g. "CAMT.053-bestand"
    bank_label: str | None  # e.g. "ING"
    period_start: date | None
    period_end: date | None
    new_rows: tuple[PreviewRow, ...] = ()
    existing_rows: tuple[PreviewRow, ...] = ()
    maybe_rows: tuple[PreviewRow, ...] = ()
    warnings: tuple[str, ...] = ()
    already_imported_on: datetime | None = None  # same file already afgerond: confirm disabled

    @property
    def new_count(self) -> int:
        return len(self.new_rows)

    @property
    def existing_count(self) -> int:
        return len(self.existing_rows)

    @property
    def maybe_count(self) -> int:
        return len(self.maybe_rows)

    @property
    def total_count(self) -> int:
        return self.new_count + self.existing_count + self.maybe_count

    @property
    def can_confirm(self) -> bool:
        return self.already_imported_on is None and (self.new_count + self.maybe_count) > 0


@dataclass(frozen=True)
class ImportResult:
    batch_id: int
    new_count: int
    skipped_count: int  # exact duplicates (al eerder geïmporteerd)
    maybe_skipped_count: int  # mogelijk dubbel, not opted in
    already_processed: bool = False  # confirm was repeated: nothing inserted
