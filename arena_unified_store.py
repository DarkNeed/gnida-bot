"""Transactional adapters for the shared completion-time queue."""
import json
import time

import arena_unified_queue as queue


def catalog(db):
    from arena_raid_engine import BOSS_SKILLS
    return {**BOSS_SKILLS, **db._fighter_catalog_locked()[1]}


def _save(db, scope, row, data):
    if data.get('finished'):
        db.connection.execute('DELETE FROM arena_qte_flows WHERE scope=? AND token=?',(scope,row['token']))
    if scope == 'raid':
        if data.get('finished'):
            db._raid_finish_locked(row, data)
        else:
            db._raid_save_locked(row, data)
        return
    if data.get('finished'):
        db._arena_finish_locked(row, data)
    db.connection.execute('UPDATE arena_battles SET state_json=?,revision=revision+1,deadline=? WHERE token=?',
        (json.dumps(data, ensure_ascii=False), 0 if row['mode'] == 'wasteland' else int(time.time()) + 120, row['token']))


def _flows(db, scope, row, data, skills):
    pending = data.get('_queue_wait')
    if not pending or not pending.get('unified'):
        return
    if scope == 'battle':
        if db._qte_load_locked(scope, row['token']):return
        native = [stage for key in pending['eligible'] for stage in queue.stages(data, key, skills)]
        # In PvP, both attack inputs are committed before either defense input.
        native.sort(key=lambda s: s['kind'] != 'attack')
        if not native:
            pending['results'] = {key: True for key in pending['eligible']}
            return
        db._qte_save_locked(dict(scope=scope, token=row['token'], owner=0, actor=native[0]['actor'],
            stages=native, result={}, unified_group=pending['id']), True)
    else:
        for key in pending['eligible']:
            actor = queue.roster(data)[key]['controller_id']
            if key in pending['results'] or db._qte_load_locked(scope, row['token'], actor):continue
            native = queue.stages(data, key, skills)
            if not native:
                pending['results'][key] = True
                continue
            db._qte_save_locked(dict(scope=scope, token=row['token'], owner=actor, actor=actor,
                stages=native, result={}, unified_key=key, unified_group=pending['id']), True)


def drive(db, scope, row, data):
    skills = catalog(db)
    queue.advance(data, skills)
    _save(db, scope, row, data)
    if not data.get('finished') and not data.get('nazarick', {}).get('blessing_offer'):
        _flows(db, scope, row, data, skills)
        # Persist any skipped empty flow tickets too.
        column, table = ('state_json', 'arena_battles') if scope == 'battle' else ('data_json', 'arena_raids')
        db.connection.execute(f'UPDATE {table} SET {column}=? WHERE token=?', (json.dumps(data, ensure_ascii=False), row['token']))


def direct(db, row, actor, revision, sid, choice_id=None):
    if row['status'] != 'active' or choice_id is None and row['revision'] != revision:
        raise ValueError('Бой или выбранное действие уже изменились. Обнови арену.')
    if row['mode'] != 'wasteland' and row['deadline'] <= time.time():
        raise ValueError('Время выбора истекло. Обнови арену.')
    data = json.loads(row['state_json'])
    key = next((k for k, f in data['sides'].items() if f['controller_id'] == actor), None)
    if key is None:raise ValueError('Это не твой боец.')
    if row['mode'] == 'slaves' or row['mode'] == 'wasteland' and not row.get('personal_solo') and row.get('a_fighter') != actor:
        for side in ('a','b') if row['mode'] == 'slaves' else ('a',):
            if not db._arena_owns_locked(row['chat_id'],row[side+'_owner'],row[side+'_fighter']):
                raise ValueError('Владелец бойца сменился. Бой недоступен.')
    if sid == 'surrender':
        data.update(finished=True, winner='b' if key == 'a' else 'a', finish_reason='surrender')
        db.connection.execute("DELETE FROM arena_qte_flows WHERE scope='battle' AND token=?", (row['token'],))
        _save(db, 'battle', row, data)
        return
    if sid == 'potion':
        f = data['sides'][key]
        if f['potion_used'] or f['hp'] >= f['stats']['max_hp']:raise ValueError('Зелье сейчас нельзя использовать.')
        from arena_global import RPG_SCOPE
        item = db.connection.execute("SELECT * FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind='potion' AND content_id='healing'", (RPG_SCOPE, actor)).fetchone()
        if not item:raise ValueError('Нет зелья.')
        db._arena_consume_item_locked(item)
    if sid == 'casino_all_in' and not data['sides'][key].get('rp_sandbox'):
        from arena_casino_chance import native_roulette
        native_roulette(db, 'battle', row['token'], actor)
    skills = catalog(db)
    db._qte_snapshot_locked('battle', row, data)
    queue.submit(data, key, sid, 'b' if key == 'a' else 'a', skills,
                 ident=choice_id if choice_id is not None else queue.choice(data, key))
    if row.get('ranked'):
        data.setdefault('ranked_actions', {'a':0, 'b':0})[key] += 1
        data.setdefault('ranked_timeouts', {'a':0, 'b':0})[key] = 0
    drive(db, 'battle', row, data)


def raid(db, row, actor, round_number, sid, target=None, choice_id=None):
    from arena_raid_engine import finish_if_needed
    from arena_encounters import target_enemy
    data, key = json.loads(row['data_json']), str(actor)
    if row['status'] != 'active' or type(round_number) is not int or round_number != data['round']:
        raise ValueError('Бой уже изменился. Обнови арену.')
    if row['deadline'] <= time.time():
        raise ValueError('Время выбора истекло. Обнови арену.')
    if data.get('nazarick', {}).get('blessing_offer'):
        raise ValueError('Бой приостановлен: отряд голосует за благословение.')
    if key not in data['players'] or data['players'][key].get('withdrawn'):
        raise ValueError('Ты не управляешь этим бойцом.')
    if sid == 'surrender':
        data['players'][key].update(withdrawn=True, reward_blocked=True, selected=None)
        queue.clock(data)['pending'] = [e for e in queue.clock(data)['pending'] if e['actor'] != key]
        db.connection.execute("DELETE FROM arena_qte_flows WHERE scope='raid' AND token=? AND actor_id=?", (row['token'], actor))
    else:
        if data.get('kind') == 'encounter' or data.get('boss_id') == 'nazarick':
            target, _ = target_enemy(data, target)
        else:target = 'boss'
        if sid == 'casino_all_in' and not data['players'][key]['fighter'].get('rp_sandbox'):
            from arena_casino_chance import native_roulette
            native_roulette(db, 'raid', row['token'], actor)
        db._qte_snapshot_locked('raid', row, data)
        queue.submit(data, key, sid, target, catalog(db), ident=choice_id)
    drive(db, 'raid', row, data)


def complete(db, flow, stage, result):
    scope = flow['scope']
    row = db._arena_row_locked(flow['token']) if scope == 'battle' else db._raid_row_locked(flow['token'])
    data = json.loads(row['state_json'] if scope == 'battle' else row['data_json'])
    pending = data.get('_queue_wait')
    if not pending or pending['id'] != flow['unified_group']:
        db._qte_delete_locked(flow)
        return
    queue.record_result(data, stage, result)
    flow['stages'].pop(0)
    column, table = ('state_json', 'arena_battles') if scope == 'battle' else ('data_json', 'arena_raids')
    db.connection.execute(f'UPDATE {table} SET {column}=? WHERE token=?', (json.dumps(data, ensure_ascii=False), row['token']))
    if flow['stages']:
        # Respect attack masks/criticals when the same cast is defended in PvP.
        for following in flow['stages']:
            if following['kind'] != 'defense':continue
            for member in following.get('members', []):
                attack = pending['attack_results'].get(member['encounter_enemy'])
                if attack:
                    member['enabled_strikes'] = attack['attack']
                    member['critical_strikes'] = attack.get('pattern_attack', {}).get('criticals', [])
        db._qte_save_locked(flow, True)
        return
    if scope == 'battle':
        pending['results'] = {key: True for key in pending['eligible']}
    else:
        pending['results'][flow['unified_key']] = True
    db._qte_delete_locked(flow)
    drive(db, scope, row, data)


def expire(db, scope, row, data):
    """Only ready humans time out; never consume a committed cast twice."""
    skills = catalog(db)
    queue.initialize(data, skills)
    if data.get('_queue_wait'):
        drive(db, scope, row, data)
        return
    inactive = []
    for key in list(queue.ready(data)):
        opponents = [k for k in queue.roster(data) if k != key and (k in queue._enemy_ids(data) if scope == 'raid' else True)
                     and queue.roster(data)[k]['hp'] > 0]
        if not opponents:continue
        queue.submit(data, key, 'defend', opponents[0], skills, timeout=True)
        if scope == 'battle' and row.get('ranked'):
            misses = data.setdefault('ranked_timeouts', {'a':0, 'b':0})
            misses[key] += 1
            if misses[key] >= 3:inactive.append(key)
        if scope == 'raid':
            p = data['players'][key]
            p['missed'] += 1
            p['reward_blocked'] |= p['missed'] >= 3
    if inactive:
        data.update(finished=True, winner=None if len(inactive)>1 else 'b' if inactive[0]=='a' else 'a', finish_reason='ranked_inactivity')
    drive(db, scope, row, data)
