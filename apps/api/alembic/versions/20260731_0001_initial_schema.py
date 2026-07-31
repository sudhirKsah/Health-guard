"""Initial Health Guard schema baseline.

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31 08:00:00
"""

from collections.abc import Sequence

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Alembic's version table is the real baseline for a new deployment. Domain tables are added
    # only when their corresponding phase is implemented; no placeholder business data is created.
    pass


def downgrade() -> None:
    pass
