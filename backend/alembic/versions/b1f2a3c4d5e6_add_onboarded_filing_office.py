"""add onboarded + filing_office to taxpayer

Agrega dos columnas al `taxpayer`:

- ``filing_office`` (String(64), nullable): clave estable del 税務署 de
  presentación (ej. ``"tsushima"``). Antes se resolvía solo por default vía
  ``getattr(taxpayer, "filing_office", None)``; ahora es una columna real.
- ``onboarded`` (Boolean, NOT NULL, default False): marca si el usuario
  completó el onboarding guiado. Los registros existentes (demo) se marcan
  ``True`` en el upgrade para no romper el escenario de demo.

Usa ``batch_alter_table`` (SQLite no soporta ALTER completo).

Revision ID: b1f2a3c4d5e6
Revises: 2543ad33e5f4
Create Date: 2026-06-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f2a3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "2543ad33e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Agrega `filing_office` y `onboarded` al taxpayer."""
    with op.batch_alter_table("taxpayer", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("filing_office", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "onboarded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    # Los contribuyentes ya existentes (demo) NO deben ver el onboarding: se
    # marcan como ya onboardeados.
    op.execute("UPDATE taxpayer SET onboarded = 1")


def downgrade() -> None:
    """Quita las columnas agregadas."""
    with op.batch_alter_table("taxpayer", schema=None) as batch_op:
        batch_op.drop_column("onboarded")
        batch_op.drop_column("filing_office")
