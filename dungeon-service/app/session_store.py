"""진행 중인 전투 세션 저장소 (Redis, dungeon-service 전용 키 네임스페이스)."""

from redis.asyncio import Redis

from app.combat import CombatSession
from app.db import settings


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


async def delete_session(redis: Redis, character_id: int) -> None:
    await redis.delete(_key(character_id))
