import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import dispose_database
from app.routers.activity import router as activity_router
from app.routers.agent_runs import router as agent_runs_router
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.ledger import router as ledger_router
from app.routers.mandates import router as mandates_router
from app.routers.realtime import router as realtime_router
from app.routers.setup import router as setup_router
from app.scheduler import ReplenishmentScheduler
from app.security import RedactingLogFilter


def configure_logging() -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(RedactingLogFilter())


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        scheduler = ReplenishmentScheduler(interval_minutes=settings.scheduler_interval_minutes)
        application.state.replenishment_scheduler = scheduler
        scheduler.start(recurring=settings.scheduler_enabled)
        try:
            yield
        finally:
            scheduler.shutdown()
            dispose_database()

    application = FastAPI(
        title="Health Guard API",
        version="0.1.0",
        description=(
            "Backend boundary for Health Guard's real inventory, UCP, and Prava integrations."
        ),
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        # Every authenticated request is preflighted. Without this the browser re-asks before each
        # one, doubling request volume for no benefit.
        max_age=600,
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(setup_router, prefix="/api/v1")
    application.include_router(mandates_router, prefix="/api/v1")
    application.include_router(agent_runs_router, prefix="/api/v1")
    application.include_router(ledger_router, prefix="/api/v1")
    application.include_router(activity_router, prefix="/api/v1")
    application.include_router(realtime_router, prefix="/api/v1")
    return application


app = create_app()
