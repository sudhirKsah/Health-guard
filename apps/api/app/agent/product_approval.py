from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_session_factory
from app.integrations.openai_brain import OpenAIBrain, OpenAIBrainError
from app.integrations.ucp import UcpAdapter, UcpConfigurationError, UcpMerchantError, UcpVariant
from app.models import (
    ApprovedVariant,
    Beneficiary,
    LedgerEvent,
    MerchantAuthorization,
    ProductEquivalenceSet,
    Supply,
)

AUTO_EQUIVALENCE_SET_NAME = "Health Guard verified exact match"
logger = logging.getLogger(__name__)

_WORDS = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_PACK = re.compile(
    r"(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>tablets?|tabs?|caplets?|capsules?|caps?|strips?|"
    r"sachets?|packets?|swabs?|bottles?|units?|pieces?|pcs?|grams?|g|kilograms?|kgs?|kg|"
    r"millilit(?:er|re)s?|ml|lit(?:er|re)s?|l)\b",
    re.IGNORECASE,
)
_PACK_OF = re.compile(r"\bpack\s+of\s+(?P<count>\d+(?:\.\d+)?)\b", re.IGNORECASE)
_UNIT_WORD = re.compile(
    r"\b(?P<unit>tablets?|tabs?|caplets?|capsules?|caps?|strips?|sachets?|packets?|"
    r"swabs?|bottles?|units?|pieces?|pcs?|grams?|g|kilograms?|kgs?|kg|"
    r"millilit(?:er|re)s?|ml|lit(?:er|re)s?|l)\b",
    re.IGNORECASE,
)
_IGNORED_TERMS = {
    "a",
    "an",
    "and",
    "brand",
    "copy",
    "exact",
    "for",
    "formula",
    "from",
    "label",
    "my",
    "of",
    "pack",
    "product",
    "same",
    "strength",
    "the",
    "use",
    "with",
}
_UNIT_ALIASES = {
    "tab": "tablet",
    "tabs": "tablet",
    "tablets": "tablet",
    "caplet": "tablet",
    "caplets": "tablet",
    "caps": "capsule",
    "capsules": "capsule",
    "strips": "strip",
    "sachets": "sachet",
    "packets": "packet",
    "swabs": "swab",
    "bottles": "bottle",
    "units": "unit",
    "pieces": "piece",
    "pcs": "piece",
    "g": "gram",
    "grams": "gram",
    "kg": "kilogram",
    "kgs": "kilogram",
    "kilograms": "kilogram",
    "ml": "milliliter",
    "milliliters": "milliliter",
    "millilitre": "milliliter",
    "millilitres": "milliliter",
    "l": "liter",
    "litre": "liter",
    "liters": "liter",
    "litres": "liter",
}


@dataclass(frozen=True)
class ExactCandidate:
    candidate_id: str
    authorization: MerchantAuthorization
    variant: UcpVariant
    pack_quantity: Decimal
    pack_unit: str
    evidence_terms: tuple[str, ...]


def normalize_unit(value: str) -> str:
    normalized = value.strip().casefold()
    return _UNIT_ALIASES.get(normalized, normalized[:-1] if normalized.endswith("s") else normalized)


def significant_terms(value: str) -> set[str]:
    return {term for term in _WORDS.findall(value.casefold()) if term not in _IGNORED_TERMS}


def candidate_pack(
    text: str, *, supply_unit: str, preferred: Decimal | None
) -> tuple[Decimal, str] | None:
    pack_of = _PACK_OF.search(text)
    if pack_of and any(
        normalize_unit(match.group("unit")) == normalize_unit(supply_unit)
        for match in _UNIT_WORD.finditer(text)
    ):
        return Decimal(pack_of.group("count")), normalize_unit(supply_unit)
    match = _PACK.search(text)
    if match:
        unit = normalize_unit(match.group("unit"))
        if unit != normalize_unit(supply_unit):
            return None
        return Decimal(match.group("count")), unit
    if preferred is not None:
        preferred_text = format(preferred.normalize(), "f")
        terms = significant_terms(text)
        if preferred_text in terms and normalize_unit(supply_unit) in {
            normalize_unit(term) for term in terms
        }:
            return preferred, normalize_unit(supply_unit)
    return None


def catalog_pack(text: str) -> tuple[Decimal, str] | None:
    """Read the catalog's own pack unit for type-ahead before the user chooses a unit."""
    match = _PACK.search(text)
    if match is None:
        return None
    return Decimal(match.group("count")), normalize_unit(match.group("unit"))


class ProductApprovalAgent:
    """Discovers catalog products while keeping final mutation behind exact deterministic gates."""

    def __init__(
        self,
        db: Session,
        *,
        ucp: UcpAdapter | None = None,
        brain: OpenAIBrain | None = None,
    ) -> None:
        self._db = db
        self._ucp = ucp or UcpAdapter()
        self._brain = brain or OpenAIBrain()

    def configure(self, *, owner_id: UUID, supply_id: UUID) -> None:
        supply = self._db.scalar(
            select(Supply)
            .join(Supply.beneficiary)
            .where(
                Supply.id == supply_id,
                Beneficiary.owner_id == owner_id,
                Supply.deleted_at.is_(None),
            )
            .options(selectinload(Supply.equivalence_sets))
        )
        if supply is None:
            return
        authorizations = list(
            self._db.scalars(
                select(MerchantAuthorization)
                .where(
                    MerchantAuthorization.owner_id == owner_id,
                    MerchantAuthorization.is_enabled.is_(True),
                )
                .order_by(MerchantAuthorization.preference_rank)
            )
        )
        if not authorizations:
            self._finish_without_approval(
                supply,
                status="waiting_for_merchant",
                message="Choose a merchant and Health Guard will find the exact product automatically.",
            )
            return

        specific_product = bool(supply.product_requirements and supply.product_requirements.strip())
        supply.setup_status = "discovering"
        supply.setup_message = (
            "Checking approved merchants for your specific product…"
            if specific_product
            else "Checking approved merchants for a matching product…"
        )
        supply.is_enabled = False
        self._db.commit()

        requested = " ".join(
            part.strip()
            for part in (supply.name, supply.product_requirements or "")
            if part and part.strip()
        )
        candidates: list[ExactCandidate] = []
        merchant_errors = 0
        ambiguous_merchants = 0
        for authorization in authorizations:
            try:
                search_variants = self._ucp.search(
                    merchant_key=authorization.merchant_key, query=requested
                )
                preliminary = self._exact_candidates(
                    supply=supply,
                    authorization=authorization,
                    requested=requested,
                    live_variants=search_variants,
                )
                live_by_identity = {
                    (item.product_id, item.variant_id): item for item in search_variants
                }
                for product_id in {item.variant.product_id for item in preliminary}:
                    for item in self._ucp.get_product(
                        merchant_key=authorization.merchant_key,
                        product_id=product_id,
                    ):
                        live_by_identity[(item.product_id, item.variant_id)] = item
            except (UcpConfigurationError, UcpMerchantError):
                merchant_errors += 1
                continue
            exact = self._exact_candidates(
                supply=supply,
                authorization=authorization,
                requested=requested,
                live_variants=list(live_by_identity.values()),
            )
            product_ids = {item.variant.product_id for item in exact}
            if exact and (not specific_product or len(product_ids) == 1):
                candidates.append(self._best_pack(exact))
            elif len(product_ids) > 1:
                ambiguous_merchants += 1

        if not candidates:
            reason = (
                "Merchant catalogs are temporarily unavailable. Health Guard will not approve a product "
                "until it can verify a live exact match."
                if merchant_errors == len(authorizations)
                else (
                    "No matching product was found for the supply name, unit, and optional pack size. "
                    "Check those details, or leave the pack size blank so Health Guard can choose."
                    if not specific_product
                    else "No unambiguous specific product was found. Check the product preference and optional pack size, then try again."
                )
            )
            self._finish_without_approval(supply, status="needs_attention", message=reason)
            return

        safe_candidates = [self._safe_candidate(candidate) for candidate in candidates]
        deterministic_ids = [candidate.candidate_id for candidate in candidates]
        try:
            review = self._brain.review_product_candidates(
                supply_description=requested,
                candidates=safe_candidates,
                deterministic_selection_ids=deterministic_ids,
                user_allows_any_matching_product=not specific_product,
            )
        except OpenAIBrainError:
            self._finish_without_approval(
                supply,
                status="needs_attention",
                message=(
                    "The product safety review could not finish. No product was approved; try again when the service is available."
                ),
            )
            return

        if not review.safe_to_approve or set(review.selected_candidate_ids) != set(
            deterministic_ids
        ):
            self._finish_without_approval(
                supply,
                status="needs_attention",
                message=review.review_reason
                or "The product review found uncertainty, so automatic ordering remains paused.",
                summary=review.summary,
            )
            return

        equivalence_set = next(
            (
                item
                for item in supply.equivalence_sets
                if item.name == AUTO_EQUIVALENCE_SET_NAME
            ),
            None,
        )
        if equivalence_set is None:
            equivalence_set = ProductEquivalenceSet(
                supply_id=supply.id,
                name=AUTO_EQUIVALENCE_SET_NAME,
                notes=(
                    "Created by the bounded catalog agent after deterministic literal-match checks."
                    if not specific_product
                    else "Created by the bounded catalog agent after deterministic exact-match checks."
                ),
            )
            self._db.add(equivalence_set)
            self._db.flush()

        selected_identity = {
            (
                candidate.authorization.id,
                candidate.variant.product_id,
                candidate.variant.variant_id,
            )
            for candidate in candidates
        }
        for existing in list(equivalence_set.approved_variants):
            identity = (
                existing.merchant_authorization_id,
                existing.merchant_product_id,
                existing.merchant_variant_id,
            )
            if identity not in selected_identity:
                self._db.delete(existing)
        existing_by_identity = {
            (
                item.merchant_authorization_id,
                item.merchant_product_id,
                item.merchant_variant_id,
            ): item
            for item in equivalence_set.approved_variants
        }
        price_checked_at = datetime.now(UTC)
        for candidate in candidates:
            identity = (
                candidate.authorization.id,
                candidate.variant.product_id,
                candidate.variant.variant_id,
            )
            existing = existing_by_identity.get(identity)
            if existing is not None:
                existing.latest_unit_price = candidate.variant.unit_price
                existing.latest_currency = candidate.variant.currency
                existing.price_checked_at = price_checked_at
                continue
            self._db.add(
                ApprovedVariant(
                    equivalence_set_id=equivalence_set.id,
                    merchant_authorization_id=candidate.authorization.id,
                    merchant_product_id=candidate.variant.product_id,
                    merchant_variant_id=candidate.variant.variant_id,
                    display_name=" — ".join(
                        value
                        for value in (
                            candidate.variant.product_title,
                            candidate.variant.variant_title,
                        )
                        if value
                    ),
                    pack_quantity=candidate.pack_quantity,
                    pack_unit=candidate.pack_unit,
                    latest_unit_price=candidate.variant.unit_price,
                    latest_currency=candidate.variant.currency,
                    price_checked_at=price_checked_at,
                )
            )

        supply.setup_status = "ready"
        verified_label = "Matching product selected" if not specific_product else "Specific product verified"
        supply.setup_message = (
            f"{verified_label} at {len(candidates)} approved merchant"
            f"{'s' if len(candidates) != 1 else ''}."
        )
        supply.agent_summary = review.summary
        supply.configured_at = datetime.now(UTC)
        supply.is_enabled = True
        self._db.add(
            LedgerEvent(
                owner_id=owner_id,
                event_type="supply_product_verified",
                title=f"{supply.name} is ready",
                detail=(
                    f"Health Guard selected a verified product at {len(candidates)} approved merchant"
                    f"{'s' if len(candidates) != 1 else ''}. Automatic checks are now active."
                ),
                severity="success",
                supply_id=supply.id,
                metadata_safe={
                    "approved_merchant_count": len(candidates),
                    "ambiguous_merchant_count": ambiguous_merchants,
                    "model": self._brain.model,
                },
            )
        )
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            self._finish_without_approval(
                supply,
                status="needs_attention",
                message="The exact product setup changed while it was being verified. Please try again.",
            )

    def _exact_candidates(
        self,
        *,
        supply: Supply,
        authorization: MerchantAuthorization,
        requested: str,
        live_variants: list[UcpVariant],
    ) -> list[ExactCandidate]:
        merchant_terms = significant_terms(
            f"{authorization.merchant_key} {authorization.merchant_name}"
        )
        required_terms = significant_terms(requested) - merchant_terms
        exact: list[ExactCandidate] = []
        for index, variant in enumerate(live_variants, start=1):
            display = variant.catalog_evidence
            display_terms = significant_terms(display)
            if not required_terms or not required_terms.issubset(display_terms):
                continue
            pack = candidate_pack(
                display,
                supply_unit=supply.unit,
                preferred=supply.preferred_pack_quantity,
            )
            if pack is None:
                continue
            if supply.preferred_pack_quantity is not None and pack[0] != supply.preferred_pack_quantity:
                continue
            if not variant.available:
                continue
            exact.append(
                ExactCandidate(
                    candidate_id=f"{authorization.merchant_key}-{index}",
                    authorization=authorization,
                    variant=variant,
                    pack_quantity=pack[0],
                    pack_unit=pack[1],
                    evidence_terms=tuple(sorted(required_terms)),
                )
            )
        return exact

    @staticmethod
    def _best_pack(candidates: list[ExactCandidate]) -> ExactCandidate:
        return min(
            candidates,
            key=lambda candidate: (
                candidate.variant.unit_price / candidate.pack_quantity,
                candidate.variant.unit_price,
                candidate.variant.product_id,
                candidate.variant.variant_id,
            ),
        )

    @staticmethod
    def _safe_candidate(candidate: ExactCandidate) -> dict[str, object]:
        return {
            "candidate_id": candidate.candidate_id,
            "merchant": candidate.authorization.merchant_name,
            "product_name": candidate.variant.product_title,
            "variant_name": candidate.variant.variant_title,
            "pack_quantity": str(candidate.pack_quantity),
            "pack_unit": candidate.pack_unit,
            "price": str(candidate.variant.unit_price),
            "currency": candidate.variant.currency,
            "available": candidate.variant.available,
            "matched_terms": list(candidate.evidence_terms),
        }

    def _finish_without_approval(
        self,
        supply: Supply,
        *,
        status: str,
        message: str,
        summary: str | None = None,
    ) -> None:
        supply.setup_status = status
        supply.setup_message = message
        supply.agent_summary = summary
        supply.configured_at = None
        supply.is_enabled = False
        self._db.add(
            LedgerEvent(
                owner_id=supply.beneficiary.owner_id,
                event_type=f"supply_setup_{status}",
                title=(
                    f"{supply.name} needs a quick check"
                    if status == "needs_attention"
                    else f"{supply.name} is waiting for a merchant"
                ),
                detail=message,
                severity="warning" if status == "needs_attention" else "info",
                supply_id=supply.id,
                metadata_safe={"setup_status": status},
            )
        )
        self._db.commit()


def auto_configure_supply_background(owner_id: UUID, supply_id: UUID) -> None:
    try:
        with get_session_factory()() as db:
            ProductApprovalAgent(db).configure(owner_id=owner_id, supply_id=supply_id)
    except Exception:
        logger.exception("Automatic product setup failed for supply %s", supply_id)
        with get_session_factory()() as db:
            supply = db.scalar(
                select(Supply)
                .join(Supply.beneficiary)
                .where(
                    Supply.id == supply_id,
                    Beneficiary.owner_id == owner_id,
                    Supply.deleted_at.is_(None),
                )
            )
            if supply is not None:
                supply.setup_status = "needs_attention"
                supply.setup_message = (
                    "The product check stopped unexpectedly. No product was approved; please try again."
                )
                supply.is_enabled = False
                db.commit()


def auto_configure_owner_supplies_background(owner_id: UUID) -> None:
    with get_session_factory()() as db:
        supply_ids = list(
            db.scalars(
                select(Supply.id)
                .join(Supply.beneficiary)
                .where(
                    Beneficiary.owner_id == owner_id,
                    Beneficiary.is_active.is_(True),
                    Supply.deleted_at.is_(None),
                )
            )
        )
    for supply_id in supply_ids:
        auto_configure_supply_background(owner_id, supply_id)
