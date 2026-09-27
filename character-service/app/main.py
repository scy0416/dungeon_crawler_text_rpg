import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.consumer import run_consumer
from app.db import SessionLocal, settings
from app.errors import register_error_handlers
from app.observability import add_correlation_middleware, setup_logging
from app.routes import SERVICE_NAME, router

setup_logging(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    consumer = asyncio.create_task(run_consumer(redis, SessionLocal, settings.consumer_name))
    yield
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await consumer
    await redis.aclose()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
add_correlation_middleware(app)
register_error_handlers(app)
app.include_router(router)
