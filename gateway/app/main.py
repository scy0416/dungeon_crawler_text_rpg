from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import settings
from app.errors import register_error_handlers
from app.observability import add_correlation_middleware, outgoing_headers, setup_logging
from app.routes import SERVICE_NAME, router

setup_logging(SERVICE_NAME)


async def propagate_correlation_id(request: httpx.Request) -> None:
    """다른 서비스 호출에 X-Request-ID를 붙여 요청 흐름을 이어서 추적한다."""
    request.headers.update(outgoing_headers())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 내부 서비스 호출용 커넥션 풀을 앱 전체에서 공유한다
    async with httpx.AsyncClient(
        timeout=settings.upstream_timeout_seconds,
        event_hooks={"request": [propagate_correlation_id]},
    ) as client:
        app.state.http_client = client
        yield


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
add_correlation_middleware(app)
register_error_handlers(app)
app.include_router(router)
