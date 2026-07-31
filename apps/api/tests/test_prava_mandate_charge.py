from decimal import Decimal

import pytest

from app.integrations.prava import PravaClient


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
