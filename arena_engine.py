from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any, Iterable

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
            "max_hp": 58,
            "physical_attack": 15,
            "magic_attack": 4,
            "physical_defense": 14,
            "magic_defense": 8,
            "speed": 8,
            "evasion": 4,
        },
        {
            "max_hp": 6,
            "physical_attack": 1.8,
            "magic_attack": 0.3,
            "physical_defense": 1.5,
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
            "max_hp": 40,
            "physical_attack": 5,
            "magic_attack": 16,
            "physical_defense": 6,
            "magic_defense": 12,
            "speed": 6,
            "evasion": 3,
        },
        {
            "max_hp": 4,
            "physical_attack": 0.4,
            "magic_attack": 2,
            "physical_defense": 0.5,
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
            6,
            90,
            15,
            0,
            (effect("adoration", "damage_pct", -0.15, 2, chance=0.40),),
        ),
        Skill(
            "posing",
            "Позирование",
            "cutie",
            6,
            None,
            0,
            100,
            25,
            3,
            (effect("posing", "evasion_flat", 20, 3, target="self"),),
        ),
        Skill(
            "air_kiss",
            "Воздушный поцелуй",
            "cutie",
            7,
            "magic",
            10,
            85,
            25,
            1,
            (effect("adoration", "damage_pct", -0.15, 2, chance=0.45),),
        ),
        Skill("meow", "Мяу", "cutie", 9, "magic", 17, 80, 45, 2),
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
            10,
            88,
            20,
            1,
            (effect("humiliate_drain", "resource", -15),),
        ),
        Skill(
            "charging",
            "Зарядка",
            "nerd",
            6,
            None,
            0,
            100,
            40,
            4,
            (
                effect("charging_damage", "damage_pct", 0.25, 3, target="self"),
                effect("charging_speed", "speed_pct", 0.20, 3, target="self"),
            ),
        ),
        Skill(
            "doxxing",
            "Деанон",
            "nerd",
            7,
            None,
            0,
            90,
            25,
            3,
            (
                effect("doxxing_drain", "resource", -25),
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
            4,
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
        and (known is None or skill.skill_id in known)
    ]


def normalize_loadout(
    class_id: str,
    level: int,
    requested: Iterable[str] | None,
    skills: dict[str, Skill] | None = None,
    granted: Iterable[str] = (),
    known: Iterable[str] | None = None,
) -> list[str]:
    unlocked = unlocked_skill_ids(class_id, level, skills, granted, known)
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
            if item.get("kind") not in {"resource", "stun"}
        ]
        sides[side] = {
            "slave_id": int(source["slave_id"]),
            "owner_id": int(source["owner_id"]),
            "controller_id": int(
                source["owner_id"] if controlled else source["slave_id"]
            ),
            "controlled": controlled,
            "class_id": class_id,
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
            ),
            "effects": starting_effects,
            "passive_details": passive_details,
            "cooldowns": {},
            "potion_used": False,
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
    return max(0, value * max(0, 1 + pct) + flat)


def validate_skill(state: dict, side_key: str, skill_id: str, skills=None) -> Skill:
    catalog = skills or BUILTIN_SKILLS
    if state["finished"] or state["active_side"] != side_key:
        raise ValueError("Сейчас не ваш ход.")
    side = state["sides"][side_key]
    if (
        skill_id not in side["loadout"] and skill_id != "bum_punch"
    ) or skill_id not in catalog:
        raise ValueError("Навык недоступен.")
    skill = catalog[skill_id]
    if side["resource"] < skill.cost:
        raise ValueError("Недостаточно выносливости.")
    if side["cooldowns"].get(skill_id, 0) > 0:
        raise ValueError("Навык восстанавливается.")
    return skill


def _tick(side: dict) -> None:
    side["effects"] = [
        dict(e, duration=e["duration"] - 1)
        for e in side["effects"]
        if e["duration"] > 1
    ]
    side["cooldowns"] = {k: v - 1 for k, v in side["cooldowns"].items() if v > 1}
    # No automatic refund after a skill, including battles saved by older code.
    # Resource can still be restored by skills with an explicit resource effect.


def resolve_skill(
    state: dict, side_key: str, skill_id: str, skills=None, rng=None
) -> dict:
    """Resolve one tap entirely on the server. No directional/confirmation phase."""
    rng = rng or random.SystemRandom()
    skill = validate_skill(state, side_key, skill_id, skills)
    actor = state["sides"][side_key]
    other = "b" if side_key == "a" else "a"
    target = state["sides"][other]
    before = {
        k: {"hp": s["hp"], "resource": s["resource"]} for k, s in state["sides"].items()
    }
    accuracy_bonus = sum(
        e.get("value", 0) for e in actor["effects"] if e.get("kind") == "accuracy_flat"
    )
    hit = not skill.hostile or rng.random() * 100 < max(
        5, min(95, skill.accuracy + accuracy_bonus - effective_stat(target, "evasion"))
    )
    actor["resource"] -= skill.cost
    damage = 0
    if hit and skill.damage_type:
        attack = effective_stat(actor, skill.damage_type + "_attack")
        defense = effective_stat(target, skill.damage_type + "_defense")
        boost = sum(
            e.get("value", 0) for e in actor["effects"] if e.get("kind") == "damage_pct"
        )
        damage = max(
            1,
            round(
                skill.power
                * (1 + attack / 20)
                * 100
                / (100 + defense * 4)
                * max(0.1, 1 + boost)
                * rng.uniform(0.95, 1.05)
            ),
        )
        target["hp"] = max(0, target["hp"] - damage)
    # Existing buffs expire after this action, before newly applied buffs are added.
    _tick(actor)
    effects_text = []
    if hit:
        for effect in skill.effects:
            if rng.random() >= effect.get("chance", 1):
                continue
            recipient = target if effect.get("target") == "enemy" else actor
            if effect["kind"] == "resource":
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
            label = {
                "accuracy_flat": "точность",
                "damage_pct": "урон",
                "speed_pct": "скорость",
                "physical_defense_pct": "защита",
                "magic_defense_pct": "маг. защита",
                "evasion_flat": "уклонение",
                "resource": "ресурс",
                "stun": "ошеломление",
            }.get(effect["kind"], effect["kind"])
            effects_text.append(label)
    if skill.cooldown:
        actor["cooldowns"][skill_id] = skill.cooldown
    text = f"{skill.name}: " + (
        f"−{damage} HP" if damage else ("эффект применён" if hit else "промах")
    )
    if effects_text:
        text += " · " + ", ".join(effects_text)
    event = {
        "seq": state["turn"],
        "side": side_key,
        "skill_id": skill_id,
        "skill_name": skill.name,
        "damage_type": skill.damage_type,
        "hit": hit,
        "damage": damage,
        "text": text,
        "before": before,
        "after": {
            k: {"hp": s["hp"], "resource": s["resource"]}
            for k, s in state["sides"].items()
        },
    }
    state["log"].append(event)
    state["log"] = state["log"][-60:]
    state["turn"] += 1
    state["active_side"] = other
    if target["hp"] <= 0:
        state.update(finished=True, winner=side_key)
    elif state["turn"] > 200:
        state.update(finished=True, winner=None)
    elif any(e["kind"] == "stun" for e in target["effects"]):
        _tick(target)
        state["log"].append(
            {
                "seq": state["turn"],
                "side": other,
                "text": "Ошеломление: ход пропущен.",
                "damage": 0,
                "hit": False,
            }
        )
        state["turn"] += 1
        state["active_side"] = side_key
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
