"""expand business profile settings

Revision ID: 7f0a1b2c3d4e
Revises: 2a21b8dc3a29
Create Date: 2026-06-22 17:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f0a1b2c3d4e"
down_revision: str | Sequence[str] | None = "2a21b8dc3a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS: tuple[sa.Column[object], ...] = (
    sa.Column("legal_name", sa.String(length=255), nullable=True),
    sa.Column("legal_name_kana", sa.String(length=255), nullable=True),
    sa.Column("corporate_number", sa.String(length=13), nullable=True),
    sa.Column("business_description", sa.String(length=255), nullable=True),
    sa.Column("department_name", sa.String(length=255), nullable=True),
    sa.Column("contact_person_name", sa.String(length=255), nullable=True),
    sa.Column("address_line1", sa.String(length=255), nullable=True),
    sa.Column("address_line2", sa.String(length=255), nullable=True),
    sa.Column("fax", sa.String(length=32), nullable=True),
    sa.Column("website_url", sa.String(length=255), nullable=True),
    sa.Column(
        "default_customer_honorific",
        sa.String(length=16),
        nullable=False,
        server_default="御中",
    ),
    sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
    sa.Column("show_bank_details", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("show_stamp_box", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("show_logo", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("show_seal", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("seal_text", sa.String(length=16), nullable=True, server_default="領収"),
    sa.Column("show_registration_number", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("invoice_message", sa.Text(), nullable=True),
    sa.Column("receipt_message", sa.Text(), nullable=True),
    sa.Column("receipt_proviso", sa.String(length=255), nullable=True),
    sa.Column("transfer_fee_note", sa.String(length=255), nullable=True),
    sa.Column("document_footer_note", sa.Text(), nullable=True),
)


def upgrade() -> None:
    """Add freee-like configurable issuer/template fields."""
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("business_profile")}
    with op.batch_alter_table("business_profile", schema=None) as batch_op:
        for column in _COLUMNS:
            if column.name not in existing:
                batch_op.add_column(column.copy())


def downgrade() -> None:
    """Remove expanded issuer/template fields."""
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("business_profile")}
    with op.batch_alter_table("business_profile", schema=None) as batch_op:
        for column in reversed(_COLUMNS):
            if column.name in existing:
                batch_op.drop_column(column.name)
