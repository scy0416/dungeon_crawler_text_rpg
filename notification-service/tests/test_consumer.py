import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.consumer import StreamConsumer
from app.handlers import GROUP, HANDLERS
from app.models import Notification
from shared.events import LevelUpEvent, QuestCompletedEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def consumer(sessionmaker: Sessionmaker, redis: FakeAsyncRedis) -> StreamConsumer:
    consumer = StreamConsumer(redis, sessionmaker, GROUP, HANDLERS, "c1", claim_idle_ms=0)
    await consumer.ensure_groups()
    return consumer


async def notifications(sessionmaker: Sessionmaker) -> list[tuple[int, str, str]]:
    async with sessionmaker() as session:
        rows = await session.scalars(select(Notification).order_by(Notification.id))
        return [(n.character_id, n.type, n.message) for n in rows]


async def test_quest_completed_and_level_up_create_notifications(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    quest = QuestCompletedEvent(character_id=1, quest_id=3, quest_name="젤리 수집가", reward_exp=60)
    await redis.xadd(QuestCompletedEvent.stream_key, quest.to_fields())
    await redis.xadd(LevelUpEvent.stream_key, LevelUpEvent(character_id=1, new_level=2).to_fields())
    assert await consumer.read_new() == 2
    rows = await notifications(sessionmaker)
    assert [(c, t) for c, t, _ in rows] == [(1, "quest_completed"), (1, "level_up")]
    assert "젤리 수집가" in rows[0][2] and "60" in rows[0][2]
    assert "레벨 2" in rows[1][2]


async def test_duplicate_event_creates_one_notification(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    event = LevelUpEvent(character_id=1, new_level=2)
    await redis.xadd(LevelUpEvent.stream_key, event.to_fields())
    await redis.xadd(LevelUpEvent.stream_key, event.to_fields())  # 재발행(최소 한 번 전달)
    await consumer.read_new()
    assert len(await notifications(sessionmaker)) == 1


async def test_old_event_without_quest_name_falls_back_to_id(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    old = QuestCompletedEvent(character_id=1, quest_id=3, reward_exp=60)  # quest_name 없는 이전 버전
    await redis.xadd(QuestCompletedEvent.stream_key, old.to_fields())
    await consumer.read_new()
    [(_, _, message)] = await notifications(sessionmaker)
    assert "#3" in message
