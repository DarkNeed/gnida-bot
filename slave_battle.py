from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Iterable


BASE_RESOURCE = 100
BASE_RESOURCE_REGEN = 15
CONTROL_PENALTY = 0.8
MAX_ACTIVE_SKILLS = 4
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
    if normalized_stats["max_hp"] <= 0 or any(value < 0 for value in normalized_stats.values()):
        raise ValueError("class stats cannot be negative")
    passives = payload.get("passives", [])
    if not isinstance(passives, list):
        raise ValueError("passives must be an array")
    return FighterClass(
        class_id=class_id,
        name=str(payload["name"]).strip(),
        resource_name=str(payload.get("resource_name", "Выносливость")).strip(),
        base_level=max(1, int(payload.get("base_level", 5))),
        base_stats=normalized_stats,
        growth=normalized_growth,
        passives=tuple(dict(item) for item in passives if isinstance(item, dict)),
    )


def skill_from_dict(skill_id: str, payload: dict[str, Any]) -> Skill:
    """Build a custom skill using the same bounded primitives as built-ins."""
    damage_type = payload.get("damage_type")
    if damage_type not in {None, "physical", "magic"}:
        raise ValueError("damage_type must be physical, magic or null")
    effects = payload.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError("effects must be an array")
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
    )


def xp_for_next_level(level: int) -> int:
    return math.ceil(10 * (1.4 ** max(0, level - 1)))


def level_from_total_xp(total_xp: int) -> int:
    level = 1
    remaining = max(0, total_xp)
    while remaining >= xp_for_next_level(level):
        remaining -= xp_for_next_level(level)
        level += 1
    return level


def level_progress(total_xp: int) -> tuple[int, int, int]:
    level = 1
    remaining = max(0, total_xp)
    while remaining >= xp_for_next_level(level):
        remaining -= xp_for_next_level(level)
        level += 1
    return level, remaining, xp_for_next_level(level)


def stats_for(
    class_id: str,
    level: int,
    controlled: bool = False,
    classes: dict[str, FighterClass] | None = None,
) -> dict[str, float]:
    catalog = classes or FIGHTER_CLASSES
    fighter_class = catalog.get(class_id, FIGHTER_CLASSES["ragamuffin"])
    effective_level = max(fighter_class.base_level, level)
    delta = effective_level - fighter_class.base_level
    stats = {
        key: round(value + fighter_class.growth.get(key, 0) * delta, 2)
        for key, value in fighter_class.base_stats.items()
    }
    stats["resource_max"] = BASE_RESOURCE
    stats["resource_regen"] = BASE_RESOURCE_REGEN
    if controlled:
        stats = {key: round(value * CONTROL_PENALTY, 2) for key, value in stats.items()}
    return stats


def unlocked_skill_ids(
    class_id: str,
    level: int,
    skills: dict[str, Skill] | None = None,
    granted: Iterable[str] = (),
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
        if (skill.class_id in allowed_classes or skill.skill_id in granted)
        and skill.unlock_level <= level
    ]


def normalize_loadout(
    class_id: str,
    level: int,
    requested: Iterable[str] | None,
    skills: dict[str, Skill] | None = None,
    granted: Iterable[str] = (),
) -> list[str]:
    unlocked = unlocked_skill_ids(class_id, level, skills, granted)
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
        starting_effects = {
            str(item.get("id", f"passive_{index}")): {
                **item,
                "turns": 1_000_000,
            }
            for index, item in enumerate(fighter_class.passives)
            if item.get("kind") not in {"resource", "stun"}
        }
        sides[side] = {
            "slave_id": int(source["slave_id"]),
            "owner_id": int(source["owner_id"]),
            "controller_id": int(
                source["owner_id"] if controlled else source["slave_id"]
            ),
            "controlled": controlled,
            "class_id": class_id,
            "level": int(source["level"]),
            "stats": stats,
            "hp": stats["max_hp"],
            "resource": stats["resource_max"],
            "loadout": normalize_loadout(
                class_id,
                int(source["level"]),
                source.get("loadout"),
                skill_catalog,
                source.get("granted_skills", ()),
            ),
            "effects": starting_effects,
            "cooldowns": {},
            "potion_used": False,
        }
    return {
        "turn": 1,
        "sides": sides,
        "log": [],
        "winner": None,
        "finished": False,
        # New battles use a Pokémon-like sequence: one fighter picks a move,
        # then the opponent chooses where to dodge that move.
        "flow": "sequential",
        "phase": "skill",
        "active_side": "a",
        "pending_action": None,
    }


def _effect_sum(fighter: dict[str, Any], kind: str) -> float:
    return sum(
        float(active.get("value", 0))
        for active in fighter["effects"].values()
        if active.get("kind") == kind
    )


def effective_stat(fighter: dict[str, Any], stat: str) -> float:
    value = float(fighter["stats"][stat])
    if stat == "speed":
        value *= 1 + _effect_sum(fighter, "speed_pct")
    elif stat == "physical_defense":
        value *= 1 + _effect_sum(fighter, "physical_defense_pct")
    elif stat == "magic_defense":
        value *= 1 + _effect_sum(fighter, "magic_defense_pct")
    elif stat == "evasion":
        value += _effect_sum(fighter, "evasion_flat")
    return max(0, value)


def _skill_hit_chance(
    skill: Skill,
    attacker: dict[str, Any],
    defender: dict[str, Any],
    attack_direction: str,
    dodge_direction: str,
) -> float:
    chance = (
        float(skill.accuracy)
        + _effect_sum(attacker, "accuracy_flat")
        - effective_stat(defender, "evasion")
    )
    chance = min(95.0, max(20.0, chance))
    chance *= 0.6 if attack_direction == dodge_direction else 1.1
    return min(95.0, max(5.0, chance))


def _damage(
    skill: Skill,
    attacker: dict[str, Any],
    defender: dict[str, Any],
    rng: random.Random,
) -> int:
    attack_stat = "physical_attack" if skill.damage_type == "physical" else "magic_attack"
    defense_stat = (
        "physical_defense" if skill.damage_type == "physical" else "magic_defense"
    )
    attack = effective_stat(attacker, attack_stat)
    defense = effective_stat(defender, defense_stat)
    modifier = 1 + _effect_sum(attacker, "damage_pct")
    raw = skill.power * (1 + attack / 20) * (100 / (100 + defense * 4))
    return max(1, round(raw * modifier * rng.uniform(0.95, 1.05)))


def _tick_existing_effects(state: dict[str, Any]) -> None:
    for fighter in state["sides"].values():
        expired: list[str] = []
        for effect_id, active in fighter["effects"].items():
            active["turns"] = int(active.get("turns", 0)) - 1
            if active["turns"] <= 0:
                expired.append(effect_id)
        for effect_id in expired:
            fighter["effects"].pop(effect_id, None)
        for skill_id in tuple(fighter["cooldowns"]):
            fighter["cooldowns"][skill_id] = max(
                0, int(fighter["cooldowns"][skill_id]) - 1
            )
            if not fighter["cooldowns"][skill_id]:
                fighter["cooldowns"].pop(skill_id, None)


def validate_action(
    state: dict[str, Any],
    side: str,
    action: dict[str, Any],
    skills: dict[str, Skill] | None = None,
) -> str | None:
    catalog = skills or BUILTIN_SKILLS
    fighter = state["sides"].get(side)
    if not fighter or state.get("finished"):
        return "Бой уже завершён."
    skill_id = str(action.get("skill_id", ""))
    if skill_id not in fighter["loadout"] or skill_id not in catalog:
        return "Этот навык не экипирован."
    skill = catalog[skill_id]
    if fighter["resource"] < skill.cost:
        return f"Недостаточно ресурса для навыка «{skill.name}»."
    if int(fighter["cooldowns"].get(skill_id, 0)) > 0:
        return f"Навык «{skill.name}» ещё перезаряжается."
    if action.get("dodge_direction") not in {"left", "right"}:
        return "Выберите направление уклонения."
    if skill.hostile and action.get("attack_direction") not in {"left", "right"}:
        return "Выберите направление атаки."
    return None


def validate_skill_action(
    state: dict[str, Any],
    side: str,
    action: dict[str, Any],
    skills: dict[str, Skill] | None = None,
) -> str | None:
    """Validate a move before the defender chooses its dodge direction."""
    catalog = skills or BUILTIN_SKILLS
    fighter = state["sides"].get(side)
    if not fighter or state.get("finished"):
        return "Бой уже завершён."
    skill_id = str(action.get("skill_id", ""))
    if skill_id not in fighter["loadout"] or skill_id not in catalog:
        return "Этот навык не экипирован."
    skill = catalog[skill_id]
    if fighter["resource"] < skill.cost:
        return f"Недостаточно ресурса для навыка «{skill.name}»."
    if int(fighter["cooldowns"].get(skill_id, 0)) > 0:
        return f"Навык «{skill.name}» ещё перезаряжается."
    if skill.hostile and action.get("attack_direction") not in {"left", "right"}:
        return "Выберите направление атаки."
    return None


def resolve_skill_action(
    state: dict[str, Any],
    side: str,
    action: dict[str, Any],
    dodge_direction: str | None = None,
    rng: random.Random | None = None,
    skills: dict[str, Skill] | None = None,
) -> dict[str, Any]:
    """Resolve one declared move and leave the next move to the other fighter."""
    catalog = skills or BUILTIN_SKILLS
    rng = rng or random.Random()
    error = validate_skill_action(state, side, action, catalog)
    if error:
        raise ValueError(error)
    other_side = "b" if side == "a" else "a"
    fighter = state["sides"][side]
    target = state["sides"][other_side]
    skill = catalog[str(action["skill_id"])]
    if skill.hostile and dodge_direction not in {"left", "right"}:
        raise ValueError("Выберите направление уклонения.")

    event: str
    pending_effects: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if fighter["hp"] <= 0:
        event = f"{side}: не может действовать"
    elif "stun" in fighter["effects"]:
        event = f"{side}: пропускает действие из-за ошеломления"
    else:
        fighter["resource"] = max(0, fighter["resource"] - skill.cost)
        if skill.cooldown:
            fighter["cooldowns"][skill.skill_id] = skill.cooldown + 1
        hit = True
        if skill.hostile:
            hit_chance = _skill_hit_chance(
                skill, fighter, target, str(action["attack_direction"]), str(dodge_direction)
            )
            hit = rng.random() * 100 < hit_chance
        if not hit:
            event = f"{side}: {skill.name} — промах"
        else:
            dealt = 0
            if skill.damage_type:
                dealt = _damage(skill, fighter, target, rng)
                target["hp"] = max(0, target["hp"] - dealt)
            for configured in skill.effects:
                recipient = fighter if configured.get("target") == "self" else target
                if rng.random() > float(configured.get("chance", 1)):
                    continue
                kind = str(configured["kind"])
                if kind == "resource":
                    recipient["resource"] = min(
                        recipient["stats"]["resource_max"],
                        max(0, recipient["resource"] + float(configured["value"])),
                    )
                elif kind == "stun":
                    if "stun_immunity" not in recipient["effects"]:
                        pending_effects.append((recipient, {**configured, "turns": 1}))
                        pending_effects.append((recipient, {"id": "stun_immunity", "kind": "immunity", "value": 1, "turns": 3}))
                elif int(configured.get("turns", 0)) > 0:
                    pending_effects.append((recipient, dict(configured)))
            event = f"{side}: {skill.name}" + (f", урон {dealt}" if dealt else "")

    _tick_existing_effects(state)
    for recipient, configured in pending_effects:
        recipient["effects"][str(configured["id"])] = configured
    for item in state["sides"].values():
        item["resource"] = min(item["stats"]["resource_max"], item["resource"] + item["stats"]["resource_regen"])
    state["log"] = (state.get("log", []) + [{"turn": state["turn"], "events": [event]}])[-12:]
    alive = [item for item in ("a", "b") if state["sides"][item]["hp"] > 0]
    if len(alive) == 1:
        state["winner"] = alive[0]
        state["finished"] = True
    elif not alive:
        state["winner"] = "draw"
        state["finished"] = True
    state["turn"] += 1
    return state


def resolve_turn(
    state: dict[str, Any],
    actions: dict[str, dict[str, Any]],
    rng: random.Random | None = None,
    skills: dict[str, Skill] | None = None,
) -> dict[str, Any]:
    catalog = skills or BUILTIN_SKILLS
    rng = rng or random.Random()
    for side in ("a", "b"):
        error = validate_action(state, side, actions.get(side, {}), catalog)
        if error:
            raise ValueError(error)

    turn_log: list[str] = []
    pending_effects: list[tuple[dict[str, Any], dict[str, Any]]] = []
    order = ["a", "b"]
    rng.shuffle(order)
    order.sort(key=lambda side: effective_stat(state["sides"][side], "speed"), reverse=True)

    for side in order:
        other_side = "b" if side == "a" else "a"
        fighter = state["sides"][side]
        target = state["sides"][other_side]
        if fighter["hp"] <= 0 or target["hp"] <= 0:
            continue
        if "stun" in fighter["effects"]:
            turn_log.append(f"{side}: пропускает действие из-за ошеломления")
            continue
        action = actions[side]
        skill = catalog[str(action["skill_id"])]
        fighter["resource"] = max(0, fighter["resource"] - skill.cost)
        if skill.cooldown:
            fighter["cooldowns"][skill.skill_id] = skill.cooldown + 1

        hit = True
        if skill.hostile:
            hit_chance = _skill_hit_chance(
                skill,
                fighter,
                target,
                str(action["attack_direction"]),
                str(actions[other_side]["dodge_direction"]),
            )
            hit = rng.random() * 100 < hit_chance
        if not hit:
            turn_log.append(f"{side}: {skill.name} — промах")
            continue

        dealt = 0
        if skill.damage_type:
            dealt = _damage(skill, fighter, target, rng)
            target["hp"] = max(0, target["hp"] - dealt)
        for configured in skill.effects:
            recipient = fighter if configured.get("target") == "self" else target
            if rng.random() > float(configured.get("chance", 1)):
                continue
            kind = str(configured["kind"])
            if kind == "resource":
                recipient["resource"] = min(
                    recipient["stats"]["resource_max"],
                    max(0, recipient["resource"] + float(configured["value"])),
                )
            elif kind == "stun":
                if "stun_immunity" not in recipient["effects"]:
                    pending_effects.append(
                        (recipient, {**configured, "turns": 1})
                    )
                    pending_effects.append(
                        (
                            recipient,
                            {
                                "id": "stun_immunity",
                                "kind": "immunity",
                                "value": 1,
                                "turns": 3,
                            },
                        )
                    )
            elif int(configured.get("turns", 0)) > 0:
                pending_effects.append((recipient, dict(configured)))
        suffix = f", урон {dealt}" if dealt else ""
        turn_log.append(f"{side}: {skill.name}{suffix}")

    _tick_existing_effects(state)
    for recipient, configured in pending_effects:
        recipient["effects"][str(configured["id"])] = configured
    for fighter in state["sides"].values():
        fighter["resource"] = min(
            fighter["stats"]["resource_max"],
            fighter["resource"] + fighter["stats"]["resource_regen"],
        )

    state["log"] = (state.get("log", []) + [
        {"turn": state["turn"], "events": turn_log}
    ])[-12:]
    alive = [side for side in ("a", "b") if state["sides"][side]["hp"] > 0]
    if len(alive) == 1:
        state["winner"] = alive[0]
        state["finished"] = True
    elif not alive:
        state["winner"] = "draw"
        state["finished"] = True
    state["turn"] += 1
    return state


def use_healing_potion(state: dict[str, Any], side: str) -> int:
    fighter = state["sides"].get(side)
    if not fighter or state.get("finished"):
        raise ValueError("Бой уже завершён.")
    if fighter["potion_used"]:
        raise ValueError("Зелье в этом бою уже использовано.")
    maximum = float(fighter["stats"]["max_hp"])
    before = float(fighter["hp"])
    healed = max(0, round(maximum * 0.30))
    fighter["hp"] = min(maximum, before + healed)
    fighter["potion_used"] = True
    return round(fighter["hp"] - before)
