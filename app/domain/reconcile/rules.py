"""Matching rules ('Onthoud dit voor volgende keer'): pure matching plus the small DB service.

Rules are only ever suggestions. They are never deleted (a rule used for a booking stays
traceable); they can be switched off and on again.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.bank.iban import normalize_iban
from app.domain.reconcile.errors import RULE_INVALID, RULE_NOT_FOUND, ReconcileError
from app.domain.reconcile.types import RuleView, TxnView
from app.models import Account, BankRule, Contact, VatCode

DIRECTIONS = ("af", "bij", "beide")
DIRECTION_LABELS = {"af": "Bedrag af", "bij": "Bedrag bij", "beide": "Af en bij"}
NEEDLE_MIN_LENGTH = 3


def normalize_text(value: str | None) -> str:
    """Lower case, accents removed, letters and digits only ('F-2026/001' -> 'f2026001')."""
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", "", text)


# --- pure ----------------------------------------------------------------------------------------
def rule_matches(rule: RuleView, txn: TxnView) -> bool:
    """IBAN equal and/or description contains the needle (both when both are set), plus direction."""
    if rule.direction != "beide" and rule.direction != txn.direction:
        return False
    if not rule.counterparty_iban and not rule.description_contains:
        return False
    if rule.counterparty_iban:
        if normalize_iban(txn.counterparty_iban) != normalize_iban(rule.counterparty_iban):
            return False
    if rule.description_contains:
        needle = normalize_text(rule.description_contains)
        if not needle or needle not in normalize_text(txn.description):
            return False
    return True


def rule_specificity(rule: RuleView) -> int:
    """3 = IBAN + text, 2 = IBAN only, 1 = text only."""
    return (2 if rule.counterparty_iban else 0) + (1 if rule.description_contains else 0)


def sort_rules(rules: list[RuleView]) -> list[RuleView]:
    """Most specific first; ties by how often the rule was used, then oldest first."""
    return sorted(rules, key=lambda r: (-rule_specificity(r), -r.use_count, r.id))


# --- DB --------------------------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_view(rule: BankRule) -> RuleView:
    return RuleView(
        id=rule.id,
        name=rule.name,
        counterparty_iban=rule.counterparty_iban,
        description_contains=rule.description_contains,
        direction=rule.direction,
        account_id=rule.account_id,
        vat_code=rule.vat_code,
        contact_id=rule.contact_id,
        use_count=rule.use_count,
    )


def active_rule_views(session: Session) -> list[RuleView]:
    rows = session.scalars(select(BankRule).where(BankRule.is_active.is_(True)).order_by(BankRule.id))
    return [to_view(r) for r in rows]


def create_rule(
    session: Session,
    *,
    name: str,
    counterparty_iban: str | None,
    description_contains: str | None,
    direction: str,
    account_id: int,
    vat_code: str | None = None,
    contact_id: int | None = None,
) -> BankRule:
    """Remember a choice. An identical active rule is reused instead of duplicated."""
    iban = normalize_iban(counterparty_iban) or None
    needle = " ".join((description_contains or "").split()) or None
    if needle is not None and len(normalize_text(needle)) < NEEDLE_MIN_LENGTH:
        raise ReconcileError(
            RULE_INVALID,
            f"De tekst om op te letten is te kort ({NEEDLE_MIN_LENGTH} tekens of meer). "
            "Vul een langere tekst in of laat hem leeg.",
        )
    if iban is None and needle is None:
        raise ReconcileError(
            RULE_INVALID,
            "Om dit te onthouden is een IBAN of een stukje tekst uit de omschrijving nodig. "
            "Deze mutatie heeft geen IBAN; vul een stukje tekst in.",
        )
    if direction not in DIRECTIONS:
        raise ReconcileError(RULE_INVALID, "Kies of de regel geldt voor een bedrag af, bij of beide.")
    if session.get(Account, account_id) is None:
        raise ReconcileError(RULE_INVALID, "Kies een rekening voor deze regel.")
    if vat_code is not None and session.get(VatCode, vat_code) is None:
        raise ReconcileError(RULE_INVALID, "Deze btw-code is onbekend. Kies een andere uit de lijst.")

    existing = session.scalar(
        select(BankRule).where(
            BankRule.is_active.is_(True),
            BankRule.counterparty_iban.is_(iban) if iban is None else BankRule.counterparty_iban == iban,
            BankRule.direction == direction,
            BankRule.account_id == account_id,
            BankRule.vat_code.is_(vat_code) if vat_code is None else BankRule.vat_code == vat_code,
        )
    )
    if existing is not None and normalize_text(existing.description_contains) == normalize_text(needle):
        return existing

    rule = BankRule(
        name=(name or "").strip()[:120] or (needle or iban or "Onthouden keuze"),
        counterparty_iban=iban,
        description_contains=needle,
        direction=direction,
        account_id=account_id,
        vat_code=vat_code,
        contact_id=contact_id,
        is_active=True,
        use_count=0,
        created_at=_now(),
    )
    session.add(rule)
    session.flush()
    return rule


def set_rule_active(session: Session, rule_id: int, active: bool) -> BankRule:
    rule = session.get(BankRule, rule_id)
    if rule is None:
        raise ReconcileError(RULE_NOT_FOUND, "Deze regel bestaat niet meer.")
    rule.is_active = active
    session.flush()
    return rule


def increment_use(session: Session, rule_id: int) -> None:
    session.execute(update(BankRule).where(BankRule.id == rule_id).values(use_count=BankRule.use_count + 1))


@dataclass(frozen=True)
class RuleRow:
    id: int
    name: str
    counterparty_iban: str | None
    description_contains: str | None
    direction: str
    direction_label: str
    account_id: int
    account_code: str
    account_name: str
    vat_code: str | None
    contact_id: int | None
    contact_name: str | None
    is_active: bool
    use_count: int
    created_at: datetime

    @property
    def condition_text(self) -> str:
        """'IBAN NL.. en omschrijving bevat "abonnement"' in plain Dutch."""
        parts = []
        if self.counterparty_iban:
            parts.append(f"IBAN {self.counterparty_iban}")
        if self.description_contains:
            parts.append(f'omschrijving bevat "{self.description_contains}"')
        return " en ".join(parts)


def list_rules(session: Session, *, include_inactive: bool = True) -> list[RuleRow]:
    """Active rules first, then by most used."""
    stmt = (
        select(BankRule, Account.code, Account.name, Contact.name)
        .join(Account, Account.id == BankRule.account_id)
        .outerjoin(Contact, Contact.id == BankRule.contact_id)
        .order_by(BankRule.is_active.desc(), BankRule.use_count.desc(), BankRule.id)
    )
    if not include_inactive:
        stmt = stmt.where(BankRule.is_active.is_(True))
    return [
        RuleRow(
            id=r.id, name=r.name, counterparty_iban=r.counterparty_iban,
            description_contains=r.description_contains, direction=r.direction,
            direction_label=DIRECTION_LABELS[r.direction], account_id=r.account_id,
            account_code=code, account_name=acc_name, vat_code=r.vat_code,
            contact_id=r.contact_id, contact_name=contact_name, is_active=bool(r.is_active),
            use_count=r.use_count, created_at=r.created_at,
        )
        for r, code, acc_name, contact_name in session.execute(stmt).all()
    ]
