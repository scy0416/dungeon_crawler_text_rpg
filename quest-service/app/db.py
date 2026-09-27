import socket
from collections.abc import AsyncIterator

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://quest_user:quest_pw@localhost:5432/quest_db"
    redis_url: str = "redis://localhost:6379/0"
    character_service_url: str = "http://localhost:8002"
    http_timeout_seconds: float = 5.0
    # Consumer Group 안에서 이 인스턴스를 구분하는 이름 (인스턴스마다 고유해야 함).
    # 죽은 인스턴스의 pending 메시지는 다른 인스턴스가 XAUTOCLAIM으로 회수한다.
    consumer_name: str = socket.gethostname()


settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
