from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.runtime import ReplenishmentAgent, owned_supply_for_agent
from app.auth import get_current_user
from app.database import get_db_session
from app.mandate_cycles import mandate_charge_window
from app.models import (
    AgentRun,
    ApprovedVariant,
    Beneficiary,
    MerchantAuthorization,
    OfferSnapshot,
    ProductEquivalenceSet,
    Supply,
    User,
)
from app.scheduler import ReplenishmentScheduler
from app.schemas import (
    AgentRunCreate,
    AgentRunOut,
    AgentRunScheduleOut,
    AgentRunScheduleRequest,
    AgentRunStartOut,
    PaymentTestRequest,
    SupplyAutomationTimingOut,
)

router = APIRouter(prefix="/agent-runs", tags=["replenishment agent"])


def owned_run(db: Session, owner_id: UUID, run_id: UUID) -> AgentRun:
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.owner_id == owner_id)
        .options(selectinload(AgentRun.steps))
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return run


@router.get("/automation-timing", response_model=list[SupplyAutomationTimingOut])
def automation_timing(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[SupplyAutomationTimingOut]:
    """Describe threshold timing separately from the scheduler's actual next check."""
    scheduler = getattr(request.app.state, "replenishment_scheduler", None)
    scheduler_available = isinstance(scheduler, ReplenishmentScheduler)
    scheduler_enabled = bool(
        scheduler_available and scheduler.next_recurring_evaluation_at is not None
    )
    interval_minutes = scheduler.interval_minutes if scheduler_available else 0
    supplies = list(
        db.scalars(
            select(Supply)
            .join(Supply.beneficiary)
            .where(
                Beneficiary.owner_id == user.id,
                Supply.deleted_at.is_(None),
            )
            .options(
                selectinload(Supply.equivalence_sets)
                .selectinload(ProductEquivalenceSet.approved_variants)
                .selectinload(ApprovedVariant.merchant_authorization)
            )
            .order_by(Supply.created_at)
        )
    )
    timings: list[SupplyAutomationTimingOut] = []
    now = datetime.now(UTC)
    for supply in supplies:
        variants = [
            variant
            for equivalence_set in supply.equivalence_sets
            for variant in equivalence_set.approved_variants
            if variant.merchant_authorization.is_enabled
        ]
        variants.sort(
            key=lambda variant: (
                variant.latest_unit_price is None,
                variant.latest_unit_price or 0,
                variant.merchant_authorization.preference_rank,
            )
        )
        selected_variant = variants[0] if variants else None
        authorization: MerchantAuthorization | None = (
            selected_variant.merchant_authorization if selected_variant else None
        )
        chargeable_price = selected_variant.latest_unit_price if selected_variant else None
        chargeable_currency = selected_variant.latest_currency if selected_variant else None
        price_checked_at = selected_variant.price_checked_at if selected_variant else None
        if selected_variant is not None and chargeable_price is None:
            latest_offer = db.scalar(
                select(OfferSnapshot)
                .join(OfferSnapshot.agent_run)
                .where(
                    AgentRun.supply_id == supply.id,
                    OfferSnapshot.merchant_authorization_id
                    == selected_variant.merchant_authorization_id,
                    OfferSnapshot.merchant_product_id
                    == selected_variant.merchant_product_id,
                    OfferSnapshot.merchant_variant_id
                    == selected_variant.merchant_variant_id,
                    OfferSnapshot.available.is_(True),
                )
                .order_by(OfferSnapshot.created_at.desc())
                .limit(1)
            )
            if latest_offer is not None:
                chargeable_price = latest_offer.landed_price
                chargeable_currency = latest_offer.currency
                price_checked_at = latest_offer.created_at
        window = (
            mandate_charge_window(
                frequency=authorization.mandate_frequency,
                renews_at=authorization.mandate_renews_at,
                last_charge_at=authorization.mandate_last_charge_at,
                last_charge_status=authorization.mandate_last_charge_status,
                approved_amount=authorization.mandate_approved_amount,
                remaining_amount=authorization.mandate_remaining_amount,
                observed_at=now,
            )
            if authorization is not None
            else None
        )
        if not supply.is_enabled:
            state = "paused"
        elif supply.setup_status != "ready":
            state = "setup_required"
        elif not scheduler_enabled:
            state = "scheduler_off"
        else:
            state = "scheduled"
        if window is not None and not window.eligible and state == "scheduled":
            state = (
                "payment_frequency_wait"
                if window.reason == "mandate_frequency_wait"
                else "payment_cycle_sync_required"
            )
        check_threshold = supply.next_order_at
        next_payment_eligible_at = (
            window.next_eligible_at if window and not window.eligible else None
        )
        if next_payment_eligible_at and next_payment_eligible_at > check_threshold:
            check_threshold = next_payment_eligible_at
        if supply.payment_deferred_until and supply.payment_deferred_until > check_threshold:
            check_threshold = supply.payment_deferred_until
        next_check = (
            scheduler.next_evaluation_on_or_after(check_threshold)
            if state in {"scheduled", "payment_frequency_wait"} and scheduler_available
            else None
        )
        if authorization is None:
            eligibility_state = "mandate_missing"
            eligibility_message = "Create an active mandate before automatic payment can run."
        elif window is not None and window.reason == "mandate_frequency_wait":
            eligibility_state = "frequency_wait"
            eligibility_message = (
                f"The {authorization.mandate_frequency} mandate was already used in this cycle. "
                "Health Guard will not attempt another payment before it renews."
            )
        elif window is not None and window.reason == "mandate_cycle_boundary_unknown":
            eligibility_state = "cycle_sync_required"
            eligibility_message = (
                "The next mandate cycle boundary is not verified, so payment is stopped safely."
            )
        elif authorization.mandate_status != "active":
            eligibility_state = "mandate_inactive"
            eligibility_message = "The selected merchant mandate is not active."
        else:
            eligibility_state = "eligible"
            eligibility_message = "The mandate is eligible when stock reaches the reorder level."
        timings.append(
            SupplyAutomationTimingOut(
                supply_id=supply.id,
                scheduler_enabled=scheduler_enabled,
                interval_minutes=interval_minutes,
                reorder_threshold_at=supply.next_order_at,
                next_automatic_check_at=next_check,
                state=state,
                chargeable_price=chargeable_price,
                chargeable_currency=chargeable_currency,
                price_checked_at=price_checked_at,
                merchant_name=authorization.merchant_name if authorization else None,
                mandate_frequency=authorization.mandate_frequency if authorization else None,
                next_payment_eligible_at=next_payment_eligible_at,
                payment_eligibility_state=eligibility_state,
                payment_eligibility_message=eligibility_message,
            )
        )
    return timings


@router.post(
    "/supplies/{supply_id}", response_model=AgentRunStartOut, status_code=status.HTTP_201_CREATED
)
def start_run(
    supply_id: UUID,
    payload: AgentRunCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AgentRunStartOut:
    supply = owned_supply_for_agent(db, owner_id=user.id, supply_id=supply_id)
    if supply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supply not found")
    run, reused = ReplenishmentAgent(db).start(
        user=user, supply=supply, trigger_id=payload.trigger_id
    )
    return AgentRunStartOut(run=AgentRunOut.model_validate(run), reused=reused)


@router.post(
    "/supplies/{supply_id}/test-payment",
    response_model=AgentRunStartOut,
    status_code=status.HTTP_201_CREATED,
)
def test_recurring_payment(
    supply_id: UUID,
    payload: PaymentTestRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AgentRunStartOut:
    supply = owned_supply_for_agent(db, owner_id=user.id, supply_id=supply_id)
    if supply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supply not found")
    run, reused = ReplenishmentAgent(db, explicit_sandbox_test=True).start(
        user=user,
        supply=supply,
        trigger_id=payload.trigger_id,
    )
    return AgentRunStartOut(run=AgentRunOut.model_validate(run), reused=reused)


@router.post("/supplies/{supply_id}/schedule", response_model=AgentRunScheduleOut)
def schedule_run(
    supply_id: UUID,
    payload: AgentRunScheduleRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AgentRunScheduleOut:
    supply = owned_supply_for_agent(db, owner_id=user.id, supply_id=supply_id)
    if supply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supply not found")
    if payload.run_at.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="run_at needs a timezone")
    scheduler = getattr(request.app.state, "replenishment_scheduler", None)
    if not isinstance(scheduler, ReplenishmentScheduler):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Scheduler unavailable")
    try:
        job_id, run_at = scheduler.schedule_evaluation(
            owner_id=user.id, supply_id=supply.id, run_at=payload.run_at
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return AgentRunScheduleOut(job_id=job_id, run_at=run_at)


@router.get("", response_model=list[AgentRunOut])
def list_runs(
    supply_id: UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[AgentRunOut]:
    statement = (
        select(AgentRun)
        .where(AgentRun.owner_id == user.id)
        .options(selectinload(AgentRun.steps))
        .order_by(AgentRun.created_at.desc())
        .limit(25)
    )
    if supply_id is not None:
        statement = statement.where(AgentRun.supply_id == supply_id)
    return [AgentRunOut.model_validate(run) for run in db.scalars(statement)]


@router.get("/{run_id}", response_model=AgentRunOut)
def get_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> AgentRunOut:
    return AgentRunOut.model_validate(owned_run(db, user.id, run_id))
