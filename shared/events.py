"""서비스 간 이벤트 페이로드 스키마 (Redis Streams).

발행/구독 양쪽이 이 모듈의 Pydantic 모델을 import해서 사용한다.
이벤트 필드를 바꿀 때는 이 파일과 기획서 "5. 이벤트 설계" 표를 먼저 수정한다.

스트림 엔트리 포맷: 필드 하나 `data`에 이벤트 JSON 전체를 담는다.
    await redis.xadd(Event.stream_key, event.to_fields())
    event = Event.from_fields(fields)
"""

import uuid
from datetime import UTC, datetime
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, Field

DATA_FIELD = "data"


class Event(BaseModel):
    stream_key: ClassVar[str]

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_fields(self) -> dict[str, str]:
        return {DATA_FIELD: self.model_dump_json()}

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> Self:
        return cls.model_validate_json(fields[DATA_FIELD])


CombatOutcome = Literal["win", "lose", "flee"]


class CombatResultEvent(Event):
    """전투 종료. dungeon-service 발행 → character-service, quest-service 구독."""

    stream_key: ClassVar[str] = "dungeon.combat_result"

    character_id: int
    dungeon_id: int
    monster_id: int
    result: CombatOutcome
    exp_gained: int
    item_drops: list[int]
    hp_remaining: int
    mp_remaining: int


class LevelUpEvent(Event):
    """레벨업. character-service 발행 → quest-service 구독."""

    stream_key: ClassVar[str] = "character.level_up"

    character_id: int
    new_level: int
