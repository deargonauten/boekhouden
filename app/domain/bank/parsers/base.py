"""Parser protocol and helpers shared by the statement parsers."""

import re
from datetime import date
from typing import Protocol

from app.domain.bank.iban import is_valid_iban, normalize_iban
from app.domain.bank.types import (
    PARSE_ERROR,
    UNKNOWN_FORMAT,
    BankImportError,
    ParsedStatement,
)


class StatementParser(Protocol):
    def detect(self, content: bytes) -> bool: ...

    def parse(self, content: bytes, hint_bank: str | None = None) -> ParsedStatement: ...


NOT_TEXT_MESSAGE = (
    "Dit bestand is geen tekstbestand en lijkt geen bankafschrift. "
    "Download het afschrift opnieuw als CAMT.053 (XML), MT940 of CSV."
)


def decode_text(content: bytes) -> str:
    """UTF-8 (with or without BOM), then Windows-1252, then ISO-8859-1."""
    if b"\x00" in content:
        raise BankImportError(UNKNOWN_FORMAT, NOT_TEXT_MESSAGE)
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return content.decode("cp1252")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def collapse(text: str | None) -> str:
    """Trim and collapse all whitespace to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def clean_iban(value: str | None) -> str | None:
    """Normalised IBAN if it is a valid one, else None."""
    n = normalize_iban(value)
    return n if is_valid_iban(n) else None


def parse_error(where: str, why: str) -> BankImportError:
    return BankImportError(PARSE_ERROR, f"Het bestand kon niet worden gelezen: {where} {why}. Controleer het bestand of download het opnieuw.")


def require_eur(currency: str | None, where: str) -> None:
    if currency and currency.upper() != "EUR":
        raise BankImportError(
            PARSE_ERROR,
            f"{where} staat in {currency.upper()}. Alleen rekeningen in euro's kunnen worden geïmporteerd.",
        )


def make_date(year: int, month: int, day: int, where: str) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise parse_error(where, "heeft een ongeldige datum") from exc


_NOT_PROVIDED = {"NOTPROVIDED", "NONREF", ""}


def clean_reference(value: str | None) -> str | None:
    v = collapse(value)
    return None if v.upper() in _NOT_PROVIDED else v


_SLASH_KEYS = (
    "TRTP|CSID|NAME|IBAN|BIC|REMI|EREF|ISDT|MARF|ORDP|BENM|ID|ADDR|RTRN|CNTP|PREF|PURP|SVCL|CREF|IBAN2"
)
_SLASH_RE = re.compile(rf"/({_SLASH_KEYS})/")


def parse_slash_fields(text: str) -> dict[str, str]:
    """Parse '/TRTP/SEPA OVERBOEKING/IBAN/NL../NAME/Jansen/REMI/Factuur 1/' into a dict.

    Values may themselves contain '/'; a value ends where the next known key starts.
    """
    matches = list(_SLASH_RE.finditer(text))
    fields: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end() : end].strip().rstrip("/").strip()
        fields.setdefault(m.group(1), value)
    return fields


def remittance_from_slash(fields: dict[str, str]) -> str:
    remi = fields.get("REMI", "")
    remi = re.sub(r"^(USTD|STRD)(/[A-Z]{3})?//", "", remi)
    return collapse(remi) or collapse(fields.get("TRTP", ""))
