from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, is_valid_prava_email
from app.database import get_db_session
from app.integrations.prava import (
    PravaApiError,
    PravaClient,
    PravaConfigurationError,
    PravaUnavailableError,
    parse_prava_amount,
    parse_prava_timestamp,
)
from app.models import MandateEvent, MerchantAuthorization, User
from app.routers.setup import MERCHANTS, owned_merchant_authorization
from app.schemas import (
    MandateActionRequest,
    MandateEventOut,
    MandateSetupRequest,
    MandateSetupSessionOut,
    MerchantAuthorizationOut,
)

router = APIRouter(prefix="/mandates", tags=["Prava mandates"])


def default_max_charges(*, frequency: str, starts_at: datetime, ends_at: datetime) -> int:
    period_days = {"weekly": 7, "monthly": 30.4375, "yearly": 365.25}[frequency]
    return min(104, max(1, ceil((ends_at - starts_at).total_seconds() / 86400 / period_days)))


def external_user_id(user: User) -> str:
    """A stable opaque reference accepted by Prava; never expose the user's email as an ID."""
    return f"health-guard:{user.id}"


def mandate_value(payload: dict[str, object], camel: str, snake: str) -> object:
    return payload.get(camel, payload.get(snake))


def matching_mandate(
    mandates: list[dict[str, object]], *, merchant_name: str, merchant_url: str
) -> dict[str, object] | None:
    """Match conservatively: a returned URL must match; otherwise use the documented merchant name."""
    normalized_name = merchant_name.casefold()
    normalized_url = merchant_url.rstrip("/").casefold()
    candidates: list[dict[str, object]] = []
    for mandate in mandates:
        response_url = mandate_value(mandate, "merchantUrl", "merchant_url")
        if isinstance(response_url, str):
            if response_url.rstrip("/").casefold() != normalized_url:
                continue
        elif str(mandate_value(mandate, "merchantName", "merchant_name") or "").casefold() != normalized_name:
            continue
        candidates.append(mandate)
    if not candidates:
        return None
    # Favor a usable mandate if an earlier superseded pending/cancelled record is also returned.
    candidates.sort(key=lambda item: 0 if item.get("status") == "active" else 1)
    return candidates[0]


def add_event(
    db: Session,
    authorization: MerchantAuthorization,
    *,
    event_type: str,
    previous_status: str | None,
    resulting_status: str | None,
    details: dict[str, object],
) -> None:
    db.add(
        MandateEvent(
            merchant_authorization_id=authorization.id,
            event_type=event_type,
            previous_status=previous_status,
            resulting_status=resulting_status,
            details=details,
        )
    )


def apply_mandate(
    authorization: MerchantAuthorization, mandate: dict[str, object]
) -> tuple[str | None, str | None]:
    previous_status = authorization.mandate_status
    mandate_id = mandate.get("id")
    returned_status = mandate.get("status")
    approved_amount = parse_prava_amount(mandate_value(mandate, "approvedAmount", "approved_amount"))
    remaining = parse_prava_amount(mandate.get("remaining"))
    currency = mandate.get("currency")
    frequency = mandate_value(mandate, "recurringFrequency", "recurring_frequency")
    if not isinstance(mandate_id, str) or not isinstance(returned_status, str):
        raise PravaApiError("Prava returned an invalid mandate")
    authorization.prava_mandate_id = mandate_id
    authorization.mandate_status = returned_status
    authorization.mandate_approved_amount = approved_amount
    authorization.mandate_remaining_amount = remaining
    authorization.mandate_currency = currency if isinstance(currency, str) else None
    authorization.mandate_frequency = frequency if isinstance(frequency, str) else None
    authorization.mandate_valid_until = parse_prava_timestamp(
        mandate_value(mandate, "validUntil", "valid_until")
    )
    authorization.mandate_renews_at = parse_prava_timestamp(
        mandate_value(mandate, "renewsAt", "renews_at")
    )
    authorization.mandate_synced_at = datetime.now(UTC)
    return previous_status, returned_status


def handle_prava_error(error: Exception) -> HTTPException:
    if isinstance(error, PravaConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, PravaUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, PravaApiError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Mandate failed")


@router.post(
    "/{merchant_authorization_id}/setup-session",
    response_model=MandateSetupSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_setup_session(
    merchant_authorization_id: UUID,
    payload: MandateSetupRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MandateSetupSessionOut:
    authorization = owned_merchant_authorization(db, user.id, merchant_authorization_id)
    if not is_valid_prava_email(user.email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Your Health Guard account needs a valid email address before Prava can create approval",
        )
    if not authorization.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Resume this merchant authorization before creating a mandate",
        )
    if authorization.mandate_status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This merchant already has an active mandate; pause or cancel it before replacing it",
        )
    now = datetime.now(UTC)
    valid_until = payload.valid_until if payload.valid_until.tzinfo else payload.valid_until.replace(tzinfo=UTC)
    if valid_until <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Mandate expiry must be in the future",
        )
    max_horizon_days = {"weekly": 366, "monthly": 731, "yearly": 1827}[payload.recurring_frequency]
    if (valid_until - now).days > max_horizon_days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Mandate expiry exceeds Prava's permitted horizon for this frequency",
        )
    max_charges = payload.max_charges or default_max_charges(
        frequency=payload.recurring_frequency,
        starts_at=now,
        ends_at=valid_until,
    )
    merchant_name, _, merchant_url = MERCHANTS[authorization.merchant_key]
    try:
        result = PravaClient().create_mandate_setup(
            external_user_id=external_user_id(user),
            user_email=user.email,
            merchant_name=merchant_name,
            merchant_url=merchant_url,
            approved_amount=payload.approved_amount,
            currency=payload.currency,
            recurring_frequency=payload.recurring_frequency,
            max_charges=max_charges,
            valid_until=valid_until,
        )
    except (PravaApiError, PravaConfigurationError, PravaUnavailableError) as error:
        raise handle_prava_error(error) from error
    iframe_url = result.get("iframe_url")
    session_id = result.get("session_id")
    if not isinstance(iframe_url, str) or not isinstance(session_id, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Prava returned an incomplete mandate approval session",
        )
    previous_status = authorization.mandate_status
    authorization.prava_setup_session_id = session_id
    authorization.mandate_status = "pending"
    authorization.mandate_approved_amount = payload.approved_amount
    authorization.mandate_remaining_amount = None
    authorization.mandate_currency = payload.currency
    authorization.mandate_frequency = payload.recurring_frequency
    authorization.mandate_max_charges = max_charges
    authorization.health_guard_stop_after = valid_until
    authorization.mandate_renews_at = None
    authorization.mandate_synced_at = now
    add_event(
        db,
        authorization,
        event_type="setup_started",
        previous_status=previous_status,
        resulting_status="pending",
        details={
            "approved_amount": str(payload.approved_amount),
            "currency": payload.currency,
            "frequency": payload.recurring_frequency,
            "max_charges": max_charges,
        },
    )
    db.commit()
    db.refresh(authorization)
    return MandateSetupSessionOut(
        merchant_authorization=MerchantAuthorizationOut.model_validate(authorization),
        iframe_url=iframe_url,
        expires_at=parse_prava_timestamp(result.get("expires_at")),
    )


@router.post("/{merchant_authorization_id}/sync", response_model=MerchantAuthorizationOut)
def sync_mandate(
    merchant_authorization_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MerchantAuthorizationOut:
    authorization = owned_merchant_authorization(db, user.id, merchant_authorization_id)
    merchant_name, _, merchant_url = MERCHANTS[authorization.merchant_key]
    try:
        mandate = matching_mandate(
            PravaClient().list_standing_mandates(external_user_id=external_user_id(user)),
            merchant_name=merchant_name,
            merchant_url=merchant_url,
        )
    except (PravaApiError, PravaConfigurationError, PravaUnavailableError) as error:
        # Prava has no mandate list to return for a customer until their first setup session.
        if isinstance(error, PravaApiError) and error.code == "CUSTOMER_NOT_FOUND":
            authorization.mandate_synced_at = datetime.now(UTC)
            db.commit()
            db.refresh(authorization)
            return MerchantAuthorizationOut.model_validate(authorization)
        raise handle_prava_error(error) from error
    if mandate is None:
        authorization.mandate_synced_at = datetime.now(UTC)
        db.commit()
        db.refresh(authorization)
        return MerchantAuthorizationOut.model_validate(authorization)
    try:
        previous_status, resulting_status = apply_mandate(authorization, mandate)
    except PravaApiError as error:
        raise handle_prava_error(error) from error
    if previous_status != resulting_status:
        add_event(
            db,
            authorization,
            event_type="status_synced",
            previous_status=previous_status,
            resulting_status=resulting_status,
            details={"source": "prava_list_mandates"},
        )
    db.commit()
    db.refresh(authorization)
    return MerchantAuthorizationOut.model_validate(authorization)


@router.post(
    "/{merchant_authorization_id}/{action}", response_model=MerchantAuthorizationOut
)
def lifecycle_action(
    merchant_authorization_id: UUID,
    action: Literal["pause", "resume", "cancel"],
    payload: MandateActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MerchantAuthorizationOut:
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Confirmation is required before changing a mandate",
        )
    authorization = owned_merchant_authorization(db, user.id, merchant_authorization_id)
    if not authorization.prava_mandate_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No Prava mandate is linked yet")
    try:
        mandate = PravaClient().mandate_lifecycle(
            mandate_id=authorization.prava_mandate_id, action=action
        )
        previous_status, resulting_status = apply_mandate(authorization, mandate)
    except (PravaApiError, PravaConfigurationError, PravaUnavailableError) as error:
        raise handle_prava_error(error) from error
    add_event(
        db,
        authorization,
        event_type=action,
        previous_status=previous_status,
        resulting_status=resulting_status,
        details={"source": "health_guard_owner_confirmed"},
    )
    db.commit()
    db.refresh(authorization)
    return MerchantAuthorizationOut.model_validate(authorization)


@router.get("/{merchant_authorization_id}/events", response_model=list[MandateEventOut])
def list_events(
    merchant_authorization_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[MandateEventOut]:
    owned_merchant_authorization(db, user.id, merchant_authorization_id)
    events = list(
        db.scalars(
            select(MandateEvent)
            .where(MandateEvent.merchant_authorization_id == merchant_authorization_id)
            .order_by(MandateEvent.created_at.desc())
        )
    )
    return [MandateEventOut.model_validate(event) for event in events]
