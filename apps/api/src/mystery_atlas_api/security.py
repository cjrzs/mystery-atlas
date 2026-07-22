from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .models import User

SESSION_COOKIE = "mystery_atlas_session"
ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_session_token(user: User) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)
    return jwt.encode(
        {"sub": user.id, "role": user.role, "exp": expires_at},
        settings.session_secret,
        algorithm=ALGORITHM,
    )


def get_current_user(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    session: Session = Depends(get_session),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="请先登录",
    )
    if not session_token:
        raise credentials_error

    try:
        payload = jwt.decode(
            session_token,
            get_settings().session_secret,
            algorithms=[ALGORITHM],
        )
        user_id = payload.get("sub")
    except InvalidTokenError as exc:
        raise credentials_error from exc

    if not isinstance(user_id, str):
        raise credentials_error
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user

