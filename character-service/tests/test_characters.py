import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

USER_1 = {"X-User-Id": "1"}
USER_2 = {"X-User-Id": "2"}


async def test_create_character_with_default_stats(client: AsyncClient) -> None:
    response = await client.post("/characters", json={"name": "Aria"}, headers=USER_1)
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == 1
    assert body["name"] == "Aria"
    assert (body["level"], body["exp"], body["hp"], body["mp"]) == (1, 0, 100, 50)


async def test_create_character_requires_user_header(client: AsyncClient) -> None:
    response = await client.post("/characters", json={"name": "Aria"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_create_character_duplicate_name(client: AsyncClient) -> None:
    await client.post("/characters", json={"name": "Aria"}, headers=USER_1)
    response = await client.post("/characters", json={"name": "Aria"}, headers=USER_2)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHARACTER_NAME_TAKEN"


async def test_list_returns_only_my_characters(client: AsyncClient) -> None:
    await client.post("/characters", json={"name": "Aria"}, headers=USER_1)
    await client.post("/characters", json={"name": "Bran"}, headers=USER_2)
    await client.post("/characters", json={"name": "Cade"}, headers=USER_1)
    response = await client.get("/characters", headers=USER_1)
    assert [c["name"] for c in response.json()] == ["Aria", "Cade"]


async def test_get_character(client: AsyncClient) -> None:
    created = await client.post("/characters", json={"name": "Aria"}, headers=USER_1)
    response = await client.get(f"/characters/{created.json()['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Aria"


async def test_get_character_not_found(client: AsyncClient) -> None:
    response = await client.get("/characters/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHARACTER_NOT_FOUND"
