"""bank statement import: bank_account, bank_import_batch, bank_transaction

Revision ID: 0009_bank_import
Revises: 0008_purchase_booking
Create Date: 2026-10-22

This migration must not import app.models.

bank_transaction is append-only: triggers refuse every DELETE and every UPDATE
except of `status` and `journal_entry_id` (reserved for the later bank
reconciliation feature, the only future writer).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_bank_import"
down_revision: Union[str, None] = "0008_purchase_booking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Banktransacties zijn onveranderlijk (append-only)"

_IMMUTABLE_COLUMNS = (
    "id",
    "bank_account_id",
    "import_batch_id",
    "booking_date",
    "value_date",
    "amount_cents",
    "currency",
    "counterparty_name",
    "counterparty_iban",
    "description",
    "end_to_end_id",
    "bank_reference",
    "balance_after_cents",
    "dedupe_key",
    "occurrence",
    "raw",
    "created_at",
)
_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in _IMMUTABLE_COLUMNS)

_NO_UPDATE = f"""
CREATE TRIGGER bank_transaction_no_update BEFORE UPDATE ON bank_transaction
WHEN NOT ({_UNCHANGED})
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""

_NO_DELETE = f"""
CREATE TRIGGER bank_transaction_no_delete BEFORE DELETE ON bank_transaction
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""


def upgrade() -> None:
    op.create_table(
        "bank_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("iban", sa.String(), nullable=False),
        sa.Column("bank", sa.String(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journal.id"]),
        sa.UniqueConstraint("iban", name="uq_bank_account_iban"),
        sa.UniqueConstraint("account_id", name="uq_bank_account_account"),
        sa.CheckConstraint(
            "bank IS NULL OR bank IN ('ing','rabobank','abn_amro','bunq','overig')",
            name="ck_bank_account_bank",
        ),
    )

    op.create_table(
        "bank_import_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("ext", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("detected_format", sa.String(), nullable=False),
        sa.Column("detected_bank", sa.String(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "maybe_duplicate_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_account.id"]),
        sa.CheckConstraint("status IN ('voorbeeld','afgerond')", name="ck_bank_batch_status"),
        sa.CheckConstraint(
            "detected_format IN ('camt053','mt940','csv')", name="ck_bank_batch_format"
        ),
    )
    op.create_index(
        "ix_bank_batch_account_sha", "bank_import_batch", ["bank_account_id", "sha256"]
    )

    op.create_table(
        "bank_transaction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'EUR'")),
        sa.Column("counterparty_name", sa.String(), nullable=True),
        sa.Column("counterparty_iban", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column("end_to_end_id", sa.String(), nullable=True),
        sa.Column("bank_reference", sa.String(), nullable=True),
        sa.Column("balance_after_cents", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'nieuw'")),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_account.id"]),
        sa.ForeignKeyConstraint(["import_batch_id"], ["bank_import_batch.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.UniqueConstraint(
            "bank_account_id", "dedupe_key", "occurrence", name="uq_bank_transaction_dedupe"
        ),
        sa.CheckConstraint("amount_cents <> 0", name="ck_bank_transaction_amount"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_bank_transaction_currency"),
        sa.CheckConstraint(
            "status IN ('nieuw','geboekt','genegeerd')", name="ck_bank_transaction_status"
        ),
    )
    op.create_index(
        "ix_bank_transaction_account_date", "bank_transaction", ["bank_account_id", "booking_date"]
    )
    op.create_index(
        "ix_bank_transaction_account_date_amount",
        "bank_transaction",
        ["bank_account_id", "booking_date", "amount_cents"],
    )
    op.create_index("ix_bank_transaction_batch", "bank_transaction", ["import_batch_id"])

    op.execute(_NO_UPDATE)
    op.execute(_NO_DELETE)


def downgrade() -> None:
    op.execute("DROP TRIGGER bank_transaction_no_delete")
    op.execute("DROP TRIGGER bank_transaction_no_update")
    op.drop_index("ix_bank_transaction_batch", table_name="bank_transaction")
    op.drop_index("ix_bank_transaction_account_date_amount", table_name="bank_transaction")
    op.drop_index("ix_bank_transaction_account_date", table_name="bank_transaction")
    op.drop_table("bank_transaction")
    op.drop_index("ix_bank_batch_account_sha", table_name="bank_import_batch")
    op.drop_table("bank_import_batch")
    op.drop_table("bank_account")
