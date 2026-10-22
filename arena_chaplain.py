"""Four revisions: finite boss-only phase heals and an ordinary rewind action."""

from copy import deepcopy
import secrets

from arena_engine import Skill, _tick

CHAPLAIN_LEVEL = 25
INCOMING = (1.6, 1.3, 1.1, 1.0)
ANCHORS = {
    'chaplain_anchor:damage': ('damage', 'Урон боссу'),
    'chaplain_anchor:healing': ('healing', 'Лечение отряда'),
    'chaplain_anchor:cleanse': ('cleanse', 'Очищение отряда'),
}
CHAPLAIN_SKILLS = {s.skill_id: s for s in (
    Skill('chaplain_hand', 'Часовая стрелка', 'raid', 1, 'physical', 23, 96, 0, 0),
    Skill('chaplain_chime', 'Колокол исправления', 'raid', 1, 'magic', 17, 97, 0, 0),
    Skill('chaplain_verdict', 'Последняя редакция', 'raid', 1, 'magic', 26, 98, 0, 0),
    Skill('chaplain_rewind', 'Переписать раунд', 'raid', 1, None, 0, 100, 0, 0),
)}
for phase in (2, 3, 4):
    names = {
        2: ('Принудительная синхронизация', 'Недостаточно прав', 'Исправление позиции'),
        3: ('Остановить процесс', 'Откат координат', 'Удалить выделенное'),
        4: ('Протокол вечности', 'Да будет свет', 'Полный доступ'),
    }[phase]
    for index, name in enumerate(names):
        ident = f'chaplain_p{phase}_{index}'
        CHAPLAIN_SKILLS[ident] = Skill(ident, name, 'raid', 1,
            'physical' if index == 0 else 'magic', (23, 17, 26)[index], 96 + index, 0, 0)


def initialize(data):
    data['chaplain'] = dict(version=2, phase=1, recoveries=0, rewinds=0,
        next_rewind=data['round'] + 4 + secrets.randbelow(3), anchors={}, banned={},
        ui_order={}, ui_scramble=False, swap_target='', notification='')


def ensure(data):
    if data.get('chaplain', {}).get('version') != 2:
        old_phase = min(4, max(1, data.get('phase', 1)))
        initialize(data)
        data['chaplain'].update(phase=old_phase, recoveries=old_phase - 1)
        for key in ('_chaplain_snapshot', '_chaplain_previous', '_chaplain_results'):
            data.pop(key, None)
    return data['chaplain']


def validate_anchor(data, skill):
    if data.get('boss_id') != 'chaplain' or skill not in ANCHORS:
        raise ValueError('Закрепление мгновения недоступно в этом бою.')


def _combat_copy(fighter):
    return deepcopy({k: v for k, v in fighter.items() if not k.startswith('_qte')})


def set_armor(data):
    boss, memory = data['boss'], ensure(data)
    boss['effects'] = [e for e in boss['effects'] if e.get('id') != 'chaplain_revision_armor']
    # Intrinsic phase rule, not a removable debuff or a 9999-turn buff icon.
    boss['chaplain_damage_taken'] = INCOMING[memory['phase'] - 1]
    boss.setdefault('mechanics', {})['chaplain_phase'] = memory['phase']
    boss['mechanics']['chaplain_incoming'] = boss['chaplain_damage_taken']


def set_intent(data):
    from arena_raid_engine import alive_players
    living = alive_players(data)
    if not living:
        return
    memory = ensure(data)
    phase = data['phase'] = memory['phase']
    set_armor(data)
    memory['anchors'] = {k: v for k, v in memory['anchors'].items()
        if k in data['players'] and not data['players'][k].get('withdrawn') and v['until'] >= data['round']}
    memory['banned'] = {}
    memory['ui_order'] = {}
    memory['ui_scramble'] = (phase >= 2 and data['round'] % 3 == 0) or phase == 4
    if phase >= 2:
        for key, player in living.items():
            loadout = player['fighter']['loadout']
            if loadout:
                memory['banned'][key] = loadout[(data['round'] - 1) % len(loadout)]
                offset = 1 + data['round'] % max(1, len(loadout) - 1)
                memory['ui_order'][key] = loadout[offset:] + loadout[:offset]
    memory['swap_target'] = (list(living)[data['round'] % len(living)]
        if phase == 3 and data['round'] % 2 == 0 or phase == 4 and data['round'] % 3 == 1 else '')
    memory['notification'] = (
        'Обнаружено несанкционированное выживание.' if phase == 4 else
        'Порядок действий скорректирован.' if phase >= 2 else '')
    previous = data.get('_chaplain_snapshot')
    if previous and previous.get('phase') == phase and previous['round'] < data['round']:
        previous['results'] = deepcopy(data.get('_chaplain_results', {}))
        data['_chaplain_previous'] = previous
    elif not previous or previous.get('phase') != phase:
        data.pop('_chaplain_previous', None)
    data['_chaplain_snapshot'] = dict(round=data['round'], phase=phase,
        boss=_combat_copy(data['boss']),
        players={k: dict(fighter=_combat_copy(p['fighter']), previous_skill=p.get('previous_skill'))
                 for k, p in data['players'].items() if not p.get('withdrawn')},
        control_lock=data.get('control_lock', 0), control_resistance=data.get('control_resistance', 0))
    data['_chaplain_results'] = dict(healing={}, cleansed={})
    index = (data['round'] - 1) % 3
    phase_skills = (('chaplain_hand', 'chaplain_chime', 'chaplain_verdict')
                    if phase == 1 else tuple(f'chaplain_p{phase}_{i}' for i in range(3)))
    data['boss']['loadout'] = [*phase_skills, 'chaplain_rewind']
    skill = phase_skills[index]
    ordinary = data['round'] >= memory['next_rewind'] and bool(data.get('_chaplain_previous'))
    if ordinary:
        skill = 'chaplain_rewind'
    targets = [] if ordinary else list(living)
    if not ordinary and index == 0:
        targets = [targets[(data['round'] - 1) % len(targets)]]
    text = ('Переписать раунд: вместо атаки вернёт боевое состояние к началу предыдущего раунда. Закрепите результат!'
            if ordinary else CHAPLAIN_SKILLS[skill].name + (' — весь отряд.' if len(targets) > 1 else ' — отмеченный боец.'))
    if data['boss']['hp'] <= data['boss']['stats']['max_hp'] * .45 and phase < 4:
        text += ' Часы идут назад: на 30% HP его здоровье будет восстановлено.'
    data['intent'] = dict(kind='chaplain_rewind' if ordinary else 'attack', skill=skill,
                          targets=targets, phase=phase, text=text)
    data['dialogue'] = dict(speaker='КАПЕЛЛАН', text=(
        'Всё согласно регламенту.' if phase <= 2 else 'Ручное вмешательство.' if phase == 3 else
        'Последняя редакция. Исправления больше не принимаются.'),
        warning='Обычный откат занимает действие босса. Фазовое восстановление возвращает только его HP.',
        persistent=True, id=f"chaplain:{data['round']}:{phase}")


def anchor(data, key, skill):
    from arena_raid_engine import log_event
    validate_anchor(data, skill)
    _tick(data['players'][key]['fighter'])
    kind, label = ANCHORS[skill]
    ensure(data)['anchors'][key] = dict(kind=kind, until=data['round'] + 2)
    log_event(data, key, key, f'Закреплено мгновение: {label.lower()}. На три раунда.', chaplain_event='anchor')


def marked_cost(data, key, skill):
    from arena_raid_engine import log_event
    if ensure(data)['banned'].get(key) != skill:
        return
    fighter = data['players'][key]['fighter']
    paid = min(max(0, fighter['hp'] - 1), max(1, round(fighter['stats']['max_hp'] * .10)))
    fighter['hp'] -= paid
    log_event(data, key, key, f'Нарушение предписания: −{paid} HP за помеченный навык.', self_damage=paid)


def action_before(data):
    return {k: dict(hp=p['fighter']['hp'], effects=deepcopy(p['fighter']['effects']))
            for k, p in data['players'].items() if not p.get('withdrawn')}


def record_action(data, before):
    from arena_epic import temporary_debuff
    results = data['_chaplain_results']
    for key, old in before.items():
        current = data['players'][key]['fighter']
        results['healing'][key] = results['healing'].get(key, 0) + max(0, current['hp'] - old['hp'])
        present = {(e.get('id'), e['kind']) for e in current['effects']}
        removed = [[e.get('id'), e['kind']] for e in old['effects']
                   if temporary_debuff(e) and (e.get('id'), e['kind']) not in present]
        results['cleansed'].setdefault(key, []).extend(removed)


def _restore_fighter(fighter, saved):
    used = list(fighter.get('used_skills', []))
    potion = fighter.get('potion_used', False)
    once = {name: {k: v for k, v in fighter.get(name, {}).items()
                   if (k.endswith('_used') or k.endswith('_revived')) and v is True}
            for name in ('rpg_state', 'final_state', 'mastery_state', 'epic_state')}
    uses = deepcopy(fighter.get('epic_state', {}).get('skill_uses', {}))
    amendment = deepcopy(amendment_active(fighter))
    remaining = max(0, amendment['until'] - fighter.get('own_turns', 0)) if amendment else 0
    fighter.clear()
    fighter.update(deepcopy(saved))
    fighter['used_skills'] = list(dict.fromkeys(fighter.get('used_skills', []) + used))
    fighter['potion_used'] = fighter.get('potion_used', False) or potion
    for name, flags in once.items():
        if flags:
            fighter.setdefault(name, {}).update(flags)
    for skill, count in uses.items():
        counts = fighter.setdefault('epic_state', {}).setdefault('skill_uses', {})
        counts[skill] = max(counts.get(skill, 0), count)
    fighter.get('mechanics', {}).pop('last_amendment', None)
    if amendment:
        amendment['until'] = fighter.get('own_turns', 0) + remaining
        fighter.setdefault('mechanics', {})['last_amendment'] = amendment


def rewind(data):
    from arena_raid_engine import log_event
    memory = ensure(data)
    checkpoint = data.get('_chaplain_previous') or data.get('_chaplain_snapshot')
    if not checkpoint or checkpoint['phase'] != memory['phase'] or data.get('_chaplain_rewound'):
        return False
    kinds = {a['kind'] for key, a in memory['anchors'].items()
             if not data['players'][key].get('withdrawn') and a['until'] >= data['round']}
    damage = max(0, checkpoint['boss']['hp'] - data['boss']['hp']) if 'damage' in kinds else 0
    results = (checkpoint.get('results', {}), data.get('_chaplain_results', {}))
    _restore_fighter(data['boss'], checkpoint['boss'])
    data['boss']['hp'] = max(1, data['boss']['hp'] - damage)
    for key, snap in checkpoint['players'].items():
        p = data['players'][key]
        if p.get('withdrawn'):
            continue
        f = p['fighter']
        _restore_fighter(f, snap['fighter'])
        if 'healing' in kinds:
            f['hp'] = min(f['stats']['max_hp'], f['hp'] + sum(r.get('healing', {}).get(key, 0) for r in results))
        if 'cleanse' in kinds:
            removed = {tuple(e) for r in results for e in r.get('cleansed', {}).get(key, [])}
            f['effects'] = [e for e in f['effects'] if (e.get('id'), e['kind']) not in removed]
        p['previous_skill'] = snap['previous_skill']
    data['control_lock'], data['control_resistance'] = checkpoint['control_lock'], checkpoint['control_resistance']
    memory['rewinds'] += 1
    memory['next_rewind'] = data['round'] + 5 + secrets.randbelow(3)
    memory['anchors'] = {}
    data['_chaplain_rewound'] = True
    set_armor(data)
    log_event(data, 'boss', 'boss', f"Редакция отменена: состояние вернулось к началу раунда {checkpoint['round']}. " +
              ('Закреплённые результаты сохранены.' if kinds else 'Капеллан потратил действие на откат.'),
              chaplain_event='rewind')
    data.pop('_chaplain_previous', None)
    data.pop('_chaplain_snapshot', None)
    return True


def intercept_end(data):
    from arena_raid_engine import alive_players
    memory = ensure(data)
    if data['boss']['hp'] <= 0 and memory['phase'] < 4 and alive_players(data):
        data['boss']['hp'] = 1
        memory['pending_phase'] = True


def transition(data):
    """Boss action boundary: only his HP/phase changes, never player fighters."""
    from arena_raid_engine import alive_players, log_event
    memory = ensure(data)
    if (memory['phase'] >= 4 or not alive_players(data) or
            not (memory.get('pending_phase') or data['boss']['hp'] <= data['boss']['stats']['max_hp'] * .30)):
        return False
    memory['phase'] += 1
    memory['recoveries'] += 1
    memory.pop('pending_phase', None)
    data['phase'] = memory['phase']
    data['boss']['hp'] = data['boss']['stats']['max_hp']
    set_armor(data)
    data['_chaplain_transitioned'] = True
    for key in ('_chaplain_snapshot', '_chaplain_previous', '_chaplain_results'):
        data.pop(key, None)
    log_event(data, 'boss', 'boss', 'Ваш результат не был сохранён. HP Капеллана полностью восстановлено. Состояние игроков не изменено.',
              chaplain_event='phase_restore', phase=memory['phase'])
    return True


def amendment_active(fighter):
    mark = fighter.get('mechanics', {}).get('last_amendment')
    return mark if mark and fighter.get('own_turns', 0) <= mark['until'] else None


def amendment_action(fighter):
    from arena_epic import temporary_debuff
    mark = amendment_active(fighter)
    if mark:
        fighter['hp'] = max(fighter['hp'], min(fighter['stats']['max_hp'], mark['hp']))
        fighter['effects'] = [e for e in fighter['effects'] if not temporary_debuff(e)]
        fighter['mechanics'].pop('last_amendment', None)
        return 'Мгновение возвращено: HP восстановлены, снимаемые дебаффы очищены. Энергия и перезарядки не возвращаются.'
    fighter.setdefault('mechanics', {})['last_amendment'] = dict(hp=fighter['hp'], until=fighter['own_turns'] + 2)
    return 'Мгновение закреплено на два собственных действия. Повторное применение бесплатно, но тратит действие.'
