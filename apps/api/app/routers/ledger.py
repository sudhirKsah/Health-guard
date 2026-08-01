from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.runtime import ReplenishmentAgent, owned_supply_for_agent
from app.auth import get_current_user
from app.database import get_db_session
from app.models import LedgerEvent, User
from app.schemas import AgentRunOut, AgentRunStartOut, LedgerEventOut

router = APIRouter(prefix="/ledger", tags=["trust ledger"])


@router.get("/events", response_model=list[LedgerEventOut])
def list_events(
    user: User = Depends(get_current_user), db: Session = Depends(get_db_session)
) -> list[LedgerEventOut]:
    events = db.scalars(
        select(LedgerEvent)
        .where(LedgerEvent.owner_id == user.id)
        .order_by(LedgerEvent.created_at.desc())
        .limit(100)
    )
    return [LedgerEventOut.model_validate(event) for event in events]


@router.post(
    "/supplies/{supply_id}/running-low",
    response_model=AgentRunStartOut,
    status_code=status.HTTP_201_CREATED,
)
def running_low(
    supply_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db_session)
) -> AgentRunStartOut:
    supply = owned_supply_for_agent(db, owner_id=user.id, supply_id=supply_id)
    if supply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supply not found")
    trigger = f"running-low:{supply.id}:{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    run, reused = ReplenishmentAgent(db).start(user=user, supply=supply, trigger_id=trigger)
    db.add(
        LedgerEvent(
            owner_id=user.id,
            event_type="running_low_signalled",
            title="Low supply signal received",
            detail=f"Health Guard will evaluate {supply.name} under its existing approvals and mandate limits.",
            severity="info",
            agent_run_id=run.id,
            supply_id=supply.id,
            metadata_safe={"trigger": "running_low"},
        )
    )
    db.commit()
    return AgentRunStartOut(run=AgentRunOut.model_validate(run), reused=reused)
