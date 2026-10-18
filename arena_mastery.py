"""Alternative progression, derived from saved choices; no new permanent currency.

Only an explicitly resolved stay unlocks mastery. Combat memory is local to a
battle and previews are pure. A branch replaces base mastery, never adds to it.
"""
from copy import deepcopy
from dataclasses import replace

from arena_fingers import negative_kinds


BASE = {
    'ragamuffin': ('Уличный опыт', 'Грязные приёмы готовят усиленный удар; разные действия собирают уличную комбинацию.', 'Не на того напал', 'physical'),
    'cutie': ('Искусство умилять', 'Чередование Мяу и UWU усиливает следующую из этих атак на 35%, с 12 уровня на 45%.', 'Критическая милота', None),
    'jock': ('Идеальная техника', 'Подготовленный Въебать: сила 16, с 12 уровня 18; попадание оставляет защиту от прямого урона −20% на одно своё действие.', 'Без страховки', 'physical'),
    'nerd': ('Теория всего', 'Три разных типа родных действий готовят усиление следующей атаки, Деанона или магазина. Промахи тоже дают шаг.', 'Проверка гипотезы', 'magic'),
    'thumb': ('Служба без повышения', 'Предупредительный выстрел усиливается; после попадания сохраняет один потраченный заряд Субординации, с 12 уровня — до двух.', 'Служебное взыскание', 'physical'),
    'index': ('Личное толкование', 'За каждое исполнение предписания дополнительно возвращает 8 Воли, с 12 уровня 12. Два исполнения готовят усиленную Последнюю строку.', 'Написано мной', None),
    'middle': ('Семья помнит', 'Ответные удары при попадании сохраняют одну Обиду, с 12 уровня две; промах сохраняет накопленные обиды.', 'Семейный разбор', 'physical'),
    'ring': ('Собственный почерк', 'После Последнего штриха сохраняет один собственный временный дебафф, с 12 уровня — два, с оставшимся до удара сроком.', 'Авторская подпись', 'magic'),
    'pinky': ('Свой небосвод', 'Чередование разных родных атак добавляет Созвездие при попадании, максимум 3; с 12 уровня атаки получают +5 точности.', 'Пересечение орбит', 'physical'),
    'warrior': ('Мастер оружия', 'Раскол брони за применение сильнее: 20% вместо 15%, с 12 уровня 25%, общий предел 45%. Три разных родных приёма собирают комбинацию.', 'Смена стойки', None),
    'mage': ('Чистая мана', 'Родные магические атаки, включая промахи, собирают до 3 Потоков. Перегрузка получает +25% урона за Поток; барьер может потратить их на защиту.', 'Мановая спираль', 'magic'),
    'priest': ('Вера без сана', 'Полезная родная поддержка усиливает следующую Кару на 40%; успешная Кара усиливает следующее лечение на 30%.', 'Тихая молитва', None),
    'hunter': ('Ремесло охоты', 'Смена формы подготавливает следующий Рваный разрез: +35% урона; с 12 уровня также +10 точности.', 'След добычи', 'physical'),
}

BASE_FINAL = {
    'ragamuffin': '«Последний из подворотни»: после трёх разных действий Удар бомжа — сила 34, 45% пробития, цена 20; попадание возвращает 20 энергии.',
    'cutie': '«Милота массового поражения»: Мяу после UWU по умилённой цели — сила 30 за 35 Любви; умиление не снимается.',
    'jock': '«Предел человеческой качалки»: подготовленный Въебать — три независимых попадания с суммарной силой 30 за 30 энергии.',
    'nerd': '«Я просчитал этот бой»: подготовленная атака +14 к силе и дешевле на 10, Деанон снижает обе защиты на 35%, магазин дополнительно возвращает 30 энергии.',
    'thumb': '«По всем статьям»: при 3 Субординации Приговор — сила 30, цена 45, 50% пробития и ещё +10% урона за собственное ослабление, максимум 3.',
    'index': '«Предписание без подписи»: подготовленная Последняя строка — сила 30, цена 35 и 50% пробития; Написано мной позволяет исполнить предписание любой следующей родной атакой.',
    'middle': '«За каждого из наших»: при 3 Обидах За всю семью — сила 28 за 40 энергии; попадание прикрывает на 25% до следующего своего действия.',
    'ring': '«Дипломная работа»: при трёх ослаблениях Последний штрих — сила 28 за 40 энергии; сохраняются два собственных дебаффа.',
    'pinky': '«Собственное созвездие»: при 3 Созвездиях Лунная дуга — сила 24, пробитие 55%, цена 25; Падающая звезда — сила 30 за 45, сохраняет критический шанс. Обе тратят 2 заряда только при попадании.',
    'warrior': '«Совершенная техника»: готовая комбинация открывает Казнь силы 28 и пробития 35% выше порога добивания. По цели с HP ≤30% — сила 36 и пробитие 50%.',
    'mage': '«Идеальный поток»: Перегрузка при 3 Потоках — сила 28 за 35 маны; попадание возвращает 20 маны. Барьер при 3 Потоках снижает прямой урон на 50%.',
    'priest': '«Чудо без сана»: три полезных действия готовят Кару силы 28 за 40 маны или Исцеление на 50% max HP за 35. Одно из двух тратит подготовку.',
    'hunter': '«Охота без конца»: успешная висцеральная атака усиливает две следующие родные атаки на 45%; серия действует до трёх своих действий, не обновляется сама от себя.',
}

# Same lower-stage identity, no final resource and no free passive slots.
# Each upgrade is conditional on the branch's existing loop, not +all stats.
BRANCHES = {
    'femboy': ('air_kiss', 'Попался окончательно', 'adoration', 24, 25, 'По умилённой цели: сила 24 за 25 Любви, снижает уклонение; умиление сохраняется.'),
    'princess': ('arch_princess', 'Королевская неприкосновенность', 'always', 0, 20, 'Розовый барьер: обе защиты +45%, уклонение +12 на 2 своих действия, цена 20.'),
    'gachi_actor': ('arch_gachi_actor', 'Из захвата не вырваться', 'prepared', 26, 30, 'После напряжения или зажима: Клубный захват силы 26 за 30, снижает атаку и уклонение, не оглушает.'),
    'mge_bro': ('arch_mge_bro', 'Мид мой', 'alternate', 30, 35, 'Ракетный прыжок после другой родной атаки: сила 30 за 35, пробитие 35%; собственная уязвимость сохраняется.'),
    'programmer': ('arch_programmer', 'Проверенный откат', 'always', 0, 15, 'Откат версии: подготовка магии +60%, остальные перезарядки −2, цена 15.'),
    'hacker': ('arch_hacker', 'Сервис недоступен', 'hacked', 22, 30, 'По взломанной цели: сила 22 за 30, похищение до 25 энергии и точность цели −18.'),
    'thumb_discipline': ('arch_thumb_discipline', 'Выучка без изъяна', 'always', 0, 15, 'Построение: точность +25, обе защиты +30% на 2 действия, цена 15.'),
    'thumb_execution': ('arch_thumb_execution', 'Двойной контроль', 'order', 30, 35, 'При 3 Субординации: два независимых выстрела, суммарная сила 30 за 35, пробитие 50%. Заряды расходуются при попадании.'),
    'index_proxy': ('arch_index_proxy', 'Буква в букву', 'prescript', 28, 25, 'Точное исполнение по предписанию: сила 28, 50% пробития за 25 Воли; исполнение считается и при промахе.'),
    'index_messenger': ('arch_index_messenger', 'Убедительное толкование', 'always', 0, 20, 'Непрошеный совет за 20: чужое предписание, обе атаки цели −25% на 2 действия; при попадании возвращает 10 Воли.'),
    'middle_guardian': ('arch_middle_guardian', 'Надёжное плечо', 'grudge', 25, 25, 'При 2 Обидах: Семья прикроет силы 25 за 25, обе защиты +40%; расход одной Обиды при попадании.'),
    'middle_revenge': ('arch_middle_revenge', 'Ничто не забыто', 'grudge', 30, 30, 'При 2 Обидах: Не забыто силы 30 за 30, обе защиты цели −25%; расход одной Обиды при попадании. Самоурон остаётся.'),
    'ring_pointillist': ('arch_ring_pointillist', 'Чистовая рана', 'negatives2', 20, 25, 'При двух ослаблениях: Пунктирная рана силы 20 за 25, кровотечение 7 на 3 действия и снижение физической защиты.'),
    'ring_fauvist': ('arch_ring_fauvist', 'Повадки хищника', 'negatives2', 27, 30, 'При двух ослаблениях: Чучело хищника силы 27 за 30, замедление и магическая защита −30% на 2 действия.'),
    'pinky_dihui': ('arch_pinky_dihui', 'Безупречный заслон', 'focus', 26, 25, 'При 2 Созвездиях: Охраняющий клинок силы 26 за 25, пробитие 45%, обе защиты +35%; расход 1 Созвездия при попадании.'),
    'pinky_tiansha': ('arch_pinky_tiansha', 'Разрез звёздной выучки', 'focus', 32, 35, 'При 2 Созвездиях: Небесная рассечка силы 32 за 35, пробитие 45%; расход 1 Созвездия при попадании.'),
    'warrior_berserker': ('arch_warrior_berserker', 'Неудержимый натиск', 'momentum', 36, 40, 'При 3 Натиска: серия трёх ударов силы 36 за 40; сохраняет один Натиск при попадании и весь при промахе.'),
    'warrior_knight': ('arch_warrior_knight', 'Выверенный контрудар', 'steadfast', 30, 30, 'При 2 Стойкости: контрудар силы 30 за 30, защита от прямого урона −35%; тратит 1 Стойкость при попадании.'),
    'mage_necromancer': ('arch_mage_necromancer', 'Непрерывная жатва', 'souls', 28, 35, 'При 3 Душах: Жатва силы 28 за 35, прежние бонусы Душ, лечение 40% снятого HP; попадание оставляет 1 Душу и продлевает скелета до 3 действий.'),
    'mage_elementalist': ('arch_mage_elementalist', 'Безупречный метеор', 'burn', 34, 40, 'Метеор по горящей цели: сила 34 за 40, прежний бонус +50%; после попадания горение сохраняется ещё на 1 действие.'),
    'mage_archmage': ('arch_mage_archmage', 'Отточенное стирание', 'echo', 38, 50, 'С готовым Эхом: Стирание силы 38 за 50 до скидки Эха, пробитие 50%; попадание оставляет шаг новой цепочки.'),
    'priest_bishop': ('arch_priest_bishop', 'Суд без ошибки', 'faith', 32, 40, 'При 3 Веры: Страшный суд силы 32 за 40, прежние +40% за заряд; попадание оставляет 1 Веру.'),
    'priest_paladin': ('arch_priest_paladin', 'Выверенный приговор', 'retribution', 34, 40, 'При 2 Воздаяния: Приговор силы 34 за 40, пробитие 50%; попадание расходует только 1 Воздаяние.'),
    'hunter_beast': ('arch_hunter_beast', 'Привычка рвать', 'beast', 34, 35, 'При 3 Зверства: Разорвать добычу силы 34 за 35, прежний бонус Зверства; попадание оставляет 1 Зверство.'),
    'hunter_moon': ('arch_hunter_moon', 'Охота при бледной луне', 'visceral', 40, 40, 'В открытом окне прерывания: Приговор силы 40 за 40, пробитие 60%; после попадания окно сохраняется ещё на одно действие, без продления повтором.'),
}


def path(source):
    if source.get('is_boss') or source.get('class_id') not in BASE:
        return ''
    level, resolved = source.get('level', 0), source.get('progression_level', 0)
    arch = source.get('archclass_id', '')
    if arch:
        from arena_archclasses import ARCHCLASSES
        entry = ARCHCLASSES.get(arch)
        return 'branch' if (entry and entry['class_id'] == source['class_id'] and
            level >= 20 and resolved >= 20 and source.get('archclass_stage', 20) == 10) else ''
    if source['class_id'] == 'ragamuffin' and level >= 5 and resolved >= 5:
        return 'base'
    return 'base' if level >= 10 and resolved >= 10 else ''


def skill_allowed(skill, source):
    required = next((t.split(':', 1)[1] for t in skill.tags if t.startswith('mastery:')), None)
    return not required or (path(source) == 'base' and required == source.get('class_id')
                            and source.get('level', 0) >= skill.unlock_level
                            and (skill.unlock_level < 10 or source.get('progression_level',0) >= 10))


def view(source):
    mode = path(source)
    if not mode:
        return None
    cls, level = source['class_id'], source['level']
    if mode == 'branch':
        return dict(name='Совершенное владение ветвью', stage=20, kind=mode,
            description=BRANCHES[source['archclass_id']][5],
            milestones=[dict(level=20, unlocked=True, description=BRANCHES[source['archclass_id']][5])])
    rows = [(10, BASE[cls][1]), (12, TWELVE[cls]),
            (15, 'Новый навык: «' + BASE[cls][2] + '». Нужен свободный слот памяти или выбор замены.'),
            (18, 'Навык 15 уровня: ' + EIGHTEEN[cls]), (20, BASE_FINAL[cls])]
    if cls == 'ragamuffin':
        rows.insert(0, (5, 'Уличная закалка: боевые характеристики на уровне полноценных классов и навык «Перевести дух».'))
    return dict(name='Совершенное мастерство' if source.get('progression_level', 0) >= 20 else BASE[cls][0],
        kind=mode, stage=20 if source.get('progression_level', 0) >= 20 else 10 if level >= 10 else 5,
        description=BASE[cls][1], milestones=[dict(level=n, description=d, unlocked=level >= n and source.get('progression_level',0)>=(20 if n==20 else 10 if n>=10 else 5),
            **({'skill_id': 'mastery_' + cls} if n == 15 else {})) for n,d in rows])


TWELVE = {
    'ragamuffin': 'Пыль в глаза дешевле на 5 энергии и снижает уклонение на 15; подготовленный удар получает силу 22.',
    'cutie': 'Бонус чередования Мяу и UWU повышается с 35% до 45%.',
    'jock': 'Подготовленный Въебать получает силу 18 вместо 16.',
    'nerd': 'Подготовленная атака получает +10 силы вместо +8; магазин возвращает ещё 20 энергии вместо 15.',
    'thumb': 'Попавший Предупредительный выстрел сохраняет до 2 потраченных зарядов вместо 1.',
    'index': 'Исполнение дополнительно возвращает 12 Воли вместо 8.',
    'middle': 'Ответ при попадании сохраняет до 2 Обид вместо 1.',
    'ring': 'Последний штрих сохраняет два собственных дебаффа вместо одного.',
    'pinky': 'Родные атаки получают +5 точности.',
    'warrior': 'Раскол брони снимает 25% за применение, общий предел 45%.',
    'mage': 'Подготовленный Потоками барьер дополнительно возвращает 10 маны.',
    'priest': 'Полезная поддержка усиливает следующую Кару на 50% вместо 40%.',
    'hunter': 'Подготовленный Рваный разрез получает +10 точности.',
}
EIGHTEEN = {k: 'сила +4, цена прежняя.' for k in BASE}
EIGHTEEN.update(cutie='умиление длится 3 действия вместо 2.', index='цена 10 вместо 15.',
    priest='лечение 25% max HP вместо 20%.', warrior='подготовка физической атаки +60% вместо +45%.')


def build_skills(Skill):
    result = {}
    for cls, (_, _, name, dtype) in BASE.items():
        effects, tags = (), ('mastery:' + cls,)
        if cls == 'cutie':
            effects = (dict(id='adoration', kind='damage_pct', value=-.4, turns=2, target='enemy', chance=.90),)
        elif cls == 'warrior':
            effects = (dict(id='mastery_stance', kind='next_physical_damage', value=.45, turns=2, target='self'),)
        elif cls == 'priest':
            effects = (dict(id='mastery_prayer', kind='rpg_heal', value=.20, target='self'),)
        elif cls == 'ring':
            effects = (dict(id='mastery_signature',kind='speed_pct',value=-.25,turns=3,target='enemy'),)
        result['mastery_' + cls] = Skill('mastery_' + cls, name, cls, 15, dtype,
            20 if dtype else 0, 95 if dtype or cls == 'cutie' else 100,
            15 if not dtype else 25, 3, effects, 'rare',
            'Путь мастерства. ' + SKILL_TEXT[cls] + ' С 18 уровня: ' + EIGHTEEN[cls], tags=tags)
    result['street_breath'] = Skill('street_breath','Перевести дух','ragamuffin',5,None,0,100,0,3,
        (dict(id='street_energy',kind='resource',value=35,target='self'),
         dict(id='street_heal',kind='heal_pct',value=.10,target='self')), description='Возвращает 35 энергии и 10% максимального HP, расходуя действие.',tags=('mastery:ragamuffin',))
    return result


SKILL_TEXT = {
    'ragamuffin': 'Удар с 35% пробития, подготавливает следующую уличную атаку.',
    'cutie': '90% шанса умиления: урон врага −40% на 2 действия.',
    'jock': 'Удар с 35% пробития; после попадания подготавливает следующий Въебать.',
    'nerd': 'Магическая атака даёт атакующий шаг Теории всего, в том числе при промахе.',
    'thumb': 'Выстрел снижает обе атаки противника на 20% на 2 действия.',
    'index': 'Следующая родная атака сама становится твоим предписанием, даже при промахе; не требует отдельного подтверждения.',
    'middle': 'Удар даёт одну Обиду при попадании и снижает обе защиты цели на 15% на 2 действия.',
    'ring': 'Атака и собственная метка: скорость цели −25% на 3 действия.',
    'pinky': 'Два отдельных удара, 30% пробития; при попадании даёт одно Созвездие.',
    'warrior': 'Следующая физическая атака +45% урона; защита от прямого урона −20% до следующего действия.',
    'mage': 'Атака; при попадании возвращает 15 маны, даёт Поток как родная магия.',
    'priest': 'Лечит 20% max HP и снимает с себя одно ослабление. В рейде лечит раненого союзника по обычным правилам Жреца.',
    'hunter': 'Атака с кровотечением 4 на 3 действия, шанс 75%; подготавливает следующий Рваный разрез.',
}


def final_base(source):
    return path(source) == 'base' and source.get('level', 0) >= 20 and source.get('progression_level', 0) >= 20


def street_stats(source, stats):
    if source.get('class_id') != 'ragamuffin' or path(source) != 'base':
        return stats
    # A retained starter must not keep level-one class growth forever.
    delta = max(0, min(20, source['level']) - 5)
    result = dict(stats)
    result.update(max_hp=round(46+4.7*delta), physical_attack=13+1.4*delta,
                  magic_attack=8+.9*delta, physical_defense=9+.95*delta,
                  magic_defense=9+.95*delta, speed=10+.8*delta, evasion=7+.35*delta)
    if source.get('controlled'):
        for key in ('max_hp','physical_attack','magic_attack','physical_defense','magic_defense','speed','evasion'):
            result[key] = round(result[key] * .8, 2)
        result['max_hp'] = round(result['max_hp'])
    return result


def context(actor, target):
    return dict(memory=deepcopy(actor.get('mastery_state', {})), mechanics=deepcopy(actor.get('mechanics', {})),
        rpg=deepcopy(actor.get('rpg_state', {})), effects=deepcopy(target.get('effects', [])),
        hp=actor['hp'], target_hp=target['hp'])


def buff(side, key, kind, value, duration):
    side['effects'] = [e for e in side['effects'] if e.get('id') != key]
    side['effects'].append(dict(id=key, kind=kind, value=value, duration=duration))


def _trigger(name, actor, target, skill):
    m, r = actor.get('mechanics', {}), actor.get('rpg_state', {})
    effects = target.get('effects', []) if target else []
    return {
        'always': True,
        'adoration': any(e.get('id') == 'adoration' and e.get('value',0)<0 for e in effects),
        'prepared': any(e.get('id') == 'evolution_prepared' for e in actor.get('effects', [])),
        'alternate': m.get('last_attack') not in (None, skill.skill_id),
        'hacked': any(e.get('id') == 'doxxing_magic' for e in effects),
        'order': m.get('order', 0) >= 3, 'prescript': m.get('prescript') == skill.skill_id,
        'grudge': m.get('grudge',0) >= 2, 'focus': m.get('focus',0) >= 2,
        'negatives2': bool(target and len(negative_kinds(target)) >= 2),
        'momentum': r.get('onslaught',0) >= 3, 'steadfast': r.get('steadfast',0) >= 2,
        'souls': r.get('souls',0) >= 3, 'burn': any(e.get('kind') == 'burn' for e in effects),
        'echo': bool(r.get('echo_ready')), 'faith': r.get('faith',0) >= 3,
        'retribution': r.get('retribution',0) >= 2, 'beast': r.get('beast',0) >= 3,
        'visceral': bool(r.get('visceral_ready') and actor.get('own_turns',0) < r.get('visceral_until',0)),
    }.get(name, False)


def _branch_changes(skill, actor, target):
    key = actor['archclass_id']
    sid, name, trigger, power, cost, description = BRANCHES[key]
    if skill.skill_id != sid:
        return None
    changes = dict(name=name, cost=cost, tags=skill.tags+('mastery_branch',), description=description)
    if skill.damage_type: changes['power'] = power
    effects = tuple(deepcopy(skill.effects))
    if key == 'princess':
        effects = tuple(dict(e, value={'physical_defense_pct':.45,'magic_defense_pct':.45,'evasion_flat':12}.get(e['kind'],e['value'])) for e in effects)
    elif key == 'programmer':
        effects = tuple(dict(e,value=.60) if e['kind']=='next_magic_damage' else e for e in effects)
    elif key == 'thumb_discipline':
        effects = (dict(id='mastery_drill_aim',kind='accuracy_flat',value=25,turns=2,target='self'),)+tuple(
            dict(id='mastery_drill_'+k,kind=k+'_defense_pct',value=.30,turns=2,target='self') for k in ('physical','magic'))
    elif key == 'hacker':
        effects = tuple(dict(e, value=25 if e['kind']=='resource_leech' else -18 if e['kind']=='accuracy_flat' else e['value']) for e in effects)
    elif key == 'index_messenger':
        effects = tuple(dict(id='mastery_advice_'+k,kind=k+'_attack_pct',value=-.25,turns=2,target='enemy') for k in ('physical','magic'))
    elif key in ('middle_guardian','middle_revenge','ring_fauvist'):
        value = .40 if key=='middle_guardian' else -.25 if key=='middle_revenge' else -.30
        effects = tuple(dict(e,value=value) if e['kind'] in ('physical_defense_pct','magic_defense_pct') else e for e in effects)
    elif key == 'ring_pointillist':
        effects = tuple(dict(e,value=7) if e['kind']=='bleed' else e for e in effects)
    elif key == 'pinky_dihui':
        effects = tuple(dict(e,value=.35) if e['kind'].endswith('_defense_pct') else e for e in effects)
    if key in ('mge_bro','index_proxy','thumb_execution','pinky_dihui','pinky_tiansha','mage_archmage','priest_paladin','hunter_moon'):
        changes['pierce'] = .35 if key=='mge_bro' else .45 if key.startswith('pinky') else .60 if key=='hunter_moon' else .50
    if key == 'thumb_execution': changes['tags'] += ('two_strike','no_order_bonus')
    if key == 'warrior_berserker': changes['tags'] += ('three_strike',)
    if key == 'warrior_knight':
        effects = tuple(e for e in effects if e['kind']!='incoming_damage_multiplier') + (dict(id='mastery_knight',kind='incoming_damage_multiplier',value=.65,turns=1,target='self'),)
    if key == 'mage_archmage':changes['cost']=40  # 50 minus the existing level-12 Echo discount.
    changes['effects'] = effects
    return dict(ready=_trigger(trigger,actor,target,skill), changes=changes, min_level=20,
                condition=description, description=description)


def rule(skill, actor, target=None):
    mode = path(actor)
    if not mode or skill.class_id != actor['class_id']: return None
    if mode == 'branch': return _branch_changes(skill, actor, target)
    cls, sid, level = actor['class_id'], skill.skill_id, actor['level']
    m, mechanics = actor.get('mastery_state',{}), actor.get('mechanics',{})
    final = final_base(actor)
    ready, changes, description = False, None, BASE[cls][1]
    tags = skill.tags + ('mastery_base',)
    if sid == 'mastery_'+cls:
        changes = dict(tags=tags, power=skill.power+(4 if level>=18 and skill.damage_type else 0))
        effects = tuple(deepcopy(skill.effects))
        if cls=='cutie' and level>=18: effects=tuple(dict(e,turns=3) for e in effects)
        if cls=='priest': effects=tuple(dict(e,value=.25 if level>=18 else .20) for e in effects)
        if cls=='warrior': effects=tuple(dict(e,value=.60 if level>=18 else .45) for e in effects)
        if cls=='index' and level>=18: changes['cost']=10
        if cls in ('ragamuffin','jock','pinky'): changes['pierce']=.30 if cls=='pinky' else .35
        if cls=='pinky': changes['tags']+=('two_strike',)
        if cls=='thumb': effects=tuple(dict(id='mastery_reprimand_'+k,kind=k+'_attack_pct',value=-.20,turns=2,target='enemy') for k in ('physical','magic'))
        if cls=='middle': effects=tuple(dict(id='mastery_family_'+k,kind=k+'_defense_pct',value=-.15,turns=2,target='enemy') for k in ('physical','magic'))
        if cls=='hunter': effects=(dict(id='mastery_hunt_bleed',kind='bleed',value=4,turns=3,target='enemy',chance=.75),)
        if cls=='priest': effects+=(dict(id='mastery_prayer_cleanse',kind='cleanse_one',value=1,target='self'),)
        if cls=='warrior': effects+=(dict(id='mastery_stance_guard',kind='incoming_damage_multiplier',value=.8,turns=1,target='self'),)
        changes['effects']=effects
        return dict(ready=True, changes=changes, min_level=15, condition='Изучен навык пути мастерства', description=skill.description)
    if cls=='ragamuffin':
        if sid=='dust_in_eyes' and level>=12:
            ready=True;changes=dict(cost=15,effects=tuple(e for e in skill.effects if e['kind']!='evasion_flat')+
                (dict(id='street_evasion',kind='evasion_flat',value=-15,turns=2,target='enemy'),))
        elif sid=='bum_punch':
            ready=m.get('street_ready',False)
            changes=dict(name='Уличный ответ',power=22 if level>=12 else 20,cost=10)
            if final and len(m.get('combo',[]))>=3:
                ready=True;changes=dict(name='Последний из подворотни',power=34,cost=20,pierce=.45,tags=tags+('mastery_street_final',))
    elif cls=='cutie' and sid in ('uwu','meow'):
        ready=m.get('last_cute') not in (None,sid)
        changes=dict(name=skill.name+' · очарование',tags=tags+('mastery_cute_combo',))
        if final and sid=='meow' and m.get('last_cute')=='uwu' and target and any(e.get('id')=='adoration' for e in target['effects']):
            changes.update(name='Милота массового поражения',power=30,cost=35,tags=tags+('mastery_cute_combo','keep_adoration'))
    elif cls=='jock' and sid=='smack':
        ready=any(e.get('id')=='evolution_prepared' for e in actor.get('effects',[]))
        changes=dict(name='Идеальный подход',power=18 if level>=12 else 16,cost=15,tags=tags+('mastery_prepared',))
        if final:changes.update(name='Предел человеческой качалки',power=30,cost=30,tags=tags+('mastery_prepared','three_strike'))
    elif cls=='nerd':
        ready=bool(m.get('theory_ready'))
        if skill.damage_type:
            changes=dict(name='Я просчитал этот бой' if final else skill.name+' · по расчёту',power=skill.power+(14 if final else 10 if level>=12 else 8),cost=max(1,skill.cost-(10 if final else 5)),tags=tags+('mastery_theory',))
        elif sid=='doxxing':
            changes=dict(name='Деанон по науке',effects=tuple(dict(e,value=-.35 if final else -.30) if e['kind'].endswith('_defense_pct') else e for e in skill.effects),tags=tags+('mastery_theory',))
        elif sid=='go_to_store':changes=dict(name='Закупка по списку',tags=tags+('mastery_theory',))
    elif cls=='thumb' and sid=='warning_shot':
        ready=True;changes=dict(power=skill.power+4,description=BASE[cls][1])
    elif cls=='thumb' and sid=='senior_verdict' and final:
        ready=mechanics.get('order',0)>=3
        changes=dict(name='По всем статьям',power=30,cost=45,pierce=.50,tags=tags+('no_order_bonus','mastery_articles'))
    elif cls=='index' and sid=='last_line':
        ready=m.get('executions',0)>=2
        changes=dict(name='Предписание без подписи' if final else 'Личное толкование',power=30 if final else 26,cost=35,pierce=.50 if final else .35,tags=tags+('mastery_written',))
    elif cls=='middle' and sid=='whole_family' and final:
        ready=mechanics.get('grudge',0)>=3;changes=dict(name='За каждого из наших',power=28,cost=40,tags=tags+('mastery_family',))
    elif cls=='ring' and sid=='last_stroke' and final:
        ready=bool(target and len(negative_kinds(target))>=3)
        changes=dict(name='Дипломная работа',power=28,cost=40,tags=tags+('mastery_diploma',))
    elif cls=='pinky' and sid in ('moon_arc','falling_star') and final:
        ready=mechanics.get('focus',0)>=3
        changes=dict(name='Собственное созвездие' if sid=='moon_arc' else 'Звёздный росчерк',power=24 if sid=='moon_arc' else 30,cost=25 if sid=='moon_arc' else 45,
            pierce=.55 if sid=='moon_arc' else skill.pierce,tags=tags+('consume_focus',)+(('no_critical',) if sid=='moon_arc' else ()))
    elif cls=='warrior' and sid=='armor_split':
        ready=True;changes=dict(effects=tuple(dict(e,value=.25 if level>=12 else .20) if e['kind']=='rpg_armor_break' else e for e in skill.effects))
    elif cls=='warrior' and sid=='warrior_execute' and final:
        low=bool(target and target['hp']<=target['stats']['max_hp']*.30)
        ready=low or len(m.get('combo',[]))>=3
        changes=dict(name='Совершенная техника',power=36 if low else 28,pierce=.50 if low else .35,tags=tags+('mastery_execute',))
    elif cls=='mage' and sid=='mana_overload':
        ready=m.get('flow',0)>0;changes=dict(tags=tags+('mastery_flow',))
        if final and m.get('flow',0)>=3:changes.update(name='Идеальный поток',power=28,tags=tags+('mastery_flow','mastery_flow_refund'))
    elif cls=='mage' and sid=='mana_barrier':
        ready=m.get('flow',0)>=3;changes=dict(name='Замкнутый поток',effects=tuple(dict(e,value=.50 if final else .60) for e in skill.effects),tags=tags+('mastery_flow_guard',))
    elif cls=='priest' and sid in ('holy_judgment','priest_heal'):
        if sid=='priest_heal' and m.get('healing_ready'):
            ready=True;changes=dict(name='Исцеление после кары',effects=tuple(dict(e,value=e['value']*1.30) if e['kind']=='rpg_heal' else e for e in skill.effects))
        if final:
            miracle=m.get('prayers',0)>=3
            if miracle or changes is None:
                ready=miracle
                changes=(dict(name='Чудо без сана: кара',power=28,cost=40,tags=tags+('mastery_miracle',)) if sid=='holy_judgment' else
                    dict(name='Чудо без сана: спасение',cost=35,effects=tuple(dict(e,value=.50) for e in skill.effects),tags=tags+('mastery_miracle',)))
    elif cls=='hunter' and sid=='hunter_cut':
        ready=bool(m.get('hunt_ready'));changes=dict(name=skill.name+' · верный след',tags=tags+('mastery_hunt',))
    if changes is None:return None
    changes.setdefault('tags',tags)
    changes.setdefault('description',BASE_FINAL[cls] if final else BASE[cls][1])
    return dict(ready=ready,changes=changes,min_level=20 if final and sid not in ('armor_split','warning_shot','dust_in_eyes') else 5 if cls=='ragamuffin' else 10,
                condition=BASE_FINAL[cls] if final else BASE[cls][1],description=changes['description'])


def variant(skill, actor, target):
    info=rule(skill,actor,target)
    return replace(skill,**info['changes']) if info and info['ready'] else skill


def info(skill, actor, target=None):
    data=rule(skill,actor,target)
    if not data:return None
    c=data['changes']
    return dict(name=c.get('name',skill.name),min_level=data['min_level'],condition=data['condition'],
        description=data['description'],cost=c.get('cost',skill.cost),power=c.get('power',skill.power),
        final_ready=data['ready'],active=False,specialization=True,mastery=True)


def modifiers(actor, target, skill):
    if path(actor) != 'base' or skill.class_id != actor['class_id']:return 0,1.0
    m, cls = actor.get('mastery_state',{}), actor['class_id']
    accuracy, multiplier = 0,1.0
    if 'mastery_cute_combo' in skill.tags:multiplier*=1.45 if actor['level']>=12 else 1.35
    if 'mastery_flow' in skill.tags:multiplier*=1+.25*m.get('flow',0)
    if 'mastery_articles' in skill.tags:
        multiplier*=1+.10*min(3,len({e['kind'] for e in target['effects'] if e.get('mastery_owner')==actor.get('controller_id') and e.get('value',0)<0}))
    if cls=='pinky' and actor['level']>=12 and skill.damage_type:accuracy+=5
    if cls=='priest' and skill.skill_id=='holy_judgment' and m.get('mercy_ready'):multiplier*=1.50 if actor['level']>=12 else 1.40
    if 'mastery_hunt' in skill.tags:
        multiplier*=1.35
        if actor['level']>=12:accuracy+=10
    if cls=='hunter' and skill.damage_type and m.get('hunt_chain',0)>0 and actor.get('own_turns',0)<m.get('hunt_until',0):multiplier*=1.45
    return accuracy,multiplier


def obeys(actor, skill):
    return bool(path(actor)=='base' and actor['class_id']=='index' and actor.get('mastery_state',{}).get('free_prescript') and skill.class_id=='index' and skill.damage_type)


def after_action(actor, target, skill, hit, damage, before, obeyed, allies=None):
    mode=path(actor)
    if not mode:return []
    m=actor.setdefault('mastery_state',{})
    old, mechanics, rpg=before['memory'],before['mechanics'],before['rpg']
    def refund(n):actor['resource']=min(actor['stats']['resource_max'],actor['resource']+n)
    def restore(e):
        if not any((x.get('id'),x['kind'])==(e.get('id'),e['kind']) for x in target['effects']):target['effects'].append(deepcopy(e))
    if mode=='branch':
        if actor['archclass_id']=='hunter_moon' and skill.skill_id=='hunter_shot' and hit:
            m.pop('moon_extension_used',None)
        if 'mastery_branch' not in skill.tags:return []
        key=actor['archclass_id'];r=actor.setdefault('rpg_state',{});mec=actor.setdefault('mechanics',{})
        if hit:
            # The native optimize tag already removes one cooldown action.
            if key=='programmer':actor['cooldowns']={k:max(0,v-1) if k!=skill.skill_id else v for k,v in actor['cooldowns'].items()}
            if key=='thumb_execution':mec['order']=0
            if key in ('middle_guardian','middle_revenge'):mec['grudge']=max(0,mechanics.get('grudge',0)-1)
            if key in ('pinky_dihui','pinky_tiansha'):mec['focus']=max(0,mechanics.get('focus',0)-1)
            if key=='index_messenger':refund(10)
            if key=='warrior_berserker':r['onslaught']=1
            if key=='warrior_knight':r['steadfast']=max(0,rpg.get('steadfast',0)-1)
            if key=='mage_necromancer':
                r['souls']=1
                if actor['hp']>0:actor['hp']=min(actor['stats']['max_hp'],actor['hp']+round(damage*.10))
            if key=='mage_elementalist':
                for e in before['effects']:
                    if e['kind']=='burn':restore(dict(e,duration=1))
            if key=='priest_bishop':r['faith']=1
            if key=='priest_paladin':r['retribution']=max(0,rpg.get('retribution',0)-1)
            if key=='hunter_beast':r['beast']=1
            if key=='hunter_moon' and not old.get('moon_extension_used'):
                r['visceral_ready']=True;r['visceral_until']=actor['own_turns']+1;m['moon_extension_used']=True
        return ['Совершенное владение ветвью']
    cls,sid,level=actor['class_id'],skill.skill_id,actor['level']
    native=skill.class_id==cls
    # One source-owned marker per effect. Never counts another raider's setup.
    if hit and (native or cls in ('ring','thumb')):
        applied={(e.get('id'),e['kind']) for e in skill.effects if e.get('target')=='enemy'}
        for e in target['effects']:
            if (e.get('id'),e['kind']) in applied:e['mastery_owner']=actor.get('controller_id')
    if cls in ('ragamuffin','warrior') and native:
        if 'mastery_street_final' in skill.tags or 'mastery_execute' in skill.tags:
            if hit:m['combo']=[]
        elif sid not in old.get('combo',[]):m['combo']=(old.get('combo',[])+[sid])[-3:]
    if cls=='ragamuffin':
        if native and not skill.damage_type and hit or sid=='mastery_ragamuffin' and hit:m['street_ready']=True
        elif native and skill.damage_type and hit:m['street_ready']=False
        if 'mastery_street_final' in skill.tags and hit:refund(20)
    elif cls=='cutie' and sid in ('uwu','meow'):m['last_cute']=sid
    elif cls=='jock':
        if 'mastery_prepared' in skill.tags and hit:buff(actor,'mastery_lift_guard','incoming_damage_multiplier',.8,1)
        if sid=='mastery_jock' and hit:buff(actor,'evolution_prepared','prepared_attack',1,2)
    elif cls=='nerd' and native:
        if 'mastery_theory' in skill.tags:
            m.update(theory_ready=False,theory_steps=[])
            if hit and sid=='go_to_store':refund(30 if final_base(actor) else 20 if level>=12 else 15)
        elif not old.get('theory_ready'):
            category='debuff' if sid=='doxxing' else 'attack' if skill.damage_type else 'support'
            steps=old.get('theory_steps',[])
            if category not in steps:steps=steps+[category]
            m.update(theory_steps=steps,theory_ready=len(steps)>=3)
    elif cls=='thumb' and sid=='warning_shot':
        actor.setdefault('mechanics',{})['order']=min(2 if level>=12 else 1,mechanics.get('order',0)) if hit else mechanics.get('order',0)
    elif cls=='index':
        if sid=='mastery_index':m['free_prescript']=True
        elif native and skill.damage_type:m['free_prescript']=False
        if 'mastery_written' in skill.tags:
            if hit:m['executions']=0
        elif obeyed:m['executions']=min(2,old.get('executions',0)+1)
        if obeyed:refund(12 if level>=12 else 8)
    elif cls=='middle':
        if sid in ('answer_for_it','whole_family'):
            actor.setdefault('mechanics',{})['grudge']=min(2 if level>=12 else 1,mechanics.get('grudge',0)) if hit else mechanics.get('grudge',0)
        if sid=='mastery_middle' and hit:actor.setdefault('mechanics',{})['grudge']=min(3,mechanics.get('grudge',0)+1)
        if 'mastery_family' in skill.tags and hit:buff(actor,'mastery_family_guard','incoming_damage_multiplier',.75,1)
    elif cls=='ring' and sid=='last_stroke' and hit:
        effects=[e for e in before['effects'] if e.get('mastery_owner')==actor.get('controller_id') and e.get('duration',0)<10000 and (e.get('value',0)<0 or e['kind']=='bleed')]
        for e in effects[:2 if level>=12 else 1]:
            target['effects']=[x for x in target['effects'] if (x.get('id'),x['kind'])!=(e.get('id'),e['kind'])];restore(e)
    elif cls=='pinky' and native and hit and skill.damage_type and 'consume_focus' not in skill.tags:
        if sid=='mastery_pinky' or mechanics.get('last_attack') not in (None,sid):
            actor.setdefault('mechanics',{})['focus']=min(3,actor['mechanics'].get('focus',0)+1)
    elif cls=='mage':
        if 'mastery_flow' in skill.tags and hit:
            m['flow']=0
            if 'mastery_flow_refund' in skill.tags:refund(20)
        elif 'mastery_flow_guard' in skill.tags:
            m['flow']=0
            if level>=12:refund(10)
        elif native and skill.damage_type=='magic':m['flow']=min(3,old.get('flow',0)+1)
        if sid=='mastery_mage' and hit:refund(15)
    elif cls=='priest' and native:
        useful=hit and (damage>0 or actor['hp']>before['hp'] or any(e['kind']=='incoming_damage_multiplier' for e in skill.effects)
            or sid in ('priest_heal','mastery_priest') and before.get('ally_healed'))
        if 'mastery_miracle' in skill.tags:
            if hit:m['prayers']=0
        elif useful:m['prayers']=min(3,old.get('prayers',0)+1)
        if sid in ('priest_heal','mastery_priest') and useful:m['mercy_ready']=True
        if sid=='holy_judgment' and hit:
            m['mercy_ready']=False;m['healing_ready']=True
        elif sid in ('priest_heal','mastery_priest') and hit and old.get('healing_ready'):m['healing_ready']=False
    elif cls=='hunter' and native:
        if sid in ('hunter_transform','mastery_hunter') and hit:m['hunt_ready']=True
        elif 'mastery_hunt' in skill.tags and hit:m['hunt_ready']=False
        active=old.get('hunt_chain',0)>0 and actor['own_turns']-1<old.get('hunt_until',0)
        if skill.damage_type and active:m['hunt_chain']=max(0,old['hunt_chain']-1)
        if sid=='hunter_visceral' and hit and final_base(actor) and not active:
            m.update(hunt_chain=2,hunt_until=actor['own_turns']+3)
    return []
