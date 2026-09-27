from pydantic import BaseModel, ConfigDict

from app.combat import Action, CombatStatus


class HealthResponse(BaseModel):
    status: str
    service: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class CharacterSnapshot(BaseModel):
    """character-service `GET /characters/{id}` 응답 중 전투에 필요한 필드."""

    id: int
    user_id: int
    name: str
    level: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    atk: int
    defense: int


class DungeonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    min_level: int


class EnterRequest(BaseModel):
    character_id: int


class CombatRequest(BaseModel):
    character_id: int
    action: Action


class CharacterView(BaseModel):
    id: int
    name: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int


class MonsterView(BaseModel):
    id: int
    name: str
    hp: int
    max_hp: int


class EnterResponse(BaseModel):
    dungeon_id: int
    character: CharacterView
    monster: MonsterView
    message: str


class ItemView(BaseModel):
    id: int
    name: str


class Rewards(BaseModel):
    exp_gained: int
    items: list[ItemView]


class CombatTurnResponse(BaseModel):
    turn: int
    action: Action
    status: CombatStatus
    log: list[str]
    character: CharacterView
    monster: MonsterView
    rewards: Rewards | None = None
