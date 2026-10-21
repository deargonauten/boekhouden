"""company profile: company_profile (single row)

Revision ID: 0006_company_profile
Revises: 0005_invoice_extraction
Create Date: 2026-10-21

This migration must not import app.models. One row at most (id = 1).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_company_profile"
down_revision: Union[str, None] = "0005_invoice_extraction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("legal_name", sa.String(), nullable=False),
        sa.Column("trade_name", sa.String(), nullable=True),
        sa.Column(
            "legal_form", sa.String(), nullable=False, server_default=sa.text("'eenmanszaak'")
        ),
        sa.Column("address_line", sa.String(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=False, server_default=sa.text("'NL'")),
        sa.Column("kvk", sa.String(), nullable=True),
        sa.Column("btw_id", sa.String(), nullable=True),
        sa.Column("iban", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_company_profile_single_row"),
        sa.CheckConstraint(
            "legal_form IN ('eenmanszaak','vof')", name="ck_company_profile_legal_form"
        ),
        sa.CheckConstraint("length(country) = 2", name="ck_company_profile_country"),
        sa.CheckConstraint(
            "kvk IS NULL OR (length(kvk) = 8 AND kvk NOT GLOB '*[^0-9]*')",
            name="ck_company_profile_kvk",
        ),
        sa.CheckConstraint(
            "btw_id IS NULL OR (length(btw_id) = 14 AND btw_id GLOB "
            "'NL[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]B[0-9][0-9]')",
            name="ck_company_profile_btw_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("company_profile")
