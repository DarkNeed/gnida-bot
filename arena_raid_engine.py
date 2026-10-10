"""Three-player PvE rounds. Native skills use the same server combat resolver."""

from copy import deepcopy
import random

from arena_engine import (
    Skill,
    create_battle_state,
    effective_stat,
    effective_skill,
    resolve_skill,
    _tick,
)

RAID_SIZE = 3
RAID_ROUND_SECONDS = 120
RAID_MAX_ROUNDS = 40
BOSS_NAME = "Железный сборщик"
BOSSES = {
    "iron": dict(name=BOSS_NAME, skills=("raid_sweep", "raid_crush", "raid_rampage")),
    "lei_heng": dict(
        name="Лей Хенг — Охотник на тигров",
        sprite="/static/assets/lei_heng.png",
        skills=("lei_double_slash", "lei_explosive_slash", "lei_perfected_flurry"),
        recommended_level=18,
        minimum_level=20,
    ),
}
BOSS_SKILLS = {
    s.skill_id: s
    for s in (
        Skill("raid_sweep", "Размах цепью", "middle", 1, "physical", 8, 95, 0, 0),
        Skill("raid_crush", "Дробящий удар", "middle", 1, "physical", 17, 95, 0, 0),
        Skill("raid_rampage", "Яростный размах", "middle", 1, "physical", 10, 95, 0, 0),
        Skill(
            "lei_double_slash", "Двойной разрез", "middle", 1, "physical", 17, 95, 0, 0
        ),
        Skill(
            "lei_explosive_slash",
            "Взрывной разрез",
            "middle",
            1,
            "physical",
            8,
            95,
            0,
            0,
        ),
        Skill(
            "lei_perfected_flurry",
            "Совершенная поступь тигробоя",
            "middle",
            1,
            "physical",
            32,
            95,
            0,
            0,
            tags=("triple_strike",),
        ),
    )
}


def alive_players(data):
    return {
        k: p
        for k, p in data["players"].items()
        if not p.get("withdrawn") and p["fighter"]["hp"] > 0
    }


def pair_state(actor, target):
    return dict(
        sides={"a": actor, "b": target},
        active_side="a",
        turn=1,
        log=[],
        finished=False,
        winner=None,
    )


def native_attack(actor, target, skill_id, skills, rng):
    return resolve_skill(
        pair_state(actor, target),
        "a",
        skill_id,
        skills,
        rng,
        advance_turn=False,
        tick_target_bleed=False,
    )


def set_intent(data):
    living = alive_players(data)
    if not living:
        return
    boss = data["boss"]
    phase = 2 if boss["hp"] <= boss["stats"]["max_hp"] // 2 else 1
    data["phase"] = phase
    pattern = (data["round"] - 1) % 3
    for player in data["players"].values():
        fighter = player["fighter"]
        fighter["effects"] = [
            e for e in fighter["effects"] if e.get("id") != "lei_prey"
        ]
    if data.get("boss_id", "iron") == "lei_heng":
        keys = list(living)
        target = keys[((data["round"] - 1) // 3) % len(keys)]
        if pattern == 2:
            living[target]["fighter"]["effects"].append(
                dict(
                    id="lei_prey",
                    kind="raid_prey",
                    value=1,
                    duration=1,
                    name="Добыча",
                    description="Цель поступи тигробоя. Защита снижает урон этой атаки на 60%.",
                )
            )
        data["intent"] = dict(
            kind="attack",
            phase=phase,
            skill=("lei_explosive_slash", "lei_double_slash", "lei_perfected_flurry")[
                pattern
            ],
            targets=keys if pattern == 0 else [target],
            text=(
                "Готовит взрывной разрез по всему отряду.",
                "Готовит двойной разрез по отмеченному бойцу.",
                "Добыча отмечена: готовит поступь тигробоя. Защищайтесь: −60% урона атаки!",
            )[pattern],
        )
        return
    if pattern == 0:
        intent = dict(
            kind="attack",
            skill="raid_rampage" if phase == 2 else "raid_sweep",
            targets=list(living),
            text="Готовит удар цепью по всему отряду.",
        )
    elif pattern == 1:
        keys = list(living)
        target = keys[(data["round"] // 3) % len(keys)]
        intent = dict(
            kind="attack",
            skill="raid_crush",
            targets=[target],
            text="Готовит дробящий удар по отмеченному бойцу.",
        )
    else:
        intent = dict(
            kind="shield",
            targets=[],
            text="Поднимет щит: обе защиты +30% на два раунда.",
        )
    # Phase is announced before choices; crossing 50% during this round cannot
    # silently strengthen the already announced attack.
    intent["phase"] = phase
    data["intent"] = intent


def create_raid_state(participants, sources, classes, skills, boss_id="iron"):
    if boss_id not in BOSSES:
        raise ValueError("Неизвестный босс.")
    level = max(
        BOSSES[boss_id].get("minimum_level", 1),
        min(20, round(sum(s["level"] for s in sources) / len(sources))),
    )
    enemy = dict(
        slave_id=0, owner_id=0, class_id="middle", level=level, passive_details=[]
    )
    players = {}
    for p, source in zip(participants, sources):
        state = create_battle_state(source, enemy, classes=classes, skills=skills)
        players[str(p["actor_id"])] = dict(
            actor_id=p["actor_id"],
            fighter_id=p["fighter_id"],
            personal=bool(p["personal"]),
            slave_owner=p["slave_owner"],
            fighter=state["sides"]["a"],
            selected=None,
            manual_turns=0,
            missed=0,
            reward_blocked=False,
            withdrawn=False,
        )
    boss = state["sides"]["b"]
    boss["stats"]["max_hp"] = max(
        1, round(sum(p["fighter"]["stats"]["max_hp"] for p in players.values()) * 1.4)
    )
    boss["hp"] = boss["stats"]["max_hp"]
    boss["stats"]["evasion"] = 0
    for stat in ("physical_defense", "magic_defense"):
        boss["stats"][stat] *= 0.7
    boss["stats"]["physical_attack"] *= 0.85
    boss["loadout"] = list(BOSSES[boss_id]["skills"])
    boss["name"] = BOSSES[boss_id]["name"]
    boss["mechanics"] = {}
    data = dict(
        players=players,
        boss_id=boss_id,
        boss=boss,
        round=1,
        phase=1,
        log=[],
        result="",
        finished=False,
        won=False,
        rewards={},
        control_resistance=0,
        control_lock=0,
    )
    set_intent(data)
    return data


def raid_snapshot(data):
    """Small detached visual state; never expose hidden action selections."""
    fighters = {"boss": data["boss"]} | {
        k: p["fighter"] for k, p in data["players"].items()
    }
    return {
        k: deepcopy(
            {
                field: f.get(field, {})
                for field in ("hp", "resource", "effects", "mechanics", "cooldowns")
            }
        )
        for k, f in fighters.items()
    }


def log_event(data, actor, target, text, **extra):
    data["event_seq"] = data.get("event_seq", 0) + 1
    first = not data["log"] or data["log"][-1]["round"] != data["round"]
    data["log"].append(
        dict(
            round=data["round"],
            actor=actor,
            target=target,
            text=text,
            seq=data["event_seq"],
            after=raid_snapshot(data),
            **({"before": data["round_before"]} if first else {}),
            **extra,
        )
    )


def defend(fighter):
    _tick(fighter)
    fighter["effects"] = [
        e for e in fighter["effects"] if not e.get("id", "").startswith("raid_guard_")
    ]
    for dtype in ("physical", "magic"):
        fighter["effects"].append(
            dict(
                id="raid_guard_" + dtype,
                kind=dtype + "_defense_pct",
                value=0.35,
                duration=1,
                target="self",
            )
        )


def finish_if_needed(data):
    living = alive_players(data)
    if data["boss"]["hp"] <= 0 or not living:
        data["finished"] = True
        data["won"] = data["boss"]["hp"] <= 0 and bool(living)
        data["result"] = (
            "Босс повержен!" if data["won"] else "Отряд потерпел поражение."
        )
        if data["boss"]["hp"] <= 0 and not living:
            data["result"] = "Босс и отряд погибли. Ничья, без наград."
        return True
    return False


def resolve_round(data, skills, rng=None):
    if data["finished"]:
        raise ValueError("Рейд завершён.")
    rng = rng or random.SystemRandom()
    data["round_before"] = raid_snapshot(data)
    boss = data["boss"]
    stunned = False
    living = alive_players(data)
    order = sorted(
        living, key=lambda k: (-effective_stat(living[k]["fighter"], "speed"), int(k))
    )
    for key in order:
        if finish_if_needed(data):
            break
        player = living[key]
        actor = player["fighter"]
        selected = player["selected"]
        dot = min(
            actor["hp"],
            sum(
                max(0, int(e["value"]))
                for e in actor["effects"]
                if e["kind"] == "bleed"
            ),
        )
        if dot:
            actor["hp"] -= dot
            log_event(data, key, key, f"Кровотечение: −{dot} HP.", damage=dot)
        if actor["hp"] <= 0:
            continue
        if selected is None:
            player["missed"] += 1
            player["reward_blocked"] |= player["missed"] >= 3
        else:
            player["manual_turns"] += 1
            player["missed"] = 0
        if any(e["kind"] == "stun" for e in actor["effects"]):
            _tick(actor)
            log_event(data, key, key, "Ошеломление: действие пропущено.")
            continue
        if selected is None or selected == "defend":
            defend(actor)
            log_event(
                data,
                key,
                key,
                "Защита: обе защиты +35%."
                + (" Время выбора истекло." if selected is None else ""),
            )
            continue
        # Resource/cooldowns were validated at submission. Enemy disruption can
        # change the applicable variant before this fighter acts: do not charge
        # or execute an unaffordable ability, and never abort the whole round.
        try:
            event = native_attack(actor, boss, selected, skills, rng)
        except ValueError:
            defend(actor)
            log_event(data, key, key, "Навык недоступен после изменений в бою: защита.")
            continue
        log_event(
            data,
            key,
            "boss",
            event["text"],
            damage=event["damage"],
            self_damage=event["self_damage"],
            skill=selected,
            damage_type=event["damage_type"],
            **({"hits": event["hits"]} if "hits" in event else {}),
        )
        control = any(e["kind"] == "stun" for e in boss["effects"])
        boss["effects"] = [e for e in boss["effects"] if e["kind"] != "stun"]
        if control:
            chance = max(0.1, 1 - 0.25 * data["control_resistance"])
            accepted = (
                not data["control_lock"] and not stunned and rng.random() < chance
            )
            data["control_resistance"] = min(4, data["control_resistance"] + 1)
            if accepted:
                stunned = True
            else:
                log_event(data, "boss", "boss", "Босс сопротивляется ошеломлению.")
    if not finish_if_needed(data):
        dot = min(
            boss["hp"],
            sum(
                max(0, int(e["value"])) for e in boss["effects"] if e["kind"] == "bleed"
            ),
        )
        if dot:
            boss["hp"] -= dot
            log_event(data, "boss", "boss", f"Кровотечение: −{dot} HP.", damage=dot)
    if not finish_if_needed(data):
        if stunned:
            _tick(boss)
            data["control_lock"] = 2
            log_event(data, "boss", "boss", "Босс ошеломлён: намерение сорвано.")
        else:
            intent = data["intent"]
            if intent["kind"] == "shield":
                _tick(boss)
                boss["effects"] = [
                    e
                    for e in boss["effects"]
                    if not e.get("id", "").startswith("raid_shield_")
                ]
                for dtype in ("physical", "magic"):
                    boss["effects"].append(
                        dict(
                            id="raid_shield_" + dtype,
                            kind=dtype + "_defense_pct",
                            value=0.3,
                            duration=2,
                            target="self",
                        )
                    )
                log_event(
                    data,
                    "boss",
                    "boss",
                    "Босс поднял щит: обе защиты +30% на два раунда.",
                )
            else:
                targets = [k for k in intent["targets"] if k in alive_players(data)]
                if not targets:
                    targets = list(alive_players(data))[:1]
                # An area attack is one boss action, not three ticks of its buffs.
                original = deepcopy(boss)
                boss_after = None
                for key in targets:
                    attacker = deepcopy(original)
                    if intent["skill"] == "lei_perfected_flurry" and any(
                        e.get("id") == "raid_guard_physical"
                        for e in data["players"][key]["fighter"]["effects"]
                    ):
                        attacker["effects"].append(
                            dict(
                                id="lei_guard_reduction",
                                kind="final_damage_multiplier",
                                value=0.4,
                                duration=1,
                            )
                        )
                    if intent["phase"] == 2:
                        attacker["effects"].append(
                            dict(
                                id="raid_fury",
                                kind="damage_pct",
                                value=0.25,
                                duration=1,
                            )
                        )
                    event = native_attack(
                        attacker,
                        data["players"][key]["fighter"],
                        intent["skill"],
                        BOSS_SKILLS,
                        rng,
                    )
                    if boss_after is None:
                        boss_after = attacker
                    log_event(
                        data,
                        "boss",
                        key,
                        event["text"],
                        damage=event["damage"],
                        skill=intent["skill"],
                        damage_type=event["damage_type"],
                        **({"hits": event["hits"]} if "hits" in event else {}),
                    )
                if boss_after is not None:
                    boss.clear()
                    boss.update(boss_after)
                else:
                    _tick(boss)
                if intent["skill"] == "lei_perfected_flurry" and targets:
                    boss["effects"].append(
                        dict(
                            id="lei_overheat",
                            kind="damage_taken_pct",
                            value=0.25,
                            duration=1,
                            name="Перегрев",
                            description="Получает на 25% больше урона до следующего действия босса.",
                        )
                    )
                    log_event(
                        data,
                        "boss",
                        "boss",
                        "Перегрев: босс получает на 25% больше урона в следующем раунде.",
                    )
            data["control_lock"] = max(0, data["control_lock"] - 1)
    if not finish_if_needed(data) and data["round"] >= RAID_MAX_ROUNDS:
        data.update(
            finished=True,
            won=False,
            result="Босс ушёл: достигнут предел 40 раундов. Без наград.",
        )
    data["log"] = data["log"][-80:]
    data.pop("round_before", None)
    if not data["finished"]:
        data["round"] += 1
        for player in data["players"].values():
            player["selected"] = None
        set_intent(data)
    return data
