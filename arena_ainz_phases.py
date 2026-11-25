"""Versioned six-phase Ainz. Old nz_ainz descriptors remain replayable."""
SUMMON_COOLDOWN=16

PHASES = (
    dict(name='Король-колдун', sprite='ainz-mage-v3', color='#b69bff', stats=(20,36,24,30,17,8),
         quote='Сначала я узнаю, на что вы способны.',
         hint='Владыка Назарика наблюдает за незваными гостями.'),
    dict(name='Солнце и Луна', sprite='ainz-blades-v3', color='#d6c7ff', stats=(26,0,19,24,25,14),
         quote='Аматэрасу. Цукуёми. Вспомним старых друзей.',
         hint='В руках Совершенного воина сходятся Солнце и Луна.'),
    dict(name='Наследие Перорончино', sprite='ainz-bow-v3', color='#ffe59a', stats=(30,0,22,26,19,10),
         quote='Перорончино, позволь воспользоваться твоим луком.',
         hint='Золотая тетива звенит в память о Перорончино.'),
    dict(name='Кровавый палач', sprite='ainz-axe-v3', color='#e95c83', stats=(43,0,30,25,13,5),
         quote='Большая сила требует точного расчёта.',
         hint='Кровавый кристалл раскалывает камень и сталь.'),
    dict(name='Наследие Тач Ми', sprite='ainz-warrior-v3', color='#a7ddff', stats=(36,0,38,33,20,9),
         quote='Перед вами не я один. За мной стоят мои товарищи.',
         hint='Белые доспехи несут наследие сильнейшего рыцаря.'),
    dict(name='Владыка смерти', sprite='ainz-death-v3', color='#cb8eff', stats=(20,43,28,35,20,9),
         quote='Совершенный воин отменён. Теперь — мой настоящий арсенал.',
         hint='Король-колдун больше не скрывает своей власти.'),
)
# name, base damage, cast seconds, damage type, QTE family, fallback status.
MOVES = (
    (('Семь камней посоха',31,4.8,'magic','mana',None),
     ('Чёрная дыра',35,3.6,'magic','void','curse'),
     ('Призыв нежити',0,3.0,None,'death',None),
     ('Легион костяных копий',32,3.3,'magic','death','frailty')),
    (('Аматэрасу: солнечный разрез',26,1.65,'physical','slash','bleed'),
     ('Цукуёми: лунный обход',28,2.0,'physical','slash','bleed'),
     ('Скрещение Солнца и Луны',34,2.7,'physical','thrust','bleed'),
     ('Шаг между клинками',29,1.85,'physical','slash','bleed')),
    (('Хоу И: солнечная стрела',34,2.8,'physical','holy','exposed'),
     ('Золотая решётка',30,3.6,'physical','holy','exposed'),
     ('Стрелы заходящего солнца',33,3.2,'physical','holy','exposed'),
     ('Выстрел сквозь горизонт',42,4.5,'physical','holy','exposed')),
    (('Кровавая секира: казнь',48,5.1,'physical','impact','frailty'),
     ('Красный раскол',41,4.3,'physical','impact','bleed'),
     ('Жатва красного кристалла',44,4.7,'physical','slash','frailty'),
     ('Сокрушительный разворот',46,5.5,'physical','impact','bleed')),
    (('Такэмикадзути VIII',36,2.6,'physical','lightning','shock'),
     ('Грозовой перекрёсток',38,3.1,'physical','lightning','shock'),
     ('Клинок сорока одного',42,3.8,'physical','slash','shock'),
     ('Белая крепость: ответный удар',39,3.4,'physical','impact','shock')),
    (('Остановка времени',39,4.0,'magic','coins',None),
     ('Цель всей жизни — смерть',54,5.6,'magic','eclipse',None),
     ('Посох: небесный приговор',43,4.4,'magic','holy',None),
     ('Разрез реальности',46,3.5,'magic','void','curse')),
)
MOVE_HINTS = (
    ('Семь камней высвобождают огонь, грозу, пустоту, яд, свет, печати и костяную магию.',
     'Чёрная дыра и вращающиеся сгустки пустоты.',
     'Аинз вызывает рыцаря смерти и костяного заклинателя.',
     'Встречные потоки костей и черепов.'),
    ('Парные солнечный и лунный клинки.',
     'Огибающие и преследующие лунные удары.',
     'Скрещение парных клинков и закручивающийся веер.',
     'Серия секторных ударов и встречных дуг.'),
    ('Тяжёлая солнечная стрела с сопровождающими стрелами.',
     'Перекрёстная решётка солнечных стрел.',
     'Вращающийся залп заходящего солнца.',
     'Горизонтальный прострел и изгибающиеся стрелы.'),
    ('Сдвигающееся рассечение, каменная ударная волна и возвратные кристаллы.',
     'Подвижные разломы, плотные волны падающего камня и боковой кристаллический залп.',
     'Три ряда обрушения и восходящее рассечение пола.',
     'Ускоренный двойной разворот и два встречных возвратных залпа.'),
    ('Электрическая цепь проводников и рикошеты зарядов.',
     'Чередующаяся электрическая решётка.',
     'Три диагональных удара с электрическим эхо.',
     'Электрические контуры, рикошеты и центральное рассечение.'),
    ('Два искажения времени и три пересекающиеся волнообразные завесы.',
     'Великий ритуал смерти.',
     'Вращающиеся камни посоха и магические печати.',
     'Чёрная дыра и пространственные рассечения.'),
)


def skills():
    from arena_engine import Skill
    return {f'nz_ainz6_p{phase}_{move}': Skill(
        f'nz_ainz6_p{phase}_{move}', name, 'raid', 1, dtype, power, 99, 0, SUMMON_COOLDOWN if (phase,move)==(1,2) else 0,
        rarity='legendary', cast_base=cast,
        pierce=.2 if phase==3 and move==3 else None,
        description=MOVE_HINTS[phase-1][move]+' '+PHASES[phase-1]['hint'])
        for phase, moves in enumerate(MOVES,1)
        for move,(name,power,cast,dtype,family,status) in enumerate(moves)}


def enabled(data):
    return data.get('nazarick',{}).get('ainz_version')==2 and data['nazarick']['stage']==4


def family(phase,move):
    return MOVES[phase-1][move][4]


def legacy_profile(p):
    # All six styles now have native trajectories. Published nz_ainz patterns
    # still replay through the legacy module without changing their geometry.
    return None


def configure(data):
    m,boss=data['nazarick'],data['boss'];phase=m['phase'];spec=PHASES[phase-1]
    data['phase_count']=6
    pa,ma,pd,md,speed,evasion=spec['stats']
    boss['stats'].update(physical_attack=pa,magic_attack=ma,physical_defense=pd,
                         magic_defense=md,speed=speed,evasion=evasion)
    boss.update(loadout=[f'nz_ainz6_p{phase}_{i}' for i in range(4)],
        class_id='mage',resource=200 if phase in (1,6) else 0)
    boss['effects']=[e for e in boss['effects'] if not e.get('id','').startswith(('ainz_form_','ainz_link_'))]
    boss['effects'].append(dict(id='ainz_form_resistance',kind='damage_taken_pct',value=-.12,
        duration=1000000,name='Высшее существо',description='Прямой входящий урон −12%.'))
    boss['passive_details']=[dict(name='Высшее существо',description='Прямой входящий урон −12%.'),
        dict(name=spec['name'],description=spec['hint'])]
    if phase not in (1,6):
        # Magic already summoned in an earlier phase must not keep casting for
        # the warrior. It is dismissed, not converted into another class.
        data['enemies']={key:f for key,f in data['enemies'].items() if key=='boss'}
        boss['effects']=[e for e in boss['effects'] if e.get('id') not in ('nz_boss_knight','nz_boss_lich')]
    m.pop('ritual',None)
    m['ainz_phase_turn']=boss.get('own_turns',0)
    m['ainz_ritual_count']=0
    for field in ('ainz_opening_hits','ainz_damage_streak','ainz_last_damage_type','ainz_summoned','ainz_summon_ready'):
        m.pop(field,None)


def set_intent(data):
    from arena_raid_engine import alive_players
    from arena_nazarick import SKILLS
    m,boss=data['nazarick'],data['boss'];phase=m['phase'];spec=PHASES[phase-1]
    for key,value,kind,name in (
        ('boss_knight',-.20,'damage_taken_pct','Прикрытие рыцаря смерти'),
        ('boss_lich',.15,'magic_attack_pct','Поддержка костяного заклинателя'),
    ):
        ident='nz_'+key
        boss['effects']=[effect for effect in boss['effects'] if effect.get('id')!=ident]
        if phase==1 and data['enemies'].get(key,{}).get('hp',0)>0:
            boss['effects'].append(dict(id=ident,kind=kind,value=value,duration=3,name=name))
    helpers=any(data['enemies'].get(key,{}).get('hp',0)>0 for key in ('boss_knight','boss_lich'))
    if phase==1 and helpers:m['ainz_summoned']=True
    boss['effects']=[e for e in boss['effects'] if e.get('id')!='ainz_link_broken']
    if phase==1 and m.get('ainz_summoned') and not helpers:
        boss['effects'].append(dict(id='ainz_link_broken',kind='damage_taken_pct',value=.25,duration=3,
            name='Обрыв связи',description='Оба призыва уничтожены: входящий урон +25% до нового призыва.'))
    turn=max(0,boss.get('own_turns',0)-m.get('ainz_phase_turn',0)-m.get('ainz_ritual_count',0))
    move=m.get('ainz_preview_move',turn%4)
    if phase==1 and move==2 and (helpers or boss.get('own_turns',0)<m.get('ainz_summon_ready',0)):
        move=1 if turn%8==6 else 3
    sid=f'nz_ainz6_p{phase}_{move}'
    players=list(alive_players(data));targets=players if move in (1,2) else players[turn%max(1,len(players)):][:1]
    kind='attack'
    if phase==1 and move==2:kind,targets='summon',[]
    if phase==6 and move==1 and not m.get('ritual'):
        m['ritual']=dict(hp=boss['hp'],threshold=round(boss['stats']['max_hp']*.04),start=data['round'])
        kind,targets='ritual',[]
    text=SKILLS[sid].name if kind!='ritual' else 'Аинз готовит великий ритуал смерти.'
    intents={'boss':dict(kind=kind,skill=sid if kind=='attack' else None,targets=targets,phase=phase,text=text,
                         area=kind=='attack' and move in (1,2))}
    for index,(key,f) in enumerate(data['enemies'].items()):
        if key=='boss' or f['hp']<=0:continue
        skill=f['loadout'][0]
        intents[key]=dict(kind='attack',skill=skill,targets=players[(turn+index)%max(1,len(players)):][:1],phase=phase,text=SKILLS[skill].name)
    data.update(enemy_intents=intents,intent=dict(intents['boss'],kind='nazarick'),phase=phase)
    data['dialogue']=dict(speaker='АИНЗ ОАЛ ГОУН',text=spec['quote'] if turn==0 else SKILLS[sid].name,
        warning=spec['hint'],persistent=True,id=f'ainz6:{phase}:{turn}:{kind}')
    boss['mechanics'].update(nazarick_phase=phase,nazarick_guardian='ainz')


def presentation(data):
    m=data['nazarick'];phase=m['phase'];spec=PHASES[phase-1]
    summon_in=max(0,m.get('ainz_summon_ready',0)-data['boss'].get('own_turns',0))
    hint=spec['hint']+(f' Повторный призыв: через {summon_in} действий Аинза.' if phase==1 and summon_in else '')
    return dict(stage=5,stage_count=5,guardian='ainz',phase=phase,phase_count=6,
        title='Аинз Оал Гоун — Король-колдун',phase_name=f'{phase}/6 · '+spec['name'],
        sprite=f'/static/assets/nazarick/{spec["sprite"]}.png',
        background='/static/assets/nazarick/bg_ainz1.webp',music=f'nz_ainz6_{phase}',
        hint=hint,summon_in=summon_in,
        floating_staff='/static/assets/nazarick/ainz-prop-staff-v2.png' if phase==6 else None,
        stage_round=data['round']-m['stage_start']+1,ritual=m.get('ritual'),
        restored=m.get('restored',False),pressure=0,pressure_max=1,exposed=False)
