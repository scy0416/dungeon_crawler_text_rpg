"""`dungeon.combat_result`, `quest.completed` 이벤트 컨슈머 (Redis Streams Consumer Group)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability import correlation_id
from app.progression import apply_combat_result, apply_quest_reward
from shared.events import CombatResultEvent, Event, QuestCompletedEvent

logger = logging.getLogger(__name__)

GROUP = "character-service-group"
BATCH_SIZE = 10
BLOCK_MS = 5000

# XREADGROUP의 읽기 시작 위치
PENDING = "0"  # 이 컨슈머가 받았지만 ACK하지 못한 메시지
NEW = ">"  # 아직 아무 컨슈머에게도 전달되지 않은 새 메시지

Handler = Callable[[AsyncSession, dict[str, str]], Awaitable[Event | None]]


async def on_combat_result(session: AsyncSession, fields: dict[str, str]) -> Event | None:
    return await apply_combat_result(session, CombatResultEvent.from_fields(fields))


async def on_quest_completed(session: AsyncSession, fields: dict[str, str]) -> Event | None:
    return await apply_quest_reward(session, QuestCompletedEvent.from_fields(fields))


# 구독하는 스트림 → 처리 함수 (처리 결과로 발행할 이벤트가 있으면 반환)
HANDLERS: dict[str, Handler] = {
    CombatResultEvent.stream_key: on_combat_result,
    QuestCompletedEvent.stream_key: on_quest_completed,
}


async def ensure_groups(redis: Redis) -> None:
    for stream in HANDLERS:
        try:
            await redis.xgroup_create(stream, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):  # 이미 그룹이 있으면 무시
                raise


async def handle_entry(
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
    stream: str,
    entry_id: str,
    fields: dict[str, str] | None,
) -> None:
    token = None
    try:
        if fields:  # 스트림에서 삭제된 pending 메시지는 fields가 비어 있다
            received = Event.from_fields(fields)
            # 받은 이벤트의 correlation_id를 이 처리 과정의 로그와 후속 이벤트에 이어 붙인다
            token = correlation_id.set(received.correlation_id or received.event_id)
            logger.info("event consumed", extra={"stream": stream, "event_id": received.event_id})
            async with sessionmaker() as session:
                event = await HANDLERS[stream](session, fields)
            if event:
                event.correlation_id = correlation_id.get()
                await redis.xadd(event.stream_key, event.to_fields())
                logger.info(
                    "event published", extra={"stream": event.stream_key, "event_id": event.event_id}
                )
    except Exception:
        # 초기 버전 실패 처리 원칙: 로그만 남기고 스킵 (DLQ는 Phase 5 확장 과제)
        logger.exception("event handling failed, skipped", extra={"stream": stream, "entry_id": entry_id})
    await redis.xack(stream, GROUP, entry_id)
    if token:
        correlation_id.reset(token)


async def consume_batch(
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
    consumer_name: str,
    start: str,
    block_ms: int | None = None,
) -> int:
    """구독 중인 모든 스트림에서 한 번 읽어서 처리하고 처리한 메시지 수를 반환한다."""
    response = await redis.xreadgroup(
        GROUP, consumer_name, {stream: start for stream in HANDLERS}, count=BATCH_SIZE, block=block_ms
    )
    handled = 0
    for stream, entries in response or []:
        for entry_id, fields in entries:
            await handle_entry(redis, sessionmaker, stream, entry_id, fields)
            handled += 1
    return handled


async def run_consumer(
    redis: Redis, sessionmaker: async_sessionmaker[AsyncSession], consumer_name: str
) -> None:
    await ensure_groups(redis)
    # 재시작 복구: 이전에 받고 ACK하지 못한 메시지부터 처리한다
    while await consume_batch(redis, sessionmaker, consumer_name, PENDING):
        pass
    logger.info("consumer started", extra={"group": GROUP, "consumer": consumer_name})
    while True:
        try:
            await consume_batch(redis, sessionmaker, consumer_name, NEW, BLOCK_MS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("consumer loop error, retrying")
            await asyncio.sleep(1)
