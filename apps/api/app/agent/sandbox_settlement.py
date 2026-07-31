from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.prava import PravaApiError, PravaClient, PravaUnavailableError
from app.models import AgentRun, MerchantAuthorization, PurchaseOrder


@dataclass(frozen=True)
class SandboxSettlementResult:
    status: str
    failure_code: str | None


class SandboxSettlementExecutor:
    """Runs Prava's documented sandbox settlement flow without inventing merchant fulfillment."""

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        prava: PravaClient | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._prava = prava or PravaClient(self._settings)

    def enabled(self) -> bool:
        return (
            self._settings.health_guard_sandbox_settlement_enabled
            and self._settings.prava_api_base_url.host == "sandbox.api.prava.space"
        )

    def execute(
        self,
        *,
        run: AgentRun,
        authorization: MerchantAuthorization,
        amount: Decimal,
        product_description: str,
        product_id: str,
        quantity: int = 1,
    ) -> SandboxSettlementResult:
        if not self.enabled():
            return SandboxSettlementResult("blocked", "sandbox_settlement_not_enabled")
        if not authorization.prava_mandate_id:
            return SandboxSettlementResult("blocked", "mandate_id_missing")
        order = self._db.scalar(
            select(PurchaseOrder).where(PurchaseOrder.agent_run_id == run.id)
        )
        if order is not None:
            return SandboxSettlementResult(order.status, order.failure_code)

        order = PurchaseOrder(
            owner_id=run.owner_id,
            agent_run_id=run.id,
            merchant_authorization_id=authorization.id,
            charge_reference=f"agent-run:{run.id}",
            requested_amount=amount,
            currency=authorization.mandate_currency or "INR",
            status="prepared",
            prava_mandate_id=authorization.prava_mandate_id,
        )
        self._db.add(order)
        # Persist the deterministic reference before the remote call. A retry can never create a
        # second charge for the same run, even if this process stops after Prava receives it.
        self._db.commit()

        try:
            charge = self._prava.charge_mandate(
                mandate_id=authorization.prava_mandate_id,
                amount=amount,
                reference=order.charge_reference,
                purchase_context=[
                    {
                        "merchant_details": {
                            "name": authorization.merchant_name,
                            "url": f"https://{authorization.merchant_domain}",
                            "country_code_iso2": "IN",
                        },
                        "product_details": [
                            {
                                "description": product_description,
                                "product_id": product_id[:50],
                                "unit_price": f"{amount:.2f}",
                                "quantity": quantity,
                            }
                        ],
                    }
                ],
            )
        except (PravaApiError, PravaUnavailableError) as error:
            order.status = "charge_failed"
            order.failure_code = getattr(error, "code", None) or "prava_charge_unavailable"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        if charge.status != "awaiting_result" or not charge.transaction_id:
            order.status = "charge_failed"
            order.failure_code = charge.error_code or "prava_charge_not_ready"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        order.prava_transaction_id = charge.transaction_id
        order.prava_order_id = charge.order_id
        order.charged_amount = amount
        order.status = "sandbox_settling"
        order.charged_at = datetime.now(UTC)
        self._db.commit()

        try:
            report = self._prava.report_mandate_charge(
                mandate_id=authorization.prava_mandate_id,
                transaction_id=charge.transaction_id,
                transaction_status="APPROVED",
                amount_paid=amount,
            )
        except (PravaApiError, PravaUnavailableError) as error:
            order.status = "report_failed"
            order.failure_code = getattr(error, "code", None) or "prava_report_unavailable"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        if report.status != "completed" or report.visa_confirmation != "SUCCESS":
            order.status = "report_failed"
            order.failure_code = "sandbox_settlement_not_confirmed"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        order.status = "sandbox_settled"
        order.report_status = "APPROVED"
        order.reported_at = datetime.now(UTC)
        order.failure_code = None
        self._db.commit()
        return SandboxSettlementResult(order.status, None)
