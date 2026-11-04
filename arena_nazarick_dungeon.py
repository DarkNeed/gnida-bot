"""Durable party checkpoints and exactly-once, personally selected rewards."""
from copy import deepcopy
import json
import secrets
import time

from arena_nazarick_dungeon_rules import ROOMS, FLOORS, GUARDIANS, background, sprite
from arena_relics import DUNGEON_RELIC_IDS as RELIC_IDS, TICKET_ID, TICKET_NAME


class NazarickDungeonMixin:
    def _connect_nazarick_dungeon(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS nazarick_progress(
                actor INTEGER PRIMARY KEY, checkpoint INTEGER NOT NULL DEFAULT 0,
                completions INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS nazarick_runs(
                id TEXT PRIMARY KEY, chat INTEGER NOT NULL, leader INTEGER NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                created INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS nazarick_members(
                run TEXT NOT NULL REFERENCES nazarick_runs(id), actor INTEGER NOT NULL,
                PRIMARY KEY(run,actor));
            CREATE INDEX IF NOT EXISTS nazarick_members_actor ON nazarick_members(actor);
            CREATE TABLE IF NOT EXISTS nazarick_claims(
                run TEXT NOT NULL, actor INTEGER NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(run,actor));
        ''')

    def _nzd_progress_locked(self,actor):
        self.connection.execute('INSERT OR IGNORE INTO nazarick_progress(actor) VALUES(?)',(actor,))
        return dict(self.connection.execute('SELECT * FROM nazarick_progress WHERE actor=?',(actor,)).fetchone())

    def _nzd_current_locked(self,actor):
        row=self.connection.execute('''SELECT r.id FROM nazarick_runs r JOIN nazarick_members m ON m.run=r.id
            WHERE m.actor=? AND r.status IN ('lobby','ready','battle','failed') ORDER BY r.created DESC LIMIT 1''',(actor,)).fetchone()
        return row['id'] if row else None

    def _nzd_row_locked(self,ident,actor=None):
        if not isinstance(ident,str):raise ValueError('Некорректный поход.')
        raw=self.connection.execute('SELECT * FROM nazarick_runs WHERE id=?',(ident,)).fetchone()
        if not raw:raise ValueError('Поход не найден.')
        row=dict(raw);row['data']=json.loads(row['data'])
        row['members']=[r['actor'] for r in self.connection.execute('SELECT actor FROM nazarick_members WHERE run=? ORDER BY actor',(ident,))]
        if actor is not None and not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?',(row['chat'],actor)).fetchone():
            raise ValueError('Этот чат недоступен.')
        return row

    def _nzd_save_locked(self,row):
        self.connection.execute('UPDATE nazarick_runs SET status=?,revision=revision+1,data=? WHERE id=?',
            (row['status'],json.dumps(row['data'],ensure_ascii=False),row['id']))

    def _nzd_rewards_locked(self):
        from arena_engine import BUILTIN_PASSIVES
        from arena_equipment import CATALOG, EFFECTS
        return dict(treatises=[dict(id=k,kind='passive',name=BUILTIN_PASSIVES[k].name,
            description=' '.join(e.get('description','') for e in BUILTIN_PASSIVES[k].effects)) for k in RELIC_IDS],
            equipment=[dict(v,description=EFFECTS[v['effect']]) for v in CATALOG.values() if v['biome']=='nazarick'],
            ticket=TICKET_NAME,francs=2000,xp=500)

    def _nzd_public_locked(self,row,actor):
        d=row['data'];idx=d['checkpoint'];room=ROOMS[min(idx,len(ROOMS)-1)]
        members=[]
        for user in row['members']:
            u=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(row['chat'],user)).fetchone()
            members.append(dict(actor=user,name=u['display_name'] if u else str(user),checkpoint=self._nzd_progress_locked(user)['checkpoint']))
        claim=self.connection.execute('SELECT result FROM nazarick_claims WHERE run=? AND actor=?',(row['id'],actor)).fetchone()
        return dict(id=row['id'],chat=row['chat'],leader=row['leader'],status=row['status'],revision=row['revision'],
            version=2,checkpoint=idx,room=room,members=members,is_member=actor in row['members'],
            battle=d.get('battle'),blessed=d.get('blessed',False),blessing_votes=d.get('blessing_votes',[]),
            blessing_available=row['status']=='failed' and not d.get('blessed'),history=d['history'][-15:],
            treasury=d.get('treasury','available'),claim=json.loads(claim['result']) if claim else None,
            can_claim=row['status']=='completed' and actor in d.get('eligible',[]) and not claim,
            rewards=self._nzd_rewards_locked())

    async def nazarick_view(self,chat,actor):
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena')
                if not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone():raise ValueError('Этот чат недоступен.')
                current=self._nzd_current_locked(actor)
                lobbies=self.connection.execute("SELECT id FROM nazarick_runs WHERE chat=? AND status IN ('lobby','ready') ORDER BY created DESC LIMIT 12",(chat,)).fetchall()
                history=self.connection.execute('''SELECT r.id FROM nazarick_runs r JOIN nazarick_members m ON m.run=r.id
                    WHERE m.actor=? AND r.status='completed' ORDER BY r.created DESC LIMIT 10''',(actor,)).fetchall()
                return dict(actor=actor,chat=chat,progress=self._nzd_progress_locked(actor),floors=[dict(number=f,name=n,
                    background=background(next(r for r in ROOMS if r['floor']==f)),rooms=[r for r in ROOMS if r['floor']==f]) for f,n,_,_ in FLOORS],
                    active=self._nzd_public_locked(self._nzd_row_locked(current),actor) if current else None,
                    lobbies=[self._nzd_public_locked(self._nzd_row_locked(r['id']),actor) for r in lobbies],
                    history=[self._nzd_public_locked(self._nzd_row_locked(r['id']),actor) for r in history],rewards=self._nzd_rewards_locked())

    async def nazarick_create(self,chat,actor):
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena')
                if not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone():raise ValueError('Этот чат недоступен.')
                current=self._nzd_current_locked(actor)
                if current:return self._nzd_public_locked(self._nzd_row_locked(current),actor)
                if self._arena_busy_locked(chat,actor):raise ValueError('Сначала заверши текущий бой.')
                self._arena_require_choice_locked(chat,actor,True)
                checkpoint=self._nzd_progress_locked(actor)['checkpoint'];ident=secrets.token_urlsafe(12)
                data=dict(version=2,checkpoint=checkpoint,players={},sources=[],baseline={},battle=None,
                    history=['Отряд собирается. Контрольные точки хранятся без срока истечения.'],blessed=False,
                    blessing_votes=[],treasury='available')
                self.connection.execute('INSERT INTO nazarick_runs VALUES(?,?,?,\'lobby\',0,?,?)',
                    (ident,chat,actor,int(time.time()),json.dumps(data,ensure_ascii=False)))
                self.connection.execute('INSERT INTO nazarick_members VALUES(?,?)',(ident,actor))
                return self._nzd_public_locked(self._nzd_row_locked(ident),actor)

    def _nzd_snapshot_locked(self,row):
        from arena_raid_engine import create_raid_state
        d=row['data'];sources=[];members=[];classes,skills=self._fighter_catalog_locked()
        for user in row['members']:
            if self._arena_busy_locked(row['chat'],user):raise ValueError('Участник уже занят другим боем.')
            self._arena_require_choice_locked(row['chat'],user,True)
            sources.append(self._arena_source_locked(row['chat'],user,user,False,True))
            members.append(dict(actor_id=user,fighter_id=user,personal=True,slave_owner=user))
        players=create_raid_state(members,sources,classes,skills,'iron')['players']
        for key,p in players.items():
            p['character_slot']=self._character_active_locked(int(key))
            p['fighter']['name']=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(row['chat'],int(key))).fetchone()[0]
        d.update(players=players,baseline=deepcopy(players),sources=sources)

    def _nzd_battle_locked(self,row,treasury=False):
        from arena_raid_engine import create_raid_state
        from arena_raid import RAID_ROUND_SECONDS
        from arena_nazarick import ORDER,load_stage
        from arena_encounters import create_encounter,set_intents
        from arena_nazarick_dungeon_rules import configure_enemy
        d=row['data'];idx=d['checkpoint'];room=ROOMS[idx]
        if not d['players']:self._nzd_snapshot_locked(row)
        # At each saved checkpoint all fighters are restored, not their main accounts.
        players=deepcopy(d['baseline'])
        for p in players.values():
            p.update(selected=None,selected_target=None)
            if d['blessed']:
                p['fighter']['effects'].append(dict(id='nz_plot_armor',kind='incoming_damage_multiplier',value=.5,duration=1000000,
                    name='Сюжетная броня',description='Входящий урон −50% до конца подземелья. Билет и выбор трофеев сохраняются.'))
        enemies=['pandora'] if treasury else room['enemies']
        if not enemies:
            d['history'].append('Девятый этаж: роскошные покои. «Не пачкайте ковёр. Его химчистка дороже вашего воскресения». Отряд отдохнул.')
            self._nzd_checkpoint_locked(row,idx+1);return
        classes,skills=self._fighter_catalog_locked()
        members=[dict(actor_id=u,fighter_id=u,personal=True,slave_owner=u) for u in row['members']]
        if len(enemies)==1 and enemies[0] in ORDER:
            combat=create_raid_state(members,d['sources'],classes,skills,'nazarick')
            combat.update(players=players)
            combat['nazarick'].update(stage=ORDER.index(enemies[0]),phase=1,dungeon_single=True,
                initial_players={k:deepcopy(p['fighter']) for k,p in players.items()})
            load_stage(combat)
        else:
            # Validated built-in templates only; never accept RP stats or loadouts.
            templates=[]
            from arena_guild_rules import mob_templates
            for who in enemies:
                if who in GUARDIANS:
                    v=dict(name=GUARDIANS[who][0],description=GUARDIANS[who][1],class_id='ragamuffin',level=20,
                        archclass_id='',archclass_stage=10,defense_mode='dodge',skills=[f'nz_{who}_p1_{i}' for i in range(5)],
                        passives=[],stats={},ai='sequence',avatar_key='',sprite_key='',flip=False,scale=1,preset_id='')
                    templates.append(dict(id='nzd:'+who,revision=2,kind='mob',definition=v))
                else:
                    # The guild's skeleton artwork is not a monster identifier.
                    mid='wraith' if who=='knight' else 'lich'
                    t=mob_templates(dict(monsters=[mid],kind='hunt'),dict(kind='battle'),len(members))[0]
                    templates.append(t)
            combat=create_encounter(members,d['sources'],classes,skills,templates,row['leader'])
            combat.update(players=players,rp_mode=False)
            for f,who in zip(combat['enemies'].values(),enemies):
                if who in GUARDIANS:configure_enemy(f,who,len(members))
                else:
                    hp=round((180 if who=='knight' else 145)*(1+.6*(len(members)-1))*(1.15 if room['floor']==2 else 1))
                    f.update(rp_sandbox=False,is_boss=True,hp=hp,name='Рыцарь катакомб' if who=='knight' else 'Костяной заклинатель',
                        guild_monster='wraith' if who=='knight' else 'lich',guild_sprite=sprite(who),
                        loadout=[f'nz_{who}_p1_0'])
                    f['stats'].update(max_hp=hp,physical_attack=9,magic_attack=12,physical_defense=7,magic_defense=7,evasion=3)
        combat.update(nazarick_run_id=row['id'],nazarick_room=idx,nazarick_treasury=treasury,rewards_enabled=False)
        if combat.get('boss_id')=='nazarick':
            from arena_nazarick_guardians import install
            install(combat['boss'],enemies[0],legacy=True)
        if combat.get('kind')=='encounter':set_intents(combat,skills)
        combat['qte_modes']={str(u):self._qte_enabled_locked(u) for u in row['members']}
        combat['unified_version']=3
        from arena_unified_queue import initialize
        from arena_unified_store import catalog
        initialize(combat,catalog(self))
        now=int(time.time());token=secrets.token_urlsafe(12)
        bossid='nazarick' if combat.get('boss_id')=='nazarick' else 'encounter'
        config=dict(nazarick_dungeon=True,roster=[dict(id=w,name=GUARDIANS[w][0] if w in GUARDIANS else w) for w in enemies])
        self.connection.execute('''INSERT INTO arena_raids(token,chat_id,creator_id,status,round,data_json,created_at,deadline,boss_id,silent,encounter_json)
            VALUES(?,?,?,'active',1,?,?,?,?,1,?)''',
            (token,row['chat'],row['leader'],json.dumps(combat,ensure_ascii=False),now,now+RAID_ROUND_SECONDS,bossid,json.dumps(config,ensure_ascii=False)))
        for u in row['members']:self.connection.execute('INSERT INTO arena_raid_players VALUES(?,?,?,1,?)',(token,u,u,u))
        d['battle']=token;row['status']='battle'
        d['history'].append('Начат бой: '+('Сокровищница · Актёр Пандоры' if treasury else room['name']))

    def _nzd_checkpoint_locked(self,row,checkpoint):
        d=row['data'];d.update(checkpoint=checkpoint,battle=None,blessing_votes=[])
        row['status']='completed' if checkpoint==len(ROOMS) else 'ready'
        for user in row['members']:
            self._nzd_progress_locked(user)
            if row['status']=='completed':self.connection.execute('UPDATE nazarick_progress SET checkpoint=0 WHERE actor=?',(user,))
            else:self.connection.execute('UPDATE nazarick_progress SET checkpoint=MAX(checkpoint,?) WHERE actor=?',(checkpoint,user))
        if row['status']=='completed':
            d['eligible']=list(row['members'])
            self.connection.executemany('UPDATE nazarick_progress SET completions=completions+1 WHERE actor=?',[(u,) for u in row['members']])
            d['history'].append('Король-колдун повержен! Каждый выбирает трактат и снаряжение. Билет гарантирован.')
        else:d['history'].append('Контрольная точка сохранена. Отряд полностью восстановлен. Можно продолжить позже.')

    def _nazarick_dungeon_battle_finished_locked(self,raid,battle):
        row=self._nzd_row_locked(battle['nazarick_run_id']);d=row['data']
        if row['status']!='battle' or d['battle']!=raid['token']:raise ValueError('Контрольная точка этого боя уже изменена.')
        original=list(row['members'])
        departed=[u for u in original if battle['players'][str(u)].get('withdrawn') or battle['players'][str(u)].get('reward_blocked')]
        for u in departed:
            self.connection.execute('DELETE FROM nazarick_members WHERE run=? AND actor=?',(row['id'],u));row['members'].remove(u)
        if departed:
            d['sources']=[s for u,s in zip(original,d['sources']) if u not in departed]
            for key in ('players','baseline'):d[key]={k:p for k,p in d[key].items() if int(k) not in departed}
            if row['members'] and row['leader'] not in row['members']:
                row['leader']=row['members'][0];self.connection.execute('UPDATE nazarick_runs SET leader=? WHERE id=?',(row['leader'],row['id']))
        if not row['members']:
            row['status']='closed';d['battle']=None;d['history'].append('Все участники покинули поход. Личные сохранения не удалены.')
            battle['rewards']={};battle['result']=d['history'][-1];self._nzd_save_locked(row);return
        if battle['won']:
            if battle.get('nazarick_treasury'):
                d.update(treasury='cleared',battle=None);row['status']='ready';d['history'].append('Пандора повержен. Путь к трону открыт; трофеи выбираются после Аинза.')
            else:self._nzd_checkpoint_locked(row,d['checkpoint']+1)
        else:
            row['status']='failed';d['battle']=None;d['blessing_votes']=[]
            d['history'].append('Отряд повержен. Контрольная точка сохранена; повторите эту комнату или примите благословение.')
        battle['rewards']={};battle['result']=d['history'][-1]
        self._nzd_save_locked(row)

    async def nazarick_get(self,ident,actor):
        async with self._lock:
            with self.connection:return self._nzd_public_locked(self._nzd_row_locked(ident,actor),actor)

    async def nazarick_action(self,ident,actor,action,revision=None,**args):
        async with self._lock:
            with self.connection:
                row=self._nzd_row_locked(ident,actor);d=row['data']
                self._require_feature_locked(row['chat'],'arena')
                if action in ('start','retry','treasury') and row['status']=='battle' and actor==row['leader']:
                    return self._nzd_public_locked(row,actor)
                if type(revision) is not int or revision!=row['revision']:raise ValueError('Поход изменился. Обновите страницу.')
                if action=='join':
                    if row['status'] not in ('lobby','ready'):raise ValueError('Состав меняется только между боями.')
                    if actor in row['members']:return self._nzd_public_locked(row,actor)
                    if len(row['members'])>=3:raise ValueError('В отряде уже трое.')
                    if self._nzd_current_locked(actor):raise ValueError('У тебя уже есть сохранённый поход. Сначала выйди из него.')
                    if self._nzd_progress_locked(actor)['checkpoint']<d['checkpoint']:raise ValueError('Сначала пройди предыдущие этажи своим персонажем.')
                    self.connection.execute('INSERT INTO nazarick_members VALUES(?,?)',(ident,actor));row['members'].append(actor)
                    d.update(players={},baseline={},sources=[])
                elif action=='leave':
                    if row['status'] not in ('lobby','ready','failed') or actor not in row['members']:raise ValueError('Выйти можно между боями незавершённого похода.')
                    self.connection.execute('DELETE FROM nazarick_members WHERE run=? AND actor=?',(ident,actor));row['members'].remove(actor)
                    d['players']={};d['baseline']={};d['sources']=[]
                    if not row['members']:row['status']='closed'
                    elif actor==row['leader']:row['leader']=row['members'][0];self.connection.execute('UPDATE nazarick_runs SET leader=? WHERE id=?',(row['leader'],ident))
                elif action in ('start','retry','treasury'):
                    if actor!=row['leader'] or row['status'] not in ('lobby','ready','failed'):raise ValueError('Продолжить может лидер между боями.')
                    if action=='treasury' and (ROOMS[d['checkpoint']]['floor']!=9 or d['treasury']!='available'):raise ValueError('Сокровищница доступна на девятом этаже один раз за поход.')
                    for user in row['members']:
                        if self._arena_busy_locked(row['chat'],user):raise ValueError('Участник занят другим боем.')
                    self._nzd_battle_locked(row,action=='treasury')
                elif action=='blessing':
                    if actor not in row['members'] or row['status']!='failed' or d['blessed']:raise ValueError('Благословение сейчас недоступно.')
                    if actor not in d['blessing_votes']:d['blessing_votes'].append(actor)
                    if all(u in d['blessing_votes'] for u in row['members']):
                        d['blessed']=True;row['status']='ready';d['history'].append('Благословение принято единогласно. Входящий урон −50%; франки и XP −50%. Билет, трактат и снаряжение сохраняются.')
                else:raise ValueError('Неизвестное действие подземелья.')
                self._nzd_save_locked(row)
                return self._nzd_public_locked(self._nzd_row_locked(ident),actor)

    async def nazarick_claim(self,ident,actor,treatise,equipment):
        async with self._lock:
            with self.connection:
                row=self._nzd_row_locked(ident,actor);d=row['data']
                if row['status']!='completed' or actor not in d.get('eligible',[]):raise ValueError('Награда доступна только участникам завершённого похода.')
                old=self.connection.execute('SELECT result FROM nazarick_claims WHERE run=? AND actor=?',(ident,actor)).fetchone()
                if old:return json.loads(old['result'])
                catalog=self._nzd_rewards_locked()
                if treatise not in RELIC_IDS or equipment not in [g['key'] for g in catalog['equipment']]:raise ValueError('Выберите трактат и снаряжение из трофеев Назарика.')
                from arena_equipment import CATALOG,public_item
                self._arena_add_item_locked(row['chat'],actor,'passive',treatise,'legendary')
                self._arena_add_item_locked(row['chat'],actor,'class_ticket',TICKET_ID,'legendary')
                # Fixed properties, no hidden random rerolls on claim retries.
                item=dict(id=secrets.token_hex(10),key=equipment,rank='S',rarity='legendary',upgrade=0,
                    affixes=[k for k in ('max_hp','physical_defense','magic_defense') if k!=CATALOG[equipment]['main']][:2],
                    favorite=False,rerolled=False,created=int(time.time()))
                self._gear_save_locked(actor,item);self._gear_touch_locked(actor)
                francs=1000 if d['blessed'] else 2000;xp=250 if d['blessed'] else 500
                self._add_francs_locked(row['chat'],actor,francs)
                # Grant to the participating slot; never the subsequently selected character.
                p=d['baseline'][str(actor)];slot=p.get('character_slot',1)
                active=self._character_active_locked(actor)
                if slot!=active:self._character_switch_locked(actor,slot)
                # Arena XP helpers bind the active slot; the scoped context is restored below.
                try:
                    self._grant_profile_xp_locked('personal_profiles',row['chat'],actor,xp)
                finally:
                    if slot!=active:self._character_switch_locked(actor,active)
                result=dict(treatise=treatise,ticket=TICKET_NAME,equipment=public_item(item),francs=francs,xp=xp)
                self.connection.execute('INSERT INTO nazarick_claims VALUES(?,?,?)',(ident,actor,json.dumps(result,ensure_ascii=False)))
                return result
