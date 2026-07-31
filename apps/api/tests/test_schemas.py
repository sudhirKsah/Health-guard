from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import SupplyCreate


def test_supply_requires_positive_daily_consumption() -> None:
    with pytest.raises(ValidationError):
        SupplyCreate(
            name="Glucose strips",
            unit="strips",
            daily_consumption=Decimal("0"),
            quantity_on_hand=Decimal("10"),
            safety_buffer_quantity=Decimal("2"),
        )
