"""Transactional Outbox (기획서 5.3).

이벤트를 상태 변경과 같은 DB 트랜잭션으로 outbox 테이블에 저장하고,
릴레이 태스크가 미발행 행을 Redis Streams로 발행한다.
이벤트를 발행하는 서비스(character/quest)에 같은 내용으로 둔다.
"""

import asyncio
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import OutboxEvent
from app.observability import correlation_id
from shared.events import DATA_FIELD, Event

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
POLL_INTERVAL_SECONDS = 1.0

_wakeup = asyncio.Event()


def add_to_outbox(session: AsyncSession, event: Event) -> None:
    """이벤트를 outbox에 추가한다. 호출한 쪽의 트랜잭션과 함께 커밋된다."""
    if event.correlation_id is None:
        event.correlation_id = correlation_id.get()
    session.add(
        OutboxEvent(event_id=event.event_id, stream=event.stream_key, payload=event.model_dump_json())
    )


def notify_relay() -> None:
    """커밋 직후 호출하면 폴링 주기를 기다리지 않고 바로 발행한다."""
    _wakeup.set()


async def relay_once(redis: Redis, sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """미발행 행을 한 묶음 발행하고 발행한 개수를 반환한다."""
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(BATCH_SIZE)
                # 여러 인스턴스의 릴레이가 같은 행을 동시에 잡지 않도록
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            # XADD 후 커밋 전에 죽으면 다시 발행된다 → 소비자가 event_id로 중복을 걸러낸다
            await redis.xadd(row.stream, {DATA_FIELD: row.payload})
            row.published_at = datetime.now(UTC)
            token = correlation_id.set(Event.model_validate_json(row.payload).correlation_id)
            logger.info("event published", extra={"stream": row.stream, "event_id": row.event_id})
            correlation_id.reset(token)
        await session.commit()
    return len(rows)


async def run_relay(redis: Redis, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    logger.info("outbox relay started")
    while True:
        _wakeup.clear()
        try:
            while await relay_once(redis, sessionmaker) == BATCH_SIZE:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox relay error, retrying")
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=POLL_INTERVAL_SECONDS)
        except TimeoutError:
            pass
