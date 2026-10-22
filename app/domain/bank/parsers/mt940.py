"""MT940 (SWIFT customer statement) parser.

Handles the common flavours of ING, Rabobank and ABN AMRO: optional SWIFT block
wrapper ({1:..}{4: .. -}), `:20:`, `:25:`, `:60F:`, `:61:` + `:86:` pairs, `:62F:`,
multi-line `:86:` and the structured subfield styles (`/TRTP/../NAME/..` and `?20..?34`).
"""

import re
from datetime import date

from app.domain.bank.amounts import parse_amount
from app.domain.bank.iban import bank_from_iban, find_iban
from app.domain.bank.parsers.base import (
    clean_iban,
    clean_reference,
    collapse,
    decode_text,
    make_date,
    parse_error,
    parse_slash_fields,
    remittance_from_slash,
    require_eur,
)
from app.domain.bank.types import (
    PARSE_ERROR,
    BankImportError,
    ParsedStatement,
    ParsedTransaction,
)

_TAG_RE = re.compile(r"^:(\d{2}[A-Z]?):", re.MULTILINE)
_BALANCE_RE = re.compile(r"^([CD])(\d{6})([A-Z]{3})([\d,]+)$")
_STMT_LINE_RE = re.compile(
    r"^(?P<value>\d{6})(?P<entry>\d{4})?(?P<mark>RC|RD|C|D)(?P<funds>[A-Z])?(?P<amount>\d+,\d*)"
    r"(?P<type>[A-Z][A-Z0-9]{3})(?P<rest>.*)$",
    re.DOTALL,
)
_BANK_MARKERS = {"INGB": "ing", "RABO": "rabobank", "ABNA": "abn_amro", "BUNQ": "bunq"}


def _yymmdd(s: str, where: str) -> date:
    yy = int(s[0:2])
    year = 2000 + yy if yy < 80 else 1900 + yy
    return make_date(year, int(s[2:4]), int(s[4:6]), where)


def _split_fields(text: str) -> list[tuple[str, str]]:
    """Split the message into (tag, value) pairs; continuation lines belong to the previous tag."""
    text = re.sub(r"\r\n?", "\n", text)
    matches = list(_TAG_RE.finditer(text))
    fields = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end() : end]
        value = re.sub(r"\n-\}?\s*$|\n\}.*$", "", value.rstrip("\n"), flags=re.DOTALL)
        fields.append((m.group(1), value.strip("\n")))
    return fields


def _balance(value: str, where: str) -> int:
    m = _BALANCE_RE.match(value.strip())
    if not m:
        raise parse_error(where, "heeft een saldo dat we niet kunnen lezen")
    require_eur(m.group(3), where)
    cents = parse_amount(m.group(4), "mt940")
    return -cents if m.group(1) == "D" else cents


def _entry_date(value_date: date, mmdd: str | None, where: str) -> date:
    if not mmdd:
        return value_date
    month, day = int(mmdd[:2]), int(mmdd[2:])
    best = None
    for year in (value_date.year - 1, value_date.year, value_date.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - value_date).days) < abs((best - value_date).days):
            best = cand
    if best is None:
        raise parse_error(where, "heeft een ongeldige boekingsdatum")
    return best


def _details_full(text: str) -> tuple[str | None, str | None, str, str | None]:
    lines = text.split("\n")
    flat = "".join(lines) if text.lstrip().startswith("/") else " ".join(lines)
    if re.search(r"\?\d{2}", flat):  # structured ?00..?63 style
        sub: dict[str, str] = {}
        for m in re.finditer(r"\?(\d{2})(.*?)(?=\?\d{2}|$)", flat):
            sub[m.group(1)] = sub.get(m.group(1), "") + m.group(2)
        desc = collapse(" ".join(sub.get(f"2{d}", "") for d in range(10)))
        name = collapse(sub.get("32", "") + " " + sub.get("33", "")) or None
        iban = clean_iban(sub.get("31")) or find_iban(flat)
        return name, iban, desc, None
    if re.search(r"/(TRTP|NAME|REMI|IBAN|EREF)/", flat):
        fields = parse_slash_fields(flat)
        iban = clean_iban(fields.get("IBAN")) or clean_iban(fields.get("IBAN2"))
        name = collapse(fields.get("NAME", "")) or None
        return name, iban, remittance_from_slash(fields), clean_reference(fields.get("EREF"))
    return None, find_iban(flat), collapse(flat), None


class Mt940Parser:
    def detect(self, content: bytes) -> bool:
        if b"\x00" in content[:2048]:
            return False
        text = content[:200000].decode("latin-1")
        return bool(re.search(r"^:20:", text, re.M) and re.search(r"^:61:", text, re.M) and re.search(r"^:25:", text, re.M))

    def parse(self, content: bytes, hint_bank: str | None = None) -> ParsedStatement:
        text = decode_text(content)
        fields = _split_fields(text)
        iban: str | None = None
        opening: int | None = None
        closing: int | None = None
        transactions: list[ParsedTransaction] = []
        ibans: list[str] = []
        seen_opening = False
        pending: tuple[str, str] | None = None  # (:61: value, where)
        number = 0

        def flush(statement_line: str | None, info: str, where: str):
            if statement_line is None:
                return
            transactions.append(self._transaction(statement_line, info, where))

        for tag, value in fields:
            if tag == "25":
                account = find_iban(value)
                if account and account not in ibans:
                    ibans.append(account)
            elif tag in ("60F", "60M"):
                flush_pending = pending
                if flush_pending:
                    flush(flush_pending[0], "", flush_pending[1])
                    pending = None
                if not seen_opening:
                    opening = _balance(value, "het beginsaldo")
                    seen_opening = True
            elif tag == "61":
                if pending:
                    flush(pending[0], "", pending[1])
                number += 1
                pending = (value, f"transactie {number}")
            elif tag == "86":
                if pending:
                    flush(pending[0], value, pending[1])
                    pending = None
            elif tag in ("62F", "62M"):
                if pending:
                    flush(pending[0], "", pending[1])
                    pending = None
                closing = _balance(value, "het eindsaldo")
        if pending:
            flush(pending[0], "", pending[1])

        if len(ibans) > 1:
            raise BankImportError(
                PARSE_ERROR,
                "In dit bestand staan afschriften van meerdere rekeningen. "
                "Download het afschrift per rekening en importeer ze apart.",
            )
        iban = ibans[0] if ibans else None
        header = text[:300].upper()
        bank = bank_from_iban(iban)
        if bank is None:
            bank = next((b for marker, b in _BANK_MARKERS.items() if marker in header), None)
        return ParsedStatement(
            account_iban=iban,
            currency="EUR",
            opening_cents=opening,
            closing_cents=closing,
            transactions=tuple(transactions),
            format="mt940",
            bank=bank,
        )

    def _transaction(self, line: str, info: str, where: str) -> ParsedTransaction:
        first, _, supplementary = line.partition("\n")
        m = _STMT_LINE_RE.match(first)
        if not m:
            raise parse_error(where, "(:61:) heeft een opbouw die we niet herkennen")
        value_date = _yymmdd(m["value"], where)
        booking = _entry_date(value_date, m["entry"], where)
        cents = parse_amount(m["amount"], "mt940")
        mark = m["mark"]
        if mark in ("D", "RC"):
            cents = -cents
        if cents == 0:
            raise parse_error(where, "heeft een bedrag van 0")
        rest = m["rest"]
        ref_part, _, bank_ref = rest.partition("//")
        customer_ref = clean_reference(ref_part)
        name, iban, desc, e2e = _details_full(info) if info else (None, None, "", None)
        if not info and supplementary.strip():
            name, iban, desc, e2e = _details_full(supplementary)
        return ParsedTransaction(
            booking_date=booking,
            value_date=value_date,
            amount_cents=cents,
            counterparty_name=name,
            counterparty_iban=iban,
            description=desc,
            end_to_end_id=e2e or customer_ref,
            bank_reference=collapse(bank_ref) or None,
            raw=f":61:{line}\n:86:{info}" if info else f":61:{line}",
        )
