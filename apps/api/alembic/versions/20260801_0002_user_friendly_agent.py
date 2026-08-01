"""add automatic product setup state

Revision ID: 20260801_0002
Revises: a7b8c9d0e123
Create Date: 2026-08-01
"""

import sqlalchemy as sa

from alembic import op

revision = "20260801_0002"
down_revision = "a7b8c9d0e123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supplies", sa.Column("product_requirements", sa.Text(), nullable=True))
    op.add_column(
        "supplies", sa.Column("preferred_pack_quantity", sa.Numeric(12, 3), nullable=True)
    )
    op.add_column(
        "supplies",
        sa.Column(
            "setup_status",
            sa.String(length=32),
            nullable=False,
            server_default="waiting_for_merchant",
        ),
    )
    op.add_column("supplies", sa.Column("setup_message", sa.Text(), nullable=True))
    op.add_column("supplies", sa.Column("agent_summary", sa.Text(), nullable=True))
    op.add_column(
        "supplies", sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        """
        UPDATE supplies
        SET setup_status = 'ready',
            setup_message = 'An exact merchant product is approved for automatic replenishment.',
            configured_at = now()
        WHERE EXISTS (
            SELECT 1
            FROM product_equivalence_sets pes
            JOIN approved_variants av ON av.equivalence_set_id = pes.id
            WHERE pes.supply_id = supplies.id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("supplies", "configured_at")
    op.drop_column("supplies", "agent_summary")
    op.drop_column("supplies", "setup_message")
    op.drop_column("supplies", "setup_status")
    op.drop_column("supplies", "preferred_pack_quantity")
    op.drop_column("supplies", "product_requirements")
