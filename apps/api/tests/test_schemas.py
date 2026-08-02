from decimal import Decimal
from uuid import uuid4

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


def test_beneficiary_dashboard_stays_in_sync_with_the_beneficiary_model() -> None:
    """The dashboard builds this model from the ORM row, so every output field must be derivable.

    Constructing it field-by-field once caused a 500 on /setup/dashboard when new beneficiary
    columns were added. This pins that BeneficiaryOut covers everything the dashboard needs.
    """
    from types import SimpleNamespace

    from app.schemas import BeneficiaryDashboard, BeneficiaryOut

    row = SimpleNamespace(
        id=uuid4(),
        name="Test Person",
        relationship_label="Parent",
        is_active=True,
        delivery_recipient=None,
        delivery_email=None,
        delivery_phone=None,
        delivery_line1=None,
        delivery_line2=None,
        delivery_city=None,
        delivery_region=None,
        delivery_postal_code=None,
        delivery_country="IN",
        has_delivery_address=False,
    )

    dashboard = BeneficiaryDashboard(
        **BeneficiaryOut.model_validate(row).model_dump(), supplies=[]
    )

    assert dashboard.has_delivery_address is False
    assert dashboard.delivery_country == "IN"
    # Every non-supply field on the dashboard model must come from BeneficiaryOut.
    assert set(BeneficiaryDashboard.model_fields) - {"supplies"} == set(BeneficiaryOut.model_fields)
