from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    create_session,
    get_current_user,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.database import get_db_session
from app.models import SessionToken, User
from app.schemas import LoginRequest, RegisterRequest, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["authentication"])


def issue_session(db: Session, user: User) -> SessionOut:
    access_token, expires_at = create_session(db, user)
    db.commit()
    return SessionOut(
        access_token=access_token, expires_at=expires_at, user=UserOut.model_validate(user)
    )


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db_session)) -> SessionOut:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account already exists for this email"
        )
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip() if payload.display_name else None,
    )
    db.add(user)
    db.flush()
    return issue_session(db, user)


@router.post("/login", response_model=SessionOut)
def login(payload: LoginRequest, db: Session = Depends(get_db_session)) -> SessionOut:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    return issue_session(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    # FastAPI has already validated this Bearer token through get_current_user. The raw token is
    # deliberately read only here to hash and revoke it; it is never logged or returned.
    del user
    if authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", maxsplit=1)[1]
        db_token = db.scalar(
            select(SessionToken).where(SessionToken.token_hash == hash_session_token(raw_token))
        )
        if db_token is not None:
            db_token.revoked_at = datetime.now(UTC)
            db.commit()
    # Do not return FastAPI's injected Response object: it has no concrete status code until
    # FastAPI builds the final response. Returning it directly makes Uvicorn receive None.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def current_user(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
