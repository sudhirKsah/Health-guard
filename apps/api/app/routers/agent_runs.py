from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.runtime import ReplenishmentAgent, owned_supply_for_agent
from app.auth import get_current_user
from app.database import get_db_session
from app.models import AgentRun, User
from app.scheduler import ReplenishmentScheduler
from app.schemas import (
    AgentRunCreate,
    AgentRunOut,
    AgentRunScheduleOut,
    AgentRunScheduleRequest,
    AgentRunStartOut,
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
