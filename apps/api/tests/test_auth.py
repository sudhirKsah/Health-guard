from app.auth import hash_password, verify_password


def test_scrypt_password_hash_is_not_the_password_and_verifies() -> None:
    password = "a-strong-test-password"
    stored = hash_password(password)

    assert password not in stored
    assert verify_password(password, stored)
    assert not verify_password("not-the-password", stored)
