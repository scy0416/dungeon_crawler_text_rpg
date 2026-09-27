"""다른 서비스 HTTP 클라이언트. 다른 서비스 DB가 아니라 공개 API만 호출한다."""

import httpx

from app.db import settings
from app.errors import AppError
from app.schemas import CharacterSnapshot


async def fetch_character(client: httpx.AsyncClient, character_id: int) -> CharacterSnapshot | None:
    try:
        response = await client.get(f"{settings.character_service_url}/characters/{character_id}")
    except httpx.RequestError:
        raise AppError(502, "UPSTREAM_UNAVAILABLE", "character-service에 연결할 수 없습니다.")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise AppError(502, "UPSTREAM_ERROR", "character-service 응답이 올바르지 않습니다.")
    return CharacterSnapshot.model_validate(response.json())
