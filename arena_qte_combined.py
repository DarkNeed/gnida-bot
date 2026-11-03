"""One input stream, independent native attack patterns; server-owned sources only."""
from copy import deepcopy
import math
import secrets

HZ = 120


def duration(stage):
    from arena_qte_patterns import duration as native_duration, profile
    from arena_nazarick_patterns import block_duration
    return max(block_duration(profile(m['profile'])) if m.get('version') == 3
               else native_duration(m) for m in stage['members'])


def combine(members, actor, hp):
    if not 1 <= len(members) <= 8 or len({m['encounter_enemy'] for m in members}) != len(members):
        raise ValueError('Некорректные источники совместной защиты.')
    modes = {m.get('defense_mode', 'dodge') for m in members}
    if len(modes) != 1:
        raise ValueError('У одного бойца должен быть один режим защиты.')
    result = dict(version=4, kind='defense', id=secrets.token_hex(16), actor=actor,
                  name=' + '.join(m['name'] for m in members), members=deepcopy(members),
                  strikes=sum(m['strikes'] for m in members), target_hp=hp,
                  defense_mode=modes.pop())
    result['duration'] = duration(result)
    return result


def replay(stage, proof, elapsed):
    from arena_qte_rules import number, replay as native_replay
    from arena_qte_patterns import defense, profile, defense_step
    from arena_qte_block import create as block_create, step as block_step
    if not isinstance(proof, dict):
        raise ValueError('Нет записи совместной защиты.')
    members = stage['members']
    if proof.get('abort') is True:
        return dict(sources={m['encounter_enemy']: dict(dodge=(r := native_replay(m, proof, elapsed))['mask'],
                   pattern_dodge=r) for m in members})
    total = math.ceil(duration(stage) * HZ - 1e-7)
    if type(proof.get('ticks')) is not int or proof['ticks'] != total or elapsed + .15 < total / HZ:
        raise ValueError('Совместную защиту нужно пройти полностью.')
    events = proof.get('inputs')
    if not isinstance(events, list) or len(events) > total:
        raise ValueError('Слишком длинная запись управления.')
    block = stage['defense_mode'] == 'block'
    previous = -1
    for e in events:
        if not isinstance(e, dict) or type(e.get('t')) is not int or not previous < e['t'] < total:
            raise ValueError('Нарушен порядок управления.')
        previous = e['t']
        if block:
            if type(e.get('active')) is not bool:
                raise ValueError('Некорректное состояние щита.')
            number(e.get('angle'), -math.pi, math.pi)
        elif 'target' in e:
            if not isinstance(e['target'], list) or len(e['target']) != 2:
                raise ValueError('Некорректная цель движения.')
            number(e['target'][0], 0, 720)
            number(e['target'][1], 0, 320)
        else:
            number(e.get('x', 0), -1, 1)
            number(e.get('y', 0), -1, 1)
    totals = [math.ceil(_member_duration(m) * HZ - 1e-7) for m in members] if not block else []
    states = [block_create(m) if block else defense(profile(m['profile']), m['stats'], m['seed'],
              m.get('enabled_strikes'), m.get('defense_preparation', 1)) for m in members]
    if block:
        # A single shield: rotation, drain and recovery are never multiplied.
        lead = max(range(len(members)), key=lambda i: members[i]['stats'].get('enemyAttack', 0))
        carrier = deepcopy(states[lead])
        carrier['events'] = sorted([dict(e, id=f'{i}/{e["id"]}') for i, s in enumerate(states)
                                    for e in s['events']], key=lambda e: e['at'])
    point = dict(x=360, y=160, r=6, vx=0, vy=0)
    index, control = 0, {}
    for tick in range(total):
        if index < len(events) and events[index]['t'] == tick:
            control, index = events[index], index + 1
        if block:
            block_step(carrier, control)
        else:
            moved = None
            for i, (m, s) in enumerate(zip(members, states)):
                if tick >= totals[i]:
                    continue
                s['player'] = dict(point)
                defense_step(s, control)
                if moved is None and s['time'] > s['preparation'] + 1e-8:
                    moved = dict(s['player'])
            if moved is not None:
                point = moved
    sources = {}
    for i, (m, s) in enumerate(zip(members, states)):
        contacts = ([dict(c, id=c['id'].split('/', 1)[1]) for c in carrier['contacts']
                     if c['id'].startswith(f'{i}/')] if block else s['contacts'])
        result = dict(mask=[not any(c['strike'] == j and (not block or c['weight'] > 0)
                                   for c in contacts) for j in range(m['strikes'])], contacts=contacts)
        if block:
            result['mode'] = 'block'
        sources[m['encounter_enemy']] = dict(dodge=result['mask'], pattern_dodge=result)
    return dict(sources=sources)


def _member_duration(m):
    from arena_qte_patterns import duration as native_duration
    return native_duration(m)
