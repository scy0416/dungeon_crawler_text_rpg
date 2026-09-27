import httpx
import pytest
from fakeredis import FakeAsyncRedis

from shared.events import CombatResultEvent

pytestmark = pytest.mark.anyio

USER_1 = {"X-User-Id": "1"}


async def published_events(redis: FakeAsyncRedis) -> list[CombatResultEvent]:
    entries = await redis.xrange(CombatResultEvent.stream_key)
    return [CombatResultEvent.from_fields(fields) for _, fields in entries]


async def test_list_dungeons(client: httpx.AsyncClient) -> None:
    response = await client.get("/dungeons", headers=USER_1)
    assert [d["id"] for d in response.json()] == [1, 2]


async def test_enter_creates_session(client: httpx.AsyncClient, redis: FakeAsyncRedis) -> None:
    response = await client.post("/dungeons/1/enter", json={"character_id": 1}, headers=USER_1)
    assert response.status_code == 201
    body = response.json()
    assert body["monster"]["name"] == "약한 슬라임"
    assert body["character"]["hp"] == 100
    assert await redis.exists("dungeon:session:1")


async def test_enter_twice_conflicts(client: httpx.AsyncClient) -> None:
    await client.post("/dungeons/1/enter", json={"character_id": 1}, headers=USER_1)
    response = await client.post("/dungeons/1/enter", json={"character_id": 1}, headers=USER_1)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMBAT_IN_PROGRESS"


@pytest.mark.parametrize(
    ("dungeon_id", "character_id", "status", "code"),
    [
        (99, 1, 404, "DUNGEON_NOT_FOUND"),
        (1, 99, 404, "CHARACTER_NOT_FOUND"),
        (1, 2, 403, "NOT_CHARACTER_OWNER"),
        (2, 1, 403, "LEVEL_TOO_LOW"),
    ],
)
async def test_enter_rejections(
    client: httpx.AsyncClient, dungeon_id: int, character_id: int, status: int, code: str
) -> None:
    response = await client.post(
        f"/dungeons/{dungeon_id}/enter", json={"character_id": character_id}, headers=USER_1
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_combat_without_session(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/dungeons/1/combat", json={"character_id": 1, "action": "attack"}, headers=USER_1
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_ACTIVE_COMBAT"


async def test_win_publishes_event_and_ends_session(
    client: httpx.AsyncClient, redis: FakeAsyncRedis
) -> None:
    await client.post("/dungeons/1/enter", json={"character_id": 1}, headers=USER_1)
    response = await client.post(
        "/dungeons/1/combat", json={"character_id": 1, "action": "attack"}, headers=USER_1
    )
    body = response.json()
    assert body["status"] == "win"
    assert body["rewards"] == {"exp_gained": 15, "items": [{"id": 1, "name": "젤리"}]}
    assert not await redis.exists("dungeon:session:1")

    [event] = await published_events(redis)
    assert (event.character_id, event.monster_id, event.result) == (1, 1, "win")
    assert (event.exp_gained, event.item_drops, event.hp_remaining) == (15, [1], 100)


async def test_lose_publishes_event_without_rewards(
    client: httpx.AsyncClient, redis: FakeAsyncRedis
) -> None:
    await client.post("/dungeons/1/enter", json={"character_id": 3}, headers=USER_1)
    response = await client.post(
        "/dungeons/1/combat", json={"character_id": 3, "action": "defend"}, headers=USER_1
    )
    assert response.json()["status"] == "lose"
    [event] = await published_events(redis)
    assert (event.result, event.exp_gained, event.item_drops, event.hp_remaining) == (
        "lose", 0, [], 0
    )


async def test_skill_without_mp(client: httpx.AsyncClient) -> None:
    await client.post("/dungeons/1/enter", json={"character_id": 3}, headers=USER_1)
    response = await client.post(
        "/dungeons/1/combat", json={"character_id": 3, "action": "skill"}, headers=USER_1
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_ENOUGH_MP"


async def test_combat_by_other_user_is_forbidden(client: httpx.AsyncClient) -> None:
    await client.post("/dungeons/1/enter", json={"character_id": 1}, headers=USER_1)
    response = await client.post(
        "/dungeons/1/combat",
        json={"character_id": 1, "action": "attack"},
        headers={"X-User-Id": "2"},
    )
    assert response.status_code == 403
