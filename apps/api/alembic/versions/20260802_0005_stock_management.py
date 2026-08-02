"""add auditable stock management

Revision ID: 20260802_0005
Revises: 20260802_0004
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0005"
down_revision = "20260802_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders", sa.Column("purchased_quantity", sa.Numeric(12, 3), nullable=True)
    )
    op.add_column(
        "purchase_orders", sa.Column("purchased_unit", sa.String(length=40), nullable=True)
    )
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supply_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=True),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(12, 3), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "balance_after >= 0", name="stock_movement_balance_nonnegative"
        ),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supply_id"], ["supplies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_order_id", name="stock_movement_purchase_order_unique"),
    )
    op.create_index("ix_stock_movements_supply_id", "stock_movements", ["supply_id"])
    op.create_index(
        "ix_stock_movements_purchase_order_id", "stock_movements", ["purchase_order_id"]
    )
    op.create_index("ix_stock_movements_occurred_at", "stock_movements", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_movements_occurred_at", table_name="stock_movements")
    op.drop_index("ix_stock_movements_purchase_order_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_supply_id", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_column("purchase_orders", "purchased_unit")
    op.drop_column("purchase_orders", "purchased_quantity")
