"""Nazarick gauntlet. Combat-local progression only; no saved stage unlocks."""
from copy import deepcopy
import random

from arena_engine import Skill, _tick, effective_stat, restore_turn_resource, bleeding_damage

ORDER = ('shalltear', 'demiurge', 'albedo', 'pandora', 'ainz')
NAMES = dict(shalltear='Шалтир — Кровавая валькирия', demiurge='Демиург — Архитектор ада',
             albedo='Альбедо — Последняя преграда', pandora='Аинз Оал Гоун', ainz='Аинз Оал Гоун — Король-колдун')
TITLES = {
    'shalltear': (('Кровавые нити', 'Пир вампира', 'Алый взгляд'), ('Копьё-пипетка', 'Эйнхерий', 'Кровавое безумие')),
    'demiurge': (('Адская геометрия', 'Приказ: преклониться', 'Предусмотренный маршрут'), ('Адское пламя', 'Двойной замысел', 'Исполнители')),
    'albedo': (('Чёрное крыло', 'Не приближайся', 'Неприступность'), ('Раскол', 'Крылья крепости', 'Последняя преграда')),
    'pandora': (('Театральная молния', 'Поддельная бездна', 'Репетиция смерти'), ('Украденный выпад', 'Смена масок', 'Финальный поклон')),
    'ainz': (('Семь камней посоха', 'Чёрная дыра', 'Призыв нежити'), ('Остановка времени', 'Цель всей жизни — смерть', 'Посох: небесный приговор')),
    'knight': (('Клинок рыцаря смерти',),), 'lich': (('Костяной залп',),),
    'hellguard': (('Адский клинок',),), 'pyromancer': (('Пламя исполнителя',),),
}
HINTS = {
    'shalltear': ('Кровавые иглы и мыши некоторое время преследуют вас, затем летят прямо. Алый взгляд — два луча из глаз над ареной.', 'Кровавые копья выстреливают по отмеченным траекториям. Двойник повторяет выпад с задержкой.'),
    'demiurge': ('Красные отрезки предвещают рассечение. Читай надпись: спасает «ПУТЬ», а не «ЛОВУШКА». Цвет и размер не подсказывают ответ. Проклятия снижают исходящий урон на 12% на три действия.', 'Огонь поджигает: 3 HP на два действия. Печати ослабляют. Демиург предсказывает направление движения; меняйте маршрут.'),
    'albedo': ('Разрушьте стойку уроном. После её разрушения Альбедо уязвима до конца следующего раунда.', 'После тяжёлого удара приходят трещины; крылья сужают проход. Разрушенная стойка ослабляет последний удар.'),
    'pandora': ('Ослабленные подражания магии Аинза: медленные молнии, небольшая бездна и объявленное рассечение смерти.', 'Маскировка снята. Актёр Пандоры использует театральные маски и копирует боевые приёмы, не получая всего арсенала Аинза.'),
    'ainz': ('Семь камней — семь отдельных испытаний по очереди: огонь, молния, бездна, яд, свет, печати, кости. Цветные снаряды накладывают свой эффект. Рыцарь прикрывает Аинза, заклинатель усиливает его.', 'Парящий посох выпускает цветные камни и спирали. Остановка времени повторяется дважды: после каждого освобождения есть 0,65 секунды на уход. В ритуале спасает пентаграмма «СМЕРТЬ», а «ЖИЗНЬ» — обман; различаются только надписи.'),
}
QUOTES = {
    'shalltear': ('Постарайтесь не умереть слишком некрасиво.', 'Довольно игр. Теперь вы увидите валькирию.', 'Кровь должна течь, а не пропадать зря.'),
    'demiurge': ('Благодарю. Вы выбрали именно тот путь, который требовался.', 'Теперь, когда приготовления завершены, начнём.', 'Ваш следующий шаг тоже учтён.'),
    'albedo': ('Перед этими дверями закончится ваш путь.', 'Вы не заслужили даже его взгляда.', 'Дальше вы не пройдёте.'),
    'pandora': ('Узрите мою несравненную, совершенно подлинную мощь!', 'Какое великолепное представление!', 'Прошу не обращать внимания на небольшие несоответствия.'),
    'ainz': ('Достаточно. Дальше я сам.', 'Вы хорошо сражались. Теперь узрите разницу.', 'Планирование важнее грубой силы.'),
}
ATTACK_QUOTES = {
    'shalltear': ('Не порвите мои нити раньше времени.', 'Вы ведь не против поделиться кровью?', 'Посмотрите мне в глаза.',
                 'Ваше сердце ещё бьётся? Исправим.', 'Одной меня вам было недостаточно?', 'Тогда танцуйте быстрее!'),
    'demiurge': ('Сначала первая печать. Затем вы поймёте остальное.', 'Преклонитесь. Это не просьба.', 'Именно там я вас и ожидал.',
                 'Пламя — всего лишь часть расчёта.', 'Выход вы нашли. Теперь найдите правильный.', 'Господа, приступайте к работе.'),
    'albedo': ('Не смейте приближаться.', 'Шаг назад.', 'Эту преграду вам не разрушить.',
               'Удар выдержите. А последствия?', 'Ваш путь окончен.', 'Во имя того, кого я защищаю!'),
    'pandora': ('Моя величественная молния! Именно так она и выглядит!', 'Совершенно настоящая высшая магия!', 'Прошу оценить выразительность исполнения.',
                'Эту роль я тоже знаю.', 'Узнаёте знакомые движения?', 'Благодарю за внимание к моему выступлению!'),
    'ainz': ('Каждый камень — ещё один способ закончить этот бой.', 'Попробуйте уйти от самой пустоты.', 'Встаньте и исполните мою волю.',
             'Время — тоже ресурс.', 'Всё живое приходит к одному исходу.', 'Взгляните наверх.'),
}
SKILLS = {}
ATTACK_HINTS={
    'nz_demiurge_p1_2':'Найди пентаграмму «ПУТЬ» до конца отсчёта. «ЛОВУШКА» выглядит так же; размер и цвет не подсказывают ответ. Попадание накладывает проклятие: урон −12% на три действия.',
    'nz_demiurge_p2_1':'Войди в небольшую зелёную пентаграмму. После её закрытия уйди с заранее размеченного рассечения. Линия удара появляется только через 0,49 секунды после проверки укрытия.',
    'nz_ainz_p1_0':'Семь отдельных цветных испытаний по очереди: огонь, шесть молний, бездна, яд, свет, печати, кости. Красный поджигает; синий снижает точность; фиолетовый ослабляет урон; зелёный отравляет; жёлтый повышает получаемый урон; розовый удорожает следующий навык; белый снижает защиты.',
    'nz_ainz_p2_0':'Два цикла остановки времени. Цветные камни и клинки замирают, затем ускоряются. После освобождения есть 0,65 секунды до запуска. При блокировании снаряды движутся до заморозки и продолжают после неё. Цвет камня определяет ослабление.',
    'nz_ainz_p2_1':'Читай надпись: спасает пентаграмма «СМЕРТЬ», а «ЖИЗНЬ» — ловушка. Они одного цвета и одинаково начертаны. Три этапа; успей войти до конца отсчёта. Урон боссу во время подготовки ослабляет ритуал.',
    'nz_ainz_p2_2':'Семь разноцветных камней вращаются по расширяющимся спиралям. Три созвездия дополнены красным лазером, молнией, а затем бездной и розовым лучом. Каждый цвет накладывает своё ослабление; точный блок предотвращает его.',
}
for who, phases in TITLES.items():
    for phase, moves in enumerate(phases, 1):
        for move, title in enumerate(moves):
            sid = f'nz_{who}_p{phase}_{move}'
            power = (18 if who != 'ainz' else 26) + 4 * (phase - 1) + 3 * move
            if who in ('knight', 'lich', 'hellguard', 'pyromancer'):
                power = 7
            dtype = 'physical' if who in ('albedo', 'knight', 'hellguard') or who == 'shalltear' and phase == 2 else 'magic'
            utility = (who, phase, move) in {('albedo', 1, 2), ('demiurge', 2, 2), ('ainz', 1, 2)}
            SKILLS[sid] = Skill(sid, title, 'raid', 1, None if utility else dtype,
                0 if utility else power, 97 if who != 'ainz' else 99, 0, 0,
                description=(ATTACK_HINTS.get(sid,HINTS.get(who, ('Самостоятельная атака призванного существа.',))[min(phase-1, len(HINTS.get(who, (0,)))-1)]) +
                    (' Сценарное действие: призыв/стойка работает только внутри рейда Назарика.' if utility else '')))


def identity(data):
    m = data['nazarick']
    return ORDER[m['stage']], m['phase']


def sprite(who, phase=1):
    key = f'{who}{phase}' if who in ORDER[:3] else ('ainz' if phase==1 else 'pandora') if who == 'pandora' else ('ainz_front' if phase==1 else 'ainz_unbound') if who=='ainz' else who
    return f'/static/assets/nazarick/{key}.png'


def presentation(data):
    who, phase = identity(data)
    m = data['nazarick']
    return dict(stage=m['stage']+1, stage_count=5, guardian=who, phase=phase,
        title='Актёр Пандоры' if who=='pandora' and phase==2 else NAMES[who], phase_name=('Аристократка', 'Кровавая валькирия') [phase-1] if who=='shalltear' else
        ('Стратег', 'Демон за улыбкой')[phase-1] if who=='demiurge' else
        ('Хранительница врат', 'Чёрные доспехи')[phase-1] if who=='albedo' else
        ('Величие', 'Истинное лицо')[phase-1] if who=='pandora' else ('Король-колдун', 'Высшая магия')[phase-1],
        background=f'/static/assets/nazarick/bg_{who}{phase if who in ORDER[:3] else 1}.webp',
        music=f'nz_{who}{phase}', hint=HINTS[who][phase-1],
        floating_staff='/static/assets/nazarick/staff_floating.png' if who=='ainz' and phase==2 else None,
        stage_round=data['round']-m['stage_start']+1, pressure=m.get('pressure', 0),
        pressure_max=m.get('pressure_max', 1), exposed=bool(m.get('exposed_until', 0)>=data['round']),
        ritual=m.get('ritual'), restored=m.get('restored', False))


def initialize(data):
    data['nazarick'] = dict(version=1, stage=0, phase=1, stage_start=1, pressure=0,
        initial_players={key: deepcopy(p['fighter']) for key, p in data['players'].items()})
    data['multi_enemy'] = True
    load_stage(data)


def offer_blessing(data):
    """A wipe pauses this raid, not a paid result; no reward settlement yet."""
    m=data['nazarick']
    if data.get('finished'):return True
    eligible=[k for k,p in data['players'].items() if not p.get('withdrawn')]
    if m.get('blessed') or not eligible:
        data.update(finished=True,won=False,result='Отряд повержен. Поход в Назарик завершён.')
        return True
    if not m.get('blessing_offer'):
        m['offer_serial']=m.get('offer_serial',0)+1
        m['blessing_offer']=dict(id=f'{m["stage"]}:{data["round"]}:{m["offer_serial"]}',eligible=eligible,votes={})
        data['result']='Отряд повержен. Принять благословение ценой билета на смену класса?'
    return False


def decline_blessing(data,reason='Отряд отказался от благословения.'):
    data['nazarick'].pop('blessing_offer',None)
    data.update(finished=True,won=False,result=reason+' Поход завершён без наград.')


def vote_blessing(data,actor,accept,offer_id):
    from arena_raid_engine import log_event
    m=data['nazarick'];offer=m.get('blessing_offer');key=str(actor)
    if not offer or not isinstance(offer_id,str) or offer_id!=offer['id']:
        raise ValueError('Предложение благословения уже изменилось. Обнови рейд.')
    if key not in offer['eligible'] or data['players'][key].get('withdrawn'):
        raise ValueError('Голосовать могут только участники поверженного отряда.')
    if not accept:
        decline_blessing(data)
        return 'declined'
    if offer['votes'].get(key):return 'unchanged'
    offer['votes'][key]=True
    if not all(offer['votes'].get(k) for k in offer['eligible']):return 'waiting'
    m.update(blessed=True,ticket_forfeited=True,phase=1,restored=True)
    m.pop('blessing_offer',None)
    data.update(finished=False,won=False,rewards={},result='',round=data['round']+1)
    m['stage_start']=data['round']
    for k,p in data['players'].items():
        if p.get('withdrawn'):continue
        saved=deepcopy(m['initial_players'][k])
        saved['effects']=[e for e in saved['effects'] if e.get('id')!='nz_plot_armor']
        saved['effects'].append(dict(id='nz_plot_armor',kind='incoming_damage_multiplier',value=.5,duration=1000000,
            name='Сюжетная броня',description='Входящий прямой и периодический урон −50% до конца этого похода. Самоурон не уменьшается. Билет из награды исключён.'))
        m['initial_players'][k]=deepcopy(saved)
        p.update(fighter=saved,selected=None,selected_target=None)
        p.pop('qte_result',None)
    load_stage(data)
    data.pop('round_before',None)
    log_event(data,'boss','boss','Благословение принято единогласно. «Сюжетная броня»: входящий урон −50%. Текущий противник восстановлен, билет из награды исключён.',nazarick_event='blessing')
    return 'restarted'


def load_stage(data):
    who, phase = identity(data)
    m = data['nazarick']
    base = deepcopy(data['boss'])
    count = len(data['players'])
    hp = (620, 650, 750, 620, 1100)[m['stage']] + (300 if who != 'ainz' else 500)*(count-1)
    base.update(name=NAMES[who], class_id='mage', level=25, hp=hp, resource=200,
        effects=[], mechanics={}, cooldowns={}, own_turns=0, passive_details=[],
        rpg_state={}, epic_state={}, final_state={}, mastery_state={}, used_skills=[],
        is_boss=True, raid_damage_multiplier=1, nz_owner=who)
    base['stats'] = dict(max_hp=hp, resource_max=200, resource_regen=0, physical_attack=12,
        magic_attack=20 if who != 'ainz' else 28, physical_defense=22 if who=='albedo' else 10,
        magic_defense=20 if who=='albedo' else 12, speed=18, evasion=8 if who!='shalltear' else 12)
    data['boss'] = base
    data['enemies'] = {'boss': base}
    data['phase'] = phase
    data['control_lock'] = data['control_resistance'] = 0
    m.update(pressure=0, pressure_max=round(hp*.16), next_summon=data['round']+2)
    for field in ('exposed_until', 'ritual', 'pending_next', 'pending_phase'):
        m.pop(field, None)
    set_intent(data)


def bind(data):
    # JSON loses object aliases; boss and roster must refer to the same fighter.
    data['enemies']['boss'] = data['boss']


def living_enemies(data):
    return {k: f for k, f in data['enemies'].items() if f['hp']>0}


def contact_afflictions(fighter, skill_id, event, guard=None):
    """Only server-replayed hazard contacts can supply per-projectile afflictions."""
    if not event.get('hit') or event.get('damage',0)<=0:return []
    if guard:
        statuses={c.get('status') for c in guard.get('pattern_dodge',{}).get('contacts',[])
                  if c.get('weight',0)>0 and c.get('reduction',0)<1}
    else:
        parts=skill_id.split('_');who,phase,move=parts[1],parts[2],parts[3]
        statuses=({'burn'} if who in ('hellguard','pyromancer') or who=='demiurge' and phase=='p2' and move=='0'
                  else {'curse'} if who=='demiurge' else {'burn','curse'} if skill_id in ('nz_ainz_p1_0','nz_ainz_p2_0','nz_ainz_p2_2') else set())
    applied=[]
    specs={
        'burn':(('burn',3),2,'Ожог','Ожог: 3 HP на два действия.'),
        'curse':(('damage_pct',-.12),3,'Проклятие','Проклятие: исходящий урон −12% на три действия.'),
        'shock':(('accuracy_flat',-12),2,'Шок','Шок: точность −12 на два действия.'),
        'venom':(('burn',2),3,'Яд посоха','Яд посоха: 2 HP на три действия.'),
        'exposed':(('damage_taken_pct',.15),2,'Уязвимость свету','Уязвимость: входящий прямой урон +15% на два действия.'),
        'sealed':(('skill_cost_flat',8),3,'Печать посоха','Печать: следующий платный навык дороже на 8 энергии; срок — три действия.'),
        'frailty':(('physical_defense_pct',-.12),2,'Хрупкость','Хрупкость: физическая и магическая защита −12% на два действия.'),
    }
    for status in sorted(statuses & specs.keys()):
        (kind,value),duration,name,text=specs[status]
        ident='nz_contact_'+status
        fighter['effects']=[e for e in fighter['effects'] if not e.get('id','').startswith(ident)]
        fighter['effects'].append(dict(id=ident,kind=kind,value=value,duration=duration,name=name))
        if status=='frailty':fighter['effects'].append(dict(id=ident+'_magic',kind='magic_defense_pct',value=-.12,duration=duration,name=name))
        applied.append(text)
    return applied


def set_intent(data):
    from arena_raid_engine import alive_players
    bind(data)
    who, phase = identity(data)
    m, boss = data['nazarick'], data['boss']
    boss['name']='Актёр Пандоры' if who=='pandora' and phase==2 else NAMES[who]
    round_index = data['round']-m['stage_start']
    move = round_index % 3
    if who == 'ainz' and phase == 2:
        if m.get('ritual'):
            move = 1
        elif move == 1:
            m['ritual'] = dict(hp=boss['hp'], threshold=round(boss['stats']['max_hp']*.10), start=data['round'])
            move = -1
    skill = f'nz_{who}_p{phase}_{max(0,move)}'
    boss['loadout'] = [f'nz_{who}_p{phase}_{i}' for i in range(3)]
    boss.pop('nz_copy',None)
    if who=='pandora' and phase==2 and move==1 and m.get('copied_skill'):
        boss['nz_copy']=deepcopy(m['copied_skill'])
    players = list(alive_players(data))
    targets = players if move != 0 else players[round_index % max(1,len(players)):][:1]
    kind = 'attack'
    if move == -1:
        kind, targets = 'ritual', []
    elif (who, phase, move) in {('demiurge',2,2),('ainz',1,2)}:
        kind, targets = 'summon', []
    elif who == 'albedo' and move == 2 and phase == 1:
        kind, targets = 'stance', []
    boss['effects'] = [e for e in boss['effects'] if not e.get('id','').startswith('nz_stance')]
    if who == 'albedo':
        exposed = m.get('exposed_until',0)>=data['round']
        boss['effects'].append(dict(id='nz_stance', kind='damage_taken_pct', value=.30 if exposed else -.35, duration=3))
    if who in ('ainz', 'demiurge'):
        for ident, value, effect in [('boss_knight',-.20,'damage_taken_pct'),('boss_lich',.15,'magic_attack_pct')]:
            boss['effects'] = [e for e in boss['effects'] if e.get('id')!='nz_'+ident]
            if ident in living_enemies(data):
                boss['effects'].append(dict(id='nz_'+ident,kind=effect,value=value,duration=3))
    text = ('Подготовка великого ритуала: нанесите 10% максимального HP босса за этот раунд, чтобы ослабить удар.'
        if kind=='ritual' else SKILLS[skill].name)
    if boss.get('nz_copy'):text+=' — '+boss['nz_copy']['name']
    data['enemy_intents'] = {'boss':dict(kind=kind, skill=skill if kind=='attack' else None, targets=targets, phase=phase, text=text)}
    for index,(key,f) in enumerate(living_enemies(data).items()):
        if key=='boss':continue
        sid=f['loadout'][0]
        target=players[(round_index+index)%len(players):][:1] if players else []
        data['enemy_intents'][key]=dict(kind='attack',skill=sid,targets=target,phase=phase,text=SKILLS[sid].name)
    data['intent'] = dict(kind='nazarick', skill=skill if kind=='attack' else None, targets=targets, phase=phase, text=text)
    data['phase']=phase
    line = QUOTES[who][phase-1] if round_index==0 else ATTACK_QUOTES[who][(phase-1)*3+max(0,move)]
    data['dialogue']=dict(speaker=boss['name'].split(' — ')[0].upper(),text=line,
        warning=HINTS[who][phase-1],persistent=True,id=f'nz:{data["round"]}:{who}:{phase}')
    boss['mechanics'].update(nazarick_phase=phase,nazarick_guardian=who)


def progress(data):
    """Called only at round boundaries; no unannounced new boss attacks."""
    from arena_raid_engine import alive_players, log_event
    who,phase=identity(data)
    m=data['nazarick']
    if not alive_players(data):
        offer_blessing(data)
        return True
    if phase==1 and data['boss']['hp']<=data['boss']['stats']['max_hp']*.5:
        m['phase']=data['phase']=2
        data['boss']['hp']=max(round(data['boss']['stats']['max_hp']*.5),data['boss']['hp'])
        log_event(data,'boss','boss',QUOTES[who][1],nazarick_event='phase')
        return True
    if data['boss']['hp']<=0:
        if m['stage']==4:
            data.update(finished=True,won=True,result='Назарик пройден. Король-колдун повержен!')
            return True
        old=who
        m['stage']+=1
        m['phase']=1
        m['stage_start']=data['round']+1
        # Restore all combat state, including KO fighters, but never deserters.
        if old in ORDER[:3]:
            for key,p in data['players'].items():
                if not p.get('withdrawn'):
                    p['fighter']=deepcopy(m['initial_players'][key])
            m['restored']=True
        else:
            m['restored']=False
        load_stage(data)
        text=('Страж повержен. Отряд полностью восстановлен: HP, энергия, эффекты, перезарядки и боевые применения.'
            if old!='pandora' else 'Маска спала: это был Актёр Пандоры. «Достаточно. Дальше я сам».')
        log_event(data,'boss','boss',text,nazarick_event='restore' if old!='pandora' else 'reveal',actor_name=NAMES[old])
        return True
    return False


def summon(data):
    from arena_raid_engine import log_event
    m=data['nazarick']
    who,_=identity(data)
    if data['round']<m['next_summon']:
        log_event(data,'boss','boss','Портал восстанавливается: действие потрачено, новых существ нет.')
        return
    for kind in ('knight','lich'):
        key='boss_'+kind
        if data['enemies'].get(key,{}).get('hp',0)>0:continue
        f=deepcopy(data['boss'])
        hp=(100 if kind=='knight' else 70)+40*(len(data['players'])-1)
        f['stats']=dict(f['stats'],max_hp=hp,physical_attack=0,magic_attack=3,physical_defense=5,magic_defense=5,evasion=0)
        f.update(hp=hp,name=('Рыцарь смерти' if kind=='knight' else 'Костяной заклинатель') if who=='ainz' else
                 ('Адский страж' if kind=='knight' else 'Демон-пиромант'),
                 loadout=[f'nz_{kind if who=="ainz" else "hellguard" if kind=="knight" else "pyromancer"}_p1_0'],effects=[],mechanics={},cooldowns={},
                 nz_sprite=kind if who=='ainz' else 'demon_guard' if kind=='knight' else 'demon_mage')
        data['enemies'][key]=f
    m['next_summon']=data['round']+4
    log_event(data,'boss','boss','Портал раскрыт. Призывы начнут действовать со следующего раунда.')


def resolve(data, skills, rng=None):
    from arena_raid_engine import alive_players, native_attack, defend, log_event, raid_snapshot
    from arena_plague import begin_turn
    rng=rng or random.SystemRandom()
    if data.get('finished'):raise ValueError('Рейд завершён.')
    bind(data)
    data['round_before']=raid_snapshot(data)
    guards={}
    m=data['nazarick']
    who,phase=identity(data)
    order=sorted(alive_players(data),key=lambda k:(-effective_stat(data['players'][k]['fighter'],'speed'),int(k)))
    boss_stunned=False
    for key in order:
        if data['boss']['hp']<=0:
            break
        p=data['players'][key]; f=p['fighter']; selected=p['selected']
        proof=p.pop('qte_result',{})
        guards[key]=proof.get('encounter_guards',{})
        p['manual_turns']+=int(selected is not None)
        p['missed']=0 if selected is not None else p['missed']+1
        if p['missed']>=3:p['reward_blocked']=True
        if any(e['kind']=='stun' for e in f['effects']):
            _tick(f);log_event(data,key,key,'Ошеломление: действие пропущено.');continue
        target=p.get('selected_target') or 'boss'
        enemy=data['enemies'].get(target)
        if selected in skills and not skills[selected].hostile and (not enemy or enemy['hp']<=0):
            target,enemy='boss',data['boss']
        if selected in (None,'defend') or not enemy or enemy['hp']<=0:
            defend(f,data['boss'],data);log_event(data,key,key,'Защита: обе защиты +35%.');continue
        for field in ('attack','pattern_attack'):
            if field in proof:f['_qte_'+field]=proof[field]
        event = {}
        try:
            event=native_attack(f,enemy,selected,skills,rng,allies=[v['fighter'] for v in alive_players(data).values()],raid_context=data)
            if skills[selected].damage_type:
                copied=skills[selected]
                # Retain a descriptor, never equipment, resources or the player's class mechanics.
                m['copied_skill']=dict(id=f'{selected}:{copied.name}:1:{copied.damage_type}',base_id=selected,
                    name=copied.name,class_id=copied.class_id,strikes=1,damage_type=copied.damage_type,
                    tags=list(copied.tags),description='Театральная копия: медленнее оригинала.')
            log_event(data,key,target,event['text'],skill=selected,**{k:event[k] for k in ('damage','self_damage','damage_type','hit','critical','hits','hit_results') if k in event})
        except ValueError:
            defend(f,data['boss'],data);log_event(data,key,key,'Навык недоступен: защита без расхода энергии.')
        finally:
            f.pop('_qte_attack',None);f.pop('_qte_pattern_attack',None)
        if target=='boss' and any(e['kind']=='stun' for e in enemy['effects']):
            enemy['effects']=[e for e in enemy['effects'] if e['kind']!='stun']
            accepted=not data['control_lock'] and not boss_stunned and rng.random()<max(.1,1-.25*data['control_resistance'])
            data['control_resistance']=min(4,data['control_resistance']+1)
            boss_stunned=boss_stunned or accepted
            if not accepted:log_event(data,'boss','boss','Босс сопротивляется ошеломлению.')
        if target=='boss' and who=='albedo' and m.get('exposed_until',0)<data['round']:
            m['pressure']+=max(0,event.get('damage',0))
            if m['pressure']>=m['pressure_max']:
                m.update(pressure=0,exposed_until=data['round']+1)
                data['boss']['effects']=[e for e in data['boss']['effects'] if e.get('id')!='nz_stance']
                data['boss']['effects'].append(dict(id='nz_stance',kind='damage_taken_pct',value=.30,duration=3))
                log_event(data,'boss','boss','Стойка разрушена: +30% входящего урона до конца следующего раунда.')
    data['_qte_boss_phase']=True
    # A defeated phase/stage never executes its prepared attack.
    transition=progress(data)
    if not transition and not data.get('finished'):
        for enemy_key,intent in list(data['enemy_intents'].items()):
            enemy=data['enemies'].get(enemy_key)
            if not enemy or enemy['hp']<=0 or not alive_players(data):continue
            if enemy_key=='boss' and boss_stunned:
                _tick(enemy);data['control_lock']=3
                m.pop('ritual',None)
                log_event(data,'boss','boss','Босс ошеломлён: намерение сорвано.');continue
            poison=begin_turn(enemy)
            if poison:log_event(data,enemy_key,enemy_key,f'Чума: −{poison} HP.',damage=poison)
            if enemy['hp']<=0:
                if enemy_key=='boss':break
                continue
            if any(e['kind']=='stun' for e in enemy['effects']):
                _tick(enemy);log_event(data,enemy_key,enemy_key,'Ошеломление: намерение сорвано.');continue
            if intent['kind'] in ('summon','stance','ritual'):
                _tick(enemy)
                if enemy['hp']<=0:
                    log_event(data,enemy_key,enemy_key,'Горение: подготовленное действие сорвано.')
                    if enemy_key=='boss':break
                    continue
                if intent['kind']=='summon':summon(data)
                elif intent['kind']=='stance':log_event(data,'boss','boss','Защитная стойка: нанесите достаточно урона, чтобы разрушить её.')
                else:log_event(data,'boss','boss','Великий ритуал начат. Подготовьтесь к следующему раунду.')
                continue
            original=deepcopy(enemy);after=None;damage_total=0
            pending_dot=bleeding_damage(original)+sum(max(0,int(e['value']))for e in original['effects'] if e['kind']=='burn')
            data['intent']=intent
            ritual_weakened=False
            if who=='ainz' and phase==2 and intent['skill'].endswith('_1'):
                ritual=m.pop('ritual',None)
                ritual_weakened=bool(ritual and ritual['hp']-data['boss']['hp']>=ritual['threshold'])
            for key in intent['targets']:
                if key not in alive_players(data):continue
                f=data['players'][key]['fighter'];guard=guards.get(key,{}).get(enemy_key)
                if guard:f['_qte_guard']=dict(guard,skill=intent['skill'])
                attacker=deepcopy(original)
                if ritual_weakened:
                    attacker['effects'].append(dict(id='nz_ritual_weakened',kind='damage_pct',value=-.60,duration=1))
                if who=='albedo' and phase==2 and intent['skill'].endswith('_2') and m.get('exposed_until',0)>=data['round']:
                    attacker['effects'].append(dict(id='nz_staggered',kind='damage_pct',value=-.50,duration=1))
                try:
                    event=native_attack(attacker,f,intent['skill'],SKILLS,rng,tick_actor_bleed=False,raid_context=data)
                finally:f.pop('_qte_guard',None)
                afflictions=contact_afflictions(f,intent['skill'],event,guard)
                if afflictions:event['text']+=' '+' '.join(afflictions)
                if after is None:after=attacker
                damage_total+=event.get('damage',0)
                enemy['hp']=max(0,enemy['hp']-event.get('reaction_damage',0))
                log_event(data,enemy_key,key,event['text'],skill=intent['skill'],**{k:event[k] for k in ('damage','damage_type','hit','critical','hits','hit_results') if k in event})
            if after:
                after['hp']=enemy['hp'];enemy.clear();enemy.update(after)
            else:_tick(enemy)
            if who=='shalltear' and enemy_key=='boss' and damage_total:
                healed=min(enemy['stats']['max_hp']-enemy['hp'],round(damage_total*(.35 if phase==1 else .50)))
                enemy['hp']+=healed
                if healed:log_event(data,'boss','boss',f'Вампиризм: +{healed} HP от реально прошедшего урона.',healing=healed)
            if after and pending_dot:
                dot=min(enemy['hp'],pending_dot);enemy['hp']-=dot
                log_event(data,enemy_key,enemy_key,f'Кровотечение / горение: −{dot} HP.',damage=dot)
            if enemy_key=='boss' and enemy['hp']<=0:break
    data.pop('_qte_boss_phase',None)
    data['control_lock']=max(0,data['control_lock']-1)
    progress(data)
    if m.get('blessing_offer'):
        data.pop('round_before',None)
        data['log']=data['log'][-80:]
        return data
    if not data.get('finished') and data['round']-m['stage_start']+1>=100:
        data.update(finished=True,won=False,result='Предел 100 раундов на текущего противника. Поход завершён.')
    data.pop('round_before',None)
    if not data.get('finished'):
        data['round']+=1
        for key,p in data['players'].items():
            p.update(selected=None,selected_target=None)
            if not p.get('withdrawn') and p['fighter']['hp']>0:
                poison=begin_turn(p['fighter'])
                if poison:log_event(data,key,key,f'Чума: −{poison} HP.',damage=poison)
                restore_turn_resource(p['fighter'])
        if not alive_players(data):offer_blessing(data)
        else:set_intent(data)
    data['log']=data['log'][-80:]
    return data
