"""Level-20 humour/Fingers paths. Pure variants; JSON-only per-battle memory.

No extra skill/passive slots, recursive attacks, or permanent profile counters.
All multi-hit attacks use one action's damage/proc budget in the native engine.
"""
from copy import deepcopy
from dataclasses import replace

from arena_fingers import negative_kinds


FINALS = {
    'femboy': ('cutie','Искуситель натурала','Разные родные попадания и умиление собирают 3 Смущения. Воздушный поцелуй расходует их на «Ты же говорил, что не поведёшься»: сила 28, 35 энергии, магическая уязвимость +20% на 2 действия цели.'),
    'princess': ('cutie','Королева милоты','Попадание врага или уклонение дают Каприз, максимум 3 и один за действие. При 2 Капризах поцелуй превращается в «Казнить нельзя помиловать» (сила 25, 30 энергии), а позирование — в «Помиловать себя» (щит −40% прямого урона на 2 своих действия, 25 энергии). Расходуются 2 Каприза.'),
    'gachi_actor': ('jock','Dungeon Master','Зажим даёт 2 Захвата, напряжение — 1, максимум 3. При 3 Захватах «Въебать» становится «Теперь моя очередь»: сила 28, 35 энергии, следующий урон цели −30%. Расход при попадании; защита или очищение противника сбивают 1 Захват.'),
    'mge_bro': ('jock','Мге-легенда','Разные родные атаки собирают 3 Доминирования даже при промахе. «Жопный пик» становится «Билет в паровозик»: 3 независимых попадания, суммарная сила 36, цена 50, доли урона 20/30/50%, последний удар игнорирует 50% защиты. Расход Доминирования при любом попадании; своя физическая защита −20% на 1 действие.'),
    'programmer': ('nerd','Архитектор костылей','3 разных родных навыка компилируют программу. Зарядка становится «В продакшене разберёмся»: следующий родной навык выбирает один режим — магическая атака +50% урона, Деанон сокращает прочие перезарядки на 2, магазин дополнительно возвращает 20 энергии. Программа действует 3 своих действия, не собирается заново до расхода.'),
    'hacker': ('nerd','Рут-админ','Деанон и разные родные атаки по взломанному врагу дают до 3 Доступа. При 3 Доступа «Отказ в обслуживании» становится «sudo rm -rf /самооценка»: сила 28, 40 энергии, обе защиты −25% на 2 действия, следующий платный навык цели дороже на 15. Расход при попадании; бесплатные атаки остаются бесплатными.'),
    'thumb_discipline': ('thumb','Соттокапо: Дисциплина','3 разных родных действия дают Приказ. Предупредительный выстрел превращается в «Устав написан кровью»: сила 17, 30 энергии, урон цели −25% на 2 действия и защита от прямого урона −25% себе и одному раненому союзнику на 1 своё действие. Приказ расходуется при попадании.'),
    'thumb_execution': ('thumb','Соттокапо: Расстрел','3 разных родных выстрела/приёма отмечают Зоны поражения. Приговор становится «Приговор окончательный»: 3 независимых выстрела с суммарной силой 34, цена 50, последний игнорирует 60% защиты. Подготовка расходуется при попадании; обычный бонус Субординации второй раз не начисляется.'),
    'index_proxy': ('index','Прокси: Безупречный исполнитель','2 исполненных собственных предписания готовят «Так было предписано»: Последняя строка получает силу 30, пробитие 55%, цену 45. Попадание расходует подготовку; полный промах возвращает 15 Воли. Повторный запрос собственного предписания позволяет один раз заменить его до исполнения.'),
    'index_messenger': ('index','Посланник: Глас предписания','Чужое предписание допускает 2 доступные атаки. Исполнение возвращает Посланнику 5 Воли, нарушение даёт 1 Вину (максимум 3) и прежний штраф энергии. При 2 Вины «Непрошеный совет» становится «От исполнения не освобождает»: магическая сила 26, 35 энергии, урон цели −20% на 2 действия; расход 2 Вины при попадании.'),
    'middle_guardian': ('middle','Великий брат: Опора семьи','Полученный прямой урон собирает до 3 Стойкости, не чаще раза за действие врага. «Семья прикроет» становится «Пока я стою — семья жива»: 30 энергии, защита себе; в рейде принимает 30% прямого урона раненого союзника в течение 2 его действий. При 3 Стойкости «За всю семью» становится ответным ударом силы 30 за 45 энергии, расход при попадании.'),
    'middle_revenge': ('middle','Великий брат: Книга мести','Реально полученный прямой урон записывается в Кровный долг, максимум собственный максимум HP. При долге от 25% max HP «За всю семью» становится «Долг передаётся по наследству»: сила 28, 50 энергии, кровотечение 6 на 3 действия; дополнительно до +50% урона от долга. Самоурон 20% снятого HP сохраняется и не создаёт долг.'),
    'ring_pointillist': ('ring','Маэстро-пуантилист','При 3 разных типах ослаблений на цели Красный этюд становится «Тысячная точка»: 6 независимых попаданий с суммарной силой 25 за 35 энергии. Одна проверка 75% на кровотечение 6 на 3 действия, а не шесть запусков пассивок и питомца.'),
    'ring_fauvist': ('ring','Маэстро-фовист','«Чучело хищника» призывает одного слугу на 3 следующих собственных действия. После поддержки слуга прикрывает хозяина на 20%, после родной атаки бьёт один раз; замедленная цель получает больше урона, защита ослабленной цели частично игнорируется. При слуге и 3 ослаблениях Последний штрих становится «Природа исправит тебя»: сила 30, 2 удара, 45 энергии. Слуга не запускает пассивки, питомца и новые атаки.'),
    'pinky_dihui': ('pinky','Звезда Дихуэй: Безлунная ночь','Атака врага в защитную стойку или уклонение подготавливают Контрстойку на 2 собственных действия. Лунная дуга становится «Луна уже за твоей спиной»: сила 26, точность 100%, пробитие 65%, цена 30. Расход стойки и до 2 Созвездий только при попадании; этот удар не критует.'),
    'pinky_tiansha': ('pinky','Звезда Тяньган: Раскол небес','При 3 Созвездиях Падающая звезда становится «Небо не выдержало»: сила 34, 60 энергии, 50% пробития, прежний шанс крита до 75%. Расходует 2 Созвездия только при попадании. После попадания получает на 20% больше прямого урона до своего следующего действия.'),
}


def branch(side):
    key = side.get('archclass_id','')
    spec = FINALS.get(key)
    return key if (spec and spec[0] == side.get('class_id') and side.get('level',0) >= 20
                   and side.get('archclass_stage',20) >= 20) else ''


def buff(side, key, kind, value, duration, **extra):
    side['effects'] = [e for e in side['effects'] if e.get('id') != key]
    side['effects'].append(dict(id=key,kind=kind,value=value,duration=duration,**extra))


def context(actor, target):
    return dict(memory=deepcopy(actor.get('final_state',{})),
                negatives=len(negative_kinds(target)),
                adored=any(e.get('id')=='adoration' for e in target.get('effects',[])),
                hacked=any(e.get('id')=='doxxing_magic' for e in target.get('effects',[])),
                obeyed=actor.get('mechanics',{}).get('prescript'))


def rule(skill, actor, target=None):
    """Return the final transformation even while locked, for truthful tooltips."""
    key, sid = branch(actor), skill.skill_id
    if not key or skill.class_id != actor.get('class_id'):return None
    m = actor.get('final_state',{})
    ready, change = False, None
    def tag(name):return skill.tags + (name,)
    if key=='femboy' and sid=='air_kiss':
        ready=m.get('shame',0)>=3
        change=dict(name='Ты же говорил, что не поведёшься',power=28,cost=35,
                    effects=(dict(id='final_charm_weakness',kind='damage_taken_pct',value=.20,turns=2,target='enemy',chance=1),),tags=tag('final_charm'))
    elif key=='princess' and sid in ('air_kiss','posing'):
        ready=m.get('whim',0)>=2
        change=(dict(name='Казнить нельзя помиловать',power=25,cost=30,tags=tag('final_whim')) if sid=='air_kiss' else
                dict(name='Помиловать себя',cost=25,effects=(dict(id='final_royal_guard',kind='incoming_damage_multiplier',value=.60,turns=2,target='self',chance=1),),tags=tag('final_whim')))
    elif key=='gachi_actor' and sid=='smack':
        ready=m.get('grip',0)>=3
        change=dict(name='Теперь моя очередь',power=28,cost=35,
                    effects=(dict(id='final_throw',kind='damage_pct',value=-.30,turns=1,target='enemy',chance=1),),tags=tag('final_throw'))
    elif key=='mge_bro' and sid=='butt_peak':
        ready=m.get('dominance',0)>=3
        change=dict(name='Билет в паровозик',power=36,cost=50,accuracy=90,pierce=0,
                    tags=tag('final_train')+('three_strike',))
    elif key=='programmer' and sid=='charging':
        ready=m.get('compiled',False)
        # Keep the native charge/discount: compilation adds a choice on top of
        # Hotfix, rather than downgrading its +60% preparation to +50%.
        change=dict(name='В продакшене разберёмся',tags=tag('final_program_start'))
    elif key=='programmer' and m.get('program_until',0)>actor.get('own_turns',0):
        if skill.damage_type:
            ready=True;change=dict(name=skill.name+' · аварийный патч',tags=tag('final_program_attack'))
        elif sid=='doxxing':
            ready=True;change=dict(name='Откат в продакшене',tags=tag('final_program_cooldown'))
        elif sid=='go_to_store':
            ready=True;change=dict(name='Починить энергетиком',tags=tag('final_program_resource'))
    elif key=='hacker' and sid=='arch_hacker':
        ready=m.get('access',0)>=3
        change=dict(name='sudo rm -rf /самооценка',power=28,cost=40,
            effects=tuple(dict(id='final_root_'+d,kind=d+'_defense_pct',value=-.25,turns=2,target='enemy',chance=1) for d in ('physical','magic'))+
            (dict(id='final_root_tax',kind='skill_cost_flat',value=15,turns=3,target='enemy',chance=1),),tags=tag('final_root'))
    elif key=='thumb_discipline' and sid=='warning_shot':
        ready=m.get('command',0)>0
        change=dict(name='Устав написан кровью',power=17,cost=30,tags=tag('final_command'),
                    effects=(dict(id='final_code',kind='damage_pct',value=-.25,turns=2,target='enemy',chance=1),))
    elif key=='thumb_execution' and sid=='senior_verdict':
        ready=len(m.get('zones',[]))>=3
        change=dict(name='Приговор окончательный',power=34,cost=50,pierce=0,
                    tags=('three_strike','no_order_bonus','final_execution'),effects=skill.effects)
    elif key=='index_proxy' and sid=='last_line':
        ready=m.get('execution',0)>=2
        change=dict(name='Так было предписано',power=30,cost=45,accuracy=95,pierce=.55,tags=tag('final_prescribed'))
    elif key=='index_messenger' and sid=='arch_index_messenger':
        ready=m.get('guilt',0)>=2
        change=dict(name='От исполнения не освобождает',damage_type='magic',power=26,cost=35,
            effects=(dict(id='final_guilt',kind='damage_pct',value=-.20,turns=2,target='enemy',chance=1),),tags=tag('final_guilt'))
    elif key=='middle_guardian' and sid=='arch_middle_guardian':
        ready=True
        change=dict(name='Пока я стою — семья жива',tags=tag('final_cover'))
    elif key=='middle_guardian' and sid=='whole_family':
        ready=m.get('steadfast',0)>=3
        change=dict(name='За нами вся семья',power=30,cost=45,tags=tag('final_steadfast'))
    elif key=='middle_revenge' and sid=='whole_family':
        ready=m.get('blood_debt',0)>=actor.get('stats',{}).get('max_hp',1)*.25
        change=dict(name='Долг передаётся по наследству',power=28,cost=50,
            effects=(dict(id='final_bloodline',kind='bleed',value=6,turns=3,target='enemy',chance=1),),tags=tag('final_bloodline'))
    elif key=='ring_pointillist' and sid=='red_etude':
        ready=bool(target and len(negative_kinds(target))>=3)
        change=dict(name='Тысячная точка',power=25,cost=35,tags=tag('final_points')+('six_strike',),
            effects=(dict(id='bleed',kind='bleed',value=6,turns=3,target='enemy',chance=.75),))
    elif key=='ring_fauvist' and sid=='arch_ring_fauvist':
        ready=True;change=dict(name='Сшить хищника',tags=tag('final_summon'))
    elif key=='ring_fauvist' and sid=='last_stroke':
        ready=bool(m.get('beast',0)>0 and target and len(negative_kinds(target))>=3)
        change=dict(name='Природа исправит тебя',power=30,cost=45,
                    tags=('two_strike','final_joint'))
    elif key=='pinky_dihui' and sid=='moon_arc':
        ready=m.get('counter_until',0)>actor.get('own_turns',0)
        change=dict(name='Луна уже за твоей спиной',power=26,cost=30,accuracy=100,pierce=.65,
                    tags=('consume_focus','no_critical','final_counter'))
    elif key=='pinky_tiansha' and sid=='falling_star':
        ready=actor.get('mechanics',{}).get('focus',0)>=3
        change=dict(name='Небо не выдержало',power=34,cost=60,pierce=.50,tags=('consume_focus','final_heaven'))
    if change is None:return None
    conditions={
        'final_charm':'Накоплены 3 Смущения', 'final_whim':'Накоплены 2 Каприза',
        'final_throw':'Накоплены 3 Захвата', 'final_train':'Накоплены 3 Доминирования',
        'final_program_start':'Скомпилированы 3 разных родных навыка',
        'final_program_attack':'Действует программа: следующий навык — магическая атака',
        'final_program_cooldown':'Действует программа: следующий навык — Деанон',
        'final_program_resource':'Действует программа: следующий навык — магазин',
        'final_root':'Накоплены 3 Доступа', 'final_command':'Подготовлен Приказ',
        'final_execution':'Подготовлены 3 разные Зоны поражения',
        'final_prescribed':'Исполнены 2 собственных предписания',
        'final_guilt':'Накоплены 2 Вины за нарушения предписаний',
        'final_cover':'Выбрана финальная ступень Опоры семьи',
        'final_steadfast':'Накоплены 3 Стойкости',
        'final_bloodline':'Кровный долг не меньше 25% максимального HP',
        'final_points':'На цели 3 разных типа отрицательных эффектов',
        'final_summon':'Выбрана финальная ступень Фовиста',
        'final_joint':'Живо чучело; на цели 3 разных ослабления',
        'final_counter':'Открыта Контрстойка после атаки врага в защиту или уклонения',
        'final_heaven':'Накоплены 3 Созвездия',
    }
    marker=next(t for t in change['tags'] if t in conditions)
    descriptions={
        'final_whim':('Сила 25 за 30 энергии; расходует 2 Каприза при попадании.' if sid=='air_kiss' else
                      'За 25 энергии расходует 2 Каприза; прямой урон −40% на 2 своих действия.'),
        'final_program_attack':'Магическая атака +50% урона; программа расходуется даже при промахе.',
        'final_program_cooldown':'При попадании Деанона остальные перезарядки −2. Программа расходуется при попытке.',
        'final_program_resource':'Магазин возвращает дополнительно 20 энергии и расходует программу. Действие тратится.',
        'final_cover':'Сохраняет атаку; защита хозяина от 25% прямого урона на 2 действия. В рейде принимает 30% прямого урона одного раненого союзника в течение 2 действий союзника.',
        'final_steadfast':'Сила 30 за 45 энергии; расходует 3 Стойкости только при попадании.',
        'final_summon':'Сохраняет атаку и призывает одно чучело на 3 следующих действия; повторный призыв заменяет слугу. Поддержка хозяина готовит защиту, родная атака вызывает один укус без запуска пассивок и питомца.',
        'final_joint':'45 энергии; 2 независимых попадания с суммарной силой 30. Заменяет обычный укус чучела, не добавляет третью атаку.',
        'final_counter':'Сила 26 за 30 энергии, точность 100% до уклонения (предел попадания 95%), пробитие 65%. Расход стойки и до 2 Созвездий только при попадании; не критует.',
    }
    return dict(name=change.pop('name'),changes=change,ready=ready,min_level=20,
                condition=conditions[marker],description=descriptions.get(marker,FINALS[key][2]),specialization=True)


def variant(skill, actor, target):
    entry=rule(skill,actor,target)
    return replace(skill,name=entry['name'],description=entry['description'],**entry['changes']) if entry and entry['ready'] else skill


def modifiers(actor, skill):
    if 'final_program_attack' in skill.tags:return .50
    if 'final_bloodline' in skill.tags:
        return min(.50, .50*actor.get('final_state',{}).get('blood_debt',0)/max(1,actor['stats']['max_hp']))
    return 0


def owner(raid, target, source):
    if target.get('controller_id')==source and target.get('hp',0)>0:return target
    if raid:
        return next((p['fighter'] for p in raid['players'].values()
                     if not p.get('withdrawn') and p['fighter'].get('controller_id')==source and p['fighter']['hp']>0),None)
    return None


def incoming(target, damage, attacker, raid=None):
    """Redirect only actual direct damage, never DOT/recoil/another redirect."""
    shield=next((e for e in target['effects'] if e.get('id')=='final_family_cover'),None)
    if shield and damage>0:
        source=owner(raid,attacker,shield.get('source'))
        if source is not None and source is not target and branch(source)=='middle_guardian':
            amount=min(source['hp'],round(min(damage,target['hp'])*.30))
            source['hp']-=amount
            sm=source.setdefault('final_state',{})
            claim=[attacker.get('controller_id'),attacker.get('own_turns',0)]
            if amount and sm.get('received_action')!=claim:
                sm.update(received_action=claim,steadfast=min(3,sm.get('steadfast',0)+1))
            damage-=amount
    return damage


def received(target, actor, skill, hit, dodged, damage):
    key=branch(target)
    if not key or not skill.damage_type:return
    m=target.setdefault('final_state',{})
    claim=[actor.get('controller_id'),actor.get('own_turns',0)]
    if m.get('received_action')==claim:return
    m['received_action']=claim
    if key=='princess' and (damage>0 or dodged):m['whim']=min(3,m.get('whim',0)+1)
    elif key=='middle_guardian' and damage>0:m['steadfast']=min(3,m.get('steadfast',0)+1)
    elif key=='middle_revenge' and damage>0:m['blood_debt']=min(target['stats']['max_hp'],m.get('blood_debt',0)+damage)
    elif key=='pinky_dihui' and (dodged or any(
            e.get('kind') in ('incoming_damage_multiplier','physical_defense_pct','magic_defense_pct')
            and (e.get('value',0)>0 if e['kind']!='incoming_damage_multiplier' else e.get('value',1)<1)
            for e in target['effects'])):
        m['counter_until']=target.get('own_turns',0)+2


def after_action(actor,target,skill,hit,damage,before,rng,stat,allies=None,skills=None):
    key=branch(actor)
    if not key:return []
    m=actor.setdefault('final_state',{})
    old=before['memory'];sid=skill.skill_id;native=skill.class_id==actor['class_id']
    notes=[]
    if key=='femboy' and native:
        if hit and 'final_charm' in skill.tags:m['shame']=0
        elif hit and (any(e.get('id')=='adoration' for e in target['effects']) or skill.damage_type) and old.get('last')!=sid:
            m['shame']=min(3,old.get('shame',0)+1)
    if key=='princess' and hit and 'final_whim' in skill.tags:m['whim']=max(0,old.get('whim',0)-2)
    if key=='gachi_actor' and native and hit:
        if 'final_throw' in skill.tags:m['grip']=0
        elif sid in ('clench','flex_chest'):m['grip']=min(3,old.get('grip',0)+(2 if sid=='clench' else 1))
    if key=='mge_bro' and native and skill.damage_type:
        if 'final_train' in skill.tags:
            if hit:m['dominance']=0
        elif old.get('last_attack')!=sid:m['dominance']=min(3,old.get('dominance',0)+1)
        m['last_attack']=sid
    if key=='programmer' and native:
        if 'final_program_start' in skill.tags:
            m.update(compiled=False,compile_steps=[],program_until=actor.get('own_turns',0)+3)
        elif any(t.startswith('final_program_') for t in skill.tags):
            m['program_until']=0
            if 'final_program_cooldown' in skill.tags and hit:
                actor['cooldowns']={k:v-2 for k,v in actor['cooldowns'].items() if v>2}
            if 'final_program_resource' in skill.tags:actor['resource']=min(actor['stats']['resource_max'],actor['resource']+20)
        elif not old.get('compiled') and old.get('program_until',0)<=actor.get('own_turns',0):
            steps=list(dict.fromkeys(old.get('compile_steps',[])+[sid]))[-3:]
            m.update(compile_steps=steps,compiled=len(steps)>=3)
    if key=='hacker' and native and hit:
        if 'final_root' in skill.tags:m['access']=0
        elif sid=='doxxing' or (skill.damage_type and before['hacked'] and old.get('last')!=sid):
            m['access']=min(3,old.get('access',0)+1)
    if key in ('thumb_discipline','thumb_execution') and native:
        spent='final_command' in skill.tags or 'final_execution' in skill.tags
        if spent and hit:m.update(command=0,zones=[])
        elif not spent:
            zones=list(dict.fromkeys(old.get('zones',[])+[sid]))[-3:]
            m.update(zones=zones,command=int(len(zones)>=3))
    if key=='index_proxy' and native:
        if 'final_prescribed' in skill.tags:
            if hit:m['execution']=0
            else:actor['resource']=min(actor['stats']['resource_max'],actor['resource']+15)
        elif before['obeyed']==sid:
            m['execution']=min(2,old.get('execution',0)+1);m['rerolled']=False
        if sid=='receive_prescript' and before['obeyed']:
            if old.get('rerolled'):actor.setdefault('mechanics',{})['prescript']=before['obeyed']
            else:
                from arena_evolution import skill_variant
                from arena_engine import skill_restriction
                from arena_mirror_effects import gift_cost
                from arena_pets import pet_cost
                choices=[]
                for candidate in actor.get('loadout',[]):
                    if not skills or candidate not in skills or candidate==before['obeyed'] or actor['cooldowns'].get(candidate):continue
                    v=skill_variant(skills[candidate],actor,target,actor.get('own_turns',0))
                    if v.damage_type and not skill_restriction(actor,v) and pet_cost(actor,v,gift_cost(actor,v))<=actor['resource']:choices.append(candidate)
                actor.setdefault('mechanics',{})['prescript']=rng.choice(choices) if choices else before['obeyed']
                m['rerolled']=bool(choices)
    if key=='index_messenger' and hit and 'final_guilt' in skill.tags:m['guilt']=max(0,old.get('guilt',0)-2)
    if key=='middle_guardian':
        if hit and 'final_cover' in skill.tags:
            buff(actor,'final_family_guard','incoming_damage_multiplier',.75,2)
            living=[s for s in (allies or []) if s is not actor and s['hp']>0]
            if living:
                friend=min(living,key=lambda s:s['hp']/s['stats']['max_hp'])
                buff(friend,'final_family_cover','family_cover',.30,2,source=actor.get('controller_id'))
                notes.append('прикрывает раненого союзника')
        if hit and 'final_steadfast' in skill.tags:m['steadfast']=0
    if key=='middle_revenge' and hit and 'final_bloodline' in skill.tags:m['blood_debt']=0
    if key=='thumb_discipline' and hit and 'final_command' in skill.tags:
        buff(actor,'final_code_guard','incoming_damage_multiplier',.75,1)
        living=[s for s in (allies or []) if s is not actor and s['hp']>0]
        if living:buff(min(living,key=lambda s:s['hp']/s['stats']['max_hp']),'final_code_guard','incoming_damage_multiplier',.75,1)
    if key=='ring_fauvist':
        if hit and 'final_summon' in skill.tags:
            m['beast']=3;notes.append('призвано чучело на 3 следующих действия')
        elif old.get('beast',0)>0:
            m['beast']=max(0,old['beast']-1)
            if native and not skill.damage_type:
                buff(actor,'final_beast_guard','incoming_damage_multiplier',.80,1)
                notes.append('чучело прикрывает хозяина')
            elif native and 'final_joint' not in skill.tags and target['hp']>0 and actor['hp']>0:
                chance=max(5,min(95,95-stat(target,'evasion')))
                if rng.random()*100<chance:
                    weakened=len(negative_kinds(target))>=2
                    slow=any(e['kind']=='speed_pct' and e['value']<0 for e in target['effects'])
                    armor=stat(target,'physical_defense')*(.5 if weakened else 1)
                    guard=1
                    for effect in target['effects']:
                        if effect['kind']=='incoming_damage_multiplier':guard*=max(.1,effect.get('value',1))
                    bite=min(target['hp'],max(1,round(6*(1+stat(actor,'magic_attack')/20)*100/(100+4*armor)*(1.4 if slow else 1)*guard)))
                    target['hp']-=bite;notes.append(f'Чучело хищника: −{bite} HP')
                else:notes.append('Чучело хищника: промах')
    if key=='pinky_dihui' and hit and 'final_counter' in skill.tags:m['counter_until']=0
    if key=='pinky_tiansha' and hit and 'final_heaven' in skill.tags:
        buff(actor,'final_heaven_open','damage_taken_pct',.20,1)
    if native:m['last']=sid
    return notes


def break_grip(actor, target):
    if branch(target)=='gachi_actor':
        m=target.get('final_state',{})
        m['grip']=max(0,m.get('grip',0)-1)


def cost_tax(side, skill):
    return max((max(0,int(e.get('value',0))) for e in side.get('effects',[]) if e.get('kind')=='skill_cost_flat'),default=0) if skill.cost else 0
