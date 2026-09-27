"""퀘스트 진행 규칙 (기획서 4.5.1). 이벤트 컨슈머와 수락 API가 호출하는 내부 함수."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProcessedEvent, Quest, QuestProgress
from shared.events import CombatResultEvent, LevelUpEvent, QuestCompletedEvent

logger = logging.getLogger(__name__)

IN_PROGRESS = "in_progress"
COMPLETED = "completed"


def advance(progress: QuestProgress, quest: Quest, value: int) -> QuestCompletedEvent | None:
    """진행도를 value로 올린다(내려가지 않고 target_count를 넘지 않음). 완료되면 발행할 이벤트를 반환."""
    progress.progress = min(max(progress.progress, value), quest.target_count)
    if progress.progress < quest.target_count:
        return None
    progress.status = COMPLETED
    progress.completed_at = datetime.now(UTC)
    return QuestCompletedEvent(
        character_id=progress.character_id, quest_id=quest.id, reward_exp=quest.reward_exp
    )


async def mark_processed(session: AsyncSession, event_id: str) -> bool:
    """처음 보는 이벤트면 처리 기록을 추가하고 True, 이미 처리했으면 False."""
    if await session.get(ProcessedEvent, event_id):
        logger.info("duplicate event skipped", extra={"event_id": event_id})
        return False
    session.add(ProcessedEvent(event_id=event_id))
    return True


async def active_quests(
    session: AsyncSession, character_id: int, quest_types: tuple[str, ...]
) -> list[tuple[QuestProgress, Quest]]:
    rows = await session.execute(
        select(QuestProgress, Quest)
        .join(Quest, Quest.id == QuestProgress.quest_id)
        .where(
            QuestProgress.character_id == character_id,
            QuestProgress.status == IN_PROGRESS,
            Quest.type.in_(quest_types),
        )
        .with_for_update(of=QuestProgress)
    )
    return [(progress, quest) for progress, quest in rows.tuples()]


def combat_progress_amount(quest: Quest, event: CombatResultEvent) -> int:
    if quest.type == "kill_monster":
        return int(quest.target_id == event.monster_id)
    if quest.type == "win_dungeon":
        return int(quest.target_id == event.dungeon_id)
    if quest.type == "collect_item":
        return event.item_drops.count(quest.target_id)
    return 0


async def apply_combat_result(
    session: AsyncSession, event: CombatResultEvent
) -> list[QuestCompletedEvent]:
    completed: list[QuestCompletedEvent] = []
    if not await mark_processed(session, event.event_id):
        return completed
    if event.result == "win":
        types = ("kill_monster", "win_dungeon", "collect_item")
        for progress, quest in await active_quests(session, event.character_id, types):
            amount = combat_progress_amount(quest, event)
            if amount and (done := advance(progress, quest, progress.progress + amount)):
                completed.append(done)
    await session.commit()
    return completed


async def apply_level_up(session: AsyncSession, event: LevelUpEvent) -> list[QuestCompletedEvent]:
    completed: list[QuestCompletedEvent] = []
    if not await mark_processed(session, event.event_id):
        return completed
    for progress, quest in await active_quests(session, event.character_id, ("reach_level",)):
        if done := advance(progress, quest, event.new_level):
            completed.append(done)
    await session.commit()
    return completed
