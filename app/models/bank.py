from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BankAccount(Base):
    """A bankrekening of the owner, linked to one grootboekrekening and a bank dagboek."""

    __tablename__ = "bank_account"
    __table_args__ = (
        CheckConstraint(
            "bank IS NULL OR bank IN ('ing','rabobank','abn_amro','bunq','overig')",
            name="ck_bank_account_bank",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    iban: Mapped[str] = mapped_column(String, unique=True)  # normalised
    bank: Mapped[str | None] = mapped_column(String)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), unique=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class BankImportBatch(Base):
    """One uploaded statement file. `voorbeeld` until confirmed, then `afgerond`."""

    __tablename__ = "bank_import_batch"
    __table_args__ = (
        CheckConstraint("status IN ('voorbeeld','afgerond')", name="ck_bank_batch_status"),
        CheckConstraint(
            "detected_format IN ('camt053','mt940','csv')", name="ck_bank_batch_format"
        ),
        Index("ix_bank_batch_account_sha", "bank_account_id", "sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"))
    status: Mapped[str] = mapped_column(String)
    original_filename: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    ext: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    detected_format: Mapped[str] = mapped_column(String)
    detected_bank: Mapped[str | None] = mapped_column(String)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    new_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    maybe_duplicate_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BankTransaction(Base):
    """A raw bank transaction. Append-only: only `status`/`journal_entry_id` may change later."""

    __tablename__ = "bank_transaction"
    __table_args__ = (
        UniqueConstraint(
            "bank_account_id", "dedupe_key", "occurrence", name="uq_bank_transaction_dedupe"
        ),
        CheckConstraint("amount_cents <> 0", name="ck_bank_transaction_amount"),
        CheckConstraint("currency = 'EUR'", name="ck_bank_transaction_currency"),
        CheckConstraint(
            "status IN ('nieuw','geboekt','genegeerd')", name="ck_bank_transaction_status"
        ),
        Index("ix_bank_transaction_account_date", "bank_account_id", "booking_date"),
        Index(
            "ix_bank_transaction_account_date_amount",
            "bank_account_id",
            "booking_date",
            "amount_cents",
        ),
        Index("ix_bank_transaction_batch", "import_batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"))
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("bank_import_batch.id"))
    booking_date: Mapped[date] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String, server_default=text("'EUR'"))
    counterparty_name: Mapped[str | None] = mapped_column(String)
    counterparty_iban: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, server_default=text("''"))
    end_to_end_id: Mapped[str | None] = mapped_column(String)
    bank_reference: Mapped[str | None] = mapped_column(String)
    balance_after_cents: Mapped[int | None] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String)
    occurrence: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    raw: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, server_default=text("'nieuw'"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
