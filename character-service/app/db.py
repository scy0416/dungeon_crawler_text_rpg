import socket
from collections.abc import AsyncIterator

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://character_user:character_pw@localhost:5432/character_db"
    redis_url: str = "redis://localhost:6379/0"
    # Consumer Group 안에서 이 인스턴스를 구분하는 이름. 재시작 후 pending 메시지를
    # 이어받으려면 재시작 전후로 같은 이름이어야 한다.
    consumer_name: str = socket.gethostname()


settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
