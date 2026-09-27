"""웹 클라이언트(nginx) 검증: 정적 페이지 서빙과 /api/* → Gateway 프록시."""

import os

import httpx
import pytest

WEB_URL = os.environ.get("WEB_URL", "http://localhost:8080")


@pytest.fixture(scope="module")
def web() -> httpx.Client:
    client = httpx.Client(base_url=WEB_URL, timeout=10)
    try:
        client.get("/").raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"웹 클라이언트가 실행 중이 아닙니다 ({WEB_URL}).")
    return client


def test_serves_client_page_and_assets(web: httpx.Client) -> None:
    page = web.get("/")
    assert "던전 크롤러" in page.text
    assert web.get("/app.js").status_code == 200
    assert web.get("/style.css").status_code == 200


def test_api_is_proxied_to_gateway(web: httpx.Client) -> None:
    assert web.get("/api/health").json() == {"status": "ok", "service": "gateway"}
    protected = web.get("/api/characters")
    assert protected.status_code == 401
    assert protected.json()["error"]["code"] == "MISSING_TOKEN"
    assert protected.headers["x-request-id"]
