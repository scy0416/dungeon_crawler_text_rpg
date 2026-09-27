"""E2E 공통 픽스처. 클라이언트는 Gateway(기본 http://localhost:8000) 하나만 사용한다."""

import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TypeVar

import httpx
import pytest

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
EVENT_TIMEOUT_SECONDS = 10.0

T = TypeVar("T")


@dataclass
class Player:
    """회원가입·로그인·캐릭터 생성까지 마친 플레이어."""

    client: httpx.Client
    username: str
    headers: dict[str, str]
    character_id: int

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        return self.client.get(path, headers=self.headers, **kwargs)

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        return self.client.post(path, headers=self.headers, **kwargs)

    def character(self) -> dict:
        return self.get(f"/characters/{self.character_id}").json()


def wait_until(fetch: Callable[[], T], condition: Callable[[T], bool]) -> T:
    """이벤트는 비동기로 반영되므로(최종적 일관성) 조건을 만족할 때까지 폴링한다."""
    deadline = time.monotonic() + EVENT_TIMEOUT_SECONDS
    while True:
        value = fetch()
        if condition(value):
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for condition, last value: {value}")
        time.sleep(0.2)


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=GATEWAY_URL, timeout=10) as c:
        try:
            c.get("/health").raise_for_status()
        except httpx.HTTPError:
            pytest.skip(f"스택이 실행 중이 아닙니다 ({GATEWAY_URL}). `docker compose up -d` 후 실행하세요.")
        yield c


def unique_name(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@pytest.fixture
def player(client: httpx.Client) -> Player:
    username = unique_name("e2e")
    credentials = {"username": username, "password": "password123"}
    client.post("/auth/register", json=credentials).raise_for_status()
    token = client.post("/auth/login", json=credentials).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/characters", json={"name": username}, headers=headers)
    created.raise_for_status()
    return Player(client, username, headers, created.json()["id"])
