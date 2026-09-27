"""진행 중인 전투 세션 저장소 (Redis, dungeon-service 전용 키 네임스페이스)."""

from redis.asyncio import Redis

from app.combat import CombatSession
from app.db import settings
from shared.events import Event


def _key(character_id: int) -> str:
    return f"dungeon:session:{character_id}"


async def create_session(redis: Redis, session: CombatSession) -> bool:
    """세션이 없을 때만 만든다. 이미 진행 중인 전투가 있으면 False."""
    created = await redis.set(
        _key(session.character.id),
        session.model_dump_json(),
        ex=settings.combat_session_ttl_seconds,
        nx=True,
    )
    return bool(created)


async def get_session(redis: Redis, character_id: int) -> CombatSession | None:
    raw = await redis.get(_key(character_id))
    return CombatSession.model_validate_json(raw) if raw else None


async def save_session(redis: Redis, session: CombatSession) -> None:
    await redis.set(
        _key(session.character.id),
        session.model_dump_json(),
        ex=settings.combat_session_ttl_seconds,
    )


async def end_session_with_event(redis: Redis, character_id: int, event: Event) -> None:
    """전투 종료 이벤트 발행과 세션 삭제를 Redis MULTI 트랜잭션으로 원자 처리한다.

    둘 중 하나만 반영되면 "이벤트는 나갔는데 세션이 남음(재전투 불가)" 또는
    "세션은 지워졌는데 이벤트가 없음(보상 유실)"이 생긴다.
    """
    async with redis.pipeline(transaction=True) as pipe:
        pipe.xadd(event.stream_key, event.to_fields())
        pipe.delete(_key(character_id))
        await pipe.execute()
