"""Doofenshmirtz and Perry: telegraphed actions without a second target."""

from copy import deepcopy

from arena_engine import Skill, _tick, bleeding_damage

DOOF_SKILLS = {
    s.skill_id: s
    for s in (
        Skill("doof_shot", "Трепещи, Перри!", "raid", 1, "magic", 12, 95, 0, 0),
        Skill("doof_hangover", "Похмелье-инатор", "raid", 1, "magic", 7, 95, 0, 0),
        Skill("doof_deport", "Депортатор-инатор", "raid", 1, "magic", 14, 95, 0, 0),
        Skill("doof_blast", "Разъёб-инатор", "raid", 1, "magic", 18, 95, 0, 0),
    )
}


def add_effect(fighter, ident, kind, value, duration, **extra):
    fighter["effects"] = [e for e in fighter["effects"] if e.get("id") != ident]
    fighter["effects"].append(
        dict(id=ident, kind=kind, value=value, duration=duration, **extra)
    )


def set_doof_intent(data):
    from arena_raid_engine import alive_players

    living = alive_players(data)
    keys = list(living)
    boss = data["boss"]
    pattern = (data["round"] - 1) % 5
    target = keys[((data["round"] - 1) // 5) % len(keys)]
    phase = data["phase"]
    if phase == 2:
        for dtype in ("physical", "magic"):
            add_effect(boss, "doof_phase_" + dtype, dtype + "_defense_pct", -0.15, 2)
    for p in living.values():
        if p.get("deported_round") == data["round"]:
            p["selected"] = "defend"
    # Applies before the party acts. One hit consumes cover; it cannot stack.
    if data["round"] % 2:
        add_effect(
            boss,
            "perry_cover",
            "damage_taken_pct",
            -0.25,
            1,
            consume_on_hit=True,
            name="Прикрытие Перри",
            description="Следующий входящий удар ослаблен на 25%.",
        )
        add_effect(
            living[target]["fighter"],
            "doof_subject",
            "damage_taken_pct",
            0.20,
            3,
            consume_on_hit=True,
            name="Подопытный",
            description="Следующий удар инатора сильнее на 20%.",
        )
    skill = ("doof_shot", "doof_hangover", "doof_deport", "monologue", "doof_blast")[
        pattern
    ]
    lines = (
        "Трепещите! Перри, отметь подопытного!",
        "Этот инатор создаёт утро понедельника. Даже в пятницу!",
        "Перри, проверь адрес! Сейчас кто-то отправится в командировку!",
        "На мой день рождения никто не пришёл. Даже уведомление из налоговой.",
        "Перри, прикрой меня! Разъёб-инатор почти заряжен!",
    )
    warnings = (
        "Готовит магический выстрел по одному бойцу.",
        "Залп по отряду: точность −15 на один ход.",
        "Депортация одного бойца на раунд. В одиночку вместо пропуска снижается точность.",
        "Монолог: урон отряда −20%, обе защиты босса −25% на следующий раунд.",
        "Залп по отряду. Нанесите 10% максимального HP босса за раунд, чтобы сорвать его!",
    )
    data["intent"] = dict(
        kind="doof",
        phase=phase,
        skill=skill,
        targets=keys if pattern in (1, 4) else [target],
        text=warnings[pattern],
    )
    data["dialogue"] = dict(
        speaker="ФУФЕЛШМЕРЦ",
        text=lines[pattern],
        warning=warnings[pattern],
        persistent=True,
        id=f"intent:{data['round']}",
    )


def resolve_doof_action(data, rng):
    from arena_raid_engine import alive_players, native_attack, log_event

    boss, intent = data["boss"], data["intent"]
    memory = boss.setdefault("mechanics", {})
    if not memory.get("self_destruct") and boss["hp"] <= boss["stats"]["max_hp"] / 2:
        memory["self_destruct"] = True
        damage = min(boss["hp"], max(1, round(boss["stats"]["max_hp"] * 0.05)))
        boss["hp"] -= damage
        for p in data["players"].values():
            p["fighter"]["effects"] = [
                e for e in p["fighter"]["effects"] if e.get("id") != "doof_subject"
            ]
        log_event(
            data,
            "boss",
            "boss",
            f"Кнопка самоуничтожения: −{damage} HP, метки сняты.",
            damage=damage,
            dialogue="Перри! Кто подключил самоуничтожение к дверному звонку?!",
        )
        if boss["hp"] <= 0:
            return
    if intent["skill"] == "monologue":
        _tick(boss)
        for dtype in ("physical", "magic"):
            add_effect(boss, "doof_story_" + dtype, dtype + "_defense_pct", -0.25, 1)
        for p in alive_players(data).values():
            add_effect(p["fighter"], "doof_story", "damage_pct", -0.20, 1)
        log_event(
            data,
            "boss",
            "boss",
            "Монолог: защиты босса −25%, урон отряда −20%.",
            dialogue="А всё началось в моём детстве…",
        )
        return
    if (
        intent["skill"] == "doof_blast"
        and data["round_before"]["boss"]["hp"] - boss["hp"]
        >= boss["stats"]["max_hp"] * 0.1
    ):
        _tick(boss)
        damage = min(boss["hp"], max(1, round(boss["stats"]["max_hp"] * 0.03)))
        boss["hp"] -= damage
        for dtype in ("physical", "magic"):
            add_effect(
                boss, "doof_interrupted_" + dtype, dtype + "_defense_pct", -0.20, 1
            )
        log_event(
            data,
            "boss",
            "boss",
            f"Заряд инатора сорван! −{damage} HP, защиты −20%.",
            damage=damage,
            dialogue="Перри! Инатор снова не прошёл гарантийный ремонт!",
        )
        return
    living = alive_players(data)
    targets = [k for k in intent["targets"] if k in living] or list(living)[:1]
    original = deepcopy(boss)
    pending_bleed = bleeding_damage(original) + sum(max(0,int(e['value'])) for e in original['effects'] if e['kind']=='burn')
    boss_after = None
    for key in targets:
        if boss['hp']<=0:
            break
        attacker = deepcopy(original)
        attacker['hp']=boss['hp']
        if intent["phase"] == 2:
            add_effect(attacker, "doof_fury", "damage_pct", 0.15, 1)
        charge = memory.get("two_coins", 0)
        if charge:
            add_effect(attacker, "doof_coins", "damage_pct", 0.10 * charge, 1)
        event = native_attack(
            attacker,
            living[key]["fighter"],
            intent["skill"],
            DOOF_SKILLS,
            rng,
            tick_actor_bleed=False,
        )
        if boss_after is None:
            boss_after = attacker
        boss['hp']=max(0,boss['hp']-event.get('reaction_damage',0))
        boss_after['hp']=boss['hp']
        fighter = living[key]["fighter"]
        if event["damage"] and intent["skill"] == "doof_hangover":
            add_effect(fighter, "doof_hangover", "accuracy_flat", -15, 1)
        if event["damage"] and intent["skill"] == "doof_deport" and fighter["hp"] > 0:
            if len(alive_players(data)) > 1:
                living[key]["deported_round"] = data["round"] + 1
                add_effect(
                    fighter,
                    "doof_deported",
                    "raid_deported",
                    1,
                    2,
                    name="Депортирован",
                    description="Пропускает следующий раунд.",
                )
            else:
                add_effect(fighter, "doof_deport_accuracy", "accuracy_flat", -20, 1)
        log_event(
            data,
            "boss",
            key,
            event["text"],
            damage=event["damage"],
            skill=intent["skill"],
            damage_type=event["damage_type"],
            hit=event["hit"],
            critical=event["critical"],
            dialogue=data["dialogue"]["text"],
        )
    if boss_after is not None:
        boss.clear()
        boss.update(boss_after)
        boss["mechanics"]["two_coins"] = 0
        if pending_bleed:
            dot = min(boss["hp"], pending_bleed)
            boss["hp"] -= dot
            log_event(data, "boss", "boss", f"Кровотечение / горение: −{dot} HP.", damage=dot)
    else:
        _tick(boss)
