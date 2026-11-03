"""The Assassin: a light, tempo-oriented class built around short casts.

The class deliberately uses only ordinary engine effects.  This keeps its
bleeding and debuffs understandable in a mixed party and lets the action
timeline, rather than a hidden exception, create its extra-action identity.
"""


def build_catalog(FighterClass, Skill, effect):
    assassin = FighterClass(
        "assassin",
        "Ассасин",
        "Концентрация",
        5,
        {
            "max_hp": 39,
            "physical_attack": 10,
            "magic_attack": 4,
            "physical_defense": 6,
            "magic_defense": 7,
            "speed": 18,
            "evasion": 13,
        },
        {
            "max_hp": 3.7,
            "physical_attack": 1.0,
            "magic_attack": 0.3,
            "physical_defense": 0.55,
            "magic_defense": 0.65,
            "speed": 1.25,
            "evasion": 0.55,
        },
        (
            dict(
                effect("assassin_first_step", "speed_pct", .12, target="self"),
                name="Первый шаг",
                description="Скорость +12%. Короткие навыки чаще успевают попасть в окно до тяжёлого каста врага.",
            ),
            dict(
                effect("assassin_hidden", "evasion_flat", 6, target="self"),
                name="Тень за спиной",
                description="Уклонение +6. Ассасин выживает позицией, а не бронёй.",
            ),
        ),
        "uncommon",
    )

    def skill(key, name, level, damage_type, power, accuracy, cost, cooldown=0,
              effects=(), *, description="", pierce=None, tags=()):
        return Skill(
            key, name, "assassin", level, damage_type, power, accuracy, cost,
            cooldown, effects, "rare" if level >= 8 else "uncommon", description,
            pierce, ("assassin", *tags),
            {
                "assassin_cut": 2.05,
                "assassin_needle": 2.3,
                "assassin_smoke": 1.45,
                "assassin_expose": 2.9,
                "assassin_execution": 4.1,
            }[key],
        )

    skills = (
        skill(
            "assassin_cut", "Теневой надрез", 5, "physical", 8, 97, 8,
            effects=(effect("assassin_cut_bleed", "bleed", 2, 3),),
            description="Короткий удар. При попадании накладывает кровотечение: −2 HP при каждом из трёх следующих атакующих действий цели.",
            tags=("quick",),
        ),
        skill(
            "assassin_needle", "Игла в сухожилие", 5, "physical", 7, 100, 14, 1,
            effects=(
                effect("assassin_limp", "speed_pct", -.25, 2, chance=.85),
                effect("assassin_needle_bleed", "bleed", 1, 3),
            ),
            description="Точный укол: с шансом 85% снижает скорость цели на 25% на два её действия и при попадании всегда накладывает слабое кровотечение.",
            tags=("quick",),
        ),
        skill(
            "assassin_smoke", "Дымовой уход", 6, None, 0, 100, 18, 3,
            effects=(effect("assassin_smoke", "evasion_flat", 22, 2, target="self"),),
            description="На два собственных действия даёт +22 уклонения. Не наносит урон, но создаёт окно для риска.",
            tags=("quick",),
        ),
        skill(
            "assassin_expose", "Открытая рана", 7, "physical", 10, 95, 22, 2,
            effects=(
                effect("assassin_expose", "damage_taken_pct", .20, 2, chance=.90),
                effect("assassin_expose_bleed", "bleed", 3, 3),
            ),
            description="Вскрывает защиту: с шансом 90% делает цель уязвимой (+20% входящего урона) на два её действия и при попадании всегда накладывает кровотечение −3.",
            tags=("quick",),
        ),
        skill(
            "assassin_execution", "Перерезать нить", 8, "physical", 20, 92, 38, 3,
            effects=(effect("assassin_execution_bleed", "bleed", 4, 3),),
            description="Финиширующий рез с пробитием 30%. При попадании накладывает тяжёлое кровотечение −4 на три атакующих действия цели.",
            pierce=.30,
            tags=("quick",),
        ),
    )
    return {"assassin": assassin}, {entry.skill_id: entry for entry in skills}
