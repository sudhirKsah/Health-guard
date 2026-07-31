from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, get_settings

MERCHANT_UCP_ENDPOINTS = {
    "himalaya": "https://himalaya-wellness-india.myshopify.com/api/ucp/mcp",
    "oziva": "https://oziva.myshopify.com/api/ucp/mcp",
}


@dataclass(frozen=True)
class UcpReadiness:
    ready: bool
    reason: str | None = None


@dataclass(frozen=True)
class UcpVariant:
    product_id: str
    product_title: str
    variant_id: str
    variant_title: str | None
    available: bool
    currency: str
    unit_price: Decimal


@dataclass(frozen=True)
class UcpQuote:
    quote_id: str
    currency: str
    landed_price: Decimal
    expires_at: datetime | None
    status: str
    requires_delivery_address: bool


class UcpConfigurationError(RuntimeError):
    """Direct UCP cannot run until Health Guard's own public profile is configured."""


class UcpMerchantError(RuntimeError):
    """Safe merchant/UCP failure: raw response bodies and continuation URLs are never retained."""


class UcpAdapter:
    """Server-only, real Shopify UCP adapter for search, product lookup, and initial quotes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def profile_url(self) -> str | None:
        return (
            str(self._settings.health_guard_ucp_profile_url)
            if self._settings.health_guard_ucp_profile_url
            else None
        )

    def readiness(self) -> UcpReadiness:
        if self.profile_url is None:
            return UcpReadiness(False, "health_guard_ucp_profile_url_not_configured")
        if not self.profile_url.startswith("https://"):
            return UcpReadiness(False, "health_guard_ucp_profile_url_must_use_https")
        return UcpReadiness(True)

    def search(self, *, merchant_key: str, query: str) -> list[UcpVariant]:
        content = self._call(
            merchant_key,
            "search_catalog",
            {
                "catalog": {
                    "query": query,
                    "context": {"address_country": "IN", "currency": "INR"},
                    "pagination": {"limit": 25},
                }
            },
        )
        variants: list[UcpVariant] = []
        for product in content.get("products", []):
            variants.extend(self._variants_from_product(product))
        return variants

    def get_product(self, *, merchant_key: str, product_id: str) -> list[UcpVariant]:
        content = self._call(
            merchant_key,
            "get_product",
            {
                "catalog": {
                    "id": product_id,
                    "context": {"address_country": "IN", "currency": "INR"},
                }
            },
        )
        product = content.get("product")
        if not isinstance(product, dict):
            raise UcpMerchantError("product_not_returned")
        return self._variants_from_product(product)

    def quote_variant(self, *, merchant_key: str, variant_id: str) -> UcpQuote:
        """Create an unpaid initial checkout. Call only with a real delivery workflow in later phases."""
        content = self._call(
            merchant_key,
            "create_checkout",
            {
                "checkout": {
                    "line_items": [{"item": {"id": variant_id}, "quantity": 1}],
                    "context": {"address_country": "IN", "currency": "INR"},
                }
            },
        )
        quote_id = sanitize_identifier(str(content.get("id", "")))
        if not quote_id:
            raise UcpMerchantError("quote_identifier_not_returned")
        total = next(
            (item for item in content.get("totals", []) if item.get("type") == "total"), None
        )
        if not isinstance(total, dict) or not isinstance(total.get("amount"), int):
            raise UcpMerchantError("quote_total_not_returned")
        message_codes = {
            message.get("code")
            for message in content.get("messages", [])
            if isinstance(message, dict)
        }
        return UcpQuote(
            quote_id=quote_id,
            currency=str(content.get("currency", "INR")),
            landed_price=minor_to_major(total["amount"]),
            expires_at=parse_timestamp(content.get("expires_at")),
            status=str(content.get("status", "unknown")),
            requires_delivery_address="delivery_address_required" in message_codes,
        )

    def _call(
        self, merchant_key: str, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        profile = self._require_ready()
        endpoint = MERCHANT_UCP_ENDPOINTS.get(merchant_key)
        if endpoint is None:
            raise UcpConfigurationError("merchant_ucp_endpoint_not_configured")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"meta": {"ucp-agent": {"profile": profile}}, **arguments},
            },
        }
        try:
            response = httpx.post(
                endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=25
            )
            response.raise_for_status()
            payload_out = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise UcpMerchantError("merchant_ucp_unavailable") from error
        if "error" in payload_out:
            raise UcpMerchantError("merchant_ucp_tool_error")
        result = payload_out.get("result")
        if not isinstance(result, dict):
            raise UcpMerchantError("merchant_ucp_invalid_response")
        content = result.get("structuredContent")
        if isinstance(content, dict):
            return content
        for item in result.get("content", []):
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                try:
                    parsed = json.loads(item["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        raise UcpMerchantError("merchant_ucp_content_not_returned")

    def _require_ready(self) -> str:
        readiness = self.readiness()
        if not readiness.ready:
            raise UcpConfigurationError(readiness.reason or "ucp_not_ready")
        return self.profile_url or ""

    @staticmethod
    def _variants_from_product(product: object) -> list[UcpVariant]:
        if not isinstance(product, dict):
            return []
        product_id = product.get("id")
        product_title = product.get("title")
        if not isinstance(product_id, str) or not isinstance(product_title, str):
            return []
        variants: list[UcpVariant] = []
        for variant in product.get("variants", []):
            if not isinstance(variant, dict) or not isinstance(variant.get("id"), str):
                continue
            price = variant.get("price")
            availability = variant.get("availability")
            if not isinstance(price, dict) or not isinstance(price.get("amount"), int):
                continue
            variants.append(
                UcpVariant(
                    product_id=product_id,
                    product_title=product_title,
                    variant_id=variant["id"],
                    variant_title=variant.get("title")
                    if isinstance(variant.get("title"), str)
                    else None,
                    available=bool(availability.get("available"))
                    if isinstance(availability, dict)
                    else False,
                    currency=str(price.get("currency", "INR")),
                    unit_price=minor_to_major(price["amount"]),
                )
            )
        return variants


def minor_to_major(amount: int) -> Decimal:
    return (Decimal(amount) / Decimal("100")).quantize(Decimal("0.01"))


def sanitize_identifier(value: str) -> str:
    parts = urlsplit(value)
    return (
        urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if parts.scheme
        else value.split("?", 1)[0]
    )


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
