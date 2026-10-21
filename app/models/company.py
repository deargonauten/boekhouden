from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CompanyProfile(Base):
    """The ondernemer's own bedrijfsgegevens. Single row (id = 1), created on first save."""

    __tablename__ = "company_profile"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_company_profile_single_row"),
        CheckConstraint(
            "legal_form IN ('eenmanszaak','vof')", name="ck_company_profile_legal_form"
        ),
        CheckConstraint("length(country) = 2", name="ck_company_profile_country"),
        CheckConstraint(
            "kvk IS NULL OR (length(kvk) = 8 AND kvk NOT GLOB '*[^0-9]*')",
            name="ck_company_profile_kvk",
        ),
        CheckConstraint(
            "btw_id IS NULL OR (length(btw_id) = 14 AND btw_id GLOB "
            "'NL[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]B[0-9][0-9]')",
            name="ck_company_profile_btw_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String)
    trade_name: Mapped[str | None] = mapped_column(String)
    legal_form: Mapped[str] = mapped_column(String, server_default=text("'eenmanszaak'"))
    address_line: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    country: Mapped[str] = mapped_column(String, server_default=text("'NL'"))
    kvk: Mapped[str | None] = mapped_column(String)
    btw_id: Mapped[str | None] = mapped_column(String)
    iban: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
