"""add opening_balance (期首残高 manual por 年度)

Crea la tabla ``opening_balance`` para los saldos manuales al iniciar un 年度.
La app mantiene estos importes como fuente editable y genera un 仕訳 de apertura
separado para que el balance sheet use el motor contable existente.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

import app.models.types
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabla `opening_balance` con unicidad por cuenta y 年度."""
    op.create_table(
        "opening_balance",
        sa.Column("id", app.models.types.GUID(), nullable=False),
        sa.Column("fiscal_year_id", app.models.types.GUID(), nullable=False),
        sa.Column("account_id", app.models.types.GUID(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name=op.f("fk_opening_balance_account_id_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fiscal_year_id"],
            ["fiscal_year.id"],
            name=op.f("fk_opening_balance_fiscal_year_id_fiscal_year"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opening_balance")),
        sa.UniqueConstraint(
            "fiscal_year_id",
            "account_id",
            name="uq_opening_balance_year_account",
        ),
    )


def downgrade() -> None:
    """Elimina la tabla `opening_balance`."""
    op.drop_table("opening_balance")
