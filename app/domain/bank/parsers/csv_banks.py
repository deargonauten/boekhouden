"""CSV exports of ING, Rabobank, ABN AMRO and bunq.

Layouts are data (`CsvLayout`): a header signature, a column mapping, a date format,
an amount style and a sign rule. A new export variant is a new entry in `LAYOUTS`.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime

from app.domain.bank.amounts import parse_amount
from app.domain.bank.iban import find_iban
from app.domain.bank.parsers.base import (
    clean_iban,
    clean_reference,
    collapse,
    decode_text,
    parse_error,
    parse_slash_fields,
    remittance_from_slash,
    require_eur,
)
from app.domain.bank.types import (
    PARSE_ERROR,
    UNKNOWN_FORMAT,
    BankImportError,
    ParsedStatement,
    ParsedTransaction,
)

UNKNOWN_CSV_MESSAGE = (
    "Dit CSV-bestand herkennen we niet. Download het afschrift als CAMT.053 (XML) of MT940 "
    "als je bank dat aanbiedt, of kies het exportformaat van ING, Rabobank, ABN AMRO of bunq."
)

DELIMITERS = (";", ",", "\t")


@dataclass(frozen=True)
class CsvLayout:
    key: str
    bank: str
    # Every group must have at least one header present (lowercase alternatives).
    signature: tuple[tuple[str, ...], ...]
    # field -> candidate header names (lowercase); description may list several columns.
    columns: dict[str, tuple[str, ...]]
    date_format: str  # strptime format
    amount_style: str  # nl | en
    sign_rule: str  # "signed" | "af_bij"
    # Headerless exports (ABN AMRO .TAB): field -> column index, and a row check.
    positions: dict[str, int] | None = None
    delimiters: tuple[str, ...] = DELIMITERS
    af_values: tuple[str, ...] = ("af", "debit", "debet")
    bij_values: tuple[str, ...] = ("bij", "credit")
    description_parser: str | None = None  # "abn" for the SEPA-style ABN AMRO text


ING = CsvLayout(
    key="ing",
    bank="ing",
    signature=(
        ("datum", "date"),
        ("naam / omschrijving", "name / description"),
        ("af bij", "debit/credit"),
        ("bedrag (eur)", "amount (eur)"),
    ),
    columns={
        "date": ("datum", "date"),
        "counterparty_name": ("naam / omschrijving", "name / description"),
        "account": ("rekening", "account"),
        "counterparty_iban": ("tegenrekening", "counterparty"),
        "direction": ("af bij", "debit/credit"),
        "amount": ("bedrag (eur)", "amount (eur)"),
        "description": ("mededelingen", "notifications"),
        "balance": ("saldo na mutatie", "resulting balance"),
    },
    date_format="%Y%m%d",
    amount_style="nl",
    sign_rule="af_bij",
)

RABOBANK = CsvLayout(
    key="rabobank",
    bank="rabobank",
    signature=(("iban/bban",), ("datum",), ("bedrag",), ("volgnr",)),
    columns={
        "account": ("iban/bban",),
        "currency": ("munt",),
        "reference": ("volgnr",),
        "date": ("datum",),
        "value_date": ("rentedatum",),
        "amount": ("bedrag",),
        "balance": ("saldo na trn",),
        "counterparty_iban": ("tegenrekening iban/bban",),
        "counterparty_name": ("naam tegenpartij",),
        "end_to_end_id": ("end to end id",),
        "description": ("omschrijving-1", "omschrijving-2", "omschrijving-3"),
    },
    date_format="%Y-%m-%d",
    amount_style="nl",
    sign_rule="signed",
)

ABN_AMRO_HEADER = CsvLayout(
    key="abn_amro_header",
    bank="abn_amro",
    signature=(("rekeningnummer",), ("transactiedatum",), ("transactiebedrag",)),
    columns={
        "account": ("rekeningnummer",),
        "currency": ("muntsoort",),
        "date": ("transactiedatum",),
        "value_date": ("rentedatum",),
        "amount": ("transactiebedrag",),
        "balance": ("eindsaldo",),
        "description": ("omschrijving",),
    },
    date_format="%Y%m%d",
    amount_style="nl",
    sign_rule="signed",
    delimiters=("\t", ";", ","),
    description_parser="abn",
)

ABN_AMRO_TAB = CsvLayout(
    key="abn_amro_tab",
    bank="abn_amro",
    signature=(),
    columns={},
    positions={
        "account": 0,
        "currency": 1,
        "date": 2,
        "value_date": 5,
        "amount": 6,
        "balance": 4,
        "description": 7,
    },
    date_format="%Y%m%d",
    amount_style="nl",
    sign_rule="signed",
    delimiters=("\t",),
    description_parser="abn",
)

BUNQ = CsvLayout(
    key="bunq",
    bank="bunq",
    signature=(
        ("date", "datum"),
        ("amount", "bedrag"),
        ("account", "rekening"),
        ("counterparty", "tegenpartij"),
        ("name", "naam"),
        ("description", "omschrijving"),
    ),
    columns={
        "date": ("date", "datum"),
        "amount": ("amount", "bedrag"),
        "account": ("account", "rekening"),
        "counterparty_iban": ("counterparty", "tegenpartij"),
        "counterparty_name": ("name", "naam"),
        "description": ("description", "omschrijving"),
    },
    date_format="%Y-%m-%d",
    amount_style="en",
    sign_rule="signed",
    delimiters=(",", ";"),
)

LAYOUTS: tuple[CsvLayout, ...] = (RABOBANK, ABN_AMRO_HEADER, ING, BUNQ, ABN_AMRO_TAB)


def _read_rows(text: str, delimiter: str) -> list[list[str]]:
    try:
        return [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter) if any(c.strip() for c in r)]
    except csv.Error as exc:
        raise BankImportError(PARSE_ERROR, f"Het CSV-bestand kon niet worden gelezen ({exc}). Download het opnieuw.") from exc


def _headers(row: list[str]) -> list[str]:
    return [h.strip().lower().lstrip("﻿") for h in row]


def _header_matches(layout: CsvLayout, headers: list[str]) -> bool:
    if layout.positions is not None or not layout.signature:
        return False
    present = set(headers)
    return all(any(alt in present for alt in group) for group in layout.signature)


def _headerless_matches(layout: CsvLayout, row: list[str]) -> bool:
    if layout.positions is None:
        return False
    if len(row) < 8:
        return False
    return bool(re.fullmatch(r"[A-Za-z]{3}", row[1].strip()) and re.fullmatch(r"\d{8}", row[2].strip()))


def find_layout(text: str, hint_bank: str | None = None) -> tuple[CsvLayout, str, list[list[str]], bool] | None:
    """Return (layout, delimiter, all rows, has_header_row) for the first layout that fits."""
    layouts = sorted(LAYOUTS, key=lambda lay: lay.bank != hint_bank) if hint_bank else LAYOUTS
    cache: dict[str, list[list[str]]] = {}
    for layout in layouts:
        for delimiter in layout.delimiters:
            if delimiter not in text:
                continue
            rows = cache.get(delimiter) or cache.setdefault(delimiter, _read_rows(text, delimiter))
            if not rows:
                continue
            if layout.positions is None and _header_matches(layout, _headers(rows[0])):
                return layout, delimiter, rows, True
            if layout.positions is not None and _headerless_matches(layout, rows[0]):
                return layout, delimiter, rows, False
    return None


def _abn_description(text: str) -> tuple[str | None, str | None, str, str | None]:
    """Split ABN AMRO omschrijving into (name, iban, description, end_to_end_id)."""
    flat = collapse(text)
    if re.search(r"/(TRTP|NAME|REMI|IBAN|EREF)/", flat):
        fields = parse_slash_fields(flat)
        return (
            collapse(fields.get("NAME", "")) or None,
            clean_iban(fields.get("IBAN")),
            remittance_from_slash(fields) or flat,
            clean_reference(fields.get("EREF")),
        )
    labelled = re.compile(r"(IBAN|BIC|Naam|Omschrijving|Kenmerk|Machtiging|Incassant|Betalingskenmerk):", re.I)
    parts = list(labelled.finditer(text))
    if parts:
        values: dict[str, str] = {}
        for i, m in enumerate(parts):
            end = parts[i + 1].start() if i + 1 < len(parts) else len(text)
            values.setdefault(m.group(1).lower(), collapse(text[m.end() : end]))
        desc = values.get("omschrijving") or flat
        return (
            values.get("naam") or None,
            clean_iban(values.get("iban")),
            desc,
            clean_reference(values.get("kenmerk")),
        )
    return None, find_iban(flat), flat, None


class CsvParser:
    def detect(self, content: bytes) -> bool:
        try:
            text = decode_text(content)
        except BankImportError:
            return False
        return find_layout(text) is not None

    def parse(self, content: bytes, hint_bank: str | None = None) -> ParsedStatement:
        text = decode_text(content)
        found = find_layout(text, hint_bank)
        if found is None:
            raise BankImportError(UNKNOWN_FORMAT, UNKNOWN_CSV_MESSAGE)
        layout, _delimiter, rows, has_header = found
        if has_header:
            headers = _headers(rows[0])
            index = {}
            for fld, names in layout.columns.items():
                idxs = [headers.index(n) for n in names if n in headers]
                if fld == "description":
                    index[fld] = idxs
                elif idxs:
                    index[fld] = idxs[:1]
            data_rows = rows[1:]
            first_line = 2
        else:
            index = {fld: [pos] for fld, pos in (layout.positions or {}).items()}
            data_rows = rows
            first_line = 1

        def cell(row: list[str], fld: str) -> str:
            return " ".join(row[i].strip() for i in index.get(fld, []) if i < len(row) and row[i].strip())

        transactions = []
        ibans: list[str] = []
        for n, row in enumerate(data_rows):
            where = f"regel {first_line + n}"
            tx = self._transaction(layout, row, cell, where)
            transactions.append(tx[0])
            if tx[1] and tx[1] not in ibans:
                ibans.append(tx[1])
        if len(ibans) > 1:
            raise BankImportError(
                PARSE_ERROR,
                "In dit bestand staan transacties van meerdere rekeningen. "
                "Download het afschrift per rekening en importeer ze apart.",
            )
        return ParsedStatement(
            account_iban=ibans[0] if ibans else None,
            currency="EUR",
            opening_cents=None,
            closing_cents=None,
            transactions=tuple(transactions),
            format="csv",
            bank=layout.bank,
        )

    def _transaction(self, layout: CsvLayout, row: list[str], cell, where: str):
        def need(fld: str, label: str) -> str:
            value = cell(row, fld)
            if not value:
                raise parse_error(where, f"mist {label}")
            return value

        raw_date = need("date", "de datum")
        try:
            booking = datetime.strptime(raw_date, layout.date_format).date()
        except ValueError as exc:
            raise parse_error(where, f"heeft een datum die we niet snappen ('{raw_date}')") from exc
        value_date = None
        raw_value = cell(row, "value_date")
        if raw_value:
            try:
                value_date = datetime.strptime(raw_value, layout.date_format).date()
            except ValueError:
                value_date = None  # rentedatum is optional information

        raw_amount = need("amount", "het bedrag")
        try:
            cents = parse_amount(raw_amount, layout.amount_style)
        except BankImportError as exc:
            raise parse_error(where, f"heeft een ongeldig bedrag ('{raw_amount}')") from exc
        if layout.sign_rule == "af_bij":
            direction = need("direction", "de aanduiding Af/Bij").lower()
            if direction in layout.af_values:
                cents = -abs(cents)
            elif direction in layout.bij_values:
                cents = abs(cents)
            else:
                raise parse_error(where, f"heeft een onbekende Af/Bij-aanduiding ('{direction}')")
        if cents == 0:
            raise parse_error(where, "heeft een bedrag van 0")

        currency = cell(row, "currency")
        require_eur(currency or None, f"Regel {where.split()[-1]}" if currency else where)

        balance = None
        raw_balance = cell(row, "balance")
        if raw_balance:
            try:
                balance = parse_amount(raw_balance, layout.amount_style)
            except BankImportError:
                balance = None

        name = collapse(cell(row, "counterparty_name")) or None
        iban = clean_iban(cell(row, "counterparty_iban"))
        description = collapse(cell(row, "description"))
        e2e = clean_reference(cell(row, "end_to_end_id"))
        if layout.description_parser == "abn":
            a_name, a_iban, a_desc, a_e2e = _abn_description(cell(row, "description"))
            name, iban, description, e2e = name or a_name, iban or a_iban, a_desc, e2e or a_e2e
        account = clean_iban(cell(row, "account"))
        return (
            ParsedTransaction(
                booking_date=booking,
                value_date=value_date,
                amount_cents=cents,
                counterparty_name=name,
                counterparty_iban=iban,
                description=description,
                end_to_end_id=e2e,
                bank_reference=clean_reference(cell(row, "reference")),
                balance_after_cents=balance,
                raw=", ".join(row) if layout.positions else " | ".join(row),
            ),
            account,
        )
