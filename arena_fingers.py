"""Original Five Fingers-inspired classes and their bounded combat mechanics."""

FINGER_IDS = {"thumb", "index", "middle", "ring", "pinky"}


def build_catalog(FighterClass, Skill, effect):
    keys = (
        "max_hp",
        "physical_attack",
        "magic_attack",
        "physical_defense",
        "magic_defense",
        "speed",
        "evasion",
    )

    def passive(kind, name, description):
        return dict(
            effect(kind, kind, 1, target="self"), name=name, description=description
        )

    specs = (
        (
            "thumb",
            "Солдато Большого пальца",
            "Боезапас",
            (52, 13, 5, 12, 9, 7, 4),
            (5, 1.5, 0.4, 1.1, 0.8, 0.5, 0.2),
            (
                passive(
                    "subordination",
                    "Субординация",
                    "Разные навыки подряд дают до 3 зарядов: +8% урона за заряд следующему выстрелу. Повтор сбрасывает цепочку.",
                ),
                passive(
                    "uniform",
                    "Безупречная форма",
                    "Пока HP выше половины, обе защиты повышены на 15%.",
                ),
            ),
        ),
        (
            "index",
            "Прозелит Указательного пальца",
            "Воля",
            (44, 12, 9, 8, 11, 13, 10),
            (4.5, 1.4, 0.7, 0.8, 1, 1, 0.3),
            (
                passive(
                    "prescript",
                    "Воля предписания",
                    "Исполнение отмеченного навыка возвращает 10 Воли.",
                ),
                passive(
                    "obedience",
                    "Без вопросов",
                    "Исполнение предписания дополнительно сокращает восстановление другого навыка на ход.",
                ),
            ),
        ),
        (
            "middle",
            "Младший брат Среднего пальца",
            "Ярость",
            (58, 14, 4, 12, 8, 8, 4),
            (5.5, 1.6, 0.3, 1.2, 0.7, 0.6, 0.2),
            (
                passive(
                    "revenge",
                    "Книга мести",
                    "Полученный прямой урон добавляет обиду (до 3). Ответные атаки расходуют её для усиления.",
                ),
                passive(
                    "tattoos",
                    "Семейные татуировки",
                    "При HP не выше 40% обе защиты повышаются на 25%.",
                ),
            ),
        ),
        (
            "ring",
            "Студент Кольца",
            "Вдохновение",
            (42, 7, 14, 7, 10, 12, 11),
            (4, 0.6, 1.7, 0.7, 1, 1, 0.3),
            (
                passive(
                    "muse",
                    "Муза",
                    "Новый тип отрицательного эффекта на враге возвращает 8 Вдохновения, не чаще раза за действие.",
                ),
                passive(
                    "exhibit",
                    "Выставочный образец",
                    "Если на враге хотя бы два разных отрицательных эффекта, урон повышен на 10%.",
                ),
            ),
        ),
        (
            "pinky",
            "Звёздный клинок",
            "Сосредоточенность",
            (45, 13, 6, 8, 9, 15, 12),
            (4.5, 1.5, 0.5, 0.8, 0.8, 1.2, 0.4),
            (
                passive(
                    "constellation",
                    "Созвездие",
                    "Дыхание даёт 2 заряда, попадание обычной родной атакой — 1 (до 3). Каждый заряд даёт +12% шанса крита. Криты не расходуют заряды; усиленная атака расходует 2 только при попадании.",
                ),
                passive(
                    "blade_loyalty",
                    "Верность клинку",
                    "Другая атака после предыдущей получает +10 точности; повтор не получает бонуса.",
                ),
            ),
        ),
    )
    classes = {
        cid: FighterClass(
            cid,
            name,
            resource,
            5,
            dict(zip(keys, stats)),
            dict(zip(keys, growth)),
            passives,
            "rare",
        )
        for cid, name, resource, stats, growth, passives in specs
    }

    def s(
        cid,
        key,
        name,
        level,
        dtype,
        power,
        accuracy,
        cost,
        cooldown,
        effects=(),
        description="",
    ):
        return Skill(
            key,
            name,
            cid,
            level,
            dtype,
            power,
            accuracy,
            cost,
            cooldown,
            effects,
            "rare",
            description,
        )

    skills = (
        s("thumb", "bayonet", "Штыковой этикет", 5, "physical", 8, 95, 0, 0),
        s(
            "thumb",
            "reload",
            "Перезарядка",
            5,
            None,
            0,
            100,
            0,
            3,
            (
                effect("reload", "resource", 40, target="self"),
                effect("aim", "accuracy_flat", 10, 1, target="self"),
            ),
        ),
        s(
            "thumb",
            "warning_shot",
            "Предупредительный выстрел",
            6,
            "physical",
            11,
            95,
            20,
            1,
            (effect("warning", "physical_attack_pct", -0.15, 2),),
        ),
        s(
            "thumb",
            "senior_verdict",
            "Приговор старшего",
            9,
            "physical",
            18,
            88,
            40,
            3,
            description="Игнорирует 30% физической защиты; расходует заряды Субординации.",
        ),
        s("index", "first_line", "Первая строка", 5, "physical", 8, 93, 0, 0),
        s(
            "index",
            "receive_prescript",
            "Получить предписание",
            5,
            None,
            0,
            100,
            0,
            3,
            (effect("will", "resource", 35, target="self"),),
            "Отмечает случайную экипированную атаку. Предписание действует на следующее действие.",
        ),
        s(
            "index",
            "literal",
            "Исполнить буквально",
            6,
            "physical",
            11,
            90,
            20,
            1,
            (effect("literal", "evasion_flat", -12, 2),),
        ),
        s(
            "index",
            "last_line",
            "Последняя строка",
            9,
            "physical",
            17,
            87,
            40,
            3,
            description="При исполнении предписания игнорирует 35% защиты.",
        ),
        s("middle", "recorded", "Записано", 5, "physical", 8, 92, 0, 0),
        s(
            "middle",
            "grit_teeth",
            "Стиснуть зубы",
            5,
            None,
            0,
            100,
            0,
            3,
            (
                effect("rage", "resource", 35, target="self"),
                effect("grit", "physical_defense_pct", 0.25, 1, target="self"),
            ),
        ),
        s(
            "middle",
            "answer_for_it",
            "Ты за это ответишь",
            6,
            "physical",
            11,
            90,
            20,
            1,
            description="Расходует обиды: +15% урона за каждую.",
        ),
        s(
            "middle",
            "whole_family",
            "За всю семью",
            9,
            "physical",
            17,
            86,
            40,
            3,
            description="Серия ударов: +20% суммарного урона за обиду, затем обиды расходуются.",
        ),
        s(
            "ring",
            "first_stroke",
            "Первый мазок",
            5,
            "magic",
            7,
            92,
            0,
            0,
            (effect("bleed", "bleed", 2, 2, chance=0.35),),
        ),
        s(
            "ring",
            "red_etude",
            "Красный этюд",
            6,
            "magic",
            10,
            90,
            20,
            1,
            (effect("bleed", "bleed", 3, 3),),
        ),
        s(
            "ring",
            "unfinished_portrait",
            "Незавершённый портрет",
            5,
            None,
            0,
            88,
            15,
            2,
            (
                effect("portrait_accuracy", "accuracy_flat", -15, 2),
                effect("portrait_defense", "magic_defense_pct", -0.20, 2),
            ),
        ),
        s(
            "ring",
            "last_stroke",
            "Последний штрих",
            9,
            "magic",
            15,
            88,
            35,
            3,
            description="+10% урона за тип отрицательного эффекта (до 3); сокращает их длительность на ход.",
        ),
        s("pinky", "silent_cut", "Тихий разрез", 5, "physical", 8, 95, 0, 0),
        s(
            "pinky",
            "calm_breath",
            "Спокойное дыхание",
            5,
            None,
            0,
            100,
            0,
            3,
            (effect("focus", "resource", 35, target="self"),),
            "Добавляет 2 заряда Созвездия, если эта пассивка экипирована.",
        ),
        s(
            "pinky",
            "moon_arc",
            "Лунная дуга",
            6,
            "physical",
            11,
            90,
            20,
            1,
            description="Игнорирует 20% физической защиты.",
        ),
        s(
            "pinky",
            "falling_star",
            "Падающая звезда",
            9,
            "physical",
            16,
            87,
            40,
            3,
            description="25% базового шанса критического удара. Крит наносит ×1,5 урона.",
        ),
    )
    return classes, {skill.skill_id: skill for skill in skills}


def has_trait(side, kind):
    return any(
        e.get("kind") == kind
        for p in side.get("passive_details", [])
        for e in p.get("effects", [])
    )


def negative_effect(effect):
    return (
        effect["kind"] in {"bleed", "stun"} or effect.get("value", 0) < 0
    ) and effect.get("duration", 0) < 10000


def negative_kinds(side):
    return {e["kind"] for e in side["effects"] if negative_effect(e)}


def combat_modifiers(actor, target, skill, rng):
    memory = actor.setdefault("mechanics", {})
    obeyed = memory.get("prescript") == skill.skill_id
    accuracy, boost, pierce = 0, 0, 0
    if (
        has_trait(actor, "blade_loyalty")
        and skill.damage_type
        and memory.get("last_attack") not in {None, skill.skill_id}
    ):
        accuracy += 10
    if (
        skill.skill_id in {"warning_shot", "senior_verdict"}
        and has_trait(actor, "subordination")
        and "no_order_bonus" not in skill.tags
    ):
        boost += 0.08 * memory.get("order", 0)
    if skill.skill_id in {"answer_for_it", "whole_family"} and has_trait(
        actor, "revenge"
    ):
        boost += (0.20 if skill.skill_id == "whole_family" else 0.15) * memory.get(
            "grudge", 0
        )
    if skill.skill_id == "last_stroke":
        boost += 0.10 * min(3, len(negative_kinds(target)))
    if has_trait(actor, "exhibit") and len(negative_kinds(target)) >= 2:
        boost += 0.10
    pierce = {"senior_verdict": 0.30, "moon_arc": 0.20}.get(skill.skill_id, 0)
    if skill.skill_id == "last_line" and obeyed:
        pierce = 0.35
    chance = 0.25 if skill.skill_id == "falling_star" else 0
    if has_trait(actor, "constellation"):
        chance += 0.12 * memory.get("focus", 0)
    critical = bool(skill.damage_type and chance and rng.random() < min(0.75, chance))
    return accuracy, boost, pierce, critical, obeyed


def after_action(
    actor, target, skill, hit, damage, critical, obeyed, previous_negatives, skills, rng
):
    m = actor.setdefault("mechanics", {})
    if damage and has_trait(target, "revenge"):
        t = target.setdefault("mechanics", {})
        t["grudge"] = min(3, t.get("grudge", 0) + 1)
    if skill.skill_id in {"answer_for_it", "whole_family"}:
        m["grudge"] = 0
    if skill.skill_id in {"warning_shot", "senior_verdict"}:
        m["order"] = 0
    elif has_trait(actor, "subordination"):
        m["order"] = (
            0
            if m.get("last_skill") == skill.skill_id
            else min(3, m.get("order", 0) + 1)
        )
    m["last_skill"] = skill.skill_id
    if skill.damage_type:
        m["last_attack"] = skill.skill_id
    if "consume_focus" in skill.tags:
        if hit:
            m["focus"] = max(0, m.get("focus", 0) - 2)
    elif has_trait(actor, "constellation"):
        if skill.skill_id == "calm_breath":
            m["focus"] = min(3, m.get("focus", 0) + 2)
        elif damage and skill.class_id == actor["class_id"] == "pinky":
            m["focus"] = min(3, m.get("focus", 0) + 1)
    if hit and skill.skill_id == "last_stroke":
        target["effects"] = [
            dict(e, duration=e["duration"] - 1) if negative_effect(e) else e
            for e in target["effects"]
            if not negative_effect(e)
            or ("consume_negatives" not in skill.tags and e["duration"] > 1)
        ]
    refund = 0
    if hit and has_trait(actor, "muse") and negative_kinds(target) - previous_negatives:
        refund += 8
    if obeyed:
        if has_trait(actor, "prescript"):
            refund += 10
        if has_trait(actor, "obedience"):
            actor["cooldowns"] = {
                k: v if k == skill.skill_id else v - 1
                for k, v in actor["cooldowns"].items()
                if k == skill.skill_id or v > 1
            }
    actor["resource"] = min(actor["stats"]["resource_max"], actor["resource"] + refund)
    m.pop("prescript", None)
    if skill.skill_id == "receive_prescript":
        choices = [
            k
            for k in actor["loadout"]
            if k in skills
            and skills[k].damage_type
            and not actor["cooldowns"].get(k, 0)
        ]
        if choices:
            m["prescript"] = rng.choice(choices)
