"""add past_filing (過去の申告 — archivo histórico de declaraciones)

Crea la tabla ``past_filing``: el archivo histórico de 確定申告 de años
anteriores que el owner sube como PDF. Guarda el PDF original en disco
(``file_ref`` + ``file_hash`` para integridad/idempotencia) y los montos clave
extraídos (nullable: el usuario los corrige si la extracción no fue perfecta).

電子帳簿保存法: el PDF se conserva indexado por al menos 7 años.

Revision ID: c3d4e5f6a7b8
Revises: b1f2a3c4d5e6
Create Date: 2026-06-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

import app.models.types  # tipos portables (GUID) usados en columnas
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b1f2a3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crea la tabla `past_filing` con su FK e índices."""
    op.create_table(
        "past_filing",
        sa.Column("id", app.models.types.GUID(), nullable=False),
        sa.Column("taxpayer_id", app.models.types.GUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("file_ref", sa.String(length=512), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("total_income", sa.Integer(), nullable=True),
        sa.Column("tax_paid", sa.Integer(), nullable=True),
        sa.Column("tax_refund", sa.Integer(), nullable=True),
        sa.Column("tax_office", sa.String(length=128), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("extraction_source", sa.String(length=16), nullable=False),
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
            ["taxpayer_id"],
            ["taxpayer.id"],
            name=op.f("fk_past_filing_taxpayer_id_taxpayer"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_past_filing")),
    )
    with op.batch_alter_table("past_filing", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_past_filing_year"), ["year"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_past_filing_file_hash"), ["file_hash"], unique=False
        )


def downgrade() -> None:
    """Elimina la tabla `past_filing`."""
    with op.batch_alter_table("past_filing", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_past_filing_file_hash"))
        batch_op.drop_index(batch_op.f("ix_past_filing_year"))
    op.drop_table("past_filing")
