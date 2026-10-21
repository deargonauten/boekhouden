"""document inbox: document table (facturen en bonnen)

Revision ID: 0004_document_inbox
Revises: 0003_relations
Create Date: 2026-10-21

This migration must not import app.models. The document table has no triggers.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_document_inbox"
down_revision: Union[str, None] = "0003_relations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'nieuw'")),
        sa.Column("source", sa.String(), nullable=False, server_default=sa.text("'upload'")),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.CheckConstraint("status IN ('nieuw','herkend','geboekt')", name="ck_document_status"),
        sa.CheckConstraint("source IN ('upload','email')", name="ck_document_source"),
        sa.CheckConstraint("size_bytes > 0", name="ck_document_size"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_document_sha256"),
        sa.CheckConstraint(
            "status <> 'geboekt' OR journal_entry_id IS NOT NULL", name="ck_document_booked_link"
        ),
    )
    op.create_index("uq_document_sha256", "document", ["sha256"], unique=True)
    op.create_index("ix_document_status", "document", ["status"])
    op.create_index("ix_document_received_at", "document", ["received_at"])
    op.create_index("ix_document_journal_entry_id", "document", ["journal_entry_id"])


def downgrade() -> None:
    op.drop_table("document")
