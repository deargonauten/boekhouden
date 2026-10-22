from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BankMatch(Base):
    """One allocation of a bank transaction to an open item (invoice or openstaande post).

    Append-only: never deleted; the only allowed update is setting `reversed_at` once (undo).
    """

    __tablename__ = "bank_match"
    __table_args__ = (
        CheckConstraint("source IN ('purchase_invoice','opening_item','sales_invoice')", name="ck_bank_match_source"),
        CheckConstraint("amount_cents > 0", name="ck_bank_match_amount"),
        Index("ix_bank_match_source", "source", "source_id"),
        Index("ix_bank_match_bank_transaction_id", "bank_transaction_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_transaction_id: Mapped[int] = mapped_column(ForeignKey("bank_transaction.id"))
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    source: Mapped[str] = mapped_column(String)
    source_id: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BankRule(Base):
    """A remembered choice for recurring bank transactions; only ever a suggestion."""

    __tablename__ = "bank_rule"
    __table_args__ = (
        CheckConstraint("direction IN ('af','bij','beide')", name="ck_bank_rule_direction"),
        CheckConstraint(
            "counterparty_iban IS NOT NULL OR description_contains IS NOT NULL",
            name="ck_bank_rule_condition",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    counterparty_iban: Mapped[str | None] = mapped_column(String)
    description_contains: Mapped[str | None] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    vat_code: Mapped[str | None] = mapped_column(ForeignKey("vat_code.code"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    use_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
