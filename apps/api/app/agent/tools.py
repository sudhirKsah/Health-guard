from __future__ import annotations

from dataclasses import dataclass

from app.agent.policy import StockProjection, project_stock
from app.integrations.ucp import UcpAdapter
from app.models import Supply


@dataclass(frozen=True)
class ToolResult:
    status: str
    summary: dict[str, object]


class InventoryTool:
    name = "get_supply_status"

    def run(self, supply: Supply) -> tuple[StockProjection, ToolResult]:
        projection = project_stock(
            quantity_on_hand=supply.quantity_on_hand,
            daily_consumption=supply.daily_consumption,
            safety_buffer_quantity=supply.safety_buffer_quantity,
        )
        return projection, ToolResult(
            status="success",
            summary={
                "supply_id": str(supply.id),
                "quantity_on_hand": str(supply.quantity_on_hand),
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

    def run(self, *, approved_variant_count: int) -> ToolResult:
        readiness = self._ucp.readiness()
        if not readiness.ready:
            return ToolResult(
                status="blocked",
                summary={
                    "reason": readiness.reason or "ucp_not_ready",
                    "approved_variant_count": approved_variant_count,
                },
            )
        if approved_variant_count == 0:
            return ToolResult(
                status="blocked",
                summary={
                    "reason": "no_exact_approved_variant_configured",
                    "approved_variant_count": 0,
                },
            )
        return ToolResult(
            status="blocked",
            summary={
                "reason": "live_ucp_transport_pending_profile_validation",
                "approved_variant_count": approved_variant_count,
            },
        )
