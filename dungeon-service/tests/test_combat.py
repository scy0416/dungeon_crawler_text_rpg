import random

import pytest

from app.combat import (
    SKILL_MP_COST,
    CharacterState,
    CombatSession,
    MonsterState,
    NotEnoughMpError,
    calculate_damage,
    choose_monster_index,
    play_turn,
    roll_drops,
)


def make_session(
    seed: int = 42,
    char_hp: int = 100,
    char_mp: int = 50,
    monster_hp: int = 1000,
    monster_atk: int = 12,
) -> CombatSession:
    return CombatSession(
        user_id=1,
        dungeon_id=1,
        seed=seed,
        character=CharacterState(
            id=1, name="Aria", hp=char_hp, max_hp=100, mp=char_mp, max_mp=50, atk=10, defense=5
        ),
        monster=MonsterState(
            id=1, name="고블린", hp=monster_hp, max_hp=monster_hp, atk=monster_atk, defense=4,
            exp_reward=25,
        ),
    )


def test_damage_within_variance_or_critical() -> None:
    base = 10 - 4
    for seed in range(500):
        damage, critical = calculate_damage(random.Random(seed), 10, 4)
        normal = damage // 2 if critical else damage
        assert round(base * 0.8) <= normal <= round(base * 1.2)


def test_damage_is_at_least_one() -> None:
    for seed in range(100):
        damage, _ = calculate_damage(random.Random(seed), 1, 100)
        assert damage >= 1


def test_same_seed_and_actions_are_reproducible() -> None:
    actions = ["attack", "defend", "skill", "attack", "flee", "attack"]
    first, second = make_session(), make_session()
    logs_first = [play_turn(first, a).log for a in actions]
    logs_second = [play_turn(second, a).log for a in actions]
    assert logs_first == logs_second
    assert first == second


def test_skill_consumes_mp() -> None:
    session = make_session()
    play_turn(session, "skill")
    assert session.character.mp == 50 - SKILL_MP_COST


def test_skill_without_enough_mp_does_not_consume_turn() -> None:
    session = make_session(char_mp=SKILL_MP_COST - 1)
    with pytest.raises(NotEnoughMpError):
        play_turn(session, "skill")
    assert session.turn == 0


def test_defend_halves_monster_damage() -> None:
    session = make_session(monster_atk=40)
    play_turn(session, "defend")
    # defend 턴에는 플레이어 판정이 없으므로 몬스터 공격이 그 턴의 첫 난수를 쓴다
    damage, _ = calculate_damage(random.Random("42:1"), 40, 5)
    assert session.character.hp == 100 - max(1, damage // 2)


def test_win_ends_turn_before_monster_attacks() -> None:
    session = make_session(monster_hp=1)
    result = play_turn(session, "attack")
    assert result.status == "win"
    assert session.monster.hp == 0
    assert session.character.hp == 100


def test_lose_when_character_hp_reaches_zero() -> None:
    session = make_session(char_hp=1)
    result = play_turn(session, "defend")
    assert result.status == "lose"
    assert session.character.hp == 0


def test_flee_success_and_failure() -> None:
    outcomes = {play_turn(make_session(seed=seed), "flee").status for seed in range(50)}
    assert outcomes == {"flee", "ongoing"}


def test_monster_choice_and_drops_are_deterministic() -> None:
    assert choose_monster_index(7, [50, 35, 15]) == choose_monster_index(7, [50, 35, 15])
    assert roll_drops(7, [(2, 0.5), (1, 0.5)]) == roll_drops(7, [(1, 0.5), (2, 0.5)])
    assert roll_drops(7, [(1, 1.0), (2, 0.0)]) == [1]
