"""The single JSON schema for extraction output, plus tolerant parsing.

Model output is untrusted: `parse_extraction` never raises for one bad field
(it becomes None with confidence "low"); only a payload with nothing usable at
all raises `ExtractionFailedError`. Cents must be real JSON integers; floats,
bools and numeric strings are rejected, never rounded.

Confidence keys (flat, header level): kind, supplier_name, supplier_kvk,
supplier_btw_number, supplier_iban, supplier_address_line, supplier_postal_code,
supplier_city, supplier_country, invoice_number, invoice_date, due_date,
currency, total_excl_cents, total_vat_cents, total_incl_cents. Line level:
description, amount_excl_cents, vat_code, vat_amount_cents,
suggested_account_code.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from app.domain.extraction.extractors.errors import failed
from app.domain.extraction.types import Confidence, ExtractedInvoice, ExtractedLine
from app.domain.relations import ExtractedContact

KINDS = ("invoice", "credit_note", "receipt", "unknown")
CONFIDENCE_LEVELS = ("high", "medium", "low")

SUPPLIER_FIELDS = (
    "name",
    "kvk",
    "btw_number",
    "iban",
    "address_line",
    "postal_code",
    "city",
    "country",
)
HEADER_FIELDS = (
    "kind",
    *(f"supplier_{f}" for f in SUPPLIER_FIELDS),
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "total_excl_cents",
    "total_vat_cents",
    "total_incl_cents",
)
LINE_FIELDS = (
    "description",
    "amount_excl_cents",
    "vat_code",
    "vat_amount_cents",
    "suggested_account_code",
)

_NULLABLE_STRING = {"type": ["string", "null"]}
_NULLABLE_CENTS = {"type": ["integer", "null"]}
_NULLABLE_DATE = {
    "type": ["string", "null"],
    "description": "ISO date YYYY-MM-DD, or null",
}


def _confidence_schema(fields: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "description": "Confidence per field you are not fully sure about or did find.",
        "properties": {f: {"type": "string", "enum": list(CONFIDENCE_LEVELS)} for f in fields},
    }


JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "supplier": {
            "type": "object",
            "description": "The party that ISSUED the document, not the buyer.",
            "properties": {f: _NULLABLE_STRING for f in SUPPLIER_FIELDS},
        },
        "invoice_number": _NULLABLE_STRING,
        "invoice_date": _NULLABLE_DATE,
        "due_date": _NULLABLE_DATE,
        "currency": {"type": "string", "description": "ISO 4217 code, default EUR"},
        "total_excl_cents": _NULLABLE_CENTS,
        "total_vat_cents": _NULLABLE_CENTS,
        "total_incl_cents": _NULLABLE_CENTS,
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": _NULLABLE_STRING,
                    "amount_excl_cents": _NULLABLE_CENTS,
                    "vat_code": _NULLABLE_STRING,
                    "vat_amount_cents": _NULLABLE_CENTS,
                    "suggested_account_code": _NULLABLE_STRING,
                    "source_text": {
                        "type": ["string", "null"],
                        "description": "Short verbatim excerpt (max ~80 chars) of the document text this line was read from, copied exactly as printed, or null",
                    },
                    "confidence": _confidence_schema(LINE_FIELDS),
                },
            },
        },
        "confidence": _confidence_schema(HEADER_FIELDS),
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "supplier", "lines"],
}

_CURRENCY = re.compile(r"^[A-Za-z]{3}$")
_MISSING = object()


def _low(conf: dict[str, Confidence], key: str) -> None:
    conf[key] = "low"


def _string(value: Any, conf: dict, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _low(conf, key)
        return None
    value = value.strip()
    return value or None


def _cents(value: Any, conf: dict, key: str) -> int | None:
    if value is None:
        return None
    # bool is an int subclass; floats (even 10.0) are never accepted.
    if isinstance(value, bool) or not isinstance(value, int):
        _low(conf, key)
        return None
    return value


def _date(value: Any, conf: dict, key: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _low(conf, key)
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        _low(conf, key)
        return None


def _confidence(value: Any) -> dict[str, Confidence]:
    if not isinstance(value, dict):
        return {}
    return {
        k: v for k, v in value.items() if isinstance(k, str) and v in CONFIDENCE_LEVELS
    }


def _source_text(value: Any) -> str | None:
    """Optional hint for the review screen; anything odd is simply dropped."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:200] or None


def _parse_line(data: Any) -> ExtractedLine | None:
    if not isinstance(data, dict):
        return None
    forced: dict[str, Confidence] = {}
    line = ExtractedLine(
        description=_string(data.get("description"), forced, "description"),
        amount_excl_cents=_cents(data.get("amount_excl_cents"), forced, "amount_excl_cents"),
        vat_code=_string(data.get("vat_code"), forced, "vat_code"),
        vat_amount_cents=_cents(data.get("vat_amount_cents"), forced, "vat_amount_cents"),
        suggested_account_code=_string(
            data.get("suggested_account_code"), forced, "suggested_account_code"
        ),
        confidence={**_confidence(data.get("confidence")), **forced},
        source_text=_source_text(data.get("source_text")),
    )
    return line


def _notes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(n.strip() for n in value if isinstance(n, str) and n.strip())


def parse_extraction(payload: Any) -> ExtractedInvoice:
    """Turn a model payload into an `ExtractedInvoice`; see module docstring."""
    known = {"kind", "supplier", "lines", "invoice_number", "invoice_date", "due_date",
             "currency", "total_excl_cents", "total_vat_cents", "total_incl_cents"}
    if not isinstance(payload, dict) or not known & payload.keys():
        raise failed()

    forced: dict[str, Confidence] = {}

    kind = payload.get("kind", _MISSING)
    if kind is _MISSING or kind is None:
        kind = "invoice"
    elif kind not in KINDS:
        kind = "unknown"

    supplier_data = payload.get("supplier")
    if not isinstance(supplier_data, dict):
        supplier_data = {}
    supplier = ExtractedContact(
        **{
            f: _string(supplier_data.get(f), forced, f"supplier_{f}")
            for f in SUPPLIER_FIELDS
        }
    )

    currency = payload.get("currency")
    if currency is None:
        currency = "EUR"
    elif isinstance(currency, str) and _CURRENCY.match(currency.strip()):
        currency = currency.strip().upper()
    else:
        _low(forced, "currency")
        currency = "EUR"

    raw_lines = payload.get("lines")
    lines = tuple(
        line
        for line in (_parse_line(x) for x in (raw_lines if isinstance(raw_lines, list) else []))
        if line is not None
    )

    try:
        raw = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = None

    return ExtractedInvoice(
        kind=kind,
        supplier=supplier,
        invoice_number=_string(payload.get("invoice_number"), forced, "invoice_number"),
        invoice_date=_date(payload.get("invoice_date"), forced, "invoice_date"),
        due_date=_date(payload.get("due_date"), forced, "due_date"),
        currency=currency,
        total_excl_cents=_cents(payload.get("total_excl_cents"), forced, "total_excl_cents"),
        total_vat_cents=_cents(payload.get("total_vat_cents"), forced, "total_vat_cents"),
        total_incl_cents=_cents(payload.get("total_incl_cents"), forced, "total_incl_cents"),
        lines=lines,
        confidence={**_confidence(payload.get("confidence")), **forced},
        notes=_notes(payload.get("notes")),
        raw=raw,
    )
