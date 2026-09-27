from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import AppError
from app.models import Character
from app.schemas import CharacterCreateRequest, CharacterResponse, HealthResponse

SERVICE_NAME = "character-service"

router = APIRouter()
character_router = APIRouter(prefix="/characters", tags=["characters"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user_id(x_user_id: Annotated[int | None, Header()] = None) -> int:
    """Gateway가 토큰 검증 후 붙여주는 X-User-Id 헤더로 요청자를 식별한다."""
    if x_user_id is None:
        raise AppError(401, "UNAUTHORIZED", "인증이 필요합니다.")
    return x_user_id


CurrentUserId = Annotated[int, Depends(get_current_user_id)]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@character_router.post("", response_model=CharacterResponse, status_code=201)
async def create_character(
    body: CharacterCreateRequest, user_id: CurrentUserId, session: Session
) -> CharacterResponse:
    character = Character(user_id=user_id, name=body.name)
    session.add(character)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppError(409, "CHARACTER_NAME_TAKEN", "이미 사용 중인 캐릭터 이름입니다.")
    await session.refresh(character)
    return CharacterResponse.model_validate(character)


@character_router.get("", response_model=list[CharacterResponse])
async def list_my_characters(user_id: CurrentUserId, session: Session) -> list[CharacterResponse]:
    characters = await session.scalars(
        select(Character).where(Character.user_id == user_id).order_by(Character.id)
    )
    return [CharacterResponse.model_validate(c) for c in characters]


@character_router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: int, session: Session) -> CharacterResponse:
    character = await session.get(Character, character_id)
    if character is None:
        raise AppError(404, "CHARACTER_NOT_FOUND", "캐릭터를 찾을 수 없습니다.")
    return CharacterResponse.model_validate(character)


router.include_router(character_router)
