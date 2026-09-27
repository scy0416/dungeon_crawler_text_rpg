import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import QuestProgress
from app.tracking import apply_combat_result, apply_level_up
from shared.events import CombatResultEvent, LevelUpEvent

pytestmark = pytest.mark.anyio

Sessionmaker = async_sessionmaker[AsyncSession]


def combat_event(**overrides: object) -> CombatResultEvent:
    fields: dict[str, object] = {
        "character_id": 1, "dungeon_id": 1, "monster_id": 1, "result": "win",
        "exp_gained": 15, "item_drops": [], "hp_remaining": 80, "mp_remaining": 40,
    }
    return CombatResultEvent.model_validate(fields | overrides)


async def accept(sessionmaker: Sessionmaker, *quest_ids: int, progress: int = 0) -> None:
    async with sessionmaker() as session:
        session.add_all(
            QuestProgress(character_id=1, user_id=1, quest_id=qid, status="in_progress",
                          progress=progress)
            for qid in quest_ids
        )
        await session.commit()


async def progress_of(sessionmaker: Sessionmaker) -> dict[int, tuple[str, int]]:
    async with sessionmaker() as session:
        rows = await session.scalars(select(QuestProgress))
        return {p.quest_id: (p.status, p.progress) for p in rows}


async def combat(sessionmaker: Sessionmaker, event: CombatResultEvent) -> list[int]:
    async with sessionmaker() as session:
        return [e.quest_id for e in await apply_combat_result(session, event)]


async def test_win_advances_matching_quests(sessionmaker: Sessionmaker) -> None:
    # 1: 슬라임(1) 처치, 2: 아이템(1) 수집, 3: 던전(1) 승리
    await accept(sessionmaker, 1, 2, 3)
    await combat(sessionmaker, combat_event(item_drops=[1, 1]))
    assert await progress_of(sessionmaker) == {
        1: ("in_progress", 1), 2: ("in_progress", 2), 3: ("in_progress", 1)
    }


async def test_non_matching_target_does_not_advance(sessionmaker: Sessionmaker) -> None:
    await accept(sessionmaker, 1, 3)
    await combat(sessionmaker, combat_event(monster_id=2, dungeon_id=2))
    assert await progress_of(sessionmaker) == {1: ("in_progress", 0), 3: ("in_progress", 0)}


@pytest.mark.parametrize("result", ["lose", "flee"])
async def test_lose_or_flee_does_not_advance(sessionmaker: Sessionmaker, result: str) -> None:
    await accept(sessionmaker, 1)
    await combat(sessionmaker, combat_event(result=result))
    assert await progress_of(sessionmaker) == {1: ("in_progress", 0)}


async def test_completion_caps_progress_and_emits_event(sessionmaker: Sessionmaker) -> None:
    await accept(sessionmaker, 2, progress=2)  # 아이템 3개 중 2개 획득 상태
    completed = await combat(sessionmaker, combat_event(item_drops=[1, 1, 1]))
    assert completed == [2]
    assert await progress_of(sessionmaker) == {2: ("completed", 3)}


async def test_completed_quest_is_not_advanced_again(sessionmaker: Sessionmaker) -> None:
    await accept(sessionmaker, 3, progress=1)
    assert await combat(sessionmaker, combat_event()) == [3]
    assert await combat(sessionmaker, combat_event()) == []


async def test_duplicate_event_is_applied_once(sessionmaker: Sessionmaker) -> None:
    await accept(sessionmaker, 1)
    event = combat_event()
    await combat(sessionmaker, event)
    await combat(sessionmaker, event)
    assert await progress_of(sessionmaker) == {1: ("in_progress", 1)}


async def test_level_up_advances_reach_level_quest(sessionmaker: Sessionmaker) -> None:
    await accept(sessionmaker, 4, progress=1)
    async with sessionmaker() as session:
        assert await apply_level_up(session, LevelUpEvent(character_id=1, new_level=2)) == []
    async with sessionmaker() as session:
        [done] = await apply_level_up(session, LevelUpEvent(character_id=1, new_level=3))
    assert (done.quest_id, done.reward_exp) == (4, 100)
    assert await progress_of(sessionmaker) == {4: ("completed", 3)}
