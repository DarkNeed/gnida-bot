"""Shared cast timing and independent-mob execution. Scripted raids use
arena_boss_queue with their native phase handlers; all times are server-owned.
"""
from copy import deepcopy
import random
import secrets

COLORS = ('#79c8df', '#a8d5ad', '#d8ae73', '#dc9279', '#b39ce5', '#db9fc7', '#8ebdc6', '#c8be87')


def cast_time(fighter, skill=None):
    from arena_engine import effective_stat
    base = (1.6 if skill is None else 2.4 if not skill.hostile else
            4.2 if skill.power >= 35 or 'six_strike' in skill.tags else 3)
    return round((1.25 + base / (1 + max(0, effective_stat(fighter, 'speed')) * .018)) * 4) / 4


def entries(data, skills):
    from arena_raid_engine import alive_players, pair_state
    from arena_engine import effective_skill
    out = []
    enemies = data.get('enemies') or {'boss': data['boss']}
    intents = data.get('enemy_intents') or {'boss': data['intent']}
    for key, p in alive_players(data).items():
        target = p.get('selected_target') or next((k for k, f in enemies.items() if f['hp'] > 0), None)
        enemy = enemies.get(target, data['boss'])
        sid = p.get('selected')
        s = effective_skill(pair_state(p['fighter'], enemy), 'a', sid, skills) if sid in skills else None
        out.append(dict(actor=key, target=target, team='players', at=cast_time(p['fighter'], s), skill=sid))
    for key, i in intents.items():
        f = enemies[key]
        if f['hp'] > 0:
            s = skills.get(i.get('skill'))
            out.append(dict(actor=key, team='enemies', at=cast_time(f, s), skill=i.get('skill')))
    return sorted(out, key=lambda e: (e['at'], e['actor']))


def public_queue(data, skills, viewer):
    if not data.get('action_queue_version'):
        return None
    queue = data.get('_cast_queue')
    planned = queue['entries'] if queue else entries(data, skills)
    colors = {k: COLORS[i % len(COLORS)] for i, k in enumerate([*data['players'], *(data.get('enemies') or {'boss': data['boss']})])}
    return dict(colors=colors, phase='defense' if data.get('_queue_wait') else 'resolve' if queue else 'choose',
                round=data['round'], last=data.get('_last_cast_timeline'),
                time=queue.get('time', 0) if queue else 0,
                entries=[dict(actor=e['actor'], at=e['at'], team=e['team'],
                              skill=e['skill'] if e['team'] == 'enemies' or e['actor'] == str(viewer) else None)
                         for e in planned if e['team'] == 'enemies' or e['actor'] == str(viewer) or queue],
                intercept_cost=8)


def intercept(data, actor, source, skills):
    """Reserve one single-target attack before either participant commits."""
    from arena_raid_engine import alive_players
    key = str(actor)
    p = alive_players(data).get(key)
    if not data.get('action_queue_version') or not p or data.get('_cast_queue') or p['selected'] is not None:
        raise ValueError('Перехват доступен до выбора своего навыка.')
    intent = (data.get('enemy_intents') or {'boss': data['intent']}).get(source)
    if not intent or not skills.get(intent.get('skill')) or not skills[intent['skill']].hostile:
        raise ValueError('У противника нет перехватываемой атаки.')
    if intent.get('interceptor') == key:
        intent['targets'] = [intent.pop('original_target')]
        intent.pop('interceptor')
        p.pop('intercept_source', None)
        return
    if p.get('intercept_source') or intent.get('interceptor') or len(intent.get('targets', [])) != 1:
        raise ValueError('Одна реакция за раунд; массовую атаку нельзя перехватить.')
    original = str(intent['targets'][0])
    target = alive_players(data).get(original)
    if not target or original == key or target['selected'] is not None:
        raise ValueError('Можно прикрыть живого союзника, который ещё не выбрал действие.')
    if p['fighter']['resource'] < 8:
        raise ValueError('Для перехвата нужно 8 энергии.')
    intent.update(original_target=original, interceptor=key, targets=[key])
    p['intercept_source'] = source


def _log(data, actor, target, event, skill=None):
    from arena_raid_engine import log_event
    log_event(data, actor, target, event['text'], **(dict(skill=skill) if skill else {}),
              **{k: event[k] for k in ('damage', 'healing', 'self_damage', 'bleed_damage', 'damage_type',
                                      'hit', 'critical', 'hits', 'hit_results') if k in event})
    data['log'][-1]['cast_at'] = data['_cast_queue']['time']


def _player(data, key, skills, rng):
    from arena_raid_engine import alive_players, native_attack, defend
    from arena_engine import _tick
    p = alive_players(data).get(key)
    if not p:
        return
    actor, selected = p['fighter'], p['selected']
    p['manual_turns'] += int(selected is not None)
    p['missed'] = 0 if selected is not None else p['missed'] + 1
    p['reward_blocked'] = p.get('reward_blocked', False) or p['missed'] >= 3
    if any(e['kind'] == 'stun' for e in actor['effects']):
        _tick(actor)
        _log(data, key, key, dict(text='Ошеломление: каст сорван.'))
        return
    enemy_key = p.get('selected_target')
    enemy = data['enemies'].get(enemy_key)
    living = [(k, f) for k, f in data['enemies'].items() if f['hp'] > 0]
    if not living:
        return
    if selected in skills and not skills[selected].hostile and (not enemy or enemy['hp'] <= 0):
        enemy_key, enemy = living[0]
    if selected is None or selected == 'defend' or not enemy or enemy['hp'] <= 0:
        defend(actor, living[0][1], data)
        _log(data, key, key, dict(text='Защита: обе защиты +35%.' if selected in (None, 'defend') else
                                'Цель уже повержена: защита без расхода энергии.'))
        return
    proof = p.get('qte_result', {})
    for field in ('attack', 'pattern_attack'):
        if field in proof:
            actor['_qte_' + field] = proof[field]
    try:
        event = native_attack(actor, enemy, selected, skills, rng,
                              allies=[v['fighter'] for v in alive_players(data).values()], raid_context=data)
        _log(data, key, enemy_key, event, selected)
    except ValueError:
        defend(actor, enemy, data)
        _log(data, key, key, dict(text='Навык стал недоступен: защита без расхода энергии.'))
    finally:
        actor.pop('_qte_attack', None)
        actor.pop('_qte_pattern_attack', None)


def _release(data, key, skills):
    from arena_plague import begin_turn
    from arena_engine import _tick, validate_skill
    from arena_raid_engine import alive_players, pair_state
    enemy = data['enemies'][key]
    if enemy['hp'] <= 0:
        return None
    damage = begin_turn(enemy)
    if damage:
        _log(data, key, key, dict(text=f'Чума: −{damage} HP.', damage=damage))
    if enemy['hp'] <= 0:
        return None
    if any(e['kind'] == 'stun' for e in enemy['effects']):
        _tick(enemy)
        _log(data, key, key, dict(text='Ошеломление: намерение сорвано.'))
        return None
    i = deepcopy(data['enemy_intents'][key])
    if enemy.get('guild_monster') == 'troll' and not any(e['kind'] == 'burn' for e in enemy['effects']):
        heal = min(enemy['stats']['max_hp'] - enemy['hp'], round(enemy['stats']['max_hp'] * .04))
        enemy['hp'] += heal
        if heal:
            _log(data, key, key, dict(text=f'Плоть болот: +{heal} HP.', healing=heal))
    if i['kind'] in ('heal', 'guard'):
        _tick(enemy)
        living = [(k, f) for k, f in data['enemies'].items() if f['hp'] > 0]
        if enemy['hp'] <= 0 or not living:
            return None
        target, ally = min(living, key=lambda item: item[1]['hp'] / item[1]['stats']['max_hp'])
        if i['kind'] == 'heal':
            heal = min(ally['stats']['max_hp'] - ally['hp'], round(ally['stats']['max_hp'] * .25))
            ally['hp'] += heal
            from arena_plague import actively_healed
            actively_healed(ally)
            _log(data, key, target, dict(text=f'Лечебный настой: +{heal} HP.', healing=heal))
        else:
            ally['effects'] = [e for e in ally['effects'] if not e.get('id', '').startswith('encounter_guard_')]
            for dtype in ('physical', 'magic'):
                ally['effects'].append(dict(id='encounter_guard_' + dtype, kind=dtype + '_defense_pct', value=.35, duration=2))
            _log(data, key, target, dict(text='Прикрытие: обе защиты +35%.'))
        return None
    living = alive_players(data)
    i['targets'] = list(dict.fromkeys(str(k) for k in i.get('targets', []) if str(k) in living))
    if not i['targets']:
        _tick(enemy)
        return None
    try:
        validate_skill(pair_state(enemy, living[i['targets'][0]]['fighter']), 'a', i['skill'], skills)
    except ValueError:
        _tick(enemy)
        _log(data, key, key, dict(text='Объявленный навык недоступен: каст сорван.'))
        return None
    return dict(source=key, fighter=deepcopy(enemy), intent=i)


def _land(data, released, guards, skills, rng):
    from arena_raid_engine import alive_players, native_attack
    for r in released:
        key, original, i = r['source'], r['fighter'], r['intent']
        enemy = data['enemies'][key]
        after = None
        data['_qte_boss_phase'], data['intent'] = True, i
        for target in i['targets']:
            if target not in alive_players(data):
                continue
            f = data['players'][target]['fighter']
            guard = guards.get(target, {}).get(key)
            if guard:
                f['_qte_guard'] = dict(guard, skill=i['skill'])
            attacker = deepcopy(original)
            try:
                event = native_attack(attacker, f, i['skill'], skills, rng,
                                      allies=[v for v in data['enemies'].values() if v['hp'] > 0], raid_context=data)
            finally:
                f.pop('_qte_guard', None)
            after = after or attacker
            enemy['hp'] = max(0, enemy['hp'] - event.get('reaction_damage', 0))
            _log(data, key, target, event, i['skill'])
        if after:
            # One cost/cooldown/tick, even when the same cast has several recipients.
            hp = (max(0, min(enemy['stats']['max_hp'], enemy['hp'] + after['hp'] - original['hp']))
                  if enemy['hp'] > 0 else 0)
            resource = max(0, min(enemy['stats']['resource_max'], enemy['resource'] + after['resource'] - original['resource']))
            # Damage/control dealt at the same cast time must survive settlement
            # of an already released attack. Do not restore the whole old actor.
            before_effects = {e.get('id'): e for e in original['effects']}
            current_effects = {e.get('id'): e for e in enemy['effects']}
            effects = [e for e in after['effects'] if e.get('id') not in before_effects or e.get('id') in current_effects]
            for ident, effect in current_effects.items():
                if before_effects.get(ident) != effect:
                    effects = [e for e in effects if e.get('id') != ident] + [effect]
            mechanics = dict(after.get('mechanics', {}))
            for ident, value in enemy.get('mechanics', {}).items():
                if original.get('mechanics', {}).get(ident) != value:
                    mechanics[ident] = value
            enemy.clear()
            enemy.update(after, hp=hp, resource=resource, effects=effects, mechanics=mechanics)
            if 'next_ai_index' in i:
                enemy['rp_ai_index'] = i['next_ai_index']
    data.pop('_qte_boss_phase', None)


def advance(data, skills, rng=None):
    from arena_encounters import finish, set_intents, alive_enemies
    from arena_raid_engine import alive_players, raid_snapshot, RAID_MAX_ROUNDS
    from arena_engine import restore_turn_resource
    from arena_plague import begin_turn
    rng = rng or random.SystemRandom()
    if not data.get('_cast_queue'):
        data['round_before'] = raid_snapshot(data)
        data['_cast_queue'] = dict(entries=entries(data, skills), cursor=0, time=0, round=data['round'])
        for key, p in alive_players(data).items():
            if p.get('intercept_source'):
                cost = min(8, p['fighter']['resource'])
                p['fighter']['resource'] -= cost
                _log(data, key, key, dict(text=f'Перехват: −{cost} энергии.'))
    queue = data['_cast_queue']
    waiting = data.get('_queue_wait')
    if waiting:
        if any(k not in waiting['results'] for k in waiting['eligible'] if k in alive_players(data)):
            return data
        _land(data, waiting['released'], waiting['results'], skills, rng)
        data.pop('_queue_wait')
    while queue['cursor'] < len(queue['entries']) and not finish(data):
        at = queue['entries'][queue['cursor']]['at']
        group = []
        while queue['cursor'] < len(queue['entries']) and queue['entries'][queue['cursor']]['at'] == at:
            group.append(queue['entries'][queue['cursor']])
            queue['cursor'] += 1
        queue['time'] = at
        # Release simultaneous enemy casts before player damage at the same time.
        released = [r for e in group if e['team'] == 'enemies' and (r := _release(data, e['actor'], skills))]
        for e in group:
            if e['team'] == 'players':
                _player(data, e['actor'], skills, rng)
        targets = {k for r in released for k in r['intent']['targets']}
        eligible = sorted(k for k in targets if k in alive_players(data) and data.get('qte_modes', {}).get(k))
        if eligible:
            data['_queue_wait'] = dict(id=secrets.token_hex(12), released=released, eligible=eligible, results={})
            return data
        _land(data, released, {}, skills, rng)
    done = finish(data)
    if not done and data['round'] >= RAID_MAX_ROUNDS:
        data.update(finished=True, won=False, result='Предел 100 раундов.')
    data['_last_cast_timeline'] = dict(round=data['round'], time=queue['time'], entries=deepcopy(queue['entries']),
                                      colors={k: COLORS[i % len(COLORS)] for i, k in enumerate([*data['players'], *data['enemies']])})
    data.pop('_cast_queue', None)
    data.pop('round_before', None)
    data['log'] = data['log'][-80:]
    if not data['finished']:
        data['round'] += 1
        for key, p in data['players'].items():
            p.update(selected=None, selected_target=None)
            p.pop('qte_result', None)
            p.pop('intercept_source', None)
            if key in alive_players(data):
                damage = begin_turn(p['fighter'])
                if damage:
                    from arena_raid_engine import log_event
                    log_event(data, key, key, f'Чума: −{damage} HP.', damage=damage)
                restore_turn_resource(p['fighter'])
        if not finish(data):
            for enemy in alive_enemies(data).values():
                restore_turn_resource(enemy)
            set_intents(data, skills)
    return data
