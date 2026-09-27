from collections.abc import AsyncIterator

import httpx
import pytest

from app.config import settings
from app.main import app, propagate_correlation_id
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
        if url.startswith(settings.notification_service_url):
            return httpx.Response(200, json={"user_id": request.headers.get("x-user-id")})
        if url.startswith(settings.quest_service_url):
            return httpx.Response(200, json={"user_id": request.headers.get("x-user-id")})
        if url.startswith(settings.dungeon_service_url):
            return httpx.Response(201, json={"user_id": request.headers.get("x-user-id")})
        if url.startswith(settings.character_service_url):
            return httpx.Response(200, json={"user_id": request.headers.get("x-user-id")})
        raise AssertionError(f"unexpected upstream: {url}")

    fake_client = httpx.AsyncClient(
        transport=httpx.MockTransport(fake_services),
        event_hooks={"request": [propagate_correlation_id]},
    )
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


async def test_dungeon_route_is_protected_and_forwarded(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    assert (await client.post("/dungeons/1/enter", json={})).status_code == 401
    response = await client.post(
        "/dungeons/1/enter", json={"character_id": 1}, headers={"Authorization": "Bearer good"}
    )
    assert response.status_code == 201
    forwarded = upstream[-1]
    assert str(forwarded.url) == f"{settings.dungeon_service_url}/dungeons/1/enter"
    assert forwarded.headers["x-user-id"] == "7"


async def test_quest_route_forwards_query_string(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.get(
        "/quests/progress", params={"character_id": 5}, headers={"Authorization": "Bearer good"}
    )
    assert response.status_code == 200
    forwarded = upstream[-1]
    assert str(forwarded.url) == f"{settings.quest_service_url}/quests/progress?character_id=5"
    assert forwarded.headers["x-user-id"] == "7"


async def test_request_id_is_generated_and_forwarded(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.get("/characters", headers={"Authorization": "Bearer good"})
    request_id = response.headers["x-request-id"]
    assert request_id
    # 토큰 검증 호출과 실제 전달 요청 모두 같은 ID를 가진다
    assert [r.headers["x-request-id"] for r in upstream] == [request_id, request_id]


async def test_client_request_id_is_kept(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    response = await client.post(
        "/auth/login", json={}, headers={"X-Request-ID": "trace-me"}
    )
    assert response.headers["x-request-id"] == "trace-me"
    assert upstream[-1].headers["x-request-id"] == "trace-me"


async def test_notification_route_is_protected_and_forwarded(
    client: httpx.AsyncClient, upstream: list[httpx.Request]
) -> None:
    assert (await client.get("/notifications")).status_code == 401
    response = await client.post("/notifications/9/read", headers={"Authorization": "Bearer good"})
    assert response.status_code == 200
    forwarded = upstream[-1]
    assert str(forwarded.url) == f"{settings.notification_service_url}/notifications/9/read"
    assert forwarded.headers["x-user-id"] == "7"
