from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OpeningItem(Base):
    """An openstaande post (unpaid invoice) entered with the beginbalans.

    Append-only: never deleted, only `paid_cents` may change (later bank reconciliation).
    Correcting the beginbalans reverses its entry; the old items are then derived as
    'vervangen' at read time.
    """

    __tablename__ = "opening_item"
    __table_args__ = (
        CheckConstraint("side IN ('debiteur','crediteur')", name="ck_opening_item_side"),
        CheckConstraint("amount_cents > 0", name="ck_opening_item_amount"),
        CheckConstraint(
            "paid_cents >= 0 AND paid_cents <= amount_cents", name="ck_opening_item_paid"
        ),
        Index("ix_opening_item_contact_id", "contact_id"),
        Index("ix_opening_item_journal_entry_id", "journal_entry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("fiscal_year.id"))
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    side: Mapped[str] = mapped_column(String)
    invoice_number: Mapped[str] = mapped_column(String)
    invoice_number_key: Mapped[str] = mapped_column(String)  # lower(trim(number))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer)
    paid_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
