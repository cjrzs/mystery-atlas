from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_session
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, UserResponse
from ..security import (
    SESSION_COOKIE,
    create_session_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def set_session_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user),
        max_age=settings.session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> User:
    email = request.email.lower()
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已经注册")

    user_count = session.scalar(select(func.count()).select_from(User)) or 0
    role = "admin" if get_settings().environment == "development" and user_count == 0 else "user"
    user = User(
        email=email,
        display_name=request.display_name.strip(),
        password_hash=hash_password(request.password),
        role=role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, user)
    return user


@router.post("/login", response_model=UserResponse)
def login(
    request: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> User:
    user = session.scalar(select(User).where(User.email == request.email.lower()))
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已停用")
    set_session_cookie(response, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user

