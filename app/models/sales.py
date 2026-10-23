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


class SalesNumberCounter(Base):
    """Last used invoice number per year (gapless; advanced only inside the finalize transaction)."""

    __tablename__ = "sales_number_counter"
    __table_args__ = (CheckConstraint("last_number >= 0", name="ck_sales_number_counter_last"),)

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_number: Mapped[int] = mapped_column(Integer)


class SalesInvoice(Base):
    """A verkoopfactuur or creditnota: concept (editable, no number) or definitief (immutable).

    Database triggers refuse every change to a definitief document except `paid_cents` and
    `updated_at`. Never deleted once definitief; corrections are creditnota's.
    """

    __tablename__ = "sales_invoice"
    __table_args__ = (
        CheckConstraint("kind IN ('invoice','credit_note')", name="ck_sales_invoice_kind"),
        CheckConstraint("status IN ('concept','definitief')", name="ck_sales_invoice_status"),
        CheckConstraint(
            "credited_invoice_id IS NULL OR kind = 'credit_note'", name="ck_sales_invoice_credited"
        ),
        CheckConstraint(
            "status = 'concept' OR (number IS NOT NULL AND journal_entry_id IS NOT NULL "
            "AND pdf_sha256 IS NOT NULL AND seller_name IS NOT NULL AND buyer_name IS NOT NULL)",
            name="ck_sales_invoice_definitief",
        ),
        CheckConstraint(
            "total_excl_cents >= 0 AND total_vat_cents >= 0 AND total_incl_cents >= 0",
            name="ck_sales_invoice_totals",
        ),
        CheckConstraint("paid_cents >= 0", name="ck_sales_invoice_paid"),
        CheckConstraint("payment_term_days >= 0", name="ck_sales_invoice_term"),
        UniqueConstraint("journal_entry_id", name="uq_sales_invoice_entry"),
        UniqueConstraint("number_year", "number_seq", name="uq_sales_invoice_number_seq"),
        Index("uq_sales_invoice_number", "number", unique=True, sqlite_where=text("number IS NOT NULL")),
        Index("ix_sales_invoice_contact_id", "contact_id"),
        Index("ix_sales_invoice_invoice_date", "invoice_date"),
        Index("ix_sales_invoice_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String, server_default=text("'invoice'"))
    status: Mapped[str] = mapped_column(String, server_default=text("'concept'"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    credited_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("sales_invoice.id"))
    number: Mapped[str | None] = mapped_column(String)
    number_year: Mapped[int | None] = mapped_column(Integer)
    number_seq: Mapped[int | None] = mapped_column(Integer)
    invoice_date: Mapped[date] = mapped_column(Date)
    service_date: Mapped[date | None] = mapped_column(Date)
    payment_term_days: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    due_date_manual: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
    reference: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)

    # Snapshot of own and customer details, filled at finalize.
    seller_name: Mapped[str | None] = mapped_column(String)
    seller_address_line: Mapped[str | None] = mapped_column(String)
    seller_postal_code: Mapped[str | None] = mapped_column(String)
    seller_city: Mapped[str | None] = mapped_column(String)
    seller_country: Mapped[str | None] = mapped_column(String)
    seller_kvk: Mapped[str | None] = mapped_column(String)
    seller_btw_id: Mapped[str | None] = mapped_column(String)
    seller_iban: Mapped[str | None] = mapped_column(String)
    seller_email: Mapped[str | None] = mapped_column(String)
    seller_phone: Mapped[str | None] = mapped_column(String)
    buyer_name: Mapped[str | None] = mapped_column(String)
    buyer_address_line: Mapped[str | None] = mapped_column(String)
    buyer_postal_code: Mapped[str | None] = mapped_column(String)
    buyer_city: Mapped[str | None] = mapped_column(String)
    buyer_country: Mapped[str | None] = mapped_column(String)
    buyer_btw_number: Mapped[str | None] = mapped_column(String)
    buyer_kvk: Mapped[str | None] = mapped_column(String)

    total_excl_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_vat_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_incl_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    paid_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"))
    pdf_sha256: Mapped[str | None] = mapped_column(String)
    pdf_path: Mapped[str | None] = mapped_column(String)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    lines: Mapped[list["SalesInvoiceLine"]] = relationship(
        back_populates="invoice", order_by="SalesInvoiceLine.position", cascade="all, delete-orphan"
    )
    vat_rows: Mapped[list["SalesInvoiceVat"]] = relationship(order_by="SalesInvoiceVat.vat_code")


class SalesInvoiceLine(Base):
    __tablename__ = "sales_invoice_line"
    __table_args__ = (
        CheckConstraint("quantity_milli > 0", name="ck_sales_invoice_line_quantity"),
        CheckConstraint("unit_price_cents >= 0", name="ck_sales_invoice_line_price"),
        Index("ix_sales_invoice_line_invoice_id", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoice.id"))
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String, server_default=text("''"))
    quantity_milli: Mapped[int] = mapped_column(Integer)  # thousandths: 1,5 = 1500
    unit: Mapped[str] = mapped_column(String, server_default=text("'stuk'"))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    vat_code: Mapped[str] = mapped_column(ForeignKey("vat_code.code"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    line_excl_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    original_line_id: Mapped[int | None] = mapped_column(ForeignKey("sales_invoice_line.id"))

    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


class SalesInvoiceVat(Base):
    """Grondslag and BTW per rate of a finalized document (written at finalize)."""

    __tablename__ = "sales_invoice_vat"

    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoice.id"), primary_key=True)
    vat_code: Mapped[str] = mapped_column(ForeignKey("vat_code.code"), primary_key=True)
    rate_bp: Mapped[int] = mapped_column(Integer)
    base_cents: Mapped[int] = mapped_column(Integer)
    vat_cents: Mapped[int] = mapped_column(Integer)


class SalesCreditApplication(Base):
    """Verrekening: how much of a creditnota was set off against an invoice. Append-only."""

    __tablename__ = "sales_credit_application"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_sales_credit_application_amount"),
        Index("ix_sales_credit_application_invoice_id", "invoice_id"),
        Index("ix_sales_credit_application_credit_note_id", "credit_note_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("sales_invoice.id"))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoice.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class SalesReminder(Base):
    """A betalingsherinnering that was created for an invoice. Append-only."""

    __tablename__ = "sales_reminder"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 3", name="ck_sales_reminder_level"),
        Index("ix_sales_reminder_invoice_id", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoice.id"))
    level: Mapped[int] = mapped_column(Integer)
    reminder_date: Mapped[date] = mapped_column(Date)
    new_due_date: Mapped[date] = mapped_column(Date)
    open_cents: Mapped[int] = mapped_column(Integer)
    body_text: Mapped[str] = mapped_column(String)
    pdf_sha256: Mapped[str | None] = mapped_column(String)
    pdf_path: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class InvoiceNumbering(Base):
    """How verkoopfactuur numbers look and run. Single row (id = 1); without a row the old default
    applies (`YYYY-NNNN`, a new series every year)."""

    __tablename__ = "invoice_numbering"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_invoice_numbering_single_row"),
        CheckConstraint("separator IN ('-','.','/','')", name="ck_invoice_numbering_separator"),
        CheckConstraint("digits BETWEEN 1 AND 8", name="ck_invoice_numbering_digits"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    separator: Mapped[str] = mapped_column(String, server_default=text("'-'"))
    digits: Mapped[int] = mapped_column(Integer, server_default=text("4"))
    continuous: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
