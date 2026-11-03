"""Persistent completion-time scheduling for every live combat adapter.

The clock advances only when all ready humans have committed. QTE is a
server-replayed boundary at completion, never another source of combat time.
Legacy saves without unified_version keep their original engine.
"""
from copy import deepcopy
import random
import secrets

from arena_skill_timing import duration, forecast, schedule, release
from arena_action_queue import COLORS

VERSION = 3


def enabled(data):
    return data.get('unified_version') == VERSION


def roster(data):
    if 'sides' in data:
        return data['sides']
    return {**{k: p['fighter'] for k, p in data['players'].items()},
            **(data.get('enemies') or {'boss': data['boss']})}


def humans(data):
    if 'sides' in data:
        return [k for k, f in data['sides'].items() if f['controller_id'] > 0 and f['hp'] > 0]
    return [k for k, p in data['players'].items() if not p.get('withdrawn') and p['fighter']['hp'] > 0]


def clock(data):
    return data.setdefault('_unified', dict(time=0., pending=[], group=[], choices={}, actions=0))


def ready(data):
    q = clock(data)
    busy = {e['actor'] for e in q['pending'] + q['group']}
    return [k for k in humans(data) if k not in busy]


def choice(data, key):
    return clock(data)['choices'].setdefault(key, secrets.token_hex(12))


def pair(actor, target):
    from arena_raid_engine import pair_state
    return pair_state(actor, target)


def _enemy_ids(data):
    if 'sides' in data:
        return [k for k, f in roster(data).items() if f['controller_id'] == 0]
    return list(data.get('enemies') or {'boss': data['boss']})


def _plan(data, skills):
    from arena_engine import effective_skill
    q, fighters = clock(data), roster(data)
    busy = {e['actor'] for e in q['pending'] + q['group']}
    for key in _enemy_ids(data):
        if key in busy or fighters[key]['hp'] <= 0 or not humans(data):
            continue
        if 'sides' in data:
            from arena_npc_ai import choose_skill
            target = 'a' if key == 'b' else 'b'
            sid = choose_skill(dict(pair(fighters[key], fighters[target]), active_side='a'), 'a', skills)
            intent = dict(kind='attack', skill=sid, targets=[target])
        else:
            intent = deepcopy((data.get('enemy_intents') or {'boss': data['intent']}).get(key, {}))
            sid = intent.get('skill')
            target = next((k for k in intent.get('targets', []) if k in humans(data)), humans(data)[0])
        skill = effective_skill(pair(fighters[key], fighters[target]), 'a', sid, skills) if sid in skills else None
        from arena_engine import Skill
        utility = Skill('queue_utility', 'Подготовка', 'universal', 1, None, 0, 100, 0, 0)
        event = schedule(q, key, sid, target, duration(fighters[key], skill or utility))
        event['intent'] = intent


def initialize(data, skills):
    clock(data)
    _plan(data, skills)
    for key in ready(data):
        choice(data, key)
    if 'sides' in data and ready(data):
        data['active_side'] = ready(data)[0]


def submit(data, key, sid, target, skills, *, ident=None, timeout=False):
    from arena_engine import validate_skill, Skill
    from arena_pets import pet_cost
    from arena_mirror_effects import gift_cost
    if not isinstance(sid, str):raise ValueError('Некорректный навык.')
    initialize(data, skills)
    if data.get('_queue_wait') or data.get('finished') or key not in ready(data):
        raise ValueError('У бойца уже готовится действие или идёт мини-игра.')
    if not timeout and ident != choice(data, key):
        raise ValueError('Выбор уже изменился. Обнови бой.')
    fighters = roster(data)
    if target not in fighters or fighters[target]['hp'] <= 0 or target == key:
        raise ValueError('Выбери живого противника.')
    actor = fighters[key]
    if sid == 'defend' or sid == 'potion' or sid.startswith('chaplain_anchor:'):
        if sid.startswith('chaplain_anchor:'):
            from arena_chaplain import validate_anchor
            validate_anchor(data, sid)
        skill = Skill(sid, 'Защита' if sid == 'defend' else 'Поддержка', 'universal', 1, None, 0, 100, 0, 0)
        cost = 0
    else:
        skill = validate_skill(pair(actor, fighters[target]), 'a', sid, skills)
        cost = pet_cost(actor, skill, gift_cost(actor, skill))
    if 'sides' not in data and data['players'][key].get('intercept_source'):
        if actor['resource'] < cost + 8:
            raise ValueError('Не хватает энергии с учётом перехвата.')
        actor['resource'] -= 8
        data['players'][key].pop('intercept_source', None)
    actor['resource'] -= cost
    event = schedule(clock(data), key, sid, target, duration(actor, skill))
    event.update(reserved=cost, timeout=timeout)
    clock(data)['choices'].pop(key, None)
    if 'sides' not in data:
        data['players'][key].update(selected=sid, selected_target=target)
    return event


def _log(data, key, target, text, **event):
    if 'sides' in data:
        from arena_engine import battle_status_snapshot
        side = key if key in data['sides'] else 'a'
        seq = max(data.get('event_seq', 0), data['log'][-1].get('seq', 0) if data['log'] else 0) + 1
        data['event_seq'] = seq
        data['log'].append(dict(seq=seq, side=side, text=text,
            status_after=battle_status_snapshot(data), **event))
    else:
        from arena_raid_engine import log_event
        log_event(data, key, target, text, **event)
        data['log'][-1]['cast_at'] = clock(data)['time']


def _finish(data):
    if 'sides' in data:
        alive = [k for k, f in data['sides'].items() if f['hp'] > 0]
        if len(alive) < 2:
            data.update(finished=True, winner=alive[0] if alive else None)
        if clock(data)['actions'] >= 200 and not data['finished']:
            data.update(finished=True, winner=None, finish_reason='turn_limit')
    else:
        from arena_raid_engine import finish_if_needed
        finish_if_needed(data)
    if data.get('finished'):
        clock(data)['pending'] = []
    return data.get('finished', False)


def _begin(data, key):
    from arena_engine import restore_turn_resource
    from arena_plague import begin_turn
    if key not in roster(data):return
    fighter = roster(data)[key]
    if fighter['hp'] <= 0:
        return
    # Raid NPC handlers already apply their own start-of-action plague tick.
    # Direct opponents use the same begin boundary as the player's fighter.
    poison = begin_turn(fighter) if 'sides' in data or key in humans(data) else 0
    gain = restore_turn_resource(fighter)
    if poison or gain:
        _log(data, key, key, ('Чума: −'+str(poison)+' HP. ' if poison else '') + ('Энергия: +'+str(gain)+'.' if gain else ''))
    choice(data, key)


def _release_group(data, skills, rng):
    from arena_engine import effective_skill
    q, fighters = clock(data), roster(data)
    q['previous_time'] = q['time']
    q['group'] = release(q)
    data['_cast_queue'] = dict(time=q['time'], round=data.get('round'), entries=[],
        signature=[data.get('nazarick', {}).get('stage'), data.get('nazarick', {}).get('phase')])
    if 'sides' not in data:
        from arena_raid_engine import raid_snapshot
        data['round_before'] = raid_snapshot(data)
    # Preserve the declared intent of this exact cast, not a later AI readback.
    for event in q['group']:
        if 'intent' in event and 'sides' not in data:
            if data.get('enemies'):
                data.setdefault('enemy_intents', {})[event['actor']] = event['intent']
            if event['actor'] == 'boss':
                data['intent'] = event['intent']
    released = []
    enemy_keys = [e['actor'] for e in q['group'] if e['actor'] in _enemy_ids(data)]
    if 'sides' not in data:
        if data.get('kind') == 'encounter':
            from arena_action_queue import _release
            released = [r for key in enemy_keys if (r := _release(data, key, skills))]
        else:
            from arena_boss_queue import _prepare
            released = _prepare(data, enemy_keys, skills, rng)
    else:
        for event in q['group']:
            if event['actor'] in enemy_keys:
                if any(e['kind'] == 'stun' for e in fighters[event['actor']]['effects']):continue
                released.append(dict(source=event['actor'], fighter=deepcopy(fighters[event['actor']]),
                                     intent=dict(skill=event['skill'], targets=[event['target']])))
    attacks = {}
    for event in q['group']:
        key, sid = event['actor'], event['skill']
        if key not in humans(data) or sid not in skills or not skills[sid].hostile:
            continue
        f, target = fighters[key], fighters[event['target']]
        if f['hp'] > 0 and target['hp'] > 0 and not any(e['kind'] == 'stun' for e in f['effects']):
            attacks[key] = event
    targets = {k for r in released if r['intent'].get('skill') in skills and skills[r['intent']['skill']].hostile
               for k in r['intent']['targets'] if k in humans(data)}
    # In PvP both human casts may land at the same timestamp.
    if 'sides' in data:
        for key, event in attacks.items():
            target = event['target']
            if target in humans(data):
                released.append(dict(source=key, fighter=deepcopy(fighters[key]), intent=dict(skill=event['skill'], targets=[target])))
                targets.add(target)
    eligible = sorted(k for k in set(attacks) | targets if data.get('qte_modes', {}).get(str(fighters[k]['controller_id'])))
    data['_queue_wait'] = dict(id=secrets.token_hex(16), unified=True, released=released,
        attacks=attacks, eligible=eligible, results={}, guards={}, attack_results={})
    return bool(eligible)


def stages(data, key, skills):
    """Build native challenges at cast completion; no client-reported damage."""
    from arena_engine import effective_skill
    from arena_qte_live import challenge
    from arena_qte_combined import combine
    pending, fighters = data['_queue_wait'], roster(data)
    actor = fighters[key]['controller_id']
    out = []
    event = pending['attacks'].get(key)
    if event:
        target = fighters[event['target']]
        variant = effective_skill(pair(fighters[key], target), 'a', event['skill'], skills)
        stage = challenge('attack', fighters[key], target, variant, actor)
        stage['unified_source'] = key
        out.append(stage)
    members = []
    for released in pending['released']:
        if key not in released['intent']['targets']:
            continue
        source, sid = released['fighter'], released['intent'].get('skill')
        if sid not in skills or not skills[sid].hostile:
            continue
        skill = effective_skill(pair(source, fighters[key]), 'a', sid, skills)
        stage = challenge('defense', source, fighters[key], skill, actor)
        stage.update(encounter_enemy=released['source'], name=source.get('name', '')+' · '+skill.name)
        members.append(stage)
    if members:
        incoming = combine(members, actor, fighters[key]['hp'])
        incoming['unified_target'] = key
        out.append(incoming)
    return out


def record_result(data, stage, result):
    pending = data['_queue_wait']
    if stage['kind'] == 'attack':
        pending['attack_results'][stage['unified_source']] = dict(attack=result['mask'], pattern_attack=result)
    else:
        pending['guards'][stage['unified_target']] = result['sources']


def _settle(data, skills, rng):
    from arena_engine import resolve_skill, _tick, use_healing_potion
    q, fighters, pending = clock(data), roster(data), data['_queue_wait']
    completed = list(q['group'])
    nazarick_before = tuple(data.get('_cast_queue', {}).get('signature', [None, None]))
    for event in completed:
        key = event['actor']
        if key in _enemy_ids(data) and 'sides' not in data:
            continue
        f, target = fighters[key], fighters[event['target']]
        simultaneous_ko = ('sides' in data and f['hp'] <= 0 and
                           any(r['source'] == key and r['fighter']['hp'] > 0 for r in pending['released']))
        if (f['hp'] <= 0 and not simultaneous_ko) or target['hp'] <= 0:
            _log(data, key, key, 'Подготовленное действие отменено: боец или цель повержены.')
            continue
        if simultaneous_ko:f['hp'] = 1
        f['resource'] = min(f['stats']['resource_max'], f['resource'] + event.get('reserved', 0))
        result = pending['attack_results'].get(key, {})
        if 'sides' in data:
            result = dict(result, **pending['guards'].get(event['target'], {}).get(key, {}))
            result['luck_evasion'] = not data.get('qte_modes', {}).get(str(target['controller_id']), False)
            result['luck_accuracy'] = not data.get('qte_modes', {}).get(str(f['controller_id']), False)
            if any(e['kind'] == 'stun' for e in f['effects']):
                _tick(f)
                _log(data, key, key, 'Ошеломление: каст сорван.', damage=0, hit=False)
            elif event['skill'] in ('defend', 'potion'):
                if event['skill'] == 'potion':
                    use_healing_potion(pair(f, target), 'a')
                _tick(f)
                _log(data, key, key, 'Пропуск хода.' if event.get('timeout') else 'Поддержка применена.', damage=0, hit=False)
            else:
                state = pair(f, target)
                try:
                    ev = resolve_skill(state, 'a', event['skill'], skills, rng, advance_turn=False, qte=result)
                except ValueError:
                    _tick(f)
                    ev = dict(text='Условия навыка изменились: каст сорван.', damage=0, hit=False)
                seq = max(data.get('event_seq', 0), data['log'][-1].get('seq', 0) if data['log'] else 0) + 1
                data['event_seq'] = seq
                ev.update(side=key, seq=seq)
                ev['after'] = {k: dict(hp=v['hp'], resource=v['resource']) for k, v in fighters.items()}
                from arena_engine import battle_status_snapshot
                ev['status_after'] = battle_status_snapshot(data)
                data['log'].append(ev)
                if not event.get('timeout'):data['had_player_action'] = True
            if simultaneous_ko:f['hp'] = 0
        else:
            p = data['players'][key]
            manual_before, misses_before = p['manual_turns'], p['missed']
            p['qte_result'] = result
            if data.get('kind') == 'encounter':
                from arena_action_queue import _player
                _player(data, key, skills, rng)
            else:
                from arena_boss_queue import _players
                restored_before = data.get('whaler_restored', {}).get(key, 0)
                _players(data, [key], skills, rng)
                if data.get('boss_id') == 'whaler':
                    data.setdefault('whaler_restored', {})[key] = restored_before + data.get('whaler_restored', {}).get(key, 0)
            p.update(selected=None, selected_target=None)
            p.pop('qte_result', None)
            if event.get('timeout'):
                p.update(manual_turns=manual_before, missed=misses_before)
        q['actions'] += 1
        if 'sides' in data:data['turn'] += 1
    if 'sides' not in data:
        if data.get('boss_id') == 'nazarick':
            from arena_nazarick import progress
            if progress(data):
                pending['released'] = []
        if data.get('kind') == 'encounter':
            from arena_action_queue import _land
        else:
            from arena_boss_queue import _land
        _land(data, pending['released'], pending['guards'], skills, rng)
    q['group'] = []
    data.pop('_queue_wait', None)
    q['pending'] = [e for e in q['pending'] if roster(data).get(e['actor'], {}).get('hp', 0) > 0]
    if _finish(data):
        return
    for event in completed:
        _begin(data, event['actor'])
    if 'sides' not in data:
        reactive = None
        if data.get('boss_id') == 'whaler' and q.get('whaler_reaction_round') != data['round']:
            from arena_whaler import prepare_reaction
            if prepare_reaction(data, rng, data.get('_queue_stunned', False)):
                reactive = data.pop('whaler_reaction')
                q['whaler_reaction_round'] = data['round']
        # Boss-native rounds count boss actions, not quick player decisions.
        enemy_done = [e for e in completed if e['actor'] in _enemy_ids(data)]
        if enemy_done and (data.get('kind') == 'encounter' or any(e['actor'] == 'boss' for e in enemy_done)):
            data.pop('_queue_stunned', None)
            q['boss_actions'] = q.get('boss_actions', 0) + 1
            data['round'] += 1
            data['control_lock'] = max(0, data.get('control_lock', 0) - 1)
            if data.get('kind') == 'encounter':
                from arena_encounters import set_intents
                old = deepcopy(data['enemy_intents'])
                set_intents(data, skills)
                busy = {e['actor'] for e in q['pending']}
                for key in busy:
                    if key in old:data['enemy_intents'][key] = old[key]
            elif data.get('boss_id') == 'nazarick':
                from arena_nazarick import set_intent
                set_intent(data)
            else:
                from arena_raid_engine import set_intent
                set_intent(data)
        if data.get('_chaplain_rewound') or data.get('_chaplain_transitioned'):
            # A script may restore fighters, but never restore clock/tickets or
            # let a committed input be replayed into another action.
            data.pop('_chaplain_rewound', None)
            data.pop('_chaplain_transitioned', None)
            q['pending'] = [e for e in q['pending'] if e['actor'] in humans(data)]
        if data.get('boss_id') == 'nazarick' and nazarick_before != (data['nazarick']['stage'], data['nazarick']['phase']):
            stage_changed = nazarick_before[0] != data['nazarick']['stage']
            if stage_changed:q['boss_actions'] = 0
            retained = []
            for event in q['pending']:
                if event['actor'] in humans(data):
                    if not stage_changed:
                        retained.append(event)
                    else:
                        f = roster(data)[event['actor']]
                        f['resource'] = min(f['stats']['resource_max'], f['resource'] + event.get('reserved', 0))
                        data['players'][event['actor']].update(selected=None, selected_target=None)
            q['pending'] = retained
            from arena_nazarick import set_intent
            set_intent(data)
        if reactive and not data.get('finished'):
            target = reactive['target']
            r = dict(source='boss', fighter=deepcopy(data['boss']), reaction=True,
                     intent=dict(kind='reaction',skill='whaler_punishment',targets=[target]))
            data['_queue_wait'] = dict(id=secrets.token_hex(16),unified=True,released=[r],attacks={},
                eligible=[target] if data.get('qte_modes',{}).get(target) else [],results={},guards={},attack_results={})
        if data.get('nazarick', {}).get('blessing_offer'):
            q['pending'] = []
            return
        if q.get('boss_actions', 0) >= 100:
            data.update(finished=True, won=False, result='Предел 100 действий противника.')
    data['log'] = data['log'][-80:]
    data.pop('round_before', None)


def advance(data, skills, rng=None):
    rng = rng or random.SystemRandom()
    initialize(data, skills)
    for _ in range(256):
        if _finish(data) or data.get('nazarick', {}).get('blessing_offer'):
            return data
        pending = data.get('_queue_wait')
        if pending:
            if any(key not in pending['results'] for key in pending['eligible'] if key in humans(data)):
                return data
            _settle(data, skills, rng)
            if data.get('finished'):return data
            initialize(data, skills)
            if data.get('_queue_wait'):continue
        if ready(data):
            if 'sides' in data:data['active_side'] = ready(data)[0]
            return data
        if not clock(data)['pending']:
            return data
        if not _release_group(data, skills, rng):
            continue
        return data
    raise ValueError('Слишком много событий очереди без выбора игрока.')


def public(data, viewer):
    q, fighters = clock(data), roster(data)
    entries = [dict(actor=e['actor'], at=round(e['end']-q['time'], 3), team='players' if e['actor'] in humans(data) else 'enemies',
                    skill=e['skill'] if e['actor'] in _enemy_ids(data) or fighters[e['actor']]['controller_id'] == viewer else None,
                    targets=e.get('intent', {}).get('targets', [e['target']])) for e in q['pending'] + q['group']]
    return dict(version=3, colors={key: COLORS[i % len(COLORS)] for i, key in enumerate(fighters)}, entries=entries,
                time=0, absolute_time=q['time'], animate_from=min(0, q.get('previous_time', q['time'])-q['time']),
                horizon=max([5, *(e['at'] for e in entries)]),
                phase='defense' if data.get('_queue_wait') else 'choose', round=data.get('round', data.get('turn', 1)))


def forecast_skill(data, key, skill):
    ends = [e['end'] for e in clock(data)['pending'] if key in e.get('intent', {}).get('targets', [e['target']]) and e['actor'] != key]
    return forecast(clock(data)['time'], duration(roster(data)[key], skill), min(ends) if ends else None)


def intercept(data, actor, source):
    key = str(actor)
    event = next((e for e in clock(data)['pending'] if e['actor'] == source), None)
    if key not in ready(data) or data.get('_queue_wait') or not event or len(event.get('intent', {}).get('targets', [])) != 1:
        raise ValueError('Можно перехватить только незавершённую одиночную атаку до выбора своего навыка.')
    intent, player = event['intent'], data['players'][key]
    if intent.get('interceptor') == key:
        intent['targets'] = [intent.pop('original_target')]
        intent.pop('interceptor')
        player.pop('intercept_source', None)
    else:
        original = intent['targets'][0]
        if original == key or original not in ready(data) or player.get('intercept_source') or intent.get('interceptor'):
            raise ValueError('Союзник или твой перехват уже заняты действием.')
        if player['fighter']['resource'] < 8:raise ValueError('Нужно 8 энергии.')
        intent.update(original_target=original, interceptor=key, targets=[key])
        player['intercept_source'] = source
    event['target'] = intent['targets'][0]
    (data.get('enemy_intents') or {'boss': data['intent']})[source].update(deepcopy(intent))
