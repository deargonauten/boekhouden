"""bank reconciliation: bank_match (allocations) and bank_rule (remembered choices)

Revision ID: 0011_bank_reconciliation
Revises: 0010_opening_balance
Create Date: 2026-10-22

This migration must not import app.models.

bank_match is append-only: a trigger refuses every DELETE and every UPDATE except
setting `reversed_at` once (from NULL to a value), which is how an undo is recorded.
bank_transaction already allows changing `status`/`journal_entry_id` (also back to
NULL / 'nieuw'), and opening_item / purchase_invoice allow `paid_cents` updates, so
no other trigger changes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_bank_reconciliation"
down_revision: Union[str, None] = "0010_opening_balance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Koppelingen van banktransacties zijn onveranderlijk (append-only)"

_FIXED = ("id", "bank_transaction_id", "journal_entry_id", "source", "source_id", "amount_cents", "created_at")
_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in _FIXED)

_NO_UPDATE = f"""
CREATE TRIGGER bank_match_no_update BEFORE UPDATE ON bank_match
WHEN NOT (OLD.reversed_at IS NULL AND NEW.reversed_at IS NOT NULL AND {_UNCHANGED})
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""

_NO_DELETE = f"""
CREATE TRIGGER bank_match_no_delete BEFORE DELETE ON bank_match
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""


def upgrade() -> None:
    op.create_table(
        "bank_match",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_transaction_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["bank_transaction_id"], ["bank_transaction.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.CheckConstraint("source IN ('purchase_invoice','opening_item')", name="ck_bank_match_source"),
        sa.CheckConstraint("amount_cents > 0", name="ck_bank_match_amount"),
    )
    op.create_index("ix_bank_match_source", "bank_match", ["source", "source_id"])
    op.create_index("ix_bank_match_bank_transaction_id", "bank_match", ["bank_transaction_id"])
    op.execute(_NO_UPDATE)
    op.execute(_NO_DELETE)

    op.create_table(
        "bank_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("counterparty_iban", sa.String(), nullable=True),
        sa.Column("description_contains", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("vat_code", sa.String(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["vat_code"], ["vat_code.code"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.CheckConstraint("direction IN ('af','bij','beide')", name="ck_bank_rule_direction"),
        sa.CheckConstraint(
            "counterparty_iban IS NOT NULL OR description_contains IS NOT NULL",
            name="ck_bank_rule_condition",
        ),
    )


def downgrade() -> None:
    op.drop_table("bank_rule")
    op.execute("DROP TRIGGER bank_match_no_delete")
    op.execute("DROP TRIGGER bank_match_no_update")
    op.drop_index("ix_bank_match_bank_transaction_id", table_name="bank_match")
    op.drop_index("ix_bank_match_source", table_name="bank_match")
    op.drop_table("bank_match")
