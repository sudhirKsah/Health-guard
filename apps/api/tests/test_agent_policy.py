from datetime import UTC, datetime
from decimal import Decimal

from app.agent.policy import ApprovedVariantPolicy, OfferCandidate, choose_offer, project_stock
from app.agent.state import AgentState, validate_transition
from app.agent.tools import CatalogSearchTool


def approval(*, enabled: bool = True, rank: int = 1) -> ApprovedVariantPolicy:
    return ApprovedVariantPolicy(
        merchant_authorization_id="merchant-a",
        merchant_product_id="product-a",
        merchant_variant_id="variant-a",
        merchant_is_enabled=enabled,
        merchant_preference_rank=rank,
    )


def offer(**overrides: object) -> OfferCandidate:
    values: dict[str, object] = {
        "merchant_authorization_id": "merchant-a",
        "merchant_product_id": "product-a",
        "merchant_variant_id": "variant-a",
        "available": True,
        "landed_price": Decimal("450"),
        "arrival_days": Decimal("2"),
    }
    values.update(overrides)
    return OfferCandidate(**values)  # type: ignore[arg-type]


def test_stock_projection_reorders_at_safety_buffer() -> None:
    projection = project_stock(
        quantity_on_hand=Decimal("8"),
        daily_consumption=Decimal("2"),
        safety_buffer_quantity=Decimal("8"),
        observed_at=datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert projection.days_until_stockout == Decimal("4")
    assert projection.days_until_safety_buffer == Decimal("0")
    assert projection.reorder_required is True


def test_policy_rejects_late_offer_and_selects_eligible_exact_variant() -> None:
    late = offer(arrival_days=Decimal("5"))
    eligible = offer(merchant_variant_id="variant-b", landed_price=Decimal("500"))
    policies = [
        approval(),
        ApprovedVariantPolicy(
            merchant_authorization_id="merchant-a",
            merchant_product_id="product-a",
            merchant_variant_id="variant-b",
            merchant_is_enabled=True,
            merchant_preference_rank=1,
        ),
    ]

    decision = choose_offer(
        offers=[late, eligible], approved_variants=policies, days_until_stockout=Decimal("4")
    )

    assert decision.selected == eligible
    assert decision.rejected[0].reason == "arrives_after_projected_stockout"


def test_policy_uses_merchant_preference_for_price_and_arrival_tie() -> None:
    first = offer(merchant_authorization_id="merchant-b")
    second = offer(merchant_authorization_id="merchant-a")
    policies = [
        approval(rank=2),
        ApprovedVariantPolicy(
            merchant_authorization_id="merchant-b",
            merchant_product_id="product-a",
            merchant_variant_id="variant-a",
            merchant_is_enabled=True,
            merchant_preference_rank=1,
        ),
    ]

    decision = choose_offer(
        offers=[second, first], approved_variants=policies, days_until_stockout=Decimal("4")
    )

    assert decision.selected == first


def test_policy_rejects_paused_merchant_and_unapproved_product() -> None:
    paused = offer()
    unapproved = offer(merchant_variant_id="unknown")

    decision = choose_offer(
        offers=[paused, unapproved],
        approved_variants=[approval(enabled=False)],
        days_until_stockout=Decimal("4"),
    )

    assert decision.selected is None
    assert [rejection.reason for rejection in decision.rejected] == [
        "merchant_authorization_paused",
        "not_an_exact_approved_variant",
    ]


def test_catalog_tool_blocks_without_a_health_guard_profile_instead_of_returning_fake_offers() -> (
    None
):
    result = CatalogSearchTool().run(approved_variant_count=1)

    assert result.status == "blocked"
    assert result.summary["reason"] == "health_guard_ucp_profile_url_not_configured"


def test_agent_state_machine_disallows_skipping_from_observe_to_payment() -> None:
    try:
        validate_transition(AgentState.OBSERVE, AgentState.ACT)
    except ValueError:
        pass
    else:
        raise AssertionError("The agent must not skip discovery and decision before acting")
