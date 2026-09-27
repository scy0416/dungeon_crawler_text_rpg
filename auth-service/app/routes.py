from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import AppError
from app.models import User
from app.schemas import (
    HealthResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    VerifyResponse,
)
from app.security import create_access_token, decode_access_token, hash_password, verify_password

SERVICE_NAME = "auth-service"

router = APIRouter()
auth_router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@auth_router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, session: Session) -> UserResponse:
    user = User(username=body.username, hashed_password=hash_password(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppError(409, "USERNAME_TAKEN", "이미 사용 중인 아이디입니다.")
    await session.refresh(user)
    return UserResponse.model_validate(user)


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: Session) -> TokenResponse:
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.hashed_password):
        raise AppError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다.")
    return TokenResponse(access_token=create_access_token(user.id, user.username))


@auth_router.get("/verify", response_model=VerifyResponse)
async def verify(authorization: Annotated[str | None, Header()] = None) -> VerifyResponse:
    """내부용: Gateway가 토큰 검증을 위임할 때 호출한다."""
    scheme, _, token = (authorization or "").partition(" ")
    claims = decode_access_token(token) if scheme.lower() == "bearer" and token else None
    if claims is None:
        raise AppError(401, "INVALID_TOKEN", "유효하지 않은 토큰입니다.")
    return claims


router.include_router(auth_router)
