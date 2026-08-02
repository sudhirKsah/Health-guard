"""record real merchant checkout evidence on purchase orders

Revision ID: 20260802_0007
Revises: 20260802_0006
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0007"
down_revision = "20260802_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("checkout_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("checkout_decline_code", sa.String(length=80), nullable=True),
    )
    # Rows settled before this migration reported APPROVED without any merchant checkout. Mark
    # them so no dashboard, ledger, or submission can present them as completed purchases.
    op.execute(
        """
        UPDATE purchase_orders
           SET status = 'settled_without_checkout',
               checkout_decline_code = 'merchant_checkout_never_attempted'
         WHERE status = 'sandbox_settled'
           AND merchant_order_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE purchase_orders
           SET status = 'sandbox_settled'
         WHERE status = 'settled_without_checkout'
        """
    )
    op.drop_column("purchase_orders", "checkout_decline_code")
    op.drop_column("purchase_orders", "checkout_attempted_at")
