"""add vendor_account_rule (memoria 取引先 -> 勘定科目)

Crea la tabla ``vendor_account_rule``: reglas que la app aprende sola cuando el
usuario confirma (o corrige) el 科目 propuesto para un recibo. La siguiente foto
del mismo 取引先 ya llega con el 科目 correcto, y la revision baja a un toque.

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
Create Date: 2026-08-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.types  # tipos portables (GUID) usados en columnas
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c0d1e2f3a4b"
down_revision: str | Sequence[str] | None = "8b9c0d1e2f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la tabla `vendor_account_rule` con su indice y unicidad por clave."""
    op.create_table(
        "vendor_account_rule",
        sa.Column("id", app.models.types.GUID(), nullable=False),
        sa.Column("vendor_key", sa.String(length=255), nullable=False),
        sa.Column("vendor_sample", sa.String(length=255), nullable=True),
        sa.Column("account_code", sa.String(length=32), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendor_account_rule")),
        sa.UniqueConstraint("vendor_key", name="uq_vendor_account_rule_key"),
    )
    with op.batch_alter_table("vendor_account_rule", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_vendor_account_rule_vendor_key"), ["vendor_key"], unique=False
        )


def downgrade() -> None:
    """Elimina la tabla `vendor_account_rule`."""
    with op.batch_alter_table("vendor_account_rule", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vendor_account_rule_vendor_key"))
    op.drop_table("vendor_account_rule")
