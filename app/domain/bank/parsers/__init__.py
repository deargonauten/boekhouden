"""Bank statement parsers. `parse_statement` detects the format by content."""

from app.domain.bank.parsers.base import NOT_TEXT_MESSAGE, StatementParser
from app.domain.bank.parsers.camt053 import Camt053Parser
from app.domain.bank.parsers.csv_banks import UNKNOWN_CSV_MESSAGE, CsvParser
from app.domain.bank.parsers.mt940 import Mt940Parser
from app.domain.bank.types import (
    EMPTY,
    FILE_TOO_BIG,
    MAX_FILE_BYTES,
    UNKNOWN_FORMAT,
    BankImportError,
    ParsedStatement,
)

PARSERS: tuple[StatementParser, ...] = (Camt053Parser(), Mt940Parser(), CsvParser())

FORMAT_LABELS = {"camt053": "CAMT.053-bestand", "mt940": "MT940-bestand", "csv": "CSV-export"}
BANK_LABELS = {"ing": "ING", "rabobank": "Rabobank", "abn_amro": "ABN AMRO", "bunq": "bunq", "overig": "overige bank"}


def format_description(statement: ParsedStatement) -> str:
    """'CAMT.053-bestand van ING' / 'CSV-export van Rabobank' (bank omitted when unknown)."""
    label = FORMAT_LABELS[statement.format]
    bank = BANK_LABELS.get(statement.bank or "")
    return f"{label} van {bank}" if bank else label


def parse_statement(content: bytes, hint_bank: str | None = None) -> ParsedStatement:
    """Detect the format by content (never by extension) and parse it.

    Raises BankImportError (Dutch message) for oversized, empty, unknown, unreadable or
    transaction-less files.
    """
    if len(content) > MAX_FILE_BYTES:
        raise BankImportError(
            FILE_TOO_BIG, "Dit bestand is groter dan 10 MB. Download een afschrift over een kortere periode."
        )
    if not content.strip():
        raise BankImportError(EMPTY, "Het bestand is leeg. Download het afschrift opnieuw bij je bank.")
    if content.lstrip()[:5] == b"%PDF-":
        raise BankImportError(
            UNKNOWN_FORMAT,
            "Dit is een PDF. Bankafschriften importeren kan alleen als CAMT.053 (XML), MT940 of CSV. "
            "Download het afschrift in een van die formaten.",
        )
    for parser in PARSERS:
        if parser.detect(content):
            statement = parser.parse(content, hint_bank)
            if not statement.transactions:
                raise BankImportError(EMPTY, "Er staan geen transacties in dit bestand.")
            return statement
    # Nothing matched: explain based on what the file looks like.
    if b"\x00" in content[:4096]:
        raise BankImportError(UNKNOWN_FORMAT, NOT_TEXT_MESSAGE)
    raise BankImportError(UNKNOWN_FORMAT, UNKNOWN_CSV_MESSAGE)


__all__ = ["BANK_LABELS", "FORMAT_LABELS", "PARSERS", "format_description", "parse_statement"]
