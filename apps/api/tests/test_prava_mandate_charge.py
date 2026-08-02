from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.sandbox_settlement import SandboxSettlementExecutor
from app.config import Settings
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
        )

    def report_mandate_charge(self, **_kwargs: object) -> object:
        return SimpleNamespace(status="completed", visa_confirmation="SUCCESS")


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
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
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
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    order = next(item for item in db.added if isinstance(item, PurchaseOrder))
    movement = next(item for item in db.added if isinstance(item, StockMovement))
    assert result.status == "sandbox_settled"
    assert prava.charge_calls == 1
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
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
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
    executor = SandboxSettlementExecutor(
        db,  # type: ignore[arg-type]
        settings=Settings(prava_api_base_url="https://sandbox.api.prava.space"),
        prava=prava,  # type: ignore[arg-type]
    )

    result = executor.execute(
        run=run,
        authorization=authorization,
        amount=Decimal("450"),
        product_description="Ashwagandha",
        product_id="product-1",
        pack_quantity=Decimal("60"),
        pack_unit="tablet",
        explicit_test=True,
    )

    assert result.status == "cancelled"
    assert result.failure_code == "mandate_frequency_wait"
    assert result.next_eligible_at is not None
    assert supply.payment_deferred_until == result.next_eligible_at
    assert prava.charge_calls == 0
