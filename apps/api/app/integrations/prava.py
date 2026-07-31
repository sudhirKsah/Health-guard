from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config import Settings, get_settings


class PravaUnavailableError(RuntimeError):
    """Raised when Prava cannot be reached or returns a non-success response."""


class PravaConfigurationError(RuntimeError):
    """Raised before a call when Health Guard has no server-side Prava secret key."""


class PravaApiError(RuntimeError):
    """A safe error boundary that retains only an upstream code and invalid field names."""

    def __init__(
        self, message: str, *, status_code: int | None = None, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class MandateCardCredentials:
    """Single-use card credentials. Keep this object in process memory only."""

    token: str
    dynamic_cvv: str
    expiry_month: str
    expiry_year: str


@dataclass(frozen=True)
class MandateCharge:
    """Safe metadata plus an ephemeral credential for one merchant checkout."""

    mandate_id: str
    instruction_id: str | None
    transaction_id: str
    order_id: str | None
    status: str
    fetch_status: str | None
    credentials: MandateCardCredentials | None
    deduplicated: bool
    error_code: str | None


@dataclass(frozen=True)
class MandateChargeReport:
    mandate_id: str | None
    transaction_id: str | None
    order_id: str | None
    status: str | None
    mandate_status: str | None
    visa_confirmation: str | None


def parse_prava_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_prava_amount(value: object) -> Decimal | None:
    if not isinstance(value, str | int | float):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


class PravaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def health(self) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(
                base_url=str(self._settings.prava_api_base_url), timeout=10.0
            ) as client:
                response = await client.get("/health")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PravaUnavailableError("Prava sandbox is unavailable") from error

        return {
            "status": payload.get("status"),
            "timestamp": payload.get("timestamp"),
        }

    def create_mandate_setup(
        self,
        *,
        external_user_id: str,
        user_email: str,
        merchant_name: str,
        merchant_url: str,
        approved_amount: Decimal,
        currency: str,
        recurring_frequency: str,
        max_charges: int,
        valid_until: datetime,
    ) -> dict[str, object]:
        amount = f"{approved_amount:.2f}"
        payload: dict[str, object] = {
            "user_id": external_user_id,
            "user_email": user_email,
            "total_amount": amount,
            "currency": currency,
            "purchase_context": [
                {
                    "merchant_details": {
                        "name": merchant_name,
                        "url": merchant_url,
                        "country_code_iso2": "IN",
                    },
                    "product_details": [
                        {
                            "description": "Health Guard recurring care supplies authorization",
                            "unit_price": amount,
                            "product_id": "health-guard-recurring-care",
                            "quantity": 1,
                        }
                    ],
                }
            ],
            "integration_type": "full_checkout",
            "description": f"Health Guard authorization for {merchant_name}",
            "mandate_setup": {
                "intent": "mandate_setup",
                "recurring_frequency": recurring_frequency,
                "merchant_scope": "listed",
                "max_charges": max_charges,
            },
        }
        # The published API reference documents mandate_setup.valid_until, but the live sandbox currently
        # rejects that field. Health Guard enforces this owner-selected stop date in its policy and records
        # Prava's actual horizon when it becomes available via mandate sync.
        del valid_until
        return self._request("POST", "/v1/sessions", json=payload)

    def list_standing_mandates(self, *, external_user_id: str) -> list[dict[str, object]]:
        payload = self._request(
            "GET",
            "/v1/mandates",
            params={"customer_id": external_user_id, "standing_only": "true"},
        )
        mandates = payload.get("mandates")
        if not isinstance(mandates, list):
            raise PravaApiError("Prava returned an invalid mandate list")
        return [item for item in mandates if isinstance(item, dict)]

    def mandate_lifecycle(self, *, mandate_id: str, action: str) -> dict[str, object]:
        if action not in {"pause", "resume", "cancel"}:
            raise ValueError("Unsupported mandate action")
        return self._request("POST", f"/v1/mandates/{mandate_id}/{action}")

    def charge_mandate(
        self,
        *,
        mandate_id: str,
        amount: Decimal,
        reference: str,
        purchase_context: list[dict[str, object]] | None = None,
    ) -> MandateCharge:
        """Mint an ephemeral, single-use credential against an active mandate.

        The caller is responsible for using the credential immediately in a server-side merchant
        checkout and reporting the result. This method intentionally neither logs nor persists it.
        """
        if not mandate_id:
            raise ValueError("A mandate id is required")
        if amount <= 0:
            raise ValueError("Charge amount must be positive")
        if not reference or len(reference) > 255:
            raise ValueError("A charge reference between 1 and 255 characters is required")
        payload: dict[str, object] = {
            "amount": f"{amount.quantize(Decimal('0.01')):.2f}",
            "reference": reference,
        }
        if purchase_context is not None:
            payload["purchase_context"] = purchase_context
        response = self._request("POST", f"/v1/mandates/{mandate_id}/charge", json=payload)
        status = response.get("status") if isinstance(response.get("status"), str) else "failed"
        transaction_id = response.get("transactionId")
        if status == "awaiting_result" and not isinstance(transaction_id, str):
            raise PravaApiError("Prava returned a charge without a transaction id")
        credentials = self._parse_charge_credentials(response.get("credentials"))
        if status == "awaiting_result" and credentials is None:
            raise PravaApiError("Prava returned a charge without one-time credentials")
        return MandateCharge(
            mandate_id=(
                response["mandateId"]
                if isinstance(response.get("mandateId"), str)
                else mandate_id
            ),
            instruction_id=(
                response["instructionId"] if isinstance(response.get("instructionId"), str) else None
            ),
            transaction_id=transaction_id if isinstance(transaction_id, str) else "",
            order_id=response["orderId"] if isinstance(response.get("orderId"), str) else None,
            status=status,
            fetch_status=(
                response["fetchStatus"] if isinstance(response.get("fetchStatus"), str) else None
            ),
            credentials=credentials,
            deduplicated=response.get("deduplicated") is True,
            error_code=response["errorCode"] if isinstance(response.get("errorCode"), str) else None,
        )

    def report_mandate_charge(
        self,
        *,
        mandate_id: str,
        transaction_id: str,
        transaction_status: str,
        amount_paid: Decimal | None = None,
        authorization_code: str | None = None,
        response_code: str | None = None,
    ) -> MandateChargeReport:
        """Settle the mandate charge after the merchant checkout succeeds or fails."""
        if transaction_status not in {"APPROVED", "DECLINED"}:
            raise ValueError("Mandate transaction status must be APPROVED or DECLINED")
        if not mandate_id or not transaction_id:
            raise ValueError("A mandate id and transaction id are required")
        payload: dict[str, object] = {"txn_status": transaction_status, "txn_type": "PURCHASE"}
        if amount_paid is not None:
            if amount_paid <= 0:
                raise ValueError("Reported amount must be positive")
            payload["amount_paid"] = f"{amount_paid.quantize(Decimal('0.01')):.2f}"
        if authorization_code:
            payload["authorization_code"] = authorization_code[:128]
        if response_code:
            payload["response_code"] = response_code[:2]
        response = self._request(
            "POST",
            f"/v1/mandates/{mandate_id}/charges/{transaction_id}/report",
            json=payload,
        )
        return MandateChargeReport(
            mandate_id=response["mandateId"] if isinstance(response.get("mandateId"), str) else None,
            transaction_id=(
                response["transactionId"] if isinstance(response.get("transactionId"), str) else None
            ),
            order_id=response["orderId"] if isinstance(response.get("orderId"), str) else None,
            status=response["status"] if isinstance(response.get("status"), str) else None,
            mandate_status=(
                response["mandateStatus"] if isinstance(response.get("mandateStatus"), str) else None
            ),
            visa_confirmation=(
                response["visaConfirmation"]
                if isinstance(response.get("visaConfirmation"), str)
                else None
            ),
        )

    @staticmethod
    def _parse_charge_credentials(value: object) -> MandateCardCredentials | None:
        if not isinstance(value, dict):
            return None
        token = value.get("token")
        dynamic_cvv = value.get("dynamicCvv")
        expiry_month = value.get("expiryMonth")
        expiry_year = value.get("expiryYear")
        if not all(isinstance(item, str) and item for item in (token, dynamic_cvv, expiry_month, expiry_year)):
            return None
        return MandateCardCredentials(
            token=token,
            dynamic_cvv=dynamic_cvv,
            expiry_month=expiry_month,
            expiry_year=expiry_year,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, object]:
        secret_key = self._settings.prava_secret_key
        if not secret_key:
            raise PravaConfigurationError("Prava secret key is not configured")
        try:
            with httpx.Client(
                base_url=str(self._settings.prava_api_base_url), timeout=20.0
            ) as client:
                response = client.request(
                    method,
                    path,
                    headers={"Authorization": f"Bearer {secret_key}"},
                    **kwargs,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as error:
            code, invalid_fields = self._safe_error_context(error.response)
            context = f" ({code})" if code else f" (HTTP {error.response.status_code})"
            if invalid_fields:
                context += f"; check: {', '.join(invalid_fields)}"
            raise PravaApiError(
                f"Prava rejected the request{context}",
                status_code=error.response.status_code,
                code=code,
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise PravaUnavailableError("Prava sandbox is unavailable") from error
        if not isinstance(payload, dict):
            raise PravaApiError("Prava returned an invalid response")
        return payload

    @staticmethod
    def _safe_error_context(response: httpx.Response) -> tuple[str | None, list[str]]:
        """Do not pass through Prava messages or values; field names are safe diagnostic metadata."""
        try:
            envelope = response.json()
        except ValueError:
            return None, []
        if not isinstance(envelope, dict) or not isinstance(envelope.get("error"), dict):
            return None, []
        error = envelope["error"]
        code = error.get("code") if isinstance(error.get("code"), str) else None
        details = error.get("details")
        fields: list[object] = []
        if isinstance(details, dict):
            # Prava's validation envelope is {fieldErrors: {field: [...]}, formErrors: [...]};
            # only names are surfaced, never the messages or submitted values.
            field_errors = details.get("fieldErrors")
            fields = sorted(field_errors.keys()) if isinstance(field_errors, dict) else []
            if not fields:
                fields = sorted(key for key in details if key != "formErrors")
        return code, [str(field) for field in fields if isinstance(field, str)][:8]
