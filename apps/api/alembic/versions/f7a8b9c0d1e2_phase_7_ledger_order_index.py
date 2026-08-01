"""phase 7 ledger purchase order index

Revision ID: f7a8b9c0d1e2
Revises: f1a2b3c4d5e6
Create Date: 2026-08-01
"""

from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_ledger_events_purchase_order_id", "ledger_events", ["purchase_order_id"])


def downgrade() -> None:
    op.drop_index("ix_ledger_events_purchase_order_id", table_name="ledger_events")
