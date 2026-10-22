"""Parsing of a btw-percentage typed in Dutch notation. Integers only, no floats."""

import re

from app.domain.errors import INVALID_VAT_RATE, LedgerError

RATE_MESSAGE = "Vul een percentage tussen 0 en 99,99 in, bijvoorbeeld 21 of 6,5."
MAX_RATE_BP = 9999

_RATE_RE = re.compile(r"(\d{1,2})(?:[.,](\d{1,2}))?")


def rate_error() -> LedgerError:
    return LedgerError(INVALID_VAT_RATE, RATE_MESSAGE)


def parse_rate_bp(text: str | None) -> int:
    """'21' -> 2100, '6,5' -> 650 (basis points). Rejects anything else."""
    cleaned = (text or "").strip().removesuffix("%").strip()
    m = _RATE_RE.fullmatch(cleaned)
    if m is None:
        raise rate_error()
    whole, frac = m.group(1), (m.group(2) or "").ljust(2, "0")
    return int(whole) * 100 + int(frac)
