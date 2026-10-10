"""Branch-bound milestones at 12/15/18; no additional combat or memory slots."""

from arena_archclasses import ARCHCLASSES, e, final_stage

UPGRADES_12 = {
    "femboy": "«Попался, натурал»: сила +1 и точность +5.",
    "princess": "«Мне нельзя делать больно»: обе защиты +25% вместо +20%.",
    "gachi_actor": "«Welcome to the club»: физическая атака цели −20% вместо −15%.",
    "mge_bro": "«Дуэль на миду»: точность +5; уязвимость сохраняется.",
    "programmer": "Под «Горячим фиксом» следующая родная магическая атака дешевле на 6 вместо 5 энергии.",
    "hacker": "«Доступ получен»: похищение до 12 вместо 10 энергии.",
    "thumb_discipline": "«Соблюдай субординацию»: физическая атака цели −30% вместо −25%.",
    "thumb_execution": "«Приговор без обжалования»: сила 22 вместо 21.",
    "index_proxy": "«Предписание исполнено»: дополнительный возврат 7 вместо 5 Воли.",
    "index_messenger": "За нарушение чужого предписания отнимается до 10 вместо 8 энергии.",
    "middle_guardian": "«За спиной семьи»: физическая защита +40%, магическая +30%.",
    "middle_revenge": "«Долг крови»: точность +5; риск снижения защит сохраняется.",
    "ring_pointillist": "«Точка за точкой»: кровотечение 5 вместо 4.",
    "ring_fauvist": "«Завершённый шедевр»: точность +5.",
    "pinky_dihui": "«Затмение»: пробитие 50% вместо 45%.",
    "pinky_tiansha": "«Рассечь небеса»: сила 20 вместо 19.",
}


def skill_branch(skill):
    return next(
        (t.split(":", 1)[1] for t in skill.tags if t.startswith("archclass:")), ""
    )


def branch_skill_allowed(skill, branch_id, level):
    required = skill_branch(skill)
    return not required or (required == branch_id and level >= skill.unlock_level)


def build_arch_skills(Skill):
    def s(
        branch_id,
        name,
        dtype,
        power,
        accuracy,
        cost,
        cooldown,
        effects=(),
        tags=(),
        pierce=None,
    ):
        return Skill(
            skill_id="arch_" + branch_id,
            name=name,
            class_id=ARCHCLASSES[branch_id]["class_id"],
            unlock_level=15,
            damage_type=dtype,
            power=power,
            accuracy=accuracy,
            cost=cost,
            cooldown=cooldown,
            effects=effects,
            tags=("archclass:" + branch_id,) + tags,
            rarity="rare",
            pierce=pierce,
            description="Уникальный навык «" + ARCHCLASSES[branch_id]["name"] + "». "
            "Открывается на 15 уровне, усиливается на 18. Трактат не требуется.",
        )

    skills = (
        s(
            "femboy",
            "Ловушка очаровашки",
            "magic",
            10,
            90,
            30,
            3,
            (
                dict(e("adoration", "damage_pct", -0.40, 2), chance=0.75),
                e("arch_femboy_slow", "speed_pct", -0.15, 2),
            ),
        ),
        s(
            "princess",
            "Розовый барьер",
            None,
            0,
            100,
            25,
            4,
            (
                e("arch_princess_physical", "physical_defense_pct", 0.30, 2, "self"),
                e("arch_princess_magic", "magic_defense_pct", 0.30, 2, "self"),
                e("arch_princess_evasion", "evasion_flat", 8, 2, "self"),
            ),
        ),
        s(
            "gachi_actor",
            "Клубный захват",
            "physical",
            12,
            90,
            35,
            3,
            (
                e("arch_gachi_attack", "physical_attack_pct", -0.20, 2),
                e("arch_gachi_evasion", "evasion_flat", -12, 2),
            ),
        ),
        s(
            "mge_bro",
            "Ракетный прыжок",
            "physical",
            17,
            90,
            40,
            3,
            (e("arch_mge_risk", "physical_defense_pct", -0.15, 1, "self"),),
        ),
        s(
            "programmer",
            "Откат версии",
            None,
            0,
            100,
            20,
            4,
            (e("arch_programmer_ready", "next_magic_damage", 0.25, 2, "self"),),
            tags=("optimize",),
        ),
        s(
            "hacker",
            "Отказ в обслуживании",
            "magic",
            10,
            90,
            35,
            3,
            (
                e("arch_hacker_leech", "resource_leech", 20),
                e("arch_hacker_aim", "accuracy_flat", -12, 2),
            ),
        ),
        s(
            "thumb_discipline",
            "Построение",
            None,
            0,
            100,
            20,
            3,
            (
                e("arch_thumb_aim", "accuracy_flat", 15, 2, "self"),
                e("arch_thumb_guard", "physical_defense_pct", 0.20, 2, "self"),
            ),
        ),
        s(
            "thumb_execution",
            "Контрольный выстрел",
            "physical",
            18,
            90,
            40,
            3,
            pierce=0.35,
        ),
        s(
            "index_proxy",
            "Точное исполнение",
            "physical",
            15,
            95,
            30,
            2,
            (e("arch_proxy_evasion", "evasion_flat", -10, 2),),
        ),
        s(
            "index_messenger",
            "Непрошеный совет",
            None,
            0,
            95,
            25,
            3,
            (e("arch_messenger_attack", "physical_attack_pct", -0.10, 2),),
            tags=("enemy_prescript",),
        ),
        s(
            "middle_guardian",
            "Семья прикроет",
            "physical",
            10,
            90,
            30,
            3,
            (
                e("arch_middle_physical", "physical_defense_pct", 0.25, 2, "self"),
                e("arch_middle_magic", "magic_defense_pct", 0.25, 2, "self"),
            ),
        ),
        s(
            "middle_revenge",
            "Не забыто",
            "physical",
            17,
            90,
            35,
            3,
            (
                e("arch_revenge_physical", "physical_defense_pct", -0.15, 2),
                e("arch_revenge_magic", "magic_defense_pct", -0.15, 2),
            ),
        ),
        s(
            "ring_pointillist",
            "Пунктирная рана",
            "magic",
            9,
            90,
            30,
            3,
            (
                e("arch_ring_bleed", "bleed", 4, 3),
                e("arch_ring_defense", "physical_defense_pct", -0.12, 2),
            ),
        ),
        s(
            "ring_fauvist",
            "Чучело хищника",
            "magic",
            13,
            90,
            35,
            3,
            (
                e("arch_fauvist_slow", "speed_pct", -0.20, 2),
                e("arch_fauvist_defense", "magic_defense_pct", -0.15, 2),
            ),
        ),
        s(
            "pinky_dihui",
            "Охраняющий клинок",
            "physical",
            12,
            95,
            30,
            2,
            (
                e("arch_dihui_physical", "physical_defense_pct", 0.20, 1, "self"),
                e("arch_dihui_magic", "magic_defense_pct", 0.20, 1, "self"),
            ),
        ),
        s("pinky_tiansha", "Небесная рассечка", "physical", 17, 90, 40, 3, pierce=0.25),
    )
    return {skill.skill_id: skill for skill in skills}


def upgrade_description(branch_id):
    return {
        "princess": "«Розовый барьер»: обе защиты +35%, уклонение +10.",
        "programmer": "«Откат версии»: подготовка следующей магии +35% вместо +25%.",
        "thumb_discipline": "«Построение»: точность +20, физическая защита +25%.",
        "index_messenger": "«Непрошеный совет»: физическая атака цели −15% вместо −10%.",
    }.get(branch_id, "Уникальный навык 15 уровня: сила +2, цена и перезарядка прежние.")


def milestones(source):
    key = source["archclass_id"]
    # Avoid importing the engine at module import time (the catalog calls us).
    from arena_engine import BUILTIN_SKILLS

    skill = BUILTIN_SKILLS["arch_" + key]
    return [
        dict(level=12, description=UPGRADES_12[key], unlocked=source["level"] >= 12),
        dict(
            level=15,
            description="Новый навык: «" + skill.name + "».",
            skill_id=skill.skill_id,
            unlocked=source["level"] >= 15,
        ),
        dict(
            level=18,
            description=upgrade_description(key),
            unlocked=source["level"] >= 18,
        ),
    ]


def unique_rule(skill, source):
    key = skill_branch(skill)
    if not key or key != source.get("archclass_id"):
        return None
    changes = dict(power=skill.power + 2) if skill.damage_type else {}
    values = {
        "princess": {
            "physical_defense_pct": 0.35,
            "magic_defense_pct": 0.35,
            "evasion_flat": 10,
        },
        "programmer": {"next_magic_damage": 0.35},
        "thumb_discipline": {"accuracy_flat": 20, "physical_defense_pct": 0.25},
        "index_messenger": {"physical_attack_pct": -0.15},
    }.get(key)
    if values:
        changes["effects"] = tuple(
            dict(item, value=values.get(item["kind"], item["value"]))
            for item in skill.effects
        )
    return dict(
        name=skill.name + " · мастерство",
        trigger="always",
        min_level=18,
        condition="Достигнут 18 уровень своего архикласса",
        description=upgrade_description(key),
        changes=changes,
    )


def improve_rule(rule, source, skill):
    if source["level"] < 12:
        return rule
    key, changes = source["archclass_id"], rule["changes"]
    effects = changes.get("effects", skill.effects)
    values = {
        "princess": {"princess_physical": 0.25, "princess_magic": 0.25},
        "gachi_actor": {"gachi_attack": -0.20},
        "hacker": {"hacker_drain": 12},
        "thumb_discipline": {"warning": -0.30},
        "index_proxy": {"proxy_refund": 7},
        "middle_guardian": {"grit_guard": 0.40, "grit_magic": 0.30},
        "ring_pointillist": {"bleed": 5},
    }.get(key)
    if values:
        changes["effects"] = tuple(
            (
                dict(
                    item,
                    value=(
                        min(item["value"], values[item["id"]])
                        if values[item["id"]] < 0
                        else max(item["value"], values[item["id"]])
                    ),
                )
                if item["id"] in values
                else item
            )
            for item in effects
        )
    if key == "femboy":
        changes.update(
            power=max(changes["power"], 14), accuracy=min(100, skill.accuracy + 5)
        )
    elif key in {"mge_bro", "middle_revenge", "ring_fauvist"}:
        changes["accuracy"] = min(100, skill.accuracy + 5)
    elif key == "programmer" and skill.damage_type == "magic" and skill.cost:
        changes["cost"] = min(changes["cost"], max(1, skill.cost - 6))
    elif key == "thumb_execution":
        changes["power"] = max(changes["power"], 22)
    elif key == "pinky_dihui":
        changes["pierce"] = max(changes["pierce"], 0.50)
    elif key == "pinky_tiansha":
        changes["power"] = max(changes["power"], 20)
    rule["description"] += " Развитие 12 уровня: " + UPGRADES_12[key]
    return rule


def prescript_penalty(source):
    return 12 if final_stage(source) else 10 if source["level"] >= 12 else 8
