"""Btw-codes: add, update, (de)activate and look up the rubriek. Flushes, never commits."""

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import (
    DUPLICATE_CODE,
    INVALID_RUBRIEK,
    INVALID_VAT_CODE,
    VAT_CODE_IN_LOCKED_PERIOD,
    VAT_CODE_IS_DEFAULT,
    VAT_CODE_SYSTEM,
    LedgerError,
)
from app.domain.vat.rates import MAX_RATE_BP, parse_rate_bp, rate_error
from app.domain.vat.rubrieken import PURCHASE_RUBRIEKEN, SALES_RUBRIEKEN
from app.models import Account, JournalEntry, JournalLine, Period, VatCode
from app.seed.vat_rubrieken import SEED_VAT_ORDER

_CODE_RE = re.compile(r"[A-Z0-9_]{2,12}")
GEEN = "GEEN"


@dataclass(frozen=True)
class VatCodeRow:
    code: str
    name: str
    rate_bp: int
    sales_rubriek: str | None
    purchase_rubriek: str | None
    is_active: bool
    is_system: bool
    used_count: int
    default_for: list[str]


def _clean_code(code: str | None) -> str:
    code = (code or "").strip().upper()
    if not _CODE_RE.fullmatch(code):
        raise LedgerError(
            INVALID_VAT_CODE,
            "Een btw-code bestaat uit 2 tot 12 hoofdletters, cijfers of liggende streepjes, "
            "bijvoorbeeld KOR of NL_5.",
        )
    return code


def _clean_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name:
        raise LedgerError(INVALID_VAT_CODE, "Geef de btw-code een naam, bijvoorbeeld 'BTW 6%'.")
    return name


def _clean_rubriek(value: str | None, catalogue: dict[str, str]) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if value not in catalogue:
        raise LedgerError(
            INVALID_RUBRIEK,
            f"Rubriek {value} past hier niet. Kies een rubriek uit de lijst of laat het veld leeg.",
        )
    return value


def _get(session: Session, code: str) -> VatCode:
    vat = session.get(VatCode, code)
    if vat is None:
        raise LedgerError(INVALID_VAT_CODE, f"De btw-code {code} bestaat niet. Kies een bestaande btw-code.")
    return vat


def add_vat_code(
    session: Session,
    *,
    code: str,
    name: str,
    rate_percent_text: str | None = None,
    rate_bp: int | None = None,
    sales_rubriek: str | None = None,
    purchase_rubriek: str | None = None,
) -> VatCode:
    code = _clean_code(code)
    if session.get(VatCode, code) is not None:
        raise LedgerError(DUPLICATE_CODE, f"De btw-code {code} bestaat al. Kies een andere code.")
    name = _clean_name(name)
    if rate_percent_text is not None:
        rate_bp = parse_rate_bp(rate_percent_text)
    elif rate_bp is None or isinstance(rate_bp, bool) or not 0 <= rate_bp <= MAX_RATE_BP:
        raise rate_error()
    sales = _clean_rubriek(sales_rubriek, SALES_RUBRIEKEN)
    purchase = _clean_rubriek(purchase_rubriek, PURCHASE_RUBRIEKEN)
    vat = VatCode(
        code=code, name=name, rate_bp=rate_bp, is_active=True, is_system=False,
        sales_rubriek=sales, purchase_rubriek=purchase,
    )
    session.add(vat)
    session.flush()
    return vat


def _used_in_locked_period(session: Session, code: str) -> bool:
    return session.scalar(
        select(func.count())
        .select_from(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Period, Period.id == JournalEntry.period_id)
        .where(JournalLine.vat_code == code, Period.status == "locked")
    ) > 0


def update_vat_code(
    session: Session,
    code: str,
    *,
    name: str,
    sales_rubriek: str | None,
    purchase_rubriek: str | None,
) -> VatCode:
    """Name and rubrieken only; code and rate never change."""
    vat = _get(session, code)
    name = _clean_name(name)
    sales = _clean_rubriek(sales_rubriek, SALES_RUBRIEKEN)
    purchase = _clean_rubriek(purchase_rubriek, PURCHASE_RUBRIEKEN)
    changed = (sales, purchase) != (vat.sales_rubriek, vat.purchase_rubriek)
    if changed and _used_in_locked_period(session, vat.code):
        raise LedgerError(
            VAT_CODE_IN_LOCKED_PERIOD,
            "Deze btw-code is al gebruikt in een vergrendelde periode, dus de rubriek kun je niet "
            "meer wijzigen. Maak een nieuwe btw-code aan voor het nieuwe geval.",
        )
    vat.name = name
    vat.sales_rubriek = sales
    vat.purchase_rubriek = purchase
    session.flush()
    return vat


def _default_accounts(session: Session, code: str) -> list[Account]:
    return list(session.scalars(
        select(Account)
        .where(Account.default_vat_code == code, Account.is_active.is_(True))
        .order_by(Account.code)
    ))


def set_vat_code_active(session: Session, code: str, active: bool) -> VatCode:
    vat = _get(session, code)
    if not active and vat.is_active:
        if vat.code == GEEN:
            raise LedgerError(
                VAT_CODE_SYSTEM,
                "'Geen btw' is nodig voor boekingen zonder btw en kan niet worden uitgezet.",
            )
        accounts = _default_accounts(session, vat.code)
        if accounts:
            listed = ", ".join(f"{a.code} {a.name}" for a in accounts[:3])
            if len(accounts) > 3:
                listed += f" en nog {len(accounts) - 3} andere"
            noun = "rekening" if len(accounts) == 1 else "rekeningen"
            raise LedgerError(
                VAT_CODE_IS_DEFAULT,
                f"Je kunt {vat.name} niet uitzetten: het is nog het standaard btw-tarief van "
                f"{noun} {listed}. Kies eerst bij die rekening een ander tarief.",
            )
    vat.is_active = active
    session.flush()
    return vat


def list_vat_codes_with_usage(session: Session) -> list[VatCodeRow]:
    used = dict(session.execute(
        select(JournalLine.vat_code, func.count())
        .where(JournalLine.vat_code.is_not(None))
        .group_by(JournalLine.vat_code)
    ).all())
    defaults: dict[str, list[str]] = {}
    for acc_code, vat_code in session.execute(
        select(Account.code, Account.default_vat_code)
        .where(Account.default_vat_code.is_not(None))
        .order_by(Account.code)
    ):
        defaults.setdefault(vat_code, []).append(acc_code)
    seed_pos = {c: i for i, c in enumerate(SEED_VAT_ORDER)}
    codes = sorted(
        session.scalars(select(VatCode)),
        key=lambda v: (0, seed_pos[v.code], "") if v.is_system and v.code in seed_pos else (1, 0, v.code),
    )
    return [
        VatCodeRow(
            v.code, v.name, v.rate_bp, v.sales_rubriek, v.purchase_rubriek, bool(v.is_active),
            bool(v.is_system), used.get(v.code, 0), defaults.get(v.code, []),
        )
        for v in codes
    ]


def rubriek_for(session: Session, vat_code: str | None, direction: str) -> str | None:
    """Rubriek of a vat code on the 'sales' or 'purchase' side (hook for the BTW-aangifte)."""
    if direction not in ("sales", "purchase"):
        raise ValueError(f"direction must be 'sales' or 'purchase', not {direction!r}")
    if not vat_code:
        return None
    vat = session.get(VatCode, vat_code)
    if vat is None:
        return None
    return vat.sales_rubriek if direction == "sales" else vat.purchase_rubriek
