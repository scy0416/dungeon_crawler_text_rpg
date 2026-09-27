import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import fetch_character
from app.db import get_session
from app.errors import AppError
from app.models import Quest, QuestProgress
from app.observability import correlation_id
from app.schemas import AcceptRequest, HealthResponse, QuestProgressResponse, QuestResponse
from app.tracking import IN_PROGRESS, advance

SERVICE_NAME = "quest-service"

logger = logging.getLogger(__name__)

router = APIRouter()
quest_router = APIRouter(prefix="/quests", tags=["quests"])


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def get_current_user_id(x_user_id: Annotated[int | None, Header()] = None) -> int:
    """Gateway가 토큰 검증 후 붙여주는 X-User-Id 헤더로 요청자를 식별한다."""
    if x_user_id is None:
        raise AppError(401, "UNAUTHORIZED", "인증이 필요합니다.")
    return x_user_id


Session = Annotated[AsyncSession, Depends(get_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]
CurrentUserId = Annotated[int, Depends(get_current_user_id)]


def progress_response(progress: QuestProgress, quest: Quest) -> QuestProgressResponse:
    return QuestProgressResponse(
        quest_id=quest.id,
        quest_name=quest.name,
        type=quest.type,
        status=progress.status,
        progress=progress.progress,
        target_count=quest.target_count,
        reward_exp=quest.reward_exp,
        accepted_at=progress.accepted_at,
        completed_at=progress.completed_at,
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@quest_router.get("", response_model=list[QuestResponse])
async def list_quests(session: Session, user_id: CurrentUserId) -> list[QuestResponse]:
    quests = await session.scalars(select(Quest).order_by(Quest.id))
    return [QuestResponse.model_validate(q) for q in quests]


@quest_router.get("/progress", response_model=list[QuestProgressResponse])
async def list_progress(
    character_id: Annotated[int, Query()], user_id: CurrentUserId, session: Session
) -> list[QuestProgressResponse]:
    rows = await session.execute(
        select(QuestProgress, Quest)
        .join(Quest, Quest.id == QuestProgress.quest_id)
        .where(QuestProgress.character_id == character_id, QuestProgress.user_id == user_id)
        .order_by(QuestProgress.quest_id)
    )
    return [progress_response(progress, quest) for progress, quest in rows.tuples()]


@quest_router.post("/{quest_id}/accept", response_model=QuestProgressResponse, status_code=201)
async def accept_quest(
    quest_id: int,
    body: AcceptRequest,
    user_id: CurrentUserId,
    session: Session,
    redis: RedisClient,
    http: HttpClient,
) -> QuestProgressResponse:
    quest = await session.get(Quest, quest_id)
    if quest is None:
        raise AppError(404, "QUEST_NOT_FOUND", "퀘스트를 찾을 수 없습니다.")

    # 다른 서비스의 데이터는 HTTP API로 가져온다 (DB 직접 접근 금지)
    character = await fetch_character(http, body.character_id)
    if character is None:
        raise AppError(404, "CHARACTER_NOT_FOUND", "캐릭터를 찾을 수 없습니다.")
    if character.user_id != user_id:
        raise AppError(403, "NOT_CHARACTER_OWNER", "본인의 캐릭터로만 수락할 수 있습니다.")
    if character.level < quest.min_level:
        raise AppError(403, "LEVEL_TOO_LOW", f"레벨 {quest.min_level} 이상만 수락할 수 있습니다.")

    progress = QuestProgress(
        character_id=character.id, user_id=user_id, quest_id=quest.id, status=IN_PROGRESS, progress=0
    )
    # 레벨 도달 퀘스트는 현재 레벨에서 시작한다 (이미 도달했으면 즉시 완료)
    completed = advance(progress, quest, character.level) if quest.type == "reach_level" else None
    session.add(progress)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppError(409, "QUEST_ALREADY_ACCEPTED", "이미 수락한 퀘스트입니다.")
    await session.refresh(progress)

    if completed:
        completed.correlation_id = correlation_id.get()
        await redis.xadd(completed.stream_key, completed.to_fields())
        logger.info(
            "event published", extra={"stream": completed.stream_key, "event_id": completed.event_id}
        )
    return progress_response(progress, quest)


router.include_router(quest_router)
