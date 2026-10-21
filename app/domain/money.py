"""Money helpers. All amounts are integer cents; floats/bools/Decimals are refused."""

import re

from app.domain.errors import InvalidAmountError

_AMOUNT_RE = re.compile(r"^(-?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?$")


def require_cents(value: object) -> int:
    """Return `value` if it is a real int (not bool), else raise TypeError."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Bedrag moet een geheel aantal centen (int) zijn, niet {type(value).__name__}")
    return value


def parse_euro(text: str) -> int:
    """Parse Dutch-formatted euros ('1.234,56', '12,5', '€ 1,00') to cents."""
    if not isinstance(text, str):
        raise TypeError("parse_euro verwacht een tekst")
    cleaned = re.sub(r"\s+", "", text.replace("€", ""))
    match = _AMOUNT_RE.match(cleaned)
    if not match:
        raise InvalidAmountError(
            f"'{text.strip()}' is geen geldig bedrag. Schrijf bijvoorbeeld 1.234,56 of 12,50 "
            "(maximaal twee cijfers achter de komma)."
        )
    sign, whole, frac = match.groups()
    cents = int(whole.replace(".", "")) * 100 + int((frac or "").ljust(2, "0") or 0)
    return -cents if sign else cents


def format_euro(cents: int) -> str:
    """Format cents as '€ 1.234,56' (negatives '-€ 1,00')."""
    require_cents(cents)
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}€ {euros:,}".replace(",", ".") + f",{rest:02d}"
