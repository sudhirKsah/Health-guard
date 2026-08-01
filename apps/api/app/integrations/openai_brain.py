from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.config import Settings, get_settings


class OpenAIBrainError(RuntimeError):
    """A safe model failure that never weakens deterministic policy."""


@dataclass(frozen=True)
class ProductApprovalReview:
    safe_to_approve: bool
    selected_candidate_ids: tuple[str, ...]
    summary: str
    review_reason: str | None


class OpenAIBrain:
    """Bounded Responses API client.

    The model receives safe catalog descriptions and policy facts only. It never receives
    Prava credentials, mandate-charge responses, card data, addresses, or API secrets.
    Every model proposal is revalidated by deterministic application code before mutation.
    """

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @property
    def model(self) -> str:
        return self._settings.openai_model

    def review_product_candidates(
        self,
        *,
        supply_description: str,
        candidates: list[dict[str, object]],
        deterministic_selection_ids: list[str],
        user_allows_any_matching_product: bool = False,
    ) -> ProductApprovalReview:
        if not candidates or not deterministic_selection_ids:
            raise OpenAIBrainError("No deterministic exact candidates were available for review")
        candidate_ids = [str(candidate["candidate_id"]) for candidate in candidates]
        result = self._call_function(
            name="submit_catalog_assessment",
            description=(
                "Return a conservative assessment of exact recurring-supply catalog matches. "
                "This tool cannot approve substitutions or candidates outside the provided list."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "safe_to_approve": {"type": "boolean"},
                    "selected_candidate_ids": {
                        "type": "array",
                        "items": {"type": "string", "enum": candidate_ids},
                    },
                    "summary": {"type": "string"},
                    "review_reason": {"type": ["string", "null"]},
                },
                "required": [
                    "safe_to_approve",
                    "selected_candidate_ids",
                    "summary",
                    "review_reason",
                ],
                "additionalProperties": False,
            },
            prompt=(
                "You are the bounded catalog-review brain for an OTC supply replenishment service. "
                "Do not diagnose, suggest a substitute, change strength/formula/form, or infer clinical "
                "equivalence. Deterministic code has already checked literal request terms, inventory "
                "unit, optional pack preference, availability, and approved merchant. "
                + (
                    "The user left the specific-product preference blank and explicitly allows any literal "
                    "match for the named supply and form; do not require an unstated brand or strength. "
                    if user_allows_any_matching_product
                    else "The user specified a product preference; require every stated identity detail. "
                )
                + "Confirm only if every deterministic selection follows that request. If anything is uncertain, set safe_to_approve "
                "to false. Write a short explanation for a normal user.\n\n"
                f"Requested supply:\n{supply_description}\n\n"
                f"Deterministic selection IDs: {json.dumps(deterministic_selection_ids)}\n"
                f"Candidates: {json.dumps(candidates, ensure_ascii=True)}"
            ),
        )
        selected = tuple(str(value) for value in result.get("selected_candidate_ids", []))
        return ProductApprovalReview(
            safe_to_approve=bool(result.get("safe_to_approve")),
            selected_candidate_ids=selected,
            summary=str(result.get("summary") or "Automatic product review completed."),
            review_reason=(
                str(result["review_reason"]) if result.get("review_reason") is not None else None
            ),
        )

    def explain_replenishment_decision(
        self, *, facts: dict[str, object], fallback: str
    ) -> str:
        try:
            result = self._call_function(
                name="submit_caregiver_explanation",
                description="Return one accurate plain-language explanation of a completed policy decision.",
                parameters={
                    "type": "object",
                    "properties": {"explanation": {"type": "string"}},
                    "required": ["explanation"],
                    "additionalProperties": False,
                },
                prompt=(
                    "Explain these already-finalized deterministic replenishment facts to a normal user. "
                    "Do not add medical advice, claim a merchant delivery when none exists, change the "
                    "outcome, or invent details. Use one or two short sentences.\n\n"
                    f"Facts: {json.dumps(facts, ensure_ascii=True)}"
                ),
            )
        except OpenAIBrainError:
            return fallback
        explanation = str(result.get("explanation") or "").strip()
        return explanation or fallback

    def _call_function(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, object],
        prompt: str,
    ) -> dict[str, Any]:
        client = self._get_client()
        try:
            response = client.responses.create(
                model=self._settings.openai_model,
                reasoning={"effort": self._settings.openai_reasoning_effort},
                input=[
                    {
                        "role": "developer",
                        "content": (
                            "Follow the supplied safety boundary exactly. Use the required function "
                            "once and return no unsupported facts."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=[
                    {
                        "type": "function",
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                        "strict": True,
                    }
                ],
                tool_choice={"type": "function", "name": name},
                parallel_tool_calls=False,
                max_output_tokens=900,
            )
        except Exception as error:
            raise OpenAIBrainError("OpenAI could not complete the bounded decision") from error
        for item in response.output:
            if getattr(item, "type", None) != "function_call" or getattr(item, "name", None) != name:
                continue
            try:
                arguments = json.loads(item.arguments)
            except (AttributeError, TypeError, json.JSONDecodeError) as error:
                raise OpenAIBrainError("OpenAI returned invalid tool arguments") from error
            if not isinstance(arguments, dict):
                raise OpenAIBrainError("OpenAI returned invalid tool arguments")
            return arguments
        raise OpenAIBrainError("OpenAI did not call the required bounded tool")

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client
        if self._settings.openai_api_key is None:
            raise OpenAIBrainError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(
            api_key=self._settings.openai_api_key.get_secret_value(),
            timeout=35,
            max_retries=1,
        )
        return self._client
