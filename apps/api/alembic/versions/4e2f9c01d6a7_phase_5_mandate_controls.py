"""phase 5 Prava mandate controls

Revision ID: 4e2f9c01d6a7
Revises: 221c01c40846
Create Date: 2026-07-31 18:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4e2f9c01d6a7"
down_revision: str | Sequence[str] | None = "221c01c40846"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "merchant_authorizations", sa.Column("prava_setup_session_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("prava_mandate_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_status", sa.String(24), nullable=True)
    )
    op.add_column(
        "merchant_authorizations",
        sa.Column("mandate_approved_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "merchant_authorizations",
        sa.Column("mandate_remaining_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_currency", sa.String(3), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_frequency", sa.String(16), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_max_charges", sa.Integer(), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_valid_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_renews_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "merchant_authorizations", sa.Column("mandate_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        "merchant_authorizations_prava_mandate_id_unique",
        "merchant_authorizations",
        ["prava_mandate_id"],
    )
    op.create_table(
        "mandate_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("merchant_authorization_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("previous_status", sa.String(length=24), nullable=True),
        sa.Column("resulting_status", sa.String(length=24), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["merchant_authorization_id"], ["merchant_authorizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mandate_events_merchant_authorization_id"),
        "mandate_events",
        ["merchant_authorization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mandate_events_merchant_authorization_id"), table_name="mandate_events")
    op.drop_table("mandate_events")
    op.drop_constraint(
        "merchant_authorizations_prava_mandate_id_unique",
        "merchant_authorizations",
        type_="unique",
    )
    for column in (
        "mandate_synced_at",
        "mandate_renews_at",
        "mandate_valid_until",
        "mandate_max_charges",
        "mandate_frequency",
        "mandate_currency",
        "mandate_remaining_amount",
        "mandate_approved_amount",
        "mandate_status",
        "prava_mandate_id",
        "prava_setup_session_id",
    ):
        op.drop_column("merchant_authorizations", column)
