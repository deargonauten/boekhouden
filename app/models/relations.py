from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Contact(Base):
    """A klant and/or leverancier. Never deleted; archived via `is_active`."""

    __tablename__ = "contact"
    __table_args__ = (
        CheckConstraint("is_customer OR is_supplier", name="ck_contact_role"),
        CheckConstraint(
            "kvk IS NULL OR (length(kvk) = 8 AND kvk NOT GLOB '*[^0-9]*')",
            name="ck_contact_kvk",
        ),
        CheckConstraint("length(country) = 2", name="ck_contact_country"),
        Index("ix_contact_name_key", "name_key"),
        Index("ix_contact_is_active", "is_active"),
        Index("uq_contact_kvk", "kvk", unique=True, sqlite_where=text("kvk IS NOT NULL")),
        Index(
            "uq_contact_btw_number",
            "btw_number",
            unique=True,
            sqlite_where=text("btw_number IS NOT NULL"),
        ),
        Index("uq_contact_iban", "iban", unique=True, sqlite_where=text("iban IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    name_key: Mapped[str] = mapped_column(String)
    is_customer: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
    is_supplier: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
    kvk: Mapped[str | None] = mapped_column(String)
    btw_number: Mapped[str | None] = mapped_column(String)
    iban: Mapped[str | None] = mapped_column(String)
    address_line: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    country: Mapped[str] = mapped_column(String, server_default=text("'NL'"))
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
