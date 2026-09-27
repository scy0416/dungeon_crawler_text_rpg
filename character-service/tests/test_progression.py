import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Character, InventoryItem
from app.progression import apply_combat_result, apply_quest_reward
from shared.events import CombatResultEvent, LevelUpEvent, QuestCompletedEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]


def combat_event(**overrides: object) -> CombatResultEvent:
    fields: dict[str, object] = {
        "character_id": 1, "dungeon_id": 1, "monster_id": 1, "result": "win",
        "exp_gained": 0, "item_drops": [], "hp_remaining": 80, "mp_remaining": 40,
    }
    return CombatResultEvent.model_validate(fields | overrides)


@pytest.fixture
async def character(sessionmaker: Sessionmaker) -> Character:
    async with sessionmaker() as session:
        character = Character(id=1, user_id=1, name="Aria")
        session.add(character)
        await session.commit()
        return character


async def apply(
    sessionmaker: Sessionmaker, event: CombatResultEvent
) -> tuple[Character, LevelUpEvent | None]:
    """이벤트를 반영하고, 새 세션으로 다시 읽은 캐릭터와 반환된 레벨업 이벤트를 돌려준다."""
    async with sessionmaker() as session:
        level_up = await apply_combat_result(session, event)
    async with sessionmaker() as session:
        character = await session.get(Character, event.character_id)
        assert character is not None
        return character, level_up


async def test_win_updates_exp_hp_mp(sessionmaker: Sessionmaker, character: Character) -> None:
    updated, level_up = await apply(sessionmaker, combat_event(exp_gained=30))
    assert (updated.exp, updated.hp, updated.mp, updated.level) == (30, 80, 40, 1)
    assert level_up is None


async def test_lose_revives_with_one_hp(sessionmaker: Sessionmaker, character: Character) -> None:
    updated, _ = await apply(sessionmaker, combat_event(result="lose", hp_remaining=0))
    assert updated.hp == 1


async def test_level_up_raises_stats_and_restores(
    sessionmaker: Sessionmaker, character: Character
) -> None:
    # Lv1→2에 100, Lv2→3에 200 필요 → 350이면 Lv3, 남은 exp 50
    updated, level_up = await apply(sessionmaker, combat_event(exp_gained=350, hp_remaining=5))
    assert (updated.level, updated.exp) == (3, 50)
    assert (updated.max_hp, updated.max_mp, updated.atk, updated.defense) == (120, 60, 14, 7)
    assert (updated.hp, updated.mp) == (120, 60)
    assert level_up is not None
    assert (level_up.character_id, level_up.new_level) == (1, 3)


async def test_item_drops_stack_in_inventory(
    sessionmaker: Sessionmaker, character: Character
) -> None:
    await apply(sessionmaker, combat_event(item_drops=[2, 2]))
    await apply(sessionmaker, combat_event(item_drops=[2, 5]))
    async with sessionmaker() as session:
        items = await session.scalars(select(InventoryItem).order_by(InventoryItem.item_id))
        assert [(i.item_id, i.quantity) for i in items] == [(2, 3), (5, 1)]


async def test_duplicate_event_is_applied_once(
    sessionmaker: Sessionmaker, character: Character
) -> None:
    event = combat_event(exp_gained=30)
    await apply(sessionmaker, event)
    updated, _ = await apply(sessionmaker, event)
    assert updated.exp == 30


async def test_unknown_character_is_skipped(sessionmaker: Sessionmaker) -> None:
    async with sessionmaker() as session:
        assert await apply_combat_result(session, combat_event(character_id=999)) is None


async def test_quest_reward_adds_exp_without_touching_hp(
    sessionmaker: Sessionmaker, character: Character
) -> None:
    reward = QuestCompletedEvent(character_id=1, quest_id=1, reward_exp=50)
    async with sessionmaker() as session:
        assert await apply_quest_reward(session, reward) is None
        assert await apply_quest_reward(session, reward) is None  # 중복은 무시
    async with sessionmaker() as session:
        updated = await session.get(Character, 1)
        assert updated is not None
        assert (updated.exp, updated.hp) == (50, 100)
