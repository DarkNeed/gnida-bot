"""Shared completion-time rules for all newly created live battles.

Every active skill has a duration, including custom and standalone boss skills.
Explicit cast_base overrides the role-based default; speed is sampled at cast start.
"""
import math

SIMULTANEOUS_WINDOW = .5


def base_duration(skill):
    if skill.cast_base is not None:
        return max(.75, float(skill.cast_base))
    explicit = {'arch_assassin_shadow': 2.65, 'arch_assassin_blood': 3.4}
    if skill.skill_id in explicit:
        return explicit[skill.skill_id]
    tags = set(skill.tags)
    if 'six_strike' in tags:
        base = 4.8
    elif 'three_strike' in tags or 'triple_strike' in tags:
        base = 3.8
    elif 'two_strike' in tags:
        base = 3.3
    elif skill.hostile:
        base = 2.2 + min(2, max(0, skill.power) * .025) + min(.8, max(0, skill.cost) * .012)
    else:
        kinds = {e['kind'] for e in skill.effects}
        base = 2.4 if kinds & {'heal', 'heal_pct', 'resource', 'resource_leech'} else 2.0
        base += min(.9, max(0, skill.cost) * .015)
    if 'quick' in tags:
        base *= .75
    if 'once_per_battle' in tags:
        base += .5
    return round(min(6, max(.9, base)), 2)


def duration(fighter, skill):
    from arena_engine import effective_stat
    value = base_duration(skill) / (1 + max(0, effective_stat(fighter, 'speed')) * .035)
    return max(.75, math.floor(value * 20 + .5) / 20)


def forecast(now, duration, enemy_end):
    finish = round(now + duration, 3)
    remaining = round(enemy_end - finish, 3) if enemy_end is not None else None
    return dict(end=finish, remaining=remaining,
                outcome='none' if remaining is None else 'together' if abs(remaining) <= SIMULTANEOUS_WINDOW + 1e-9
                else 'before' if remaining > 0 else 'after')


def schedule(queue, actor, skill, target, duration):
    if any(e['actor'] == actor for e in queue['pending']):
        raise ValueError('У этого бойца уже готовится действие.')
    event = dict(actor=actor, skill=skill, target=target, start=queue['time'],
                 duration=duration, end=round(queue['time'] + duration, 3))
    queue['pending'].append(event)
    return event


def release(queue):
    if not queue['pending']:
        return []
    at = min(e['end'] for e in queue['pending'])
    # Anchor to the earliest cast, not a transitive chain of near neighbours.
    # Settle at the last included completion: no attack fires before its cast ends.
    group = [e for e in queue['pending'] if e['end'] - at <= SIMULTANEOUS_WINDOW + 1e-9]
    queue['time'] = max(e['end'] for e in group)
    queue['pending'] = [e for e in queue['pending'] if e not in group]
    return group
