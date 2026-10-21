"""core ledger: schema, immutability triggers, seed

Revision ID: 0002_core_ledger
Revises: 0001_baseline
Create Date: 2026-10-21

NOTE for later migrations: SQLite triggers are not model-visible and Alembic
batch mode (render_as_batch=True) recreates tables, which DROPS triggers. Any
later migration that alters journal_entry, journal_line, period or fiscal_year
must recreate the triggers defined in TRIGGERS below.

This migration must not import app.models; seed data comes from app.seed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.seed.rgs_accounts import SEED_ACCOUNTS, SEED_JOURNALS, SEED_VAT_CODES

revision: str = "0002_core_ledger"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Boekingen zijn onveranderlijk (append-only)"

TRIGGERS: dict[str, str] = {
    "journal_entry_no_update": f"""
CREATE TRIGGER journal_entry_no_update BEFORE UPDATE ON journal_entry
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
    "journal_entry_no_delete": f"""
CREATE TRIGGER journal_entry_no_delete BEFORE DELETE ON journal_entry
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
    "journal_line_no_update": f"""
CREATE TRIGGER journal_line_no_update BEFORE UPDATE ON journal_line
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
    "journal_line_no_delete": f"""
CREATE TRIGGER journal_line_no_delete BEFORE DELETE ON journal_line
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
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
    "period_lock_only": """
CREATE TRIGGER period_lock_only BEFORE UPDATE ON period
WHEN NOT (
    (OLD.id IS NEW.id AND OLD.fiscal_year_id IS NEW.fiscal_year_id
     AND OLD.number IS NEW.number AND OLD.start_date IS NEW.start_date
     AND OLD.end_date IS NEW.end_date AND OLD.status IS NEW.status
     AND OLD.locked_at IS NEW.locked_at)
    OR
    (OLD.status = 'open' AND NEW.status = 'locked'
     AND OLD.id IS NEW.id AND OLD.fiscal_year_id IS NEW.fiscal_year_id
     AND OLD.number IS NEW.number AND OLD.start_date IS NEW.start_date
     AND OLD.end_date IS NEW.end_date)
)
BEGIN SELECT RAISE(ABORT, 'Een periode kan alleen vergrendeld worden (open naar vergrendeld)'); END""",
    "period_no_delete": """
CREATE TRIGGER period_no_delete BEFORE DELETE ON period
BEGIN SELECT RAISE(ABORT, 'Periodes kunnen niet verwijderd worden'); END""",
    "fiscal_year_close_only": """
CREATE TRIGGER fiscal_year_close_only BEFORE UPDATE ON fiscal_year
WHEN NOT (
    (OLD.id IS NEW.id AND OLD.year IS NEW.year AND OLD.start_date IS NEW.start_date
     AND OLD.end_date IS NEW.end_date AND OLD.status IS NEW.status)
    OR
    (OLD.status = 'open' AND NEW.status = 'closed'
     AND OLD.id IS NEW.id AND OLD.year IS NEW.year
     AND OLD.start_date IS NEW.start_date AND OLD.end_date IS NEW.end_date)
)
BEGIN SELECT RAISE(ABORT, 'Een boekjaar kan alleen afgesloten worden (open naar gesloten)'); END""",
    "fiscal_year_no_delete": """
CREATE TRIGGER fiscal_year_no_delete BEFORE DELETE ON fiscal_year
BEGIN SELECT RAISE(ABORT, 'Boekjaren kunnen niet verwijderd worden'); END""",
}


def upgrade() -> None:
    op.create_table(
        "vat_code",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("rate_bp", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("rgs_code", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("is_postable", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("default_vat_code", sa.String(), sa.ForeignKey("vat_code.code"), nullable=True),
        sa.UniqueConstraint("code"),
        sa.CheckConstraint(
            "length(code) = 4 AND code NOT GLOB '*[^0-9]*'", name="ck_account_code"
        ),
        sa.CheckConstraint(
            "type IN ('asset','liability','equity','revenue','expense')",
            name="ck_account_type",
        ),
    )
    op.create_table(
        "journal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("code"),
        sa.CheckConstraint(
            "type IN ('verkoop','inkoop','bank','kas','memoriaal')", name="ck_journal_type"
        ),
        sa.CheckConstraint(
            "type NOT IN ('bank','kas') OR account_id IS NOT NULL", name="ck_journal_account"
        ),
        sa.CheckConstraint(
            "length(code) <= 6 AND code = upper(code)", name="ck_journal_code"
        ),
    )
    op.create_table(
        "fiscal_year",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'open'")),
        sa.UniqueConstraint("year"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_fiscal_year_status"),
    )
    op.create_table(
        "period",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fiscal_year_id", sa.Integer(), sa.ForeignKey("fiscal_year.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("fiscal_year_id", "number", name="uq_period_year_number"),
        sa.CheckConstraint("number BETWEEN 1 AND 12", name="ck_period_number"),
        sa.CheckConstraint("status IN ('open','locked')", name="ck_period_status"),
    )
    op.create_table(
        "entry_sequence",
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journal.id"), primary_key=True),
        sa.Column("fiscal_year_id", sa.Integer(), sa.ForeignKey("fiscal_year.id"), primary_key=True),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "journal_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journal.id"), nullable=False),
        sa.Column("period_id", sa.Integer(), sa.ForeignKey("period.id"), nullable=False),
        sa.Column("entry_number", sa.String(), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False, server_default=sa.text("'normal'")),
        sa.Column("reverses_entry_id", sa.Integer(), sa.ForeignKey("journal_entry.id"), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("entry_number"),
        sa.UniqueConstraint("reverses_entry_id"),
        sa.CheckConstraint("kind IN ('normal','opening','storno')", name="ck_entry_kind"),
        sa.CheckConstraint(
            "(kind = 'storno') = (reverses_entry_id IS NOT NULL)", name="ck_entry_storno"
        ),
    )
    op.create_index("ix_journal_entry_booking_date", "journal_entry", ["booking_date"])
    op.create_index("ix_journal_entry_journal_id_id", "journal_entry", ["journal_id", "id"])
    op.create_table(
        "journal_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entry.id"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=False),
        sa.Column("debit_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("credit_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("vat_code", sa.String(), sa.ForeignKey("vat_code.code"), nullable=True),
        sa.UniqueConstraint("entry_id", "line_no", name="uq_journal_line_entry_line"),
        sa.CheckConstraint(
            "debit_cents >= 0 AND credit_cents >= 0 "
            "AND ((debit_cents > 0) <> (credit_cents > 0))",
            name="ck_line_amounts",
        ),
    )
    op.create_index("ix_journal_line_account_id", "journal_line", ["account_id"])

    # Seed (idempotent)
    conn = op.get_bind()
    for code, name, rate_bp in SEED_VAT_CODES:
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO vat_code (code, name, rate_bp, is_active) "
                "VALUES (:code, :name, :rate_bp, 1)"
            ),
            {"code": code, "name": name, "rate_bp": rate_bp},
        )
    for a in SEED_ACCOUNTS:
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO account (code, name, rgs_code, type, is_postable, "
                "is_active, is_system, default_vat_code) "
                "VALUES (:code, :name, :rgs, :type, 1, 1, :sys, :vat)"
            ),
            {
                "code": a.code, "name": a.name, "rgs": a.rgs_code, "type": a.type,
                "sys": int(a.is_system), "vat": a.default_vat_code,
            },
        )
    for code, name, jtype, account_code in SEED_JOURNALS:
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO journal (code, name, type, account_id, is_active) "
                "VALUES (:code, :name, :type, "
                "(SELECT id FROM account WHERE code = :acc), 1)"
            ),
            {"code": code, "name": name, "type": jtype, "acc": account_code},
        )

    for ddl in TRIGGERS.values():
        op.execute(ddl)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_journal_line_account_id", table_name="journal_line")
    op.drop_table("journal_line")
    op.drop_index("ix_journal_entry_journal_id_id", table_name="journal_entry")
    op.drop_index("ix_journal_entry_booking_date", table_name="journal_entry")
    op.drop_table("journal_entry")
    op.drop_table("entry_sequence")
    op.drop_table("period")
    op.drop_table("fiscal_year")
    op.drop_table("journal")
    op.drop_table("account")
    op.drop_table("vat_code")
