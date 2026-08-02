from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.agent.policy import POLICY_VERSION, ApprovedVariantPolicy, OfferCandidate, choose_offer
from app.agent.sandbox_settlement import SandboxSettlementExecutor
from app.agent.state import AgentState, validate_transition
from app.agent.tools import CatalogSearchTool, ConfiguredVariant, InventoryTool
from app.integrations.openai_brain import OpenAIBrain
from app.mandate_cycles import MandateChargeWindow, mandate_charge_window
from app.models import (
    AgentRun,
    AgentStep,
    ApprovedVariant,
    Beneficiary,
    LedgerEvent,
    MerchantAuthorization,
    OfferSnapshot,
    ProductEquivalenceSet,
    Supply,
    User,
)


class ReplenishmentAgent:
    """A bounded agent that records evidence and never receives payment capability in Phase 3."""

    def __init__(
        self,
        db: Session,
        *,
        brain: OpenAIBrain | None = None,
        explicit_sandbox_test: bool = False,
    ) -> None:
        self.db = db
        self.inventory_tool = InventoryTool()
        self.catalog_search_tool = CatalogSearchTool()
        self.brain = brain or OpenAIBrain()
        self.explicit_sandbox_test = explicit_sandbox_test

    def start(
        self, *, user: User, supply: Supply, trigger_id: str | None = None
    ) -> tuple[AgentRun, bool]:
        trigger = trigger_id or f"manual:{uuid4()}"
        existing = self._find_run(user.id, trigger)
        if existing is not None:
            return existing, True

        projection, inventory_result = self.inventory_tool.run(supply)
        run = AgentRun(
            owner_id=user.id,
            supply_id=supply.id,
            trigger_id=trigger,
            goal=(
                f"Keep {supply.name} available without selecting anything outside the "
                "caregiver's explicit approval."
            ),
            state=AgentState.OBSERVE,
            status="running",
            policy_version=POLICY_VERSION,
            days_until_stockout=projection.days_until_stockout,
            projected_stockout_at=projection.projected_stockout_at,
        )
        self.db.add(run)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self._find_run(user.id, trigger)
            if existing is None:
                raise
            return existing, True

        self._record_step(
            run,
            stage="observe",
            tool_name=self.inventory_tool.name,
            status=inventory_result.status,
            input_summary={"supply_id": str(supply.id)},
            output_summary=inventory_result.summary,
        )

        if not supply.is_enabled:
            return self._finish(
                run,
                state=AgentState.COMPLETE,
                status="completed",
                outcome="wait",
                explanation=(
                    f"{supply.name} is paused. Health Guard will not evaluate or order this supply."
                ),
            )
        if not supply.beneficiary.is_active:
            return self._finish(
                run,
                state=AgentState.COMPLETE,
                status="completed",
                outcome="wait",
                explanation=(
                    f"{supply.name} belongs to a paused beneficiary. No reorder evaluation was performed."
                ),
            )
        if not projection.reorder_required:
            return self._finish(
                run,
                state=AgentState.COMPLETE,
                status="completed",
                outcome="wait",
                explanation=(
                    f"{supply.name} has {projection.days_until_safety_buffer} days before reaching "
                    "its safety buffer, so no reorder evaluation is needed yet."
                ),
            )

        self._transition(run, AgentState.DISCOVER)
        configured_variants = list(
            self.db.execute(
                select(ApprovedVariant, MerchantAuthorization)
                .join(ApprovedVariant.equivalence_set)
                .join(ApprovedVariant.merchant_authorization)
                .where(
                    ProductEquivalenceSet.supply_id == supply.id,
                    MerchantAuthorization.is_enabled.is_(True),
                )
                .order_by(MerchantAuthorization.preference_rank)
            )
        )
        catalog_result, live_offers = self.catalog_search_tool.run(
            query=supply.name,
            configured_variants=[
                ConfiguredVariant(
                    merchant_authorization_id=authorization.id,
                    merchant_key=authorization.merchant_key,
                    merchant_product_id=variant.merchant_product_id,
                    merchant_variant_id=variant.merchant_variant_id,
                )
                for variant, authorization in configured_variants
            ],
        )
        checked_at = datetime.now(UTC)
        variants_by_identity = {
            (
                str(authorization.id),
                variant.merchant_product_id,
                variant.merchant_variant_id,
            ): variant
            for variant, authorization in configured_variants
        }
        for offer in live_offers:
            configured_variant = variants_by_identity.get(
                (
                    str(offer.merchant_authorization_id),
                    offer.merchant_product_id,
                    offer.merchant_variant_id,
                )
            )
            if configured_variant is not None:
                configured_variant.latest_unit_price = offer.unit_price
                configured_variant.latest_currency = offer.currency
                configured_variant.price_checked_at = checked_at
        self._record_step(
            run,
            stage="discover",
            tool_name=self.catalog_search_tool.name,
            status=catalog_result.status,
            input_summary={"supply_id": str(supply.id), "query": supply.name},
            output_summary=catalog_result.summary,
        )
        snapshots = []
        for offer in live_offers:
            snapshot = OfferSnapshot(
                agent_run_id=run.id,
                merchant_authorization_id=offer.merchant_authorization_id,
                merchant_product_id=offer.merchant_product_id,
                merchant_variant_id=offer.merchant_variant_id,
                product_title=offer.product_title,
                variant_title=offer.variant_title,
                available=offer.available,
                currency=offer.currency,
                unit_price=offer.unit_price,
                shipping_price=0,
                landed_price=offer.unit_price,
                estimated_arrival_days=None,
                source_status="catalog_live",
            )
            self.db.add(snapshot)
            snapshots.append(snapshot)
        self.db.flush()
        self._transition(run, AgentState.DECIDE)
        sandbox_executor = SandboxSettlementExecutor(self.db)
        sandbox_settlement = sandbox_executor.enabled(
            explicit_test=self.explicit_sandbox_test
        )
        mandate_windows: dict[UUID, MandateChargeWindow] = {
            authorization.id: mandate_charge_window(
                frequency=authorization.mandate_frequency,
                renews_at=authorization.mandate_renews_at,
                last_charge_at=authorization.mandate_last_charge_at,
                last_charge_status=authorization.mandate_last_charge_status,
                approved_amount=authorization.mandate_approved_amount,
                remaining_amount=authorization.mandate_remaining_amount,
                observed_at=checked_at,
            )
            for _variant, authorization in configured_variants
        }
        policy = choose_offer(
            offers=[
                OfferCandidate(
                    merchant_authorization_id=str(offer.merchant_authorization_id),
                    merchant_product_id=offer.merchant_product_id,
                    merchant_variant_id=offer.merchant_variant_id,
                    available=offer.available,
                    landed_price=offer.unit_price,
                    # The official Prava sandbox settlement flow tests payment authorisation and
                    # reporting only; it does not create a physical merchant delivery. Do not apply
                    # this exception in production, where a delivery-aware quote remains mandatory.
                    arrival_days=Decimal("0") if sandbox_settlement else None,
                )
                for offer in live_offers
            ],
            approved_variants=[
                ApprovedVariantPolicy(
                    merchant_authorization_id=str(authorization.id),
                    merchant_product_id=variant.merchant_product_id,
                    merchant_variant_id=variant.merchant_variant_id,
                    merchant_is_enabled=authorization.is_enabled,
                    merchant_preference_rank=authorization.preference_rank,
                    mandate_status=authorization.mandate_status,
                    mandate_approved_amount=authorization.mandate_approved_amount,
                    mandate_remaining_amount=authorization.mandate_remaining_amount,
                    health_guard_stop_after=authorization.health_guard_stop_after,
                    mandate_valid_until=authorization.mandate_valid_until,
                    mandate_next_charge_at=mandate_windows[
                        authorization.id
                    ].next_eligible_at,
                    mandate_charge_block_reason=mandate_windows[authorization.id].reason,
                )
                for variant, authorization in configured_variants
            ],
            days_until_stockout=projection.days_until_stockout,
        )
        decision_reason = (
            policy.rejected[0].reason if policy.rejected else "no_live_exact_offer_returned"
        )
        self._record_step(
            run,
            stage="decide",
            tool_name="deterministic_policy_evaluator",
            status="blocked" if policy.selected is None else "success",
            input_summary={"policy_version": POLICY_VERSION},
            output_summary={
                "decision": "blocked" if policy.selected is None else "reorder",
                "reason": decision_reason if policy.selected is None else None,
                "live_offer_snapshot_count": len(snapshots),
                "payment_tools_available": sandbox_settlement,
                "sandbox_settlement": sandbox_settlement,
            },
        )
        if policy.selected is not None:
            selected_variant, selected_authorization = next(
                (variant, authorization)
                for variant, authorization in configured_variants
                if str(authorization.id) == policy.selected.merchant_authorization_id
                and variant.merchant_product_id == policy.selected.merchant_product_id
                and variant.merchant_variant_id == policy.selected.merchant_variant_id
            )
            self._transition(run, AgentState.ACT)
            settlement = sandbox_executor.execute(
                run=run,
                authorization=selected_authorization,
                amount=policy.selected.landed_price,
                product_description=next(
                    offer.product_title
                    for offer in live_offers
                    if str(offer.merchant_authorization_id)
                    == policy.selected.merchant_authorization_id
                    and offer.merchant_product_id == policy.selected.merchant_product_id
                    and offer.merchant_variant_id == policy.selected.merchant_variant_id
                ),
                product_id=policy.selected.merchant_product_id,
                pack_quantity=selected_variant.pack_quantity,
                pack_unit=selected_variant.pack_unit,
                explicit_test=self.explicit_sandbox_test,
            )
            self._record_step(
                run,
                stage="act",
                tool_name="prava_sandbox_mandate_settlement",
                status=(
                    "success"
                    if settlement.status == "sandbox_settled"
                    else "cancelled"
                    if settlement.status == "cancelled"
                    else "blocked"
                ),
                input_summary={
                    "merchant_authorization_id": str(selected_authorization.id),
                    "amount": f"{policy.selected.landed_price:.2f}",
                },
                output_summary={
                    "status": settlement.status,
                    "failure_code": settlement.failure_code,
                    "next_eligible_at": (
                        settlement.next_eligible_at.isoformat()
                        if settlement.next_eligible_at
                        else None
                    ),
                    "merchant_fulfillment": "not_available_in_sandbox_settlement",
                },
            )
            if settlement.status == "sandbox_settled":
                self._transition(run, AgentState.VERIFY)
                self._record_step(
                    run,
                    stage="verify",
                    tool_name="verify_prava_sandbox_settlement",
                    status="success",
                    input_summary={
                        "purchase_order_status": "sandbox_settled",
                    },
                    output_summary={
                        "prava_report_status": "APPROVED",
                        "merchant_order_id": None,
                        "merchant_fulfillment": "not_available_in_sandbox_settlement",
                    },
                )
                return self._finish(
                    run,
                    state=AgentState.COMPLETE,
                    status="completed",
                    outcome="sandbox_settled",
                    explanation=(
                        "Health Guard completed Prava's documented sandbox mandate charge and settlement "
                        "flow. This verifies the payment transaction only; it does not create a merchant "
                        "fulfillment order."
                    ),
                )
            if settlement.status == "cancelled":
                reason = {
                    "supply_deleted_or_paused": (
                        "The recurring supply was paused or deleted before payment. No payment was attempted."
                    ),
                    "supply_no_longer_due": (
                        "Another completed order already replenished this supply. No duplicate payment was attempted."
                    ),
                    "inventory_unit_changed": (
                        "The supply unit changed before payment. No payment was attempted."
                    ),
                    "mandate_frequency_wait": (
                        "This supply is ready to reorder, but the mandate has already been used "
                        f"in its {selected_authorization.mandate_frequency} cycle. No payment was "
                        "attempted. The next eligible payment time is "
                        f"{settlement.next_eligible_at.isoformat() if settlement.next_eligible_at else 'being synchronized'}."
                    ),
                    "mandate_cycle_boundary_unknown": (
                        "The mandate cycle boundary could not be verified, so Health Guard stopped "
                        "before payment. No payment was attempted."
                    ),
                    "mandate_sync_unavailable": (
                        "Health Guard could not verify the latest mandate cycle with Prava, so it "
                        "stopped before payment. No payment was attempted."
                    ),
                    "mandate_not_active": (
                        "The Prava mandate is not active. No payment was attempted."
                    ),
                }.get(
                    settlement.failure_code or "",
                    "The supply changed before payment. No payment was attempted.",
                )
                frequency_wait = settlement.failure_code == "mandate_frequency_wait"
                return self._finish(
                    run,
                    state=AgentState.COMPLETE,
                    status="completed",
                    outcome="frequency_wait" if frequency_wait else "wait",
                    explanation=reason,
                )
            return self._finish(
                run,
                state=AgentState.BLOCKED,
                status="blocked",
                outcome="blocked",
                explanation=(
                    "A live exact offer met the policy, but the Prava sandbox settlement did not complete. "
                    "No merchant fulfillment outcome was recorded."
                ),
            )
        if decision_reason == "mandate_frequency_wait":
            next_eligible_at = min(
                window.next_eligible_at
                for window in mandate_windows.values()
                if window.next_eligible_at is not None
            )
            supply.payment_deferred_until = next_eligible_at
            return self._finish(
                run,
                state=AgentState.COMPLETE,
                status="completed",
                outcome="frequency_wait",
                explanation=(
                    f"{supply.name} is ready to reorder, but its mandate has already been used in "
                    f"the current payment cycle. No payment was attempted. The next eligible "
                    f"payment time is {next_eligible_at.isoformat()}."
                ),
            )
        return self._finish(
            run,
            state=AgentState.BLOCKED,
            status="blocked",
            outcome="blocked",
            explanation=(
                f"{supply.name} needs a reorder evaluation. Health Guard found only offers that cannot "
                "be safely selected yet because a delivery-aware quote is required. No payment was attempted."
            ),
        )

    def _find_run(self, owner_id: UUID, trigger_id: str) -> AgentRun | None:
        return self.db.scalar(
            select(AgentRun)
            .where(AgentRun.owner_id == owner_id, AgentRun.trigger_id == trigger_id)
            .options(
                selectinload(AgentRun.steps),
                selectinload(AgentRun.offer_snapshots),
                selectinload(AgentRun.purchase_order),
            )
        )

    def _record_step(
        self,
        run: AgentRun,
        *,
        stage: str,
        tool_name: str,
        status: str,
        input_summary: dict[str, object],
        output_summary: dict[str, object],
    ) -> None:
        run.steps.append(
            AgentStep(
                sequence=len(run.steps) + 1,
                stage=stage,
                tool_name=tool_name,
                status=status,
                input_summary=input_summary,
                output_summary=output_summary,
            )
        )

    def _finish(
        self,
        run: AgentRun,
        *,
        state: AgentState,
        status: str,
        outcome: str,
        explanation: str,
    ) -> tuple[AgentRun, bool]:
        self._transition(run, state)
        if outcome != "frequency_wait":
            explanation = self.brain.explain_replenishment_decision(
                facts={
                    "outcome": outcome,
                    "final_state": state.value,
                    "days_until_stockout": str(run.days_until_stockout),
                    "deterministic_explanation": explanation,
                },
                fallback=explanation,
            )
        run.status = status
        run.outcome = outcome
        run.explanation = explanation
        run.completed_at = datetime.now(UTC)
        severity = (
            "success"
            if outcome == "sandbox_settled"
            else "warning"
            if outcome == "blocked"
            else "info"
        )
        title = {
            "sandbox_settled": "Payment approved",
            "blocked": "Reorder needs attention",
            "wait": "Reorder check completed",
            "frequency_wait": "Payment waiting for mandate renewal",
        }.get(outcome, "Agent evaluation completed")
        self.db.add(
            LedgerEvent(
                owner_id=run.owner_id,
                event_type=f"agent_{outcome}",
                title=title,
                detail=explanation,
                severity=severity,
                agent_run_id=run.id,
                supply_id=run.supply_id,
                purchase_order_id=run.purchase_order.id if run.purchase_order else None,
                metadata_safe={"trigger_id": run.trigger_id, "state": state},
            )
        )
        self.db.commit()
        persisted = self._find_run(run.owner_id, run.trigger_id)
        if persisted is None:
            raise RuntimeError("Agent run was not persisted")
        return persisted, False

    def _transition(self, run: AgentRun, next_state: AgentState) -> None:
        current = AgentState(run.state)
        validate_transition(current, next_state)
        run.state = next_state


def owned_supply_for_agent(db: Session, *, owner_id: UUID, supply_id: UUID) -> Supply | None:
    return db.scalar(
        select(Supply)
        .join(Supply.beneficiary)
        .where(
            Supply.id == supply_id,
            Beneficiary.owner_id == owner_id,
            Supply.deleted_at.is_(None),
        )
        .options(selectinload(Supply.beneficiary))
    )
