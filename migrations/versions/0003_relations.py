"""relations: contact table (klanten en leveranciers)

Revision ID: 0003_relations
Revises: 0002_core_ledger
Create Date: 2026-10-21

This migration must not import app.models. The contact table has no triggers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_relations"
down_revision: Union[str, None] = "0002_core_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("is_customer", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_supplier", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("kvk", sa.String(), nullable=True),
        sa.Column("btw_number", sa.String(), nullable=True),
        sa.Column("iban", sa.String(), nullable=True),
        sa.Column("address_line", sa.String(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=False, server_default=sa.text("'NL'")),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("is_customer OR is_supplier", name="ck_contact_role"),
        sa.CheckConstraint(
            "kvk IS NULL OR (length(kvk) = 8 AND kvk NOT GLOB '*[^0-9]*')",
            name="ck_contact_kvk",
        ),
        sa.CheckConstraint("length(country) = 2", name="ck_contact_country"),
    )
    op.create_index("ix_contact_name_key", "contact", ["name_key"])
    op.create_index("ix_contact_is_active", "contact", ["is_active"])
    for col in ("kvk", "btw_number", "iban"):
        op.create_index(
            f"uq_contact_{col}",
            "contact",
            [col],
            unique=True,
            sqlite_where=sa.text(f"{col} IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_table("contact")
