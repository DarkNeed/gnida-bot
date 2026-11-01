"""Shared, persistent NPC camps. All changes live in the kingdom transaction."""
from copy import deepcopy
import hashlib
import json
import math
import secrets

from arena_kingdom_rules import HOUR,DAY,WIDTH,HEIGHT,SITES,NEUTRAL_LANDS,TERRAINS,terrain,distance,capacity
import arena_kingdom_war as army
import arena_kingdom_estate as estate
import arena_kingdom_council as council

KINDS={
 'goblins':dict(name='Гоблинская налоговая инспекция',color='#91bc62',roster=['militia','archers','vagrants'],
    names=['Гоблин с декларацией','Гоблин-арбалетчик','Выездной взыскатель'],
    text='Вычет за потерю конечности положен только при наличии самой конечности. Проверяют караваны и терпение соседей.'),
 'bandits':dict(name='Разбойничья таможня',color='#d69868',roster=['vagrants','archers','shields'],
    names=['Сборщик дорожной пошлины','Стрелок без лицензии','Старший по шлагбауму'],
    text='Платный въезд, платный выезд. Похороны тоже платные, но постоянным клиентам обещают скидку.'),
 'crypt':dict(name='Склеп бессрочного найма',color='#90b9b1',roster=['skeletons','skeletons','necromancers'],
    names=['Бывший стажёр','Вечный заместитель','Начальник отдела кадров'],
    text='На собеседовании обещали работу до гроба. Мелким шрифтом оказалось — и после. Мёртвые забирают припасы живых.'),
 'velvet':dict(name='Бархатный заговор',color='#c390b4',roster=['agents','agents','archers'],
    names=['Агент в кружевной форме','Дипломат по ночным вопросам','Охрана частного приёма'],
    text='Приглашение обещает взрослым гостям незабываемую ночь. Утром не хватает казначея, печати и половины обозов.'),
}


def connect(db):
    db.connection.executescript('''
      CREATE TABLE IF NOT EXISTS kingdom_camp_worlds(chat INTEGER PRIMARY KEY,next_spawn INTEGER NOT NULL,sequence INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS kingdom_camps(id TEXT PRIMARY KEY,chat INTEGER NOT NULL,q INTEGER NOT NULL,r INTEGER NOT NULL,
        status TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,data TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS kingdom_camps_chat ON kingdom_camps(chat,status);
    ''')


def rows(db,chat):
    result=[]
    for raw in db.connection.execute('SELECT * FROM kingdom_camps WHERE chat=? ORDER BY id',(chat,)):
        row=dict(raw);row['data']=json.loads(row['data']);result.append(row)
    return result


def get(db,chat,ident):
    if not isinstance(ident,str):raise ValueError('Выбери живой лагерь.')
    row=next((c for c in rows(db,chat) if c['id']==ident),None)
    if not row:raise ValueError('Лагерь находится в другом мире или уже исчез.')
    return row


def save(db,c):
    db.connection.execute('UPDATE kingdom_camps SET status=?,revision=revision+1,data=? WHERE id=?',
        (c['status'],json.dumps(c['data'],ensure_ascii=False),c['id']));c['revision']+=1


def occupied(db,chat,q,r):
    return bool(db.connection.execute("SELECT 1 FROM kingdom_camps WHERE chat=? AND q=? AND r=? AND status='active'",(chat,q,r)).fetchone())


def garrison(kind,stage):
    definition=KINDS[kind]
    fighters=army._fighters([dict(id=str(i),kind=k,slot=i,condition=100) for i,k in enumerate(definition['roster'])],'e:',.52+.13*stage)
    for i,u in enumerate(fighters):
        u['name']=definition['names'][i]
        if any(t in u['tags'] for t in ('ranged','mage','necro')):u['slot']=2+i
    return fighters


def spawn(db,world,now,seq):
    chat=world['chat'];towns=list(db.connection.execute('SELECT q,r FROM kingdom_towns WHERE chat=?',(chat,)))
    blocked={(t['q'],t['r']) for t in db.connection.execute('SELECT q,r FROM kingdom_tiles WHERE chat=?',(chat,))}
    blocked.update((c['q'],c['r']) for c in rows(db,chat) if c['status']=='active' or c['data'].get('ruin_until',0)>now)
    existing=[(c['q'],c['r']) for c in rows(db,chat) if c['status']=='active']
    choices=[(q,r) for r in range(HEIGHT) for q in range(WIDTH) if (q,r) not in blocked
        and (q,r) not in SITES and (q,r) not in NEUTRAL_LANDS and TERRAINS[terrain(world['seed'],q,r)]['buildable']
        and all(distance((q,r),p)>=3 for p in existing)
        and all(distance((q,r),(t['q'],t['r']))>=2 for t in towns)]
    if not choices:return False
    q,r=min(choices,key=lambda p:hashlib.sha256(f'{world["seed"]}:{seq}:{p}'.encode()).digest())
    kind=list(KINDS)[seq%len(KINDS)]
    data=dict(kind=kind,stage=1,hp=1200,max_hp=1200,garrison=garrison(kind,1),born=now,grow_at=now+DAY,
              pressure_at=now+DAY,busy=None,contributions={},raids=0,history=[],ruin_until=0)
    db.connection.execute('INSERT INTO kingdom_camps(id,chat,q,r,status,data) VALUES(?,?,?,?,?,?)',
        (secrets.token_hex(10),chat,q,r,'active',json.dumps(data,ensure_ascii=False)))
    return True


def finish(db,c,row,campaign):
    d=row['data'];m=army.initialize(d);cd=c['data'];at=campaign['finish']
    # Accrue the old army's upkeep and production through its return first.
    # Casualties and loot must not rewrite the preceding six hours.
    db._kingdom_advance_locked(row,db._kingdom_world_locked(row['chat']),until=at)
    report=army.resolve_battle(campaign['snapshot'],campaign['seed'])
    from arena_kingdom_siege import settle
    report.update(id=campaign['id'],target=c['id'],name=KINDS[cd['kind']]['name'],at=at,kind='living_camp',
                  lost=settle(m,report['final']['own']),loot={})
    remaining={u['id']:u['hp'] for u in report['final']['enemies']}
    for u in cd['garrison']:u['hp']=min(u['max_hp'],remaining.get(u['id'],0))
    cd['busy']=None;cd['raids']+=1
    damage=min(cd['hp'],math.ceil(cd['max_hp']*campaign['wall_fraction'])) if report['won'] else 0
    cd['hp']-=damage
    if damage:
        cd['contributions'][row['id']]=cd['contributions'].get(row['id'],0)+damage
        for key,amount in dict(food=45,wood=35,stone=25).items():
            actual=min(math.floor(amount*campaign['loot_multiplier']),max(0,capacity(d)-d['resources'][key]))
            d['resources'][key]+=actual;report['loot'][key]=actual
        m['glory']+=1
    report.update(wall_damage=damage,wall_hp=cd['hp'],wall_max=cd['max_hp'])
    cd['history']=(cd['history']+[dict(at=at,town=row['name'],damage=damage,won=report['won'])])[-12:]
    m['reports']=(m['reports']+[report])[-3:];m['campaign']=None
    db._kingdom_log(row,f'Набег на «{report["name"]}»: укрепления −{damage}, осталось {cd["hp"]}/{cd["max_hp"]}. Потеряно отрядов: {report["lost"]}.',at)
    db._kingdom_save_locked(row)
    if cd['hp']==0:
        c['status']='ruins';cd['ruin_until']=at+DAY
        total=sum(cd['contributions'].values())
        for ident,contribution in cd['contributions'].items():
            receiver=db._kingdom_row_locked(ident);rd=receiver['data']
            gains={}
            for key,amount in dict(food=240,wood=360,stone=300).items():
                gain=amount*cd['stage']*contribution//total
                gains[key]=min(gain,max(0,capacity(rd)-rd['resources'][key]));rd['resources'][key]+=gains[key]
            # One trophy for meaningful participation; last-hit chip does not qualify.
            trophy=contribution*5>=cd['max_hp']
            if trophy:estate.initialize(rd)['trophies']+=1
            db._kingdom_log(receiver,'Лагерь разрушен. Доля вклада '+str(round(contribution*100/total))+'%: '+
                ', '.join(f'{k} +{v}' for k,v in gains.items())+('. Трофей +1.' if trophy else '.'),at)
            db._kingdom_save_locked(receiver)
    save(db,c)


def advance(db,world,now):
    chat=world['chat']
    # Resolve by finish time globally, never by the order towns were viewed.
    due=[]
    for raw in db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=?',(chat,)).fetchall():
        row=db._kingdom_row_locked(raw['id']);campaign=row['data'].get('military',{}).get('campaign')
        if campaign and campaign.get('kind')=='living_camp' and campaign['finish']<=now:due.append((campaign['finish'],row['id']))
    for _,ident in sorted(due):
        row=db._kingdom_row_locked(ident);campaign=row['data']['military']['campaign']
        finish(db,get(db,chat,campaign['target']),row,campaign)
    camps=rows(db,chat)
    for c in camps:
        cd=c['data']
        if c['status']!='active':continue
        changed=False
        if not cd['busy'] and cd['grow_at']<=now and cd['stage']<3 and cd['hp']==cd['max_hp'] and cd['raids']==0:
            cd['stage']+=1;cd['hp']=cd['max_hp']=800+400*cd['stage'];cd['garrison']=garrison(cd['kind'],cd['stage'])
            cd['grow_at']=now+DAY;changed=True
        if cd['pressure_at']<=now:
            if cd['stage']>=2 and not cd['busy'] and any(u['hp']>0 for u in cd['garrison']):
                for raw in db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=?',(chat,)).fetchall():
                    row=db._kingdom_row_locked(raw['id'])
                    if distance((c['q'],c['r']),(row['q'],row['r']))>3:continue
                    # Settle past income/output first: a newly observed raid
                    # cannot retroactively reduce tax collection for old hours.
                    db._kingdom_advance_locked(row,world,until=now)
                    d=row['data'];factor=.5 if estate.has(d,'watchtower') else 1
                    loss={k:min(60,math.floor(d['resources'][k]*.05*factor)) for k in d['resources']}
                    for k,v in loss.items():d['resources'][k]-=v
                    d['order']=max(20,d['order']-math.ceil(2*factor))
                    db._kingdom_log(row,'Налёт из «'+KINDS[cd['kind']]['name']+'»: небольшая потеря запасов и порядка. Башня снижает ущерб.',now)
                    db._kingdom_save_locked(row)
            cd['pressure_at']=now+DAY;changed=True
        if changed:save(db,c)
    if not db.connection.execute('SELECT 1 FROM kingdom_towns WHERE chat=?',(chat,)).fetchone():return
    meta=db.connection.execute('SELECT * FROM kingdom_camp_worlds WHERE chat=?',(chat,)).fetchone()
    if not meta:
        seq=0
        for _ in range(3):spawn(db,world,now,seq);seq+=1
        db.connection.execute('INSERT INTO kingdom_camp_worlds VALUES(?,?,?)',(chat,now+12*HOUR,seq))
    elif meta['next_spawn']<=now:
        if sum(c['status']=='active' for c in rows(db,chat))<4:spawn(db,world,now,meta['sequence'])
        db.connection.execute('UPDATE kingdom_camp_worlds SET next_spawn=?,sequence=sequence+1 WHERE chat=?',(now+12*HOUR,chat))
    # Ruins are temporary; rewards/history remain in towns. No permanent replay archive.
    for c in rows(db,chat):
        if c['status']=='ruins' and c['data']['ruin_until']<=now:db.connection.execute('DELETE FROM kingdom_camps WHERE id=?',(c['id'],))


def public(db,chat,town,now):
    result=[]
    for c in rows(db,chat):
        cd=c['data'];definition=KINDS[cd['kind']]
        result.append(dict(id=c['id'],revision=c['revision'],q=c['q'],r=c['r'],status=c['status'],
            name=definition['name'],text=definition['text'],color=definition['color'],stage=cd['stage'],hp=cd['hp'],max_hp=cd['max_hp'],
            garrison=[dict(name=u['name'],hp=u['hp'],max_hp=u['max_hp']) for u in cd['garrison']],busy=bool(cd['busy']),
            pressure_at=cd['pressure_at'],history=cd['history'],raids=cd['raids'],
            contribution=cd['contributions'].get(town['id'],0) if town else 0,
            scout=bool(town and estate.has(town['data'],'watchtower')),
            ruin_until=cd['ruin_until'],grow_at=cd['grow_at']))
    return result


def march(db,row,payload,now):
    c=get(db,row['chat'],payload.get('camp'));cd=c['data'];d=row['data'];m=army.initialize(d)
    if type(payload.get('camp_revision')) is not int or payload['camp_revision']!=c['revision']:raise ValueError('Лагерь изменился. Обнови разведку.')
    if c['status']!='active' or cd['busy']:raise ValueError('Лагерь разрушен или к нему уже идёт армия.')
    if m['campaign'] or m.get('siege_lock'):raise ValueError('Армия уже занята походом или осадой.')
    tactic=payload.get('tactic')
    if not isinstance(tactic,str) or tactic not in army.TACTICS:raise ValueError('Выбери тактику.')
    selected=army.formation_units(d,now,ready=True)
    if not selected:raise ValueError('Поставь готовые отряды в боевой строй.')
    cost=council.supplies(d,len(selected))
    if d['resources']['food']<cost:raise ValueError('Не хватает походного снабжения.')
    d['resources']['food']-=cost;ident=secrets.token_hex(8)
    target=dict(name=KINDS[cd['kind']]['name'],tactic='guard',loot={})
    fighters=dict(own=council.buff(d,army._fighters(selected,'p:')),enemies=deepcopy(cd['garrison']))
    m['campaign']=dict(id=ident,kind='living_camp',target=c['id'],name=target['name'],started=now,finish=now+6*HOUR,
        unit_ids=[u['id'] for u in selected],seed=secrets.token_hex(16),wall_fraction=.35 if estate.has(d,'siegeworks') else .25,
        loot_multiplier=1.2 if estate.has(d,'caravan') else 1,
        snapshot=dict(target=c['id'],tactic=tactic,units=deepcopy(selected),fighters=fighters,outpost=target))
    cd['busy']=ident;save(db,c)
    return 'Набег начат: 6 часов вместе с возвращением. Потери отрядов настоящие. Повреждения лагеря сохранятся для всего чата.'
