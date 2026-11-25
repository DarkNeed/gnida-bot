"""Direct-damage mitigation for a server-released group of simultaneous casts.

The queue has already grouped casts using its 0.5-second window. Count skills
per recipient, never projectiles, native strike groups or periodic effects.
"""
from contextlib import contextmanager


def damage_factor(count):
    return 1.0 if count < 2 else .9 if count == 2 else .8


def target_counts(released, skills):
    sources = {}
    for cast in released:
        skill = skills.get(cast['intent'].get('skill'))
        if not skill or not skill.hostile or not skill.damage_type or skill.power <= 0:
            continue
        for target in set(cast['intent'].get('targets', [])):
            sources.setdefault(target, set()).add(cast['source'])
    return {key: len(value) for key, value in sources.items()}


@contextmanager
def incoming_group(data, released, skills):
    fighters = data.get('sides') or {
        **{key: p['fighter'] for key, p in data['players'].items()},
        **(data.get('enemies') or {'boss': data['boss']}),
    }
    saved = []
    counts = target_counts(released, skills)
    if data.get('unified_version') == 3 and any(key.startswith('brood:') for key in counts):
        from arena_summons import troop
        fighters = {**fighters, **troop(data)}
    for key, count in counts.items():
        if key not in fighters:
            continue
        fighter = fighters[key]
        saved.append((fighter, fighter.get('_simultaneous_incoming')))
        fighter['_simultaneous_incoming'] = damage_factor(count)
    try:
        yield
    finally:
        for fighter, previous in saved:
            if previous is None:
                fighter.pop('_simultaneous_incoming', None)
            else:
                fighter['_simultaneous_incoming'] = previous


def direct_damage(target, amount):
    """Round once per skill's total, before shields; never touches DOTs."""
    import math
    factor = target.get('_simultaneous_incoming', 1)
    return max(0, math.floor(amount * factor + .5))
