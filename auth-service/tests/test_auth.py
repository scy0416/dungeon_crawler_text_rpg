import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio

CREDENTIALS = {"username": "hero", "password": "password123"}


async def register_and_login(client: AsyncClient) -> str:
    await client.post("/auth/register", json=CREDENTIALS)
    response = await client.post("/auth/login", json=CREDENTIALS)
    return response.json()["access_token"]


async def test_register(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json=CREDENTIALS)
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "hero"
    assert "password" not in body and "hashed_password" not in body


async def test_register_duplicate_username(client: AsyncClient) -> None:
    await client.post("/auth/register", json=CREDENTIALS)
    response = await client.post("/auth/register", json=CREDENTIALS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"


async def test_register_validation_error_format(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={"username": "a", "password": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_login_wrong_password(client: AsyncClient) -> None:
    await client.post("/auth/register", json=CREDENTIALS)
    response = await client.post("/auth/login", json={**CREDENTIALS, "password": "wrong-pass"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_verify_valid_token(client: AsyncClient) -> None:
    token = await register_and_login(client)
    response = await client.get("/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": 1, "username": "hero"}


@pytest.mark.parametrize("authorization", [None, "Bearer invalid.token", "Basic abc"])
async def test_verify_invalid_token(client: AsyncClient, authorization: str | None) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = await client.get("/auth/verify", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
