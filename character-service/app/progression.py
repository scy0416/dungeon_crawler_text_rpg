"""전투 결과 반영 규칙 (기획서 4.4.1). 이벤트 컨슈머만 호출하는 내부 함수로, HTTP로 노출하지 않는다."""

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character, InventoryItem, ProcessedEvent
from shared.events import CombatResultEvent, LevelUpEvent

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


async def apply_combat_result(
    session: AsyncSession, event: CombatResultEvent
) -> LevelUpEvent | None:
    """전투 결과를 캐릭터에 반영한다. 레벨이 올랐으면 발행할 LevelUpEvent를 반환한다.

    처리 기록(processed_events)을 같은 트랜잭션에 남겨 같은 이벤트를 두 번 반영하지 않는다.
    """
    if await session.get(ProcessedEvent, event.event_id):
        logger.info("duplicate event skipped event_id=%s", event.event_id)
        return None

    session.add(ProcessedEvent(event_id=event.event_id))
    character = await session.get(Character, event.character_id, with_for_update=True)
    if character is None:
        logger.warning("character not found character_id=%s", event.character_id)
        await session.commit()
        return None

    level_before = character.level
    character.hp = min(event.hp_remaining, character.max_hp)
    character.mp = min(event.mp_remaining, character.max_mp)
    if event.result == "lose":
        character.hp = REVIVE_HP

    character.exp += event.exp_gained
    while character.exp >= required_exp(character.level):
        level_up(character)
    if character.level > level_before:
        character.hp, character.mp = character.max_hp, character.max_mp

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

    if character.level > level_before:
        return LevelUpEvent(character_id=character.id, new_level=character.level)
    return None
