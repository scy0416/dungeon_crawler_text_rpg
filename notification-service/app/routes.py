from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import fetch_character
from app.db import get_session
from app.errors import AppError
from app.models import Notification
from app.schemas import HealthResponse, NotificationResponse

SERVICE_NAME = "notification-service"

router = APIRouter()
notification_router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def get_current_user_id(x_user_id: Annotated[int | None, Header()] = None) -> int:
    """Gateway가 토큰 검증 후 붙여주는 X-User-Id 헤더로 요청자를 식별한다."""
    if x_user_id is None:
        raise AppError(401, "UNAUTHORIZED", "인증이 필요합니다.")
    return x_user_id


Session = Annotated[AsyncSession, Depends(get_session)]
HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]
CurrentUserId = Annotated[int, Depends(get_current_user_id)]


async def ensure_owner(http: httpx.AsyncClient, character_id: int, user_id: int) -> None:
    """알림 이벤트에는 user_id가 없으므로 소유자는 character-service에 HTTP로 확인한다."""
    character = await fetch_character(http, character_id)
    if character is None:
        raise AppError(404, "CHARACTER_NOT_FOUND", "캐릭터를 찾을 수 없습니다.")
    if character.user_id != user_id:
        raise AppError(403, "NOT_CHARACTER_OWNER", "본인 캐릭터의 알림만 볼 수 있습니다.")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@notification_router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    character_id: Annotated[int, Query()],
    user_id: CurrentUserId,
    session: Session,
    http: HttpClient,
    unread_only: Annotated[bool, Query()] = False,
) -> list[NotificationResponse]:
    await ensure_owner(http, character_id, user_id)
    query = select(Notification).where(Notification.character_id == character_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    notifications = await session.scalars(query.order_by(Notification.id.desc()))
    return [NotificationResponse.model_validate(n) for n in notifications]


@notification_router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: int, user_id: CurrentUserId, session: Session, http: HttpClient
) -> NotificationResponse:
    notification = await session.get(Notification, notification_id)
    if notification is None:
        raise AppError(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다.")
    await ensure_owner(http, notification.character_id, user_id)
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.commit()
    return NotificationResponse.model_validate(notification)


router.include_router(notification_router)
