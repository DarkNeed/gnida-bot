"""Settlement armies, trusted NPC campaigns and bounded tactical battle reports.

No arena stats, items, XP, francs or player-owned land are awarded by this mode.
The parent settlement transaction owns all spending and saves the result once.
"""
from copy import deepcopy
import math
import random
import secrets
import arena_kingdom_council as council

HOUR = 3600
SLOTS = ('Левый фланг', 'Правый фланг', 'Левый тыл', 'Правый тыл', 'Поддержка')
TACTICS = {
    'assault': dict(name='Штурм', text='Урон +15%, броня −15%. Быстро, но с большими потерями.'),
    'guard': dict(name='Оборона', text='Броня +6, урон −10%. Полезна против стрелков и налётчиков.'),
    'flank': dict(name='Обход', text='Урон −5%; каждые два раунда бойцы могут атаковать тыл, минуя переднюю линию.'),
}
UNITS = {
    'militia': dict(name='Городское ополчение', role='Пехота', hp=170, attack=30, armor=10, speed=8, evasion=3,
                    price=12000, food=40, wood=30, hours=6, barracks=1, stage=1, tags=['infantry'],
                    text='Недорого держит переднюю линию. В мирное время спорит с начальством, в военное — с копьём.'),
    'vagrants': dict(name='Свора с вокзала', role='Налётчики', hp=140, attack=38, armor=4, speed=11, evasion=8,
                    price=18000, food=55, wood=20, hours=6, barracks=1, stage=1, tags=['raider'],
                    text='Два таких отряда получают +20% урона. Вещмешок считается и оружием, и жилплощадью.'),
    'shields': dict(name='Щитоносцы', role='Тяжёлая пехота', hp=240, attack=23, armor=24, speed=5, evasion=0,
                    price=30000, food=60, wood=70, hours=8, barracks=1, stage=1, tags=['infantry','shield'],
                    text='Защищают лучников. Лозунг «стоять до конца» мелким шрифтом вписан в трудовой договор.'),
    'archers': dict(name='Следопыты', role='Стрелки', hp=120, attack=45, armor=5, speed=13, evasion=10,
                    price=32000, food=50, wood=80, hours=8, barracks=1, stage=1, tags=['ranged','recon'],
                    text='Стреляют из тыла. Вместе со щитами или бархатными агентами открывают разные синергии.'),
    'agents': dict(name='Бархатные агенты', role='Диверсанты', hp=125, attack=35, armor=6, speed=17, evasion=18,
                    price=35000, food=50, wood=40, hours=8, barracks=1, stage=1, faction='velvet', favor=1,
                    tags=['agent'], text='Каждый третий раунд обходят пехоту. Два отряда со следопытами дают всей армии +8 уклонения.'),
    'paladins': dict(name='Паладины отчётности', role='Святая пехота', hp=240, attack=43, armor=20, speed=6, evasion=1,
                    price=55000, food=80, wood=60, hours=12, barracks=2, stage=2, faction='light', favor=1,
                    tags=['infantry','holy'], text='Особенно опасны для нежити. Со жрецами получают +4 брони и сильнее лечатся.'),
    'priests': dict(name='Полевые жрецы', role='Лекари', hp=135, attack=20, armor=5, speed=9, evasion=5,
                    price=40000, food=60, wood=50, hours=10, barracks=1, stage=1, tags=['healer','holy'], heal=32,
                    text='Лечат раненого союзника вместо атаки. Спасение души не входит в боевую страховку.'),
    'skeletons': dict(name='Костяная смена', role='Нежить', hp=190, attack=31, armor=13, speed=7, evasion=2,
                    price=25000, food=30, wood=60, hours=6, barracks=1, stage=1, tags=['undead','infantry'],
                    text='Надёжная пехота для некроманта. Зарплата не нужна, но профсоюз требует снабжения.'),
    'necromancers': dict(name='Некроманты профсоюза', role='Тёмные маги', hp=115, attack=38, armor=4, speed=10, evasion=7,
                    price=65000, food=65, wood=80, hours=12, barracks=2, stage=2, faction='grave', favor=1,
                    tags=['mage','necro'], heal=30,
                    text='Частично игнорируют броню, чинят нежить и один раз за бой возвращают погибший костяной отряд.'),
}
OUTPOSTS = {
    'road_camp': dict(name='Диванная баррикада', faction='heating', stage=1, tactic='assault', terrain='Тракт',
                     roster=['vagrants','militia'], scale=.72, loot=dict(food=90,wood=65,stone=30),
                     text='Мятежная свора перекрыла тракт диваном. Рекомендуются три готовых отряда, хотя мебель уже считает себя крепостью.'),
    'velvet_spies': dict(name='Школа бархатных интриг', faction='velvet', stage=1, tactic='flank', terrain='Лес',
                        roster=['agents','agents','archers'], scale=.9, loot=dict(food=140,wood=100,stone=70),
                        text='Отступники Бархатного двора продают чужие секреты. Их бумаги опаснее кинжалов, а форма дороже вашей казны.'),
    'tithe_fort': dict(name='Форт последней десятины', faction='light', stage=2, tactic='guard', terrain='Холмы',
                      roster=['paladins','shields','archers','priests'], scale=1, loot=dict(food=180,wood=130,stone=150),
                      text='Раскольники ордена объявили налог священным. Щиты и лекарь делают прямой штурм дорогим удовольствием.'),
    'bone_foundry': dict(name='Фабрика вечной смены', faction='grave', stage=2, tactic='guard', terrain='Склеп',
                        roster=['skeletons','skeletons','necromancers','archers','priests'], scale=1.05,
                        loot=dict(food=200,wood=180,stone=220),
                        text='Чёрные работодатели заставляют мёртвых работать без выходных. Лекари и некромант стоят в тылу. Святая армия здесь особенно полезна.'),
}


def initial_military():
    return dict(units=[],formation=[None]*5,campaign=None,reports=[],cooldowns={},glory=0,siege_lock=None)


def initialize(data):
    data.setdefault('military',initial_military())
    data['military'].setdefault('siege_lock',None)
    return data['military']


def reserve_cap(data):
    return min(10,4+2*data['buildings']['barracks'])


def new_unit(kind, now, *, ready=False):
    return dict(id=secrets.token_hex(8),kind=kind,condition=100,
                ready_at=now if ready else now+UNITS[kind]['hours']*HOUR,service='recruit')


def requirements(data, kind):
    u=UNITS[kind];reasons=[]
    if data['buildings']['barracks']<u['barracks']:reasons.append(f"Казармы {u['barracks']} уровня")
    if data['stage']<u['stage']:reasons.append('Нужен город')
    if u.get('faction') and data['factions'].get(u['faction'],0)<u['favor']:
        reasons.append('Нужны положительные отношения с фракцией')
    return reasons


def synergies(kinds):
    result=[]
    if 'shields' in kinds and 'archers' in kinds:
        result.append(dict(id='covered',name='Стена и залп',text='Следопытам +6 брони и +15% урона.'))
    if 'paladins' in kinds and 'priests' in kinds:
        result.append(dict(id='holy',name='По штатному расписанию небес',text='Паладинам +4 брони, лечение жрецов +25%. Святые бойцы наносят нежити +30% урона.'))
    if kinds.count('agents')>=2 and 'archers' in kinds:
        result.append(dict(id='velvet',name='Бархатная разведка',text='Всем +8 уклонения; через раунд открывается обход вражеского тыла.'))
    if kinds.count('vagrants')>=2:
        result.append(dict(id='pack',name='Вокзальное братство',text='Отряды своры наносят +20% урона. Бонус не складывается за каждый новый отряд.'))
    if 'necromancers' in kinds and 'skeletons' in kinds:
        result.append(dict(id='grave',name='Коллективный загробный договор',text='Некроманты лечат нежить и один раз за бой возвращают один костяной отряд с 30% здоровья.'))
    return result


def formation_units(data, now, *, ready=False):
    m=initialize(data);lookup={u['id']:u for u in m['units']};result=[]
    for slot,uid in enumerate(m['formation']):
        if uid is None:continue
        if uid not in lookup:raise ValueError('Строй устарел: отряд больше не числится в резерве.')
        unit=lookup[uid]
        if ready and unit['ready_at']>now:raise ValueError('Дождись обучения или лечения всех отрядов в строю.')
        result.append(dict(**deepcopy(unit),slot=slot))
    if len({u['id'] for u in result})!=len(result):raise ValueError('Один отряд нельзя поставить в строй дважды.')
    return result


def _fighters(units, prefix, scale=1):
    result=[]
    for u in units:
        definition=UNITS[u['kind']];hp=round(definition['hp']*scale)
        result.append(dict(id=prefix+u['id'],source_id=u['id'],kind=u['kind'],name=definition['name'],slot=u['slot'],
                           max_hp=hp,hp=max(1,round(hp*u['condition']/100)),attack=definition['attack']*scale,
                           armor=definition['armor'],speed=definition['speed'],evasion=definition['evasion'],
                           heal=definition.get('heal',0)*scale,tags=list(definition['tags'])))
    return result


def _apply(team, tactic):
    combos=synergies([u['kind'] for u in team]);ids={s['id'] for s in combos}
    for u in team:
        if tactic=='assault':u['attack']*=1.15;u['armor']*=.85
        elif tactic=='guard':u['attack']*=.9;u['armor']+=6
        else:u['attack']*=.95
        if 'covered' in ids and u['kind']=='archers':u['armor']+=6;u['attack']*=1.15
        if 'holy' in ids:
            if u['kind']=='paladins':u['armor']+=4
            if u['kind']=='priests':u['heal']*=1.25
        if 'velvet' in ids:u['evasion']=min(35,u['evasion']+8)
        if 'pack' in ids and u['kind']=='vagrants':u['attack']*=1.2
        # The rear is vulnerable without infantry. Front placements trade armour
        # for covering the more fragile shooters/healers behind them.
        if u['slot']<2:u['armor']+=3
    return ids


def resolve_battle(snapshot, seed):
    """Pure, reproducible 12-round combat; client reports cannot declare victory."""
    rng=random.Random(seed);target=snapshot.get('outpost') or OUTPOSTS[snapshot['target']]
    if snapshot.get('fighters'):
        own=deepcopy(snapshot['fighters']['own']);enemies=deepcopy(snapshot['fighters']['enemies'])
    else:
        own=_fighters(snapshot['units'],'p:')
        enemies=_fighters([dict(id=str(i),kind=k,slot=i,condition=100) for i,k in enumerate(target['roster'])],'e:',target['scale'])
    # Enemy support and ranged units belong behind the first two squads too.
    for u in enemies:
        if any(tag in u['tags'] for tag in ('healer','mage','necro','ranged')):u['slot']=max(2,u['slot'])
    own_combo=_apply(own,snapshot['tactic']);enemy_combo=_apply(enemies,target['tactic'])
    initial=deepcopy(dict(own=own,enemies=enemies));events=[];raised={'p':False,'e':False}
    for round_number in range(1,13):
        order=sorted(own+enemies,key=lambda u:(-u['speed'],u['id']))
        for actor in order:
            if actor['hp']<=0:continue
            player=actor in own;friends=own if player else enemies;foes=enemies if player else own
            living=[u for u in foes if u['hp']>0]
            if not living:break
            side='p' if player else 'e';combos=own_combo if player else enemy_combo
            wounded=[u for u in friends if 0<u['hp']<u['max_hp']*.85 and (actor['kind']!='necromancers' or 'undead' in u['tags'])]
            if actor['heal'] and wounded:
                patient=min(wounded,key=lambda u:u['hp']/u['max_hp']);amount=min(patient['max_hp']-patient['hp'],round(actor['heal']))
                patient['hp']+=amount;events.append(dict(round=round_number,actor=actor['id'],target=patient['id'],kind='heal',value=amount));continue
            dead=[u for u in friends if u['hp']<=0 and 'undead' in u['tags']]
            if actor['kind']=='necromancers' and 'grave' in combos and dead and not raised[side]:
                patient=dead[0];patient['hp']=round(patient['max_hp']*.3);raised[side]=True
                events.append(dict(round=round_number,actor=actor['id'],target=patient['id'],kind='revive',value=patient['hp']));continue
            tactic=snapshot['tactic'] if player else target['tactic']
            flank=(tactic=='flank' or 'velvet' in combos) and round_number%2==0 or actor['kind']=='agents' and round_number%3==0
            back=[u for u in living if u['slot']>=2];front=[u for u in living if u['slot']<2]
            candidates=back if flank and back else front or living
            victim=rng.choice(candidates)
            if rng.random()<min(.35,victim['evasion']/100):
                events.append(dict(round=round_number,actor=actor['id'],target=victim['id'],kind='miss',value=0));continue
            armor=victim['armor']*(.35 if 'mage' in actor['tags'] or 'necro' in actor['tags'] else 1)
            damage=actor['attack']*100/(100+armor*3)*rng.uniform(.9,1.1)
            if 'holy' in actor['tags'] and 'undead' in victim['tags']:damage*=1.3
            critical=bool(actor.get('fortune') and rng.random()<.08)
            if critical:damage*=1.3
            damage=min(victim['hp'],max(2,round(damage)));victim['hp']-=damage
            events.append(dict(round=round_number,actor=actor['id'],target=victim['id'],kind='hit',value=damage,critical=critical))
        if not any(u['hp']>0 for u in own) or not any(u['hp']>0 for u in enemies):break
    return dict(won=any(u['hp']>0 for u in own) and not any(u['hp']>0 for u in enemies),rounds=round_number,
                initial=initial,events=events,final=deepcopy(dict(own=own,enemies=enemies)),
                synergies=synergies([u['kind'] for u in own]))


def advance(data, now):
    m=initialize(data);campaign=m['campaign']
    if not campaign or campaign['finish']>now:return None
    report=resolve_battle(campaign['snapshot'],campaign['seed']);target=campaign['snapshot'].get('outpost') or OUTPOSTS[campaign['snapshot']['target']]
    report.update(id=campaign['id'],target=campaign['snapshot']['target'],name=target['name'],at=campaign['finish'])
    fighters={u['source_id']:u for u in report['final']['own']};survivors=[];lost=[]
    for unit in m['units']:
        fighter=fighters.get(unit['id'])
        if fighter:
            if fighter['hp']<=0:lost.append(unit['id']);continue
            unit['condition']=max(1,math.ceil(100*fighter['hp']/fighter['max_hp']))
        survivors.append(unit)
    m['units']=survivors;m['formation']=[None if uid in lost else uid for uid in m['formation']]
    report['lost']=len(lost);report['loot']={}
    if report['won']:
        cap=600+data['buildings']['warehouse']*500
        for key,amount in target['loot'].items():
            actual=max(0,min(amount,cap-data['resources'][key]));data['resources'][key]+=actual;report['loot'][key]=actual
        m['glory']+=1
    # Campaigns are personal NPC activity, not ownership of a shared map tile.
    # Resolution on a late visit never permits back-to-back offline farming.
    m['cooldowns'][campaign['snapshot']['target']]=now+24*HOUR
    m['reports']=(m['reports']+[report])[-3:];m['campaign']=None
    return report


def view(data, now):
    m=initialize(data);result=deepcopy(m)
    if result['campaign']:
        result['campaign'].pop('seed');result['campaign'].pop('snapshot')
    result.update(capacity=reserve_cap(data),slots=list(SLOTS),catalog=deepcopy(UNITS),tactics=TACTICS,
                  synergies=synergies([u['kind'] for u in formation_units(data,now)]),
                  recruitment=[dict(id=k,reasons=requirements(data,k)) for k in UNITS])
    for key,u in result['catalog'].items():
        result['catalog'][key]=council.recruit_terms(data,u)
        effective=council.buff(data,_fighters([dict(id='preview',kind=key,condition=100,slot=2)],'p:'))[0]
        for stat,source in (('hp','max_hp'),('attack','attack'),('armor','armor'),('speed','speed'),('evasion','evasion')):
            result['catalog'][key][stat]=round(effective[source],1)
    result['supplies']=council.supplies(data,len([uid for uid in m['formation'] if uid]))
    result['outposts']=[dict(id=k,**deepcopy(t),cooldown=m['cooldowns'].get(k,0)) for k,t in OUTPOSTS.items()]
    return result


def action(db, row, command, payload, now):
    d=row['data'];m=initialize(d);units=m['units']
    deployed=set(m['campaign']['unit_ids']) if m['campaign'] else set()
    siege=m.get('siege_lock')
    if siege:
        if command=='march' or command=='formation' and (siege['role']=='attacker' or siege['phase']=='battle'):
            raise ValueError('Армия связана осадой. Подробности во вкладке «Войны».')
        if command in ('dismiss','recover') and payload.get('unit') in siege.get('unit_ids',[]):
            raise ValueError('Этот отряд участвует в осаде.')
    if command=='recruit':
        kind=payload.get('unit')
        if not isinstance(kind,str) or kind not in UNITS:raise ValueError('Неизвестный вид войск.')
        reasons=requirements(d,kind)
        if reasons:raise ValueError('Для найма: '+', '.join(reasons))
        if len(units)>=reserve_cap(d):raise ValueError('Резерв заполнен. Улучши казармы или распусти отряд.')
        if any(u['ready_at']>now for u in units):raise ValueError('Казармы уже обучают или лечат отряд.')
        definition=council.recruit_terms(d,UNITS[kind])
        for key in ('food','wood'):
            if d['resources'][key]<definition[key]:raise ValueError('Не хватает припасов для найма.')
        from arena_kingdom_finance import spend
        spend(db,row,definition['price'])
        for key in ('food','wood'):d['resources'][key]-=definition[key]
        units.append(new_unit(kind,now))
        return 'Начат найм: '+definition['name']+'.'
    if command=='formation':
        formation=payload.get('formation')
        if m['campaign']:raise ValueError('Дождись возвращения армии перед сменой строя.')
        if not isinstance(formation,list) or len(formation)!=5:raise ValueError('В строю ровно пять позиций.')
        ids={u['id'] for u in units};chosen=[uid for uid in formation if uid is not None]
        if any(not isinstance(uid,str) or uid not in ids for uid in chosen) or len(set(chosen))!=len(chosen):
            raise ValueError('Выбери разные отряды из своего резерва.')
        m['formation']=list(formation);return 'Построение сохранено.'
    if command in ('recover','dismiss'):
        uid=payload.get('unit');unit=next((u for u in units if u['id']==uid),None)
        if not unit:raise ValueError('Отряд не найден в твоём резерве.')
        if uid in deployed:raise ValueError('Отряд сейчас в походе.')
        if command=='dismiss':
            m['units']=[u for u in units if u['id']!=uid];m['formation']=[None if s==uid else s for s in m['formation']]
            return 'Отряд распущен без возврата затрат.'
        if unit['condition']>=100:raise ValueError('Отряд не нуждается в лечении.')
        if any(u['ready_at']>now for u in units):raise ValueError('Казармы уже заняты обучением или лечением.')
        cost=30+math.ceil((100-unit['condition'])/2)
        if d['resources']['food']<cost:raise ValueError('Не хватает пищи для восстановления.')
        d['resources']['food']-=cost;unit.update(condition=100,ready_at=now+3*HOUR,service='recover')
        return 'Восстановление отряда: 3 часа.'
    if command=='march':
        target_id=payload.get('target');tactic=payload.get('tactic')
        if not isinstance(target_id,str) or target_id not in OUTPOSTS:raise ValueError('Выбери NPC-заставу.')
        if not isinstance(tactic,str) or tactic not in TACTICS:raise ValueError('Выбери тактику.')
        if m['campaign']:raise ValueError('Армия уже в походе.')
        target=OUTPOSTS[target_id]
        if d['stage']<target['stage']:raise ValueError('Для этой цели нужен город.')
        if m['cooldowns'].get(target_id,0)>now:raise ValueError('Эта NPC-застава ещё восстанавливается после прошлого похода.')
        selected=formation_units(d,now,ready=True)
        if not selected:raise ValueError('Поставь хотя бы один готовый отряд в строй.')
        cost=council.supplies(d,len(selected))
        if d['resources']['food']<cost:raise ValueError('Не хватает походного снабжения.')
        d['resources']['food']-=cost
        fighters=dict(own=council.buff(d,_fighters(selected,'p:')),enemies=_fighters(
            [dict(id=str(i),kind=k,slot=i,condition=100) for i,k in enumerate(target['roster'])],'e:',target['scale']))
        m['campaign']=dict(id=secrets.token_hex(8),target=target_id,name=target['name'],started=now,finish=now+6*HOUR,
                           unit_ids=[u['id'] for u in selected],seed=secrets.token_hex(16),
                           snapshot=dict(target=target_id,tactic=tactic,units=deepcopy(selected),fighters=fighters,outpost=deepcopy(target)))
        return 'Армия отправлена. Поход с возвращением займёт 6 часов; потери отрядов настоящие.'
    raise ValueError('Неизвестный военный приказ.')
