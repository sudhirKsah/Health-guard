"""add native medication reminder preferences

Revision ID: 20260803_0010
Revises: 20260802_0009
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

revision = "20260803_0010"
down_revision = "20260802_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "medication_reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("supply_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("time_of_day", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supply_id"], ["supplies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "supply_id", name="medication_reminder_owner_supply_unique"),
    )
    op.create_index("ix_medication_reminders_owner_id", "medication_reminders", ["owner_id"])
    op.create_index("ix_medication_reminders_supply_id", "medication_reminders", ["supply_id"])


def downgrade() -> None:
    op.drop_index("ix_medication_reminders_supply_id", table_name="medication_reminders")
    op.drop_index("ix_medication_reminders_owner_id", table_name="medication_reminders")
    op.drop_table("medication_reminders")
