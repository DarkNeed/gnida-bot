"""Nazarick-only identities and real passive/effect rules. Never grant player classes."""
from copy import deepcopy

NAMES={
 'gargantua':(('Каменная ладонь','Бросок валуна','Поступь колосса','Осадный корпус','Обрушение подземного озера'),('Грохот титана','Каменный град','Разлом основания','Перегрузка ядра','Падение свода')),
 'cocytus':(('Бог-императорский клинок','Режущий ветер','Ледяное дыхание','Морозная аура','Удар неподвижного царя мудрости'),('Разрез четырёх рук','Танец четырёх клинков','Ледяные пики','Полная морозная аура','Пять царей мудрости')),
 'aura':(('Стрела, пронзающая тень','Кнут укротительницы','Дождь стрел','Небесное око','Охота Фенрира'),('Галактический выстрел','Неподвижные путы','Звериная облава','Дыхание ужаса','Великая охота')),
 'mare':(('Корни под ногами','Каменные копья','Землетрясение','Сила Гайи','Поток лавы'),('Разрыв земли','Каменный лес','Великое землетрясение','Укрытие природы','Малая катастрофа')),
 'victim':(('Розовые осколки','Плач жертвы','Хрупкая печать','Ангельская оболочка','Предвестие жертвы'),('Завет самопожертвования','Цепи восьмого этажа','Проклятие нарушителей','Замкнутый барьер','Последняя печать')),
 'sebas':(('Шаг дворецкого','Стальная ладонь','Вихрь ударов','Восстановление ци','Разрушительный кулак'),('Драконий кулак','Когти драконида','Драконий вихрь','Дыхание жизни','Истинная сила дворецкого')),
 'yuri':(('Удар дуллахана','Двойка Альфы','Сметающий локоть','Железная стойка','Удар внутренней энергии'),('Контрудар Альфы','Разрушительная серия','Круговой удар','Несгибаемая стойка','Кулак старшей сестры')),
 'narberal':(('Грозовой шар','Цепная молния','Драконья молния','Магический щит','Двойная драконья молния'),('Сфера грома','Разветвлённая молния','Грозовые столбы','Усиление магии','Тройная драконья молния')),
 'lupusregina':(('Когти оборотня','Волчий прыжок','Удар булавой','Массовое исцеление','Охота Беты'),('Кровавые когти','Жестокая игра','Лунная булава','Сильное массовое исцеление','Клыки оборотня')),
 'solution':(('Кислотный плевок','Слизистая сеть','Разъедающий след','Текучая форма','Живой кислотный омут'),('Кислотный дождь','Удушающие путы','Кислотная ловушка','Восстановление слизи','Поглощение Эпсилон')),
 'entoma':(('Жук-пуля','Шёлковые путы','Вихрь насекомых','Панцирный щит','Облако плотоядных мух'),('Бронебойный жук','Липкая паутина','Стальной рой','Паразитическая регенерация','Буря плотоядных мух')),
 'cz':(('Выстрел Дельты','Тройная очередь','Перекрёстный огонь','Усиленное прицеливание','Бронебойный выстрел'),('Точный выстрел','Заградительная очередь','Зачистка сектора','Боевой анализ','Огневое превосходство')),
}

def status(ident,kind,value,turns=3,target='enemy',name='',description=''):
    return dict(id='nzd_'+ident,kind=kind,value=value,turns=turns,duration=turns,target=target,chance=1,
                name=name,description=description)

SUPPORT={
 'gargantua':('physical_defense_pct',.35,'Осадный корпус: физическая защита +35%.'),
 'cocytus':('nzd_frost_aura',1,'Раскрывает морозную ауру: следующие попадания сильнее сковывают холодом.'),
 'aura':('accuracy_flat',10,'Небесное око: точность +10%; во второй фазе дыхание ослабляет скорость и силу отряда.'),
 'mare':('nzd_team_guard',.22,'Сила Гайи: обе защиты отряда +22%; во второй фазе Укрытие природы снижает прямой урон на 25%.'),
 'victim':('incoming_damage_multiplier',.72,'Барьер сосуда: входящий урон ×0,72 на три собственных действия.'),
 'sebas':('heal_pct',.13,'Ци восстанавливает 13% максимального HP; во второй фазе 17%.'),
 'yuri':('physical_defense_pct',.30,'Стойка дуллахана: физическая защита +30% на три собственных действия.'),
 'narberal':('magic_defense_pct',.30,'Магический щит: магическая защита +30%; во второй фазе также усиливает магическую атаку.'),
 'lupusregina':('nzd_team_heal',.16,'Лечит живых союзников на 16% максимального HP, во второй фазе на 20%. Устраняйте лекаря или прерывайте каст.'),
 'solution':('heal_pct',.12,'Восстанавливает 12% HP и на два действия усиливает уклонение текучей формы.'),
 'entoma':('physical_defense_pct',.28,'Панцирные насекомые повышают физическую защиту на 28%.'),
 'cz':('accuracy_flat',12,'Анализ цели: точность +12%; открывает слабое место следующим попаданием.'),
}
PASSIVES={
 'gargantua':(('Стратегический осадный голем','Входящий прямой урон −18%. Кровотечение, чума и ментальный контроль не действуют.',('incoming_damage_multiplier',.82)),('Каменное тело','Физическая защита +25%. Долгие удары оставляют время для нескольких быстрых действий.',('physical_defense_pct',.25))),
 'cocytus':(('Воин четырёх клинков','Физическая атака +12%; длинные серии состоят из отдельных ударов.',('physical_attack_pct',.12)),('Рыцарь Нифльхейма','Попадания холодом накапливают до трёх стаков скованности. На третьем: скорость −24%, уклонение −6. Это не пропуск хода.',('magic_defense_pct',.20))),
 'aura':(('Небесное око','Бонус точности +6. Скрытность не даёт полной неуязвимости.',('accuracy_flat',6)),('Узы близнецов','Пока Аура и Маре живы, у обоих урон +12%. Победа над одним разрывает связку.',None)),
 'mare':(('Хранитель шестого этажа','Магическая атака +12%. Разломы предварительно обозначаются.',('magic_attack_pct',.12)),('Узы близнецов','Пока оба близнеца живы: урон +12%. Исцеление/укрытие можно прервать контролем.',None)),
 'victim':(('Жертвенный сосуд','Поражение первой формы запускает ритуал, а не завершает бой.',None),('Печати восьмого этажа','Проклятия замедляют касты, но не отнимают управление полностью.',('magic_defense_pct',.20))),
 'sebas':(('Драконид','Обе защиты +18%. Во второй фазе раскрывает истинную силу, а не просто получает больше HP.',('physical_defense_pct',.18)),('Мастер внутренней энергии','Каждое третье завершённое действие восстанавливает 3% HP. Активное лечение занимает отдельный каст.',None)),
 'yuri':(('Дуллахан','Кровотечение и чума не действуют. Физическая защита +18%.',('physical_defense_pct',.18)),('Старшая Плеяда','Пока Юри жива, союзные Плеяды получают на 10% меньше прямого урона.',None)),
 'narberal':(('Боевая волшебница','Магическая атака +12%. Электрические попадания временно уменьшают запас доступной энергии.',('magic_attack_pct',.12)),('Магический щит','Магическая защита +18%.',('magic_defense_pct',.18))),
 'lupusregina':(('Оборотень-жрица','Каждое третье действие восстанавливает 3% HP. Лечение союзников — отдельный прерываемый каст.',None),('Звериный азарт','Скорость +10%. Когти оставляют кровоточащие раны.',('speed_pct',.10))),
 'solution':(('Хищная слизь','Физическая защита +22%. Кислота ослабляет броню, а не игнорирует блок.',('physical_defense_pct',.22)),('Текучая форма','Уклонение +4; активная регенерация требует времени.',('evasion_flat',4))),
 'entoma':(('Насекомая заклинательница','Магическая защита +18%; паутина замедляет касты, рой наносит периодический урон.',('magic_defense_pct',.18)),('Многослойный панцирь','Входящий прямой урон −10%.',('incoming_damage_multiplier',.90))),
 'cz':(('Автоматон','Чума и ментальный контроль не действуют. Точность +5.',('accuracy_flat',5)),('Подавление','Попадания очередью снижают скорость на два собственных действия. Снаряды — настоящие пули.',None)),
}
LEGACY_PASSIVES={
 'shalltear':(('Истинный вампир','Вампиризм возвращает 35% / 50% реально нанесённого урона по фазам; это существующая механика стража.',None),('Нежить Назарика','Кровотечение и чума не действуют.',None)),
 'demiurge':(('Архидемон','Горение не действует. Магическая защита +18%.',('magic_defense_pct',.18)),('Повелитель приспешников','Приказы, пентаграммы и призывы используют собственные боевые сценарии.',None)),
 'albedo':(('Неприступная стена','Обе защиты +20%.',('physical_defense_pct',.20)),('Гермес Трисмегист','Магическая защита +20%; удерживает переднюю линию, но не неуязвима.',('magic_defense_pct',.20))),
 'pandora':(('Актёр','Уклонение +3. Смена облика и копирование атак сохраняются.',('evasion_flat',3)),('Совершенная имитация','Заимствованные атаки медленнее и слабее оригинала Аинза.',None)),
 'ainz':(('Король-колдун','Прямой входящий урон −12%.',('incoming_damage_multiplier',.88)),('Владыка нежити','Кровотечение, чума и ментальный контроль не действуют; фазы и посох сохраняют свои сценарии.',None)),
}

def install(f,who,legacy=False):
    rows=(LEGACY_PASSIVES if legacy else PASSIVES).get(who,())
    if legacy:f['nzd_legacy']=who
    f['passive_details']=[p for p in f.get('passive_details',[]) if not p.get('nzd_passive')]
    for i,(name,text,rule) in enumerate(rows):
        effect=status('passive_'+who+'_'+str(i),*(rule or ('nzd_lore',0)),turns=999999,target='self',name=name,description=text)
        f['passive_details'].append(dict(skill_id=effect['id'],name=name,rarity='legendary',nzd_passive=True,effects=[deepcopy(effect)]))
        if rule:
            f['effects']=[e for e in f['effects'] if e.get('id')!=effect['id']]+[effect]

def prepare(data):
    enemies=data.get('enemies',{})
    alive={f.get('nzd_guardian') for f in enemies.values() if f['hp']>0}
    for f in enemies.values():
        f['effects']=[e for e in f['effects'] if e.get('id') not in ('nzd_sibling','nzd_yuri_cover')]
        if f.get('nzd_guardian') in ('aura','mare') and {'aura','mare'}<=alive:
            f['effects'].append(status('sibling','damage_pct',.12,999999,'self','Узы близнецов','Урон +12%, пока оба близнеца живы.'))
        if 'yuri' in alive and f.get('nzd_guardian') in ('narberal','lupusregina'):
            f['effects'].append(status('yuri_cover','incoming_damage_multiplier',.90,999999,'self','За спиной Альфы','Прямой урон −10%, пока Юри жива.'))

def allows_effect(f,e):
    who=f.get('nzd_guardian') or f.get('nzd_legacy')
    immune=set()
    if f.get('nzd_ritual'):return False
    if who in ('gargantua','cz','yuri','shalltear','ainz'):immune|={'plague_infect','plague_fever','plague_spores'}
    if who in ('gargantua','yuri','shalltear','ainz'):immune.add('bleed')
    if who in ('gargantua','cz','ainz'):immune|={'stun','charm','charmed','taunt'}
    if who=='demiurge':immune.add('burn')
    return e['kind'] not in immune

def effect(actor,target,e,allies,context):
    """Only explicit Nazarick effects are intercepted; common combat stays native."""
    kind=e['kind']
    if kind=='nzd_frost':
        old=next((v for v in target['effects'] if v.get('id')=='nzd_frost'),{})
        stacks=min(3,old.get('stacks',0)+int(e['value'])+int(any(v.get('id')=='nzd_cold_blade' for v in actor['effects'])))
        slow=status('frost','speed_pct',-.08*stacks,3,name='Заморозка' if stacks==3 else 'Ледяная скованность',description=f'Холод: {stacks}/3. Скорость −{stacks*8}%. При трёх стаках уклонение −6; управление не отнимается.')
        slow['stacks']=stacks
        target['effects']=[v for v in target['effects'] if v.get('id') not in ('nzd_frost','nzd_frost_evasion')]+[slow]
        if stacks==3:target['effects'].append(status('frost_evasion','evasion_flat',-6,3,name='Заморозка',description='Уклонение −6 на три собственных действия.'))
        return f'холод {stacks}/3'
    if kind=='nzd_frost_aura':
        actor['effects']=[v for v in actor['effects'] if v.get('id')!='nzd_cold_blade']+[status('cold_blade','damage_pct',.14,3,'self','Морозная аура','Урон +14% на три собственных действия.')]
        return 'морозная аура раскрыта'
    if kind=='nzd_team_heal':
        amount=0
        from arena_plague import actively_healed
        for f in allies or [actor]:
            if f['hp']<=0:continue
            heal=min(f['stats']['max_hp']-f['hp'],round(f['stats']['max_hp']*e['value']))
            f['hp']+=heal;amount+=heal
            if heal:actively_healed(f)
        return f'исцеление отряда: +{amount} HP'
    if kind=='nzd_team_guard':
        for f in allies or [actor]:
            if f['hp']<=0:continue
            for k,v in (('physical_defense_pct',e['value']),('magic_defense_pct',e['value'])):
                ident='gaia_'+k;f['effects']=[v for v in f['effects'] if v.get('id')!='nzd_'+ident]+[status(ident,k,v,3,'self','Сила Гайи','Защиты отряда усилены на три собственных действия.')]
        return 'защиты отряда усилены'
    if kind=='nzd_team_shelter':
        for f in allies or [actor]:
            if f['hp']<=0:continue
            f['effects']=[v for v in f['effects'] if v.get('id')!='nzd_nature_shelter']+[status('nature_shelter','incoming_damage_multiplier',e['value'],2,'self','Укрытие природы','Прямой входящий урон ×0,75 на два действия.')]
        return 'Укрытие природы защищает отряд'
    return None

def after_action(actor):
    who=actor.get('nzd_guardian')
    if who=='victim' and actor.get('nzd_ritual'):
        actor.update(hp=0,nzd_ritual_complete=True)
        return
    turn=actor.get('own_turns',0)
    if who not in ('sebas','lupusregina') or not turn or turn%3 or actor.get('nzd_regen_turn')==turn:return
    actor['nzd_regen_turn']=turn
    actor['hp']=min(actor['stats']['max_hp'],actor['hp']+round(actor['stats']['max_hp']*.03))
