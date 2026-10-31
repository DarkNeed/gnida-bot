"""Built-in PvE opponents; author-exclusive content is never added to the pool."""

import random
from arena_archclasses import branch_options, ARCHCLASS_LEVEL
from arena_archprogress import branch_skill_allowed
from arena_mastery import skill_allowed as mastery_allowed

from arena_engine import (
    FIGHTER_CLASSES,
    BUILTIN_SKILLS,
    MAX_ACTIVE_SKILLS,
    MAX_FIGHTER_LEVEL,
)


def victory_xp(enemy_level: int) -> int:
    """Reward the saved opponent's level, not an unbounded floor number."""
    return 5 + 2 * max(1, min(MAX_FIGHTER_LEVEL, int(enemy_level)))


def enemy_source(level: int, previous_class: str | None = None, rng=None, *, enabled_classes=None) -> dict:
    rng = rng or random.SystemRandom()
    level = max(1, min(MAX_FIGHTER_LEVEL, int(level)))
    pool = [key for key, cls in FIGHTER_CLASSES.items() if key!='gambler' and cls.base_level <= level and (enabled_classes is None or key in enabled_classes)]
    if not pool:
        pool = ['ragamuffin']
    if len(pool) > 1 and previous_class in pool:
        pool.remove(previous_class)
    class_id = rng.choice(pool)
    archclass_id = (
        rng.choice(branch_options(class_id))["id"]
        if level >= ARCHCLASS_LEVEL and branch_options(class_id)
        else ""
    )
    native = [
        s.skill_id
        for s in BUILTIN_SKILLS.values()
        if s.class_id == class_id
        and s.unlock_level <= level
        and branch_skill_allowed(s, archclass_id, level)
        and mastery_allowed(s,dict(class_id=class_id,level=level,archclass_id=archclass_id))
        and 'raid_loot' not in s.tags
    ]
    # At least one attack, then varied native skills rather than always the
    # first four low-level skills. Foreign-class filler is never added.
    attacks = [key for key in native if BUILTIN_SKILLS[key].damage_type]
    signature = ['arch_'+archclass_id] if 'arch_'+archclass_id in attacks else []
    loadout = signature or [rng.choice(attacks)]
    # Finishers need their native setup. Never generate an unusable moon hunter
    # or a necromancer without the summon that produces Souls.
    setups = {'hunter':['hunter_shot','hunter_cut'], 'mage':['mana_focus','mana_shot'],
              'warrior':['armor_split'], 'priest':['light_word']}
    if level >= 15:
        loadout += [sid for sid in setups.get(class_id, []) if sid in native and sid not in loadout]
    cheap = [sid for sid in attacks if BUILTIN_SKILLS[sid].cost <= 15 and sid not in loadout]
    if cheap and len(loadout) < MAX_ACTIVE_SKILLS and not any(BUILTIN_SKILLS[sid].damage_type and BUILTIN_SKILLS[sid].cost <= 15 for sid in loadout):
        loadout.append(rng.choice(cheap))
    remaining = [key for key in native if key not in loadout]
    loadout += rng.sample(remaining, min(len(remaining), MAX_ACTIVE_SKILLS - len(loadout)))
    inherited = [
        s.skill_id
        for s in BUILTIN_SKILLS.values()
        if class_id == 'ragamuffin' and s.class_id == "ragamuffin"
        and s.unlock_level <= level
        and s.skill_id not in loadout
        and not any(t.startswith('mastery:') for t in s.tags)
    ]
    loadout += inherited[: MAX_ACTIVE_SKILLS - len(loadout)]
    return dict(
        slave_id=0,
        owner_id=0,
        controlled=False,
        native_enemy=True,
        class_id=class_id,
        archclass_id=archclass_id,
        archclass_stage=20 if level >= 20 else 10,
        progression_level=20 if level >= 20 else 10 if level >= 10 else 5,
        level=level,
        npc_tier=2 if level >= 18 else 1 if level >= 12 else 0,
        loadout=loadout,
    )
