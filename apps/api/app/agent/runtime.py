from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.agent.policy import POLICY_VERSION
from app.agent.state import AgentState, validate_transition
from app.agent.tools import CatalogSearchTool, InventoryTool
from app.models import (
    AgentRun,
    AgentStep,
    ApprovedVariant,
    Beneficiary,
    MerchantAuthorization,
    ProductEquivalenceSet,
    Supply,
    User,
)


class ReplenishmentAgent:
    """A bounded agent that records evidence and never receives payment capability in Phase 3."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory_tool = InventoryTool()
        self.catalog_search_tool = CatalogSearchTool()

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
        configured_variants = self.db.scalar(
            select(func.count(ApprovedVariant.id))
            .join(ApprovedVariant.equivalence_set)
            .join(ApprovedVariant.merchant_authorization)
            .where(
                ProductEquivalenceSet.supply_id == supply.id,
                MerchantAuthorization.is_enabled.is_(True),
            )
        )
        # The Phase 4 adapter supplies catalog details. This phase records only the configured count.
        catalog_result = self.catalog_search_tool.run(
            approved_variant_count=configured_variants or 0
        )
        self._record_step(
            run,
            stage="discover",
            tool_name=self.catalog_search_tool.name,
            status=catalog_result.status,
            input_summary={"supply_id": str(supply.id), "query": supply.name},
            output_summary=catalog_result.summary,
        )
        self._transition(run, AgentState.DECIDE)
        self._record_step(
            run,
            stage="decide",
            tool_name="deterministic_policy_evaluator",
            status="blocked",
            input_summary={"policy_version": POLICY_VERSION},
            output_summary={
                "decision": "blocked",
                "reason": catalog_result.summary["reason"],
                "payment_tools_available": False,
            },
        )
        return self._finish(
            run,
            state=AgentState.BLOCKED,
            status="blocked",
            outcome="blocked",
            explanation=(
                f"{supply.name} is at or below its safety buffer and needs a reorder evaluation, "
                "but no live eligible quote is available yet. Health Guard did not attempt a payment."
            ),
        )

    def _find_run(self, owner_id: UUID, trigger_id: str) -> AgentRun | None:
        return self.db.scalar(
            select(AgentRun)
            .where(AgentRun.owner_id == owner_id, AgentRun.trigger_id == trigger_id)
            .options(selectinload(AgentRun.steps))
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
        run.status = status
        run.outcome = outcome
        run.explanation = explanation
        run.completed_at = datetime.now(UTC)
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
        .where(Supply.id == supply_id, Beneficiary.owner_id == owner_id)
        .options(selectinload(Supply.beneficiary))
    )
