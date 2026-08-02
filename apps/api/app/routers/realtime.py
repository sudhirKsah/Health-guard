from __future__ import annotations

import asyncio
import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.auth import get_current_user
from app.database import get_session_factory
from app.models import (
    AgentRun,
    ApprovedVariant,
    Beneficiary,
    LedgerEvent,
    MerchantAuthorization,
    ProductEquivalenceSet,
    PurchaseOrder,
    StockMovement,
    Supply,
    User,
)

router = APIRouter(prefix="/events", tags=["realtime updates"])

# How often each connected client's fingerprint is checked. Background work (product discovery,
# an agent run) takes seconds, so sub-second detection buys nothing and costs a query per client
# per tick. Keep-alive comments stop idle proxies closing the stream.
POLL_SECONDS = 2.0
KEEPALIVE_SECONDS = 20.0


def _stamp(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def owner_fingerprint(owner_id: UUID) -> str:
    """One round trip covering everything the dashboard renders.

    This runs once per connected client per tick, so it is deliberately a single query of scalar
    subqueries rather than eight separate statements.
    """
    with get_session_factory()() as db:
        row = db.execute(
            select(
                select(func.max(Beneficiary.updated_at))
                .where(Beneficiary.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(Supply.updated_at))
                .join(Supply.beneficiary)
                .where(Beneficiary.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(MerchantAuthorization.updated_at))
                .where(MerchantAuthorization.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(ApprovedVariant.updated_at))
                .join(ApprovedVariant.equivalence_set)
                .join(ProductEquivalenceSet.supply)
                .join(Supply.beneficiary)
                .where(Beneficiary.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(AgentRun.completed_at))
                .where(AgentRun.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(PurchaseOrder.updated_at))
                .where(PurchaseOrder.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(StockMovement.occurred_at))
                .join(StockMovement.supply)
                .join(Supply.beneficiary)
                .where(Beneficiary.owner_id == owner_id)
                .scalar_subquery(),
                select(func.max(LedgerEvent.created_at))
                .where(LedgerEvent.owner_id == owner_id)
                .scalar_subquery(),
            )
        ).one()
    return "|".join(_stamp(value) for value in row)


@router.get("/stream")
async def stream_updates(
    request: Request,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    async def events():
        # Seed from the state at connect time. The client always loads once on mount, so emitting
        # the very first fingerprint would make every page view fetch everything twice — which is
        # exactly what it used to do. Only genuine changes after this point are worth a round trip.
        previous: str | None = await asyncio.to_thread(owner_fingerprint, user.id)
        elapsed = 0.0
        yield "retry: 1500\n\n"
        while not await request.is_disconnected():
            fingerprint = await asyncio.to_thread(owner_fingerprint, user.id)
            if fingerprint != previous:
                previous = fingerprint
                payload = json.dumps({"type": "refresh", "fingerprint": fingerprint})
                yield f"event: refresh\ndata: {payload}\n\n"
            elapsed += POLL_SECONDS
            if elapsed >= KEEPALIVE_SECONDS:
                elapsed = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
