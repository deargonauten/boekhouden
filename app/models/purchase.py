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
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PurchaseInvoice(Base):
    """A booked inkoopfactuur (or creditnota): links document, leverancier and boeking.

    Never deleted. A wrong booking is fixed with a stornoboeking; whether an invoice is
    storno'd or paid is derived at read time (`paid_cents` is filled by later features).
    """

    __tablename__ = "purchase_invoice"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_purchase_invoice_document"),
        UniqueConstraint("journal_entry_id", name="uq_purchase_invoice_entry"),
        CheckConstraint("kind IN ('invoice','credit_note')", name="ck_purchase_invoice_kind"),
        CheckConstraint("total_incl_cents > 0", name="ck_purchase_invoice_total"),
        CheckConstraint("paid_cents >= 0", name="ck_purchase_invoice_paid"),
        Index("ix_purchase_invoice_contact_id", "contact_id"),
        Index("ix_purchase_invoice_invoice_date", "invoice_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    invoice_number: Mapped[str] = mapped_column(String)
    invoice_number_key: Mapped[str] = mapped_column(String)  # lower(trim(number)), duplicate guard
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String)
    total_excl_cents: Mapped[int] = mapped_column(Integer)
    total_vat_cents: Mapped[int] = mapped_column(Integer)
    total_incl_cents: Mapped[int] = mapped_column(Integer)
    # Amounts above are euro cents. For a foreign-currency invoice the original total and the
    # koers it was booked at are kept here.
    currency: Mapped[str] = mapped_column(String, server_default=text("'EUR'"))
    exchange_rate_micro: Mapped[int | None] = mapped_column(Integer)
    original_total_incl_cents: Mapped[int | None] = mapped_column(Integer)
    paid_cents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class SupplierDefault(Base):
    """Learned choice per leverancier + rekening (leerfunctie); only ever a suggestion."""

    __tablename__ = "supplier_default"
    __table_args__ = (
        UniqueConstraint("contact_id", "account_id", name="uq_supplier_default_contact_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    vat_code: Mapped[str | None] = mapped_column(ForeignKey("vat_code.code"))
    use_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_used_at: Mapped[datetime] = mapped_column(DateTime)
