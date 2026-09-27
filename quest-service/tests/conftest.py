from collections.abc import AsyncIterator

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import get_session, settings
from app.main import app
from app.models import Base, Quest
from app.routes import get_http_client, get_redis

# 테스트용 퀘스트: id → (type, target_id, target_count, min_level, reward_exp)
QUESTS = {
    1: ("kill_monster", 1, 3, 1, 50),
    2: ("collect_item", 1, 3, 1, 60),
    3: ("win_dungeon", 1, 2, 1, 150),
    4: ("reach_level", None, 3, 1, 100),
    5: ("win_dungeon", 2, 5, 3, 300),
}

# 가짜 character-service 데이터: character_id → 응답 본문
CHARACTERS = {
    1: {"id": 1, "user_id": 1, "level": 1},
    2: {"id": 2, "user_id": 2, "level": 1},
    3: {"id": 3, "user_id": 1, "level": 3},
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # 테스트는 인메모리 SQLite로 격리한다 (운영 스키마는 Alembic이 관리)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        session.add_all(
            Quest(id=qid, name=f"quest{qid}", description="", type=t, target_id=target,
                  target_count=count, min_level=min_level, reward_exp=reward)
            for qid, (t, target, count, min_level, reward) in QUESTS.items()
        )
        await session.commit()
    yield sm
    await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], redis: FakeAsyncRedis
) -> AsyncIterator[httpx.AsyncClient]:
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
