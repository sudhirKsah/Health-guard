from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.merchant_checkout import (
    DeliveryAddress,
    MerchantCheckoutExecutor,
    build_checkout_executor,
)
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
    merchant_order_id: str | None = None


class SandboxSettlementExecutor:
    """Runs Prava's end-to-end flow: charge → merchant checkout → settle the true outcome.

    The mandate charge only mints a single-use card; it does not buy anything. This executor
    presents that card at the real merchant and reports whatever the merchant's processor
    actually returned. It never reports APPROVED for a checkout that did not happen.
    """

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        prava: PravaClient | None = None,
        checkout: MerchantCheckoutExecutor | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._prava = prava or PravaClient(self._settings)
        self._checkout = checkout or build_checkout_executor()

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
        variant_id: str,
        address: DeliveryAddress,
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

        if charge.credentials is None:
            order.status = "charge_failed"
            order.failure_code = "prava_charge_without_credentials"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        order.prava_transaction_id = charge.transaction_id
        order.prava_order_id = charge.order_id
        order.charged_amount = amount
        order.status = "checkout_pending"
        order.charged_at = datetime.now(UTC)
        self._db.commit()

        # The one-time card exists only inside this call. It is handed straight to the checkout
        # executor and is never persisted, logged, or passed to the model layer.
        outcome = self._checkout.checkout(
            merchant_domain=authorization.merchant_domain,
            variant_id=variant_id,
            quantity=quantity,
            amount=amount,
            currency=order.currency,
            credentials=charge.credentials,
            address=address,
        )
        order.checkout_attempted_at = datetime.now(UTC)
        order.checkout_decline_code = outcome.decline_code
        order.merchant_order_id = outcome.merchant_order_id
        if outcome.is_success:
            order.checkout_completed_at = order.checkout_attempted_at

        try:
            report = self._prava.report_mandate_charge(
                mandate_id=authorization.prava_mandate_id,
                transaction_id=charge.transaction_id,
                transaction_status=outcome.prava_report_status,
                amount_paid=amount if outcome.is_success else None,
                response_code=outcome.response_code,
            )
        except (PravaApiError, PravaUnavailableError) as error:
            order.status = "report_failed"
            order.failure_code = getattr(error, "code", None) or "prava_report_unavailable"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        # Verified against the sandbox: Prava echoes the settlement it recorded, not the health of
        # the report call. An APPROVED report settles "completed"; a DECLINED report settles
        # "failed" — the transaction failed, which is exactly what we asked it to record. Treating
        # "failed" as an error made a correctly-settled decline look like a broken integration.
        if report.status not in {"completed", "failed"}:
            order.status = "report_failed"
            order.failure_code = "settlement_not_confirmed"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)
        if outcome.is_success and report.status != "completed":
            # We claimed a merchant order but Prava did not confirm the settlement. Never let this
            # stand as a completed purchase.
            order.status = "report_failed"
            order.failure_code = "approved_settlement_not_confirmed"
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        order.reported_at = datetime.now(UTC)
        order.report_status = outcome.prava_report_status
        authorization.mandate_last_charge_at = order.reported_at
        # Verified against a live sandbox mandate: a charge settled DECLINED leaves spent="0.00",
        # chargeCount=0 and the full remaining balance, so a decline does NOT consume the cycle and
        # a genuine retry stays possible. Only an APPROVED settlement draws down `remaining`, which
        # is what mandate_charge_window keys off.
        authorization.mandate_last_charge_status = outcome.prava_report_status

        if not outcome.is_success:
            order.status = "checkout_declined"
            order.failure_code = outcome.decline_code
            # Inventory is deliberately untouched: no goods were ordered.
            self._db.add(
                LedgerEvent(
                    owner_id=run.owner_id,
                    event_type="merchant_checkout_declined",
                    title=f"{supply.name} purchase was not completed",
                    detail=(
                        outcome.detail
                        or "The merchant did not accept the one-time card, so no order was placed."
                    )
                    + " The payment was settled as DECLINED and stock was not changed.",
                    severity="warning",
                    agent_run_id=run.id,
                    supply_id=supply.id,
                    purchase_order_id=order.id,
                    metadata_safe={
                        "decline_code": outcome.decline_code,
                        "merchant": authorization.merchant_name,
                    },
                )
            )
            self._db.commit()
            return SandboxSettlementResult(order.status, order.failure_code)

        order.status = "completed"
        order.failure_code = None
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
                    f"Merchant order {outcome.merchant_order_id} added "
                    f"{movement.quantity_delta} {pack_unit}(s). "
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
                    "merchant_order_id": outcome.merchant_order_id,
                },
            )
        )
        self._db.commit()
        return SandboxSettlementResult(
            order.status, None, merchant_order_id=outcome.merchant_order_id
        )

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
