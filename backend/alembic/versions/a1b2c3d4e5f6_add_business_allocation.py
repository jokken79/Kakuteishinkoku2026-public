"""Conserva el criterio del reparto de un gasto mixto.

Revision ID: a1b2c3d4e5f6
Revises: 9c0d1e2f3a4b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.models.types import PortableJSON

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "9c0d1e2f3a4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transaction", sa.Column("business_allocation", PortableJSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.drop_column("business_allocation")
