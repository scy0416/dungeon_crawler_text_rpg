"""quest-service가 구독하는 스트림과 처리 함수."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.consumer import Handler
from app.tracking import apply_combat_result, apply_level_up
from shared.events import CombatResultEvent, LevelUpEvent

GROUP = "quest-service-group"


async def on_combat_result(session: AsyncSession, fields: dict[str, str]) -> None:
    await apply_combat_result(session, CombatResultEvent.from_fields(fields))


async def on_level_up(session: AsyncSession, fields: dict[str, str]) -> None:
    await apply_level_up(session, LevelUpEvent.from_fields(fields))


HANDLERS: dict[str, Handler] = {
    CombatResultEvent.stream_key: on_combat_result,
    LevelUpEvent.stream_key: on_level_up,
}
