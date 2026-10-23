from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VatSetting(Base):
    """The ondernemer's btw-aangifte settings. Single row (id = 1), created on first save."""

    __tablename__ = "vat_setting"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_vat_setting_single_row"),
        CheckConstraint("frequency IN ('quarter','month')", name="ck_vat_setting_frequency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    frequency: Mapped[str] = mapped_column(String)
    kor_from: Mapped[date | None] = mapped_column(Date)
    kor_until: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class VatReturn(Base):
    """A filed (ingediende) btw-aangifte with its frozen snapshot. Only filed returns are stored.

    Append-only: database triggers refuse every DELETE and every UPDATE except setting
    `reference` once (from NULL to a value).
    """

    __tablename__ = "vat_return"
    __table_args__ = (
        UniqueConstraint("year", "kind", "number", name="uq_vat_return_period"),
        CheckConstraint("kind IN ('quarter','month')", name="ck_vat_return_kind"),
        CheckConstraint(
            "(kind = 'quarter' AND number BETWEEN 1 AND 4) OR (kind = 'month' AND number BETWEEN 1 AND 12)",
            name="ck_vat_return_number",
        ),
        CheckConstraint("status = 'ingediend'", name="ck_vat_return_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    number: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String)
    filed_on: Mapped[date] = mapped_column(Date)
    filed_at: Mapped[datetime] = mapped_column(DateTime)
    reference: Mapped[str | None] = mapped_column(String)
    snapshot_json: Mapped[str] = mapped_column(Text)
    total_cents: Mapped[int] = mapped_column(Integer)


class VatEntryContact(Base):
    """Couples a klant to a booked entry for the ICP-opgaaf (the ledger itself stays untouched)."""

    __tablename__ = "vat_entry_contact"

    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"), primary_key=True, autoincrement=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime)
