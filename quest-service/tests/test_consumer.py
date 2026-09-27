import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.consumer import GROUP, NEW, PENDING, consume_batch, ensure_groups
from app.models import QuestProgress
from shared.events import CombatResultEvent, LevelUpEvent, QuestCompletedEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]
CONSUMER = "test-consumer"


@pytest.fixture
async def setup(sessionmaker: Sessionmaker, redis: FakeAsyncRedis) -> None:
    async with sessionmaker() as session:
        session.add_all([
            QuestProgress(character_id=1, user_id=1, quest_id=1, status="in_progress", progress=2),
            QuestProgress(character_id=1, user_id=1, quest_id=4, status="in_progress", progress=2),
        ])
        await session.commit()
    await ensure_groups(redis)


def slime_kill() -> CombatResultEvent:
    return CombatResultEvent(
        character_id=1, dungeon_id=1, monster_id=1, result="win",
        exp_gained=15, item_drops=[], hp_remaining=90, mp_remaining=50,
    )


async def completed_quest_ids(redis: FakeAsyncRedis) -> list[int]:
    entries = await redis.xrange(QuestCompletedEvent.stream_key)
    return [QuestCompletedEvent.from_fields(fields).quest_id for _, fields in entries]


async def test_consumes_both_streams_and_publishes_completion(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(CombatResultEvent.stream_key, slime_kill().to_fields())
    await redis.xadd(LevelUpEvent.stream_key, LevelUpEvent(character_id=1, new_level=3).to_fields())
    assert await consume_batch(redis, sessionmaker, CONSUMER, NEW) == 2
    assert sorted(await completed_quest_ids(redis)) == [1, 4]
    for stream in (CombatResultEvent.stream_key, LevelUpEvent.stream_key):
        assert (await redis.xpending(stream, GROUP))["pending"] == 0


async def test_pending_message_is_reprocessed_after_restart(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(CombatResultEvent.stream_key, slime_kill().to_fields())
    # 처리 도중 죽은 상황: 메시지를 받았지만 ACK하지 못함
    await redis.xreadgroup(GROUP, CONSUMER, {CombatResultEvent.stream_key: NEW})
    assert await consume_batch(redis, sessionmaker, CONSUMER, PENDING) == 1
    assert await completed_quest_ids(redis) == [1]


async def test_correlation_id_is_carried_to_published_event(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    event = slime_kill()
    event.correlation_id = "req-42"
    await redis.xadd(CombatResultEvent.stream_key, event.to_fields())
    await consume_batch(redis, sessionmaker, CONSUMER, NEW)
    [(_, fields)] = await redis.xrange(QuestCompletedEvent.stream_key)
    assert QuestCompletedEvent.from_fields(fields).correlation_id == "req-42"
