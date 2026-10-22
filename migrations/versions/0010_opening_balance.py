"""beginbalans: opening_item (openstaande posten of the beginbalans)

Revision ID: 0010_opening_balance
Revises: 0009_bank_import
Create Date: 2026-10-22

This migration must not import app.models.

opening_item is append-only: triggers refuse every DELETE and every UPDATE except of
`paid_cents` (reserved for the later bank reconciliation feature).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_opening_balance"
down_revision: Union[str, None] = "0009_bank_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Openstaande posten van de beginbalans zijn onveranderlijk (append-only)"

_IMMUTABLE_COLUMNS = (
    "id",
    "fiscal_year_id",
    "journal_entry_id",
    "contact_id",
    "side",
    "invoice_number",
    "invoice_number_key",
    "invoice_date",
    "due_date",
    "amount_cents",
    "created_at",
)
_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in _IMMUTABLE_COLUMNS)

_NO_UPDATE = f"""
CREATE TRIGGER opening_item_no_update BEFORE UPDATE ON opening_item
WHEN NOT ({_UNCHANGED})
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""

_NO_DELETE = f"""
CREATE TRIGGER opening_item_no_delete BEFORE DELETE ON opening_item
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""


def upgrade() -> None:
    op.create_table(
        "opening_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fiscal_year_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("invoice_number", sa.String(), nullable=False),
        sa.Column("invoice_number_key", sa.String(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("paid_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fiscal_year_id"], ["fiscal_year.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.CheckConstraint("side IN ('debiteur','crediteur')", name="ck_opening_item_side"),
        sa.CheckConstraint("amount_cents > 0", name="ck_opening_item_amount"),
        sa.CheckConstraint(
            "paid_cents >= 0 AND paid_cents <= amount_cents", name="ck_opening_item_paid"
        ),
    )
    op.create_index("ix_opening_item_contact_id", "opening_item", ["contact_id"])
    op.create_index("ix_opening_item_journal_entry_id", "opening_item", ["journal_entry_id"])
    op.execute(_NO_UPDATE)
    op.execute(_NO_DELETE)


def downgrade() -> None:
    op.execute("DROP TRIGGER opening_item_no_delete")
    op.execute("DROP TRIGGER opening_item_no_update")
    op.drop_index("ix_opening_item_journal_entry_id", table_name="opening_item")
    op.drop_index("ix_opening_item_contact_id", table_name="opening_item")
    op.drop_table("opening_item")
