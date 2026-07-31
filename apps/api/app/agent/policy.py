from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

POLICY_VERSION = "phase3-v1"


@dataclass(frozen=True)
class StockProjection:
    days_until_stockout: Decimal
    days_until_safety_buffer: Decimal
    projected_stockout_at: datetime
    reorder_required: bool


def project_stock(
    *,
    quantity_on_hand: Decimal,
    daily_consumption: Decimal,
    safety_buffer_quantity: Decimal,
    observed_at: datetime | None = None,
) -> StockProjection:
    if daily_consumption <= 0:
        raise ValueError("Daily consumption must be positive")
    if quantity_on_hand < 0 or safety_buffer_quantity < 0:
        raise ValueError("Inventory quantities cannot be negative")
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    days_until_stockout = quantity_on_hand / daily_consumption
    days_until_safety_buffer = (
        max(Decimal("0"), quantity_on_hand - safety_buffer_quantity) / daily_consumption
    )
    return StockProjection(
        days_until_stockout=days_until_stockout,
        days_until_safety_buffer=days_until_safety_buffer,
        projected_stockout_at=now + timedelta(days=float(days_until_stockout)),
        reorder_required=quantity_on_hand <= safety_buffer_quantity,
    )


@dataclass(frozen=True)
class ApprovedVariantPolicy:
    merchant_authorization_id: str
    merchant_product_id: str
    merchant_variant_id: str
    merchant_is_enabled: bool
    merchant_preference_rank: int


@dataclass(frozen=True)
class OfferCandidate:
    merchant_authorization_id: str
    merchant_product_id: str
    merchant_variant_id: str
    available: bool
    landed_price: Decimal
    arrival_days: Decimal | None


@dataclass(frozen=True)
class RejectedOffer:
    offer: OfferCandidate
    reason: str


@dataclass(frozen=True)
class OfferDecision:
    selected: OfferCandidate | None
    rejected: tuple[RejectedOffer, ...]


def choose_offer(
    *,
    offers: list[OfferCandidate],
    approved_variants: list[ApprovedVariantPolicy],
    days_until_stockout: Decimal,
) -> OfferDecision:
    """Choose only a configured exact variant; ties are stable and explainable."""
    approvals = {
        (
            variant.merchant_authorization_id,
            variant.merchant_product_id,
            variant.merchant_variant_id,
        ): variant
        for variant in approved_variants
    }
    eligible: list[tuple[OfferCandidate, ApprovedVariantPolicy]] = []
    rejected: list[RejectedOffer] = []
    for offer in offers:
        approval = approvals.get(
            (offer.merchant_authorization_id, offer.merchant_product_id, offer.merchant_variant_id)
        )
        if approval is None:
            rejected.append(RejectedOffer(offer, "not_an_exact_approved_variant"))
        elif not approval.merchant_is_enabled:
            rejected.append(RejectedOffer(offer, "merchant_authorization_paused"))
        elif not offer.available:
            rejected.append(RejectedOffer(offer, "unavailable"))
        elif offer.arrival_days is None:
            rejected.append(RejectedOffer(offer, "arrival_estimate_missing"))
        elif offer.arrival_days > days_until_stockout:
            rejected.append(RejectedOffer(offer, "arrives_after_projected_stockout"))
        else:
            eligible.append((offer, approval))
    eligible.sort(
        key=lambda item: (
            item[0].landed_price,
            item[0].arrival_days,
            item[1].merchant_preference_rank,
            item[0].merchant_authorization_id,
            item[0].merchant_product_id,
            item[0].merchant_variant_id,
        )
    )
    return OfferDecision(selected=eligible[0][0] if eligible else None, rejected=tuple(rejected))
