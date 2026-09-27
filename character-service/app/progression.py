"""전투 결과·퀘스트 보상 반영 규칙 (기획서 4.4.1, 4.5.1). 이벤트 컨슈머만 호출하는 내부 함수로, HTTP로 노출하지 않는다."""

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character, InventoryItem, ProcessedEvent
from shared.events import CombatResultEvent, LevelUpEvent, QuestCompletedEvent

logger = logging.getLogger(__name__)

REVIVE_HP = 1
EXP_PER_LEVEL = 100
LEVEL_UP_STATS = {"max_hp": 10, "max_mp": 5, "atk": 2, "defense": 1}


def required_exp(level: int) -> int:
    return level * EXP_PER_LEVEL


def level_up(character: Character) -> None:
    character.exp -= required_exp(character.level)
    character.level += 1
    for stat, amount in LEVEL_UP_STATS.items():
        setattr(character, stat, getattr(character, stat) + amount)


def gain_exp(character: Character, amount: int) -> LevelUpEvent | None:
    """경험치를 더하고 필요하면 레벨업한다. 레벨이 올랐으면 발행할 LevelUpEvent를 반환한다."""
    level_before = character.level
    character.exp += amount
    while character.exp >= required_exp(character.level):
        level_up(character)
    if character.level == level_before:
        return None
    character.hp, character.mp = character.max_hp, character.max_mp
    return LevelUpEvent(character_id=character.id, new_level=character.level)


async def claim_event(
    session: AsyncSession, event_id: str, character_id: int
) -> Character | None:
    """처리 기록(processed_events)을 남기고 대상 캐릭터를 잠가서 가져온다.

    같은 트랜잭션에 기록하므로 같은 이벤트를 두 번 반영하지 않는다.
    이미 처리한 이벤트거나 캐릭터가 없으면 None.
    """
    if await session.get(ProcessedEvent, event_id):
        logger.info("duplicate event skipped", extra={"event_id": event_id})
        return None
    session.add(ProcessedEvent(event_id=event_id))
    character = await session.get(Character, character_id, with_for_update=True)
    if character is None:
        logger.warning("character not found", extra={"character_id": character_id})
        await session.commit()
    return character


async def apply_combat_result(
    session: AsyncSession, event: CombatResultEvent
) -> LevelUpEvent | None:
    """전투 결과를 캐릭터에 반영한다. 레벨이 올랐으면 발행할 LevelUpEvent를 반환한다."""
    character = await claim_event(session, event.event_id, event.character_id)
    if character is None:
        return None

    character.hp = min(event.hp_remaining, character.max_hp)
    character.mp = min(event.mp_remaining, character.max_mp)
    if event.result == "lose":
        character.hp = REVIVE_HP
    level_up_event = gain_exp(character, event.exp_gained)

    for item_id, count in Counter(event.item_drops).items():
        item = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.character_id == character.id, InventoryItem.item_id == item_id
            )
        )
        if item is None:
            item = InventoryItem(character_id=character.id, item_id=item_id, quantity=0)
            session.add(item)
        item.quantity += count

    await session.commit()
    return level_up_event


async def apply_quest_reward(
    session: AsyncSession, event: QuestCompletedEvent
) -> LevelUpEvent | None:
    """퀘스트 보상 경험치를 지급한다. 레벨이 올랐으면 발행할 LevelUpEvent를 반환한다."""
    character = await claim_event(session, event.event_id, event.character_id)
    if character is None:
        return None
    level_up_event = gain_exp(character, event.reward_exp)
    await session.commit()
    return level_up_event
