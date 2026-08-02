"""per-beneficiary delivery address

Revision ID: 20260802_0008
Revises: 20260802_0007
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260802_0008"
down_revision = "20260802_0007"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("delivery_recipient", sa.String(length=160)),
    ("delivery_email", sa.String(length=320)),
    ("delivery_phone", sa.String(length=32)),
    ("delivery_line1", sa.String(length=255)),
    ("delivery_line2", sa.String(length=255)),
    ("delivery_city", sa.String(length=120)),
    ("delivery_region", sa.String(length=120)),
    ("delivery_postal_code", sa.String(length=24)),
    ("prava_address_id", sa.String(length=64)),
)


def upgrade() -> None:
    for name, kind in _COLUMNS:
        op.add_column("beneficiaries", sa.Column(name, kind, nullable=True))
    op.add_column(
        "beneficiaries",
        sa.Column(
            "delivery_country",
            sa.String(length=2),
            nullable=False,
            server_default="IN",
        ),
    )


def downgrade() -> None:
    op.drop_column("beneficiaries", "delivery_country")
    for name, _kind in reversed(_COLUMNS):
        op.drop_column("beneficiaries", name)
