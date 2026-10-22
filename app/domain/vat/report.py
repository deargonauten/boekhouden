"""BTW-aangifte report: grondslag and btw per rubriek from the booked journal lines.

STUB (public API); implementation follows.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.domain.vat.rubrieken import PURCHASE_RUBRIEKEN, SALES_RUBRIEKEN

# Account-to-rubriek mapping, by account code (not id).
BTW_ACCOUNT_RUBRIEK: dict[str, str] = {"3100": "1a", "3110": "1b", "3120": "1c", "3140": "1d"}
VERLEGD_PAYABLE = "3130"
INPUT_ACCOUNTS: tuple[str, ...] = ("1400", "1410")

# Rubrieken in the order of the Belastingdienst form, with their side.
RUBRIEK_ORDER: tuple[tuple[str, str], ...] = (
    ("1a", "sales"), ("1b", "sales"), ("1c", "sales"), ("1d", "sales"), ("1e", "sales"),
    ("2a", "purchase"), ("3a", "sales"), ("3b", "sales"), ("3c", "sales"),
    ("4a", "purchase"), ("4b", "purchase"),
)
TOTAL_LABELS: dict[str, str] = {
    "5a": "Verschuldigde btw",
    "5b": PURCHASE_RUBRIEKEN["5b"],
    "5c": "Subtotaal (verschuldigd min voorbelasting)",
    "5g": "Totaal",
}

# direction values of a report
PAY, REFUND, ZERO = "pay", "refund", "zero"


@dataclass(frozen=True)
class RubriekLine:
    rubriek: str
    side: str  # 'sales' | 'purchase'
    label: str
    grondslag_cents: int  # unrounded, for drill-down
    grondslag_whole_cents: int  # rounded toward zero to whole euros, for display/export
    vat_cents: int


@dataclass(frozen=True)
class VatWarning:
    code: str
    message: str
    entry_ids: tuple[int, ...] = ()


@dataclass
class VatReport:
    period_start: date
    period_end: date
    lines: list[RubriekLine]
    totals: dict[str, int]  # '5a', '5b', '5c', '5g'
    warnings: list[VatWarning] = field(default_factory=list)
    direction: str = ZERO


def build_vat_report(session: Session, start: date, end: date, *, today: date | None = None) -> VatReport:
    raise NotImplementedError
