from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    auth_service_url: str = "http://localhost:8001"
    character_service_url: str = "http://localhost:8002"
    dungeon_service_url: str = "http://localhost:8003"
    upstream_timeout_seconds: float = 5.0


settings = Settings()
