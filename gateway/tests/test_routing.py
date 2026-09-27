from collections.abc import AsyncIterator

import httpx
import pytest

from app.config import settings
from app.main import app
from app.routes import get_http_client

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def upstream() -> list[httpx.Request]:
    """가짜 내부 서비스가 받은 요청 기록."""
    return []


@pytest.fixture
async def client(upstream: list[httpx.Request]) -> AsyncIterator[httpx.AsyncClient]:
    def fake_services(request: httpx.Request) -> httpx.Response:
        if request.url.host == "down":
            raise httpx.ConnectError("connection refused")
        upstream.append(request)
        url = str(request.url)
        if url.startswith(f"{settings.auth_service_url}/auth/verify"):
            if request.headers.get("authorization") == "Bearer good":
                return httpx.Response(200, json={"user_id": 7, "username": "hero"})
            return httpx.Response(
                401, json={"error": {"code": "INVALID_TOKEN", "message": "bad"}}
            )
        if url.startswith(settings.auth_service_url):
            return httpx.Response(201, json={"id": 1, "username": "hero"})
        if url.startswith(settings.character_service_url):
            return httpx.Response(200, json={"user_id": request.headers.get("x-user-id")})
        raise AssertionError(f"unexpected upstream: {url}")

    fake_client = httpx.AsyncClient(transport=httpx.MockTransport(fake_services))
    app.dependency_overrides[get_http_client] = lambda: fake_client
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as c:
        yield c
    app.dependency_overrides.clear()
    await fake_client.aclose()


async def test_public_auth_route_is_forwarded(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.post("/auth/register", json={"username": "hero", "password": "pw"})
    assert response.status_code == 201
    assert str(upstream[0].url) == f"{settings.auth_service_url}/auth/register"


async def test_internal_verify_route_is_not_exposed(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.get("/auth/verify")
    assert response.status_code == 404
    assert upstream == []


async def test_protected_route_without_token(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.get("/characters")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MISSING_TOKEN"
    assert upstream == []


async def test_protected_route_relays_auth_rejection(client: httpx.AsyncClient) -> None:
    response = await client.get("/characters", headers={"Authorization": "Bearer bad"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_protected_route_attaches_verified_user_id(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.get(
        "/characters/3",
        headers={"Authorization": "Bearer good", "X-User-Id": "999"},  # 위조 시도
    )
    assert response.status_code == 200
    forwarded = upstream[-1]
    assert str(forwarded.url) == f"{settings.character_service_url}/characters/3"
    assert forwarded.headers["x-user-id"] == "7"
    assert "authorization" not in forwarded.headers


async def test_upstream_down_returns_502(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_service_url", "http://down")
    response = await client.post("/auth/login", json={})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
