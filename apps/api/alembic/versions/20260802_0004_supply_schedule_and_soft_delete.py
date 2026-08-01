"""add supply inventory timing and soft deletion

Revision ID: 20260802_0004
Revises: 20260801_0003
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0004"
down_revision = "20260801_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplies",
        sa.Column(
            "inventory_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("UPDATE supplies SET inventory_observed_at = updated_at")
    op.add_column(
        "supplies", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_supplies_deleted_at", "supplies", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_supplies_deleted_at", table_name="supplies")
    op.drop_column("supplies", "deleted_at")
    op.drop_column("supplies", "inventory_observed_at")
