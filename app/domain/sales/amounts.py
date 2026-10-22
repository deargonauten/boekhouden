"""Pure amount rules of the verkoopfacturen: integer cents, half-up rounding, no floats."""

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.domain.errors import InvalidAmountError
from app.domain.money import parse_euro
from app.domain.sales.errors import INVALID_INPUT, UNSUPPORTED_VAT, UNSUPPORTED_VAT_MESSAGE, SalesError
from app.domain.sales.types import AgeingRow, LineInput, Totals, VatGroup


def _round_div(numerator: int, denominator: int) -> int:
    """round_half_up(numerator / denominator) for non-negative integers."""
    return (2 * numerator + denominator) // (2 * denominator)


def line_excl(quantity_milli: int, unit_price_cents: int) -> int:
    """Line amount excl. BTW: quantity (thousandths) x price, rounded half up to a cent."""
    return _round_div(quantity_milli * unit_price_cents, 1000)


def compute_totals(lines: Sequence[LineInput], rates: Mapping[str, int]) -> Totals:
    """Line amounts, VAT per rate group (rounded once on the group sum) and the totals."""
    amounts: list[int] = []
    bases: dict[str, int] = {}
    for line in lines:
        rate = rates.get(line.vat_code)
        if rate is None:
            raise SalesError(UNSUPPORTED_VAT, UNSUPPORTED_VAT_MESSAGE, field="lines")
        amount = line_excl(line.quantity_milli, line.unit_price_cents)
        amounts.append(amount)
        bases[line.vat_code] = bases.get(line.vat_code, 0) + amount
    groups = tuple(
        sorted(
            (
                VatGroup(code, rates[code], base, _round_div(base * rates[code], 10000))
                for code, base in bases.items()
            ),
            key=lambda g: (-g.rate_bp, g.vat_code),
        )
    )
    total_excl = sum(g.base_cents for g in groups)
    total_vat = sum(g.vat_cents for g in groups)
    return Totals(tuple(amounts), groups, total_excl, total_vat, total_excl + total_vat)


def due_date(invoice_date: date, days: int) -> date:
    return invoice_date + timedelta(days=days)


def _bad(message: str, field: str | None = None) -> SalesError:
    return SalesError(INVALID_INPUT, message, field=field)


def parse_quantity(text: str) -> int:
    """'1,5' / '1.5' -> 1500 (thousandths). At most 3 decimals, greater than zero."""
    cleaned = (text or "").strip().replace(",", ".")
    message = "Vul een aantal in, bijvoorbeeld 1 of 2,5 (maximaal drie cijfers achter de komma)."
    if not re.fullmatch(r"\d+(\.\d{1,3})?", cleaned):
        raise _bad(message)
    try:
        milli = int(Decimal(cleaned) * 1000)
    except InvalidOperation:  # pragma: no cover - regex already guards this
        raise _bad(message) from None
    if milli <= 0:
        raise _bad("Het aantal moet groter zijn dan nul.")
    return milli


def format_quantity(milli: int) -> str:
    """1500 -> '1,5'; 1000 -> '1'."""
    whole, rest = divmod(milli, 1000)
    return f"{whole},{rest:03d}".rstrip("0") if rest else str(whole)


def parse_price(text: str) -> int:
    """Price in cents from '12,50', '12.50', '1.234,56' or '12'. Never negative."""
    cleaned = re.sub(r"\s+", "", (text or "").replace("€", ""))
    if re.fullmatch(r"\d+\.\d{1,2}", cleaned):  # English decimal point: 12.50
        cleaned = cleaned.replace(".", ",")
    try:
        cents = parse_euro(cleaned)
    except InvalidAmountError:
        raise _bad(
            f"'{(text or '').strip()}' is geen geldig bedrag. Schrijf bijvoorbeeld 12,50 "
            "(maximaal twee cijfers achter de komma)."
        ) from None
    if cents < 0:
        raise _bad("De prijs mag niet negatief zijn. Voor een terugbetaling maak je een creditnota.")
    return cents


_BUCKET_FIELDS = {
    "not_due": "not_due_cents",
    "d1_30": "d1_30_cents",
    "d31_60": "d31_60_cents",
    "d61_90": "d61_90_cents",
    "over_90": "over_90_cents",
}


def ageing_bucket(due: date, today: date) -> str:
    """Bucket key by days past the vervaldatum on `today` (0 or less: not yet due)."""
    days = (today - due).days
    if days <= 0:
        return "not_due"
    if days <= 30:
        return "d1_30"
    if days <= 60:
        return "d31_60"
    if days <= 90:
        return "d61_90"
    return "over_90"


def add_to_bucket(row: AgeingRow, bucket: str, cents: int) -> AgeingRow:
    from dataclasses import replace

    name = _BUCKET_FIELDS[bucket]
    return replace(row, **{name: getattr(row, name) + cents})
