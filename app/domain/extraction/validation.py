"""Deterministic checks on an extracted invoice.

`assess` never raises and can only add doubt: it turns model confidence
(medium/low) and our own checks into plain-Dutch flags, one per field.

Flag field names: header fields `invoice_number`, `invoice_date`, `due_date`,
`currency`, `kind`, `total_excl`, `total_vat`, `total_incl`, `supplier_name`,
`supplier_kvk`, `supplier_btw_number`, `supplier_iban`, ...; line fields
`line.<index>.<amount|vat_code|vat_amount|account|description>`.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.domain.extraction.suggestions import (
    VAT_TOLERANCE_CENTS,
    AccountRef,
    half_up_vat,
    resolve_account_code,
    resolve_vat_code,
)
from app.domain.extraction.types import ExtractedInvoice
from app.domain.money import format_euro
from app.domain.relations.validation import (
    is_valid_btw_number,
    is_valid_iban,
    is_valid_kvk,
    normalize_btw_number,
    normalize_iban,
    normalize_kvk,
)

Level = Literal["low", "medium", "info"]
_RANK = {"info": 0, "medium": 1, "low": 2}

NOT_FOUND = "Niet gevonden op de factuur. Vul dit zelf in."
UNSURE = "Het programma is hier niet zeker van. Controleer dit."


@dataclass(frozen=True)
class Flag:
    field: str
    level: Level
    reason: str


def line_field(index: int, name: str) -> str:
    return f"line.{index}.{name}"


# Names the extractor schema may use for confidence keys -> our flag field names.
_ALIASES = {
    "total_excl_cents": "total_excl",
    "total_vat_cents": "total_vat",
    "total_incl_cents": "total_incl",
}
_LINE_ALIASES = {
    "amount_excl_cents": "amount",
    "vat_amount_cents": "vat_amount",
    "suggested_account_code": "account",
}
_SUPPLIER_KEYS = {
    "name", "kvk", "btw_number", "iban", "address_line", "postal_code", "city", "country",
}


def _header_field(key: str) -> str:
    key = key.replace("supplier.", "supplier_")
    if key in _SUPPLIER_KEYS:
        key = f"supplier_{key}"
    return _ALIASES.get(key, key)


def _one_year_before(today: date) -> date:
    try:
        return today.replace(year=today.year - 1)
    except ValueError:  # 29 February
        return today.replace(year=today.year - 1, day=28)


def _rate_text(rate_bp: int) -> str:
    if rate_bp % 100 == 0:
        return str(rate_bp // 100)
    return f"{rate_bp / 100:.2f}".replace(".", ",")


def assess(
    invoice: ExtractedInvoice,
    accounts: Iterable[AccountRef],
    vat_codes: Mapping[str, int],
    today: date,
) -> list[Flag]:
    """All flags for `invoice`; `vat_codes` maps active BTW codes to rate in basis points."""
    accounts = list(accounts)
    raw: list[Flag] = []

    def add(field: str, level: Level, reason: str) -> None:
        raw.append(Flag(field, level, reason))

    # model confidence first, our own checks may raise the level afterwards
    for key, conf in invoice.confidence.items():
        if conf in ("medium", "low"):
            add(_header_field(key), conf, UNSURE)
    for i, line in enumerate(invoice.lines):
        for key, conf in line.confidence.items():
            if conf in ("medium", "low"):
                add(line_field(i, _LINE_ALIASES.get(key, key)), conf, UNSURE)

    # d. missing basics
    if not (invoice.supplier.name or "").strip():
        add("supplier_name", "low", NOT_FOUND)
    if invoice.invoice_number is None or not invoice.invoice_number.strip():
        add("invoice_number", "low", NOT_FOUND)
    if invoice.invoice_date is None:
        add("invoice_date", "low", NOT_FOUND)
    else:
        # e. date window
        if invoice.invoice_date > today or invoice.invoice_date < _one_year_before(today):
            add(
                "invoice_date",
                "medium",
                "Controleer de datum: die ligt in de toekomst of meer dan een jaar geleden.",
            )

    # f. supplier identifiers (kept for the user to correct, never used for matching)
    sup = invoice.supplier
    for field, raw_value, normalize, valid, hint in (
        ("supplier_kvk", sup.kvk, normalize_kvk, is_valid_kvk,
         "Het KvK-nummer klopt niet (8 cijfers). Controleer het nummer."),
        ("supplier_btw_number", sup.btw_number, normalize_btw_number, is_valid_btw_number,
         "Het btw-nummer klopt niet (bijvoorbeeld NL123456789B01). Controleer het nummer."),
        ("supplier_iban", sup.iban, normalize_iban, is_valid_iban,
         "Het IBAN klopt niet (controlecijfers kloppen niet). Controleer het rekeningnummer."),
    ):
        value = normalize(raw_value)
        if value is not None and not valid(value):
            add(field, "low", hint)

    # i/j. currency and kind
    if (invoice.currency or "EUR").upper() != "EUR":
        add("currency", "low", "Deze factuur is niet in euro's; bedragen zijn niet omgerekend.")
    if invoice.kind == "credit_note":
        add("kind", "info", "Dit is een creditnota")

    # g/h. per line: account and BTW code
    resolved_codes: list[str | None] = []
    for i, line in enumerate(invoice.lines):
        if resolve_account_code(line.suggested_account_code, accounts) is None:
            add(line_field(i, "account"), "low", "Kies zelf een rekening.")
        code, inferred = resolve_vat_code(line, vat_codes)
        resolved_codes.append(code)
        if inferred:
            add(line_field(i, "vat_code"), "medium", "Tarief afgeleid uit het bedrag. Controleer dit.")
        elif code is None:
            add(line_field(i, "vat_code"), "low", "Kies zelf het BTW-tarief.")

    # a. lines vs total
    amounts = [ln.amount_excl_cents for ln in invoice.lines]
    if invoice.lines and invoice.total_excl_cents is not None and None not in amounts:
        line_sum = sum(amounts)  # type: ignore[arg-type]
        if line_sum != invoice.total_excl_cents:
            add(
                "total_excl",
                "low",
                f"De regels tellen op tot {format_euro(line_sum)}, maar het totaal op de "
                f"factuur is {format_euro(invoice.total_excl_cents)}.",
            )

    # b. BTW arithmetic per code group
    groups: dict[str, list[int]] = {}
    for i, code in enumerate(resolved_codes):
        if code is not None:
            groups.setdefault(code, []).append(i)
    for code, idxs in groups.items():
        lines = [invoice.lines[i] for i in idxs]
        if any(ln.amount_excl_cents is None or ln.vat_amount_cents is None for ln in lines):
            continue
        excl = sum(ln.amount_excl_cents for ln in lines)  # type: ignore[misc]
        given = sum(ln.vat_amount_cents for ln in lines)  # type: ignore[misc]
        rate_bp = vat_codes[code]
        expected = half_up_vat(excl, rate_bp)
        if abs(given - expected) > VAT_TOLERANCE_CENTS:
            add(
                line_field(idxs[0], "vat_amount"),
                "low",
                f"Bij {_rate_text(rate_bp)}% BTW over {format_euro(excl)} hoort "
                f"{format_euro(expected)}, maar op de factuur staat {format_euro(given)}.",
            )

    # c. excl + vat = incl
    if None not in (invoice.total_excl_cents, invoice.total_vat_cents, invoice.total_incl_cents):
        expected_incl = invoice.total_excl_cents + invoice.total_vat_cents  # type: ignore[operator]
        if expected_incl != invoice.total_incl_cents:
            add(
                "total_incl",
                "low",
                f"Bedrag zonder BTW plus BTW is {format_euro(expected_incl)}, maar het totaal "
                f"incl. BTW op de factuur is {format_euro(invoice.total_incl_cents)}.",  # type: ignore[arg-type]
            )

    return merge_flags(raw)


def merge_flags(flags: list[Flag]) -> list[Flag]:
    """One flag per field: highest level, reasons joined (own checks before model doubt)."""
    order: list[str] = []
    by_field: dict[str, list[Flag]] = {}
    for f in flags:
        if f.field not in by_field:
            order.append(f.field)
        by_field[f.field] = [*by_field.get(f.field, []), f]
    merged: list[Flag] = []
    for field in order:
        group = by_field[field]
        level = max((f.level for f in group), key=_RANK.__getitem__)
        specific = [f.reason for f in group if f.reason != UNSURE]
        reasons = specific or [UNSURE]
        merged.append(Flag(field, level, " ".join(dict.fromkeys(reasons))))
    return merged


def flagged_fields(flags: Iterable[Flag]) -> list[str]:
    """Distinct fields the owner should check (info flags do not count)."""
    seen: dict[str, None] = {}
    for f in flags:
        if f.level in ("low", "medium"):
            seen.setdefault(f.field)
    return list(seen)
