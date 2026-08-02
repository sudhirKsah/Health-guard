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
    if order.report_status == "APPROVED" or order.status == "sandbox_settled":
        return "approved"
    if order.report_status == "DECLINED" or order.status in {"charge_failed", "report_failed"}:
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
        fulfillment = (
            f" Merchant order {order.merchant_order_id} was recorded."
            if order.merchant_order_id
            else " Payment approval is recorded; merchant fulfillment is not recorded by this sandbox flow."
        )
        inventory = (
            f" {order.purchased_quantity} {order.purchased_unit}(s) were added to tracked stock."
            if order.purchased_quantity is not None and order.purchased_unit
            else ""
        )
        return (
            "Payment approved",
            f"{supply.name} for {beneficiary.name} was approved at {merchant.merchant_name} for {money}.{fulfillment}{inventory}",
        )
    if status_value == "declined":
        reason = {
            "prava_charge_unavailable": "Prava could not authorize the payment",
            "prava_charge_not_ready": "the payment authorization was not ready",
            "prava_report_unavailable": "the final payment result could not be confirmed",
            "sandbox_settlement_not_confirmed": "Prava did not confirm the settlement",
        }.get(order.failure_code or "", "the payment could not be completed")
        return (
            "Payment declined",
            f"No payment completed for {supply.name} at {merchant.merchant_name}: {reason}.",
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
