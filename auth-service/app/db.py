from collections.abc import AsyncIterator

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# 로컬 개발용 기본값. 배포 환경에서는 반드시 JWT_SECRET 환경변수(비밀값)로 덮어쓴다
DEV_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://auth_user:auth_pw@localhost:5432/auth_db"
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
