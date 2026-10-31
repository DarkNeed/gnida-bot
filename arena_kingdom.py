"""Chat-local settlements. NPC resources never turn into francs or combat rewards."""
from copy import deepcopy
import json
import re
import secrets
import time

from arena_kingdom_rules import (WIDTH, HEIGHT, FOUND_PRICE, HOUR, EVENT_SECONDS, EVENT_INTERVAL, BOUNTY,
    TERRAINS, BUILDINGS, SITES, INCIDENTS, coordinates, neighbours, distance, terrain, capacity,
    population_cap, defense, rates, construction, initial, STAGES, FACTIONS, NEUTRAL_LANDS,
    incident_kind, land_cap, promotion)
import arena_kingdom_war as kingdom_war
import arena_kingdom_council as council
import arena_kingdom_time as world_time
from arena_kingdom_siege import KingdomSiegeMixin,initialize as initialize_pvp


def kingdom_now():
    return int(time.time())


class KingdomMixin(KingdomSiegeMixin):
    def _connect_kingdom(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS kingdom_worlds(chat INTEGER PRIMARY KEY,seed TEXT NOT NULL,created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS kingdom_towns(id TEXT PRIMARY KEY,chat INTEGER NOT NULL,owner INTEGER NOT NULL,
                name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',q INTEGER NOT NULL,r INTEGER NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,data TEXT NOT NULL,UNIQUE(chat,owner),UNIQUE(chat,q,r));
            CREATE TABLE IF NOT EXISTS kingdom_tiles(chat INTEGER NOT NULL,q INTEGER NOT NULL,r INTEGER NOT NULL,
                town TEXT NOT NULL REFERENCES kingdom_towns(id),PRIMARY KEY(chat,q,r));
            CREATE TABLE IF NOT EXISTS kingdom_requests(owner INTEGER NOT NULL,nonce TEXT NOT NULL,request TEXT NOT NULL,
                result TEXT NOT NULL,PRIMARY KEY(owner,nonce));
        ''')
        self._connect_kingdom_sieges()

    def _kingdom_world_locked(self, chat):
        self.connection.execute('INSERT OR IGNORE INTO kingdom_worlds VALUES(?,?,?)',(chat,secrets.token_hex(8),kingdom_now()))
        return dict(self.connection.execute('SELECT * FROM kingdom_worlds WHERE chat=?',(chat,)).fetchone())

    def _kingdom_row_locked(self, ident):
        row=self.connection.execute('SELECT * FROM kingdom_towns WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Поселение не найдено.')
        row=dict(row);row['data']=json.loads(row['data']);return row

    def _kingdom_save_locked(self, row):
        self.connection.execute('UPDATE kingdom_towns SET name=?,description=?,data=?,revision=revision+1 WHERE id=?',
            (row['name'],row['description'],json.dumps(row['data'],ensure_ascii=False),row['id']))
        row['revision']+=1

    @staticmethod
    def _kingdom_log(row, text, now):
        row['data']['history']=(row['data']['history']+[dict(at=now,text=text)])[-30:]

    def _kingdom_tiles_locked(self, row, world):
        return [dict(q=t['q'],r=t['r'],terrain=terrain(world['seed'],t['q'],t['r'])) for t in
                self.connection.execute('SELECT q,r FROM kingdom_tiles WHERE town=?',(row['id'],))]

    def _kingdom_resolve_locked(self, row, text, *, success, helper=None, choice=None):
        d=row['data'];event=d['event']
        if not event:raise ValueError('Событие уже завершено.')
        escrow=event.get('escrow',0)
        if escrow:
            recipient=helper if success and helper and helper!=row['owner'] else row['owner']
            self._add_francs_locked(row['chat'],recipient,escrow*9//10 if recipient!=row['owner'] else escrow)
        if success:
            d['order']=min(100,d['order']+5);d['prestige']+=1
            definition=INCIDENTS[event['kind']];choice=choice or {}
            faction=definition.get('faction')
            if faction:
                d['factions'][faction]=max(-10,min(10,d['factions'].get(faction,0)+choice.get('favor',0)))
            followup=choice.get('followup')
            if followup and followup not in d['stories']:d['stories'].append(followup)
            for key,amount in choice.get('grant',{}).items():
                d['resources'][key]=min(capacity(d),d['resources'][key]+amount)
        else:
            mitigation=min(.75,d['buildings']['barracks']*.20+d['buildings']['warehouse']*.10)
            for key in d['resources']:d['resources'][key]=max(0,d['resources'][key]-round(min(150,d['resources'][key]*.20)*(1-mitigation)))
            d['order']=max(20,d['order']-10)
        self._kingdom_log(row,text,kingdom_now())
        d['event']=None;d['next_event']=kingdom_now()+EVENT_INTERVAL

    def _kingdom_advance_locked(self, row, world):
        now=kingdom_now();d=row['data'];before=json.dumps(d,sort_keys=True)
        # Additive upgrade: an existing town keeps its land and unfinished job.
        d.setdefault('founded_at',d['history'][0]['at'] if d['history'] else now)
        d.setdefault('growth_hours',0);d.setdefault('factions',{});d.setdefault('stories',[])
        kingdom_war.initialize(d)
        council.initialize(d)
        initialize_pvp(d)
        job=d['construction']
        offline_budget=7*24
        # Finish in chronological order: offline production before construction
        # completion cannot receive the new building's output retroactively.
        def produce(until):
            nonlocal offline_budget
            hours=max(0,(until-d['last_tick'])//HOUR)
            if not hours:return
            counted=min(hours,offline_budget);offline_budget-=counted
            values=rates(d,self._kingdom_tiles_locked(row,world));cap=capacity(d)
            for key,value in values.items():d['resources'][key]=max(0,min(cap,d['resources'][key]+value*counted))
            if d['resources']['food']==0:d['order']=max(20,d['order']-min(20,2*counted))
            else:
                if d['order']<85:d['order']=min(85,d['order']+min(8,counted))
                if d['order']>=50:
                    growth,remainder=divmod(d['growth_hours']+counted,council.growth_hours(d));d['growth_hours']=remainder
                    d['population']=min(population_cap(d),d['population']+growth)
            d['last_tick']+=hours*HOUR
        milestones=[]
        if job and job['finish']<=now:milestones.append((job['finish'],'building'))
        reform=d['government']['pending']
        if reform and reform['finish']<=now:milestones.append((reform['finish'],'reform'))
        for finish,kind in sorted(milestones):
            produce(finish)
            if kind=='building':
                d['buildings'][job['building']]=job['level'];d['construction']=None
                self._kingdom_log(row,BUILDINGS[job['building']]['name']+f": завершён {job['level']} уровень.",finish)
            else:
                name=council.advance(d,finish);self._kingdom_log(row,'Завершена реформа: '+name+'.',finish)
            # New production and growth rates never apply retroactively.
            d['last_tick']=finish
        produce(now)
        report=kingdom_war.advance(d,now)
        if report:
            self._kingdom_log(row,('Победа' if report['won'] else 'Отступление')+' у NPC-заставы «'+report['name']+'». Потеряно отрядов: '+str(report['lost'])+'.',now)
        if d['event'] and d['event']['deadline']<=now:
            self._kingdom_resolve_locked(row,'На событие не ответили вовремя. Часть запасов потеряна, поселение и постройки сохранены.',success=False)
        elif not d['event'] and d['next_event']<=now:
            started=d['next_event']
            kind=d['stories'].pop(0) if d['stories'] else incident_kind(row['id'],d['event_seq'])
            d['event_seq']+=1
            d['event']=dict(id=secrets.token_hex(8),kind=kind,started=started,deadline=started+EVENT_SECONDS,escrow=0,battle=None,attempted=[])
            self._kingdom_log(row,'Новое событие: '+INCIDENTS[kind]['name'],started)
            if d['event']['deadline']<=now:
                self._kingdom_resolve_locked(row,'Событие истекло во время отсутствия. Ограниченная потеря запасов; поселение и постройки сохранены.',success=False)
        if before!=json.dumps(d,sort_keys=True):self._kingdom_save_locked(row)

    def _kingdom_public_locked(self, row, world, actor):
        d=deepcopy(row['data']);own=row['owner']==actor;tiles=self._kingdom_tiles_locked(row,world)
        event=d.get('event')
        if event:
            definition=INCIDENTS[event['kind']];event.update(deepcopy(definition))
            event['can_help']=event['kind']=='bandits' and bool(event['escrow']) and actor!=row['owner'] and actor not in event['attempted']
            event['bounty']=BOUNTY;event['payout']=BOUNTY*9//10
            if not own:event.pop('attempted',None)
        result=dict(id=row['id'],owner=row['owner'],name=row['name'],description=row['description'],q=row['q'],r=row['r'],
            revision=row['revision'],own=own,stage=d['stage'],population=d['population'],order=d['order'],prestige=d['prestige'],
            defense=defense(d),tiles=tiles,event=event,stage_name=STAGES[d['stage']]['name'])
        user=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(row['chat'],row['owner'])).fetchone()
        result['owner_name']=user['display_name'] if user else str(row['owner'])
        if own:
            result.update(resources=d['resources'],buildings=d['buildings'],construction=d['construction'],history=d['history'],
                          rates=rates(d,tiles),capacity=capacity(d),population_cap=population_cap(d),next_event=d['next_event'])
            result['building_options']=[]
            for key,definition in BUILDINGS.items():
                try:quote=construction(d,key,kingdom_now());allowed=True
                except ValueError:quote={};allowed=False
                result['building_options'].append(dict(id=key,**definition,level=d['buildings'][key],quote=quote,allowed=allowed))
            result['annex_price']=7500*(len(tiles)+1)
            result['territory_cap']=land_cap(d)
            profile=self._arena_profile_locked(row['chat'],actor,True);rank=self._guild_hunter_locked(actor)['rank']
            result.update(founded_at=d['founded_at'],factions=d['factions'],stories=len(d['stories']),
                          promotion=promotion(d,kingdom_now(),profile['level'],rank),military=kingdom_war.view(d,kingdom_now()))
            result['government']=council.view(d,kingdom_now())
            result['pvp']=deepcopy(d['pvp'])
        return result

    def _kingdom_view_locked(self, chat, actor):
        self._kingdom_siege_advance_locked(chat)
        world=self._kingdom_world_locked(chat);rows=[]
        for raw in self.connection.execute('SELECT id FROM kingdom_towns WHERE chat=? ORDER BY id',(chat,)).fetchall():
            row=self._kingdom_row_locked(raw['id']);self._kingdom_advance_locked(row,world);rows.append(row)
        claims={(r['q'],r['r']):r['town'] for r in self.connection.execute('SELECT * FROM kingdom_tiles WHERE chat=?',(chat,))}
        tiles=[dict(q=q,r=r,terrain=terrain(world['seed'],q,r),town=claims.get((q,r)),site=SITES.get((q,r))) for r in range(HEIGHT) for q in range(WIDTH)]
        own=next((row for row in rows if row['owner']==actor),None)
        owned={point for point,ident in claims.items() if own and ident==own['id']}
        for tile in tiles:
            point=(tile['q'],tile['r']);reason=''
            if tile['town']:reason='Эта земля уже принадлежит поселению.'
            elif tile['site']:reason='Место приключения нельзя застроить.'
            elif point in NEUTRAL_LANDS:reason='Общий участок тракта: остаётся нейтральным для всех.'
            elif not TERRAINS[tile['terrain']]['buildable']:reason='На реке пока нельзя строить.'
            elif own:
                if not any(point in neighbours(*other) for other in owned):reason='Выбери землю рядом с твоей границей.'
                elif len(owned)>=land_cap(own['data']):reason='Достигнут жёсткий предел территории этого этапа.'
            elif any(distance(point,(row['q'],row['r']))<3 for row in rows):reason='До центра соседа должно быть хотя бы три клетки.'
            tile.update(can_found=not own and not reason,can_annex=bool(own) and not reason,claim_reason=reason)
        profile=self._arena_profile_locked(chat,actor,True);hunter=self._guild_hunter_locked(actor)
        balance=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone()
        timed=world_time.encounters(world['seed'],kingdom_now(),tiles)
        for event in timed:event['claimed']=bool(own and event['id'] in own['data'].get('timed_visits',{}))
        return dict(chat=chat,actor=actor,now=kingdom_now(),width=WIDTH,height=HEIGHT,tiles=tiles,terrains=TERRAINS,
            environment=world_time.environment(kingdom_now()),map_events=timed,
            towns=[self._kingdom_public_locked(row,world,actor) for row in rows],balance=balance['balance'] if balance else 0,
            eligibility=dict(level=profile['level'],rank=hunter['rank'],allowed=profile['level']>=15 and hunter['rank']>=3,price=FOUND_PRICE),
            factions=FACTIONS,neutral_lands=[dict(q=q,r=r) for q,r in sorted(NEUTRAL_LANDS)],
            diplomacy=self._kingdom_siege_view_locked(chat,actor,rows),
            rules=dict(event_seconds=EVENT_SECONDS,stages=STAGES,growth_hours=6,
                       offline_hours=168,bounty=BOUNTY,war=True,npc_campaigns=True))

    async def kingdom_view(self, chat, actor):
        async with self._lock:
            self._require_feature_locked(chat,'arena')
            with self.connection:return self._kingdom_view_locked(chat,actor)

    def _kingdom_hero_locked(self, row, actor):
        from arena_encounters import create_encounter
        from arena_raid import RAID_ROUND_SECONDS
        if self._arena_busy_locked(row['chat'],actor):raise ValueError('Сначала заверши текущий бой или поход.')
        self._arena_require_choice_locked(row['chat'],actor,True)
        source=self._arena_source_locked(row['chat'],actor,actor,False,True)
        classes,skills=self._fighter_catalog_locked()
        combat=create_encounter([dict(actor_id=actor,fighter_id=actor,personal=True,slave_owner=actor)],
                                [source],classes,skills,['goblin','brute'],actor)
        for index,fighter in enumerate(combat['enemies'].values()):
            fighter.update(name=('Разведчик теплотрассы','Диванный король')[index],
                           kingdom_npc='Союз свободных теплотрасс',loadout=['bum_punch','encounter_smash'])
        event=row['data']['event'];token=secrets.token_urlsafe(12);now=int(time.time())
        combat.update(kingdom_id=row['id'],kingdom_event=event['id'],kingdom_helper=actor)
        combat['qte_modes']={str(actor):self._qte_enabled_locked(actor)}
        combat['players'][str(actor)]['character_slot']=self._character_active_locked(actor)
        config=dict(kingdom=True,roster=['goblin','brute'])
        self.connection.execute('''INSERT INTO arena_raids(token,chat_id,creator_id,status,round,data_json,created_at,deadline,boss_id,silent,encounter_json)
            VALUES(?,?,?,'active',1,?,?,?,'encounter',1,?)''',
            (token,row['chat'],actor,json.dumps(combat,ensure_ascii=False),now,now+RAID_ROUND_SECONDS,json.dumps(config)))
        self.connection.execute('INSERT INTO arena_raid_players VALUES(?,?,?,1,?)',(token,actor,actor,actor))
        event['battle']=token;event['attempted'].append(actor)
        self._kingdom_log(row,('Правитель лично' if actor==row['owner'] else 'Наёмный охотник')+' выступил против бандитов.',kingdom_now())
        return token

    def _kingdom_battle_finished_locked(self, raid, battle):
        row=self._kingdom_row_locked(battle['kingdom_id'])
        self._kingdom_advance_locked(row,self._kingdom_world_locked(row['chat']))
        event=row['data']['event']
        if event and event['id']==battle['kingdom_event'] and event.get('battle')==raid['token']:
            event['battle']=None
            if battle['won']:
                self._kingdom_resolve_locked(row,'Свора отступила. Диванный король обещал вернуться, когда высохнет мантия.',success=True,helper=battle['kingdom_helper'],choice=dict(favor=-1))
                battle['result']='Тракт освобождён. Возвращайся к поселению.'
            else:
                self._kingdom_log(row,'Вылазка не удалась. Можно выбрать другое решение; герой не теряет постоянный прогресс.',kingdom_now())
                battle['result']='Вылазка не удалась. Поселение ещё можно защитить другим способом.'
            self._kingdom_save_locked(row)
        else:
            battle['result']='Вылазка завершена, но событие уже истекло. Резерв заказа возвращён владельцу.'
        battle['rewards']={}

    async def kingdom_action(self, chat, actor, data):
        if not isinstance(data,dict):raise ValueError('Некорректный запрос.')
        nonce=data.get('nonce');action=data.get('action')
        if not isinstance(nonce,str) or not re.fullmatch(r'[0-9a-f]{32}',nonce) or not isinstance(action,str):raise ValueError('Обнови страницу и повтори действие.')
        if data.get('confirm') is not True:raise ValueError('Подтверди действие.')
        fields=dict(found=('q','r','name'),build=('building',),annex=('q','r'),rename=('name','description'),
                    supplies=(),promote=(),event=('choice',),help=(),recruit=('unit',),formation=('formation',),
                    recover=('unit',),dismiss=('unit',),march=('target','tactic'),reform=('field','choice'),
                    siege=('defender','q','r','tactic'),cancel_siege=('siege',),defense=('tactic',),explore=('event',))
        if action not in fields:raise ValueError('Неизвестное действие поселения.')
        relevant=('action','town','revision','confirm')+fields[action]
        request=json.dumps(dict(chat=chat,data={key:data[key] for key in relevant if key in data}),sort_keys=True,ensure_ascii=False)
        async with self._lock:
            self._require_feature_locked(chat,'arena')
            with self.connection:
                self._kingdom_siege_advance_locked(chat)
                prior=self.connection.execute('SELECT * FROM kingdom_requests WHERE owner=? AND nonce=?',(actor,nonce)).fetchone()
                if prior:
                    if prior['request']!=request:raise ValueError('Этот запрос уже использован для другого действия.')
                    return dict(**json.loads(prior['result']),view=self._kingdom_view_locked(chat,actor))
                world=self._kingdom_world_locked(chat);now=kingdom_now();result=dict(notice='Изменения сохранены.')
                if action=='found':
                    if self.connection.execute('SELECT 1 FROM kingdom_towns WHERE chat=? AND owner=?',(chat,actor)).fetchone():raise ValueError('У тебя уже есть поселение в этом чате.')
                    profile=self._arena_profile_locked(chat,actor,True)
                    if profile['level']<15 or self._guild_hunter_locked(actor)['rank']<3:raise ValueError('Нужны 15 уровень и ранг охотника C.')
                    q,r=coordinates(data.get('q'),data.get('r'))
                    if not TERRAINS[terrain(world['seed'],q,r)]['buildable'] or (q,r) in SITES or (q,r) in NEUTRAL_LANDS:raise ValueError('Здесь нельзя основать поселение.')
                    if self.connection.execute('SELECT 1 FROM kingdom_tiles WHERE chat=? AND q=? AND r=?',(chat,q,r)).fetchone():raise ValueError('Эта земля уже занята.')
                    for other in self.connection.execute('SELECT q,r FROM kingdom_towns WHERE chat=?',(chat,)):
                        if distance((q,r),(other['q'],other['r']))<3:raise ValueError('До другого поселения должно быть хотя бы три клетки.')
                    name=data.get('name')
                    if not isinstance(name,str) or len(name)>64 or not 2<=len(name.strip())<=32:raise ValueError('Название — от 2 до 32 символов.')
                    self._forge_spend_francs_locked(chat,actor,FOUND_PRICE)
                    ident=secrets.token_hex(10)
                    self.connection.execute('INSERT INTO kingdom_towns(id,chat,owner,name,q,r,data) VALUES(?,?,?,?,?,?,?)',
                        (ident,chat,actor,name.strip(),q,r,json.dumps(initial(now),ensure_ascii=False)))
                    self.connection.execute('INSERT INTO kingdom_tiles VALUES(?,?,?,?)',(chat,q,r,ident))
                    result['notice']='Поселение основано. Ратуша и фермы готовы.'
                else:
                    ident=data.get('town')
                    if not isinstance(ident,str):raise ValueError('Выбери поселение.')
                    row=self._kingdom_row_locked(ident)
                    if row['chat']!=chat:raise ValueError('Поселение находится в другом чате.')
                    self._kingdom_advance_locked(row,world)
                    if type(data.get('revision')) is not int or data['revision']!=row['revision']:raise ValueError('Поселение изменилось. Обнови карту и подтверди действие заново.')
                    if action!='help' and row['owner']!=actor:raise ValueError('Это не твоё поселение.')
                    d=row['data']
                    if action in ('annex','promote') and d['military'].get('siege_lock'):
                        raise ValueError('Территория и этап поселения заблокированы до завершения осады.')
                    if action in ('siege','cancel_siege','defense'):
                        result.update(self._kingdom_siege_action_locked(row,action,data,now))
                    elif action=='explore':
                        result['notice']=world_time.visit(self,row,world,data,now)
                    elif action=='reform':
                        result['notice']=council.reform(self,row,data,now);self._kingdom_log(row,result['notice'],now)
                    elif action in ('recruit','formation','recover','dismiss','march'):
                        result['notice']=kingdom_war.action(self,row,action,data,now)
                        self._kingdom_log(row,result['notice'],now)
                    elif action=='build':
                        if d['construction']:raise ValueError('Сначала дождись завершения текущего строительства.')
                        job=construction(d,data.get('building'),now)
                        for key in ('wood','stone'):
                            if d['resources'][key]<job[key]:raise ValueError('Не хватает древесины или камня.')
                        self._forge_spend_francs_locked(chat,actor,job['price'])
                        for key in ('wood','stone'):d['resources'][key]-=job[key]
                        d['construction']=job;self._kingdom_log(row,'Начато строительство: '+BUILDINGS[job['building']]['name'],now)
                    elif action=='annex':
                        q,r=coordinates(data.get('q'),data.get('r'));owned=self._kingdom_tiles_locked(row,world)
                        if len(owned)>=land_cap(d):raise ValueError('Достигнут жёсткий предел территории этого этапа.')
                        if not any((q,r) in neighbours(t['q'],t['r']) for t in owned):raise ValueError('Земля должна прилегать к твоей территории.')
                        if (q,r) in SITES or (q,r) in NEUTRAL_LANDS or not TERRAINS[terrain(world['seed'],q,r)]['buildable']:raise ValueError('Эту клетку нельзя присоединить.')
                        if self.connection.execute('SELECT 1 FROM kingdom_tiles WHERE chat=? AND q=? AND r=?',(chat,q,r)).fetchone():raise ValueError('Земля уже занята.')
                        self._forge_spend_francs_locked(chat,actor,7500*(len(owned)+1))
                        self.connection.execute('INSERT INTO kingdom_tiles VALUES(?,?,?,?)',(chat,q,r,row['id']))
                        self._kingdom_log(row,'Присоединена земля: '+TERRAINS[terrain(world['seed'],q,r)]['name'],now)
                    elif action=='rename':
                        name,description=data.get('name'),data.get('description','')
                        if not isinstance(name,str) or len(name)>64 or not 2<=len(name.strip())<=32 or not isinstance(description,str) or len(description)>180:raise ValueError('Название 2–32 символа, описание до 180.')
                        row.update(name=name.strip(),description=description.strip())
                    elif action=='supplies':
                        self._forge_spend_francs_locked(chat,actor,2500)
                        for key,amount in dict(food=120,wood=80,stone=60).items():d['resources'][key]=min(capacity(d),d['resources'][key]+amount)
                        self._kingdom_log(row,'Караван снабжения доставил продовольствие и материалы за 2500 ₣.',now)
                    elif action=='promote':
                        p=self._arena_profile_locked(chat,actor,True)
                        quote=promotion(d,now,p['level'],self._guild_hunter_locked(actor)['rank'])
                        if not quote:raise ValueError('Столица — последний этап хозяйства этой версии.')
                        if not quote['allowed']:
                            raise ValueError('Для следующего этапа нужно: '+', '.join(c['text'] for c in quote['checks'] if not c['ok']))
                        if d['construction']:raise ValueError('Дождись завершения текущей стройки перед сменой этапа.')
                        self._forge_spend_francs_locked(chat,actor,quote['price']);d['stage']=quote['stage']
                        self._kingdom_log(row,f"Новый этап: {quote['name']}. Предел земель — {quote['lands']}; уровень построек — {quote['building_cap']}.",now)
                    elif action in ('event','help'):
                        event=d['event']
                        if not event:raise ValueError('Событие уже завершено.')
                        if event.get('battle'):raise ValueError('Сначала дождись окончания вылазки.')
                        choice='hero' if action=='help' else data.get('choice')
                        definition=INCIDENTS[event['kind']]
                        if action=='help' and (actor==row['owner'] or not event['escrow'] or event['kind']!='bandits'):raise ValueError('Нет доступного заказа на помощь.')
                        if choice=='hero':
                            if event['kind']!='bandits' or actor in event['attempted']:raise ValueError('Личная попытка уже использована или здесь нужен другой способ.')
                            result['battle']=self._kingdom_hero_locked(row,actor)
                        elif choice=='bounty':
                            if event['kind']!='bandits' or event['escrow']:raise ValueError('Заказ уже размещён или не подходит этому событию.')
                            self._forge_spend_francs_locked(chat,actor,BOUNTY);event['escrow']=BOUNTY
                            self._kingdom_log(row,'Размещён заказ на зачистку. В резерве 5000 ₣, награда помощнику 4500 ₣ после победы.',now)
                        else:
                            selected=next((c for c in definition['choices'] if c['id']==choice),None)
                            if not selected:raise ValueError('Выбери доступное решение события.')
                            if choice=='garrison' and defense(d)<definition['threat']:raise ValueError(f"Нужно минимум {definition['threat']} силы гарнизона.")
                            if choice=='reserve' and d['buildings']['warehouse']<1:raise ValueError('Сначала нужны амбары.')
                            for key in ('food','wood','stone'):
                                if d['resources'][key]<selected.get(key,0):raise ValueError('Не хватает запасов для этого решения.')
                            if selected.get('francs'):self._forge_spend_francs_locked(chat,actor,selected['francs'])
                            for key in ('food','wood','stone'):d['resources'][key]-=selected.get(key,0)
                            self._kingdom_resolve_locked(row,selected['text'],success=True,choice=selected)
                    else:raise ValueError('Неизвестное действие поселения.')
                    self._kingdom_save_locked(row)
                self.connection.execute('INSERT INTO kingdom_requests VALUES(?,?,?,?)',(actor,nonce,request,json.dumps(result,ensure_ascii=False)))
                # Old revisions can no longer spend resources; keep a bounded
                # replay window instead of growing a free-edit journal forever.
                self.connection.execute('DELETE FROM kingdom_requests WHERE owner=? AND rowid NOT IN (SELECT rowid FROM kingdom_requests WHERE owner=? ORDER BY rowid DESC LIMIT 500)',(actor,actor))
                return dict(**result,view=self._kingdom_view_locked(chat,actor))
