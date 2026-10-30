"""Account-wide hunter progression and saved party expeditions.

All actions and payouts share the existing SQLite lock/transaction. Combat uses
ordinary character snapshots and the multi-enemy resolver, never free RP builds.
"""
from collections import Counter
from copy import deepcopy
import json
import random
import secrets
import time
from arena_guild_rules import (RANKS, DAILY_LIMIT, RUN_SECONDS, LOBBY_SECONDS,
    CONTRACTS, MONSTERS, BIOMES, SUPPLIES, EVENTS, make_map, mob_templates,
    calibration_rank, fingerprint, art, INVITE_COOLDOWN)
from arena_raid import raid_day, RAID_ROUND_SECONDS


class GuildMixin:
    def _connect_guild(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS guild_hunters(
                actor_id INTEGER PRIMARY KEY, rank INTEGER NOT NULL DEFAULT 0,
                reputation INTEGER NOT NULL DEFAULT 0, peak_rank INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
                dungeons INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0,
                rank_wins INTEGER NOT NULL DEFAULT 0, clearance INTEGER NOT NULL DEFAULT 0,
                calibrated INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS guild_daily(
                actor_id INTEGER NOT NULL, day TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0 CHECK(used BETWEEN 0 AND 3),
                PRIMARY KEY(actor_id,day));
            CREATE TABLE IF NOT EXISTS guild_runs(
                id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, leader INTEGER NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                created INTEGER NOT NULL, expires INTEGER NOT NULL, data_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS guild_runs_active ON guild_runs(status,expires);
            CREATE TABLE IF NOT EXISTS guild_members(
                run_id TEXT NOT NULL REFERENCES guild_runs(id), actor_id INTEGER NOT NULL,
                PRIMARY KEY(run_id,actor_id));
            CREATE INDEX IF NOT EXISTS guild_members_actor ON guild_members(actor_id);
            CREATE TABLE IF NOT EXISTS guild_requests(
                actor_id INTEGER NOT NULL, nonce TEXT NOT NULL, fingerprint TEXT NOT NULL,
                run_id TEXT NOT NULL, PRIMARY KEY(actor_id,nonce));
            CREATE TABLE IF NOT EXISTS guild_bag(
                actor_id INTEGER NOT NULL, item TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
                PRIMARY KEY(actor_id,item));
            CREATE TABLE IF NOT EXISTS guild_purchases(
                actor_id INTEGER NOT NULL, nonce TEXT NOT NULL, item TEXT NOT NULL,
                PRIMARY KEY(actor_id,nonce));
            CREATE TABLE IF NOT EXISTS guild_settlements(
                run_id TEXT NOT NULL, actor_id INTEGER NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(run_id,actor_id));
            CREATE TABLE IF NOT EXISTS guild_invites(
                run_id TEXT PRIMARY KEY REFERENCES guild_runs(id), message_id INTEGER,
                last_posted INTEGER NOT NULL DEFAULT 0, claim TEXT NOT NULL DEFAULT '',
                claim_until INTEGER NOT NULL DEFAULT 0, published_revision INTEGER NOT NULL DEFAULT -1,
                signature TEXT NOT NULL DEFAULT '', retry_at INTEGER NOT NULL DEFAULT 0);
        ''')

    def _guild_hunter_locked(self, actor):
        self.connection.execute('INSERT OR IGNORE INTO guild_hunters(actor_id) VALUES(?)', (actor,))
        return dict(self.connection.execute('SELECT * FROM guild_hunters WHERE actor_id=?', (actor,)).fetchone())

    def _guild_used_locked(self, actor):
        row=self.connection.execute('SELECT used FROM guild_daily WHERE actor_id=? AND day=?', (actor,raid_day())).fetchone()
        return row['used'] if row else 0

    def _guild_busy_locked(self, actor, exclude='', active_only=False):
        return bool(self.connection.execute('''SELECT 1 FROM guild_members m JOIN guild_runs r ON r.id=m.run_id
            WHERE m.actor_id=? AND r.id<>? AND r.status IN ('lobby','active') AND r.expires>? AND (?=0 OR r.status='active')''',
            (actor,exclude,int(time.time()),int(active_only))).fetchone())

    def _guild_row_locked(self, ident, actor=None):
        if not isinstance(ident,str):raise ValueError('Некорректный поход.')
        raw=self.connection.execute('SELECT * FROM guild_runs WHERE id=?', (ident,)).fetchone()
        if not raw:raise ValueError('Поход не найден.')
        row=dict(raw)
        if actor is not None and not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?', (row['chat_id'],actor)).fetchone():
            raise ValueError('Этот чат недоступен.')
        row['data']=json.loads(row.pop('data_json'))
        row['members']=[r['actor_id'] for r in self.connection.execute('SELECT actor_id FROM guild_members WHERE run_id=? ORDER BY actor_id',(ident,))]
        return row

    def _guild_save_locked(self, row):
        self.connection.execute('UPDATE guild_runs SET status=?,revision=revision+1,expires=?,data_json=? WHERE id=?',
            (row['status'],row['expires'],json.dumps(row['data'],ensure_ascii=False),row['id']))

    def _guild_expire_locked(self):
        now=int(time.time())
        for raw in self.connection.execute("SELECT id FROM guild_runs WHERE status IN ('lobby','active') AND expires<=?",(now,)).fetchall():
            row=self._guild_row_locked(raw['id'])
            if row['status']=='lobby':row['status']='cancelled';self._guild_save_locked(row)
            else:
                token=row['data'].get('battle')
                if token:
                    raid=self._raid_row_locked(token)
                    if raid['status']=='active':
                        battle=json.loads(raid['data_json']);battle.update(finished=True,won=False,result='Срок похода истёк.',rewards={})
                        self.connection.execute("DELETE FROM arena_qte_flows WHERE scope='raid' AND token=?",(token,))
                        self._raid_save_locked(raid,battle,'cancelled')
                self._guild_settle_locked(row,False,'Срок похода истёк.')

    def _guild_require_rank_locked(self, actor, contract):
        hunter=self._guild_hunter_locked(actor)
        if RANKS.index(contract['rank'])>hunter['rank']+1:
            raise ValueError('Можно брать заказ не выше своего ранга +1.')
        if self._guild_used_locked(actor)>=DAILY_LIMIT:raise ValueError('Три допуска на сегодня уже использованы. Сброс — в 00:00 МСК.')

    def _guild_contract_locked(self, actor, chat, key):
        if not isinstance(key,str):raise ValueError('Некорректный код заказа.')
        if key in CONTRACTS:return deepcopy(CONTRACTS[key])
        if key=='calibration':
            hunter=self._guild_hunter_locked(actor)
            profile=self._arena_profile_locked(chat,actor,True)
            rank=calibration_rank(profile['level'])
            if not rank or hunter['calibrated'] or hunter['wins'] or hunter['losses']:
                raise ValueError('Вступительное испытание недоступно: оно одноразовое, до первого оплаченного выхода, с 5 уровня.')
            c=deepcopy(CONTRACTS[rank.lower()+'_elite']);c.update(id='calibration',name='Квалификация · '+rank,calibration=True)
            return c
        raise ValueError('Заказ не найден.')

    async def guild_create(self, chat, actor, contract_id, nonce):
        if not isinstance(nonce,str) or not 8<=len(nonce)<=80:raise ValueError('Нужен уникальный номер запроса.')
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena');self._guild_expire_locked()
                if not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone():raise ValueError('Этот чат недоступен.')
                mark=fingerprint((chat,contract_id));old=self.connection.execute('SELECT * FROM guild_requests WHERE actor_id=? AND nonce=?',(actor,nonce)).fetchone()
                if old:
                    if old['fingerprint']!=mark:raise ValueError('Этот номер запроса использован для другого заказа.')
                    return self._guild_public_locked(self._guild_row_locked(old['run_id']),actor)
                contract=self._guild_contract_locked(actor,chat,contract_id)
                if not contract.get('calibration'):self._guild_require_rank_locked(actor,contract)
                elif self._guild_used_locked(actor)>=DAILY_LIMIT:raise ValueError('Нет допусков на сегодня.')
                if self._arena_busy_locked(chat,actor):raise ValueError('Сначала заверши текущий бой или поход.')
                self._arena_require_choice_locked(chat,actor,True)
                now=int(time.time());ident=secrets.token_urlsafe(12)
                data=dict(contract=contract,nodes=[],position=None,pending=None,votes={},vote_deadline=0,
                    players={},battle=None,finds=0,history=['Заказ принят. Соберите отряд или начните в одиночку.'],supplies_used={},revealed=False)
                self.connection.execute('INSERT INTO guild_runs VALUES(?,?,?,?,0,?,?,?)',
                    (ident,chat,actor,'lobby',now,now+LOBBY_SECONDS,json.dumps(data,ensure_ascii=False)))
                self.connection.execute('INSERT INTO guild_members VALUES(?,?)',(ident,actor))
                self.connection.execute('INSERT INTO guild_requests VALUES(?,?,?,?)',(actor,nonce,mark,ident))
                return self._guild_public_locked(self._guild_row_locked(ident),actor)

    def _guild_start_locked(self, row, actor):
        if actor!=row['leader']:raise ValueError('Начать поход может лидер.')
        if row['status']=='active':return
        if row['status']!='lobby':raise ValueError('Сбор уже закрыт.')
        if not 1<=len(row['members'])<=3:raise ValueError('Нужны 1–3 участника.')
        d=row['data'];c=d['contract'];sources=[];members=[]
        for user in row['members']:
            if c.get('calibration'):
                if len(row['members'])!=1:raise ValueError('Вступительное испытание проходят в одиночку.')
                self._guild_contract_locked(user,row['chat_id'],'calibration')
                if self._guild_used_locked(user)>=DAILY_LIMIT:raise ValueError('Нет допусков на сегодня.')
            else:self._guild_require_rank_locked(user,c)
            if self._arena_busy_locked(row['chat_id'],user,guild_exclude=row['id']):raise ValueError('Участник уже занят другим боем.')
            self._arena_require_choice_locked(row['chat_id'],user,True)
            sources.append(self._arena_source_locked(row['chat_id'],user,user,False,True))
            members.append(dict(actor_id=user,fighter_id=user,personal=True,slave_owner=user))
        # Snapshot canonical sources exactly once; room transitions never refill.
        from arena_raid_engine import create_raid_state
        classes,skills=self._fighter_catalog_locked()
        fighters=create_raid_state(members,sources,classes,skills,'iron')['players']
        for key,p in fighters.items():
            p['character_slot']=self._character_active_locked(p['actor_id'])
            p['fighter']['name']=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(row['chat_id'],int(key))).fetchone()['display_name']
            self.connection.execute('''INSERT INTO guild_daily VALUES(?,?,1) ON CONFLICT(actor_id,day)
                DO UPDATE SET used=used+1''',(int(key),raid_day()))
            if c.get('calibration'):self.connection.execute('UPDATE guild_hunters SET calibrated=1 WHERE actor_id=?',(int(key),))
        d['players']=fighters;d['sources']=sources;d['nodes']=make_map(c,secrets.randbits(64))
        d['position']='start' if c['kind']=='dungeon' else None
        row['status']='active';row['expires']=int(time.time())+RUN_SECONDS
        d['history'].append('Допуски списаны. Снимки персонажей сохранены; здоровье между комнатами не восстанавливается автоматически.')
        if c['kind']!='dungeon':self._guild_enter_locked(row,'boss')

    def _guild_battle_locked(self,row,node):
        from arena_encounters import create_encounter,set_intents
        from arena_guild_rules import art
        d=row['data'];classes,skills=self._fighter_catalog_locked()
        templates=mob_templates(d['contract'],node,len(row['members']))
        members=[dict(actor_id=u,fighter_id=u,personal=True,slave_owner=u) for u in row['members']]
        combat=create_encounter(members,d['sources'],classes,skills,templates,row['leader'])
        combat.update(players=deepcopy(d['players']),rp_mode=False,guild_run_id=row['id'],guild_node=node['id'])
        for p in combat['players'].values():p.update(selected=None,selected_target=None)
        for enemy,template in zip(combat['enemies'].values(),templates):
            enemy.update(guild_monster=template['guild_monster'],guild_sprite=art(template['guild_monster']))
            if template['guild_monster']=='troll':
                enemy['passive_details'].append(dict(name='Плоть болот',rarity='rare',effects=[dict(kind='guild_regen',value=.04,description='Восстанавливает 4% HP перед действием. Горение подавляет восстановление.')]))
        set_intents(combat,skills)
        combat['qte_modes']={str(u):self._qte_enabled_locked(u) for u in row['members']}
        token=secrets.token_urlsafe(12);now=int(time.time())
        config=dict(guild=True,roster=[dict(id=t['guild_monster'],name=t['definition']['name']) for t in templates])
        self.connection.execute('''INSERT INTO arena_raids(token,chat_id,creator_id,status,round,data_json,created_at,deadline,boss_id,silent,encounter_json)
            VALUES(?,?,?,'active',1,?,?,?,'encounter',1,?)''',
            (token,row['chat_id'],row['leader'],json.dumps(combat,ensure_ascii=False),now,now+RAID_ROUND_SECONDS,json.dumps(config,ensure_ascii=False)))
        for u in row['members']:self.connection.execute('INSERT INTO arena_raid_players VALUES(?,?,?,1,?)',(token,u,u,u))
        d['battle']=token

    def _guild_enter_locked(self,row,node_id):
        d=row['data'];node=next((n for n in d['nodes'] if n['id']==node_id),None)
        if not node or node['cleared']:raise ValueError('Комната уже пройдена или не существует.')
        d.update(position=node_id,pending=None,votes={},vote_deadline=0)
        if node['kind'] in ('battle','elite','boss'):self._guild_battle_locked(row,node)
        elif node['kind']=='event':d['pending']=dict(kind='event',event=node['event'])
        elif node['kind']=='rest':d['pending']=dict(kind='rest')
        else:
            amount=15+RANKS.index(d['contract']['rank'])*12
            d['finds']+=amount;node['cleared']=True
            d['history'].append(f'Найдены ценности: +{amount} ₣ каждому при успешном возвращении.')

    def _guild_event_locked(self,row,choice):
        d=row['data'];node=next(n for n in d['nodes'] if n['id']==d['position'])
        pending=d['pending'];event=pending.get('event');living=[p['fighter'] for p in d['players'].values() if not p.get('withdrawn') and p['fighter']['hp']>0]
        if pending['kind']=='rest':
            if choice=='heal':
                for f in living:f['hp']=min(f['stats']['max_hp'],f['hp']+round(f['stats']['max_hp']*.30))
                message='Привал: +30% HP живым участникам.'
            elif choice=='focus':
                for f in living:
                    f['resource']=min(f['stats']['resource_max'],f['resource']+round(f['stats']['resource_max']*.5));f['cooldowns']={}
                message='Медитация: +50% энергии, перезарядки завершены.'
            else:raise ValueError('Недоступный вариант привала.')
        elif choice=='leave':message='Отряд прошёл мимо.'
        elif event=='shrine' and choice=='blessing':
            for f in living:
                f['hp']=min(f['stats']['max_hp'],f['hp']+round(f['stats']['max_hp']*.4))
                f['effects'].append(dict(id='guild_shrine',kind='damage_taken_pct',value=.15,duration=100000))
            message='Благословение: +40% HP. Цена света: входящий урон +15% до конца похода.'
        elif event=='shrine' and choice=='break' or event=='cocoon' and choice=='rescue' and node['roll']<.5:
            node.update(ambush='spider' if event=='cocoon' else 'guardian',bonus=True);d['pending']=None
            self._guild_battle_locked(row,node);d['history'].append('Засада! Выбор пути превратился в бой.');return
        elif event=='cocoon' and choice in ('rescue','burn'):
            amount=60 if choice=='rescue' else 15;d['finds']+=amount;message=f'В походном мешке +{amount} ₣ каждому.'
        elif event=='well' and choice=='drink':
            for f in living:
                f['resource']=min(f['stats']['resource_max'],f['resource']+round(f['stats']['resource_max']*.45))
                f['hp']=max(1,f['hp']-round(f['stats']['max_hp']*.1))
            message='Колодец: +45% энергии, −10% максимального HP.'
        elif event=='well' and choice=='offering':
            d['finds']=d['finds']*7//10
            for f in living:self._guild_cleanse(f)
            message='Подношение принято: потеряна часть находок, чума и раны очищены.'
        else:raise ValueError('Недоступный выбор события.')
        node['cleared']=True;d['pending']=None;d['history'].append(message)

    @staticmethod
    def _guild_cleanse(f):
        f['effects']=[e for e in f['effects'] if e['kind'] not in ('bleed','burn','plague_fever','plague_spores')]

    def _guild_vote_locked(self,row,actor,choice):
        d=row['data'];eligible=[k for k,p in d['players'].items() if not p.get('withdrawn') and p['fighter']['hp']>0]
        if str(actor) not in eligible:raise ValueError('Маршрут выбирают живые участники отряда.')
        if d['pending']:
            if d['pending']['kind']=='rest':allowed=['heal','focus']
            else:allowed=[c['id'] for c in EVENTS[d['pending']['event']]['choices']]
        else:
            current=next(n for n in d['nodes'] if n['id']==d['position'])
            if not current['cleared']:raise ValueError('Сначала завершите эту комнату.')
            allowed=current['links']
        if choice not in allowed:raise ValueError('Выберите соседнюю комнату или доступный вариант события.')
        if str(actor) in d['votes']:raise ValueError('Твой голос уже принят.')
        d['votes'][str(actor)]=choice
        if not d['vote_deadline']:d['vote_deadline']=int(time.time())+40
        self._guild_resolve_votes_locked(row)

    def _guild_resolve_votes_locked(self,row):
        d=row['data'];eligible=[k for k,p in d['players'].items() if not p.get('withdrawn') and p['fighter']['hp']>0]
        if not d['votes'] or not (all(k in d['votes'] for k in eligible) or d['vote_deadline']<=int(time.time())):return False
        counts=Counter(d['votes'].values());best=max(counts.values());tied=sorted(k for k,v in counts.items() if v==best)
        choice=d['votes'].get(str(row['leader']))
        choice=choice if choice in tied else tied[0]
        d.update(votes={},vote_deadline=0)
        if d['pending']:self._guild_event_locked(row,choice)
        else:self._guild_enter_locked(row,choice)
        return True

    def _guild_supply_locked(self,row,actor,item,target):
        d=row['data'];key=str(actor)+':'+str(d['position'])
        if item not in SUPPLIES or key in d['supplies_used']:raise ValueError('Можно использовать один припас на участника между комнатами.')
        p=d['players'].get(str(actor));other=d['players'].get(str(target or actor))
        if not p or p.get('withdrawn') or not other or other.get('withdrawn'):raise ValueError('Выберите участника этого отряда.')
        if p['fighter']['hp']<=0:raise ValueError('Павший участник не может использовать припасы.')
        stock=self.connection.execute('SELECT quantity FROM guild_bag WHERE actor_id=? AND item=?',(actor,item)).fetchone()
        if not stock or stock['quantity']<1:raise ValueError('Этого припаса нет в рюкзаке.')
        f=p['fighter'];o=other['fighter']
        if item=='bandage':f['hp']=min(f['stats']['max_hp'],f['hp']+round(f['stats']['max_hp']*.3));f['effects']=[e for e in f['effects'] if e['kind']!='bleed']
        elif item=='ration':f['resource']=min(f['stats']['resource_max'],f['resource']+round(f['stats']['resource_max']*.35))
        elif item=='antidote':self._guild_cleanse(o)
        elif item=='scout':d['revealed']=True
        elif item=='camp':
            for x in d['players'].values():
                q=x['fighter']
                if not x.get('withdrawn') and q['hp']>0:q['hp']=min(q['stats']['max_hp'],q['hp']+round(q['stats']['max_hp']*.25))
        elif item=='revive':
            if o['hp']>0:raise ValueError('Этот союзник ещё жив.')
            o['hp']=max(1,round(o['stats']['max_hp']*.35));self._guild_cleanse(o)
        elif item=='balm':
            f['hp']=min(f['stats']['max_hp'],f['hp']+round(f['stats']['max_hp']*.5))
            f['resource']=min(f['stats']['resource_max'],f['resource']+round(f['stats']['resource_max']*.5));self._guild_cleanse(f)
        self.connection.execute('UPDATE guild_bag SET quantity=quantity-1 WHERE actor_id=? AND item=?',(actor,item))
        d['supplies_used'][key]=item;d['history'].append(f'{f["name"]}: использован {SUPPLIES[item]["name"]}.')

    def _guild_settle_locked(self,row,won,reason,retreat=False):
        if row['status']!='active':return
        d=row['data'];c=d['contract'];results={}
        for actor in row['members']:
            old=self.connection.execute('SELECT result_json FROM guild_settlements WHERE run_id=? AND actor_id=?',(row['id'],actor)).fetchone()
            if old:results[str(actor)]=json.loads(old['result_json']);continue
            h=self._guild_hunter_locked(actor);p=d['players'].get(str(actor),{})
            eligible=not p.get('withdrawn') and not p.get('reward_blocked') and p.get('missed',0)<3
            success=won and eligible
            francs=(c['reward']+d['finds']) if success else d['finds']//2 if retreat and eligible else 0
            reputation=0;rank_before=h['rank'];loot='';equipment_loot=[]
            if success:
                difficulty=RANKS.index(c['rank'])
                reputation=40 if difficulty>h['rank'] else 28 if difficulty==h['rank'] else 0
                if c.get('calibration'):
                    h.update(rank=difficulty,reputation=0,rank_wins=0,clearance=0)
                    reputation=0
                else:
                    h['reputation']=min(100,h['reputation']+reputation)
                    if difficulty>=h['rank']:h['rank_wins']+=1;h['clearance']=max(h['clearance'],int(c['kind']!='hunt'))
                    if h['reputation']>=100 and h['rank_wins']>=3 and h['clearance'] and h['rank']<6:
                        h.update(rank=h['rank']+1,reputation=0,rank_wins=0,clearance=0)
                h['wins']+=1;h['streak']=0;h['dungeons']+=int(c['kind']=='dungeon')
                # A guaranteed useful guild item; elite/dungeon also drop a real
                # non-boss tractate. No raid cooldowns, pet grants or PvP rating.
                supply='bandage' if difficulty<2 else 'ration' if difficulty<4 else 'antidote'
                self.connection.execute('INSERT INTO guild_bag VALUES(?,?,1) ON CONFLICT(actor_id,item) DO UPDATE SET quantity=quantity+1',(actor,supply))
                loot=SUPPLIES[supply]['name']
                equipment_loot.append(self._gear_loot_locked('guild:'+row['id']+':boss',actor,c,
                    guaranteed=c['kind']=='dungeon',chance=.45 if c['kind']=='elite' else .15,
                    materials=3 if c['kind']=='dungeon' else 1))
                if c['kind']=='dungeon':
                    for node in d['nodes']:
                        if node.get('cleared') and node['kind'] in ('treasure','elite'):
                            equipment_loot.append(self._gear_loot_locked('guild:'+row['id']+':'+node['id'],actor,c,chance=.25,materials=1))
                if c['kind']!='hunt':
                    from arena_engine import BUILTIN_SKILLS
                    from arena_archprogress import skill_branch
                    rarity='common' if difficulty<2 else 'uncommon' if difficulty<4 else 'rare' if difficulty<6 else 'epic'
                    pool=[s for s in BUILTIN_SKILLS.values() if s.rarity==rarity and s.class_id!='ragamuffin' and 'raid_loot' not in s.tags and not skill_branch(s) and not any(t.startswith('archclass:') for t in s.tags)]
                    if pool:
                        s=random.SystemRandom().choice(pool);self._arena_add_item_locked(row['chat_id'],actor,'skill',s.skill_id,s.rarity);loot+=' · трактат «'+s.name+'»'
            else:
                reputation=-12;h['reputation']=max(0,h['reputation']-12);h['losses']+=1;h['streak']+=1
                if h['reputation']==0 and h['streak']>=3 and h['rank']>0:
                    h.update(rank=h['rank']-1,reputation=60,rank_wins=0,clearance=0,streak=0)
            h['peak_rank']=max(h['peak_rank'],h['rank'])
            self.connection.execute('''UPDATE guild_hunters SET rank=?,reputation=?,peak_rank=?,wins=?,losses=?,dungeons=?,streak=?,rank_wins=?,clearance=? WHERE actor_id=?''',
                tuple(h[k] for k in ('rank','reputation','peak_rank','wins','losses','dungeons','streak','rank_wins','clearance'))+(actor,))
            if francs:self._add_francs_locked(row['chat_id'],actor,francs)
            result=dict(won=success,francs=francs,loot=loot,equipment_loot=equipment_loot,reputation=reputation,rank=RANKS[h['rank']],rank_before=RANKS[rank_before])
            self.connection.execute('INSERT INTO guild_settlements VALUES(?,?,?)',(row['id'],actor,json.dumps(result,ensure_ascii=False)));results[str(actor)]=result
        row['status']='completed' if won else 'retreated' if retreat else 'failed'
        d.update(results=results,reason=reason,battle=None,pending=None,votes={},vote_deadline=0)
        d['history'].append(reason);self._guild_save_locked(row)

    def _guild_battle_finished_locked(self,raid,battle):
        ident=battle.get('guild_run_id')
        if not ident:return
        row=self._guild_row_locked(ident);d=row['data']
        if row['status']!='active' or d['battle']!=raid['token']:raise ValueError('Бой не относится к текущей комнате похода.')
        d['players']=deepcopy(battle['players']);d['battle']=None
        node=next(n for n in d['nodes'] if n['id']==battle['guild_node'])
        if battle['won']:
            node['cleared']=True
            d['finds']+=35 if node.get('bonus') else 8+RANKS.index(d['contract']['rank'])*5
            d['history'].append('Комната зачищена. Здоровье, энергия и перезарядки перенесены дальше.')
            if node['kind']=='boss':self._guild_settle_locked(row,True,'Заказ выполнен. Отряд вернулся в гильдию.')
            else:self._guild_save_locked(row)
        else:self._guild_settle_locked(row,False,'Отряд потерпел поражение. Обычный инвентарь не потерян.')
        battle['result']='Комната зачищена — возвращайтесь к карте.' if battle['won'] and node['kind']!='boss' else row['data'].get('reason','Поход завершён.')
        battle['rewards']={}

    async def guild_action(self,ident,actor,action,revision=None,**args):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked();row=self._guild_row_locked(ident,actor);d=row['data']
                self._require_feature_locked(row['chat_id'],'arena')
                if action=='start' and row['status']=='active' and actor==row['leader']:return self._guild_public_locked(row,actor)
                if type(revision) is not int or revision!=row['revision']:raise ValueError('Поход изменился. Обновите страницу.')
                if action=='join':
                    if row['status']!='lobby':raise ValueError('Сбор уже закрыт.')
                    if actor in row['members']:return self._guild_public_locked(row,actor)
                    if len(row['members'])>=3:raise ValueError('Все места заняты.')
                    if d['contract'].get('calibration'):raise ValueError('Квалификация — одиночное испытание.')
                    self._guild_require_rank_locked(actor,d['contract'])
                    if self._arena_busy_locked(row['chat_id'],actor):raise ValueError('Ты уже занят другим боем или походом.')
                    self._arena_require_choice_locked(row['chat_id'],actor,True)
                    self.connection.execute('INSERT INTO guild_members VALUES(?,?)',(ident,actor));row['members'].append(actor)
                elif action=='leave':
                    if row['status']!='lobby' or actor not in row['members']:raise ValueError('Выйти можно до начала похода.')
                    if actor==row['leader']:row['status']='cancelled'
                    else:self.connection.execute('DELETE FROM guild_members WHERE run_id=? AND actor_id=?',(ident,actor));row['members'].remove(actor)
                elif action=='start':self._guild_start_locked(row,actor)
                elif action in ('vote','supply','retreat'):
                    if row['status']!='active' or actor not in row['members']:raise ValueError('Ты не участник активного похода.')
                    if d['battle']:raise ValueError('Сначала завершите текущий бой.')
                    if action=='vote':self._guild_vote_locked(row,actor,args.get('choice'))
                    elif action=='supply':self._guild_supply_locked(row,actor,args.get('item'),args.get('target'))
                    else:
                        if actor!=row['leader']:raise ValueError('Отступление объявляет лидер.')
                        self._guild_settle_locked(row,False,'Отступление: сохранена половина походных франков, награды заказа нет.',True)
                        return self._guild_public_locked(self._guild_row_locked(ident),actor)
                else:raise ValueError('Неизвестное действие гильдии.')
                self._guild_save_locked(row)
                return self._guild_public_locked(self._guild_row_locked(ident),actor)

    def _guild_public_locked(self,row,actor):
        d=row['data'];current=next((n for n in d['nodes'] if n['id']==d['position']),None)
        nodes=[]
        for n in d['nodes']:
            visible=d['revealed'] or n['cleared'] or n['kind']=='boss' or not current or n['layer']<=current['layer']+1
            public={k:n[k] for k in ('id','layer','lane','links','cleared')}
            public['kind']=n['kind'] if visible else 'unknown';nodes.append(public)
        members=[];classes,_=self._fighter_catalog_locked()
        for user in row['members']:
            profile=self._guild_hunter_locked(user);raw=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(row['chat_id'],user)).fetchone()
            p=d['players'].get(str(user));f=p['fighter'] if p else None
            character=self._arena_profile_locked(row['chat_id'],user,True)
            cid=f['class_id'] if f else character['class_id']
            members.append(dict(actor_id=user,name=raw['display_name'] if raw else str(user),rank=RANKS[profile['rank']],
                class_name=classes[cid].name,level=f['level'] if f else character['level'],
                hp=f['hp'] if f else None,max_hp=f['stats']['max_hp'] if f else None,
                resource=f['resource'] if f else None,resource_max=f['stats']['resource_max'] if f else None,
                withdrawn=bool(p and p.get('withdrawn')),character_slot=p.get('character_slot') if p else None))
        pending=deepcopy(d['pending'])
        if pending and pending['kind']=='event':pending.update(EVENTS[pending['event']])
        elif pending:pending.update(name='Тихий привал',text='Каждому нужен отдых. Выберите, что важнее сейчас.',choices=[
            dict(id='heal',name='Перевязать раны',hint='+30% HP живым участникам.'),dict(id='focus',name='Сосредоточиться',hint='+50% энергии и завершение перезарядок.')])
        invite=self.connection.execute('SELECT message_id,last_posted FROM guild_invites WHERE run_id=?',(row['id'],)).fetchone()
        last_posted=self.connection.execute('''SELECT MAX(i.last_posted) FROM guild_invites i JOIN guild_runs r ON r.id=i.run_id
            WHERE r.chat_id=? AND r.leader=?''',(row['chat_id'],row['leader'])).fetchone()[0] or 0
        return dict(id=row['id'],chat_id=row['chat_id'],leader=row['leader'],status=row['status'],revision=row['revision'],
            invite=dict(posted=bool(invite and invite['message_id']),available_at=last_posted+INVITE_COOLDOWN if last_posted else 0),
            expires=row['expires'],server_time=int(time.time()),contract=d['contract'],members=members,nodes=nodes,
            position=d['position'],pending=pending,battle=d['battle'],finds=d['finds'],votes=d['votes'],vote_deadline=d['vote_deadline'],
            history=d['history'][-20:],results=d.get('results',{}),reason=d.get('reason',''),
            supplies_used=d['supplies_used'],bag={r['item']:r['quantity'] for r in self.connection.execute('SELECT * FROM guild_bag WHERE actor_id=?',(actor,))})

    async def guild_get(self,ident,actor):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked();row=self._guild_row_locked(ident,actor)
                if row['status']=='active' and not row['data']['battle'] and self._guild_resolve_votes_locked(row):self._guild_save_locked(row);row=self._guild_row_locked(ident)
                return self._guild_public_locked(row,actor)

    async def guild_current(self,chat,actor):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked()
                found=self.connection.execute("SELECT id FROM guild_runs WHERE chat_id=? AND leader=? AND status IN ('lobby','active') ORDER BY created DESC LIMIT 1",(chat,actor)).fetchone()
                if not found:raise ValueError('У тебя нет своего сбора в этом чате. Выбери заказ в /заказы или напиши /охота F1.')
                return self._guild_public_locked(self._guild_row_locked(found['id'],actor),actor)

    async def guild_claim_invite(self,ident,actor):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked();row=self._guild_row_locked(ident,actor)
                self._require_feature_locked(row['chat_id'],'arena')
                if row['leader']!=actor:raise ValueError('Позвать отряд может только лидер.')
                if row['status']!='lobby':raise ValueError('Сбор уже закрыт.')
                if len(row['members'])>=3:raise ValueError('Отряд уже заполнен.')
                if row['data']['contract'].get('calibration'):raise ValueError('Квалификация — одиночное испытание.')
                now=int(time.time())
                recent=self.connection.execute('''SELECT MAX(i.last_posted) posted,MAX(i.claim_until) claimed FROM guild_invites i
                    JOIN guild_runs r ON r.id=i.run_id WHERE r.chat_id=? AND r.leader=?''',(row['chat_id'],actor)).fetchone()
                if (recent['claimed'] or 0)>now:raise ValueError('Приглашение уже отправляется.')
                wait=(recent['posted'] or 0)+INVITE_COOLDOWN-now
                if recent['posted'] and wait>0:raise ValueError(f'Повторно позвать можно через {max(1,(wait+59)//60)} мин.')
                self.connection.execute('INSERT OR IGNORE INTO guild_invites(run_id) VALUES(?)',(ident,))
                invite=dict(self.connection.execute('SELECT * FROM guild_invites WHERE run_id=?',(ident,)).fetchone())
                claim=secrets.token_hex(12)
                self.connection.execute('UPDATE guild_invites SET claim=?,claim_until=? WHERE run_id=?',(claim,now+60,ident))
                return dict(run=self._guild_public_locked(row,actor),claim=claim,previous=invite['message_id'])

    async def guild_finish_invite(self,ident,claim,message_id=None,revision=-1,signature=''):
        async with self._lock:
            with self.connection:
                if message_id is None:
                    self.connection.execute("UPDATE guild_invites SET claim='',claim_until=0 WHERE run_id=? AND claim=?",(ident,claim))
                else:
                    result=self.connection.execute("UPDATE guild_invites SET message_id=?,last_posted=?,claim='',claim_until=0,published_revision=?,signature=?,retry_at=0 WHERE run_id=? AND claim=?",
                        (message_id,int(time.time()),revision,signature,ident,claim))
                    if result.rowcount!=1:raise ValueError('Приглашение изменилось. Обнови сбор.')

    async def guild_publication(self,ident):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked();row=self._guild_row_locked(ident)
                invite=self.connection.execute('SELECT * FROM guild_invites WHERE run_id=?',(ident,)).fetchone()
                return self._guild_public_locked(row,row['leader']),dict(invite) if invite else None

    async def guild_publication_done(self,ident,message_id,revision,signature,retry_at=0):
        async with self._lock:
            with self.connection:
                self.connection.execute('UPDATE guild_invites SET published_revision=?,signature=?,retry_at=? WHERE run_id=? AND message_id=?',
                    (revision,signature,retry_at,ident,message_id))

    async def guild_publications_due(self):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked()
                return [r['run_id'] for r in self.connection.execute('''SELECT i.run_id FROM guild_invites i JOIN guild_runs r ON r.id=i.run_id
                    WHERE i.message_id IS NOT NULL AND i.published_revision<>r.revision AND i.retry_at<=? ORDER BY i.retry_at,r.created LIMIT 30''',(int(time.time()),))]

    async def guild_view(self,chat,actor):
        async with self._lock:
            with self.connection:
                self._guild_expire_locked();h=self._guild_hunter_locked(actor);profile=self._arena_profile_locked(chat,actor,True)
                money=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone()
                current=self.connection.execute("SELECT r.id FROM guild_runs r JOIN guild_members m ON m.run_id=r.id WHERE m.actor_id=? AND r.status IN ('lobby','active') ORDER BY r.created DESC LIMIT 1",(actor,)).fetchone()
                rows=self.connection.execute("SELECT * FROM guild_runs WHERE chat_id=? AND status='lobby' ORDER BY created DESC LIMIT 15",(chat,)).fetchall()
                hunters=self.connection.execute('''SELECT h.*,(SELECT display_name FROM users u WHERE u.user_id=h.actor_id ORDER BY last_seen DESC LIMIT 1) name
                    FROM guild_hunters h ORDER BY rank DESC,reputation DESC,wins DESC,actor_id LIMIT 30''').fetchall()
                history=self.connection.execute('''SELECT r.id,r.status,r.data_json FROM guild_runs r JOIN guild_members m ON m.run_id=r.id
                    WHERE m.actor_id=? AND r.status NOT IN ('lobby','active') ORDER BY r.created DESC LIMIT 10''',(actor,)).fetchall()
                return dict(actor_id=actor,chat_id=chat,hunter=dict(h,rank_name=RANKS[h['rank']],peak_rank_name=RANKS[h['peak_rank']],
                    calibration_rank=calibration_rank(profile['level']) if not(h['calibrated'] or h['wins'] or h['losses']) else None),
                    daily=dict(used=self._guild_used_locked(actor),limit=DAILY_LIMIT,day=raid_day(),timezone='Europe/Moscow'),
                    francs=money['balance'] if money else 0,ranks=RANKS,biomes=BIOMES,
                    contracts=[dict(c,locked=RANKS.index(c['rank'])>h['rank']+1) for c in CONTRACTS.values()],
                    monsters=[dict(id=k,sprite=art(k),**m) for k,m in MONSTERS.items()],shop=[dict(id=k,**s,locked=RANKS.index(s['rank'])>h['rank']) for k,s in SUPPLIES.items()],
                    bag={r['item']:r['quantity'] for r in self.connection.execute('SELECT * FROM guild_bag WHERE actor_id=?',(actor,))},
                    active=self._guild_public_locked(self._guild_row_locked(current['id']),actor) if current else None,
                    lobbies=[self._guild_public_locked(self._guild_row_locked(r['id']),actor) for r in rows],
                    leaderboard=[dict(r,rank_name=RANKS[r['rank']]) for r in hunters],
                    history=[dict(id=r['id'],status=r['status'],name=json.loads(r['data_json'])['contract']['name']) for r in history])

    async def guild_buy(self,chat,actor,item,nonce):
        if item not in SUPPLIES or not isinstance(nonce,str) or not 8<=len(nonce)<=80:raise ValueError('Некорректная покупка.')
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena');h=self._guild_hunter_locked(actor);s=SUPPLIES[item]
                old=self.connection.execute('SELECT * FROM guild_purchases WHERE actor_id=? AND nonce=?',(actor,nonce)).fetchone()
                if old:
                    if old['item']!=item:raise ValueError('Номер покупки уже использован.')
                    return
                if RANKS.index(s['rank'])>h['rank']:raise ValueError('Недостаточный ранг для покупки.')
                result=self.connection.execute('UPDATE franc_balances SET balance=balance-? WHERE chat_id=? AND user_id=? AND balance>=?',(s['price'],chat,actor,s['price']))
                if result.rowcount!=1:raise ValueError('Недостаточно франков выбранного чата.')
                self.connection.execute('INSERT INTO guild_bag VALUES(?,?,1) ON CONFLICT(actor_id,item) DO UPDATE SET quantity=quantity+1',(actor,item))
                self.connection.execute('INSERT INTO guild_purchases VALUES(?,?,?)',(actor,nonce,item))
