from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

NotificationType = Literal["quest_completed", "level_up"]


class HealthResponse(BaseModel):
    status: str
    service: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class CharacterSnapshot(BaseModel):
    """character-service `GET /characters/{id}` 응답 중 소유자 확인에 필요한 필드."""

    id: int
    user_id: int
    level: int


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    character_id: int
    type: NotificationType
    message: str
    created_at: datetime
    read_at: datetime | None
