"""phase 6 credential-free purchase orders

Revision ID: e9f0a1b2c3d4
Revises: b4d5e7f8a901
Create Date: 2026-07-31 21:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "b4d5e7f8a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("charge_reference", sa.String(length=255), nullable=False),
        sa.Column("requested_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("charged_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prava_mandate_id", sa.String(length=255), nullable=False),
        sa.Column("prava_transaction_id", sa.String(length=255), nullable=True),
        sa.Column("prava_order_id", sa.String(length=255), nullable=True),
        sa.Column("merchant_order_id", sa.String(length=255), nullable=True),
        sa.Column("report_status", sa.String(length=16), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("charged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkout_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("charged_amount IS NULL OR charged_amount > 0", name="purchase_order_charged_amount_positive"),
        sa.CheckConstraint("requested_amount > 0", name="purchase_order_requested_amount_positive"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merchant_authorization_id"], ["merchant_authorizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id", name="purchase_order_agent_run_unique"),
        sa.UniqueConstraint("charge_reference", name="purchase_order_charge_reference_unique"),
        sa.UniqueConstraint("merchant_order_id"),
        sa.UniqueConstraint("prava_order_id"),
        sa.UniqueConstraint("prava_transaction_id"),
    )
    op.create_index("ix_purchase_orders_owner_id", "purchase_orders", ["owner_id"], unique=False)
    op.create_index("ix_purchase_orders_agent_run_id", "purchase_orders", ["agent_run_id"], unique=False)
    op.create_index(
        "ix_purchase_orders_merchant_authorization_id",
        "purchase_orders",
        ["merchant_authorization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_orders_merchant_authorization_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_agent_run_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_owner_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")
