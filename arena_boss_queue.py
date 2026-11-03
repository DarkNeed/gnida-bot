"""Cast scheduling for scripted raids; boss scripts remain the authority.

The queue pauses at actual attack times, not at each player's submission. Native
boss handlers still own phases, summons, resource costs and special reactions.
"""
from copy import deepcopy
import random
import secrets

from arena_action_queue import COLORS, entries


def _signature(data):
    m = data.get('nazarick', {})
    return [m.get('stage'), m.get('phase')]


def _enemies(data):
    return data.get('enemies') or {'boss': data['boss']}


def _intents(data):
    return data.get('enemy_intents') or {'boss': data['intent']}


def _players(data, keys, skills, rng):
    if data['boss_id'] == 'nazarick':
        from arena_nazarick import resolve
        resolve(data, skills, rng, actor_keys=keys, enemy_keys=[], complete=False)
    else:
        from arena_raid_engine import _resolve_round_legacy
        _resolve_round_legacy(data, skills, rng, actor_keys=keys, defer_boss=True)


def _prepare(data, keys, skills, rng):
    """Cancel defeated/interrupted casts before asking anyone for a defense."""
    from arena_raid_engine import alive_players, finish_if_needed
    if not keys:
        return []
    if data['boss_id'] == 'nazarick':
        from arena_nazarick import progress
        if progress(data) or _signature(data) != data['_cast_queue']['signature']:
            return []
    elif data['boss_id'] == 'chaplain':
        from arena_chaplain import transition
        transition(data)
    if finish_if_needed(data) or data.get('_chaplain_transitioned') or data.get('_chaplain_rewound'):
        return []
    released = []
    for key in keys:
        enemy, intent = _enemies(data).get(key), _intents(data).get(key)
        if not enemy or enemy['hp'] <= 0 or not intent:
            continue
        # Non-attack boss actions still have an initiative slot, but no QTE.
        hostile = skills.get(intent.get('skill'))
        interrupted = (key == 'boss' and data.get('_queue_stunned') or
                       any(e['kind'] == 'stun' for e in enemy['effects']))
        targets = [str(k) for k in intent.get('targets', []) if str(k) in alive_players(data)]
        if interrupted or not hostile or not hostile.hostile:
            targets = []
        if data['boss_id'] == 'whaler' and intent.get('skill') == 'whaler_rot':
            # The ritual is interrupted by actions already completed at this time.
            if sum(data.get('whaler_restored', {}).values()) >= intent['ritual_target']:
                targets = []
        i = deepcopy(intent)
        i['targets'] = targets
        released.append(dict(source=key, fighter=deepcopy(enemy), intent=i))
    return released


def _land(data, released, guards, skills, rng):
    from arena_raid_engine import _finish_boss_round
    if not released:
        return
    for key, p in data['players'].items():
        per_source = guards.get(key, {})
        # Nazarick's native resolver consumes per-source guards; other scripted
        # bosses consume the same proof directly, including mixed-damage parts.
        if data['boss_id'] != 'nazarick':
            guard = per_source.get('boss')
            if guard:
                r = next(r for r in released if r['source'] == 'boss')
                from arena_qte_live import challenge
                descriptor = challenge('defense', r['fighter'], p['fighter'], skills[r['intent']['skill']], int(key))
                p['fighter']['_qte_guard'] = dict(guard, skill=r['intent']['skill'], subskills=descriptor.get('subskills'))
    try:
        if released and released[0].get('reaction'):
            from arena_whaler import attack
            original = data['intent']
            data['intent'] = released[0]['intent']
            data['_qte_boss_phase'] = True
            try:
                attack(data, 'whaler_punishment', released[0]['intent']['targets'], rng, reaction=True)
            finally:
                data['intent'] = original
                data.pop('_qte_boss_phase', None)
        elif data['boss_id'] == 'nazarick':
            from arena_nazarick import resolve
            resolve(data, skills, rng, actor_keys=[], enemy_keys=[r['source'] for r in released], complete=False,
                    defense_guards=guards)
        elif released:
            _finish_boss_round(data, skills, rng, data.get('_queue_stunned', False), complete=False)
        if any(r['source'] == 'boss' and not r.get('reaction') for r in released):
            data['_cast_queue']['boss_acted'] = True
            data['_cast_queue']['stun_consumed'] = data.get('_queue_stunned', False)
    finally:
        for p in data['players'].values():
            p['fighter'].pop('_qte_guard', None)


def _wait(data, released):
    from arena_raid_engine import alive_players
    targets = {k for r in released for k in r['intent']['targets']}
    eligible = sorted(k for k in targets if k in alive_players(data) and data.get('qte_modes', {}).get(k)
                      and data['players'][k]['selected'] is not None)
    if not eligible:
        return False
    data['_queue_wait'] = dict(id=secrets.token_hex(12), released=released, eligible=eligible, results={})
    return True


def advance(data, skills, rng=None):
    from arena_raid_engine import BOSS_SKILLS, alive_players, raid_snapshot, _finish_boss_round, finish_if_needed
    rng = rng or random.SystemRandom()
    catalog = {**BOSS_SKILLS, **skills}
    if data.get('finished'):
        raise ValueError('Рейд завершён.')
    if not data.get('_cast_queue'):
        data['_queue_stunned'] = data.pop('_pending_boss_stun', False)
        data['round_before'] = raid_snapshot(data)
        data['_cast_queue'] = dict(entries=entries(data, catalog), cursor=0, time=0, round=data['round'], signature=_signature(data))
        for key, p in alive_players(data).items():
            if p.get('intercept_source'):
                p['fighter']['resource'] -= min(8, p['fighter']['resource'])
                from arena_raid_engine import log_event
                log_event(data, key, key, 'Перехват: −8 энергии.')
    queue = data['_cast_queue']
    pending = data.get('_queue_wait')
    if pending:
        if any(k not in pending['results'] for k in pending['eligible'] if k in alive_players(data)):
            return data
        _land(data, pending['released'], pending['results'], catalog, rng)
        data.pop('_queue_wait', None)
    while queue['cursor'] < len(queue['entries']):
        if finish_if_needed(data) or data.get('nazarick', {}).get('blessing_offer') or data.get('_chaplain_rewound'):
            break
        at = queue['entries'][queue['cursor']]['at']
        group = []
        while queue['cursor'] < len(queue['entries']) and queue['entries'][queue['cursor']]['at'] == at:
            group.append(queue['entries'][queue['cursor']])
            queue['cursor'] += 1
        queue['time'] = at
        _players(data, [e['actor'] for e in group if e['team'] == 'players'], skills, rng)
        released = _prepare(data, [e['actor'] for e in group if e['team'] == 'enemies'], catalog, rng)
        if _wait(data, released):
            return data
        _land(data, released, {}, catalog, rng)
    # A reactive punishment is not the boss's regular turn, and must not replay
    # that turn or spend/tick its resources twice when the defense is submitted.
    if data['boss_id'] == 'whaler' and not queue.get('reaction_checked') and not finish_if_needed(data):
        queue['reaction_checked'] = True
        from arena_whaler import prepare_reaction
        if prepare_reaction(data, rng, data.get('_queue_stunned', False)):
            reaction = data.pop('whaler_reaction')
            r = dict(source='boss', fighter=deepcopy(data['boss']), reaction=True,
                     intent=dict(kind='reaction', skill='whaler_punishment', targets=[reaction['target']]))
            if _wait(data, [r]):
                return data
            _land(data, [r], {}, catalog, rng)
    data['_last_cast_timeline'] = dict(round=data['round'], time=queue['time'], entries=deepcopy(queue['entries']),
        colors={k: COLORS[i % len(COLORS)] for i, k in enumerate([*data['players'], *_enemies(data)])})
    # Control arriving after the boss acted interrupts his NEXT cast.
    if queue.get('boss_acted') and data.get('_queue_stunned') and not queue.get('stun_consumed'):
        data['_pending_boss_stun'] = True
    # Finalization advances the round and restores resources exactly once.
    if data['boss_id'] == 'nazarick' and not data.get('finished'):
        from arena_nazarick import resolve
        resolve(data, skills, rng, actor_keys=[], enemy_keys=[], complete=True)
    elif data['boss_id'] != 'nazarick':
        _finish_boss_round(data, skills, rng, data.get('_queue_stunned', False), act=False)
    data.pop('_cast_queue', None)
    data.pop('_queue_stunned', None)
    data.pop('round_before', None)
    for p in data['players'].values():
        p.pop('qte_result', None)
        p.pop('intercept_source', None)
    return data
