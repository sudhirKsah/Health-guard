from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

RECURRING_FREQUENCIES = {"weekly", "monthly", "yearly"}
APPROVED_CHARGE_STATUSES = {"approved", "completed", "success"}


@dataclass(frozen=True)
class MandateChargeWindow:
    eligible: bool
    reason: str | None = None
    next_eligible_at: datetime | None = None


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _shift_month(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + (value.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def shift_cycle(value: datetime, frequency: str, cycles: int) -> datetime:
    normalized = utc_datetime(value)
    if normalized is None:
        raise ValueError("A cycle boundary is required")
    if frequency == "weekly":
        return normalized + timedelta(weeks=cycles)
    if frequency == "monthly":
        return _shift_month(normalized, cycles)
    if frequency == "yearly":
        target_year = normalized.year + cycles
        day = min(normalized.day, calendar.monthrange(target_year, normalized.month)[1])
        return normalized.replace(year=target_year, day=day)
    raise ValueError(f"Unsupported recurring mandate frequency: {frequency}")


def current_cycle_boundaries(
    *, renews_at: datetime, frequency: str, observed_at: datetime
) -> tuple[datetime, datetime]:
    """Return the current cycle start and next boundary using Prava's renewal anchor."""
    now = utc_datetime(observed_at)
    renewal_anchor = utc_datetime(renews_at)
    if now is None or renewal_anchor is None:
        raise ValueError("Cycle timestamps are required")
    cycle_offset = 0
    next_boundary = renewal_anchor
    while next_boundary <= now:
        cycle_offset += 1
        next_boundary = shift_cycle(renewal_anchor, frequency, cycle_offset)
    return shift_cycle(renewal_anchor, frequency, cycle_offset - 1), next_boundary


def mandate_charge_window(
    *,
    frequency: str | None,
    renews_at: datetime | None,
    last_charge_at: datetime | None,
    last_charge_status: str | None,
    approved_amount: Decimal | None = None,
    remaining_amount: Decimal | None = None,
    observed_at: datetime | None = None,
) -> MandateChargeWindow:
    """Enforce Prava's documented one-approved-charge-per-cycle rule locally."""
    if frequency not in RECURRING_FREQUENCIES:
        return MandateChargeWindow(eligible=True)
    normalized_status = (last_charge_status or "").casefold()
    last_charge = utc_datetime(last_charge_at)
    approved_charge_recorded = (
        last_charge is not None and normalized_status in APPROVED_CHARGE_STATUSES
    )
    now = utc_datetime(observed_at or datetime.now(UTC))
    if now is None:
        raise ValueError("An observation time is required")
    renewal = utc_datetime(renews_at)
    cycle_spend_recorded = (
        approved_amount is not None
        and remaining_amount is not None
        and remaining_amount < approved_amount
        and renewal is not None
        and renewal > now
    )
    if not approved_charge_recorded and not cycle_spend_recorded:
        return MandateChargeWindow(eligible=True)
    if renews_at is None:
        return MandateChargeWindow(
            eligible=False,
            reason="mandate_cycle_boundary_unknown",
        )
    cycle_start, next_boundary = current_cycle_boundaries(
        renews_at=renews_at,
        frequency=frequency,
        observed_at=now,
    )
    if cycle_spend_recorded or (
        last_charge is not None and cycle_start <= last_charge < next_boundary
    ):
        return MandateChargeWindow(
            eligible=False,
            reason="mandate_frequency_wait",
            next_eligible_at=next_boundary,
        )
    return MandateChargeWindow(eligible=True)
