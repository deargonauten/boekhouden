"""Leerfunctie: remember the rekening + btw-code chosen per leverancier.

Only ever a suggestion; the owner confirms on the review/preview screen. Functions
flush but never commit.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.purchase.booking import BookingLineInput
from app.models import Account, InvoiceExtraction, SupplierDefault, VatCode


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class SupplierSuggestion:
    contact_id: int
    account_id: int
    account_code: str
    account_name: str
    vat_code: str | None
    use_count: int

    @property
    def hint(self) -> str:
        return f"Vorige keer koos je {self.account_code} {self.account_name} voor deze leverancier."


def record_booking(session: Session, contact_id: int, lines: Iterable[BookingLineInput]) -> None:
    """Count each booked line's rekening for this leverancier; its btw-code becomes the latest choice."""
    now = _now()
    for line in lines:
        if line.account_id is None:
            continue
        row = session.scalar(
            select(SupplierDefault).where(
                SupplierDefault.contact_id == contact_id, SupplierDefault.account_id == line.account_id
            )
        )
        if row is None:
            session.add(
                SupplierDefault(
                    contact_id=contact_id,
                    account_id=line.account_id,
                    vat_code=line.vat_code,
                    use_count=1,
                    last_used_at=now,
                )
            )
        else:
            row.use_count += 1
            row.vat_code = line.vat_code
            row.last_used_at = now
        session.flush()


def suggest_for_contact(session: Session, contact_id: int | None) -> SupplierSuggestion | None:
    """Most used (then most recent) active, postable rekening for this leverancier, or None."""
    if contact_id is None:
        return None
    rows = session.execute(
        select(SupplierDefault, Account)
        .join(Account, Account.id == SupplierDefault.account_id)
        .where(
            SupplierDefault.contact_id == contact_id,
            Account.is_active.is_(True),
            Account.is_postable.is_(True),
        )
        .order_by(
            SupplierDefault.use_count.desc(),
            SupplierDefault.last_used_at.desc(),
            SupplierDefault.id.desc(),
        )
        .limit(1)
    ).first()
    if rows is None:
        return None
    default, account = rows
    return SupplierSuggestion(
        contact_id=contact_id,
        account_id=account.id,
        account_code=account.code,
        account_name=account.name,
        vat_code=_active_vat(session, default.vat_code) or _active_vat(session, account.default_vat_code),
        use_count=default.use_count,
    )


def _active_vat(session: Session, code: str | None) -> str | None:
    if not code:
        return None
    vat = session.get(VatCode, code)
    return code if vat is not None and vat.is_active else None


def apply_to_lines(
    session: Session,
    extraction: InvoiceExtraction,
    *,
    inferred_vat_positions: Collection[int] = (),
) -> SupplierSuggestion | None:
    """Fill lines without a rekening from the leverancier's history.

    Such a line gets the learned rekening; its btw-code only when it has none or when
    the code was only inferred from the amounts (`inferred_vat_positions`). Lines that
    already have a rekening are left alone (the screen shows `hint` next to them).
    Returns the suggestion used, or None when the leverancier has no history.
    """
    suggestion = suggest_for_contact(session, extraction.contact_id)
    if suggestion is None:
        return None
    changed = False
    for line in extraction.lines:
        if line.account_id is not None:
            continue
        line.account_id = suggestion.account_id
        if suggestion.vat_code and (not line.vat_code or line.position in inferred_vat_positions):
            line.vat_code = suggestion.vat_code
        changed = True
    if changed:
        session.flush()
    return suggestion
