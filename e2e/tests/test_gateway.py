"""Gateway 라우팅·인증 위임·공통 에러 포맷·요청 추적 검증."""

import httpx
import pytest

from conftest import Player


@pytest.mark.parametrize("path", ["/characters", "/dungeons", "/quests"])
def test_protected_routes_require_token(client: httpx.Client, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MISSING_TOKEN"


def test_invalid_token_is_rejected_by_auth_service(client: httpx.Client) -> None:
    response = client.get("/characters", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_internal_verify_endpoint_is_not_exposed(player: Player) -> None:
    assert player.get("/auth/verify").status_code == 404


def test_spoofed_user_header_is_ignored(player: Player, client: httpx.Client) -> None:
    other = client.post(
        "/characters", json={"name": player.username[:14] + "-alt"},
        headers={**player.headers, "X-User-Id": "999999"},
    ).json()
    mine = {c["id"] for c in player.get("/characters").json()}
    assert other["id"] in mine


def test_validation_error_uses_common_format(client: httpx.Client) -> None:
    response = client.post("/auth/register", json={"username": "a", "password": "x"})
    assert response.status_code == 422
    assert set(response.json()["error"]) == {"code", "message"}


def test_request_id_is_returned(client: httpx.Client) -> None:
    generated = client.get("/health")
    assert generated.headers["x-request-id"]
    kept = client.get("/health", headers={"X-Request-ID": "e2e-trace"})
    assert kept.headers["x-request-id"] == "e2e-trace"
