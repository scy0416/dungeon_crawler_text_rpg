"""`dungeon.combat_result` 이벤트 컨슈머 (Redis Streams Consumer Group)."""

import asyncio
import logging

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.progression import apply_combat_result
from shared.events import CombatResultEvent, LevelUpEvent

logger = logging.getLogger(__name__)

GROUP = "character-service-group"
STREAM = CombatResultEvent.stream_key
BATCH_SIZE = 10
BLOCK_MS = 5000

# XREADGROUP의 읽기 시작 위치
PENDING = "0"  # 이 컨슈머가 받았지만 ACK하지 못한 메시지
NEW = ">"  # 아직 아무 컨슈머에게도 전달되지 않은 새 메시지


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):  # 이미 그룹이 있으면 무시
            raise


async def handle_entry(
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
    entry_id: str,
    fields: dict[str, str] | None,
) -> None:
    try:
        if fields:  # 스트림에서 삭제된 pending 메시지는 fields가 비어 있다
            event = CombatResultEvent.from_fields(fields)
            async with sessionmaker() as session:
                level_up = await apply_combat_result(session, event)
            if level_up:
                await redis.xadd(LevelUpEvent.stream_key, level_up.to_fields())
                logger.info("published %s event_id=%s", LevelUpEvent.stream_key, level_up.event_id)
    except Exception:
        # 초기 버전 실패 처리 원칙: 로그만 남기고 스킵 (DLQ는 Phase 5 확장 과제)
        logger.exception("failed to handle entry_id=%s, skipped", entry_id)
    await redis.xack(STREAM, GROUP, entry_id)


async def consume_batch(
    redis: Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
    consumer_name: str,
    start: str,
    block_ms: int | None = None,
) -> int:
    """한 번 읽어서 처리하고 처리한 메시지 수를 반환한다."""
    response = await redis.xreadgroup(
        GROUP, consumer_name, {STREAM: start}, count=BATCH_SIZE, block=block_ms
    )
    handled = 0
    for _stream, entries in response or []:
        for entry_id, fields in entries:
            await handle_entry(redis, sessionmaker, entry_id, fields)
            handled += 1
    return handled


async def run_consumer(
    redis: Redis, sessionmaker: async_sessionmaker[AsyncSession], consumer_name: str
) -> None:
    await ensure_group(redis)
    # 재시작 복구: 이전에 받고 ACK하지 못한 메시지부터 처리한다
    while await consume_batch(redis, sessionmaker, consumer_name, PENDING):
        pass
    logger.info("consumer started group=%s consumer=%s", GROUP, consumer_name)
    while True:
        try:
            await consume_batch(redis, sessionmaker, consumer_name, NEW, BLOCK_MS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("consumer loop error, retrying")
            await asyncio.sleep(1)
