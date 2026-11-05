"""add household_expense (家計簿 — libro de gastos personales, NO fiscal)

Crea la tabla ``household_expense``: gastos PERSONALES que el owner trackea
aparte y que NO entran a la declaración (NO van al 仕訳 ni al cálculo del
所得税/住民税/消費税). Módulo 100% aditivo: sin FK a fiscal_year ni taxpayer,
se filtra por mes/año desde el campo ``date``.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

import app.models.types  # tipos portables (GUID) usados en columnas
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabla `household_expense` con su índice por fecha."""
    op.create_table(
        "household_expense",
        sa.Column("id", app.models.types.GUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("memo", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_household_expense")),
    )
    with op.batch_alter_table("household_expense", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_household_expense_date"), ["date"], unique=False
        )


def downgrade() -> None:
    """Elimina la tabla `household_expense`."""
    with op.batch_alter_table("household_expense", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_household_expense_date"))
    op.drop_table("household_expense")
