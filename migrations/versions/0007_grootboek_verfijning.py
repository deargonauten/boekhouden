"""grootboek verfijning: btw-rubrieken and 'selecteerbaar bij'

Revision ID: 0007_grootboek_verfijning
Revises: 0006_company_profile
Create Date: 2026-10-22

This migration must not import app.models; it may import app.seed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.seed.rgs_accounts import default_contexts
from app.seed.vat_rubrieken import SEED_VAT_RUBRIEKEN

revision: str = "0007_grootboek_verfijning"
down_revision: Union[str, None] = "0006_company_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FLAGS = ("selectable_purchase", "selectable_sales", "selectable_bank")


def upgrade() -> None:
    with op.batch_alter_table("vat_code") as batch:
        batch.add_column(sa.Column("sales_rubriek", sa.String(), nullable=True))
        batch.add_column(sa.Column("purchase_rubriek", sa.String(), nullable=True))
        batch.add_column(
            sa.Column(
                "is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")
            )
        )
    with op.batch_alter_table("account") as batch:
        for name in _FLAGS:
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )

    conn = op.get_bind()
    for code, (sales, purchase) in SEED_VAT_RUBRIEKEN.items():
        conn.execute(
            sa.text(
                "UPDATE vat_code SET sales_rubriek = :s, purchase_rubriek = :p, "
                "is_system = 1 WHERE code = :c"
            ),
            {"s": sales, "p": purchase, "c": code},
        )
    rows = conn.execute(sa.text("SELECT id, code, type, is_system FROM account")).all()
    for id_, code, type_, is_system in rows:
        purchase, sales, bank = default_contexts(type_, bool(is_system), code)
        conn.execute(
            sa.text(
                "UPDATE account SET selectable_purchase = :p, selectable_sales = :s, "
                "selectable_bank = :b WHERE id = :id"
            ),
            {"p": int(purchase), "s": int(sales), "b": int(bank), "id": id_},
        )


def downgrade() -> None:
    with op.batch_alter_table("account") as batch:
        for name in _FLAGS:
            batch.drop_column(name)
    with op.batch_alter_table("vat_code") as batch:
        batch.drop_column("is_system")
        batch.drop_column("purchase_rubriek")
        batch.drop_column("sales_rubriek")
