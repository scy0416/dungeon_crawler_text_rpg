from collections.abc import AsyncIterator

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://dungeon_user:dungeon_pw@localhost:5432/dungeon_db"
    redis_url: str = "redis://localhost:6379/0"
    character_service_url: str = "http://localhost:8002"
    combat_session_ttl_seconds: int = 1800
    http_timeout_seconds: float = 5.0


settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
