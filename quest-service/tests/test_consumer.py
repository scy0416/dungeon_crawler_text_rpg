import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.consumer import StreamConsumer, dlq_stream
from app.handlers import GROUP, HANDLERS
from app.models import QuestProgress
from app.outbox import relay_once
from shared.events import CombatResultEvent, LevelUpEvent, QuestCompletedEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def consumer(sessionmaker: Sessionmaker, redis: FakeAsyncRedis) -> StreamConsumer:
    async with sessionmaker() as session:
        session.add_all([
            QuestProgress(character_id=1, user_id=1, quest_id=1, status="in_progress", progress=2),
            QuestProgress(character_id=1, user_id=1, quest_id=4, status="in_progress", progress=2),
        ])
        await session.commit()
    consumer = StreamConsumer(redis, sessionmaker, GROUP, HANDLERS, "c1", claim_idle_ms=0)
    await consumer.ensure_groups()
    return consumer


def slime_kill() -> CombatResultEvent:
    return CombatResultEvent(
        character_id=1, dungeon_id=1, monster_id=1, result="win",
        exp_gained=15, item_drops=[], hp_remaining=90, mp_remaining=50,
    )


async def published_completions(redis: FakeAsyncRedis) -> list[QuestCompletedEvent]:
    entries = await redis.xrange(QuestCompletedEvent.stream_key)
    return [QuestCompletedEvent.from_fields(fields) for _, fields in entries]


async def test_consumes_both_streams_and_publishes_completion_via_outbox(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    event = slime_kill()
    event.correlation_id = "req-42"
    await redis.xadd(CombatResultEvent.stream_key, event.to_fields())
    await redis.xadd(LevelUpEvent.stream_key, LevelUpEvent(character_id=1, new_level=3).to_fields())
    assert await consumer.read_new() == 2
    assert await relay_once(redis, sessionmaker) == 2

    completions = {e.quest_id: e for e in await published_completions(redis)}
    assert sorted(completions) == [1, 4]
    assert completions[1].correlation_id == "req-42"
    for stream in HANDLERS:
        assert (await redis.xpending(stream, GROUP))["pending"] == 0


async def test_stale_message_of_dead_consumer_is_claimed(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(CombatResultEvent.stream_key, slime_kill().to_fields())
    await redis.xreadgroup(GROUP, "dead-instance", {CombatResultEvent.stream_key: ">"})
    assert await consumer.claim_stale() == 1
    await relay_once(redis, sessionmaker)
    assert [e.quest_id for e in await published_completions(redis)] == [1]


async def test_unparseable_message_goes_to_dlq(
    consumer: StreamConsumer, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(LevelUpEvent.stream_key, {"data": "{}"})
    await consumer.read_new()
    [(_, entry)] = await redis.xrange(dlq_stream(LevelUpEvent.stream_key))
    assert entry["consumer_group"] == GROUP
