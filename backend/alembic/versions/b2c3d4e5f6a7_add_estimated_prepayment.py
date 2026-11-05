"""Guarda por ejercicio el 予定納税 notificado; NULL significa no informado.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fiscal_year", sa.Column("estimated_prepayment", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fiscal_year") as batch:
        batch.drop_column("estimated_prepayment")
