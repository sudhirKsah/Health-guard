from decimal import Decimal
from types import SimpleNamespace

from app.integrations.merchant_checkout import (
    CHECKOUT_DECLINED,
    CHECKOUT_SUCCEEDED,
    CHECKOUT_UNAVAILABLE,
    CheckoutOutcome,
    DeliveryAddress,
    UnavailableCheckoutExecutor,
    build_checkout_executor,
)
from app.integrations.playwright_checkout import (
    PlaywrightCheckoutExecutor,
    _classify,
    _numeric_variant_id,
)

CARD = SimpleNamespace(
    token="4111111111111111", dynamic_cvv="123", expiry_month="12", expiry_year="2030"
)
ADDRESS = DeliveryAddress(
    recipient="Test User",
    line1="1 Test Street",
    city="Kochi",
    region="Kerala",
    postal_code="690525",
    country="IN",
)
NO_ADDRESS = DeliveryAddress(recipient="", line1="", city="", postal_code="")


class FakePage:
    def __init__(self, *, url: str = "", body: str = "") -> None:
        self.url = url
        self._body = body

    def inner_text(self, _selector: str) -> str:
        return self._body


def test_merchant_refusal_is_a_decline_not_a_failure() -> None:
    """A sandbox test card refused by the processor is the expected end-to-end proof."""
    outcome = _classify(
        FakePage(url="https://shop.test/checkout", body="Your card was declined. Try another card.")
    )

    assert outcome.status == CHECKOUT_DECLINED
    assert outcome.decline_code == "merchant_declined"
    assert outcome.prava_report_status == "DECLINED"
    assert outcome.card_presented is True


def test_insufficient_funds_is_recognized_as_a_decline() -> None:
    outcome = _classify(FakePage(body="Payment error: insufficient funds on this card."))

    assert outcome.status == CHECKOUT_DECLINED
    assert outcome.card_presented is True


def test_confirmed_order_is_the_only_path_to_approved() -> None:
    outcome = _classify(
        FakePage(url="https://shop.test/checkouts/abc/thank_you", body="Thank you for your order")
    )

    assert outcome.status == CHECKOUT_SUCCEEDED
    assert outcome.prava_report_status == "APPROVED"


def test_unrecognized_merchant_response_is_never_approved() -> None:
    """An ambiguous page must not be guessed either way."""
    outcome = _classify(FakePage(url="https://shop.test/checkout", body="Loading…"))

    assert outcome.status == CHECKOUT_UNAVAILABLE
    assert outcome.prava_report_status == "DECLINED"
    # The card did reach the merchant, so this is not the same as never having tried.
    assert outcome.card_presented is True


def test_playwright_refuses_to_run_without_a_delivery_address() -> None:
    outcome = PlaywrightCheckoutExecutor().checkout(
        merchant_domain="shop.test",
        variant_id="12345",
        quantity=1,
        amount=Decimal("450"),
        currency="INR",
        credentials=CARD,
        address=NO_ADDRESS,
    )

    assert outcome.status == CHECKOUT_UNAVAILABLE
    assert outcome.decline_code == "delivery_address_not_configured"
    assert outcome.card_presented is False


def test_gid_variant_is_reduced_to_a_shopify_cart_id() -> None:
    assert _numeric_variant_id("gid://shopify/ProductVariant/44123456789") == "44123456789"
    assert _numeric_variant_id("44123456789") == "44123456789"
    assert _numeric_variant_id("no-digits-here") is None


def test_backend_none_forces_the_never_approves_executor() -> None:
    executor = build_checkout_executor(SimpleNamespace(merchant_checkout_backend="none"))

    assert isinstance(executor, UnavailableCheckoutExecutor)
    assert executor.checkout().prava_report_status == "DECLINED"


def test_default_backend_is_playwright() -> None:
    settings = SimpleNamespace(merchant_checkout_backend="playwright", checkout_headless=True)

    assert isinstance(build_checkout_executor(settings), PlaywrightCheckoutExecutor)


def test_delivery_address_completeness_and_name_split() -> None:
    assert ADDRESS.is_complete is True
    assert NO_ADDRESS.is_complete is False
    assert ADDRESS.first_name == "Test"
    assert ADDRESS.last_name == "User"
    single = DeliveryAddress(recipient="Prince", line1="x", city="y", postal_code="z")
    assert single.last_name == "Prince"


def test_only_a_confirmed_order_reports_approved() -> None:
    assert CheckoutOutcome(CHECKOUT_SUCCEEDED, merchant_order_id="o1").prava_report_status == (
        "APPROVED"
    )
    assert CheckoutOutcome(CHECKOUT_DECLINED).prava_report_status == "DECLINED"
    assert CheckoutOutcome(CHECKOUT_UNAVAILABLE).prava_report_status == "DECLINED"
