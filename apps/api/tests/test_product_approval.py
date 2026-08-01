import json
from decimal import Decimal
from types import SimpleNamespace

from pydantic import SecretStr

from app.agent.product_approval import (
    candidate_pack,
    catalog_pack,
    normalize_unit,
    significant_terms,
)
from app.config import Settings
from app.integrations.openai_brain import OpenAIBrain
from app.routers.mandates import default_max_charges
from app.routers.setup import suggestion_matches


class FakeResponses:
    def __init__(self, arguments: dict[str, object]) -> None:
        self.arguments = arguments
        self.request: dict[str, object] | None = None

    def create(self, **kwargs):
        self.request = kwargs
        tool_name = kwargs["tools"][0]["name"]
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name=tool_name,
                    arguments=json.dumps(self.arguments),
                )
            ]
        )


class FakeOpenAI:
    def __init__(self, arguments: dict[str, object]) -> None:
        self.responses = FakeResponses(arguments)


def test_pack_match_requires_the_same_inventory_unit() -> None:
    assert candidate_pack(
        "Septilin tablets 60 tablets", supply_unit="tablet", preferred=Decimal("60")
    ) == (Decimal("60"), "tablet")
    assert candidate_pack(
        "Himalaya Sandal Glow Soap 75g", supply_unit="gram", preferred=None
    ) == (Decimal("75"), "gram")
    assert candidate_pack(
        "Refreshing lotion 100 ml", supply_unit="milliliter", preferred=None
    ) == (Decimal("100"), "milliliter")


def test_catalog_pack_infers_the_recommendation_unit_before_form_selection() -> None:
    assert catalog_pack("Himalaya Sandal Glow Soap 75g") == (Decimal("75"), "gram")
    assert catalog_pack("Himalaya Organic Ashwagandha 60 Caplets") == (
        Decimal("60"),
        "tablet",
    )
    assert (
        candidate_pack(
            "Septilin 60 capsules", supply_unit="tablet", preferred=Decimal("60")
        )
        is None
    )
    assert normalize_unit("Tablets") == "tablet"
    assert candidate_pack(
        "Himalaya Organic Ashwagandha 30 Caplets",
        supply_unit="tablet",
        preferred=None,
    ) == (Decimal("30"), "tablet")
    assert candidate_pack(
        "Himalaya Organic Ashwagandha Pack of 60 30 Caplets",
        supply_unit="tablet",
        preferred=None,
    ) == (Decimal("60"), "tablet")


def test_significant_terms_keep_identity_and_strength() -> None:
    assert significant_terms("Copy the label: Septilin 500 mg tablets") == {
        "septilin",
        "500",
        "mg",
        "tablets",
    }


def test_suggestions_allow_a_typed_prefix_but_require_every_query_term() -> None:
    evidence = "Himalaya Organic Ashwagandha 60 tablets"

    assert suggestion_matches(
        query="ashwa",
        catalog_evidence=evidence,
        merchant_label="himalaya Himalaya Wellness",
    )
    assert not suggestion_matches(
        query="ashwa gummies",
        catalog_evidence=evidence,
        merchant_label="himalaya Himalaya Wellness",
    )


def test_openai_review_is_a_forced_strict_tool_call() -> None:
    fake = FakeOpenAI(
        {
            "safe_to_approve": True,
            "selected_candidate_ids": ["himalaya-1"],
            "summary": "The exact label and pack match.",
            "review_reason": None,
        }
    )
    brain = OpenAIBrain(
        Settings(
            openai_api_key=SecretStr("test-key"),
            openai_model="gpt-5.6-terra",
            openai_reasoning_effort="medium",
        ),
        client=fake,  # type: ignore[arg-type]
    )
    result = brain.review_product_candidates(
        supply_description="Septilin tablets 60 tablets",
        candidates=[
            {
                "candidate_id": "himalaya-1",
                "merchant": "Himalaya Wellness",
                "product_name": "Septilin",
                "variant_name": "60 tablets",
            }
        ],
        deterministic_selection_ids=["himalaya-1"],
        user_allows_any_matching_product=True,
    )
    request = fake.responses.request
    assert request is not None
    assert request["model"] == "gpt-5.6-terra"
    assert request["tool_choice"] == {
        "type": "function",
        "name": "submit_catalog_assessment",
    }
    assert request["parallel_tool_calls"] is False
    assert request["tools"][0]["strict"] is True  # type: ignore[index]
    assert "specific-product preference blank" in request["input"][1]["content"]  # type: ignore[index]
    assert result.safe_to_approve is True
    assert result.selected_candidate_ids == ("himalaya-1",)


def test_default_mandate_charge_count_matches_frequency() -> None:
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 8, 1, tzinfo=UTC)
    assert default_max_charges(
        frequency="monthly", starts_at=start, ends_at=start + timedelta(days=365)
    ) == 12
    assert default_max_charges(
        frequency="weekly", starts_at=start, ends_at=start + timedelta(days=365)
    ) == 53
