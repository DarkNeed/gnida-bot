"""Built-in PvE opponents; author-exclusive content is never added to the pool."""

import random

from arena_engine import (
    FIGHTER_CLASSES,
    BUILTIN_SKILLS,
    MAX_ACTIVE_SKILLS,
    MAX_FIGHTER_LEVEL,
)


def victory_xp(enemy_level: int) -> int:
    """Reward the saved opponent's level, not an unbounded floor number."""
    return 5 + 2 * max(1, min(MAX_FIGHTER_LEVEL, int(enemy_level)))


def enemy_source(level: int, previous_class: str | None = None, rng=None) -> dict:
    rng = rng or random.SystemRandom()
    level = max(1, min(MAX_FIGHTER_LEVEL, int(level)))
    pool = [key for key, cls in FIGHTER_CLASSES.items() if cls.base_level <= level]
    if len(pool) > 1 and previous_class in pool:
        pool.remove(previous_class)
    class_id = rng.choice(pool)
    native = [
        s.skill_id
        for s in BUILTIN_SKILLS.values()
        if s.class_id == class_id and s.unlock_level <= level
    ]
    # At least one attack, then varied native skills rather than always the
    # first four low-level skills. Fill remaining slots with inherited skills.
    attacks = [key for key in native if BUILTIN_SKILLS[key].damage_type]
    loadout = [rng.choice(attacks)]
    remaining = [key for key in native if key not in loadout]
    loadout += rng.sample(remaining, min(len(remaining), MAX_ACTIVE_SKILLS - 1))
    inherited = [
        s.skill_id
        for s in BUILTIN_SKILLS.values()
        if s.class_id == "ragamuffin"
        and s.unlock_level <= level
        and s.skill_id not in loadout
    ]
    loadout += inherited[: MAX_ACTIVE_SKILLS - len(loadout)]
    return dict(
        slave_id=0,
        owner_id=0,
        controlled=False,
        class_id=class_id,
        level=level,
        loadout=loadout,
    )
