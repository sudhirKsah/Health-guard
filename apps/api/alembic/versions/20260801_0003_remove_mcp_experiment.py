"""permanently remove the abandoned Payments MCP experiment

Revision ID: 20260801_0003
Revises: 20260801_0002
Create Date: 2026-08-01

The live application uses the verified REST mandate-charge path. This migration deletes only rows
identified by the abandoned MCP checkout columns, removes its OAuth table and purchase-order fields,
and restores the tracked REST/ledger schema.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260801_0003"
down_revision = "20260801_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "purchase_orders" in tables:
        columns = {column["name"] for column in inspector.get_columns("purchase_orders")}
        if {"checkout_session_id", "payment_session_id"}.issubset(columns):
            op.execute(
                sa.text(
                    "DELETE FROM purchase_orders "
                    "WHERE prava_mandate_id IS NULL "
                    "AND (checkout_session_id IS NOT NULL OR payment_session_id IS NOT NULL)"
                )
            )

        unique_constraints = {
            item["name"]
            for item in inspector.get_unique_constraints("purchase_orders")
            if item.get("name")
        }
        for constraint_name in (
            "purchase_order_checkout_session_unique",
            "purchase_order_payment_session_unique",
        ):
            if constraint_name in unique_constraints:
                op.drop_constraint(constraint_name, "purchase_orders", type_="unique")

        for column_name in (
            "checkout_session_id",
            "payment_session_id",
            "quote_expires_at",
            "payment_expires_at",
            "merchant_product_id",
            "merchant_variant_id",
            "quantity",
        ):
            if column_name in columns:
                op.drop_column("purchase_orders", column_name)

        if "prava_mandate_id" in columns:
            remaining_nulls = bind.execute(
                sa.text("SELECT count(*) FROM purchase_orders WHERE prava_mandate_id IS NULL")
            ).scalar_one()
            if remaining_nulls:
                raise RuntimeError(
                    "Refusing to remove the MCP schema because unrelated purchase orders lack a mandate"
                )
            op.alter_column(
                "purchase_orders",
                "prava_mandate_id",
                existing_type=sa.String(length=255),
                nullable=False,
            )

    if "prava_mcp_connections" in tables:
        op.drop_table("prava_mcp_connections")

    if "ledger_events" not in tables:
        op.create_table(
            "ledger_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("owner_id", sa.Uuid(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False),
            sa.Column("agent_run_id", sa.Uuid(), nullable=True),
            sa.Column("supply_id", sa.Uuid(), nullable=True),
            sa.Column("purchase_order_id", sa.Uuid(), nullable=True),
            sa.Column("metadata_safe", sa.JSON(), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["supply_id"], ["supplies.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ledger_events_owner_id", "ledger_events", ["owner_id"])
        op.create_index("ix_ledger_events_event_type", "ledger_events", ["event_type"])
        op.create_index("ix_ledger_events_agent_run_id", "ledger_events", ["agent_run_id"])
        op.create_index("ix_ledger_events_supply_id", "ledger_events", ["supply_id"])
        op.create_index(
            "ix_ledger_events_purchase_order_id", "ledger_events", ["purchase_order_id"]
        )
        op.create_index("ix_ledger_events_created_at", "ledger_events", ["created_at"])


def downgrade() -> None:
    raise RuntimeError("The removed MCP experiment data cannot be restored")
