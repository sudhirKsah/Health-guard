from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models import SessionToken, User

SESSION_DAYS = 30
_bearer_scheme = HTTPBearer(auto_error=False)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 16_384
    digest = hashlib.scrypt(password.encode(), salt=salt, n=iterations, r=8, p=1, dklen=64)
    return "$".join(
        (
            "scrypt",
            str(iterations),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = stored.split("$", 3)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(raw_salt.encode())
        expected = base64.urlsafe_b64decode(raw_digest.encode())
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(raw_iterations), r=8, p=1, dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
    db.add(
        SessionToken(
            user_id=user.id, token_hash=hash_session_token(raw_token), expires_at=expires_at
        )
    )
    return raw_token, expires_at


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    now = datetime.now(UTC)
    token = db.scalar(
        select(SessionToken).where(
            SessionToken.token_hash == hash_session_token(credentials.credentials),
            SessionToken.revoked_at.is_(None),
            SessionToken.expires_at > now,
        )
    )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired"
        )
    return token.user
