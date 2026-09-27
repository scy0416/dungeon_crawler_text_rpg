import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import OutboxEvent
from app.observability import correlation_id
from app.outbox import add_to_outbox, relay_once
from shared.events import LevelUpEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]


async def test_relay_publishes_once_and_marks_published(
    sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    async with sessionmaker() as session:
        add_to_outbox(session, LevelUpEvent(character_id=1, new_level=2))
        add_to_outbox(session, LevelUpEvent(character_id=1, new_level=3))
        await session.commit()

    assert await relay_once(redis, sessionmaker) == 2
    assert await relay_once(redis, sessionmaker) == 0  # 이미 발행한 행은 다시 보내지 않는다
    levels = [LevelUpEvent.from_fields(f).new_level for _, f in await redis.xrange(LevelUpEvent.stream_key)]
    assert levels == [2, 3]
    async with sessionmaker() as session:
        assert all(row.published_at for row in await session.scalars(select(OutboxEvent)))


async def test_rolled_back_transaction_publishes_nothing(
    sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    async with sessionmaker() as session:
        add_to_outbox(session, LevelUpEvent(character_id=1, new_level=2))
        await session.rollback()
    assert await relay_once(redis, sessionmaker) == 0
    assert await redis.xlen(LevelUpEvent.stream_key) == 0


async def test_outbox_captures_current_correlation_id(sessionmaker: Sessionmaker) -> None:
    event = LevelUpEvent(character_id=1, new_level=2)
    token = correlation_id.set("req-7")
    try:
        async with sessionmaker() as session:
            add_to_outbox(session, event)
            await session.commit()
    finally:
        correlation_id.reset(token)
    assert event.correlation_id == "req-7"
