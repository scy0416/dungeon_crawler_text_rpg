"""이벤트 → 알림 변환 규칙. 이벤트 컨슈머만 호출하는 내부 함수."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, ProcessedEvent
from shared.events import Event, LevelUpEvent, QuestCompletedEvent

logger = logging.getLogger(__name__)


async def save_notification(
    session: AsyncSession, event: Event, character_id: int, type_: str, message: str
) -> None:
    """알림을 저장한다. 처리 기록을 같은 트랜잭션에 남겨 같은 이벤트로 알림을 두 번 만들지 않는다."""
    if await session.get(ProcessedEvent, event.event_id):
        logger.info("duplicate event skipped", extra={"event_id": event.event_id})
        return
    session.add(ProcessedEvent(event_id=event.event_id))
    session.add(
        Notification(
            character_id=character_id, type=type_, message=message, source_event_id=event.event_id
        )
    )
    await session.commit()


async def notify_quest_completed(session: AsyncSession, event: QuestCompletedEvent) -> None:
    # 이벤트에 실린 quest_name을 쓰므로 quest-service를 호출할 필요가 없다
    name = event.quest_name or f"#{event.quest_id}"
    message = f"퀘스트 '{name}' 완료! 보상 {event.reward_exp} exp"
    await save_notification(session, event, event.character_id, "quest_completed", message)


async def notify_level_up(session: AsyncSession, event: LevelUpEvent) -> None:
    message = f"레벨 {event.new_level} 달성! 스탯이 오르고 HP/MP가 모두 회복됐습니다"
    await save_notification(session, event, event.character_id, "level_up", message)
