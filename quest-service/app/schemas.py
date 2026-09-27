from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

QuestType = Literal["kill_monster", "collect_item", "win_dungeon", "reach_level"]
QuestStatus = Literal["in_progress", "completed"]


class HealthResponse(BaseModel):
    status: str
    service: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class CharacterSnapshot(BaseModel):
    """character-service `GET /characters/{id}` 응답 중 퀘스트에 필요한 필드."""

    id: int
    user_id: int
    level: int


class QuestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    type: QuestType
    target_id: int | None
    target_count: int
    min_level: int
    reward_exp: int


class AcceptRequest(BaseModel):
    character_id: int


class QuestProgressResponse(BaseModel):
    quest_id: int
    quest_name: str
    type: QuestType
    status: QuestStatus
    progress: int
    target_count: int
    reward_exp: int
    accepted_at: datetime
    completed_at: datetime | None
