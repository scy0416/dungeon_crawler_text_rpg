"""엔드투엔드 시나리오: 회원가입 → 캐릭터 생성 → 던전 입장 → 전투 → 퀘스트 완료.

전투 결과는 HTTP 호출 없이 이벤트로만 character-service, quest-service에 전파되므로
반영 여부는 폴링(wait_until)으로 확인한다.
"""

from conftest import Player, wait_until

DUNGEON = 1
SLIME_QUEST = 1  # 슬라임 3마리 처치
MAX_FIGHTS = 80


def fight(player: Player) -> dict:
    """전투 한 판을 끝까지 진행하고 마지막 턴 응답을 반환한다."""
    turn = player.post(f"/dungeons/{DUNGEON}/enter", json={"character_id": player.character_id})
    assert turn.status_code == 201, turn.text
    state = turn.json()
    while True:
        action = "skill" if state["character"]["mp"] >= 10 else "attack"
        state = player.post(
            f"/dungeons/{DUNGEON}/combat",
            json={"character_id": player.character_id, "action": action},
        ).json()
        if state["status"] != "ongoing":
            return state


def total_exp(character: dict) -> int:
    return sum(level * 100 for level in range(1, character["level"])) + character["exp"]


def quest_progress(player: Player, quest_id: int) -> dict:
    rows = player.get("/quests/progress", params={"character_id": player.character_id}).json()
    return next(p for p in rows if p["quest_id"] == quest_id)


def test_register_to_quest_completion(player: Player) -> None:
    accepted = player.post(f"/quests/{SLIME_QUEST}/accept", json={"character_id": player.character_id})
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "in_progress"

    combat_exp = 0
    for _ in range(MAX_FIGHTS):
        before = player.character()
        if before["hp"] < before["max_hp"] // 2:
            assert player.post(f"/characters/{player.character_id}/rest").json()["hp"] == before["max_hp"]

        result = fight(player)
        combat_exp += result["rewards"]["exp_gained"]
        # 전투 결과가 이벤트로 character-service에 반영될 때까지 대기
        wait_until(player.character, lambda c: total_exp(c) >= total_exp(before) + result["rewards"]["exp_gained"])

        if quest_progress(player, SLIME_QUEST)["status"] == "completed":
            break
    else:
        raise AssertionError(f"{MAX_FIGHTS}번 싸워도 퀘스트가 완료되지 않았습니다")

    quest = quest_progress(player, SLIME_QUEST)
    assert (quest["progress"], quest["target_count"]) == (3, 3)
    # 퀘스트 보상은 quest.completed 이벤트 → character-service 로 지급된다
    character = wait_until(
        player.character, lambda c: total_exp(c) == combat_exp + quest["reward_exp"]
    )

    # notification-service도 같은 quest.completed를 구독해 알림을 만든다 (다른 서비스 코드 변경 없이 추가된 구독자)
    def notifications() -> list[dict]:
        return player.get("/notifications", params={"character_id": player.character_id}).json()

    rows = wait_until(notifications, lambda ns: any(n["type"] == "quest_completed" for n in ns))
    quest_notice = next(n for n in rows if n["type"] == "quest_completed")
    assert quest["quest_name"] in quest_notice["message"]
    if character["level"] > 1:
        wait_until(notifications, lambda ns: any(n["type"] == "level_up" for n in ns))

    read = player.post(f"/notifications/{quest_notice['id']}/read").json()
    assert read["read_at"] is not None
    unread = player.get(
        "/notifications", params={"character_id": player.character_id, "unread_only": True}
    ).json()
    assert quest_notice["id"] not in {n["id"] for n in unread}


def test_combat_result_updates_character_and_inventory(player: Player) -> None:
    before = player.character()
    result = fight(player)
    rewards = result["rewards"]

    after = wait_until(player.character, lambda c: c["hp"] != before["hp"] or total_exp(c) > total_exp(before))
    if result["status"] == "win":
        assert total_exp(after) == total_exp(before) + rewards["exp_gained"]
    else:
        assert after["hp"] == 1  # 패배 시 HP 1로 부활

    inventory = {i["item_id"]: i["quantity"] for i in player.get(f"/characters/{player.character_id}/inventory").json()}
    for item in rewards["items"]:
        assert inventory.get(item["id"], 0) >= 1


def test_cannot_start_second_combat(player: Player) -> None:
    body = {"character_id": player.character_id}
    assert player.post(f"/dungeons/{DUNGEON}/enter", json=body).status_code == 201
    second = player.post(f"/dungeons/{DUNGEON}/enter", json=body)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "COMBAT_IN_PROGRESS"
