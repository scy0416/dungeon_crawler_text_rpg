import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.consumer import StreamConsumer, dlq_stream
from app.handlers import GROUP, HANDLERS
from app.models import Character
from app.outbox import relay_once
from shared.events import CombatResultEvent, LevelUpEvent, QuestCompletedEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]
STREAM = CombatResultEvent.stream_key


def make_consumer(
    redis: FakeAsyncRedis, sessionmaker: Sessionmaker, name: str = "c1", handlers: dict | None = None
) -> StreamConsumer:
    # 테스트에서는 방치 시간 조건 없이 바로 회수한다
    return StreamConsumer(redis, sessionmaker, GROUP, handlers or HANDLERS, name, claim_idle_ms=0)


@pytest.fixture
async def consumer(sessionmaker: Sessionmaker, redis: FakeAsyncRedis) -> StreamConsumer:
    async with sessionmaker() as session:
        session.add(Character(id=1, user_id=1, name="Aria"))
        await session.commit()
    consumer = make_consumer(redis, sessionmaker)
    await consumer.ensure_groups()
    return consumer


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


async def pending_count(redis: FakeAsyncRedis, stream: str = STREAM) -> int:
    return (await redis.xpending(stream, GROUP))["pending"]


async def test_ensure_groups_is_idempotent(consumer: StreamConsumer, redis: FakeAsyncRedis) -> None:
    await consumer.ensure_groups()
    for stream in HANDLERS:
        assert [g["name"] for g in await redis.xinfo_groups(stream)] == [GROUP]


async def test_consumes_event_and_acks(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, win_event(30).to_fields())
    assert await consumer.read_new() == 1
    assert (await get_character(sessionmaker)).exp == 30
    assert await pending_count(redis) == 0


async def test_level_up_is_published_through_outbox(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    event = win_event(100)
    event.correlation_id = "req-42"
    await redis.xadd(STREAM, event.to_fields())
    await consumer.read_new()
    # 릴레이가 돌기 전에는 스트림에 없다 (outbox에만 저장됨)
    assert await redis.xlen(LevelUpEvent.stream_key) == 0
    assert await relay_once(redis, sessionmaker) == 1

    [(_, fields)] = await redis.xrange(LevelUpEvent.stream_key)
    level_up = LevelUpEvent.from_fields(fields)
    assert (level_up.character_id, level_up.new_level, level_up.correlation_id) == (1, 2, "req-42")


async def test_quest_reward_grants_exp(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    reward = QuestCompletedEvent(character_id=1, quest_id=3, reward_exp=120)
    await redis.xadd(QuestCompletedEvent.stream_key, reward.to_fields())
    assert await consumer.read_new() == 1
    assert ((c := await get_character(sessionmaker)).level, c.exp) == (2, 20)


async def test_stale_message_of_dead_consumer_is_claimed(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, win_event(30).to_fields())
    # 다른 인스턴스가 메시지를 받은 뒤 ACK하지 못하고 죽은 상황
    await redis.xreadgroup(GROUP, "dead-instance", {STREAM: ">"})
    assert await pending_count(redis) == 1

    assert await consumer.claim_stale() == 1
    assert (await get_character(sessionmaker)).exp == 30
    assert await pending_count(redis) == 0


async def test_unparseable_message_goes_to_dlq_immediately(
    consumer: StreamConsumer, redis: FakeAsyncRedis
) -> None:
    await redis.xadd(STREAM, {"data": "not-json"})
    await consumer.read_new()
    assert await pending_count(redis) == 0
    [(_, entry)] = await redis.xrange(dlq_stream(STREAM))
    assert entry["consumer_group"] == GROUP
    assert entry["error"].startswith("unparseable")


async def test_schema_mismatch_goes_to_dlq_without_retry(
    consumer: StreamConsumer, redis: FakeAsyncRedis
) -> None:
    # 공통 필드만 있고 CombatResultEvent 필수 필드가 없는 메시지
    await redis.xadd(STREAM, {"data": "{}"})
    await consumer.read_new()
    assert await pending_count(redis) == 0
    [(_, entry)] = await redis.xrange(dlq_stream(STREAM))
    assert entry["error"].startswith("invalid payload")


async def test_failing_message_is_retried_then_moved_to_dlq(
    sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    attempts = 0

    async def always_fails(session: AsyncSession, fields: dict[str, str]) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("db down")

    consumer = make_consumer(redis, sessionmaker, handlers={STREAM: always_fails})
    await consumer.ensure_groups()
    await redis.xadd(STREAM, win_event(30).to_fields())

    await consumer.read_new()  # 1회차 실패 → pending 유지
    assert await pending_count(redis) == 1
    await consumer.claim_stale()  # 2회차 실패 → pending 유지
    assert await pending_count(redis) == 1
    await consumer.claim_stale()  # 3회차 실패 → DLQ
    assert attempts == 3
    assert await pending_count(redis) == 0
    [(_, entry)] = await redis.xrange(dlq_stream(STREAM))
    assert "db down" in entry["error"]
    assert CombatResultEvent.from_fields(entry).exp_gained == 30  # 원본 데이터 보존


async def test_transient_failure_succeeds_on_retry(
    consumer: StreamConsumer, sessionmaker: Sessionmaker, redis: FakeAsyncRedis
) -> None:
    failed_once = False

    async def flaky(session: AsyncSession, fields: dict[str, str]) -> None:
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("temporary")
        await HANDLERS[STREAM](session, fields)

    consumer.handlers = {STREAM: flaky}
    await redis.xadd(STREAM, win_event(30).to_fields())
    await consumer.read_new()
    await consumer.claim_stale()
    assert (await get_character(sessionmaker)).exp == 30
    assert await pending_count(redis) == 0
    assert await redis.xlen(dlq_stream(STREAM)) == 0
