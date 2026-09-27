from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import settings
from app.errors import register_error_handlers
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 내부 서비스 호출용 커넥션 풀을 앱 전체에서 공유한다
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="gateway", lifespan=lifespan)
register_error_handlers(app)
app.include_router(router)
