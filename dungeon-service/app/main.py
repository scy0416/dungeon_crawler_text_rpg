import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from app.db import settings
from app.errors import register_error_handlers
from app.routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        app.state.http_client = client
        yield
    await app.state.redis.aclose()


app = FastAPI(title="dungeon-service", lifespan=lifespan)
register_error_handlers(app)
app.include_router(router)
