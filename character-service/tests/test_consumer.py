import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.consumer import GROUP, NEW, PENDING, STREAM, consume_batch, ensure_group
from app.models import Character
from shared.events import CombatResultEvent, LevelUpEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]
CONSUMER = "test-consumer"


@pytest.fixture
async def setup(sessionmaker: Sessionmaker, redis: FakeAsyncRedis) -> None:
    async with sessionmaker() as session:
        session.add(Character(id=1, user_id=1, name="Aria"))
        await session.commit()
    await ensure_group(redis)


def win_event(exp_gained: int) -> CombatResultEvent:
    return CombatResultEvent(
        character_id=1, dungeon_id=1, monster_id=1, result="win",
        exp_gained=exp_gained, item_drops=[], hp_remaining=90, mp_remaining=50,
    )


async def get_character(sessionmaker: Sessionmaker) -> Character:
    async with sessionmaker() as session:
        character = await session.get(Character, 1)
        assert character is not None
        return character


async def test_ensure_group_is_idempotent(redis: FakeAsyncRedis) -> None:
    await ensure_group(redis)
    await ensure_group(redis)
    groups = await redis.xinfo_groups(STREAM)
    assert [g["name"] for g in groups] == [GROUP]


async def test_consumes_event_and_acks(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, win_event(30).to_fields())
    assert await consume_batch(redis, sessionmaker, CONSUMER, NEW) == 1
    assert (await get_character(sessionmaker)).exp == 30
    assert (await redis.xpending(STREAM, GROUP))["pending"] == 0


async def test_level_up_publishes_event(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, win_event(100).to_fields())
    await consume_batch(redis, sessionmaker, CONSUMER, NEW)
    [(_, fields)] = await redis.xrange(LevelUpEvent.stream_key)
    event = LevelUpEvent.from_fields(fields)
    assert (event.character_id, event.new_level) == (1, 2)


async def test_pending_message_is_reprocessed_after_restart(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, win_event(30).to_fields())
    # 처리 도중 죽은 상황: 메시지를 받았지만 ACK하지 못함
    await redis.xreadgroup(GROUP, CONSUMER, {STREAM: NEW})
    assert (await redis.xpending(STREAM, GROUP))["pending"] == 1

    # 재시작 후 같은 컨슈머 이름으로 pending부터 처리
    assert await consume_batch(redis, sessionmaker, CONSUMER, PENDING) == 1
    assert (await get_character(sessionmaker)).exp == 30
    assert (await redis.xpending(STREAM, GROUP))["pending"] == 0


async def test_malformed_message_is_skipped(
    setup: None, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, {"data": "not-json"})
    assert await consume_batch(redis, sessionmaker, CONSUMER, NEW) == 1
    assert (await redis.xpending(STREAM, GROUP))["pending"] == 0
