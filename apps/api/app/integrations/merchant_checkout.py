"""Step 4 of Prava's end-to-end flow: present the one-time card at the real merchant.

Prava mints a single-use, merchant-scoped credential; it does **not** place the order. Someone
must drive the merchant's own checkout, and Prava's REST surface exposes no checkout endpoint, so
Health Guard drives it itself with headless Chromium (see `playwright_checkout`).

Two invariants hold for every executor in this module:

1. Card credentials are passed straight to the executor and are never logged, persisted, returned
   in an outcome, or shown to an LLM.
2. An executor that cannot complete a real checkout returns ``unavailable``. It never reports
   success, so :meth:`CheckoutOutcome.prava_report_status` can only yield ``APPROVED`` when a
   merchant genuinely accepted the payment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.integrations.prava import MandateCardCredentials

logger = logging.getLogger(__name__)

CHECKOUT_SUCCEEDED = "succeeded"
CHECKOUT_DECLINED = "declined"
CHECKOUT_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DeliveryAddress:
    """Where one beneficiary's supplies are shipped.

    A self-driven checkout has to type these into the merchant's own form, so they are plain
    values. Never log this object, put it in an agent trace, or include it in a model prompt.
    """

    recipient: str
    line1: str
    city: str
    postal_code: str
    country: str = "IN"
    line2: str | None = None
    region: str | None = None
    phone: str | None = None
    email: str | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.recipient and self.line1 and self.city and self.postal_code)

    @property
    def first_name(self) -> str:
        return self.recipient.split(" ", 1)[0]

    @property
    def last_name(self) -> str:
        parts = self.recipient.split(" ", 1)
        return parts[1] if len(parts) > 1 else parts[0]


@dataclass(frozen=True)
class CheckoutOutcome:
    """The result of a real merchant checkout attempt. Never carries card credentials."""

    status: str
    merchant_order_id: str | None = None
    decline_code: str | None = None
    response_code: str | None = None
    detail: str | None = None
    # Whether the card actually reached the merchant. This is the difference between "the merchant
    # refused it" (the expected sandbox proof) and "we never got that far", which look alike in the
    # UI but mean very different things.
    card_presented: bool = False

    @property
    def is_success(self) -> bool:
        return self.status == CHECKOUT_SUCCEEDED

    @property
    def prava_report_status(self) -> str:
        """Only a genuine merchant order may be settled as APPROVED with the card network."""
        return "APPROVED" if self.is_success else "DECLINED"


class MerchantCheckoutExecutor(Protocol):
    def checkout(
        self,
        *,
        merchant_domain: str,
        variant_id: str,
        quantity: int,
        amount: Decimal,
        currency: str,
        credentials: MandateCardCredentials,
        address: DeliveryAddress,
    ) -> CheckoutOutcome: ...


class UnavailableCheckoutExecutor:
    """The safe default: no checkout capability is configured, so nothing is ever approved."""

    def available(self) -> bool:
        return True

    def checkout(self, **_kwargs: object) -> CheckoutOutcome:
        return CheckoutOutcome(
            CHECKOUT_UNAVAILABLE,
            decline_code="merchant_checkout_not_configured",
            detail=(
                "Merchant checkout is switched off, so the one-time card was never presented to a "
                "merchant. The charge is settled as DECLINED."
            ),
        )


def build_checkout_executor(settings: object | None = None) -> MerchantCheckoutExecutor:
    """Resolve the configured checkout executor.

    Selection never affects safety: whichever executor is chosen, an outcome other than a
    confirmed merchant order settles DECLINED.
    """
    # Imported lazily: playwright_checkout imports this module for its outcome constants.
    from app.config import get_settings
    from app.integrations.playwright_checkout import PlaywrightCheckoutExecutor

    resolved = settings or get_settings()
    if getattr(resolved, "merchant_checkout_backend", "playwright") == "none":
        return UnavailableCheckoutExecutor()

    executor = PlaywrightCheckoutExecutor(
        headless=getattr(resolved, "checkout_headless", True)
    )
    if not executor.available():
        logger.warning("Playwright is not installed; merchant checkout is unavailable.")
        return UnavailableCheckoutExecutor()
    return executor
