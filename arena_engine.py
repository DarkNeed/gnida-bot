from __future__ import annotations

import math
import random
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Iterable
from arena_fingers import (
    build_catalog,
    has_trait,
    negative_kinds,
    combat_modifiers,
    after_action,
)
from arena_class_mechanics import class_modifiers, class_after_action, has_adoration
from arena_mirror_effects import gift_cost, gift_modifiers, gift_after_action
from arena_evolution import skill_variant, evolution_after_action
from arena_archclasses import (
    arch_after_action, obey_enemy_prescript, selected_branch, revenge_recoil,
)
from arena_archprogress import build_arch_skills, branch_skill_allowed, skill_branch

BASE_RESOURCE = 100
BASE_RESOURCE_REGEN = 0
CONTROL_PENALTY = 0.8
MAX_ACTIVE_SKILLS = 4
MAX_PASSIVE_SKILLS = 2
MAX_LEARNED_ACTIVE_SKILLS = 6
MAX_LEARNED_PASSIVE_SKILLS = 3
MAX_FIGHTER_LEVEL = 20
RARITY_LABELS = {
    "common": "Обычный",
    "uncommon": "Необычный",
    "rare": "Редкий",
    "epic": "Эпический",
}
CLASS_SELECTION_LEVEL = 5
SKILL_DELEGATION_SECONDS = 48 * 60 * 60


@dataclass(frozen=True)
class FighterClass:
    class_id: str
    name: str
    resource_name: str
    base_level: int
    base_stats: dict[str, float]
    growth: dict[str, float]
    passives: tuple[dict[str, Any], ...] = ()
    rarity: str = "common"


@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    class_id: str
    unlock_level: int
    damage_type: str | None
    power: float
    accuracy: float
    cost: int
    cooldown: int
    effects: tuple[dict[str, Any], ...] = ()
    rarity: str = "common"
    description: str = ""
    pierce: float | None = None
    tags: tuple[str, ...] = ()

    @property
    def hostile(self) -> bool:
        return self.damage_type is not None or any(
            effect.get("target") == "enemy" for effect in self.effects
        )


FIGHTER_CLASSES = {
    "ragamuffin": FighterClass(
        "ragamuffin",
        "Оборванец",
        "Выносливость",
        1,
        {
            "max_hp": 20,
            "physical_attack": 5,
            "magic_attack": 3,
            "physical_defense": 3,
            "magic_defense": 3,
            "speed": 5,
            "evasion": 4,
        },
        {
            "max_hp": 4,
            "physical_attack": 1,
            "magic_attack": 0.5,
            "physical_defense": 0.5,
            "magic_defense": 0.5,
            "speed": 1,
            "evasion": 1,
        },
    ),
    "cutie": FighterClass(
        "cutie",
        "Милашка",
        "Любовь",
        5,
        {
            "max_hp": 42,
            "physical_attack": 8,
            "magic_attack": 12,
            "physical_defense": 7,
            "magic_defense": 10,
            "speed": 14,
            "evasion": 14,
        },
        {
            "max_hp": 4,
            "physical_attack": 0.6,
            "magic_attack": 1.5,
            "physical_defense": 0.7,
            "magic_defense": 1,
            "speed": 1.2,
            "evasion": 0.5,
        },
    ),
    "jock": FighterClass(
        "jock",
        "Качок",
        "Тестостерон",
        5,
        {
            "max_hp": 53,
            "physical_attack": 13.5,
            "magic_attack": 4,
            "physical_defense": 12,
            "magic_defense": 8,
            "speed": 8,
            "evasion": 4,
        },
        {
            "max_hp": 5,
            "physical_attack": 1.5,
            "magic_attack": 0.3,
            "physical_defense": 1.05,
            "magic_defense": 0.8,
            "speed": 0.6,
            "evasion": 0.2,
        },
    ),
    "nerd": FighterClass(
        "nerd",
        "Задрот",
        "Энергосы",
        5,
        {
            "max_hp": 44,
            "physical_attack": 5,
            "magic_attack": 16,
            "physical_defense": 7,
            "magic_defense": 12,
            "speed": 6,
            "evasion": 3,
        },
        {
            "max_hp": 4.5,
            "physical_attack": 0.4,
            "magic_attack": 2,
            "physical_defense": 0.65,
            "magic_defense": 1.3,
            "speed": 0.5,
            "evasion": 0.1,
        },
    ),
}


def effect(
    effect_id: str,
    kind: str,
    value: float,
    turns: int = 0,
    *,
    target: str = "enemy",
    chance: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": effect_id,
        "kind": kind,
        "value": value,
        "turns": turns,
        "target": target,
        "chance": chance,
    }


BUILTIN_SKILLS = {
    skill.skill_id: skill
    for skill in (
        Skill("bum_punch", "Удар бомжа", "ragamuffin", 1, "physical", 10, 85, 0, 0),
        Skill(
            "dust_in_eyes",
            "Пыль в глаза",
            "ragamuffin",
            3,
            None,
            0,
            85,
            20,
            3,
            (effect("dust", "accuracy_flat", -20, 3),),
        ),
        Skill(
            "uwu",
            "UWU",
            "cutie",
            5,
            "magic",
            8,
            90,
            10,
            0,
            (effect("adoration", "damage_pct", -0.40, 2, chance=0.60),),
        ),
        Skill(
            "posing",
            "Позирование",
            "cutie",
            6,
            None,
            0,
            100,
            20,
            3,
            (effect("posing", "evasion_flat", 20, 3, target="self"),),
        ),
        Skill(
            "air_kiss",
            "Воздушный поцелуй",
            "cutie",
            7,
            "magic",
            12,
            90,
            20,
            1,
            (effect("adoration", "damage_pct", -0.40, 2, chance=0.45),),
            description="Против умилённой цели наносит на 20% больше урона.",
        ),
        Skill(
            "meow",
            "Мяу",
            "cutie",
            9,
            "magic",
            17,
            85,
            35,
            2,
            description="Против умилённой цели +25% урона, но при попадании умиление снимается.",
        ),
        Skill("smack", "Въебать", "jock", 5, "physical", 10, 95, 10, 0),
        Skill("butt_peak", "Жопный пик", "jock", 6, "physical", 18, 75, 45, 3),
        Skill(
            "flex_chest",
            "Напрячь сиси",
            "jock",
            7,
            None,
            0,
            100,
            25,
            3,
            (
                effect("flex_physical", "physical_defense_pct", 0.35, 3, target="self"),
                effect("flex_magic", "magic_defense_pct", 0.20, 3, target="self"),
            ),
        ),
        Skill(
            "clench",
            "Зажим булками",
            "jock",
            8,
            None,
            0,
            90,
            20,
            2,
            (effect("clenched", "evasion_flat", -20, 3),),
        ),
        Skill(
            "wallop",
            "Уебать",
            "jock",
            9,
            "physical",
            10,
            82,
            30,
            2,
            (effect("stun", "stun", 1, 1, chance=0.35),),
        ),
        Skill(
            "humiliate",
            "Унизить",
            "nerd",
            5,
            "magic",
            13,
            88,
            15,
            0,
            (effect("humiliate_drain", "resource_leech", 15),),
            description="Отнимает до 15 энергии и возвращает себе половину действительно отнятого ресурса.",
        ),
        Skill(
            "charging",
            "Зарядка",
            "nerd",
            6,
            None,
            0,
            100,
            15,
            3,
            (
                effect("charging_damage", "next_magic_damage", 0.60, 3, target="self"),
                effect("charging_aim", "accuracy_flat", 10, 1, target="self"),
            ),
            description="Следующая магическая атака получает +60% урона. Усиление действует не дольше 3 своих действий и расходуется даже при промахе.",
        ),
        Skill(
            "doxxing",
            "Деанон",
            "nerd",
            7,
            None,
            0,
            90,
            20,
            3,
            (
                effect("doxxing_physical", "physical_defense_pct", -0.20, 3),
                effect("doxxing_magic", "magic_defense_pct", -0.20, 3),
                effect("doxxed", "evasion_flat", -15, 3),
            ),
        ),
        Skill(
            "mother_joke",
            "Шутка про мать",
            "nerd",
            8,
            "magic",
            18,
            80,
            40,
            2,
            (effect("enraged", "damage_pct", 0.20, 2),),
            description="По цели под Деаноном +20% урона. При попадании усиливает урон противника на 20% на 2 его хода.",
        ),
        Skill(
            "go_to_store",
            "Сходить в магаз",
            "nerd",
            9,
            None,
            0,
            100,
            0,
            0,
            (effect("energy_drinks", "resource", 55, target="self"),),
        ),
    )
}


VISIBLE_CLASS_ALIASES = {
    "оборванец": "ragamuffin",
    "милашка": "cutie",
    "качок": "jock",
    "задрот": "nerd",
}

FIGHTER_CLASSES = {
    k: replace(c, rarity="common" if k == "ragamuffin" else "uncommon")
    for k, c in FIGHTER_CLASSES.items()
}
BUILTIN_SKILLS = {
    k: replace(
        s,
        rarity=(
            "rare"
            if s.unlock_level >= 8
            else "uncommon" if s.unlock_level >= 5 else "common"
        ),
    )
    for k, s in BUILTIN_SKILLS.items()
}

_finger_classes, _finger_skills = build_catalog(FighterClass, Skill, effect)
FIGHTER_CLASSES.update(_finger_classes)
BUILTIN_SKILLS.update(_finger_skills)
BUILTIN_SKILLS.update(build_arch_skills(Skill))
VISIBLE_CLASS_ALIASES.update({c.name.casefold(): k for k, c in _finger_classes.items()})
# Old names remain valid input; stable IDs keep inventory and saved builds intact.
VISIBLE_CLASS_ALIASES.update(
    {
        "капо": "thumb",
        "исполнитель": "index",
        "мститель семьи": "middle",
        "маэстро": "ring",
    }
)

FIGHTER_CLASSES["cutie"] = replace(
    FIGHTER_CLASSES["cutie"],
    passives=(
        dict(
            effect("charming", "charming", 1, target="self"),
            name="Очаровашка",
            description="Успешное наложение умиления возвращает 5 Любви, не чаще раза за действие.",
        ),
        dict(
            effect("evasive_love", "evasive_love", 1, target="self"),
            name="Не трогай лапками",
            description="Уклонение от прямой атаки возвращает 8 Любви. Обычный промах врага бонуса не даёт.",
        ),
    ),
)
FIGHTER_CLASSES["nerd"] = replace(
    FIGHTER_CLASSES["nerd"],
    passives=(
        dict(
            effect("analysis", "analysis", 1, target="self"),
            name="Анализ",
            description="Разная магическая атака после предыдущей получает +10 точности. Повтор бонуса не даёт.",
        ),
        dict(
            effect("economy", "economy", 1, target="self"),
            name="Экономия",
            description="Каждая третья платная магическая атака возвращает 10 энергии. Счётчик обнуляется в новом бою.",
        ),
    ),
)
FIGHTER_CLASSES["jock"] = replace(
    FIGHTER_CLASSES["jock"],
    passives=(
        dict(
            effect("right_version", "right_version", 1, target="self"),
            name="♂ Right Version ♂",
            description="Успешные «Напрячь сиси» и «Зажим булками» усиливают следующую физическую атаку на 15%. Не складывается; действует 2 своих хода, расходуется даже при промахе.",
        ),
        dict(
            effect("fucking_stamina", "fucking_stamina", 1, target="self"),
            name="♂ Fucking Stamina ♂",
            description="«Напрячь сиси» и успешный «Зажим булками» возвращают 8 Тестостерона после оплаты навыка. Ход и перезарядка сохраняются.",
        ),
    ),
)


@dataclass(frozen=True)
class PassiveSkill:
    skill_id: str
    name: str
    effects: tuple[dict[str, Any], ...]
    rarity: str = "common"


BUILTIN_PASSIVES = {
    p.skill_id: p
    for p in (
        PassiveSkill(
            "steady_hand",
            "Твёрдая рука",
            (effect("steady_hand", "accuracy_flat", 8, target="self"),),
        ),
        PassiveSkill(
            "light_step",
            "Лёгкий шаг",
            (effect("light_step", "evasion_flat", 5, target="self"),),
        ),
        PassiveSkill(
            "quick_start",
            "Расторопность",
            (effect("quick_start", "speed_pct", 0.10, target="self"),),
        ),
        PassiveSkill(
            "stone_skin",
            "Каменная кожа",
            (effect("stone_skin", "physical_defense_pct", 0.15, target="self"),),
            "uncommon",
        ),
        PassiveSkill(
            "magic_ward",
            "Магический оберег",
            (effect("magic_ward", "magic_defense_pct", 0.15, target="self"),),
            "uncommon",
        ),
        PassiveSkill(
            "battle_rhythm",
            "Боевой ритм",
            (effect("battle_rhythm", "damage_pct", 0.08, target="self"),),
            "rare",
        ),
    )
}


def content_rarity(payload: dict) -> str:
    rarity = str(payload.get("rarity", "rare"))
    if rarity not in RARITY_LABELS:
        raise ValueError("Unknown rarity")
    return rarity


def fighter_class_from_dict(class_id: str, payload: dict[str, Any]) -> FighterClass:
    """Build a validated custom class from its database definition."""
    base_stats = payload.get("base_stats")
    growth = payload.get("growth")
    required = {
        "max_hp",
        "physical_attack",
        "magic_attack",
        "physical_defense",
        "magic_defense",
        "speed",
        "evasion",
    }
    if not isinstance(base_stats, dict) or not required.issubset(base_stats):
        raise ValueError("base_stats must contain every combat stat")
    if not isinstance(growth, dict):
        raise ValueError("growth must be an object")
    normalized_stats = {key: float(base_stats[key]) for key in required}
    normalized_growth = {key: float(growth.get(key, 0)) for key in required}
    if any(
        not math.isfinite(v) or abs(v) > 10000
        for v in (*normalized_stats.values(), *normalized_growth.values())
    ):
        raise ValueError("class stats must be finite and bounded")
    if normalized_stats["max_hp"] <= 0 or any(
        value < 0 for value in normalized_stats.values()
    ):
        raise ValueError("class stats cannot be negative")
    passives = payload.get("passives", [])
    if not isinstance(passives, list):
        raise ValueError("passives must be an array")
    if len(passives) > 10:
        raise ValueError("too many passives")
    for item in passives:
        if not isinstance(item, dict) or item.get("kind") not in {
            "accuracy_flat",
            "damage_pct",
            "speed_pct",
            "physical_defense_pct",
            "magic_defense_pct",
            "evasion_flat",
        }:
            raise ValueError("unsupported passive")
        if (
            not math.isfinite(float(item.get("value", 0)))
            or abs(float(item.get("value", 0))) > 100
        ):
            raise ValueError("passive must be finite and bounded")
    return FighterClass(
        class_id=class_id,
        name=str(payload["name"]).strip(),
        resource_name=str(payload.get("resource_name", "Выносливость")).strip(),
        base_level=max(1, int(payload.get("base_level", 5))),
        base_stats=normalized_stats,
        growth=normalized_growth,
        passives=tuple(dict(item) for item in passives if isinstance(item, dict)),
        rarity=content_rarity(payload),
    )


def skill_from_dict(skill_id: str, payload: dict[str, Any]) -> Skill:
    """Build a custom skill using the same bounded primitives as built-ins."""
    damage_type = payload.get("damage_type")
    if damage_type not in {None, "physical", "magic"}:
        raise ValueError("damage_type must be physical, magic or null")
    effects = payload.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError("effects must be an array")
    if len(effects) > 10 or any(
        not math.isfinite(float(payload.get(k, 0))) for k in ("power", "accuracy")
    ):
        raise ValueError("invalid skill numbers")
    allowed_effects = {
        "accuracy_flat",
        "damage_pct",
        "speed_pct",
        "physical_defense_pct",
        "magic_defense_pct",
        "evasion_flat",
        "resource",
        "stun",
        "bleed",
        "physical_attack_pct",
        "resource_leech",
        "next_magic_damage",
    }
    normalized_effects: list[dict[str, Any]] = []
    for item in effects:
        if not isinstance(item, dict) or item.get("kind") not in allowed_effects:
            raise ValueError("unsupported effect")
        if (
            any(not math.isfinite(float(item.get(k, 0))) for k in ("value", "chance"))
            or abs(float(item.get("value", 0))) > 100
        ):
            raise ValueError("effect must be finite and bounded")
        normalized_effects.append(
            effect(
                str(item.get("id") or f"{skill_id}_{len(normalized_effects)}"),
                str(item["kind"]),
                float(item.get("value", 0)),
                max(0, min(10, int(item.get("turns", 0)))),
                target="self" if item.get("target") == "self" else "enemy",
                chance=max(0.0, min(1.0, float(item.get("chance", 1)))),
            )
        )
    return Skill(
        skill_id=skill_id,
        name=str(payload["name"]).strip(),
        class_id=str(payload.get("class_id", "ragamuffin")),
        unlock_level=max(1, int(payload.get("unlock_level", 1))),
        damage_type=damage_type,
        power=max(0.0, min(100.0, float(payload.get("power", 0)))),
        accuracy=max(5.0, min(100.0, float(payload.get("accuracy", 100)))),
        cost=max(0, min(BASE_RESOURCE, int(payload.get("cost", 0)))),
        cooldown=max(0, min(10, int(payload.get("cooldown", 0)))),
        effects=tuple(normalized_effects),
        rarity=content_rarity(payload),
    )


def xp_for_next_level(level: int) -> int:
    return math.ceil(10 * (1.4 ** max(0, level - 1)))


def level_from_total_xp(
    total_xp: int, max_level: int | None = MAX_FIGHTER_LEVEL
) -> int:
    level = 1
    remaining = max(0, total_xp)
    while (max_level is None or level < max_level) and remaining >= xp_for_next_level(
        level
    ):
        remaining -= xp_for_next_level(level)
        level += 1
    return level


def level_progress(total_xp: int) -> tuple[int, int, int]:
    level = 1
    remaining = max(0, total_xp)
    while level < MAX_FIGHTER_LEVEL and remaining >= xp_for_next_level(level):
        remaining -= xp_for_next_level(level)
        level += 1
    return (
        (level, 0, 0)
        if level == MAX_FIGHTER_LEVEL
        else (level, remaining, xp_for_next_level(level))
    )


def fighter_xp_limit() -> int:
    return sum(xp_for_next_level(level) for level in range(1, MAX_FIGHTER_LEVEL))


def stats_for(
    class_id: str,
    level: int,
    controlled: bool = False,
    classes: dict[str, FighterClass] | None = None,
) -> dict[str, float]:
    catalog = classes or FIGHTER_CLASSES
    fighter_class = catalog.get(class_id, FIGHTER_CLASSES["ragamuffin"])
    effective_level = max(1, min(MAX_FIGHTER_LEVEL, level))
    delta = effective_level - fighter_class.base_level
    stats = {
        key: max(0, round(value + fighter_class.growth.get(key, 0) * delta, 2))
        for key, value in fighter_class.base_stats.items()
    }
    stats["resource_max"] = BASE_RESOURCE
    stats["resource_regen"] = BASE_RESOURCE_REGEN
    if controlled:
        stats = {key: round(value * CONTROL_PENALTY, 2) for key, value in stats.items()}
    for key in ("max_hp", "resource_max"):
        stats[key] = max(1, round(stats[key]))
    return stats


def unlocked_skill_ids(
    class_id: str,
    level: int,
    skills: dict[str, Skill] | None = None,
    granted: Iterable[str] = (),
    known: Iterable[str] | None = None,
    archclass_id: str = "",
) -> list[str]:
    catalog = skills or BUILTIN_SKILLS
    allowed_classes = {"ragamuffin"}
    if class_id != "ragamuffin":
        allowed_classes.add(class_id)
    return [
        skill.skill_id
        for skill in sorted(
            catalog.values(), key=lambda item: (item.unlock_level, item.skill_id)
        )
        if (
            (skill.skill_id in BUILTIN_SKILLS and skill.class_id in allowed_classes)
            or (class_id not in FIGHTER_CLASSES and skill.class_id == class_id)
            or skill.skill_id in granted
        )
        and skill.unlock_level <= level
        and branch_skill_allowed(skill, archclass_id, level)
        and (known is None or skill.skill_id in known)
    ]


def normalize_loadout(
    class_id: str,
    level: int,
    requested: Iterable[str] | None,
    skills: dict[str, Skill] | None = None,
    granted: Iterable[str] = (),
    known: Iterable[str] | None = None,
    archclass_id: str = "",
) -> list[str]:
    unlocked = unlocked_skill_ids(class_id, level, skills, granted, known, archclass_id)
    selected: list[str] = []
    for skill_id in requested or ():
        if skill_id in unlocked and skill_id not in selected:
            selected.append(skill_id)
        if len(selected) == MAX_ACTIVE_SKILLS:
            break
    for skill_id in unlocked:
        if skill_id not in selected and len(selected) < MAX_ACTIVE_SKILLS:
            selected.append(skill_id)
    return selected


def create_battle_state(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    classes: dict[str, FighterClass] | None = None,
    skills: dict[str, Skill] | None = None,
) -> dict[str, Any]:
    class_catalog = classes or FIGHTER_CLASSES
    skill_catalog = skills or BUILTIN_SKILLS
    sides: dict[str, dict[str, Any]] = {}
    for side, source in (("a", first), ("b", second)):
        controlled = bool(source.get("controlled"))
        class_id = str(source["class_id"])
        stats = stats_for(class_id, int(source["level"]), controlled, class_catalog)
        fighter_class = class_catalog.get(class_id, FIGHTER_CLASSES["ragamuffin"])
        passive_details = source.get("passive_details")
        if passive_details is None:
            passive_details = [
                dict(
                    skill_id=f"inherent:{class_id}:{i}",
                    name=p.get("name", "Пассивка класса"),
                    effects=[p],
                    rarity=fighter_class.rarity,
                )
                for i, p in enumerate(fighter_class.passives[:MAX_PASSIVE_SKILLS])
            ]
        passive_details = passive_details[:MAX_PASSIVE_SKILLS]
        starting_effects = [
            {
                **item,
                "duration": 1_000_000,
            }
            for passive in passive_details
            for item in passive["effects"]
            if item.get("kind")
            in {
                "accuracy_flat",
                "damage_pct",
                "speed_pct",
                "physical_defense_pct",
                "magic_defense_pct",
                "evasion_flat",
                "physical_attack_pct",
            }
        ]
        sides[side] = {
            "slave_id": int(source["slave_id"]),
            "owner_id": int(source["owner_id"]),
            "controller_id": int(
                source["owner_id"] if controlled else source["slave_id"]
            ),
            "controlled": controlled,
            "class_id": class_id,
            "archclass_id": (
                source.get("archclass_id", "") if selected_branch(source) else ""
            ),
            "archclass_stage": source.get("archclass_stage", 20),
            "level": min(MAX_FIGHTER_LEVEL, int(source["level"])),
            "stats": stats,
            "hp": stats["max_hp"],
            "resource": stats["resource_max"],
            "loadout": normalize_loadout(
                class_id,
                int(source["level"]),
                source.get("loadout"),
                skill_catalog,
                source.get("granted_skills", ()),
                source.get("known_skills"),
                source.get("archclass_id", ""),
            ),
            "effects": starting_effects,
            "passive_details": passive_details,
            "cooldowns": {},
            "potion_used": False,
            "own_turns": 0,
        }
    return {
        "turn": 1,
        "sides": sides,
        "log": [],
        "winner": None,
        "finished": False,
        "flow": "single_click",
        "phase": "skill",
        "active_side": "a",
    }


def effective_stat(side: dict, name: str) -> float:
    value = float(side["stats"].get(name, 0))
    pct = sum(
        float(e.get("value", 0))
        for e in side["effects"]
        if e.get("kind") == name + "_pct"
    )
    flat = sum(
        float(e.get("value", 0))
        for e in side["effects"]
        if e.get("kind") == name + "_flat"
    )
    if name in {"physical_defense", "magic_defense"}:
        if has_trait(side, "uniform") and side["hp"] > side["stats"]["max_hp"] / 2:
            pct += 0.15
        if has_trait(side, "tattoos") and side["hp"] <= side["stats"]["max_hp"] * 0.4:
            pct += 0.25
    return max(0, value * max(0, 1 + pct) + flat)


def completed_turns(state: dict, side_key: str) -> int:
    side = state["sides"][side_key]
    # Legacy battles have a bounded log but need only a threshold of four.
    return side.get("own_turns", sum(e.get("side") == side_key for e in state["log"]))


def _initialize_turn_counts(state: dict) -> None:
    for key, side in state["sides"].items():
        side.setdefault("own_turns", completed_turns(state, key))


def effective_skill(state: dict, side_key: str, skill_id: str, skills=None) -> Skill:
    skill = (skills or BUILTIN_SKILLS)[skill_id]
    return skill_variant(
        skill,
        state["sides"][side_key],
        state["sides"]["b" if side_key == "a" else "a"],
        completed_turns(state, side_key),
    )


def validate_skill(state: dict, side_key: str, skill_id: str, skills=None) -> Skill:
    catalog = skills or BUILTIN_SKILLS
    if state["finished"] or state["active_side"] != side_key:
        raise ValueError("Сейчас не ваш ход.")
    side = state["sides"][side_key]
    if (
        skill_id not in side["loadout"] and skill_id != "bum_punch"
    ) or skill_id not in catalog:
        raise ValueError("Навык недоступен.")
    if (
        not branch_skill_allowed(
            catalog[skill_id], side.get("archclass_id", ""), side["level"]
        )
        or (
            skill_branch(catalog[skill_id])
            and (
                not selected_branch(side)
                or catalog[skill_id].class_id != side["class_id"]
            )
        )
    ):
        raise ValueError("Навык недоступен этому архиклассу или уровню.")
    skill = effective_skill(state, side_key, skill_id, catalog)
    if side["resource"] < gift_cost(side, skill):
        raise ValueError("Недостаточно выносливости.")
    if side["cooldowns"].get(skill_id, 0) > 0:
        raise ValueError("Навык восстанавливается.")
    return skill


def _tick(side: dict) -> None:
    side["own_turns"] = side.get("own_turns", 0) + 1
    side["effects"] = [
        dict(e, duration=e["duration"] - 1)
        for e in side["effects"]
        if e["duration"] > 1
    ]
    side["cooldowns"] = {k: v - 1 for k, v in side["cooldowns"].items() if v > 1}
    # No automatic refund after a skill, including battles saved by older code.
    # Resource can still be restored by skills with an explicit resource effect.


def battle_status_snapshot(state: dict) -> dict:
    """Small detached UI snapshot: no passive sentinels or instant resource changes."""
    return {
        key: {
            "effects": deepcopy(
                [
                    e
                    for e in side.get("effects", [])
                    if 0 < e.get("duration", 0) < 10_000
                    and e.get("kind") not in {"resource", "resource_leech"}
                ]
            ),
            "mechanics": deepcopy(
                {
                    name: side["mechanics"][name]
                    for name in (
                        "order",
                        "grudge",
                        "focus",
                        "prescript",
                        "enemy_prescript",
                    )
                    if name in side.get("mechanics", {})
                }
            ),
        }
        for key, side in state["sides"].items()
    }


def _advance_turn(state: dict, side_key: str) -> None:
    other = "b" if side_key == "a" else "a"
    target = state["sides"][other]
    state["turn"] += 1
    state["active_side"] = other
    actor = state["sides"][side_key]
    if actor["hp"] <= 0 and target["hp"] <= 0:
        state.update(finished=True, winner=None, finish_reason="mutual_knockout")
    elif actor["hp"] <= 0:
        state.update(finished=True, winner=other, finish_reason="self_damage")
    elif target["hp"] <= 0:
        state.update(finished=True, winner=side_key)
    elif state["turn"] > 200:
        state.update(finished=True, winner=None, finish_reason="turn_limit")
    elif any(e["kind"] == "stun" for e in target["effects"]):
        order_note = obey_enemy_prescript(target, None)
        _tick(target)
        state["log"].append(
            {
                "seq": state["turn"],
                "side": other,
                "text": "Ошеломление: ход пропущен."
                + (" · " + order_note if order_note else ""),
                "damage": 0,
                "hit": False,
                "status_after": battle_status_snapshot(state),
            }
        )
        state["turn"] += 1
        state["active_side"] = side_key


def skip_turn(state: dict) -> None:
    """Server-only timeout: consumes a turn, not resource or an attack/passive proc."""
    if state["finished"]:
        raise ValueError("Бой завершён.")
    _initialize_turn_counts(state)
    key = state["active_side"]
    actor = state["sides"][key]
    target = state["sides"]["b" if key == "a" else "a"]
    state.setdefault("had_player_action", any(e.get("skill_id") for e in state["log"]))
    before = {
        k: {"hp": s["hp"], "resource": s["resource"]} for k, s in state["sides"].items()
    }
    order_note = obey_enemy_prescript(actor, None)
    _tick(actor)
    # As with a normal action, damage-over-time is applied as the next side starts.
    bleed_damage = min(
        target["hp"],
        sum(max(0, int(e["value"])) for e in target["effects"] if e["kind"] == "bleed"),
    )
    target["hp"] -= bleed_damage
    text = "Время вышло: ход пропущен (2 минуты)."
    if bleed_damage:
        text += f" · кровотечение: −{bleed_damage} HP"
    if order_note:
        text += " · " + order_note
    state["log"].append(
        dict(
            seq=state["turn"],
            side=key,
            action_kind="turn_timeout",
            text=text,
            damage=0,
            hit=False,
            bleed_damage=bleed_damage,
            before=before,
            after={
                k: {"hp": s["hp"], "resource": s["resource"]}
                for k, s in state["sides"].items()
            },
            status_after=battle_status_snapshot(state),
        )
    )
    state["log"] = state["log"][-60:]
    _advance_turn(state, key)


def resolve_skill(
    state: dict, side_key: str, skill_id: str, skills=None, rng=None
) -> dict:
    """Resolve one tap entirely on the server. No directional/confirmation phase."""
    rng = rng or random.SystemRandom()
    skill = validate_skill(state, side_key, skill_id, skills)
    _initialize_turn_counts(state)
    evolved = skill is not (skills or BUILTIN_SKILLS)[skill_id]
    state["had_player_action"] = True
    actor = state["sides"][side_key]
    other = "b" if side_key == "a" else "a"
    target = state["sides"][other]
    before = {
        k: {"hp": s["hp"], "resource": s["resource"]} for k, s in state["sides"].items()
    }
    previous_negatives = negative_kinds(target)
    adored = has_adoration(target)
    bleeding = any(e["kind"] == "bleed" for e in target["effects"])
    mirror_accuracy, mirror_multiplier = gift_modifiers(actor, target)
    actual_cost = gift_cost(actor, skill)
    class_accuracy, class_boost = class_modifiers(actor, target, skill)
    extra_accuracy, extra_boost, pierce, critical, obeyed = combat_modifiers(
        actor, target, skill, rng
    )
    if skill.pierce is not None:
        pierce = skill.pierce
    if "no_critical" in skill.tags:
        critical = False
    accuracy_bonus = sum(
        e.get("value", 0) for e in actor["effects"] if e.get("kind") == "accuracy_flat"
    )
    roll = rng.random() * 100 if skill.hostile else 0
    raw_accuracy = (
        skill.accuracy
        + accuracy_bonus
        + extra_accuracy
        + class_accuracy
        + mirror_accuracy
    )
    hit = not skill.hostile or roll < max(
        5,
        min(
            95,
            raw_accuracy - effective_stat(target, "evasion"),
        ),
    )
    dodged = bool(
        skill.damage_type and not hit and roll < max(5, min(95, raw_accuracy))
    )
    actor["resource"] -= actual_cost
    order_note = obey_enemy_prescript(actor, skill_id)
    damage = 0
    if hit and skill.damage_type:
        attack = effective_stat(actor, skill.damage_type + "_attack")
        defense = effective_stat(target, skill.damage_type + "_defense") * (1 - pierce)
        boosts = [
            e.get("value", 0) for e in actor["effects"] if e.get("kind") == "damage_pct"
        ]
        boost = sum(v for v in boosts if v >= 0)
        reduction = max(0.1, 1 + sum(v for v in boosts if v < 0))
        damage = max(
            1,
            round(
                skill.power
                * (1 + attack / 20)
                * 100
                / (100 + defense * 4)
                * max(0.1, 1 + boost + extra_boost + class_boost)
                * reduction
                * mirror_multiplier
                * (1.5 if critical else 1)
                * rng.uniform(0.95, 1.05)
            ),
        )
        target["hp"] = max(0, target["hp"] - damage)
    # Existing buffs expire after this action, before newly applied buffs are added.
    if skill.damage_type == "magic":
        actor["effects"] = [
            e for e in actor["effects"] if e["kind"] != "next_magic_damage"
        ]
    elif skill.damage_type == "physical":
        actor["effects"] = [
            e for e in actor["effects"] if e["kind"] != "next_physical_damage"
        ]
    _tick(actor)
    effects_text = []
    charmed = False
    if hit:
        for effect in skill.effects:
            if rng.random() >= effect.get("chance", 1):
                continue
            recipient = target if effect.get("target") == "enemy" else actor
            if effect["kind"] == "resource_leech":
                stolen = min(recipient["resource"], max(0, int(effect["value"])))
                recipient["resource"] -= stolen
                actor["resource"] = min(
                    actor["stats"]["resource_max"], actor["resource"] + stolen // 2
                )
            elif effect["kind"] == "resource":
                recipient["resource"] = max(
                    0,
                    min(
                        recipient["stats"]["resource_max"],
                        recipient["resource"] + int(effect["value"]),
                    ),
                )
            else:
                new = dict(effect)
                new.setdefault("duration", max(1, new.get("turns", 1)))
                recipient["effects"] = [
                    e
                    for e in recipient["effects"]
                    if (e.get("id"), e["kind"]) != (new.get("id"), new["kind"])
                ]
                recipient["effects"].append(new)
                charmed = charmed or (
                    recipient is target
                    and new.get("id") == "adoration"
                    and new["kind"] == "damage_pct"
                    and new.get("value", 0) < 0
                )
            label = (
                "умиление"
                if effect.get("id") == "adoration"
                else {
                    "accuracy_flat": "точность",
                    "damage_pct": "урон",
                    "speed_pct": "скорость",
                    "physical_defense_pct": "защита",
                    "magic_defense_pct": "маг. защита",
                    "evasion_flat": "уклонение",
                    "resource": "ресурс",
                    "stun": "ошеломление",
                    "bleed": "кровотечение",
                    "physical_attack_pct": "физ. атака",
                    "resource_leech": "похищение энергии",
                    "next_magic_damage": "подготовка магии",
                }.get(effect["kind"], effect["kind"])
            )
            effects_text.append(label)
    if skill.cooldown:
        actor["cooldowns"][skill_id] = skill.cooldown
    class_after_action(actor, target, skill, hit, dodged, adored, charmed)
    gift_after_action(actor, target, skill, hit, damage, actual_cost, bleeding, charmed)
    evolution_after_action(actor, target, skill, hit, evolved)
    after_action(
        actor,
        target,
        skill,
        hit,
        damage,
        critical,
        obeyed,
        previous_negatives,
        skills or BUILTIN_SKILLS,
        rng,
    )
    arch_notes = arch_after_action(
        actor, target, skill, hit, skills or BUILTIN_SKILLS, rng
    )
    self_damage = revenge_recoil(actor, min(before[other]["hp"], damage))
    # Damage-over-time ticks when the affected fighter is about to act, including
    # a stunned turn. It cannot be avoided by using a utility skill.
    bleed_damage = min(
        target["hp"],
        sum(max(0, int(e["value"])) for e in target["effects"] if e["kind"] == "bleed"),
    )
    if target["hp"] > 0:
        target["hp"] -= bleed_damage
    text = f"{skill.name}: " + (
        f"−{damage} HP"
        if damage
        else ("эффект применён" if hit else "уклонение" if dodged else "промах")
    )
    if effects_text:
        text += " · " + ", ".join(effects_text)
    if hit and critical:
        text += " · критический удар"
    if obeyed:
        text += " · предписание исполнено"
    if bleed_damage:
        text += f" · кровотечение: −{bleed_damage} HP"
    if self_damage:
        text += f" · самоурон: −{self_damage} HP"
    if order_note:
        text += " · " + order_note
    if arch_notes:
        text += " · " + " · ".join(arch_notes)
    event = {
        "seq": state["turn"],
        "side": side_key,
        "skill_id": skill_id,
        "skill_name": skill.name,
        "evolved": evolved,
        "damage_type": skill.damage_type,
        "hit": hit,
        "dodged": dodged,
        "damage": damage,
        "critical": bool(hit and critical),
        "bleed_damage": bleed_damage,
        "self_damage": self_damage,
        "text": text,
        "before": before,
        "after": {
            k: {"hp": s["hp"], "resource": s["resource"]}
            for k, s in state["sides"].items()
        },
        "status_after": battle_status_snapshot(state),
    }
    state["log"].append(event)
    state["log"] = state["log"][-60:]
    _advance_turn(state, side_key)
    return event


def use_healing_potion(state: dict, side_key: str) -> None:
    side = state["sides"][side_key]
    if (
        state["finished"]
        or side["potion_used"]
        or side["hp"] >= side["stats"]["max_hp"]
    ):
        raise ValueError("Зелье сейчас нельзя использовать.")
    side["hp"] = min(
        side["stats"]["max_hp"],
        side["hp"] + max(1, round(side["stats"]["max_hp"] * 0.3)),
    )
    side["potion_used"] = True
