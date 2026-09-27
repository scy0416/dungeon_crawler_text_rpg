"""character-service가 구독하는 스트림과 처리 함수."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.consumer import Handler
from app.progression import apply_combat_result, apply_quest_reward
from shared.events import CombatResultEvent, QuestCompletedEvent

GROUP = "character-service-group"


async def on_combat_result(session: AsyncSession, fields: dict[str, str]) -> None:
    await apply_combat_result(session, CombatResultEvent.from_fields(fields))


async def on_quest_completed(session: AsyncSession, fields: dict[str, str]) -> None:
    await apply_quest_reward(session, QuestCompletedEvent.from_fields(fields))


HANDLERS: dict[str, Handler] = {
    CombatResultEvent.stream_key: on_combat_result,
    QuestCompletedEvent.stream_key: on_quest_completed,
}
