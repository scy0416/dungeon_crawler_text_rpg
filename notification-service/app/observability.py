"""로깅/요청 추적 공통 설정 (모든 서비스에 같은 내용으로 둔다. 서비스 간 코드 공유 금지).

- 로그는 한 줄에 JSON 하나: {"ts", "level", "service", "logger", "correlation_id", "msg", ...extra}
- correlation ID: HTTP는 X-Request-ID 헤더, 이벤트는 correlation_id 필드로 전파한다
"""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response

REQUEST_ID_HEADER = "X-Request-ID"

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

logger = logging.getLogger("app.access")

# LogRecord 기본 속성. 이 외의 속성(logger.info(..., extra={...}))은 JSON 필드로 출력한다
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {
    "message", "asctime", "taskName", "color_message"  # color_message: uvicorn의 ANSI 색상 중복 메시지
}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "correlation_id": correlation_id.get(),
            "msg": record.getMessage(),
        }
        payload.update(
            (key, value) for key, value in vars(record).items() if key not in _STANDARD_ATTRS
        )
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # uvicorn 로그도 같은 포맷으로. 액세스 로그는 아래 미들웨어가 correlation ID와 함께 남긴다
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # httpx는 호출마다 INFO 로그를 남긴다. 서비스 간 호출은 받는 쪽 액세스 로그로 충분하다
    logging.getLogger("httpx").setLevel(logging.WARNING)


def outgoing_headers() -> dict[str, str]:
    """다른 서비스를 HTTP로 호출할 때 붙일 헤더."""
    current = correlation_id.get()
    return {REQUEST_ID_HEADER: current} if current else {}


def add_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = correlation_id.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return response
        except Exception:
            logger.exception(
                "request failed", extra={"method": request.method, "path": request.url.path}
            )
            raise
        finally:
            correlation_id.reset(token)
