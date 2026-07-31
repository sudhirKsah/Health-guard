from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Timestamped, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))

    sessions: Mapped[list[SessionToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    beneficiaries: Mapped[list[Beneficiary]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    merchant_authorizations: Mapped[list[MerchantAuthorization]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class Beneficiary(Timestamped, Base):
    __tablename__ = "beneficiaries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    relationship_label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner: Mapped[User] = relationship(back_populates="beneficiaries")
    supplies: Mapped[list[Supply]] = relationship(
        back_populates="beneficiary", cascade="all, delete-orphan"
    )


class Supply(Timestamped, Base):
    __tablename__ = "supplies"
    __table_args__ = (
        CheckConstraint("daily_consumption > 0", name="supply_daily_consumption_positive"),
        CheckConstraint("quantity_on_hand >= 0", name="supply_quantity_nonnegative"),
        CheckConstraint("safety_buffer_quantity >= 0", name="supply_safety_buffer_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    beneficiary_id: Mapped[UUID] = mapped_column(
        ForeignKey("beneficiaries.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    daily_consumption: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    safety_buffer_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    beneficiary: Mapped[Beneficiary] = relationship(back_populates="supplies")
    equivalence_sets: Mapped[list[ProductEquivalenceSet]] = relationship(
        back_populates="supply", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="supply", cascade="all, delete-orphan"
    )


class MerchantAuthorization(Timestamped, Base):
    __tablename__ = "merchant_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "merchant_key", name="merchant_authorization_owner_key_unique"
        ),
        CheckConstraint("preference_rank > 0", name="merchant_authorization_rank_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant_key: Mapped[str] = mapped_column(String(40), nullable=False)
    merchant_name: Mapped[str] = mapped_column(String(120), nullable=False)
    merchant_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    preference_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Prava never returns card credentials as part of mandate management. These fields are
    # deliberately limited to the owner-approved mandate's safe control-plane state.
    prava_setup_session_id: Mapped[str | None] = mapped_column(String(255))
    prava_mandate_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    mandate_status: Mapped[str | None] = mapped_column(String(24))
    mandate_approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mandate_remaining_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mandate_currency: Mapped[str | None] = mapped_column(String(3))
    mandate_frequency: Mapped[str | None] = mapped_column(String(16))
    mandate_max_charges: Mapped[int | None] = mapped_column(Integer)
    health_guard_stop_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mandate_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mandate_renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mandate_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="merchant_authorizations")
    approved_variants: Mapped[list[ApprovedVariant]] = relationship(
        back_populates="merchant_authorization"
    )
    mandate_events: Mapped[list[MandateEvent]] = relationship(
        back_populates="merchant_authorization", cascade="all, delete-orphan"
    )
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(
        back_populates="merchant_authorization"
    )


class MandateEvent(Base):
    """Append-only, credential-free record of a mandate control-plane action."""

    __tablename__ = "mandate_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    merchant_authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchant_authorizations.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(24))
    resulting_status: Mapped[str | None] = mapped_column(String(24))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    merchant_authorization: Mapped[MerchantAuthorization] = relationship(
        back_populates="mandate_events"
    )


class ProductEquivalenceSet(Timestamped, Base):
    __tablename__ = "product_equivalence_sets"
    __table_args__ = (
        UniqueConstraint("supply_id", "name", name="equivalence_set_supply_name_unique"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    supply_id: Mapped[UUID] = mapped_column(
        ForeignKey("supplies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    supply: Mapped[Supply] = relationship(back_populates="equivalence_sets")
    approved_variants: Mapped[list[ApprovedVariant]] = relationship(
        back_populates="equivalence_set", cascade="all, delete-orphan"
    )


class ApprovedVariant(Timestamped, Base):
    __tablename__ = "approved_variants"
    __table_args__ = (
        CheckConstraint("pack_quantity > 0", name="approved_variant_pack_quantity_positive"),
        UniqueConstraint(
            "equivalence_set_id",
            "merchant_authorization_id",
            "merchant_product_id",
            "merchant_variant_id",
            name="approved_variant_exact_identity_unique",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    equivalence_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_equivalence_sets.id", ondelete="CASCADE"), index=True
    )
    merchant_authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchant_authorizations.id", ondelete="RESTRICT"), index=True
    )
    merchant_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant_variant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    pack_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    pack_unit: Mapped[str] = mapped_column(String(40), nullable=False)

    equivalence_set: Mapped[ProductEquivalenceSet] = relationship(
        back_populates="approved_variants"
    )
    merchant_authorization: Mapped[MerchantAuthorization] = relationship(
        back_populates="approved_variants"
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("owner_id", "trigger_id", name="agent_run_owner_trigger_unique"),
        CheckConstraint("days_until_stockout >= 0", name="agent_run_days_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    supply_id: Mapped[UUID] = mapped_column(
        ForeignKey("supplies.id", ondelete="CASCADE"), index=True
    )
    trigger_id: Mapped[str] = mapped_column(String(128), nullable=False)
    goal: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(24))
    explanation: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    days_until_stockout: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    projected_stockout_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="agent_runs")
    supply: Mapped[Supply] = relationship(back_populates="agent_runs")
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        order_by="AgentStep.sequence",
    )
    offer_snapshots: Mapped[list[OfferSnapshot]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        order_by="OfferSnapshot.created_at",
    )
    purchase_order: Mapped[PurchaseOrder | None] = relationship(back_populates="agent_run")


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="agent_step_run_sequence_unique"),
        CheckConstraint("sequence > 0", name="agent_step_sequence_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    input_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    agent_run: Mapped[AgentRun] = relationship(back_populates="steps")


class OfferSnapshot(Base):
    """A safe, normalized observation of a UCP product/quote; never a payment credential."""

    __tablename__ = "offer_snapshots"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="offer_snapshot_unit_price_nonnegative"),
        CheckConstraint("shipping_price >= 0", name="offer_snapshot_shipping_price_nonnegative"),
        CheckConstraint("landed_price >= 0", name="offer_snapshot_landed_price_nonnegative"),
        CheckConstraint(
            "estimated_arrival_days IS NULL OR estimated_arrival_days >= 0",
            name="offer_snapshot_arrival_days_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    merchant_authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchant_authorizations.id", ondelete="RESTRICT"), index=True
    )
    merchant_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant_variant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_title: Mapped[str] = mapped_column(String(500), nullable=False)
    variant_title: Mapped[str | None] = mapped_column(String(500))
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    landed_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    estimated_arrival_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    quote_id: Mapped[str | None] = mapped_column(String(255))
    quote_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    agent_run: Mapped[AgentRun] = relationship(back_populates="offer_snapshots")
    merchant_authorization: Mapped[MerchantAuthorization] = relationship()


class PurchaseOrder(Timestamped, Base):
    """An idempotent, credential-free record of a proposed or completed replenishment order.

    One row belongs to one agent run. The Prava charge reference is retained so a retry can ask
    Prava for the same charge, but network-token credentials are never persisted.
    """

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("agent_run_id", name="purchase_order_agent_run_unique"),
        UniqueConstraint("charge_reference", name="purchase_order_charge_reference_unique"),
        CheckConstraint("requested_amount > 0", name="purchase_order_requested_amount_positive"),
        CheckConstraint(
            "charged_amount IS NULL OR charged_amount > 0",
            name="purchase_order_charged_amount_positive",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    merchant_authorization_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchant_authorizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    charge_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    charged_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared")
    prava_mandate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    prava_transaction_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    prava_order_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    merchant_order_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    report_status: Mapped[str | None] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    charged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkout_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="purchase_orders")
    agent_run: Mapped[AgentRun] = relationship(back_populates="purchase_order")
    merchant_authorization: Mapped[MerchantAuthorization] = relationship(
        back_populates="purchase_orders"
    )
