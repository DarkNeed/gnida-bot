"""The Whaler: resource coordination, saved post-action reaction and plague."""

from copy import deepcopy
from arena_engine import Skill, _tick, bleeding_damage
from arena_plague import infect, begin_turn

WHALER_LEVEL = 22
WHALER_SKILLS = {
    s.skill_id: s
    for s in (
        Skill("whaler_harpoon", "Удар гарпуном", "raid", 1, "physical", 30, 95, 0, 0),
        Skill("whaler_staff", "Чёрный посох", "raid", 1, "physical", 10, 95, 0, 0),
        Skill("whaler_miasma", "Миазмы Китобоя", "raid", 1, "magic", 1, 95, 0, 0),
        Skill("whaler_punishment", "Кара болот", "raid", 1, "physical", 20, 95, 0, 0),
        Skill(
            "whaler_punishment_magic",
            "Кара болот · скверна",
            "raid",
            1,
            "magic",
            20,
            95,
            0,
            0,
        ),
        Skill("whaler_rot", "Болотная гниль", "raid", 1, "physical", 30, 95, 0, 0),
        Skill(
            "whaler_rot_magic",
            "Болотная гниль · скверна",
            "raid",
            1,
            "magic",
            30,
            95,
            0,
            0,
        ),
    )
}

LINES = {
    "whaler_harpoon": ("Почувствуй себя китом!", "Хочешь, насажу на гарпун?"),
    "whaler_staff": ("Мне мерзко до тебя прикасаться!", "Подвинься."),
    "whaler_miasma": ("Вдох, выдох — и умри.", "Ты не пил витамины?"),
    "whaler_punishment": ("Никакого жульничества!", "Энергетики — зло!"),
    "whaler_rot": ("Моя последняя надежда…", "Сгиньте!"),
}


def say(data, skill, warning):
    lines = LINES[skill]
    text = lines[(data["round"] // 3) % len(lines)]
    if data["round"] == 1 and skill == "whaler_harpoon":
        text = "Вас мама не учила бояться подозрительных людей?"
    data["dialogue"] = dict(
        speaker="КИТОБОЙ",
        text=text,
        warning=warning,
        persistent=True,
        id=f"whaler:{data['round']}:{skill}",
    )


def set_intent(data):
    from arena_raid_engine import alive_players

    keys = list(alive_players(data))
    if not keys:
        return
    m = data["boss"].setdefault("mechanics", {})
    ritual = data["boss"]["hp"] <= data["boss"]["stats"]["max_hp"] * 0.25 and not m.get(
        "whaler_ritual_used"
    )
    if ritual:
        m["whaler_ritual_used"] = True
        skill, targets = "whaler_rot", keys
        warning = f"Ритуал гнили! Восстановите действиями {30 * len(keys)} энергии за этот раунд или добейте босса. Кара отключена; иначе 30 физ. + 30 маг. по всем."
    else:
        skill = ("whaler_harpoon", "whaler_staff", "whaler_miasma")[
            (data["round"] - 1) % 3
        ]
        targets = (
            [keys[((data["round"] - 1) // 3) % len(keys)]]
            if skill == "whaler_harpoon"
            else keys
        )
        warning = {
            "whaler_harpoon": "Гарпун по отмеченному бойцу: физический удар 30.",
            "whaler_staff": "Размах чёрным посохом: физический удар 10 по всему отряду.",
            "whaler_miasma": "Миазмы по всем: лихорадка −5 HP на 5 ходов и споры до 3. Лечение снимает стак спор; очищение или отдельное восстановление энергии снимает чуму.",
        }[skill]
        warning += " Восстановление действием вызывает Кару по восстановившему больше всех. Пассивные 8% не учитываются."
    data["phase"] = (
        2 if data["boss"]["hp"] <= data["boss"]["stats"]["max_hp"] * 0.25 else 1
    )
    data["intent"] = dict(
        kind="whaler",
        skill=skill,
        targets=targets,
        phase=data["phase"],
        text=warning,
        ritual_target=30 * len(keys) if ritual else 0,
    )
    data["whaler_restored"] = {}
    say(data, skill, warning)


def prepare_reaction(data, rng, stunned):
    from arena_raid_engine import alive_players

    if stunned or data["boss"]["hp"] <= 0 or data["intent"]["skill"] == "whaler_rot":
        return False
    restored = {
        k: v
        for k, v in data.get("whaler_restored", {}).items()
        if k in alive_players(data) and v > 0
    }
    if not restored:
        return False
    maximum = max(restored.values())
    target = rng.choice([k for k, v in restored.items() if v == maximum])
    warning = f"Кара болот: {data['players'][target]['fighter'].get('name', target)} восстановил {maximum} энергии. Дополнительные 20 физ. + 20 маг.; приготовьтесь к отдельной защите!"
    data["whaler_reaction"] = dict(target=target, restored=maximum, stunned=stunned)
    say(data, "whaler_punishment", warning)
    return True


def attack(data, skill, targets, rng, reaction=False):
    from arena_raid_engine import alive_players, native_attack, log_event

    boss = data["boss"]
    original = deepcopy(boss)
    pending_dot = bleeding_damage(boss) + sum(
        max(0, int(e["value"])) for e in boss["effects"] if e["kind"] == "burn"
    )
    parts = [skill] + (
        {
            "whaler_punishment": ["whaler_punishment_magic"],
            "whaler_rot": ["whaler_rot_magic"],
        }.get(skill, [])
    )
    boss_after = None
    for key in targets:
        if key not in alive_players(data) or boss["hp"] <= 0:
            continue
        fighter = data["players"][key]["fighter"]
        for sid in parts:
            if fighter["hp"] <= 0 or boss["hp"] <= 0:
                break
            attacker = deepcopy(original)
            attacker["hp"] = boss["hp"]
            event = native_attack(
                attacker,
                fighter,
                sid,
                WHALER_SKILLS,
                rng,
                tick_actor_bleed=False,
                raid_context=data,
            )
            boss["hp"] = max(0, boss["hp"] - event.get("reaction_damage", 0))
            attacker["hp"] = boss["hp"]
            boss_after = attacker
            if event["hit"] and sid == "whaler_miasma" and fighter["hp"] > 0:
                infect(fighter, viscous=True)
            log_event(
                data,
                "boss",
                key,
                event["text"],
                damage=event["damage"],
                skill=sid,
                damage_type=event["damage_type"],
                hit=event["hit"],
                **(
                    {"hit_results": event["hit_results"], "hits": event["hits"]}
                    if "hit_results" in event
                    else {}
                ),
                dialogue=data.get("dialogue", {}).get("text", ""),
            )
    if not reaction:
        if boss_after is not None:
            hp = boss["hp"]
            boss.clear()
            boss.update(boss_after)
            boss["hp"] = max(0, hp - pending_dot)
        else:
            _tick(boss)


def resolve_action(data, rng):
    from arena_raid_engine import log_event, alive_players

    intent = data["intent"]
    if (
        intent["skill"] == "whaler_rot"
        and sum(data.get("whaler_restored", {}).values()) >= intent["ritual_target"]
    ):
        _tick(data["boss"])
        log_event(
            data,
            "boss",
            "boss",
            "Ритуал гнили сорван восстановлением энергии. Кара не возникает.",
            dialogue="Слишком много… чистого воздуха…",
        )
        return
    attack(data, intent["skill"], intent["targets"], rng)


def resume_reaction(data, skills, rng):
    from arena_raid_engine import _finish_boss_round

    pending = data.pop("whaler_reaction")
    key = pending["target"]
    fighter = data["players"][key]["fighter"]
    original_guard = fighter.pop("_qte_guard", None)
    result = pending.get("result")
    if result:
        fighter["_qte_guard"] = dict(
            skill="whaler_punishment",
            dodge=result["dodge"],
            subskills=["whaler_punishment", "whaler_punishment_magic"],
        )
        if "pattern_dodge" in result:
            fighter["_qte_guard"]["pattern_dodge"] = result["pattern_dodge"]
    intent = data["intent"]
    data["intent"] = dict(skill="whaler_punishment")
    data["_qte_boss_phase"] = True
    attack(data, "whaler_punishment", [key], rng, reaction=True)
    fighter.pop("_qte_guard", None)
    if original_guard:
        fighter["_qte_guard"] = original_guard
    data["intent"] = intent
    return _finish_boss_round(data, skills, rng, pending["stunned"])
