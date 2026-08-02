from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.agent.policy import StockProjection, project_stock
from app.integrations.ucp import UcpAdapter, UcpConfigurationError, UcpMerchantError
from app.inventory import estimated_quantity
from app.models import Supply


@dataclass(frozen=True)
class ToolResult:
    status: str
    summary: dict[str, object]


@dataclass(frozen=True)
class ConfiguredVariant:
    merchant_authorization_id: UUID
    merchant_key: str
    merchant_product_id: str
    merchant_variant_id: str


@dataclass(frozen=True)
class DiscoveredOffer:
    merchant_authorization_id: UUID
    merchant_product_id: str
    merchant_variant_id: str
    product_title: str
    variant_title: str | None
    available: bool
    currency: str
    unit_price: Decimal


class InventoryTool:
    name = "get_supply_status"

    def run(self, supply: Supply) -> tuple[StockProjection, ToolResult]:
        now = datetime.now(UTC)
        observed_at = supply.inventory_observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        current_quantity = estimated_quantity(supply, at=now)
        projection = project_stock(
            quantity_on_hand=current_quantity,
            daily_consumption=supply.daily_consumption,
            safety_buffer_quantity=supply.safety_buffer_quantity,
            observed_at=now,
        )
        return projection, ToolResult(
            status="success",
            summary={
                "supply_id": str(supply.id),
                "quantity_on_hand": str(supply.quantity_on_hand),
                "estimated_quantity_now": str(current_quantity),
                "inventory_observed_at": observed_at.isoformat(),
                "unit": supply.unit,
                "daily_consumption": str(supply.daily_consumption),
                "safety_buffer_quantity": str(supply.safety_buffer_quantity),
                "days_until_stockout": str(projection.days_until_stockout),
                "days_until_safety_buffer": str(projection.days_until_safety_buffer),
                "reorder_required": projection.reorder_required,
            },
        )


class CatalogSearchTool:
    """Honest UCP boundary: no fabricated catalog or quote responses are permitted."""

    name = "search_products"

    def __init__(self, ucp: UcpAdapter | None = None) -> None:
        self._ucp = ucp or UcpAdapter()

    def run(
        self, *, query: str, configured_variants: list[ConfiguredVariant]
    ) -> tuple[ToolResult, list[DiscoveredOffer]]:
        readiness = self._ucp.readiness()
        if not readiness.ready:
            return ToolResult(
                status="blocked",
                summary={
                    "reason": readiness.reason or "ucp_not_ready",
                    "approved_variant_count": len(configured_variants),
                },
            ), []
        if not configured_variants:
            return ToolResult(
                status="blocked",
                summary={
                    "reason": "no_exact_approved_variant_configured",
                    "approved_variant_count": 0,
                },
            ), []
        offers: list[DiscoveredOffer] = []
        merchant_errors: list[str] = []
        by_merchant: dict[str, list[ConfiguredVariant]] = {}
        for configured in configured_variants:
            by_merchant.setdefault(configured.merchant_key, []).append(configured)
        for merchant_key, configured_for_merchant in by_merchant.items():
            try:
                live_variants = self._ucp.search(merchant_key=merchant_key, query=query)
                # Product lookup is a required second live read; it refreshes the selected product before
                # an offer is persisted, even though search already returns partial variants.
                product_ids = {
                    item.product_id
                    for item in live_variants
                    if any(
                        item.product_id == configured.merchant_product_id
                        for configured in configured_for_merchant
                    )
                }
                # Search results can contain partial variant information. Persist offers only from
                # the product lookup refresh, where available, rather than treating the lookup as
                # a no-op.
                live_by_identity = {
                    (item.product_id, item.variant_id): item for item in live_variants
                }
                for product_id in product_ids:
                    for refreshed in self._ucp.get_product(
                        merchant_key=merchant_key, product_id=product_id
                    ):
                        live_by_identity[(refreshed.product_id, refreshed.variant_id)] = refreshed
                for live in live_by_identity.values():
                    for configured in configured_for_merchant:
                        if (
                            live.product_id == configured.merchant_product_id
                            and live.variant_id == configured.merchant_variant_id
                        ):
                            offers.append(
                                DiscoveredOffer(
                                    merchant_authorization_id=configured.merchant_authorization_id,
                                    merchant_product_id=live.product_id,
                                    merchant_variant_id=live.variant_id,
                                    product_title=live.product_title,
                                    variant_title=live.variant_title,
                                    available=live.available,
                                    currency=live.currency,
                                    unit_price=live.unit_price,
                                )
                            )
            except (UcpConfigurationError, UcpMerchantError) as error:
                merchant_errors.append(f"{merchant_key}:{error}")
        return ToolResult(
            status="success" if offers else "blocked",
            summary={
                "approved_variant_count": len(configured_variants),
                "exact_live_offer_count": len(offers),
                "merchant_error_count": len(merchant_errors),
                "merchant_errors": merchant_errors,
            },
        ), offers
