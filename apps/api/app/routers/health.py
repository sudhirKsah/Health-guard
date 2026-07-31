from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_engine
from app.integrations.prava import PravaClient, PravaUnavailableError
from app.integrations.ucp import UcpAdapter

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from error
    return {"status": "ok"}


@router.get("/integrations/prava/health")
async def prava_health() -> dict[str, object]:
    try:
        return await PravaClient().health()
    except PravaUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prava sandbox is unavailable",
        ) from error


@router.get("/integrations/ucp/readiness")
def ucp_readiness() -> dict[str, str | bool | None]:
    readiness = UcpAdapter().readiness()
    return {"ready": readiness.ready, "reason": readiness.reason}
