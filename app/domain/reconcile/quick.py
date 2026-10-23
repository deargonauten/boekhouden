"""Snelkeuzes voor een bankmutatie zonder factuur: betaling/teruggave btw-aangifte en privé."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import LedgerError
from app.domain.reconcile.errors import ACCOUNT_REQUIRED, ReconcileError
from app.domain.reconcile.service import _txn
from app.domain.reconcile.types import DirectLine
from app.domain.vat import VatPeriod, kind_for_year, periods_of_year
from app.models import Account

QUICK_PRIVATE = "prive"
QUICK_VAT_RETURN = "btw"
QUICK_KINDS = (QUICK_PRIVATE, QUICK_VAT_RETURN)

PRIVATE_WITHDRAWALS_CODE = "2010"  # geld af
PRIVATE_DEPOSITS_CODE = "2020"  # geld bij
VAT_CURRENT_ACCOUNT_CODE = "3150"
NO_VAT = "GEEN"
YEARS_BACK = 1  # the year of the transaction plus this many earlier ones


@dataclass(frozen=True)
class VatPeriodChoice:
    value: str  # VatPeriod.slug, e.g. '2026-Q3'
    label: str


def _parse_period(value: str) -> VatPeriod:
    year, _, rest = value.strip().partition("-")
    try:
        number = int(rest[1:])
        kind = {"Q": "quarter", "M": "month"}[rest[:1]]
        return VatPeriod(int(year), kind, number)
    except (KeyError, ValueError, IndexError, LedgerError):
        raise ReconcileError(
            ACCOUNT_REQUIRED, "Kies een periode uit de lijst voor de btw-aangifte, of laat de keuze leeg."
        ) from None


def vat_period_choices(session: Session, txn_id: int) -> list[VatPeriodChoice]:
    """Aangifteperiodes to pick from: the year of the transaction (and the year before),
    newest first, in the frequency (kwartaal/maand) that year uses."""
    year = _txn(session, txn_id).booking_date.year
    choices: list[VatPeriodChoice] = []
    for y in range(year, year - YEARS_BACK - 1, -1):
        for period in reversed(periods_of_year(y, kind_for_year(session, y))):
            choices.append(VatPeriodChoice(period.slug, period.label))
    return choices


def _account_id(session: Session, code: str) -> int:
    found = session.scalar(select(Account.id).where(Account.code == code))
    if found is None:
        raise ReconcileError(
            ACCOUNT_REQUIRED,
            f"Rekening {code} ontbreekt in je grootboek, dus deze snelkeuze kan niet worden geboekt. "
            "Kies zelf een rekening bij 'Boeken zonder factuur'.",
        )
    return found


def quick_line(session: Session, txn_id: int, kind: str, period: str | None = None) -> DirectLine:
    """The one direct line for the whole transaction. Privé: 'Privé-opnamen' for money out,
    'Privé-stortingen' for money in. Btw-aangifte: the btw-rekening-courant (betaling or
    teruggaaf), with the chosen period in the omschrijving. Never carries btw."""
    t = _txn(session, txn_id)
    amount = abs(t.amount_cents)
    if kind == QUICK_PRIVATE:
        code = PRIVATE_WITHDRAWALS_CODE if t.amount_cents < 0 else PRIVATE_DEPOSITS_CODE
        text = "Privé-opname" if t.amount_cents < 0 else "Privé-storting"
        return DirectLine(_account_id(session, code), amount, NO_VAT, text)
    if kind == QUICK_VAT_RETURN:
        label = _parse_period(period).label if period and period.strip() else None
        verb = "Btw-aangifte"
        text = f"{verb} {label}" if label else verb
        return DirectLine(_account_id(session, VAT_CURRENT_ACCOUNT_CODE), amount, NO_VAT, text)
    raise ReconcileError(ACCOUNT_REQUIRED, "Kies of dit een btw-aangifte of een privé-boeking is.")
