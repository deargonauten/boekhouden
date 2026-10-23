"""email intake: email_message

Revision ID: 0015_email_intake
Revises: 0014_btw_aangifte
Create Date: 2026-10-23

This migration must not import app.models.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_email_intake"
down_revision: Union[str, None] = "0014_btw_aangifte"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_key", sa.String(), nullable=False),
        sa.Column("from_addr", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("documents_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("documents_duplicate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("attachments_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("moved", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint(
            "outcome IN ('opgeslagen','alleen_dubbel','geen_bijlage')", name="ck_email_message_outcome"
        ),
    )
    op.create_index("uq_email_message_key", "email_message", ["message_key"], unique=True)
    op.create_index("ix_email_message_processed_at", "email_message", ["processed_at"])


def downgrade() -> None:
    op.drop_index("ix_email_message_processed_at", table_name="email_message")
    op.drop_index("uq_email_message_key", table_name="email_message")
    op.drop_table("email_message")
