from datetime import date, datetime

from sqlalchemy import (
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


class InvoiceExtraction(Base):
    """What was read from a document, plus the owner's corrections. Working data, not a booking."""

    __tablename__ = "invoice_extraction"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_invoice_extraction_document"),
        CheckConstraint("status IN ('ok','failed')", name="ck_invoice_extraction_status"),
        Index("ix_invoice_extraction_contact_id", "contact_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"))
    status: Mapped[str] = mapped_column(String)
    extractor: Mapped[str] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(String)
    raw_json: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str | None] = mapped_column(String)
    supplier_name: Mapped[str | None] = mapped_column(String)
    supplier_kvk: Mapped[str | None] = mapped_column(String)
    supplier_btw_number: Mapped[str | None] = mapped_column(String)
    supplier_iban: Mapped[str | None] = mapped_column(String)
    supplier_address_line: Mapped[str | None] = mapped_column(String)
    supplier_postal_code: Mapped[str | None] = mapped_column(String)
    supplier_city: Mapped[str | None] = mapped_column(String)
    supplier_country: Mapped[str | None] = mapped_column(String)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id"))
    invoice_number: Mapped[str | None] = mapped_column(String)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String, server_default=text("'EUR'"))
    exchange_rate_micro: Mapped[int | None] = mapped_column(Integer)  # foreign units per EUR x 1e6
    shifted_vat_rate_bp: Mapped[int | None] = mapped_column(Integer)  # Dutch rate for btw-verlegd lines
    total_excl_cents: Mapped[int | None] = mapped_column(Integer)
    total_vat_cents: Mapped[int | None] = mapped_column(Integer)
    total_incl_cents: Mapped[int | None] = mapped_column(Integer)
    flags_json: Mapped[str] = mapped_column(String, server_default=text("'[]'"))
    notes: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    lines: Mapped[list["InvoiceExtractionLine"]] = relationship(
        order_by="InvoiceExtractionLine.position", viewonly=True
    )


class InvoiceExtractionLine(Base):
    """One invoice line of an extraction; replaced as a whole when the review is saved."""

    __tablename__ = "invoice_extraction_line"
    __table_args__ = (
        UniqueConstraint("extraction_id", "position", name="uq_invoice_extraction_line_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("invoice_extraction.id"))
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String)
    amount_excl_cents: Mapped[int | None] = mapped_column(Integer)
    vat_amount_cents: Mapped[int | None] = mapped_column(Integer)
    vat_code: Mapped[str | None] = mapped_column(ForeignKey("vat_code.code"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    flags_json: Mapped[str] = mapped_column(String, server_default=text("'[]'"))
    source_text: Mapped[str | None] = mapped_column(String)  # passage in the document, for highlighting
