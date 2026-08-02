from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db_session
from app.models import AgentRun, Beneficiary, MerchantAuthorization, PurchaseOrder, Supply, User
from app.schemas import TransactionActivityOut

router = APIRouter(prefix="/activity", tags=["user activity"])


def transaction_status(order: PurchaseOrder) -> str:
    # "approved" requires a real merchant order. A settled charge with no order is not a purchase.
    if order.report_status == "APPROVED" and order.merchant_order_id:
        return "approved"
    if order.report_status == "DECLINED" or order.status in {
        "charge_failed",
        "report_failed",
        "checkout_declined",
        "settled_without_checkout",
    }:
        return "declined"
    return "pending"


def transaction_copy(
    *,
    order: PurchaseOrder,
    supply: Supply,
    beneficiary: Beneficiary,
    merchant: MerchantAuthorization,
    status_value: str,
) -> tuple[str, str]:
    amount = order.charged_amount or order.requested_amount
    money = f"{order.currency} {amount:.2f}"
    if status_value == "approved":
        inventory = (
            f" {order.purchased_quantity} {order.purchased_unit}(s) were added to tracked stock."
            if order.purchased_quantity is not None and order.purchased_unit
            else ""
        )
        return (
            "Order placed",
            f"{supply.name} for {beneficiary.name} was purchased at {merchant.merchant_name} for "
            f"{money}. Merchant order {order.merchant_order_id} was confirmed.{inventory}",
        )
    if status_value == "declined":
        reason = {
            "prava_charge_unavailable": "Prava could not authorize the payment",
            "prava_charge_not_ready": "the payment authorization was not ready",
            "prava_charge_without_credentials": "Prava did not return a usable one-time card",
            "prava_report_unavailable": "the final payment result could not be confirmed",
            "settlement_not_confirmed": "Prava did not confirm the settlement",
            "merchant_declined": "the merchant's checkout refused the one-time card",
            "merchant_checkout_not_configured": (
                "merchant checkout is switched off, so the card was never presented"
            ),
            "playwright_not_installed": (
                "the checkout browser is not installed, so the card was never presented"
            ),
            "delivery_address_not_configured": (
                "this person has no delivery address yet, so the card was never presented"
            ),
            "card_fields_not_reached": (
                "the merchant's checkout never showed card fields, so nothing was submitted"
            ),
            "merchant_result_unrecognized": (
                "the card was submitted but the merchant's response could not be read"
            ),
            "merchant_checkout_never_attempted": (
                "this older record was settled before merchant checkout existed"
            ),
        }.get(order.failure_code or "", "the payment could not be completed")
        return (
            "Payment declined",
            f"No order was placed for {supply.name} at {merchant.merchant_name}: {reason}. "
            "Tracked stock was not changed.",
        )
    return (
        "Payment processing",
        f"Health Guard is confirming {money} for {supply.name} at {merchant.merchant_name}.",
    )


@router.get("/transactions", response_model=list[TransactionActivityOut])
def list_transactions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db_session)
) -> list[TransactionActivityOut]:
    rows = db.execute(
        select(PurchaseOrder, AgentRun, Supply, Beneficiary, MerchantAuthorization)
        .join(AgentRun, PurchaseOrder.agent_run_id == AgentRun.id)
        .join(Supply, AgentRun.supply_id == Supply.id)
        .join(Beneficiary, Supply.beneficiary_id == Beneficiary.id)
        .join(
            MerchantAuthorization,
            PurchaseOrder.merchant_authorization_id == MerchantAuthorization.id,
        )
        .where(PurchaseOrder.owner_id == user.id)
        .where(PurchaseOrder.status != "cancelled")
        .order_by(PurchaseOrder.created_at.desc())
        .limit(100)
    )
    results: list[TransactionActivityOut] = []
    for order, _run, supply, beneficiary, merchant in rows:
        status_value = transaction_status(order)
        title, detail = transaction_copy(
            order=order,
            supply=supply,
            beneficiary=beneficiary,
            merchant=merchant,
            status_value=status_value,
        )
        results.append(
            TransactionActivityOut(
                id=order.id,
                occurred_at=order.updated_at,
                beneficiary_name=beneficiary.name,
                supply_name=supply.name,
                merchant_name=merchant.merchant_name,
                amount=Decimal(order.charged_amount or order.requested_amount),
                currency=order.currency,
                status=status_value,
                title=title,
                detail=detail,
            )
        )
    return results
