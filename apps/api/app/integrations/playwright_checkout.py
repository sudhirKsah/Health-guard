"""Playwright merchant checkout: presents the one-time card at the merchant's own storefront.

This is step 4 of Prava's end-to-end flow. Prava mints a single-use, merchant-scoped credential
but does not place the order, and its REST surface exposes no checkout endpoint, so Health Guard
drives the merchant's own checkout with headless Chromium: it fills the beneficiary's contact and
shipping details, submits the card, and reads back what the merchant's processor decided.

Design constraints:

* The card credential is used inside this process and is never logged, persisted, or screenshotted.
* A refusal by the merchant's processor is a **decline** (a successful end-to-end proof in sandbox).
  Anything that stops before the card is submitted is **unavailable**, never a decline and never a
  success, so an automation failure can never be mistaken for a completed purchase.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.integrations.merchant_checkout import (
    CHECKOUT_DECLINED,
    CHECKOUT_SUCCEEDED,
    CHECKOUT_UNAVAILABLE,
    CheckoutOutcome,
    DeliveryAddress,
)
from app.integrations.prava import MandateCardCredentials

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 45_000

# Phrases a Shopify checkout shows when the processor refuses the card. A sandbox test card is
# expected to land here — that is the outcome Prava requires before granting production access.
DECLINE_PHRASES = (
    "insufficient funds",
    "was declined",
    "card was declined",
    "declined",
    "do not honor",
    "do not honour",
    "payment could not be processed",
    "payment failed",
    "unable to process",
    "try a different card",
    "incorrect card number",
)

# Phrases proving the order actually went through.
SUCCESS_PHRASES = (
    "thank you for your order",
    "order confirmed",
    "your order is confirmed",
    "thank you!",
)


class PlaywrightCheckoutExecutor:
    """Drives a Shopify storefront checkout with the one-time tokenized card."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms

    def available(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        return True

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
    ) -> CheckoutOutcome:
        if not self.available():
            return CheckoutOutcome(
                CHECKOUT_UNAVAILABLE,
                decline_code="playwright_not_installed",
                detail="Playwright is not installed, so no merchant checkout was attempted.",
            )
        if not address.is_complete:
            return CheckoutOutcome(
                CHECKOUT_UNAVAILABLE,
                decline_code="delivery_address_not_configured",
                detail=(
                    "This beneficiary has no complete delivery address, so the card was never "
                    "presented. Add the address in care setup."
                ),
            )

        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright

        numeric_variant = _numeric_variant_id(variant_id)
        if not numeric_variant:
            return CheckoutOutcome(
                CHECKOUT_UNAVAILABLE,
                decline_code="variant_id_not_usable_for_cart",
                detail=(
                    "The approved variant id could not be reduced to a Shopify numeric variant, "
                    "so no cart could be opened."
                ),
            )

        # Shopify's permalink builds a cart and jumps straight to checkout, which avoids scraping
        # the product page for an add-to-cart control that differs per theme.
        checkout_url = f"https://{merchant_domain}/cart/{numeric_variant}:{quantity}"

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self._headless)
                try:
                    context = browser.new_context(locale="en-IN")
                    page = context.new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(checkout_url, wait_until="domcontentloaded")
                    _dismiss_overlays(page)
                    if "/checkout" not in page.url:
                        page.goto(
                            f"https://{merchant_domain}/checkout", wait_until="domcontentloaded"
                        )
                    self._fill_contact_and_shipping(page, address)
                    submitted = self._submit_payment(page, credentials, address)
                    if not submitted:
                        return CheckoutOutcome(
                            CHECKOUT_UNAVAILABLE,
                            decline_code="card_fields_not_reached",
                            detail=(
                                "The checkout never exposed card fields, so the one-time card was "
                                "not presented to the merchant."
                            ),
                        )
                    return _classify(page)
                finally:
                    browser.close()
        except (PlaywrightTimeout, PlaywrightError) as error:
            # Never leak the page content or the credential into the log record.
            logger.warning("Playwright checkout stopped: %s", type(error).__name__)
            return CheckoutOutcome(
                CHECKOUT_UNAVAILABLE,
                decline_code="merchant_checkout_automation_failed",
                detail="The merchant checkout automation stopped before a result was confirmed.",
            )

    def _fill_contact_and_shipping(self, page: object, address: DeliveryAddress) -> None:
        fields = {
            "email": address.email or "",
            "firstName": address.first_name,
            "lastName": address.last_name,
            "address1": address.line1,
            "address2": address.line2 or "",
            "city": address.city,
            "province": address.region or "",
            "postalCode": address.postal_code,
            "phone": address.phone or "",
        }
        for name, value in fields.items():
            if not value:
                continue
            _fill_first(page, [f"input[name='{name}']", f"input#{name}"], value)
        _click_first(
            page,
            [
                "button:has-text('Continue to shipping')",
                "button:has-text('Continue to payment')",
                "button:has-text('Continue')",
            ],
        )

    def _submit_payment(
        self, page: object, credentials: MandateCardCredentials, address: DeliveryAddress
    ) -> bool:
        """Type the one-time card into the payment iframe. Returns False if never reached."""
        frame = _payment_frame(page)
        if frame is None:
            return False
        expiry = f"{credentials.expiry_month}/{credentials.expiry_year[-2:]}"
        typed = _fill_first(
            frame, ["input[name='number']", "input[name='cardnumber']"], credentials.token
        )
        if not typed:
            return False
        _fill_first(frame, ["input[name='expiry']", "input[name='exp-date']"], expiry)
        _fill_first(
            frame,
            ["input[name='verification_value']", "input[name='cvc']", "input[name='cvv']"],
            credentials.dynamic_cvv,
        )
        _fill_first(frame, ["input[name='name']"], address.recipient)
        _click_first(
            page,
            [
                "button:has-text('Pay now')",
                "button:has-text('Complete order')",
                "button#continue_button",
            ],
        )
        page.wait_for_timeout(8_000)
        return True


def _numeric_variant_id(variant_id: str) -> str | None:
    """Reduce a UCP/GID variant reference to the numeric id Shopify's cart permalink expects."""
    tail = variant_id.rstrip("/").split("/")[-1]
    digits = "".join(character for character in tail if character.isdigit())
    return digits or None


def _payment_frame(page: object):
    for candidate in page.frames:
        name = f"{getattr(candidate, 'name', '')} {getattr(candidate, 'url', '')}".casefold()
        if "card" in name or "payment" in name:
            return candidate
    return None


def _fill_first(scope: object, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            locator = scope.locator(selector).first
            if locator.count() == 0:
                continue
            locator.fill(value, timeout=8_000)
            return True
        except Exception:  # noqa: BLE001 - selector probing is best-effort by design
            continue
    return False


def _click_first(scope: object, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            locator = scope.locator(selector).first
            if locator.count() == 0:
                continue
            locator.click(timeout=8_000)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _dismiss_overlays(page: object) -> None:
    _click_first(
        page,
        [
            "button:has-text('Accept')",
            "button:has-text('Got it')",
            "button[aria-label='Close']",
        ],
    )


def _classify(page: object) -> CheckoutOutcome:
    """Decide the outcome from the post-submit page, preferring an explicit signal.

    Every branch sets card_presented: by this point the card has reached the merchant, so no
    fallback executor may run it a second time.
    """
    try:
        body = (page.inner_text("body") or "").casefold()
    except Exception:  # noqa: BLE001
        body = ""
    url = (getattr(page, "url", "") or "").casefold()

    if "thank_you" in url or "orders/" in url or any(p in body for p in SUCCESS_PHRASES):
        return CheckoutOutcome(
            CHECKOUT_SUCCEEDED,
            merchant_order_id=_order_id_from(url, body),
            response_code="00",
            detail="The merchant confirmed the order.",
            card_presented=True,
        )
    if any(phrase in body for phrase in DECLINE_PHRASES):
        return CheckoutOutcome(
            CHECKOUT_DECLINED,
            decline_code="merchant_declined",
            detail=(
                "The one-time card was submitted to the merchant's checkout and the processor "
                "refused it. In sandbox this is the expected end-to-end result."
            ),
            card_presented=True,
        )
    return CheckoutOutcome(
        CHECKOUT_UNAVAILABLE,
        decline_code="merchant_result_unrecognized",
        detail=(
            "The card was submitted but the merchant's response could not be classified, so no "
            "outcome is claimed."
        ),
        card_presented=True,
    )


def _order_id_from(url: str, body: str) -> str | None:
    for token in url.replace("?", "/").split("/"):
        if token.startswith("orders") and len(token) > 6:
            return token
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("order #"):
            return stripped.split("#", 1)[1].strip() or None
    return None
