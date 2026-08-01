from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import is_valid_prava_email, normalize_email


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        email = normalize_email(value)
        if not is_valid_prava_email(email):
            raise ValueError("A valid email address is required")
        return email


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        email = normalize_email(value)
        if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
            raise ValueError("A valid email address is required")
        return email


class UserOut(ApiModel):
    id: UUID
    email: str
    display_name: str | None


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class BeneficiaryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    relationship_label: str = Field(min_length=1, max_length=80)


class BeneficiaryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    relationship_label: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None


class BeneficiaryOut(ApiModel):
    id: UUID
    name: str
    relationship_label: str
    is_active: bool


class SupplyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(min_length=1, max_length=40)
    daily_consumption: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    quantity_on_hand: Decimal = Field(ge=0, max_digits=12, decimal_places=3)
    safety_buffer_quantity: Decimal = Field(ge=0, max_digits=12, decimal_places=3)


class SupplyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    daily_consumption: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    quantity_on_hand: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=3)
    safety_buffer_quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=3
    )
    is_enabled: bool | None = None


class SupplyOut(ApiModel):
    id: UUID
    beneficiary_id: UUID
    name: str
    unit: str
    daily_consumption: Decimal
    quantity_on_hand: Decimal
    safety_buffer_quantity: Decimal
    is_enabled: bool


class MerchantAuthorizationCreate(BaseModel):
    merchant_key: str = Field(pattern="^(himalaya|oziva|zandu)$")
    preference_rank: int = Field(ge=1, le=99)


class MerchantAuthorizationUpdate(BaseModel):
    preference_rank: int | None = Field(default=None, ge=1, le=99)
    is_enabled: bool | None = None


class MerchantAuthorizationOut(ApiModel):
    id: UUID
    merchant_key: str
    merchant_name: str
    merchant_domain: str
    preference_rank: int
    is_enabled: bool
    prava_mandate_id: str | None
    mandate_status: str | None
    mandate_approved_amount: Decimal | None
    mandate_remaining_amount: Decimal | None
    mandate_currency: str | None
    mandate_frequency: str | None
    mandate_max_charges: int | None
    health_guard_stop_after: datetime | None
    mandate_valid_until: datetime | None
    mandate_renews_at: datetime | None
    mandate_synced_at: datetime | None


class MandateSetupRequest(BaseModel):
    approved_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")
    recurring_frequency: str = Field(default="monthly", pattern="^(weekly|monthly|yearly)$")
    max_charges: int = Field(default=12, ge=1, le=104)
    valid_until: datetime


class MandateSetupSessionOut(BaseModel):
    merchant_authorization: MerchantAuthorizationOut
    iframe_url: str
    expires_at: datetime | None


class MandateActionRequest(BaseModel):
    confirmed: bool


class MandateEventOut(ApiModel):
    id: UUID
    event_type: str
    previous_status: str | None
    resulting_status: str | None
    details: dict[str, object]
    created_at: datetime


class EquivalenceSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    notes: str | None = Field(default=None, max_length=1000)


class EquivalenceSetOut(ApiModel):
    id: UUID
    supply_id: UUID
    name: str
    notes: str | None


class ApprovedVariantCreate(BaseModel):
    merchant_authorization_id: UUID
    merchant_product_id: str = Field(min_length=1, max_length=255)
    merchant_variant_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    pack_quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    pack_unit: str = Field(min_length=1, max_length=40)


class ApprovedVariantOut(ApiModel):
    id: UUID
    equivalence_set_id: UUID
    merchant_authorization_id: UUID
    merchant_product_id: str
    merchant_variant_id: str
    display_name: str
    pack_quantity: Decimal
    pack_unit: str


class EquivalenceSetDashboard(EquivalenceSetOut):
    approved_variants: list[ApprovedVariantOut]


class SupplyDashboard(SupplyOut):
    equivalence_sets: list[EquivalenceSetDashboard]


class BeneficiaryDashboard(BeneficiaryOut):
    supplies: list[SupplyDashboard]


class SetupDashboard(BaseModel):
    beneficiaries: list[BeneficiaryDashboard]
    merchant_authorizations: list[MerchantAuthorizationOut]


class AgentRunCreate(BaseModel):
    trigger_id: str | None = Field(default=None, min_length=1, max_length=128)


class AgentRunScheduleRequest(BaseModel):
    run_at: datetime


class AgentRunScheduleOut(BaseModel):
    job_id: str
    run_at: datetime


class AgentStepOut(ApiModel):
    id: UUID
    sequence: int
    stage: str
    tool_name: str
    status: str
    input_summary: dict[str, object]
    output_summary: dict[str, object]
    created_at: datetime


class OfferSnapshotOut(ApiModel):
    id: UUID
    merchant_authorization_id: UUID
    merchant_product_id: str
    merchant_variant_id: str
    product_title: str
    variant_title: str | None
    available: bool
    currency: str
    unit_price: Decimal
    shipping_price: Decimal
    landed_price: Decimal
    estimated_arrival_days: Decimal | None
    quote_id: str | None
    quote_expires_at: datetime | None
    source_status: str
    created_at: datetime


class PurchaseOrderOut(ApiModel):
    id: UUID
    merchant_authorization_id: UUID
    charge_reference: str
    requested_amount: Decimal
    charged_amount: Decimal | None
    currency: str
    status: str
    prava_mandate_id: str
    prava_transaction_id: str | None
    prava_order_id: str | None
    merchant_order_id: str | None
    report_status: str | None
    failure_code: str | None
    charged_at: datetime | None
    checkout_completed_at: datetime | None
    reported_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRunOut(ApiModel):
    id: UUID
    supply_id: UUID
    trigger_id: str
    goal: str
    state: str
    status: str
    outcome: str | None
    explanation: str | None
    policy_version: str
    days_until_stockout: Decimal
    projected_stockout_at: datetime
    created_at: datetime
    completed_at: datetime | None
    steps: list[AgentStepOut]
    offer_snapshots: list[OfferSnapshotOut]
    purchase_order: PurchaseOrderOut | None


class AgentRunStartOut(BaseModel):
    run: AgentRunOut
    reused: bool


class LedgerEventOut(ApiModel):
    id: UUID
    event_type: str
    title: str
    detail: str
    severity: str
    agent_run_id: UUID | None
    supply_id: UUID | None
    purchase_order_id: UUID | None
    metadata_safe: dict[str, object]
    read_at: datetime | None
    created_at: datetime
