"""add mandate cycle guard and approved variant price

Revision ID: 20260802_0006
Revises: 20260802_0005
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0006"
down_revision = "20260802_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplies", sa.Column("payment_deferred_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "merchant_authorizations",
        sa.Column("mandate_last_charge_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "merchant_authorizations",
        sa.Column("mandate_last_charge_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "approved_variants", sa.Column("latest_unit_price", sa.Numeric(12, 2), nullable=True)
    )
    op.add_column(
        "approved_variants", sa.Column("latest_currency", sa.String(length=3), nullable=True)
    )
    op.add_column(
        "approved_variants",
        sa.Column("price_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approved_variants", "price_checked_at")
    op.drop_column("approved_variants", "latest_currency")
    op.drop_column("approved_variants", "latest_unit_price")
    op.drop_column("merchant_authorizations", "mandate_last_charge_status")
    op.drop_column("merchant_authorizations", "mandate_last_charge_at")
    op.drop_column("supplies", "payment_deferred_until")
