import httpx
import pytest
from fakeredis import FakeAsyncRedis

from shared.events import QuestCompletedEvent

pytestmark = pytest.mark.anyio

USER_1 = {"X-User-Id": "1"}


async def test_list_quests(client: httpx.AsyncClient) -> None:
    response = await client.get("/quests", headers=USER_1)
    assert [q["id"] for q in response.json()] == [1, 2, 3, 4, 5]


async def test_accept_quest(client: httpx.AsyncClient) -> None:
    response = await client.post("/quests/1/accept", json={"character_id": 1}, headers=USER_1)
    assert response.status_code == 201
    body = response.json()
    assert (body["status"], body["progress"], body["target_count"]) == ("in_progress", 0, 3)


async def test_accept_twice_conflicts(client: httpx.AsyncClient) -> None:
    await client.post("/quests/1/accept", json={"character_id": 1}, headers=USER_1)
    response = await client.post("/quests/1/accept", json={"character_id": 1}, headers=USER_1)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QUEST_ALREADY_ACCEPTED"


@pytest.mark.parametrize(
    ("quest_id", "character_id", "status", "code"),
    [
        (99, 1, 404, "QUEST_NOT_FOUND"),
        (1, 99, 404, "CHARACTER_NOT_FOUND"),
        (1, 2, 403, "NOT_CHARACTER_OWNER"),
        (5, 1, 403, "LEVEL_TOO_LOW"),
    ],
)
async def test_accept_rejections(
    client: httpx.AsyncClient, quest_id: int, character_id: int, status: int, code: str
) -> None:
    response = await client.post(
        f"/quests/{quest_id}/accept", json={"character_id": character_id}, headers=USER_1
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_accept_reach_level_starts_from_current_level(client: httpx.AsyncClient) -> None:
    response = await client.post("/quests/4/accept", json={"character_id": 1}, headers=USER_1)
    assert (response.json()["status"], response.json()["progress"]) == ("in_progress", 1)


async def test_accept_reach_level_already_reached_completes_immediately(
    client: httpx.AsyncClient, redis: FakeAsyncRedis
) -> None:
    response = await client.post("/quests/4/accept", json={"character_id": 3}, headers=USER_1)
    assert response.json()["status"] == "completed"
    [(_, fields)] = await redis.xrange(QuestCompletedEvent.stream_key)
    event = QuestCompletedEvent.from_fields(fields)
    assert (event.character_id, event.quest_id, event.reward_exp) == (3, 4, 100)


async def test_progress_lists_only_own_character(client: httpx.AsyncClient) -> None:
    await client.post("/quests/1/accept", json={"character_id": 1}, headers=USER_1)
    await client.post("/quests/2/accept", json={"character_id": 1}, headers=USER_1)
    mine = await client.get("/quests/progress", params={"character_id": 1}, headers=USER_1)
    assert [p["quest_id"] for p in mine.json()] == [1, 2]
    others = await client.get(
        "/quests/progress", params={"character_id": 1}, headers={"X-User-Id": "2"}
    )
    assert others.json() == []
