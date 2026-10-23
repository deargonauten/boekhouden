"""expliciet boeken in een vergrendelde periode (bankmutaties)

Revision ID: 0020_locked_booking_override
Revises: 0019_invoice_numbering
Create Date: 2026-10-23

Single-row flag the ledger service sets for the duration of one explicitly confirmed posting
and clears again. While it is set, the two period-open triggers accept a vergrendelde period
(the booking date must still fall inside the period). The triggers are recreated here; see the
note in 0002_core_ledger about batch mode dropping them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_locked_booking_override"
down_revision: Union[str, None] = "0019_invoice_numbering"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OVERRIDE_ON = "EXISTS (SELECT 1 FROM locked_booking_override WHERE id = 1 AND active = 1)"

NEW_TRIGGERS = {
    "journal_entry_period_open": f"""
CREATE TRIGGER journal_entry_period_open BEFORE INSERT ON journal_entry
WHEN NOT EXISTS (
    SELECT 1 FROM period
    WHERE id = NEW.period_id AND (status = 'open' OR {OVERRIDE_ON})
      AND NEW.booking_date >= start_date AND NEW.booking_date <= end_date
)
BEGIN SELECT RAISE(ABORT, 'Periode is vergrendeld of boekdatum valt buiten de periode'); END""",
    "journal_line_period_open": f"""
CREATE TRIGGER journal_line_period_open BEFORE INSERT ON journal_line
WHEN NOT EXISTS (
    SELECT 1 FROM journal_entry e JOIN period p ON p.id = e.period_id
    WHERE e.id = NEW.entry_id AND (p.status = 'open' OR {OVERRIDE_ON})
)
BEGIN SELECT RAISE(ABORT, 'Periode is vergrendeld'); END""",
}


def upgrade() -> None:
    op.create_table(
        "locked_booking_override",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("id = 1", name="ck_locked_booking_override_single_row"),
    )
    op.execute("INSERT INTO locked_booking_override (id, active) VALUES (1, 0)")
    for name, ddl in NEW_TRIGGERS.items():
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.execute(ddl)


OLD_TRIGGERS = {
    "journal_entry_period_open": """
CREATE TRIGGER journal_entry_period_open BEFORE INSERT ON journal_entry
WHEN NOT EXISTS (
    SELECT 1 FROM period
    WHERE id = NEW.period_id AND status = 'open'
      AND NEW.booking_date >= start_date AND NEW.booking_date <= end_date
)
BEGIN SELECT RAISE(ABORT, 'Periode is vergrendeld of boekdatum valt buiten de periode'); END""",
    "journal_line_period_open": """
CREATE TRIGGER journal_line_period_open BEFORE INSERT ON journal_line
WHEN NOT EXISTS (
    SELECT 1 FROM journal_entry e JOIN period p ON p.id = e.period_id
    WHERE e.id = NEW.entry_id AND p.status = 'open'
)
BEGIN SELECT RAISE(ABORT, 'Periode is vergrendeld'); END""",
}


def downgrade() -> None:
    for name, ddl in OLD_TRIGGERS.items():
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.execute(ddl)
    op.drop_table("locked_booking_override")
