import httpx

from app.auth import hash_password, is_valid_prava_email, verify_password
from app.integrations.prava import PravaClient
from app.models import User
from app.routers.auth import logout


class FakeLogoutDb:
    def scalar(self, _statement: object) -> None:
        return None

    def commit(self) -> None:
        return None


def test_scrypt_password_hash_is_not_the_password_and_verifies() -> None:
    password = "a-strong-test-password"
    stored = hash_password(password)

    assert password not in stored
    assert verify_password(password, stored)
    assert not verify_password("not-the-password", stored)


def test_prava_email_validation_requires_a_domain_suffix() -> None:
    assert is_valid_prava_email("caregiver@example.com")
    assert not is_valid_prava_email("caregiver@example")


def test_prava_error_sanitizer_keeps_only_validation_field_names() -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": "VAL_2001",
                "message": "Validation failed with private content",
                "details": {
                    "fieldErrors": {"mandate_setup.valid_until": ["private detail"]},
                    "formErrors": ["private form detail"],
                },
            }
        },
    )

    assert PravaClient._safe_error_context(response) == ("VAL_2001", ["mandate_setup.valid_until"])


def test_logout_returns_a_concrete_no_content_response() -> None:
    response = logout(
        user=User(email="caregiver@example.com", password_hash="not-used"),
        db=FakeLogoutDb(),  # type: ignore[arg-type]
        authorization="Bearer session-token",
    )

    assert response.status_code == 204
