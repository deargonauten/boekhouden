"""invoice extraction: invoice_extraction and invoice_extraction_line

Revision ID: 0005_invoice_extraction
Revises: 0004_document_inbox
Create Date: 2026-10-21

This migration must not import app.models. Working data, no triggers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_invoice_extraction"
down_revision: Union[str, None] = "0004_document_inbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoice_extraction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("raw_json", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("supplier_name", sa.String(), nullable=True),
        sa.Column("supplier_kvk", sa.String(), nullable=True),
        sa.Column("supplier_btw_number", sa.String(), nullable=True),
        sa.Column("supplier_iban", sa.String(), nullable=True),
        sa.Column("supplier_address_line", sa.String(), nullable=True),
        sa.Column("supplier_postal_code", sa.String(), nullable=True),
        sa.Column("supplier_city", sa.String(), nullable=True),
        sa.Column("supplier_country", sa.String(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("invoice_number", sa.String(), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'EUR'")),
        sa.Column("total_excl_cents", sa.Integer(), nullable=True),
        sa.Column("total_vat_cents", sa.Integer(), nullable=True),
        sa.Column("total_incl_cents", sa.Integer(), nullable=True),
        sa.Column("flags_json", sa.String(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.UniqueConstraint("document_id", name="uq_invoice_extraction_document"),
        sa.CheckConstraint("status IN ('ok','failed')", name="ck_invoice_extraction_status"),
    )
    op.create_index("ix_invoice_extraction_contact_id", "invoice_extraction", ["contact_id"])

    op.create_table(
        "invoice_extraction_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("extraction_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("amount_excl_cents", sa.Integer(), nullable=True),
        sa.Column("vat_amount_cents", sa.Integer(), nullable=True),
        sa.Column("vat_code", sa.String(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("flags_json", sa.String(), nullable=False, server_default=sa.text("'[]'")),
        sa.ForeignKeyConstraint(["extraction_id"], ["invoice_extraction.id"]),
        sa.ForeignKeyConstraint(["vat_code"], ["vat_code.code"]),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.UniqueConstraint("extraction_id", "position", name="uq_invoice_extraction_line_position"),
    )


def downgrade() -> None:
    op.drop_table("invoice_extraction_line")
    op.drop_table("invoice_extraction")
