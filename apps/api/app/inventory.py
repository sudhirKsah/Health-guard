from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PurchaseOrder, StockMovement, Supply

STOCK_QUANTUM = Decimal("0.001")


def stock_quantity(value: Decimal) -> Decimal:
    return max(Decimal("0"), value).quantize(STOCK_QUANTUM, rounding=ROUND_HALF_UP)


def estimated_quantity(supply: Supply, *, at: datetime | None = None) -> Decimal:
    now = at or datetime.now(UTC)
    observed_at = supply.inventory_observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    elapsed_days = Decimal(str(max(0.0, (now - observed_at).total_seconds()))) / Decimal(
        "86400"
    )
    return stock_quantity(supply.quantity_on_hand - supply.daily_consumption * elapsed_days)


def rebase_inventory(supply: Supply, *, at: datetime | None = None) -> Decimal:
    now = at or datetime.now(UTC)
    current = estimated_quantity(supply, at=now)
    supply.quantity_on_hand = current
    supply.inventory_observed_at = now
    return current


def record_stock_count(
    db: Session,
    *,
    supply: Supply,
    quantity_on_hand: Decimal,
    note: str,
    at: datetime | None = None,
) -> StockMovement:
    now = at or datetime.now(UTC)
    previous = estimated_quantity(supply, at=now)
    balance = stock_quantity(quantity_on_hand)
    supply.quantity_on_hand = balance
    supply.inventory_observed_at = now
    movement = StockMovement(
        supply_id=supply.id,
        movement_type="manual_count",
        quantity_delta=balance - previous,
        balance_after=balance,
        unit=supply.unit,
        note=note,
        occurred_at=now,
    )
    db.add(movement)
    return movement


def record_purchased_stock(
    db: Session,
    *,
    supply: Supply,
    purchase_order: PurchaseOrder,
    pack_quantity: Decimal,
    pack_unit: str,
    at: datetime | None = None,
) -> StockMovement:
    existing = db.scalar(
        select(StockMovement).where(StockMovement.purchase_order_id == purchase_order.id)
    )
    if existing is not None:
        return existing
    if pack_unit != supply.unit:
        raise ValueError("Purchased pack unit does not match the supply inventory unit")
    now = at or datetime.now(UTC)
    previous = estimated_quantity(supply, at=now)
    purchased = stock_quantity(pack_quantity)
    balance = stock_quantity(previous + purchased)
    supply.quantity_on_hand = balance
    supply.inventory_observed_at = now
    purchase_order.purchased_quantity = purchased
    purchase_order.purchased_unit = pack_unit
    movement = StockMovement(
        supply_id=supply.id,
        purchase_order_id=purchase_order.id,
        movement_type="automatic_purchase",
        quantity_delta=purchased,
        balance_after=balance,
        unit=pack_unit,
        note=f"Added {purchased} {pack_unit}(s) from an approved recurring purchase.",
        occurred_at=now,
    )
    db.add(movement)
    return movement
