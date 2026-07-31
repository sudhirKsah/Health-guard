from app.security import redact_sensitive


def test_redact_sensitive_removes_key_and_credential_values() -> None:
    value = "key=sk_test_123456789 token=abc123 dynamic_cvv=999"

    redacted = redact_sensitive(value)

    assert "sk_test_123456789" not in redacted
    assert "abc123" not in redacted
    assert "999" not in redacted
