from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import PaymentTestRequest, SupplyCreate


def test_supply_allows_health_guard_to_choose_a_product() -> None:
    supply = SupplyCreate(
        name="Ashwagandha",
        unit="tablet",
        daily_consumption=Decimal("1"),
        quantity_on_hand=Decimal("10"),
        safety_buffer_quantity=Decimal("5"),
    )

    assert supply.product_requirements is None


def test_payment_test_requires_an_explicit_confirmation_and_scoped_trigger() -> None:
    request = PaymentTestRequest(
        confirmed=True,
        trigger_id="payment-test:123e4567-e89b-12d3-a456-426614174000",
    )

    assert request.confirmed is True
    with pytest.raises(ValidationError):
        PaymentTestRequest(confirmed=False, trigger_id="manual:unsafe")


def test_supply_requires_positive_daily_consumption() -> None:
    with pytest.raises(ValidationError):
        SupplyCreate(
            name="Glucose strips",
            unit="strips",
            daily_consumption=Decimal("0"),
            quantity_on_hand=Decimal("10"),
            safety_buffer_quantity=Decimal("2"),
        )
