"""Resolving what the extractor suggested against what really exists.

Pure functions, integer arithmetic only. An unusable suggestion is cleared
(None) here; `validation.assess` turns that into a "Controleer dit" flag.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.domain.extraction.types import ExtractedLine

# A BTW amount may differ this many cents from the computed one (rounding per line).
VAT_TOLERANCE_CENTS = 2
# Rates a missing/unknown BTW code is inferred from: (code, rate in basis points).
_INFERABLE = (("NL_21", 2100), ("NL_9", 900))


@dataclass(frozen=True)
class AccountRef:
    """What we need to know about a grootboekrekening to judge a suggestion."""

    code: str
    type: str
    is_postable: bool = True
    is_active: bool = True
    name: str = ""


def half_up_vat(excl_cents: int, rate_bp: int) -> int:
    """VAT over `excl_cents` at `rate_bp` (basis points), rounded half up, integers only."""
    num = excl_cents * rate_bp
    return (2 * num + 10000) // 20000


def resolve_account_code(code: str | None, accounts: Iterable[AccountRef]) -> str | None:
    """`code` if it is an active, postable expense account, else None."""
    if not code:
        return None
    wanted = code.strip()
    for a in accounts:
        if a.code == wanted and a.is_active and a.is_postable and a.type == "expense":
            return a.code
    return None


def infer_vat_code(
    amount_excl_cents: int | None,
    vat_amount_cents: int | None,
    vat_rates: Mapping[str, int],
) -> str | None:
    """BTW code (21%, 9%, 0%) that fits the printed amounts, or None."""
    if amount_excl_cents is None or vat_amount_cents is None:
        return None
    if vat_amount_cents == 0:
        return "NL_0" if "NL_0" in vat_rates else None
    best: tuple[int, str] | None = None
    for code, rate_bp in _INFERABLE:
        if code not in vat_rates:
            continue
        deviation = abs(vat_amount_cents - half_up_vat(amount_excl_cents, rate_bp))
        if deviation <= VAT_TOLERANCE_CENTS and (best is None or deviation < best[0]):
            best = (deviation, code)
    return best[1] if best else None


def resolve_vat_code_for_account(
    account_code: str | None,
    default_vat_by_account: Mapping[str, str | None],
    vat_rates: Mapping[str, int],
) -> str | None:
    """The account's standaard btw-code, only when it is an active code (else None)."""
    if not account_code:
        return None
    default = default_vat_by_account.get(account_code)
    return default if default and default in vat_rates else None


def resolve_vat_code(
    line: ExtractedLine, vat_rates: Mapping[str, int]
) -> tuple[str | None, bool]:
    """(code, inferred): the line's own code when active, else one inferred from amounts."""
    if line.vat_code and line.vat_code in vat_rates:
        return line.vat_code, False
    inferred = infer_vat_code(line.amount_excl_cents, line.vat_amount_cents, vat_rates)
    return inferred, inferred is not None
