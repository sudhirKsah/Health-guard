"""drop prava_address_id — the Prava CLI checkout path was removed

Revision ID: 20260802_0009
Revises: 20260802_0008
Create Date: 2026-08-02

Health Guard now drives the merchant checkout itself with headless Chromium, so it ships each
beneficiary's own address directly. The opaque Prava address reference only existed for the CLI
executor, which required every beneficiary's address to live under one operator's personal Prava
account — an arrangement that could not be justified for other people's data.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0009"
down_revision = "20260802_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("beneficiaries", "prava_address_id")


def downgrade() -> None:
    op.add_column(
        "beneficiaries", sa.Column("prava_address_id", sa.String(length=64), nullable=True)
    )
