from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.agent.policy import ApprovedVariantPolicy, OfferCandidate, choose_offer, project_stock
from app.agent.state import AgentState, validate_transition
from app.agent.tools import CatalogSearchTool, InventoryTool
from app.config import Settings
from app.integrations.ucp import UcpAdapter
from app.mandate_cycles import mandate_charge_window
from app.models import Supply


def approval(*, enabled: bool = True, rank: int = 1, **overrides: object) -> ApprovedVariantPolicy:
    values: dict[str, object] = {
        "merchant_authorization_id": "merchant-a",
        "merchant_product_id": "product-a",
        "merchant_variant_id": "variant-a",
        "merchant_is_enabled": enabled,
        "merchant_preference_rank": rank,
        "mandate_status": "active",
        "mandate_approved_amount": Decimal("600"),
        "mandate_remaining_amount": Decimal("600"),
        "mandate_valid_until": datetime.now(UTC) + timedelta(days=1),
    }
    values.update(overrides)
    return ApprovedVariantPolicy(**values)  # type: ignore[arg-type]


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


def test_inventory_tool_accounts_for_consumption_since_the_last_observation() -> None:
    supply = Supply(
        name="Test tablets",
        unit="tablet",
        daily_consumption=Decimal("2"),
        quantity_on_hand=Decimal("10"),
        safety_buffer_quantity=Decimal("8"),
        inventory_observed_at=datetime.now(UTC) - timedelta(days=1),
    )

    projection, result = InventoryTool().run(supply)

    assert projection.reorder_required is True
    assert Decimal(str(result.summary["estimated_quantity_now"])) <= Decimal("8")


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
            mandate_status="active",
            mandate_approved_amount=Decimal("600"),
            mandate_remaining_amount=Decimal("600"),
            mandate_valid_until=datetime.now(UTC) + timedelta(days=1),
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
            mandate_status="active",
            mandate_approved_amount=Decimal("600"),
            mandate_remaining_amount=Decimal("600"),
            mandate_valid_until=datetime.now(UTC) + timedelta(days=1),
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


def test_policy_blocks_inactive_or_over_cap_mandates() -> None:
    inactive = choose_offer(
        offers=[offer()],
        approved_variants=[approval(mandate_status="paused")],
        days_until_stockout=Decimal("4"),
    )
    over_cap = choose_offer(
        offers=[offer()],
        approved_variants=[approval(mandate_approved_amount=Decimal("449"))],
        days_until_stockout=Decimal("4"),
    )

    assert inactive.rejected[0].reason == "mandate_not_active"
    assert over_cap.rejected[0].reason == "mandate_amount_cap_exceeded"


def test_policy_rejects_offer_before_next_mandate_cycle() -> None:
    decision = choose_offer(
        offers=[offer()],
        approved_variants=[
            approval(mandate_next_charge_at=datetime.now(UTC) + timedelta(days=10))
        ],
        days_until_stockout=Decimal("4"),
    )

    assert decision.selected is None
    assert decision.rejected[0].reason == "mandate_frequency_wait"


def test_monthly_mandate_waits_until_prava_cycle_boundary_after_approved_charge() -> None:
    now = datetime(2026, 8, 20, 9, tzinfo=UTC)
    renewal = datetime(2026, 9, 2, 12, tzinfo=UTC)

    window = mandate_charge_window(
        frequency="monthly",
        renews_at=renewal,
        last_charge_at=datetime(2026, 8, 3, 8, tzinfo=UTC),
        last_charge_status="APPROVED",
        observed_at=now,
    )

    assert window.eligible is False
    assert window.reason == "mandate_frequency_wait"
    assert window.next_eligible_at == renewal


def test_stale_renewal_anchor_advances_and_allows_a_new_cycle() -> None:
    window = mandate_charge_window(
        frequency="monthly",
        renews_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
        last_charge_at=datetime(2026, 6, 10, 8, tzinfo=UTC),
        last_charge_status="APPROVED",
        observed_at=datetime(2026, 8, 20, 9, tzinfo=UTC),
    )

    assert window.eligible is True


def test_legacy_synced_remaining_amount_blocks_without_local_last_charge() -> None:
    renewal = datetime(2026, 9, 2, 12, tzinfo=UTC)
    window = mandate_charge_window(
        frequency="monthly",
        renews_at=renewal,
        last_charge_at=None,
        last_charge_status=None,
        approved_amount=Decimal("600"),
        remaining_amount=Decimal("150"),
        observed_at=datetime(2026, 8, 20, 9, tzinfo=UTC),
    )

    assert window.eligible is False
    assert window.next_eligible_at == renewal


def test_weekly_and_yearly_mandates_also_allow_only_one_charge_per_cycle() -> None:
    cases = [
        (
            "weekly",
            datetime(2026, 8, 9, 12, tzinfo=UTC),
            datetime(2026, 8, 3, 8, tzinfo=UTC),
            datetime(2026, 8, 5, 9, tzinfo=UTC),
        ),
        (
            "yearly",
            datetime(2027, 8, 2, 12, tzinfo=UTC),
            datetime(2026, 8, 3, 8, tzinfo=UTC),
            datetime(2026, 12, 1, 9, tzinfo=UTC),
        ),
    ]

    for frequency, renewal, last_charge, now in cases:
        window = mandate_charge_window(
            frequency=frequency,
            renews_at=renewal,
            last_charge_at=last_charge,
            last_charge_status="APPROVED",
            observed_at=now,
        )
        assert window.eligible is False
        assert window.next_eligible_at == renewal


def test_catalog_tool_blocks_without_a_health_guard_profile_instead_of_returning_fake_offers() -> (
    None
):
    result, offers = CatalogSearchTool(UcpAdapter(Settings(health_guard_ucp_profile_url=None))).run(
        query="ashwagandha",
        configured_variants=[],
    )

    assert result.status == "blocked"
    assert result.summary["reason"] == "health_guard_ucp_profile_url_not_configured"
    assert offers == []


def test_agent_state_machine_disallows_skipping_from_observe_to_payment() -> None:
    try:
        validate_transition(AgentState.OBSERVE, AgentState.ACT)
    except ValueError:
        pass
    else:
        raise AssertionError("The agent must not skip discovery and decision before acting")
