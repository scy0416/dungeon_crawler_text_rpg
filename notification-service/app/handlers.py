"""notification-service가 구독하는 스트림과 처리 함수."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.consumer import Handler
from app.notifier import notify_level_up, notify_quest_completed
from shared.events import LevelUpEvent, QuestCompletedEvent

GROUP = "notification-service-group"


async def on_quest_completed(session: AsyncSession, fields: dict[str, str]) -> None:
    await notify_quest_completed(session, QuestCompletedEvent.from_fields(fields))


async def on_level_up(session: AsyncSession, fields: dict[str, str]) -> None:
    await notify_level_up(session, LevelUpEvent.from_fields(fields))


HANDLERS: dict[str, Handler] = {
    QuestCompletedEvent.stream_key: on_quest_completed,
    LevelUpEvent.stream_key: on_level_up,
}
