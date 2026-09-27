import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.consumer import run_consumer
from app.db import SessionLocal, settings
from app.errors import register_error_handlers
from app.routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    consumer = asyncio.create_task(run_consumer(redis, SessionLocal, settings.consumer_name))
    yield
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await consumer
    await redis.aclose()


app = FastAPI(title="character-service", lifespan=lifespan)
register_error_handlers(app)
app.include_router(router)
