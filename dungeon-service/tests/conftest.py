from collections.abc import AsyncIterator

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import get_session, settings
from app.main import app
from app.models import Base, Dungeon, Item, Monster, MonsterDrop
from app.routes import get_http_client, get_redis

# 가짜 character-service 데이터: character_id → 응답 본문
CHARACTERS = {
    1: {"id": 1, "user_id": 1, "name": "Aria", "level": 1, "hp": 100, "max_hp": 100,
        "mp": 50, "max_mp": 50, "atk": 10, "defense": 5},
    2: {"id": 2, "user_id": 2, "name": "Bran", "level": 1, "hp": 100, "max_hp": 100,
        "mp": 50, "max_mp": 50, "atk": 10, "defense": 5},
    3: {"id": 3, "user_id": 1, "name": "Cade", "level": 1, "hp": 1, "max_hp": 100,
        "mp": 5, "max_mp": 50, "atk": 10, "defense": 5},
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def client(redis: FakeAsyncRedis) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        session.add_all([
            Dungeon(id=1, name="테스트 동굴", description="", min_level=1),
            Dungeon(id=2, name="고렙 던전", description="", min_level=5),
            Item(id=1, name="젤리", description=""),
        ])
        await session.flush()
        session.add_all([
            Monster(id=1, dungeon_id=1, name="약한 슬라임", hp=1, atk=8, defense=0,
                    exp_reward=15, spawn_weight=1),
            Monster(id=2, dungeon_id=2, name="보스", hp=999, atk=99, defense=99,
                    exp_reward=999, spawn_weight=1),
        ])
        await session.flush()
        session.add(MonsterDrop(monster_id=1, item_id=1, drop_rate=1.0))
        await session.commit()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    def fake_character_service(request: httpx.Request) -> httpx.Response:
        character_id = int(request.url.path.rsplit("/", 1)[-1])
        if character_id in CHARACTERS:
            return httpx.Response(200, json=CHARACTERS[character_id])
        return httpx.Response(404, json={"error": {"code": "CHARACTER_NOT_FOUND", "message": ""}})

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(fake_character_service),
        base_url=settings.character_service_url,
    )
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_http_client] = lambda: http_client
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()
    await http_client.aclose()
    await engine.dispose()
