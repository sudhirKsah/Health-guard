from app.scheduler import ReplenishmentScheduler


def test_scheduler_rejects_a_non_positive_interval() -> None:
    try:
        ReplenishmentScheduler(interval_minutes=0)
    except ValueError as error:
        assert str(error) == "Scheduler interval must be at least one minute"
    else:
        raise AssertionError("A zero-minute interval must not create a worker")
