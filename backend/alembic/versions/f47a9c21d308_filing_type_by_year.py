"""Permite confirmar modalidad por ejercicio sin inventar datos históricos.

Revision ID: f47a9c21d308
Revises: b2c3d4e5f6a7
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f47a9c21d308"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fiscal_year", sa.Column("filing_type_override", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fiscal_year") as batch:
        batch.drop_column("filing_type_override")
