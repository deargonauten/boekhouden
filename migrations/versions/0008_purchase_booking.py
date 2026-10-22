"""purchase booking: purchase_invoice, supplier_default, source link on journal_entry

Revision ID: 0008_purchase_booking
Revises: 0007_grootboek_verfijning
Create Date: 2026-10-22

This migration must not import app.models.

journal_entry stays append-only. The update trigger is replaced by one that allows
exactly one change: filling `source_type`/`source_id` once, while they are still
empty (the booking is posted first, the inkoopfactuur that points to it second, in
the same transaction). Every other update is still refused.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_purchase_booking"
down_revision: Union[str, None] = "0007_grootboek_verfijning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Boekingen zijn onveranderlijk (append-only)"

_ORIGINAL_TRIGGER = f"""
CREATE TRIGGER journal_entry_no_update BEFORE UPDATE ON journal_entry
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""

_UNCHANGED = " AND ".join(
    f"NEW.{c} IS OLD.{c}"
    for c in (
        "id",
        "journal_id",
        "period_id",
        "entry_number",
        "booking_date",
        "description",
        "reference",
        "kind",
        "reverses_entry_id",
        "created_at",
    )
)

_SOURCE_LINK_TRIGGER = f"""
CREATE TRIGGER journal_entry_no_update BEFORE UPDATE ON journal_entry
WHEN NOT (
    OLD.source_type IS NULL AND OLD.source_id IS NULL
    AND NEW.source_type IS NOT NULL AND NEW.source_id IS NOT NULL
    AND {_UNCHANGED}
)
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""


def upgrade() -> None:
    op.create_table(
        "purchase_invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(), nullable=False),
        sa.Column("invoice_number_key", sa.String(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("total_excl_cents", sa.Integer(), nullable=False),
        sa.Column("total_vat_cents", sa.Integer(), nullable=False),
        sa.Column("total_incl_cents", sa.Integer(), nullable=False),
        sa.Column("paid_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.UniqueConstraint("document_id", name="uq_purchase_invoice_document"),
        sa.UniqueConstraint("journal_entry_id", name="uq_purchase_invoice_entry"),
        sa.CheckConstraint("kind IN ('invoice','credit_note')", name="ck_purchase_invoice_kind"),
        sa.CheckConstraint("total_incl_cents > 0", name="ck_purchase_invoice_total"),
        sa.CheckConstraint("paid_cents >= 0", name="ck_purchase_invoice_paid"),
    )
    op.create_index("ix_purchase_invoice_contact_id", "purchase_invoice", ["contact_id"])
    op.create_index("ix_purchase_invoice_invoice_date", "purchase_invoice", ["invoice_date"])

    op.create_table(
        "supplier_default",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("vat_code", sa.String(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["vat_code"], ["vat_code.code"]),
        sa.UniqueConstraint("contact_id", "account_id", name="uq_supplier_default_contact_account"),
    )

    op.execute("DROP TRIGGER journal_entry_no_update")
    op.execute(_SOURCE_LINK_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER journal_entry_no_update")
    op.execute(_ORIGINAL_TRIGGER)
    op.drop_table("supplier_default")
    op.drop_index("ix_purchase_invoice_invoice_date", table_name="purchase_invoice")
    op.drop_index("ix_purchase_invoice_contact_id", table_name="purchase_invoice")
    op.drop_table("purchase_invoice")
