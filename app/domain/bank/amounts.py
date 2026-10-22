"""Parse bank amount strings to integer cents without floats."""

import re

from app.domain.bank.types import PARSE_ERROR, BankImportError

# style -> (thousands separator, decimal separator)
_STYLES = {
    "nl": (".", ","),  # 1.234,56
    "en": (",", "."),  # 1,234.56 / 1234.56
    "mt940": ("", ","),  # 1234,56 / 100,
}


def _bad(text: str, why: str) -> BankImportError:
    return BankImportError(PARSE_ERROR, f"'{(text or '').strip()}' is geen geldig bedrag ({why}).")


def parse_amount(text: str, style: str = "nl") -> int:
    """'1.234,56' (nl), '1,234.56' / '1234.56' (en), '1234,56' (mt940) -> signed cents.

    A leading + or - is honoured. More than two decimals is an error (never rounded).
    """
    if style not in _STYLES:
        raise ValueError(f"Onbekende bedragstijl: {style}")
    thousands, decimal = _STYLES[style]
    s = re.sub(r"[\s ]", "", text or "").replace("€", "")
    sign = 1
    if s and s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:]
    if not s:
        raise _bad(text, "leeg")
    whole, _, frac = s.partition(decimal)
    if thousands and re.fullmatch(rf"\d{{1,3}}(?:{re.escape(thousands)}\d{{3}})+", whole):
        whole = whole.replace(thousands, "")
    if not re.fullmatch(r"[0-9]+", whole) or (frac and not re.fullmatch(r"[0-9]+", frac)):
        raise _bad(text, "alleen cijfers en een decimaalteken zijn toegestaan")
    if len(frac) > 2:
        raise _bad(text, "meer dan twee cijfers achter de komma")
    return sign * (int(whole) * 100 + int(frac.ljust(2, "0")))
