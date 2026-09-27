import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Notification

pytestmark = pytest.mark.anyio

USER_1 = {"X-User-Id": "1"}


@pytest.fixture
async def seeded(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        session.add_all([
            Notification(character_id=1, type="level_up", message="레벨 2 달성!", source_event_id="e1"),
            Notification(character_id=1, type="quest_completed", message="퀘스트 완료", source_event_id="e2"),
            Notification(character_id=2, type="level_up", message="남의 알림", source_event_id="e3"),
        ])
        await session.commit()


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.json() == {"status": "ok", "service": "notification-service"}


async def test_list_newest_first(client: httpx.AsyncClient, seeded: None) -> None:
    response = await client.get("/notifications", params={"character_id": 1}, headers=USER_1)
    assert [n["id"] for n in response.json()] == [2, 1]


async def test_list_others_character_is_forbidden(client: httpx.AsyncClient, seeded: None) -> None:
    response = await client.get("/notifications", params={"character_id": 2}, headers=USER_1)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_CHARACTER_OWNER"


async def test_mark_read_and_unread_filter(client: httpx.AsyncClient, seeded: None) -> None:
    read = await client.post("/notifications/1/read", headers=USER_1)
    assert read.status_code == 200 and read.json()["read_at"] is not None
    unread = await client.get(
        "/notifications", params={"character_id": 1, "unread_only": True}, headers=USER_1
    )
    assert [n["id"] for n in unread.json()] == [2]


async def test_mark_read_of_others_notification_is_forbidden(
    client: httpx.AsyncClient, seeded: None
) -> None:
    assert (await client.post("/notifications/3/read", headers=USER_1)).status_code == 403


async def test_requires_user_header(client: httpx.AsyncClient) -> None:
    response = await client.get("/notifications", params={"character_id": 1})
    assert response.status_code == 401
