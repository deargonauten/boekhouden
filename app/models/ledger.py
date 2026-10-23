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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class VatCode(Base):
    __tablename__ = "vat_code"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    rate_bp: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    sales_rubriek: Mapped[str | None] = mapped_column(String)
    purchase_rubriek: Mapped[str | None] = mapped_column(String)
    is_system: Mapped[bool] = mapped_column(
        Boolean, server_default=text("0"), nullable=False
    )


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint(
            "length(code) = 4 AND code NOT GLOB '*[^0-9]*'", name="ck_account_code"
        ),
        CheckConstraint(
            "type IN ('asset','liability','equity','revenue','expense')",
            name="ck_account_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    rgs_code: Mapped[str | None] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    is_postable: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
    default_vat_code: Mapped[str | None] = mapped_column(ForeignKey("vat_code.code"))
    selectable_purchase: Mapped[bool] = mapped_column(
        Boolean, server_default=text("0"), nullable=False
    )
    selectable_sales: Mapped[bool] = mapped_column(
        Boolean, server_default=text("0"), nullable=False
    )
    selectable_bank: Mapped[bool] = mapped_column(
        Boolean, server_default=text("0"), nullable=False
    )


class Journal(Base):
    __tablename__ = "journal"
    __table_args__ = (
        CheckConstraint(
            "type IN ('verkoop','inkoop','bank','kas','memoriaal')",
            name="ck_journal_type",
        ),
        CheckConstraint(
            "type NOT IN ('bank','kas') OR account_id IS NOT NULL",
            name="ck_journal_account",
        ),
        CheckConstraint(
            "length(code) <= 6 AND code = upper(code)", name="ck_journal_code"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class FiscalYear(Base):
    __tablename__ = "fiscal_year"
    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="ck_fiscal_year_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, server_default=text("'open'"))

    periods: Mapped[list["Period"]] = relationship(
        back_populates="fiscal_year", order_by="Period.number"
    )


class Period(Base):
    __tablename__ = "period"
    __table_args__ = (
        UniqueConstraint("fiscal_year_id", "number", name="uq_period_year_number"),
        CheckConstraint("number BETWEEN 1 AND 12", name="ck_period_number"),
        CheckConstraint("status IN ('open','locked')", name="ck_period_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("fiscal_year.id"))
    number: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, server_default=text("'open'"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="periods")


class EntrySequence(Base):
    __tablename__ = "entry_sequence"

    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id"), primary_key=True)
    fiscal_year_id: Mapped[int] = mapped_column(
        ForeignKey("fiscal_year.id"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class JournalEntry(Base):
    __tablename__ = "journal_entry"
    __table_args__ = (
        CheckConstraint("kind IN ('normal','opening','storno')", name="ck_entry_kind"),
        CheckConstraint(
            "(kind = 'storno') = (reverses_entry_id IS NOT NULL)", name="ck_entry_storno"
        ),
        Index("ix_journal_entry_booking_date", "booking_date"),
        Index("ix_journal_entry_journal_id_id", "journal_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("period.id"))
    entry_number: Mapped[str] = mapped_column(String, unique=True)
    booking_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String)
    reference: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, server_default=text("'normal'"))
    reverses_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entry.id"), unique=True
    )
    source_type: Mapped[str | None] = mapped_column(String)
    source_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP")
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", order_by="JournalLine.line_no"
    )


class JournalLine(Base):
    __tablename__ = "journal_line"
    __table_args__ = (
        UniqueConstraint("entry_id", "line_no", name="uq_journal_line_entry_line"),
        CheckConstraint(
            "debit_cents >= 0 AND credit_cents >= 0 "
            "AND ((debit_cents > 0) <> (credit_cents > 0))",
            name="ck_line_amounts",
        ),
        Index("ix_journal_line_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    debit_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    credit_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(String)
    vat_code: Mapped[str | None] = mapped_column(ForeignKey("vat_code.code"))

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")


class LockedBookingOverride(Base):
    """Single-row flag, set only while one explicitly confirmed posting into a vergrendelde periode runs."""

    __tablename__ = "locked_booking_override"
    __table_args__ = (CheckConstraint("id = 1", name="ck_locked_booking_override_single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("0"), nullable=False)
