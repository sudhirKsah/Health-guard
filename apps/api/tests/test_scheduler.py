from datetime import UTC, datetime

from app.scheduler import ReplenishmentScheduler, interval_on_or_after


def test_scheduler_rejects_a_non_positive_interval() -> None:
    try:
        ReplenishmentScheduler(interval_minutes=0)
    except ValueError as error:
        assert str(error) == "Scheduler interval must be at least one minute"
    else:
        raise AssertionError("A zero-minute interval must not create a worker")


def test_interval_timing_returns_first_worker_run_for_an_already_due_supply() -> None:
    first_run = datetime(2026, 8, 2, 10, 30, tzinfo=UTC)

    assert interval_on_or_after(
        first_run=first_run,
        threshold_at=datetime(2026, 8, 2, 9, 0, tzinfo=UTC),
        interval_minutes=60,
    ) == first_run


def test_interval_timing_rounds_future_threshold_up_to_the_next_worker_run() -> None:
    assert interval_on_or_after(
        first_run=datetime(2026, 8, 2, 10, 30, tzinfo=UTC),
        threshold_at=datetime(2026, 8, 2, 12, 31, tzinfo=UTC),
        interval_minutes=60,
    ) == datetime(2026, 8, 2, 13, 30, tzinfo=UTC)
