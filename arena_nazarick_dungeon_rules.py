"""Versioned Nazarick route. Old five-stage raids retain their own rules."""
from copy import deepcopy
from arena_nazarick_guardians import NAMES, SUPPORT, status, install

ASSETS='/static/assets/nazarick-dungeon-v2/'
GUARDIANS={
 'gargantua':('Гаргантюа','Голем четвёртого этажа','Пробуждение камня','Перегрузка печати',920,15,'physical','#c8ad76'),
 'cocytus':('Коцит','Воин ледяного озера','Честь воина','Четыре клинка',780,19,'physical','#8edcff'),
 'aura':('Аура','Повелительница зверей','Охота','Загон',470,16,'physical','#9fc36b'),
 'mare':('Маре','Хранитель леса','Тихая земля','Гнев леса',530,18,'magic','#73bd83'),
 'victim':('Виктим','Жертва восьмого этажа','Жертвенный сосуд','Защитный ритуал',160,14,'magic','#edacd0'),
 'sebas':('Себас','Драконий дворецкий','Безупречный этикет','Драконья сущность',820,22,'physical','#d7e2e7'),
 'yuri':('Юри Альфа','Плеяды · кулачный бой','Стойка','Контратака',330,13,'physical','#b0b8de'),
 'narberal':('Нарберал Гамма','Плеяды · молния','Молния','Грозовой зал',290,16,'magic','#8ccfff'),
 'lupusregina':('Люпусрегина Бета','Плеяды · волчица','Улыбка','Охотничий азарт',350,14,'physical','#e9b187'),
 'solution':('Солюшн Эпсилон','Плеяды · слизь','Растворение','Кислотная ловушка',320,14,'magic','#91cfb4'),
 'entoma':('Энтома Василисса','Плеяды · насекомые','Нити','Рой',300,14,'magic','#dc8ba8'),
 'cz':('СиЗет Дельта','Плеяды · стрелок','Прицел','Огонь на подавление',280,16,'physical','#c5be94'),
}
MOVES={
 'gargantua':(('Каменная ладонь','Осколки озера','Рунный разлом'),('Грохот титана','Падающий свод','Ядро Гаргантюа')),
 'cocytus':(('Ледяная нагината','Танец четырёх клинков','Дыхание ледника'),('Божественный разрез','Морозная клетка','Последняя дуэль')),
 'aura':(('Охотничья стрела','Кнут зверолова','Звериная облава'),('Двойной выстрел','Загон хищников','Метка добычи')),
 'mare':(('Корни под ногами','Каменные копья','Лесной обвал'),('Землетрясение','Терновая темница','Голос земли')),
 'victim':(('Розовые осколки','Плач жертвы','Хрупкая печать'),('Завет самопожертвования','Цепи восьмого этажа','Проклятие нарушителей')),
 'sebas':(('Шаг дворецкого','Стальная ладонь','Идеальная стойка'),('Драконий кулак','Серебряный вихрь','Удар сердца дракона')),
 'yuri':(('Прямой удар','Костяная стойка','Сметающий локоть'),('Двойка Альфы','Поворот корпуса','Последний поклон')),
 'narberal':(('Грозовой шар','Разряд Гаммы','Громовой столб'),('Цепная молния','Штормовой круг','Суд грозы')),
 'lupusregina':(('Когти Беты','Волчий прыжок','Лунная булава'),('Кровавый азарт','Круг охоты','Клыки луны')),
 'solution':(('Кислотная капля','Слизистая сеть','Растворяющий след'),('Дождь Эпсилон','Кислотный омут','Поглощение')),
 'entoma':(('Жук-пуля','Шёлковая нить','Вихрь насекомых'),('Стальной рой','Паучья сеть','Чужой голос')),
 'cz':(('Выстрел Дельты','Тройная очередь','Перекрёстный огонь'),('Бронебойный выстрел','Заградительная очередь','Зачистка сектора')),
}
MOVES=NAMES
# Each room is a durable checkpoint; the treasury is a side branch, not floor 11.
FLOORS=(
 (1,'Гробницы','tombs',(('Врата мёртвых',('knight','lich')),)),
 (2,'Катакомбы','catacombs',(('Кровавые коридоры',('knight','lich','knight')),)),
 (3,'Алые покои','shalltear',(('Шалтир',('shalltear',)),)),
 (4,'Подземное озеро','lake',(('Гаргантюа',('gargantua',)),)),
 (5,'Ледник','glacier',(('Коцит',('cocytus',)),)),
 (6,'Лесной амфитеатр','jungle',(('Аура и Маре',('aura','mare')),)),
 (7,'Адский мир','demiurge',(('Демиург',('demiurge',)),)),
 (8,'Запретная пустошь','wilderness',(('Жертва восьмого этажа',('victim',)),)),
 (9,'Королевские покои','royal',(('Аудиенция',()),)),
 (10,'Тронный этаж','antechamber',(('Плеяды · первая линия',('yuri','narberal','lupusregina')),
    ('Плеяды · вторая линия',('solution','entoma','cz')),('Себас',('sebas',)),
    ('Альбедо',('albedo',)),('Король-колдун',('ainz',)))),
)
ROOMS=[dict(floor=f,title=title,biome=bg,name=name,enemies=list(enemies))
       for f,title,bg,rooms in FLOORS for name,enemies in rooms]
for i,r in enumerate(ROOMS):r['index']=i

def sprite(who,phase=1):
    if who=='gargantua':return ASSETS+('gargantua-phase2-v1.png' if phase==2 else 'gargantua-v2.png')
    if who in GUARDIANS:return ASSETS+('sebas_dragon' if who=='sebas' and phase==2 else who)+'.png'
    from arena_nazarick import sprite as legacy
    return legacy(who,phase)

def background(room,phase=1):
    bg=room['biome']
    if bg in ('shalltear','demiurge'):
        return f'/static/assets/nazarick/bg_{bg}{phase}.webp'
    return ASSETS+'bg_'+bg+'.webp'

def build_skills(Skill):
    result={}
    for who,phases in MOVES.items():
        info=GUARDIANS[who]
        for phase,moves in enumerate(phases,1):
            for move,name in enumerate(moves):
                key=f'nz_{who}_p{phase}_{move}'
                support=move==3
                hint=(SUPPORT[who][2] if support else PATTERN_HINTS[who][move] if move<3 else SIGNATURE_HINTS[who])
                if who=='victim' and phase==2 and move==4:hint='Посмертное испытание длится 45 секунд: шесть частей — цепи, рои, рассечения, стены, вращающиеся печати и финал. Переживи ритуал; атаковать саму печать нельзя.'
                effects=[]
                if support:
                    kind,value,_=SUPPORT[who]
                    if who=='mare' and phase==2:kind,value='nzd_team_shelter',.75
                    if who=='entoma' and phase==2:kind,value='heal_pct',.12
                    if phase==2 and kind in ('heal_pct','nzd_team_heal'):value+=.04
                    if kind in ('heal_pct','nzd_team_heal'):hint=f'Активное исцеление {"отряда" if kind=="nzd_team_heal" else "себя"}: {round(value*100)}% максимального HP.'
                    if who=='mare' and phase==2:hint='Прямой входящий урон отряда ×0,75 на два собственных действия.'
                    if who=='narberal' and phase==2:hint+=' Магическая атака +20% на три действия.'
                    if who=='solution':hint+=' Уклонение +6 на два действия.'
                    if who=='aura' and phase==2:hint+=' Дыхание ужаса: скорость врагов −18%, урон −12% на два действия.'
                    effects.append(status(who+'_support',kind,value,3,'self',name,hint))
                    if who=='aura' and phase==2:
                        effects.extend([status('terror_speed','speed_pct',-.18,2,name='Дыхание ужаса',description='Скорость −18% на два действия.'),status('terror_attack','damage_pct',-.12,2,name='Дыхание ужаса',description='Урон −12% на два действия.')])
                    if who=='narberal' and phase==2:effects.append(status('spell_amp','magic_attack_pct',.20,3,'self','Усиление магии','Магическая атака +20%.'))
                    if who=='solution':effects.append(status('fluid','evasion_flat',6,2,'self','Текучая форма','Уклонение +6.'))
                else:
                    if who=='cocytus':effects.append(status('frost','nzd_frost',1,name='Ледяная скованность',description='Накапливает холод до 3 стаков.'))
                    if who in ('aura','mare','victim','cz') and move in (1,2,4):effects.append(status('bind_'+who,'speed_pct',-.14 if phase==1 else -.20,2,name='Путы' if who!='cz' else 'Подавление',description='Следующие касты будут дольше; движение не блокируется полностью.'))
                    if who=='lupusregina':effects.append(status('wolf_wound','bleed',3 if phase==1 else 4,3,name='Раны от когтей',description='Кровотечение при атакующем действии.'))
                    if who=='solution':effects.append(status('acid_armor','physical_defense_pct',-.20,3,name='Разъеденная броня',description='Физическая защита −20%.'))
                    if who=='entoma':effects.append(status('insects','burn',3,3,name='Укусы роя',description='Рой наносит 3 периодического урона.'))
                    if who=='narberal':effects.append(status('shock','resource',-6,1,name='Электрический разряд',description='Попадание сжигает 6 энергии.'))
                    if who=='mare' and move==4 and phase==1:effects.append(status('lava','burn',4,3,name='Лава',description='Горение: 4 HP за действие.'))
                tags=('five_strike',) if who=='cocytus' and phase==2 and move==4 else ('three_strike',) if move==4 and who in ('yuri','sebas','cz') else ()
                result[key]=Skill(key,name,'raid',1,None if support else info[6],0 if support else (18+phase*4+min(move,2)*3+(10 if move==4 else 0)),
                    96 if move<4 else 98,(10,16,20,12,30)[move],(0,1,2,4,3)[move],effects=tuple(effects),rarity='legendary',
                    tags=tags,pierce=(.25 if phase==1 else .35) if who=='cz' and move==4 else None,
                    cast_base=(2.4,3.0,3.6,2.7,4.4)[move]+(.2 if phase==2 else 0),description=hint+' '+(' '.join(e.get('description','') for e in effects) if not support else ''))
    return result

PATTERN_HINTS={
 'gargantua':('Ладонь отмечает широкий разрез. Уйди за линию или встреть удар щитом.','Каменные обломки летят веером с края. Центр веера опаснее.','Трещины заранее подсвечены; между ними остаётся проход.'),
 'cocytus':('Нагината режет отмеченную диагональ, затем возвращается.','Четыре клинка идут по очереди, а не одновременно.','Мороз оставляет широкий безопасный коридор; следи за его смещением.'),
 'aura':('Стрелы выпускаются с двух краёв; направление фиксируется при прицеливании.','Кнут описывает дугу вокруг твоей прежней позиции.','Звери проходят по отмеченным дорожкам; перемещайся между волнами.'),
 'mare':('Корни отмечают твою позицию до появления. Не стой на метке.','Каменные копья появляются с края и летят в указанном направлении.','Земля дрожит двумя полосами с промежутком для прохода.'),
 'victim':('Розовые печати медленно расходятся веером.','Не наступай на отмеченный круг, пока он закрывается.','Линия печати запоминает твою позицию.',''),
 'sebas':('Один точный выпад, затем ответ с другого края.','Удары ладонью чередуют стороны; между ними есть пауза.','Круговой разрез раскрывается после предупреждения.'),
 'yuri':('Кулак летит по отмеченной траектории.','Удар и повтор с противоположного направления.','Разрез локтем: заранее видна диагональ.'),
 'narberal':('Грозовые шары движутся веером.','Молния заранее рисует искривлённую траекторию.','Столбы грозы оставляют проход между отметками.'),
 'lupusregina':('Когти рассекают диагонали последовательно.','Прыжок на прежнюю позицию, затем удар рядом.','Булава движется широкой дугой.'),
 'solution':('Кислота летит медленным плотным веером.','Сеть отмечает дорожки, но не перекрывает всю арену.','Кислотный круг остаётся на отмеченном месте.'),
 'entoma':('Жуки летят по прямой, затем с соседней стороны.','Нити появляются на отмеченных линиях.','Рой расходится; у краёв есть проходы.'),
 'cz':('Пуля идёт с края после красного прицела.','Три очереди с паузами для смены позиции.','Перекрёстный огонь не приходит одновременно.'),
}
SIGNATURE_HINTS={
 'gargantua':'Валуны обрушиваются по трём отмеченным полосам с паузами; между полосами всегда есть проход.',
 'cocytus':'Пять царей проявляются последовательно: меч, копьё, палица, змей и электрический клинок. Блокируй каждый удар отдельно.',
 'aura':'Фенрир обходит поле по охотничьим дорожкам; стрелы перекрывают прежнюю позицию, а не преследуют бесконечно.',
 'mare':'Поток лавы с проходами; во второй фазе Малая катастрофа чередует разломы и круги обрушения с предупреждением.',
 'victim':'Печати сходятся с разных сторон. Окна между цепями позволяют двигаться и восстанавливать стойкость.',
 'sebas':'Быстрая, но заранее обозначенная серия из трёх направлений. Финальный кулак тяжелее первых.',
 'yuri':'Три отдельных кулачных выпада; направление следующего показывается до начала удара.',
 'narberal':'Драконьи молнии извиваются с разных сторон. Не вся арена опасна: между ветвями остаются коридоры.',
 'lupusregina':'Хищница прыгает на отмеченную прежнюю позицию, затем проводит широкую атаку когтями.',
 'solution':'Кислотный омут растёт после предупреждения, оставляя выходы между потоками.',
 'entoma':'Плотоядные мухи движутся волнами с разных краёв, а паутина заранее обозначает линии.',
 'cz':'Три бронебойные очереди меняют угол. Прицел предупреждает о каждом направлении.',
}

def configure_enemy(f,who,count):
    info=GUARDIANS.get(who)
    if not info:return
    hp=round(info[4]*(1+.60*(count-1)))
    f.update(name=info[0],hp=hp,resource=200,rp_sandbox=False,rp_ai='sequence',is_boss=True,nzd_guardian=who,nzd_phase=1,
        loadout=[f'nz_{who}_p1_{i}' for i in range(len(MOVES[who][0]))],effects=[],passive_details=[],cooldowns={},npc_tier=3)
    f['stats'].update(max_hp=hp,resource_max=200,physical_attack=info[5],magic_attack=info[5],
        physical_defense=14 if who!='gargantua' else 24,magic_defense=14,speed=18,evasion=6)
    install(f,who)
    if who=='gargantua':f['stats']['speed']=9
    if who=='cocytus':f['stats']['speed']=22
    if who in ('aura','cz'):f['stats']['speed']=26

def phases(data):
    """Gate a guardian once. Victim dies into the ritual rather than skipping it."""
    if not data.get('nazarick_run_id'):return
    for f in data.get('enemies',{}).values():
        who=f.get('nzd_guardian')
        if who=='victim' and f.get('nzd_ritual') and not f.get('nzd_ritual_complete'):
            f['hp']=1
            # The postmortem seal is an autonomous one-shot script, not the
            # exhausted caster's remaining mana. Also repairs older demo saves.
            f['resource']=max(f.get('resource',0),30)
            f.get('cooldowns',{}).pop('nz_victim_p2_4',None)
            continue
        if not who or f.get('nzd_phase')!=1:continue
        threshold=0 if who=='victim' else f['stats']['max_hp']*.5
        if f['hp']<=threshold:
            if who=='victim':
                f['stats']['max_hp']=1
                f['stats']['magic_attack']=22
                f['name']='Защитный ритуал Виктима'
                f['nzd_ritual']=True
                f['resource']=f['stats']['resource_max']
                f['effects']=[]
                install(f,who)
            f.update(nzd_phase=2,hp=max(1,round(f['stats']['max_hp']*(1 if who=='victim' else .5))),
                loadout=[f'nz_{who}_p{p}_{i}' for p in (1,2) for i in range(len(MOVES[who][p-1]))],rp_ai_index=0)
            if who=='victim':f['loadout']=['nz_victim_p2_4']
            from arena_raid_engine import log_event
            log_event(data,f.get('enemy_id','e1'),'boss',GUARDIANS[who][0]+': '+GUARDIANS[who][3],nazarick_event='phase')

def intents(data):
    from arena_raid_engine import alive_players
    from arena_engine import validate_skill, BUILTIN_SKILLS
    from arena_raid_engine import pair_state, BOSS_SKILLS
    from arena_nazarick_guardians import prepare
    prepare(data)
    living=list(alive_players(data));out={}
    for i,(key,f) in enumerate(data['enemies'].items()):
        if f['hp']<=0:continue
        who=f.get('nzd_guardian');phase=f.get('nzd_phase',1)
        if not who:continue
        cycle=(0,1,2,0,4,1,3,2,4)
        turn=f.get('own_turns',0)
        # Linked guardians keep a common phrase of their rotation. Their own
        # speed/cast durations still decide whether releases fit the 0.5s window.
        linked=who in ('aura','mare','yuri','narberal','lupusregina','solution','entoma','cz')
        move=4 if f.get('nzd_ritual') else f.get('nzd_preview_move',cycle[(turn+(0 if linked else i))%len(cycle)])
        target=living[(turn+i)%len(living)] if living else None
        available=[]
        for m in (move,*(j for j in range(len(MOVES[who][phase-1])) if j!=move)):
            sid=f'nz_{who}_p{phase}_{m}'
            try:validate_skill(pair_state(f,data['players'][target]['fighter'] if target else f),'a',sid,{**BOSS_SKILLS,**BUILTIN_SKILLS});available.append(m)
            except ValueError:pass
        if not available and not f.get('nzd_ritual'):
            out[key]=dict(kind='recover',skill=None,targets=[],phase=phase,text='Восстановление сил')
            continue
        move=available[0] if available else 0
        if f.get('nzd_ritual'):move=4
        targets=(list(living) if move in (2,4) and who in ('gargantua','mare','victim','narberal','entoma') or move==3 and who=='aura' and phase==2 else [target] if target else [])
        out[key]=dict(kind='attack',skill=f'nz_{who}_p{phase}_{move}',targets=targets,
            phase=phase,text=MOVES[who][phase-1][move])
    if out:
        data['enemy_intents']=out;data['intent']=dict(kind='encounter',targets=[],phase=max(i['phase'] for i in out.values()),
            text=' · '.join(data['enemies'][key]['name']+': '+i['text'] for key,i in out.items()))
        first=next(iter(out));f=data['enemies'][first];who=f['nzd_guardian'];phase=f['nzd_phase']
        data['dialogue']=dict(speaker=f['name'],text=QUOTES[who][phase-1],persistent=True,id=f'nzd:{data["round"]}:{phase}')

QUOTES={
 'gargantua':('Камень под вашими ногами проснулся.','Своды озера дрожат от второго удара.'),
 'cocytus':('ДОСТОЙНЫЙ. ПРОТИВНИК.','ЧЕСТЬ. ТРЕБУЕТ. ВСЕХ. КЛИНКОВ.'),
 'aura':('Не разбегайтесь. Моим зверям так скучно.','Маре, теперь загоняем их вместе!'),
 'mare':('П-простите… вам нельзя дальше.','Лес… больше не будет вас щадить.'),
 'victim':('Хрупкий страж склоняет голову.','Жертва принята. Этаж запечатан.'),
 'sebas':('Прошу простить отсутствие гостеприимства.','Позвольте закончить эту аудиенцию.'),
 'yuri':('Уместны ли здесь ваши манеры?','Урок ещё не закончен.'),
 'narberal':('Насекомым не место перед троном.','Вам не пережить эту грозу.'),
 'lupusregina':('Ой, вы ещё живые? Как здорово!','Давайте продлим удовольствие.'),
 'solution':('Не трогайте обивку. Она дороже вас.','Уборка закончится очень быстро.'),
 'entoma':('Какой… приятный… голос.','Рой… проголодался.'),
 'cz':('Цель обнаружена.','Устранение. Повторить.'),
}

def view(data):
    room=ROOMS[data['nazarick_room']];f=next((f for f in data['enemies'].values() if f['hp']>0),data['boss'])
    who=f.get('nzd_guardian','crypt');phase=f.get('nzd_phase',1)
    return dict(stage=room['floor'],stage_count=10,guardian=who,phase=phase,title=room['name'],
        phase_name=GUARDIANS.get(who,GUARDIANS['gargantua'])[phase+1],background=background(room,phase),
        music=f'nz_{who}{phase}',hint='Победа сохраняет контрольную точку. Провал возвращает к началу этой комнаты.',
        stage_round=data['round'],pressure=0,pressure_max=1)
