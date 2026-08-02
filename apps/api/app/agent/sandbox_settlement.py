from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.prava import (
    PravaApiError,
    PravaClient,
    PravaConfigurationError,
    PravaUnavailableError,
    parse_prava_amount,
    parse_prava_timestamp,
)
from app.inventory import estimated_quantity, record_purchased_stock
from app.mandate_cycles import mandate_charge_window
from app.models import (
    AgentRun,
    Beneficiary,
    LedgerEvent,
    MerchantAuthorization,
    PurchaseOrder,
    Supply,
)


@dataclass(frozen=True)
class SandboxSettlementResult:
    status: str
    failure_code: str | None
    next_eligible_at: datetime | None = None


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

    def enabled(self, *, explicit_test: bool = False) -> bool:
        return (
            (self._settings.health_guard_sandbox_settlement_enabled or explicit_test)
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
        pack_quantity: Decimal,
        pack_unit: str,
        quantity: int = 1,
        explicit_test: bool = False,
    ) -> SandboxSettlementResult:
        if not self.enabled(explicit_test=explicit_test):
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
            purchased_quantity=pack_quantity,
            purchased_unit=pack_unit,
        )
        self._db.add(order)
        # Persist the deterministic reference before the final eligibility gate. A retry can never
        # create a second charge for the same run, even if the process stops after Prava receives it.
        self._db.commit()

        # Serialize every charge sharing this mandate, including charges for different supplies.
        # The lock is held until Prava's result is reported and the local cycle state is committed.
        locked_authorization = self._db.scalar(
            select(MerchantAuthorization)
            .where(MerchantAuthorization.id == authorization.id)
            .with_for_update(of=MerchantAuthorization)
        )
        if locked_authorization is None:
            order.status = "cancelled"
            order.failure_code = "mandate_authorization_missing"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)
        authorization = locked_authorization

        sync_failure = self._sync_mandate_state(run=run, authorization=authorization)
        if sync_failure is not None:
            order.status = "cancelled"
            order.failure_code = sync_failure
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        # This is the final irreversible-action gate. The supply row lock serializes payment with
        # pause/delete and prevents two concurrent runs from replenishing the same supply.
        supply = self._db.scalar(
            select(Supply)
            .join(Supply.beneficiary)
            .where(
                Supply.id == run.supply_id,
                Supply.deleted_at.is_(None),
                Supply.is_enabled.is_(True),
                Beneficiary.is_active.is_(True),
            )
            .with_for_update(of=Supply)
        )
        if supply is None:
            order.status = "cancelled"
            order.failure_code = "supply_deleted_or_paused"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)
        if pack_unit != supply.unit:
            order.status = "cancelled"
            order.failure_code = "inventory_unit_changed"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)
        if estimated_quantity(supply) > supply.safety_buffer_quantity:
            order.status = "cancelled"
            order.failure_code = "supply_no_longer_due"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        window = mandate_charge_window(
            frequency=authorization.mandate_frequency,
            renews_at=authorization.mandate_renews_at,
            last_charge_at=authorization.mandate_last_charge_at,
            last_charge_status=authorization.mandate_last_charge_status,
            approved_amount=authorization.mandate_approved_amount,
            remaining_amount=authorization.mandate_remaining_amount,
        )
        if authorization.mandate_status != "active":
            order.status = "cancelled"
            order.failure_code = "mandate_not_active"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)
        if not window.eligible:
            order.status = "cancelled"
            order.failure_code = window.reason
            supply.payment_deferred_until = window.next_eligible_at
            self._db.commit()
            return SandboxSettlementResult(
                order.status,
                order.failure_code,
                next_eligible_at=window.next_eligible_at,
            )
        if (
            authorization.mandate_approved_amount is None
            or amount > authorization.mandate_approved_amount
        ):
            order.status = "cancelled"
            order.failure_code = "mandate_amount_cap_exceeded"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)
        if (
            authorization.mandate_remaining_amount is not None
            and amount > authorization.mandate_remaining_amount
        ):
            order.status = "cancelled"
            order.failure_code = "mandate_cycle_remaining_insufficient"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

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
        authorization.mandate_last_charge_at = order.reported_at
        authorization.mandate_last_charge_status = "APPROVED"
        supply.payment_deferred_until = None
        movement = record_purchased_stock(
            self._db,
            supply=supply,
            purchase_order=order,
            pack_quantity=pack_quantity * quantity,
            pack_unit=pack_unit,
            at=order.reported_at,
        )
        self._db.add(
            LedgerEvent(
                owner_id=run.owner_id,
                event_type="stock_automatically_replenished",
                title=f"{supply.name} stock replenished",
                detail=(
                    f"An approved purchase added {movement.quantity_delta} {pack_unit}(s). "
                    f"Estimated stock is now {movement.balance_after}."
                ),
                severity="success",
                agent_run_id=run.id,
                supply_id=supply.id,
                purchase_order_id=order.id,
                metadata_safe={
                    "quantity_added": str(movement.quantity_delta),
                    "balance_after": str(movement.balance_after),
                    "unit": pack_unit,
                },
            )
        )
        self._db.commit()
        return SandboxSettlementResult(order.status, None)

    def _sync_mandate_state(
        self, *, run: AgentRun, authorization: MerchantAuthorization
    ) -> str | None:
        """Refresh Prava's safe control-plane fields before any charge is attempted."""
        try:
            mandates = self._prava.list_standing_mandates(
                external_user_id=f"health-guard:{run.owner_id}"
            )
        except (PravaApiError, PravaConfigurationError, PravaUnavailableError):
            return "mandate_sync_unavailable"
        mandate = next(
            (item for item in mandates if item.get("id") == authorization.prava_mandate_id),
            None,
        )
        if mandate is None:
            return "mandate_not_found"
        returned_status = mandate.get("status")
        if not isinstance(returned_status, str):
            return "mandate_sync_invalid"
        authorization.mandate_status = returned_status
        authorization.mandate_approved_amount = parse_prava_amount(
            mandate.get("approvedAmount", mandate.get("approved_amount"))
        )
        authorization.mandate_remaining_amount = parse_prava_amount(mandate.get("remaining"))
        currency = mandate.get("currency")
        authorization.mandate_currency = currency if isinstance(currency, str) else None
        frequency = mandate.get("recurringFrequency", mandate.get("recurring_frequency"))
        authorization.mandate_frequency = frequency if isinstance(frequency, str) else None
        authorization.mandate_valid_until = parse_prava_timestamp(
            mandate.get("validUntil", mandate.get("valid_until"))
        )
        authorization.mandate_renews_at = parse_prava_timestamp(
            mandate.get("renewsAt", mandate.get("renews_at"))
        )
        last_charge = mandate.get("lastCharge", mandate.get("last_charge"))
        if isinstance(last_charge, dict):
            last_status = last_charge.get("status")
            remote_charge_at = parse_prava_timestamp(last_charge.get("at"))
            local_charge_at = authorization.mandate_last_charge_at
            if (
                remote_charge_at is not None
                and (local_charge_at is None or remote_charge_at >= local_charge_at)
            ):
                authorization.mandate_last_charge_status = (
                    last_status if isinstance(last_status, str) else None
                )
                authorization.mandate_last_charge_at = remote_charge_at
        authorization.mandate_synced_at = datetime.now(UTC)
        return None
