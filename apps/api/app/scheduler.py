from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.runtime import ReplenishmentAgent
from app.database import get_session_factory
from app.models import Beneficiary, Supply


class ReplenishmentScheduler:
    """Starts bounded agent evaluations; it never contains purchase policy itself."""

    def __init__(self, *, interval_minutes: int) -> None:
        if interval_minutes < 1:
            raise ValueError("Scheduler interval must be at least one minute")
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._interval_minutes = interval_minutes

    def start(self, *, recurring: bool) -> None:
        if recurring:
            self._scheduler.add_job(
                self.run_due_evaluations,
                trigger="interval",
                minutes=self._interval_minutes,
                id="replenishment-evaluations",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def run_due_evaluations(self) -> None:
        """Evaluate each enabled, active supply once per interval bucket.

        The agent owns all decisions and persists a unique run per supply/bucket. This worker does
        not manufacture offers, credentials, or checkout results.
        """
        bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
        with get_session_factory()() as db:
            supplies = list(
                db.scalars(
                    select(Supply)
                    .join(Supply.beneficiary)
                    .where(Supply.is_enabled.is_(True), Beneficiary.is_active.is_(True))
                    .options(selectinload(Supply.beneficiary).selectinload(Beneficiary.owner))
                )
            )
            for supply in supplies:
                ReplenishmentAgent(db).start(
                    user=supply.beneficiary.owner,
                    supply=supply,
                    trigger_id=f"scheduled:{supply.id}:{bucket}",
                )

    def schedule_evaluation(
        self, *, owner_id: UUID, supply_id: UUID, run_at: datetime
    ) -> tuple[str, datetime]:
        """Schedule one owner-scoped evaluation; callers must verify ownership before scheduling."""
        normalized_run_at = run_at.astimezone(UTC)
        if normalized_run_at <= datetime.now(UTC):
            raise ValueError("Scheduled evaluation must be in the future")
        job_id = f"scheduled-run:{uuid4()}"
        self._scheduler.add_job(
            self._run_scheduled_evaluation,
            trigger="date",
            run_date=normalized_run_at,
            id=job_id,
            args=[owner_id, supply_id, job_id],
            misfire_grace_time=60,
            replace_existing=False,
        )
        return job_id, normalized_run_at

    @staticmethod
    def _run_scheduled_evaluation(owner_id: UUID, supply_id: UUID, job_id: str) -> None:
        with get_session_factory()() as db:
            supply = db.scalar(
                select(Supply)
                .join(Supply.beneficiary)
                .where(Supply.id == supply_id, Beneficiary.owner_id == owner_id)
                .options(selectinload(Supply.beneficiary).selectinload(Beneficiary.owner))
            )
            if supply is None:
                return
            ReplenishmentAgent(db).start(
                user=supply.beneficiary.owner,
                supply=supply,
                trigger_id=f"scheduled:{job_id}",
            )
