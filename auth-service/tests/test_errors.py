from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_error_handlers
from app.observability import add_correlation_middleware


def test_unexpected_error_uses_common_format() -> None:
    app = FastAPI()
    add_correlation_middleware(app)
    register_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "서버 내부 오류가 발생했습니다."}
    }
    assert "secret detail" not in response.text
