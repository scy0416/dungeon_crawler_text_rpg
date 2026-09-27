"""Redis Streams Consumer Group 컨슈머 (기획서 5.3).

이벤트를 구독하는 모든 서비스에 같은 내용으로 둔다 (서비스 간 코드 공유 금지).
서비스별 그룹 이름과 스트림 → 처리 함수는 `app/handlers.py`에 둔다.

- 처리 성공 → XACK
- 처리 실패 → ACK하지 않고 pending으로 남김 → XAUTOCLAIM으로 주기적으로 재시도
  (죽은 인스턴스가 남긴 pending 메시지도 같은 방식으로 다른 인스턴스가 회수)
- 전달 횟수가 max_deliveries에 도달한 뒤에도 실패, 또는 파싱·스키마 검증 실패 → `{stream}.dlq`로 이동 후 ACK
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability import correlation_id
from shared.events import Event

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, dict[str, str]], Awaitable[object]]

NEW = ">"  # 아직 아무 컨슈머에게도 전달되지 않은 새 메시지


def dlq_stream(stream: str) -> str:
    return f"{stream}.dlq"


@dataclass
class StreamConsumer:
    redis: Redis
    sessionmaker: async_sessionmaker[AsyncSession]
    group: str
    handlers: dict[str, Handler]
    name: str
    # 처리 성공 후 호출 (예: outbox 릴레이 깨우기)
    on_handled: Callable[[], None] | None = None
    batch_size: int = 10
    block_ms: int = 5000
    claim_idle_ms: int = 30_000
    claim_interval_seconds: float = 10.0
    max_deliveries: int = 3

    async def ensure_groups(self) -> None:
        for stream in self.handlers:
            try:
                await self.redis.xgroup_create(stream, self.group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):  # 이미 그룹이 있으면 무시
                    raise

    async def read_new(self, block_ms: int | None = None) -> int:
        """새 메시지를 한 번 읽어서 처리하고 처리한 메시지 수를 반환한다."""
        response = await self.redis.xreadgroup(
            self.group,
            self.name,
            {stream: NEW for stream in self.handlers},
            count=self.batch_size,
            block=block_ms,
        )
        handled = 0
        for stream, entries in response or []:
            for entry_id, fields in entries:
                await self.handle_entry(stream, entry_id, fields, deliveries=1)
                handled += 1
        return handled

    async def claim_stale(self) -> int:
        """claim_idle_ms 이상 방치된 pending 메시지를 가져와 다시 처리한다."""
        handled = 0
        for stream in self.handlers:
            cursor = "0-0"
            while True:
                cursor, entries, _deleted = await self.redis.xautoclaim(
                    stream,
                    self.group,
                    self.name,
                    min_idle_time=self.claim_idle_ms,
                    start_id=cursor,
                    count=self.batch_size,
                )
                for entry_id, fields in entries:
                    deliveries = await self.delivery_count(stream, entry_id)
                    await self.handle_entry(stream, entry_id, fields, deliveries)
                    handled += 1
                if cursor == "0-0":
                    break
        return handled

    async def delivery_count(self, stream: str, entry_id: str) -> int:
        pending = await self.redis.xpending_range(
            stream, self.group, min=entry_id, max=entry_id, count=1
        )
        return pending[0]["times_delivered"] if pending else 1

    async def handle_entry(
        self, stream: str, entry_id: str, fields: dict[str, str] | None, deliveries: int
    ) -> None:
        if not fields:  # 스트림에서 삭제된 메시지
            await self.redis.xack(stream, self.group, entry_id)
            return
        try:
            received = Event.from_fields(fields)
        except (KeyError, ValidationError) as exc:
            await self.dead_letter(stream, entry_id, fields, f"unparseable: {exc}")
            return

        # 받은 이벤트의 correlation_id를 이 처리 과정의 로그와 후속 이벤트에 이어 붙인다
        token = correlation_id.set(received.correlation_id or received.event_id)
        log_extra = {"stream": stream, "event_id": received.event_id, "deliveries": deliveries}
        try:
            logger.info("event consumed", extra=log_extra)
            async with self.sessionmaker() as session:
                await self.handlers[stream](session, fields)
            await self.redis.xack(stream, self.group, entry_id)
            if self.on_handled:
                self.on_handled()
        except ValidationError as exc:
            # 스키마에 맞지 않는 이벤트는 재시도해도 소용없다
            await self.dead_letter(stream, entry_id, fields, f"invalid payload: {exc}")
        except Exception as exc:
            if deliveries >= self.max_deliveries:
                logger.exception("event handling failed, giving up", extra=log_extra)
                await self.dead_letter(stream, entry_id, fields, repr(exc))
            else:
                # ACK하지 않으면 pending에 남아 claim_stale에서 다시 처리된다
                logger.warning("event handling failed, will retry", extra=log_extra, exc_info=True)
        finally:
            correlation_id.reset(token)

    async def dead_letter(
        self, stream: str, entry_id: str, fields: dict[str, str], error: str
    ) -> None:
        await self.redis.xadd(
            dlq_stream(stream),
            {
                **fields,
                "original_stream": stream,
                "original_id": entry_id,
                "consumer_group": self.group,
                "error": error,
            },
        )
        await self.redis.xack(stream, self.group, entry_id)
        logger.error(
            "event moved to DLQ",
            extra={"stream": stream, "entry_id": entry_id, "dlq": dlq_stream(stream), "error": error},
        )

    async def run(self) -> None:
        await self.ensure_groups()
        logger.info("consumer started", extra={"group": self.group, "consumer": self.name})
        last_claim = float("-inf")
        while True:
            try:
                if time.monotonic() - last_claim >= self.claim_interval_seconds:
                    await self.claim_stale()
                    last_claim = time.monotonic()
                await self.read_new(self.block_ms)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("consumer loop error, retrying")
                await asyncio.sleep(1)
