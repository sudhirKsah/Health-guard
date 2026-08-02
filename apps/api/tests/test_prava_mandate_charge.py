from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.sandbox_settlement import SandboxSettlementExecutor
from app.config import Settings
from app.integrations.merchant_checkout import (
    CHECKOUT_DECLINED,
    CHECKOUT_SUCCEEDED,
    CheckoutOutcome,
    DeliveryAddress,
    UnavailableCheckoutExecutor,
)
from app.integrations.prava import PravaClient
from app.models import (
    AgentRun,
    LedgerEvent,
    MerchantAuthorization,
    PurchaseOrder,
    StockMovement,
    Supply,
)


class FakeSettlementDb:
    def __init__(self, scalar_results: list[object | None]) -> None:
        self.scalar_results = scalar_results
        self.added: list[object] = []
        self.commits = 0

    def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def add(self, item: object) -> None:
        if isinstance(item, PurchaseOrder) and item.id is None:
            item.id = uuid4()
        self.added.append(item)

    def commit(self) -> None:
        self.commits += 1


class FakeSettlementPrava:
    def __init__(self, *, last_charge_at: datetime | None = None) -> None:
        self.charge_calls = 0
        self.last_charge_at = last_charge_at

    def list_standing_mandates(self, **_kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "id": "mdt_stock",
                "status": "active",
                "approvedAmount": "600.00",
                "remaining": "600.00",
                "currency": "INR",
                "recurringFrequency": "monthly",
                "renewsAt": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                "lastCharge": (
                    {"status": "APPROVED", "at": self.last_charge_at.isoformat()}
                    if self.last_charge_at
                    else None
                ),
            }
        ]

    def charge_mandate(self, **_kwargs: object) -> object:
        self.charge_calls += 1
        return SimpleNamespace(
            status="awaiting_result",
            transaction_id="txn_stock",
            order_id="ord_stock",
            error_code=None,
            credentials=SimpleNamespace(
                token="4111111111111111",
                dynamic_cvv="123",
                expiry_month="12",
                expiry_year="2030",
            ),
        )

    def report_mandate_charge(self, **kwargs: object) -> object:
        self.reported_status = kwargs.get("transaction_status")
        self.reported_amount = kwargs.get("amount_paid")
        return SimpleNamespace(status="completed", visa_confirmation="SUCCESS")


class FakeCheckout:
    """Stands in for the merchant checkout leg without touching a browser or a real store."""

    def __init__(self, outcome: CheckoutOutcome) -> None:
        self.outcome = outcome
        self.calls = 0
        self.seen_token: str | None = None

    def checkout(self, *, credentials, **_kwargs: object) -> CheckoutOutcome:
        self.calls += 1
        self.seen_token = credentials.token
        return self.outcome


def succeeding_checkout() -> FakeCheckout:
    return FakeCheckout(
        CheckoutOutcome(CHECKOUT_SUCCEEDED, merchant_order_id="ord_merchant_1", response_code="00")
    )


def declining_checkout() -> FakeCheckout:
    return FakeCheckout(CheckoutOutcome(CHECKOUT_DECLINED, decline_code="merchant_declined"))


ADDRESS = DeliveryAddress(
    recipient="Ashutosh Vats",
    line1="1 Test Street",
    city="Kochi",
    region="Kerala",
    postal_code="690525",
    country="IN",
)


def settlement_entities() -> tuple[AgentRun, MerchantAuthorization, Supply]:
    supply = Supply(
        id=uuid4(),
        name="Ashwagandha",
        unit="tablet",
        daily_consumption=Decimal("1"),
        quantity_on_hand=Decimal("5"),
        safety_buffer_quantity=Decimal("7"),
        inventory_observed_at=datetime.now(UTC),
        is_enabled=True,
    )
    run = AgentRun(id=uuid4(), owner_id=uuid4(), supply_id=supply.id)
    authorization = MerchantAuthorization(
        id=uuid4(),
        merchant_name="Himalaya Wellness",
        merchant_domain="himalayawellness.in",
        prava_mandate_id="mdt_stock",
        mandate_currency="INR",
    )
    return run, authorization, supply


def client_with_response(response: dict[str, object]) -> tuple[PravaClient, dict[str, object]]:
    client = object.__new__(PravaClient)
    captured: dict[str, object] = {}

    def request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        captured.update({"method": method, "path": path, **kwargs})
        return response

    client._request = request  # type: ignore[method-assign]
    return client, captured


def test_charge_mandate_uses_stable_reference_and_keeps_credentials_in_memory() -> None:
    client, captured = client_with_response(
        {
            "mandateId": "mdt_123",
            "instructionId": "ins_123",
            "transactionId": "txn_123",
            "orderId": "ord_123",
            "status": "awaiting_result",
            "fetchStatus": "SUCCESS",
            "credentials": {
                "token": "4111111111111111",
                "dynamicCvv": "123",
                "expiryMonth": "12",
                "expiryYear": "2030",
            },
            "deduplicated": False,
        }
    )

    result = client.charge_mandate(
        mandate_id="mdt_123",
        amount=Decimal("450"),
        reference="run:123",
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/mandates/mdt_123/charge"
    assert captured["json"] == {"amount": "450.00", "reference": "run:123"}
    assert result.transaction_id == "txn_123"
    assert result.credentials is not None
    assert result.credentials.token == "4111111111111111"
    assert not hasattr(result, "raw_response")


def test_charge_mandate_rejects_success_response_without_credential() -> None:
    client, _ = client_with_response(
        {"mandateId": "mdt_123", "transactionId": "txn_123", "status": "awaiting_result"}
    )

    with pytest.raises(RuntimeError, match="one-time credentials"):
        client.charge_mandate(
            mandate_id="mdt_123", amount=Decimal("450.00"), reference="run:123"
        )


def test_report_mandate_charge_uses_report_endpoint() -> None:
    client, captured = client_with_response(
        {
            "mandateId": "mdt_123",
            "transactionId": "txn_123",
            "orderId": "ord_123",
            "status": "completed",
            "mandateStatus": "active",
            "visaConfirmation": "SUCCESS",
        }
    )

    report = client.report_mandate_charge(
        mandate_id="mdt_123",
        transaction_id="txn_123",
        transaction_status="APPROVED",
        amount_paid=Decimal("450"),
        authorization_code="OK123",
        response_code="00",
    )

    assert captured["path"] == "/v1/mandates/mdt_123/charges/txn_123/report"
    assert captured["json"] == {
        "txn_status": "APPROVED",
        "txn_type": "PURCHASE",
        "amount_paid": "450.00",
        "authorization_code": "OK123",
        "response_code": "00",
    }
    assert report.status == "completed"
    assert report.visa_confirmation == "SUCCESS"


def test_report_mandate_charge_rejects_unknown_status() -> None:
    client, _ = client_with_response({})

    with pytest.raises(ValueError, match="APPROVED or DECLINED"):
        client.report_mandate_charge(
            mandate_id="mdt_123", transaction_id="txn_123", transaction_status="PENDING"
        )


def test_explicit_payment_test_is_allowed_only_against_prava_sandbox() -> None:
    sandbox = SandboxSettlementExecutor(
        None,  # type: ignore[arg-type]
        settings=Settings(
            prava_api_base_url="https://sandbox.api.prava.space",
            health_guard_sandbox_settlement_enabled=False,
        ),
    )
    production = SandboxSettlementExecutor(
        None,  # type: ignore[arg-type]
        settings=Settings(
            prava_api_base_url="https://api.prava.space",
            health_guard_sandbox_settlement_enabled=True,
        ),
    )

    assert sandbox.enabled() is False
    assert sandbox.enabled(explicit_test=True) is True
    assert production.enabled(explicit_test=True) is False


def test_deleted_supply_is_cancelled_at_the_final_gate_before_prava_charge() -> None:
    run, authorization, _supply = settlement_entities()
    db = FakeSettlementDb([None, authorization, None])
    prava = FakeSettlementPrava()
    checkout = succeeding_checkout()
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=checkout,
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    assert result.status == "cancelled"
    assert result.failure_code == "supply_deleted_or_paused"
    assert prava.charge_calls == 0


def test_approved_purchase_adds_pack_to_stock_exactly_once() -> None:
    run, authorization, supply = settlement_entities()
    db = FakeSettlementDb([None, authorization, supply, None])
    prava = FakeSettlementPrava()
    checkout = succeeding_checkout()
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=checkout,
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    order = next(item for item in db.added if isinstance(item, PurchaseOrder))
    movement = next(item for item in db.added if isinstance(item, StockMovement))
    assert result.status == "completed"
    assert result.merchant_order_id == "ord_merchant_1"
    assert prava.charge_calls == 1
    # The one-time card reached the merchant leg, and only then was APPROVED settled.
    assert checkout.calls == 1
    assert checkout.seen_token == "4111111111111111"
    assert prava.reported_status == "APPROVED"
    assert order.merchant_order_id == "ord_merchant_1"
    assert supply.quantity_on_hand == Decimal("65.000")
    assert order.purchased_quantity == Decimal("60.000")
    assert movement.quantity_delta == Decimal("60.000")
    assert movement.balance_after == Decimal("65.000")
    assert any(isinstance(item, LedgerEvent) for item in db.added)


def test_concurrent_run_is_cancelled_after_first_order_replenishes_stock() -> None:
    run, authorization, supply = settlement_entities()
    supply.quantity_on_hand = Decimal("65")
    db = FakeSettlementDb([None, authorization, supply])
    prava = FakeSettlementPrava()
    checkout = succeeding_checkout()
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=checkout,
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    assert result.status == "cancelled"
    assert result.failure_code == "supply_no_longer_due"
    assert prava.charge_calls == 0


def test_second_charge_in_same_mandate_cycle_is_stopped_before_prava_charge() -> None:
    run, authorization, supply = settlement_entities()
    db = FakeSettlementDb([None, authorization, supply])
    prava = FakeSettlementPrava(last_charge_at=datetime.now(UTC) - timedelta(hours=1))
    checkout = succeeding_checkout()
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=checkout,
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    assert result.status == "cancelled"
    assert result.failure_code == "mandate_frequency_wait"
    assert result.next_eligible_at is not None
    assert supply.payment_deferred_until == result.next_eligible_at
    assert prava.charge_calls == 0


def test_merchant_decline_is_reported_declined_and_never_adds_stock() -> None:
    """The expected sandbox end-to-end result: the card reaches the merchant and is refused."""
    run, authorization, supply = settlement_entities()
    db = FakeSettlementDb([None, authorization, supply])
    prava = FakeSettlementPrava()
    checkout = declining_checkout()
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=checkout,
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    order = next(item for item in db.added if isinstance(item, PurchaseOrder))
    assert result.status == "checkout_declined"
    assert checkout.calls == 1
    assert prava.charge_calls == 1
    assert prava.reported_status == "DECLINED"
    # A decline must not claim an amount was paid.
    assert prava.reported_amount is None
    assert order.report_status == "DECLINED"
    assert order.merchant_order_id is None
    assert order.checkout_attempted_at is not None
    # Nothing shipped, so tracked stock is untouched and no movement was written.
    assert supply.quantity_on_hand == Decimal("5")
    assert not any(isinstance(item, StockMovement) for item in db.added)
    # The mandate cycle is not consumed by a decline, so a genuine retry stays possible.
    assert authorization.mandate_last_charge_status == "DECLINED"


def test_missing_checkout_capability_never_settles_as_approved() -> None:
    """With no checkout executor configured, a charge can only ever settle DECLINED."""
    run, authorization, supply = settlement_entities()
    db = FakeSettlementDb([None, authorization, supply])
    prava = FakeSettlementPrava()
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=UnavailableCheckoutExecutor(),
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    assert result.status == "checkout_declined"
    assert result.failure_code == "merchant_checkout_not_configured"
    assert prava.reported_status == "DECLINED"
    assert supply.quantity_on_hand == Decimal("5")


def test_checkout_outcome_only_maps_a_real_order_to_approved() -> None:
    assert CheckoutOutcome(CHECKOUT_SUCCEEDED, merchant_order_id="o1").prava_report_status == "APPROVED"
    assert CheckoutOutcome(CHECKOUT_DECLINED).prava_report_status == "DECLINED"
    assert UnavailableCheckoutExecutor().checkout(
        merchant_domain="example.test",
        variant_id="v1",
        quantity=1,
        amount=Decimal("1"),
        currency="INR",
        credentials=SimpleNamespace(token="t", dynamic_cvv="c", expiry_month="12", expiry_year="2030"),
    ).prava_report_status == "DECLINED"


class ReportStatusPrava(FakeSettlementPrava):
    """Echoes the settlement status Prava actually returns for each reported outcome."""

    def report_mandate_charge(self, **kwargs: object) -> object:
        self.reported_status = kwargs.get("transaction_status")
        self.reported_amount = kwargs.get("amount_paid")
        # Verified against the sandbox: DECLINED settles as "failed", APPROVED as "completed".
        settled = "completed" if kwargs.get("transaction_status") == "APPROVED" else "failed"
        return SimpleNamespace(status=settled, visa_confirmation=None)


def _run_settlement(checkout, prava):
    run, authorization, supply = settlement_entities()
    db = FakeSettlementDb([None, authorization, supply])
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
        checkout=checkout,
    )
    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        variant_id="variant-1",
        address=ADDRESS,
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )
    return result, db, supply, authorization


def test_declined_settlement_returning_failed_is_a_completed_settlement() -> None:
    """Prava echoes status="failed" for a DECLINED report. That is a settled decline, not an error."""
    prava = ReportStatusPrava()
    result, db, supply, authorization = _run_settlement(declining_checkout(), prava)

    assert prava.reported_status == "DECLINED"
    assert result.status == "checkout_declined"
    assert result.failure_code == "merchant_declined"
    order = next(item for item in db.added if isinstance(item, PurchaseOrder))
    assert order.report_status == "DECLINED"
    assert order.reported_at is not None
    assert supply.quantity_on_hand == Decimal("5")


def test_approved_report_that_prava_does_not_confirm_is_never_a_purchase() -> None:
    """If we claim a merchant order but Prava settles "failed", refuse to record a purchase."""

    class DisagreeingPrava(FakeSettlementPrava):
        def report_mandate_charge(self, **kwargs: object) -> object:
            self.reported_status = kwargs.get("transaction_status")
            return SimpleNamespace(status="failed", visa_confirmation=None)

    result, db, supply, _ = _run_settlement(succeeding_checkout(), DisagreeingPrava())

    assert result.status == "report_failed"
    assert result.failure_code == "approved_settlement_not_confirmed"
    assert supply.quantity_on_hand == Decimal("5")
    assert not any(isinstance(item, StockMovement) for item in db.added)
