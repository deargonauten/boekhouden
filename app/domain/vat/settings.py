"""BTW-aangifte settings: frequency and KOR. STUB (public API); implementation follows."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.domain.vat.periods import VatPeriod

KOR_LIMIT_CENTS = 2_000_000  # information only, never enforced


@dataclass(frozen=True)
class VatSettings:
    frequency: str = "quarter"  # 'quarter' | 'month'
    kor_from: date | None = None
    kor_until: date | None = None


def get_vat_settings(session: Session) -> VatSettings:
    raise NotImplementedError


def save_vat_settings(
    session: Session, frequency: str, kor_from: date | None, kor_until: date | None,
    today: date | None = None,
) -> VatSettings:
    raise NotImplementedError


def is_kor(period: VatPeriod, settings: VatSettings) -> str:
    """'none' | 'partial' | 'full'."""
    raise NotImplementedError
