"""전투 규칙 (기획서 4.4.1). I/O 없는 순수 로직이라 단위 테스트로 규칙을 검증한다.

모든 난수는 세션 시드에서 파생한 Random으로 만든다 → 같은 시드·같은 행동이면 결과가 재현된다.
"""

import random
from typing import Literal

from pydantic import BaseModel

Action = Literal["attack", "defend", "skill", "flee"]
CombatStatus = Literal["ongoing", "win", "lose", "flee"]

SKILL_MP_COST = 10
FLEE_CHANCE = 0.5
CRITICAL_CHANCE = 0.1


class CharacterState(BaseModel):
    id: int
    name: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    atk: int
    defense: int


class MonsterState(BaseModel):
    id: int
    name: str
    hp: int
    max_hp: int
    atk: int
    defense: int
    exp_reward: int


class CombatSession(BaseModel):
    user_id: int
    dungeon_id: int
    seed: int
    turn: int = 0
    character: CharacterState
    monster: MonsterState


class TurnResult(BaseModel):
    status: CombatStatus
    log: list[str]


class NotEnoughMpError(Exception):
    pass


def calculate_damage(rng: random.Random, atk: int, defense: int) -> tuple[int, bool]:
    base = max(1, atk - defense)
    damage = max(1, round(base * rng.uniform(0.8, 1.2)))
    critical = rng.random() < CRITICAL_CHANCE
    return (damage * 2 if critical else damage), critical


def choose_monster_index(seed: int, spawn_weights: list[int]) -> int:
    rng = random.Random(f"{seed}:spawn")
    return rng.choices(range(len(spawn_weights)), weights=spawn_weights)[0]


def roll_drops(seed: int, drop_table: list[tuple[int, float]]) -> list[int]:
    """drop_table: (item_id, drop_rate) 목록. 재현성을 위해 item_id 순으로 굴린다."""
    rng = random.Random(f"{seed}:drops")
    return [item_id for item_id, rate in sorted(drop_table) if rng.random() < rate]


def play_turn(session: CombatSession, action: Action) -> TurnResult:
    """플레이어 행동 → 몬스터 반격 순으로 1턴을 진행하고 session을 갱신한다."""
    character, monster = session.character, session.monster
    if action == "skill" and character.mp < SKILL_MP_COST:
        raise NotEnoughMpError

    session.turn += 1
    rng = random.Random(f"{session.seed}:{session.turn}")
    log: list[str] = []
    defending = False

    if action in ("attack", "skill"):
        atk = character.atk
        if action == "skill":
            character.mp -= SKILL_MP_COST
            atk *= 2
        damage, critical = calculate_damage(rng, atk, monster.defense)
        monster.hp = max(0, monster.hp - damage)
        move = "강타" if action == "skill" else "공격"
        log.append(f"{character.name}의 {move}! {monster.name}에게 {damage} 피해" + (" (치명타!)" if critical else ""))
        if monster.hp == 0:
            log.append(f"{monster.name}을(를) 쓰러뜨렸다!")
            return TurnResult(status="win", log=log)
    elif action == "defend":
        defending = True
        log.append(f"{character.name}은(는) 방어 자세를 취했다.")
    elif action == "flee":
        if rng.random() < FLEE_CHANCE:
            log.append("도망에 성공했다!")
            return TurnResult(status="flee", log=log)
        log.append("도망에 실패했다!")

    damage, critical = calculate_damage(rng, monster.atk, character.defense)
    if defending:
        damage = max(1, damage // 2)
    character.hp = max(0, character.hp - damage)
    log.append(f"{monster.name}의 공격! {character.name}에게 {damage} 피해" + (" (치명타!)" if critical else ""))
    if character.hp == 0:
        log.append(f"{character.name}은(는) 쓰러졌다...")
        return TurnResult(status="lose", log=log)
    return TurnResult(status="ongoing", log=log)
