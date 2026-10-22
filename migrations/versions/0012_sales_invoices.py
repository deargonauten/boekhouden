"""sales invoices: sales_invoice (+lines, vat, number counter, credit applications, reminders)

Revision ID: 0012_sales_invoices
Revises: 0011_bank_reconciliation
Create Date: 2026-10-22

This migration must not import app.models.

A definitief sales_invoice is immutable: triggers refuse every DELETE and every UPDATE
except one that changes only `paid_cents` and/or `updated_at` (bank payments). The change
from concept to definitief is allowed because the trigger only looks at rows whose OLD
status is already 'definitief'. Lines and VAT rows of a definitief invoice cannot be
inserted, updated or deleted. credit applications and reminders are append-only.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_sales_invoices"
down_revision: Union[str, None] = "0011_bank_reconciliation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_MSG = "Een definitieve factuur kan niet meer worden gewijzigd (maak een creditnota)"
APPEND_ONLY_MSG = "Dit is onveranderlijk (append-only)"

# Every column of sales_invoice except paid_cents and updated_at.
_FROZEN = (
    "id", "kind", "status", "contact_id", "credited_invoice_id", "number", "number_year",
    "number_seq", "invoice_date", "service_date", "payment_term_days", "due_date",
    "due_date_manual", "reference", "note",
    "seller_name", "seller_address_line", "seller_postal_code", "seller_city", "seller_country",
    "seller_kvk", "seller_btw_id", "seller_iban", "seller_email", "seller_phone",
    "buyer_name", "buyer_address_line", "buyer_postal_code", "buyer_city", "buyer_country",
    "buyer_btw_number", "buyer_kvk",
    "total_excl_cents", "total_vat_cents", "total_incl_cents", "journal_entry_id",
    "pdf_sha256", "pdf_path", "finalized_at", "created_at",
)  # fmt: skip
_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in _FROZEN)

_TRIGGERS = [
    f"""CREATE TRIGGER sales_invoice_no_update BEFORE UPDATE ON sales_invoice
WHEN OLD.status = 'definitief' AND NOT ({_UNCHANGED})
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
    f"""CREATE TRIGGER sales_invoice_no_delete BEFORE DELETE ON sales_invoice
WHEN OLD.status = 'definitief'
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
]
for _table in ("sales_invoice_line", "sales_invoice_vat"):
    _TRIGGERS += [
        f"""CREATE TRIGGER {_table}_no_insert BEFORE INSERT ON {_table}
WHEN (SELECT status FROM sales_invoice WHERE id = NEW.invoice_id) = 'definitief'
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
        f"""CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
WHEN (SELECT status FROM sales_invoice WHERE id = OLD.invoice_id) = 'definitief'
  OR (SELECT status FROM sales_invoice WHERE id = NEW.invoice_id) = 'definitief'
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
        f"""CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
WHEN (SELECT status FROM sales_invoice WHERE id = OLD.invoice_id) = 'definitief'
BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MSG}'); END""",
    ]
for _table in ("sales_credit_application", "sales_reminder"):
    _TRIGGERS += [
        f"""CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY_MSG}'); END""",
        f"""CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY_MSG}'); END""",
    ]

_TRIGGER_NAMES = [t.split()[2] for t in _TRIGGERS]


def upgrade() -> None:
    op.add_column(
        "contact",
        sa.Column(
            "payment_term_days",
            sa.Integer(),
            sa.CheckConstraint(
                "payment_term_days IS NULL OR (payment_term_days >= 0 AND payment_term_days <= 365)",
                name="ck_contact_payment_term",
            ),
            nullable=True,
        ),
    )

    op.create_table(
        "sales_number_counter",
        sa.Column("year", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.CheckConstraint("last_number >= 0", name="ck_sales_number_counter_last"),
    )

    op.create_table(
        "sales_invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False, server_default=sa.text("'invoice'")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'concept'")),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("credited_invoice_id", sa.Integer(), nullable=True),
        sa.Column("number", sa.String(), nullable=True),
        sa.Column("number_year", sa.Integer(), nullable=True),
        sa.Column("number_seq", sa.Integer(), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("payment_term_days", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("due_date_manual", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("seller_name", sa.String(), nullable=True),
        sa.Column("seller_address_line", sa.String(), nullable=True),
        sa.Column("seller_postal_code", sa.String(), nullable=True),
        sa.Column("seller_city", sa.String(), nullable=True),
        sa.Column("seller_country", sa.String(), nullable=True),
        sa.Column("seller_kvk", sa.String(), nullable=True),
        sa.Column("seller_btw_id", sa.String(), nullable=True),
        sa.Column("seller_iban", sa.String(), nullable=True),
        sa.Column("seller_email", sa.String(), nullable=True),
        sa.Column("seller_phone", sa.String(), nullable=True),
        sa.Column("buyer_name", sa.String(), nullable=True),
        sa.Column("buyer_address_line", sa.String(), nullable=True),
        sa.Column("buyer_postal_code", sa.String(), nullable=True),
        sa.Column("buyer_city", sa.String(), nullable=True),
        sa.Column("buyer_country", sa.String(), nullable=True),
        sa.Column("buyer_btw_number", sa.String(), nullable=True),
        sa.Column("buyer_kvk", sa.String(), nullable=True),
        sa.Column("total_excl_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_vat_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_incl_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("paid_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("pdf_sha256", sa.String(), nullable=True),
        sa.Column("pdf_path", sa.String(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"]),
        sa.ForeignKeyConstraint(["credited_invoice_id"], ["sales_invoice.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.UniqueConstraint("journal_entry_id", name="uq_sales_invoice_entry"),
        sa.UniqueConstraint("number_year", "number_seq", name="uq_sales_invoice_number_seq"),
        sa.CheckConstraint("kind IN ('invoice','credit_note')", name="ck_sales_invoice_kind"),
        sa.CheckConstraint("status IN ('concept','definitief')", name="ck_sales_invoice_status"),
        sa.CheckConstraint(
            "credited_invoice_id IS NULL OR kind = 'credit_note'", name="ck_sales_invoice_credited"
        ),
        sa.CheckConstraint(
            "status = 'concept' OR (number IS NOT NULL AND journal_entry_id IS NOT NULL "
            "AND pdf_sha256 IS NOT NULL AND seller_name IS NOT NULL AND buyer_name IS NOT NULL)",
            name="ck_sales_invoice_definitief",
        ),
        sa.CheckConstraint(
            "total_excl_cents >= 0 AND total_vat_cents >= 0 AND total_incl_cents >= 0",
            name="ck_sales_invoice_totals",
        ),
        sa.CheckConstraint("paid_cents >= 0", name="ck_sales_invoice_paid"),
        sa.CheckConstraint("payment_term_days >= 0", name="ck_sales_invoice_term"),
    )
    op.create_index(
        "uq_sales_invoice_number", "sales_invoice", ["number"], unique=True,
        sqlite_where=sa.text("number IS NOT NULL"),
    )
    op.create_index("ix_sales_invoice_contact_id", "sales_invoice", ["contact_id"])
    op.create_index("ix_sales_invoice_invoice_date", "sales_invoice", ["invoice_date"])
    op.create_index("ix_sales_invoice_status", "sales_invoice", ["status"])

    op.create_table(
        "sales_invoice_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column("quantity_milli", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False, server_default=sa.text("'stuk'")),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("vat_code", sa.String(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("line_excl_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("original_line_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoice.id"]),
        sa.ForeignKeyConstraint(["vat_code"], ["vat_code.code"]),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["original_line_id"], ["sales_invoice_line.id"]),
        sa.CheckConstraint("quantity_milli > 0", name="ck_sales_invoice_line_quantity"),
        sa.CheckConstraint("unit_price_cents >= 0", name="ck_sales_invoice_line_price"),
    )
    op.create_index("ix_sales_invoice_line_invoice_id", "sales_invoice_line", ["invoice_id"])

    op.create_table(
        "sales_invoice_vat",
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("vat_code", sa.String(), nullable=False),
        sa.Column("rate_bp", sa.Integer(), nullable=False),
        sa.Column("base_cents", sa.Integer(), nullable=False),
        sa.Column("vat_cents", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("invoice_id", "vat_code"),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoice.id"]),
        sa.ForeignKeyConstraint(["vat_code"], ["vat_code.code"]),
    )

    op.create_table(
        "sales_credit_application",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credit_note_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["credit_note_id"], ["sales_invoice.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoice.id"]),
        sa.CheckConstraint("amount_cents > 0", name="ck_sales_credit_application_amount"),
    )
    op.create_index("ix_sales_credit_application_invoice_id", "sales_credit_application", ["invoice_id"])
    op.create_index(
        "ix_sales_credit_application_credit_note_id", "sales_credit_application", ["credit_note_id"]
    )

    op.create_table(
        "sales_reminder",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("reminder_date", sa.Date(), nullable=False),
        sa.Column("new_due_date", sa.Date(), nullable=False),
        sa.Column("open_cents", sa.Integer(), nullable=False),
        sa.Column("body_text", sa.String(), nullable=False),
        sa.Column("pdf_sha256", sa.String(), nullable=True),
        sa.Column("pdf_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoice.id"]),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_sales_reminder_level"),
    )
    op.create_index("ix_sales_reminder_invoice_id", "sales_reminder", ["invoice_id"])

    for statement in _TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    for name in _TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("sales_reminder")
    op.drop_table("sales_credit_application")
    op.drop_table("sales_invoice_vat")
    op.drop_table("sales_invoice_line")
    op.drop_table("sales_invoice")
    op.drop_table("sales_number_counter")
    with op.batch_alter_table("contact") as batch:
        batch.drop_constraint("ck_contact_payment_term", type_="check")
        batch.drop_column("payment_term_days")
