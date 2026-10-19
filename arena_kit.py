"""Kit: fixed level 25 encounter. Intent is frozen before player selections."""

from copy import deepcopy

from arena_engine import Skill, _tick, bleeding_damage

KIT_LEVEL = 25
KIT_STATS = dict(max_hp=1100, resource_max=100, physical_attack=48,
                 magic_attack=52, physical_defense=22, magic_defense=22,
                 speed=18, evasion=10)
KIT_SKILLS = {s.skill_id: s for s in (
    Skill('kit_reflection', 'Отражение', 'raid', 1, 'physical', 7, 95, 0, 0,
          description='Два раздельных удара: физический и магический.'),
    Skill('kit_ash', 'Пепельная сторона', 'raid', 1, 'magic', 8, 95, 0, 0),
    Skill('kit_light', 'Световой поток', 'raid', 1, 'magic', 21, 95, 0, 0,
          description='Отмеченная цель получает Метку очищения. Защита снимает её до тика.'),
    Skill('kit_rift', 'Прямой разлом', 'raid', 1, 'physical', 12, 95, 0, 0,
          description='Колхозанский стайл: удар по всему отряду.'),
    Skill('kit_field', 'Поле божественной вспышки', 'raid', 1, None, 0, 100, 0, 0,
          description='Попытка прямой атаки вызывает одну ответную вспышку за раунд. Поддержка и защита безопасны.'),
    Skill('kit_coins', 'Две стороны одной монеты', 'raid', 1, 'physical', 16, 95, 0, 0,
          description='Двойной удар по отряду. 10% максимального HP за раунд срывают подготовку; Защита снижает урон.'),
    Skill('kit_coins_ash', 'Обратная сторона', 'raid', 1, 'magic', 16, 95, 0, 0),
    Skill('kit_eclipse', 'Солнечное затмение', 'raid', 1, 'magic', 44, 95, 0, 0,
          pierce=.25, description='Одна объявленная ульта при переходе ниже 35% HP. Защита резко снижает урон.'),
    Skill('kit_flash', 'Ответная вспышка', 'raid', 1, 'magic', 5, 95, 0, 0),
)}
ACTION_NAMES = {'physical': 'физическую атаку', 'magic': 'магию', 'support': 'поддержку'}


def add_effect(side, ident, kind, value, duration, **extra):
    side['effects'] = [e for e in side['effects'] if e.get('id') != ident]
    side['effects'].append(dict(id=ident, kind=kind, value=value, duration=duration, **extra))


def set_kit_intent(data):
    from arena_raid_engine import alive_players
    living = alive_players(data)
    if not living:
        return
    boss, keys = data['boss'], list(living)
    memory = boss.setdefault('mechanics', {})
    ratio = boss['hp'] / boss['stats']['max_hp']
    phase = 3 if ratio <= .35 else 2 if ratio <= .70 else 1
    data.update(phase=phase, phase_count=3, arena_theme=('court', 'asura', 'eclipse')[phase - 1])
    memory['kit_phase'] = phase
    target = keys[(data['round'] - 1) % len(keys)]
    pattern = (data['round'] - 1) % 5
    if phase == 3 and not memory.get('eclipse_announced'):
        skill = 'kit_eclipse'
        memory['eclipse_announced'] = True
    elif phase >= 2 and pattern == 3:
        skill = 'kit_field'
    elif phase >= 2 and pattern == 4:
        skill = 'kit_coins'
    else:
        skill = ('kit_reflection', 'kit_light', 'kit_rift', 'kit_reflection', 'kit_light')[pattern]
    texts = {
        'kit_reflection': 'Отражение: два удара по отмеченному бойцу — физический и магический.',
        'kit_light': 'Световой поток по отмеченному бойцу. Метку очищения можно снять Защитой или очищением.',
        'kit_rift': 'Колхозанский стайл: Прямой разлом по всему отряду.',
        'kit_field': 'Поле божественной вспышки: одна ответная вспышка за раунд на попытку атаки. Восстановите силы или защищайтесь.',
        'kit_coins': 'Раскручивает Отражение: двойной удар по отряду. Нанесите 10% максимального HP за этот раунд, чтобы сорвать его, или защищайтесь!',
        'kit_eclipse': 'СОЛНЕЧНОЕ ЗАТМЕНИЕ: мощный удар по всему отряду после ваших действий. Защищайтесь! Повторной ульты не будет.',
    }
    targets = keys if skill in ('kit_rift', 'kit_coins', 'kit_eclipse') else [target]
    if skill == 'kit_field':
        targets = []
    data['intent'] = dict(kind='kit', phase=phase, skill=skill, targets=targets, text=texts[skill])
    data.pop('kit_prediction', None)
    for p in data['players'].values():
        p['fighter']['effects'] = [e for e in p['fighter']['effects'] if e.get('id') != 'kit_foreseen']
    if data['round'] % 3 == 2:
        predicted = living[target].get('kit_previous_action')
        if predicted in ACTION_NAMES:
            data['kit_prediction'] = dict(target=target, action=predicted)
            add_effect(living[target]['fighter'], 'kit_foreseen', 'kit_foreseen', 1, 1,
                       name='Эхо-взор', description='Кит предсказывает '+ACTION_NAMES[predicted]+'. Выберите другой тип действия или Защиту.')
    prediction = data.get('kit_prediction')
    if prediction:
        data['intent']['text'] += ' Эхо-взор предсказывает '+ACTION_NAMES[prediction['action']]+' отмеченного бойца; смените тип действия или защищайтесь.'
    lines = {'kit_eclipse': 'Мои лучшие дни позади. Этот — ещё нет.',
             'kit_field': 'Я вижу, куда ты ударишь. Попробуй удивить.',
             'kit_coins': 'У каждой монеты две стороны. Обе сегодня против тебя.',
             'kit_rift': 'Колхозанский стайл. Без лишних церемоний.'}
    data['dialogue'] = dict(speaker='КИТ', text=lines.get(skill, 'Сильным быть недостаточно. Покажи, ради кого ты не упадёшь.'),
                            warning='Фиксированный уровень 25. Фон и намерения меняются только между раундами.',
                            persistent=True, id=f"kit:{data['round']}")


def kit_prepare_action(data, key, skill):
    """Only the direct player action gets shields; followers never open a reaction."""
    boss = data['boss']
    category = skill.damage_type or 'support'
    prediction = data.get('kit_prediction', {})
    predicted = prediction.get('target') == key and prediction.get('action') == category
    first = boss['mechanics'].get('kit_shield_round') != data['round']
    if skill.damage_type and (first or predicted):
        add_effect(boss, 'kit_action_shield', 'incoming_damage_multiplier', .75, 1,
                   consume_on_hit=True, name='Эхо-щиты', description='Прямой удар ослаблен на 25%.')
    return dict(category=category, predicted=predicted, first=first)


def kit_finish_action(data, key, event, prepared):
    boss = data['boss']
    boss['effects'] = [e for e in boss['effects'] if e.get('id') != 'kit_action_shield']
    if prepared['first'] and event.get('damage', 0) > 0:
        boss['mechanics']['kit_shield_round'] = data['round']
    data['players'][key]['kit_previous_action'] = prepared['category']


def kit_defend(data, key):
    fighter = data['players'][key]['fighter']
    fighter['effects'] = [e for e in fighter['effects'] if e.get('id') != 'kit_mark']
    data['players'][key]['kit_previous_action'] = 'guard'


def kit_react(data, key, event, prepared, rng):
    from arena_raid_engine import native_attack, log_event
    boss, player = data['boss'], data['players'][key]
    memory = boss['mechanics']
    field = data['intent']['skill'] == 'kit_field' and event.get('damage_type')
    if (not (prepared['predicted'] or field) or boss['hp'] <= 0
            or player['fighter']['hp'] <= 0 or memory.get('kit_reaction_round') == data['round']):
        return
    memory['kit_reaction_round'] = data['round']
    reaction = deepcopy(boss)
    reaction['controller_id'] = -125  # Different action identity from the boss's main turn.
    retaliation = native_attack(reaction, player['fighter'], 'kit_flash', KIT_SKILLS,
                               rng, tick_actor_bleed=False, raid_context=data)
    boss['hp'] = max(0, boss['hp'] - retaliation.get('reaction_damage', 0))
    log_event(data, 'boss', key, ('Предсказание сбылось. ' if prepared['predicted'] else 'Поле вспыхнуло. ')+retaliation['text'],
              damage=retaliation['damage'], skill='kit_flash', damage_type='magic',
              hit=retaliation['hit'], critical=retaliation['critical'])


def resolve_kit_action(data, rng):
    from arena_raid_engine import alive_players, native_attack, log_event
    boss, intent = data['boss'], data['intent']
    skill = intent['skill']
    if skill == 'kit_field':
        _tick(boss)
        log_event(data, 'boss', 'boss', 'Поле вспышки рассеялось. Кит возвращается в стойку.')
        return
    if skill == 'kit_coins' and data['round_before']['boss']['hp'] - boss['hp'] >= boss['stats']['max_hp'] * .10:
        _tick(boss)
        add_effect(boss, 'kit_opening', 'damage_taken_pct', .25, 1,
                   name='Стойка сломана', description='Кит получает на 25% больше урона до следующего действия.')
        log_event(data, 'boss', 'boss', 'Две стороны одной монеты: подготовка сорвана! Кит открыт для атак на следующий раунд.')
        return
    living = alive_players(data)
    # An announced target who withdrew/died does not redirect an unseen attack.
    targets = [k for k in intent['targets'] if k in living]
    pending_dot = bleeding_damage(boss) + sum(max(0, int(e['value'])) for e in boss['effects'] if e['kind'] == 'burn')
    original = deepcopy(boss)
    strikes = (skill, 'kit_ash') if skill == 'kit_reflection' else (skill, 'kit_coins_ash') if skill == 'kit_coins' else (skill,)
    for key in targets:
        for sid in strikes:
            if boss['hp'] <= 0 or living[key]['fighter']['hp'] <= 0:
                break
            fighter = living[key]['fighter']
            attacker = deepcopy(original)
            attacker['hp'] = boss['hp']
            if intent['phase'] > 1:
                add_effect(attacker, 'kit_fury', 'damage_pct', .10 * (intent['phase'] - 1), 1)
            if skill in ('kit_coins', 'kit_eclipse') and any(e.get('id') == 'raid_guard_magic' for e in fighter['effects']):
                add_effect(attacker, 'kit_guarded_ultimate', 'final_damage_multiplier', .4, 1)
            if skill == 'kit_light' and any(e.get('id') == 'kit_mark' for e in fighter['effects']):
                add_effect(attacker, 'kit_purification', 'damage_pct', .25, 1)
            event = native_attack(attacker, fighter, sid, KIT_SKILLS, rng,
                                  tick_actor_bleed=False, raid_context=data)
            boss['hp'] = max(0, boss['hp'] - event.get('reaction_damage', 0))
            if skill == 'kit_light' and event['hit'] and fighter['hp'] > 0:
                add_effect(fighter, 'kit_mark', 'burn', max(1, round(fighter['stats']['max_hp'] * .03)), 2,
                           name='Метка очищения', description='Горение на два действия. Усиливает следующий Световой поток; Защита или очищение снимают метку.')
            log_event(data, 'boss', key, event['text'], damage=event['damage'], skill=sid,
                      damage_type=event['damage_type'], hit=event['hit'], critical=event['critical'])
    _tick(boss, tick_dot=False)
    if pending_dot:
        dot = min(boss['hp'], pending_dot)
        boss['hp'] -= dot
        log_event(data, 'boss', 'boss', f'Кровотечение / горение: −{dot} HP.', damage=dot)
