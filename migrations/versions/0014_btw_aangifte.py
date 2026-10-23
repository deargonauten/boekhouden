"""btw-aangifte: vat_setting, vat_return (append-only), vat_entry_contact

Revision ID: 0014_btw_aangifte
Revises: 0013_bank_match_sales
Create Date: 2026-10-23

This migration must not import app.models.

vat_return holds only filed returns and is append-only: a trigger refuses every DELETE and
every UPDATE except setting `reference` once (from NULL to a value), same pattern as bank_match.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_btw_aangifte"
down_revision: Union[str, None] = "0013_bank_match_sales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Een ingediende btw-aangifte kan niet meer worden gewijzigd (append-only)"

_FIXED = (
    "id", "year", "kind", "number", "start_date", "end_date", "status",
    "filed_on", "filed_at", "snapshot_json", "total_cents",
)
_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in _FIXED)

_NO_UPDATE = f"""
CREATE TRIGGER vat_return_no_update BEFORE UPDATE ON vat_return
WHEN NOT (OLD.reference IS NULL AND NEW.reference IS NOT NULL AND {_UNCHANGED})
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""

_NO_DELETE = f"""
CREATE TRIGGER vat_return_no_delete BEFORE DELETE ON vat_return
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""


def upgrade() -> None:
    op.create_table(
        "vat_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("kor_from", sa.Date(), nullable=True),
        sa.Column("kor_until", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_vat_setting_single_row"),
        sa.CheckConstraint("frequency IN ('quarter','month')", name="ck_vat_setting_frequency"),
    )
    op.create_table(
        "vat_return",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("filed_at", sa.DateTime(), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.UniqueConstraint("year", "kind", "number", name="uq_vat_return_period"),
        sa.CheckConstraint("kind IN ('quarter','month')", name="ck_vat_return_kind"),
        sa.CheckConstraint(
            "(kind = 'quarter' AND number BETWEEN 1 AND 4) OR (kind = 'month' AND number BETWEEN 1 AND 12)",
            name="ck_vat_return_number",
        ),
        sa.CheckConstraint("status = 'ingediend'", name="ck_vat_return_status"),
    )
    op.execute(_NO_UPDATE)
    op.execute(_NO_DELETE)
    op.create_table(
        "vat_entry_contact",
        sa.Column("entry_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entry.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
    )


def downgrade() -> None:
    op.drop_table("vat_entry_contact")
    op.execute("DROP TRIGGER vat_return_no_delete")
    op.execute("DROP TRIGGER vat_return_no_update")
    op.drop_table("vat_return")
    op.drop_table("vat_setting")
