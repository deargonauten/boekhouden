"""grootboek: kosten- en omzetrekeningen volgens het nieuwe schema

Revision ID: 0016_grootboek_kosten_omzet
Revises: 0015_email_intake
Create Date: 2026-10-23

Renumbers/renames the expense and revenue accounts by id, so booked lines stay
attached. Idempotent: a fresh database is already seeded with the new codes.
This migration must not import app.models; it may import app.seed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.seed.rgs_accounts import SEED_ACCOUNTS, default_contexts

revision: str = "0016_grootboek_kosten_omzet"
down_revision: Union[str, None] = "0015_email_intake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old code, new code). Order matters: 4510 and 4610 are freed before reuse.
_RENUMBER = [
    ("4510", "4339"),  # Representatiekosten
    ("4610", "4806"),  # Administratiekosten (oud)
    ("8000", "8400"),
    ("8010", "8401"),
    ("8020", "8403"),
    ("8040", "8404"),
    ("8050", "8408"),
    ("8990", "8410"),
    ("4100", "4215"),
    ("4110", "4205"),
    ("4200", "4625"),
    ("4210", "4635"),
    ("4220", "4605"),
    ("4230", "4615"),
    ("4300", "4405"),
    ("4310", "4410"),
    ("4320", "4146"),
    ("4400", "4835"),
    ("4500", "4530"),
    ("4600", "4805"),
    ("4700", "4130"),
    ("4900", "4905"),
    ("4910", "4630"),
]


def upgrade() -> None:
    conn = op.get_bind()
    by_code = {a.code: a for a in SEED_ACCOUNTS}
    present = {r[0] for r in conn.execute(sa.text("SELECT code FROM account"))}
    for old, new in _RENUMBER:
        if new in present:  # fresh database, already seeded with the new codes
            continue
        seed = by_code[new]
        conn.execute(
            sa.text(
                "UPDATE account SET code = :new, name = :name, "
                "default_vat_code = :vat WHERE code = :old"
            ),
            {"new": new, "name": seed.name, "vat": seed.default_vat_code, "old": old},
        )
        present.add(new)
    existing = {r[0] for r in conn.execute(sa.text("SELECT code FROM account"))}
    for a in SEED_ACCOUNTS:
        if a.code in existing or a.type not in ("expense", "revenue"):
            continue
        purchase, sales, bank = default_contexts(a.type, a.is_system, a.code)
        conn.execute(
            sa.text(
                "INSERT INTO account (code, name, rgs_code, type, is_system, "
                "default_vat_code, selectable_purchase, selectable_sales, "
                "selectable_bank) VALUES (:c, :n, :r, :t, :s, :v, :p, :sa, :b)"
            ),
            {"c": a.code, "n": a.name, "r": a.rgs_code, "t": a.type,
             "s": int(a.is_system), "v": a.default_vat_code, "p": int(purchase),
             "sa": int(sales), "b": int(bank)},
        )
    # The old Administratiekosten account is superseded by 4805: hide it.
    conn.execute(
        sa.text(
            "UPDATE account SET is_active = 0 WHERE code = '4806'"
        )
    )


def downgrade() -> None:
    # Renumbering is not reversed; the schema itself is unchanged.
    pass
