from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class CharacterCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=20)


class CharacterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    level: int
    exp: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    atk: int
    defense: int
    created_at: datetime


class InventoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: int
    quantity: int
