"""retain the applied agent run status width

Revision ID: a7b8c9d0e123
Revises: f7a8b9c0d1e2
Create Date: 2026-08-01

This revision contains only the already-applied status-width change. It deliberately contains no
Payments MCP tables, checkout state, credentials, or integration behavior.
"""

import sqlalchemy as sa

from alembic import op

revision = "a7b8c9d0e123"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agent_runs",
        "status",
        existing_type=sa.String(length=24),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "agent_runs",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=24),
        existing_nullable=False,
    )
