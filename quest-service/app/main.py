import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from app.consumer import StreamConsumer
from app.db import SessionLocal, settings
from app.errors import register_error_handlers
from app.handlers import GROUP, HANDLERS
from app.observability import add_correlation_middleware, outgoing_headers, setup_logging
from app.outbox import notify_relay, run_relay
from app.routes import SERVICE_NAME, router

setup_logging(SERVICE_NAME)


async def propagate_correlation_id(request: httpx.Request) -> None:
    """다른 서비스 호출에 X-Request-ID를 붙여 요청 흐름을 이어서 추적한다."""
    request.headers.update(outgoing_headers())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    consumer = StreamConsumer(
        redis, SessionLocal, GROUP, HANDLERS, settings.consumer_name, on_handled=notify_relay
    )
    tasks = [asyncio.create_task(consumer.run()), asyncio.create_task(run_relay(redis, SessionLocal))]
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        event_hooks={"request": [propagate_correlation_id]},
    ) as client:
        app.state.http_client = client
        yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await redis.aclose()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
add_correlation_middleware(app)
register_error_handlers(app)
app.include_router(router)
