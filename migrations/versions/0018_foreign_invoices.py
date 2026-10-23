"""buitenlandse facturen: valuta, wisselkoers en verlegd btw-tarief

Revision ID: 0018_foreign_invoices
Revises: 0017_extraction_line_source_text
Create Date: 2026-10-23

Extraction keeps the koers and the Dutch rate for verlegde btw while nakijken; the
booked inkoopfactuur keeps its original currency, koers and original total (its own
amounts stay euro cents).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_foreign_invoices"
down_revision: Union[str, None] = "0017_extraction_line_source_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_extraction") as batch:
        batch.add_column(sa.Column("exchange_rate_micro", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("shifted_vat_rate_bp", sa.Integer(), nullable=True))
    with op.batch_alter_table("purchase_invoice") as batch:
        batch.add_column(sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'EUR'")))
        batch.add_column(sa.Column("exchange_rate_micro", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("original_total_incl_cents", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("purchase_invoice") as batch:
        batch.drop_column("original_total_incl_cents")
        batch.drop_column("exchange_rate_micro")
        batch.drop_column("currency")
    with op.batch_alter_table("invoice_extraction") as batch:
        batch.drop_column("shifted_vat_rate_bp")
        batch.drop_column("exchange_rate_micro")
