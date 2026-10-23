"""instelbare factuurnummering

Revision ID: 0019_invoice_numbering
Revises: 0018_foreign_invoices
Create Date: 2026-10-23

Single-row setting: separator, digits of the volgnummer and whether the volgnummer runs on
over the years. No row means the old behaviour (`YYYY-NNNN`, new series per year).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_invoice_numbering"
down_revision: Union[str, None] = "0018_foreign_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoice_numbering",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("separator", sa.String(), nullable=False, server_default=sa.text("'-'")),
        sa.Column("digits", sa.Integer(), nullable=False, server_default=sa.text("4")),
        sa.Column("continuous", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("id = 1", name="ck_invoice_numbering_single_row"),
        sa.CheckConstraint("separator IN ('-','.','/','')", name="ck_invoice_numbering_separator"),
        sa.CheckConstraint("digits BETWEEN 1 AND 8", name="ck_invoice_numbering_digits"),
    )


def downgrade() -> None:
    op.drop_table("invoice_numbering")
