import logging
import secrets
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import session_store
from app.clients import fetch_character
from app.combat import (
    CharacterState,
    CombatSession,
    MonsterState,
    NotEnoughMpError,
    SKILL_MP_COST,
    choose_monster_index,
    play_turn,
    roll_drops,
)
from app.db import get_session
from app.errors import AppError
from app.models import Dungeon, Item, Monster, MonsterDrop
from app.observability import correlation_id
from app.schemas import (
    CharacterView,
    CombatRequest,
    CombatTurnResponse,
    DungeonResponse,
    EnterRequest,
    EnterResponse,
    HealthResponse,
    ItemView,
    MonsterView,
    Rewards,
)
from shared.events import CombatResultEvent

SERVICE_NAME = "dungeon-service"

logger = logging.getLogger(__name__)

router = APIRouter()
dungeon_router = APIRouter(prefix="/dungeons", tags=["dungeons"])


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


def character_view(combat: CombatSession) -> CharacterView:
    return CharacterView.model_validate(combat.character.model_dump())


def monster_view(combat: CombatSession) -> MonsterView:
    return MonsterView.model_validate(combat.monster.model_dump())


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@dungeon_router.get("", response_model=list[DungeonResponse])
async def list_dungeons(session: Session, user_id: CurrentUserId) -> list[DungeonResponse]:
    dungeons = await session.scalars(select(Dungeon).order_by(Dungeon.id))
    return [DungeonResponse.model_validate(d) for d in dungeons]


@dungeon_router.post("/{dungeon_id}/enter", response_model=EnterResponse, status_code=201)
async def enter_dungeon(
    dungeon_id: int,
    body: EnterRequest,
    user_id: CurrentUserId,
    session: Session,
    redis: RedisClient,
    http: HttpClient,
) -> EnterResponse:
    dungeon = await session.get(Dungeon, dungeon_id)
    if dungeon is None:
        raise AppError(404, "DUNGEON_NOT_FOUND", "던전을 찾을 수 없습니다.")
    if await session_store.get_session(redis, body.character_id):
        raise AppError(409, "COMBAT_IN_PROGRESS", "이미 진행 중인 전투가 있습니다.")

    # 다른 서비스의 데이터는 HTTP API로 가져온다 (DB 직접 접근 금지)
    character = await fetch_character(http, body.character_id)
    if character is None:
        raise AppError(404, "CHARACTER_NOT_FOUND", "캐릭터를 찾을 수 없습니다.")
    if character.user_id != user_id:
        raise AppError(403, "NOT_CHARACTER_OWNER", "본인의 캐릭터만 입장할 수 있습니다.")
    if character.level < dungeon.min_level:
        raise AppError(403, "LEVEL_TOO_LOW", f"레벨 {dungeon.min_level} 이상만 입장할 수 있습니다.")

    monsters = list(
        await session.scalars(
            select(Monster).where(Monster.dungeon_id == dungeon_id).order_by(Monster.id)
        )
    )
    seed = secrets.randbits(32)
    monster = monsters[choose_monster_index(seed, [m.spawn_weight for m in monsters])]
    combat = CombatSession(
        user_id=user_id,
        dungeon_id=dungeon_id,
        seed=seed,
        character=CharacterState.model_validate(character.model_dump()),
        monster=MonsterState(
            id=monster.id,
            name=monster.name,
            hp=monster.hp,
            max_hp=monster.hp,
            atk=monster.atk,
            defense=monster.defense,
            exp_reward=monster.exp_reward,
        ),
    )
    if not await session_store.create_session(redis, combat):
        raise AppError(409, "COMBAT_IN_PROGRESS", "이미 진행 중인 전투가 있습니다.")

    return EnterResponse(
        dungeon_id=dungeon_id,
        character=character_view(combat),
        monster=monster_view(combat),
        message=f"{dungeon.name}에 들어섰다. {monster.name}이(가) 나타났다!",
    )


@dungeon_router.post("/{dungeon_id}/combat", response_model=CombatTurnResponse)
async def combat_turn(
    dungeon_id: int,
    body: CombatRequest,
    user_id: CurrentUserId,
    session: Session,
    redis: RedisClient,
) -> CombatTurnResponse:
    combat = await session_store.get_session(redis, body.character_id)
    if combat is None:
        raise AppError(404, "NO_ACTIVE_COMBAT", "진행 중인 전투가 없습니다.")
    if combat.user_id != user_id:
        raise AppError(403, "NOT_CHARACTER_OWNER", "본인의 전투만 진행할 수 있습니다.")
    if combat.dungeon_id != dungeon_id:
        raise AppError(400, "WRONG_DUNGEON", "다른 던전에서 진행 중인 전투입니다.")

    try:
        result = play_turn(combat, body.action)
    except NotEnoughMpError:
        raise AppError(400, "NOT_ENOUGH_MP", f"MP가 부족합니다. (필요 MP: {SKILL_MP_COST})")

    response = CombatTurnResponse(
        turn=combat.turn,
        action=body.action,
        status=result.status,
        log=result.log,
        character=character_view(combat),
        monster=monster_view(combat),
    )
    if result.status == "ongoing":
        await session_store.save_session(redis, combat)
        return response

    exp_gained, item_ids = 0, []
    if result.status == "win":
        exp_gained = combat.monster.exp_reward
        drops = await session.scalars(
            select(MonsterDrop).where(MonsterDrop.monster_id == combat.monster.id)
        )
        item_ids = roll_drops(combat.seed, [(d.item_id, d.drop_rate) for d in drops])

    # 전투 결과는 HTTP 호출 없이 이벤트로만 다른 서비스에 전파한다
    event = CombatResultEvent(
        character_id=combat.character.id,
        dungeon_id=combat.dungeon_id,
        monster_id=combat.monster.id,
        result=result.status,
        exp_gained=exp_gained,
        item_drops=item_ids,
        hp_remaining=combat.character.hp,
        mp_remaining=combat.character.mp,
        correlation_id=correlation_id.get(),
    )
    await session_store.end_session_with_event(redis, combat.character.id, event)
    logger.info(
        "event published",
        extra={"stream": event.stream_key, "event_id": event.event_id, "result": event.result},
    )

    items = {i.id: i for i in await session.scalars(select(Item).where(Item.id.in_(item_ids)))}
    response.rewards = Rewards(
        exp_gained=exp_gained,
        items=[ItemView(id=i, name=items[i].name) for i in item_ids],
    )
    return response


router.include_router(dungeon_router)
