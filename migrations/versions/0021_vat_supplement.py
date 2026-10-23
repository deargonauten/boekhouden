"""btw-suppletie: verschil tussen een ingediende aangifte en de stand per vandaag

Revision ID: 0021_vat_supplement
Revises: 0020_locked_booking_override
Create Date: 2026-10-23

This migration must not import app.models.

A suppletie freezes the difference per rubriek of one filed period. It can be deleted until a later
aangifte takes it along; then `included_in_return_id` is set once (from NULL to a value) and the row
is immutable. Triggers enforce that, same pattern as vat_return.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_vat_supplement"
down_revision: Union[str, None] = "0020_locked_booking_override"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Een suppletie die in een aangifte is meegenomen kan niet meer worden gewijzigd"

_FIXED = ("id", "year", "kind", "number", "start_date", "end_date", "created_at", "snapshot_json", "total_cents")
_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in _FIXED)

_NO_UPDATE = f"""
CREATE TRIGGER vat_supplement_no_update BEFORE UPDATE ON vat_supplement
WHEN NOT (OLD.included_in_return_id IS NULL AND NEW.included_in_return_id IS NOT NULL AND {_UNCHANGED})
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""

_NO_DELETE = f"""
CREATE TRIGGER vat_supplement_no_delete BEFORE DELETE ON vat_supplement
WHEN OLD.included_in_return_id IS NOT NULL
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END"""


def upgrade() -> None:
    op.create_table(
        "vat_supplement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("included_in_return_id", sa.Integer(), sa.ForeignKey("vat_return.id"), nullable=True),
        sa.CheckConstraint("kind IN ('quarter','month')", name="ck_vat_supplement_kind"),
    )
    op.execute(_NO_UPDATE)
    op.execute(_NO_DELETE)


def downgrade() -> None:
    op.execute("DROP TRIGGER vat_supplement_no_delete")
    op.execute("DROP TRIGGER vat_supplement_no_update")
    op.drop_table("vat_supplement")
