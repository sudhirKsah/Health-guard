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
    Supply,
    User,
)

router = APIRouter(prefix="/events", tags=["realtime updates"])


def _stamp(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def owner_fingerprint(owner_id: UUID) -> str:
    with get_session_factory()() as db:
        values = [
            db.scalar(
                select(func.max(Beneficiary.updated_at)).where(Beneficiary.owner_id == owner_id)
            ),
            db.scalar(
                select(func.max(Supply.updated_at))
                .join(Supply.beneficiary)
                .where(Beneficiary.owner_id == owner_id)
            ),
            db.scalar(
                select(func.max(MerchantAuthorization.updated_at)).where(
                    MerchantAuthorization.owner_id == owner_id
                )
            ),
            db.scalar(
                select(func.max(ApprovedVariant.updated_at))
                .join(ApprovedVariant.equivalence_set)
                .join(ProductEquivalenceSet.supply)
                .join(Supply.beneficiary)
                .where(Beneficiary.owner_id == owner_id)
            ),
            db.scalar(
                select(func.max(AgentRun.completed_at)).where(AgentRun.owner_id == owner_id)
            ),
            db.scalar(
                select(func.max(PurchaseOrder.updated_at)).where(PurchaseOrder.owner_id == owner_id)
            ),
            db.scalar(
                select(func.max(LedgerEvent.created_at)).where(LedgerEvent.owner_id == owner_id)
            ),
        ]
    return "|".join(_stamp(value) for value in values)


@router.get("/stream")
async def stream_updates(
    request: Request,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    async def events():
        previous: str | None = None
        heartbeat = 0
        yield "retry: 1500\n\n"
        while not await request.is_disconnected():
            fingerprint = await asyncio.to_thread(owner_fingerprint, user.id)
            if fingerprint != previous:
                previous = fingerprint
                payload = json.dumps({"type": "refresh", "fingerprint": fingerprint})
                yield f"event: refresh\ndata: {payload}\n\n"
            heartbeat += 1
            if heartbeat >= 15:
                heartbeat = 0
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
