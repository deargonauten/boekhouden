"""bank_match: allow source 'sales_invoice' (afletteren of verkoopfacturen)

Revision ID: 0013_bank_match_sales
Revises: 0012_sales_invoices
Create Date: 2026-10-22

This migration must not import app.models.

SQLite cannot alter a CHECK constraint, so bank_match is rebuilt: rows are copied, the two
indexes and both append-only triggers of 0011 are recreated verbatim (no UPDATE except
setting `reversed_at` once, no DELETE). The downgrade restores the old CHECK and refuses to
run while matches on sales invoices exist (those rows would violate it).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_bank_match_sales"
down_revision: Union[str, None] = "0012_sales_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Verbatim from 0011_bank_reconciliation.
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

_COLUMNS = "id, bank_transaction_id, journal_entry_id, source, source_id, amount_cents, created_at, reversed_at"


def _rebuild(allowed_sources: str) -> None:
    op.execute("DROP TRIGGER bank_match_no_delete")
    op.execute("DROP TRIGGER bank_match_no_update")
    op.drop_index("ix_bank_match_bank_transaction_id", table_name="bank_match")
    op.drop_index("ix_bank_match_source", table_name="bank_match")
    op.execute("ALTER TABLE bank_match RENAME TO bank_match_old")
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
        sa.CheckConstraint(f"source IN ({allowed_sources})", name="ck_bank_match_source"),
        sa.CheckConstraint("amount_cents > 0", name="ck_bank_match_amount"),
    )
    op.execute(f"INSERT INTO bank_match ({_COLUMNS}) SELECT {_COLUMNS} FROM bank_match_old")
    op.execute("DROP TABLE bank_match_old")
    op.create_index("ix_bank_match_source", "bank_match", ["source", "source_id"])
    op.create_index("ix_bank_match_bank_transaction_id", "bank_match", ["bank_transaction_id"])
    op.execute(_NO_UPDATE)
    op.execute(_NO_DELETE)


def upgrade() -> None:
    _rebuild("'purchase_invoice','opening_item','sales_invoice'")


def downgrade() -> None:
    found = op.get_bind().execute(sa.text("SELECT count(*) FROM bank_match WHERE source = 'sales_invoice'")).scalar()
    if found:
        raise RuntimeError(
            "Kan niet terug naar de vorige versie: er zijn bankkoppelingen aan verkoopfacturen. "
            "Die koppelingen zijn onveranderlijk."
        )
    _rebuild("'purchase_invoice','opening_item'")
