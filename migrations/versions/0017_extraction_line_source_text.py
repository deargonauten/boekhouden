"""nakijken: bronpassage per uitgelezen regel

Revision ID: 0017_extraction_line_source_text
Revises: 0016_grootboek_kosten_omzet
Create Date: 2026-10-23

Adds the verbatim passage a line was read from, so the review screen can
highlight it in the original document. Working data, nullable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_extraction_line_source_text"
down_revision: Union[str, None] = "0016_grootboek_kosten_omzet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_extraction_line") as batch:
        batch.add_column(sa.Column("source_text", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_extraction_line") as batch:
        batch.drop_column("source_text")
