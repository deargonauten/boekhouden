"""Foreign currency helpers. Integer arithmetic only, no floats.

A wisselkoers is stored as "foreign units per 1 euro" times 1.000.000 (the way the ECB
publishes it: 1 EUR = 1,0842 USD is 1_084_200). Amounts stay integer cents.
"""

import re

from app.domain.errors import LedgerError
from app.domain.money import format_euro, require_cents

INVALID_EXCHANGE_RATE = "INVALID_EXCHANGE_RATE"
INVALID_CURRENCY = "INVALID_CURRENCY"

RATE_SCALE = 1_000_000
BASE_CURRENCY = "EUR"

_RATE_RE = re.compile(r"(\d+)(?:[.,](\d{1,6}))?")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")

RATE_MESSAGE = (
    "Vul de wisselkoers in als aantal buitenlandse munten voor 1 euro, bijvoorbeeld 1,0842. "
    "Gebruik maximaal 6 cijfers achter de komma."
)


def parse_rate(text: str | None) -> int:
    """'1,0842' -> 1_084_200. Rejects blank, zero, negative and over-precise input."""
    match = _RATE_RE.fullmatch((text or "").strip())
    if match is None:
        raise LedgerError(INVALID_EXCHANGE_RATE, RATE_MESSAGE)
    whole, frac = match.group(1), (match.group(2) or "").ljust(6, "0")
    rate = int(whole) * RATE_SCALE + int(frac)
    if rate <= 0:
        raise LedgerError(INVALID_EXCHANGE_RATE, RATE_MESSAGE)
    return rate


def format_rate(rate_micro: int) -> str:
    """1_084_200 -> '1,0842' (trailing zeros dropped, at least two decimals)."""
    whole, frac = divmod(rate_micro, RATE_SCALE)
    return f"{whole},{f'{frac:06d}'.rstrip('0').ljust(2, '0')}"


def to_eur_cents(foreign_cents: int, rate_micro: int) -> int:
    """Convert foreign cents to euro cents, rounded half away from zero."""
    require_cents(foreign_cents)
    sign = -1 if foreign_cents < 0 else 1
    return sign * ((abs(foreign_cents) * RATE_SCALE * 2 + rate_micro) // (rate_micro * 2))


def normalize_currency(raw: str | None) -> str:
    """Upper-case ISO code; blank means euro."""
    value = (raw or "").strip().upper()
    if not value:
        return BASE_CURRENCY
    if _CURRENCY_RE.fullmatch(value) is None:
        raise LedgerError(
            INVALID_CURRENCY,
            "Een valuta schrijf je als code van drie letters, bijvoorbeeld EUR, USD of GBP.",
        )
    return value


def format_amount(cents: int, currency: str) -> str:
    """'€ 1,00' for euro, otherwise 'USD 1.234,56' (negatives '-GBP 1,00')."""
    if currency == BASE_CURRENCY:
        return format_euro(cents)
    sign = "-" if cents < 0 else ""
    return f"{sign}{currency} {format_euro(abs(cents))[2:]}"
