"""phase 5 local mandate stop date

Revision ID: b4d5e7f8a901
Revises: 4e2f9c01d6a7
Create Date: 2026-07-31 20:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d5e7f8a901"
down_revision: str | Sequence[str] | None = "4e2f9c01d6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "merchant_authorizations",
        sa.Column("health_guard_stop_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("merchant_authorizations", "health_guard_stop_after")
