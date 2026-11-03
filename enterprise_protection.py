"""Optional enterprise protection: tax exemption, persistent threats and co-op raids.

All clocks use the database clock. State/economic writes share Database._lock.
Only enterprise production is exempt; quests, expeditions and wages are unchanged.
"""
import json
import random
import secrets
from uuid import uuid4

from npc_worker_rules import DAY,HOUR

REJOIN_FEE=250
EVENTS={
 'orcs':dict(name='Орочья трудовая инспекция',text='Три инспектора A-ранга проверяют наличие черепов под касками. Четвёртого сократили за слишком дорогую проверку. Лицензия на ограбление заверена вашей бывшей крышей.'),
 'escape':dict(name='Рабам — выходные, хозяевам — соболезнования',text='Подпольный профсоюз готовит групповой побег. В графе «выходное пособие» работники указали себя.'),
 'strike':dict(name='Забастовка концептуальной зарплаты',text='Работники узнали об отмене налога. Требуют свою долю экономии — хотя бы в виде позвоночника без производственной травмы.'),
}


def now():
    from database import utc_timestamp
    return utc_timestamp()


def orc_roster():
    # A-rank guild benchmarks: level 19, 410–490 HP, 32–33 attack, 18–23 armor.
    roles=(('Старший инспектор','warrior',480,33,23,['guild_cleaver','guild_smash','guild_claw']),
           ('Изыматель имущества','warrior',450,32,21,['guild_smash','guild_cleaver','guild_claw']),
           ('Оценщик черепов','hunter',410,33,18,['guild_claw','guild_cleaver','guild_smash']))
    return [dict(id='protection:orc:'+str(i),revision=1,kind='mob',npc_tier=3,definition=dict(
        name=name+' · орк A',description='Орочья трудовая инспекция · ранг A',class_id=cls,
        level=19,archclass_id='',archclass_stage=10,defense_mode='dodge',skills=kit,passives=[],
        stats=dict(max_hp=hp,resource_max=100,physical_attack=attack,magic_attack=attack,
                   physical_defense=armor,magic_defense=armor,speed=27,evasion=8),
        ai='sequence',avatar_key='',sprite_key='',flip=False,scale=.95,preset_id=''))
        for i,(name,cls,hp,attack,armor,kit) in enumerate(roles)]


class EnterpriseProtectionMixin:
    def _init_protection(self):
        self.connection.executescript('''
          CREATE TABLE IF NOT EXISTS enterprise_protection(
            chat INTEGER NOT NULL,owner INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
            changed INTEGER NOT NULL,next_event INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat,owner));
          CREATE TABLE IF NOT EXISTS enterprise_threats(
            id TEXT PRIMARY KEY,chat INTEGER NOT NULL,owner INTEGER NOT NULL,kind TEXT NOT NULL,
            status TEXT NOT NULL,created INTEGER NOT NULL,deadline INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,data TEXT NOT NULL,notified INTEGER NOT NULL DEFAULT 0);
          CREATE INDEX IF NOT EXISTS enterprise_threat_owner ON enterprise_threats(chat,owner,status);
          CREATE INDEX IF NOT EXISTS enterprise_threat_account ON enterprise_threats(owner,status,created);
          CREATE TABLE IF NOT EXISTS enterprise_outages(
            event TEXT PRIMARY KEY,chat INTEGER NOT NULL,owner INTEGER NOT NULL,
            starts INTEGER NOT NULL,ends INTEGER NOT NULL);
          CREATE INDEX IF NOT EXISTS enterprise_outage_owner ON enterprise_outages(chat,owner,starts,ends);
          CREATE TABLE IF NOT EXISTS enterprise_protection_receipts(
            owner INTEGER NOT NULL,nonce TEXT NOT NULL,request TEXT NOT NULL,result TEXT NOT NULL,
            PRIMARY KEY(owner,nonce));
        ''')
        self._ensure_column('business_tax_daily','taxable_income','INTEGER')

    def _protection_enabled_locked(self,chat,owner):
        r=self.connection.execute('SELECT enabled FROM enterprise_protection WHERE chat=? AND owner=?',(chat,owner)).fetchone()
        return not r or bool(r['enabled'])

    def _protection_outage_locked(self,chat,owner,begin,end):
        return bool(self.connection.execute('SELECT 1 FROM enterprise_outages WHERE chat=? AND owner=? AND starts<? AND ends>? LIMIT 1',
                                           (chat,owner,end,begin)).fetchone())

    def _protection_count_locked(self,chat,owner):
        return self.connection.execute('SELECT COUNT(*) FROM business_workers WHERE chat_id=? AND owner_id=?',(chat,owner)).fetchone()[0]+self.connection.execute("SELECT COUNT(*) FROM fictional_workers WHERE chat=? AND owner=? AND status='work'",(chat,owner)).fetchone()[0]

    def _protection_event_locked(self,chat,owner,kind):
        if kind not in EVENTS:raise ValueError('Неизвестное событие.')
        ident=uuid4().hex
        self.connection.execute("INSERT INTO enterprise_threats VALUES(?,?,?,?,'open',?,?,0,?,0)",
            (ident,chat,owner,kind,now(),now()+DAY,json.dumps(dict(history=[],raid=None))))
        return ident

    def _protection_resolve_locked(self,event,outcome,hours=0,stamp=None):
        current=self.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(event['id'],)).fetchone()
        if not current or current['status']!='open':return
        stamp=now() if stamp is None else stamp
        self._enterprise_settle_owner_locked(event['chat'],event['owner'],now())
        if hours:
            self.connection.execute('INSERT OR IGNORE INTO enterprise_outages VALUES(?,?,?,?,?)',
                (event['id'],event['chat'],event['owner'],stamp,stamp+hours*HOUR))
        self.connection.execute('UPDATE enterprise_threats SET status=?,revision=revision+1 WHERE id=?',(outcome,event['id']))

    def _protection_escape_locked(self,event):
        from slave_recovery import RECOVERY_SYMBOLS
        rng=random.SystemRandom();chat,owner=event['chat'],event['owner'];candidates=[]
        for r in self._npc_rows_locked(chat,owner):
            if r['status'] in ('work','rest'):candidates.append(('npc',r['id'],r['created'],r['data']['name']))
        for r in self.connection.execute('''SELECT o.slave_id,o.acquired_at,u.display_name FROM ownership o
            LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
            WHERE o.chat_id=? AND o.owner_id=?''',(chat,owner)):
            if not self._enterprise_away_locked(chat,owner,r['slave_id'],now(),now()+1) and not self._trader_listed_locked(chat,r['slave_id']):
                candidates.append(('human',str(r['slave_id']),r['acquired_at'],r['display_name'] or str(r['slave_id'])))
        rng.shuffle(candidates)
        for typ,worker,epoch,name in candidates[:3]:
            if self.connection.execute("SELECT 1 FROM workforce_events WHERE worker=? AND worker_type=? AND status IN ('announcing','open','playing','search')",(worker,typ)).fetchone():continue
            payload=dict(secret=rng.sample(range(len(RECOVERY_SYMBOLS)),3),history=[],bounty=0,protection_event=event['id'])
            self.connection.execute("INSERT INTO workforce_events VALUES(?,?,?,?,?,?,?,'escaped','announcing',?,NULL,NULL,NULL,0,?,0)",
                (uuid4().hex,chat,owner,worker,typ,epoch,name,now(),json.dumps(payload)))
        self._protection_resolve_locked(event,'escaped')

    def _protection_tick_locked(self,chat,owner):
        stamp=now()
        for e in self.connection.execute("SELECT * FROM enterprise_threats WHERE chat=? AND owner=? AND status='open'",(chat,owner)).fetchall():
            if not self._feature_enabled_locked(chat,'slavery') or e['kind']=='orcs' and not self._feature_enabled_locked(chat,'arena'):
                self._protection_resolve_locked(e,'cancelled');continue
            if e['deadline']>stamp:continue
            p=json.loads(e['data']);raid=self.connection.execute('SELECT status FROM arena_raids WHERE token=?',(p.get('raid'),)).fetchone()
            # The advertised deadline is the time to START defending. A battle
            # already started may finish under normal raid turn timeouts.
            if raid and raid['status']=='active':continue
            if raid and raid['status']=='lobby':
                self.connection.execute("UPDATE arena_raids SET status='cancelled',finished_at=?,revision=revision+1 WHERE token=?",(stamp,p['raid']))
            if e['kind']=='escape':self._protection_escape_locked(e)
            else:self._protection_resolve_locked(e,'lost',12)
        policy=self.connection.execute('SELECT * FROM enterprise_protection WHERE chat=? AND owner=?',(chat,owner)).fetchone()
        if not policy or policy['enabled'] or policy['next_event']>stamp:return
        if not self._feature_enabled_locked(chat,'slavery'):return
        if not self.connection.execute('SELECT 1 FROM businesses WHERE chat_id=? AND owner_id=?',(chat,owner)).fetchone():return
        if self.connection.execute("SELECT 1 FROM enterprise_threats WHERE owner=? AND (status='open' OR created>?)",(owner,stamp-DAY)).fetchone():return
        if self.connection.execute("SELECT 1 FROM workforce_events WHERE owner=? AND status IN ('announcing','open','playing','search')",(owner,)).fetchone():return
        kind=random.SystemRandom().choice(tuple(EVENTS))
        if kind=='orcs' and not self._feature_enabled_locked(chat,'arena'):kind='strike'
        self._protection_event_locked(chat,owner,kind)
        self.connection.execute('UPDATE enterprise_protection SET next_event=? WHERE chat=? AND owner=?',(stamp+2*DAY,chat,owner))

    def _protection_view_locked(self,chat,actor):
        self._protection_tick_locked(chat,actor)
        policy=self.connection.execute('SELECT * FROM enterprise_protection WHERE chat=? AND owner=?',(chat,actor)).fetchone()
        events=[]
        for e in self.connection.execute("SELECT * FROM enterprise_threats WHERE chat=? AND (owner=? OR status='open' AND kind='orcs') ORDER BY created DESC LIMIT 10",(chat,actor)):
            p=json.loads(e['data']);r=dict(e);r.pop('data');r.update(EVENTS[e['kind']],mine=e['owner']==actor,raid=p.get('raid'))
            if p.get('raid'):
                raid=self.connection.execute('SELECT status,message_id FROM arena_raids WHERE token=?',(p['raid'],)).fetchone()
                r.update(raid_status=raid['status'] if raid else None,announced=bool(raid and raid['message_id']))
            events.append(r)
        outage=self.connection.execute('SELECT MAX(ends) FROM enterprise_outages WHERE chat=? AND owner=? AND ends>?',(chat,actor,now())).fetchone()[0]
        return dict(enabled=not policy or bool(policy['enabled']),revision=policy['revision'] if policy else 0,
            next_event=policy['next_event'] if policy and not policy['enabled'] else None,rejoin_fee=REJOIN_FEE,
            events=events,outage_until=outage,workers=self._protection_count_locked(chat,actor))

    async def protection_action(self,chat,actor,b):
        nonce=b.get('nonce')
        if not isinstance(nonce,str) or len(nonce)!=32 or any(c not in '0123456789abcdef' for c in nonce):raise ValueError('Обнови страницу.')
        if b.get('confirm') is not True:raise ValueError('Подтверди действие.')
        request=json.dumps(dict(chat=chat,body={k:v for k,v in b.items() if k!='nonce'}),sort_keys=True)
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'slavery')
                old=self.connection.execute('SELECT * FROM enterprise_protection_receipts WHERE owner=? AND nonce=?',(actor,nonce)).fetchone()
                if old:
                    if old['request']!=request:raise ValueError('Повторный запрос отличается.')
                    return json.loads(old['result'])
                self._protection_tick_locked(chat,actor)
                action=b.get('action');result=dict(notice='Состояние крыши обновлено.')
                if action=='protection_toggle':
                    enabled=b.get('enabled')
                    if type(enabled) is not bool:raise ValueError('Некорректный режим.')
                    if not self.connection.execute('SELECT 1 FROM businesses WHERE chat_id=? AND owner_id=?',(chat,actor)).fetchone():raise ValueError('Сначала открой предприятие.')
                    p=self.connection.execute('SELECT * FROM enterprise_protection WHERE chat=? AND owner=?',(chat,actor)).fetchone()
                    if b.get('revision')!=(p['revision'] if p else 0):raise ValueError('Режим изменился. Обнови страницу.')
                    current=not p or bool(p['enabled'])
                    if enabled==current:raise ValueError('Этот режим уже включён.')
                    self._enterprise_settle_owner_locked(chat,actor,now())
                    if enabled:self._npc_pay_locked(chat,actor,REJOIN_FEE)
                    elif p and p['changed']+DAY>now():raise ValueError('Повторный отказ от крыши доступен через сутки после переключения.')
                    due=p['next_event'] if p else now()+DAY
                    self.connection.execute('''INSERT INTO enterprise_protection VALUES(?,?,?,?,?,1)
                        ON CONFLICT(chat,owner) DO UPDATE SET enabled=excluded.enabled,changed=excluded.changed,revision=revision+1''',
                        (chat,actor,int(enabled),now(),due))
                    result['notice']='Заявление «Я всё осознал» принято. Уже начавшиеся события и простой сохраняются.' if enabled else 'Крыша снята. Оркам переданы координаты для установления дипломатических отношений. Срок следующей угрозы указан в управлении; уже объявленные сроки не меняются.'
                else:
                    e=self.connection.execute('SELECT * FROM enterprise_threats WHERE id=? AND chat=?',(b.get('id'),chat)).fetchone()
                    if not e or e['owner']!=actor:raise ValueError('Это событие другого владельца.')
                    self._protection_tick_locked(chat,actor)
                    e=self.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(e['id'],)).fetchone()
                    if e['status']!='open' or e['deadline']<=now():raise ValueError('Событие уже завершено.')
                    if e['revision']!=b.get('revision'):raise ValueError('Событие изменилось. Обнови страницу.')
                    if action=='protection_conditions' and e['kind']=='escape':
                        cost=100+25*self._protection_count_locked(chat,actor)
                        self._npc_pay_locked(chat,actor,cost);self._protection_resolve_locked(e,'prevented',6)
                        self._npc_estate_locked(chat,actor)
                        self.connection.execute('UPDATE npc_estates SET care=? WHERE chat=? AND owner=?',(now(),chat,actor))
                        for r in self._npc_rows_locked(chat,actor):
                            r['data']['loyalty']=min(100,r['data']['loyalty']+10);self._npc_save_locked(r)
                        result['notice']='Заговор предотвращён: условия улучшены, оплачено '+str(cost)+' ₣; 6 часов общего отдыха.'
                    elif action=='protection_strike' and e['kind']=='strike':
                        paid=b.get('paid')
                        if type(paid) is not bool:raise ValueError('Выбери условия соглашения.')
                        if paid:self._npc_pay_locked(chat,actor,100+20*self._protection_count_locked(chat,actor))
                        self._protection_resolve_locked(e,'agreement',6 if paid else 12)
                        result['notice']='Соглашение подписано. Предприятия отдыхают '+('6' if paid else '12')+' часов; содержание продолжается.'
                    elif action=='protection_raid' and e['kind']=='orcs':
                        result.update(raid=self._protection_lobby_locked(e),notice='Сбор защиты открыт. Нужно 2–3 игрока против трёх орков A-ранга. Приглашение будет отправлено в чат.')
                    else:raise ValueError('Недоступное действие.')
                self.connection.execute('INSERT INTO enterprise_protection_receipts VALUES(?,?,?,?)',(actor,nonce,request,json.dumps(result,ensure_ascii=False)))
                return result

    def _protection_lobby_locked(self,event):
        from arena_raid import RAID_LOBBY_SECONDS
        self._require_feature_locked(event['chat'],'arena')
        p=json.loads(event['data'])
        if p.get('raid'):
            r=self.connection.execute('SELECT status FROM arena_raids WHERE token=?',(p['raid'],)).fetchone()
            if r and r['status'] in ('lobby','active'):return p['raid']
        token=secrets.token_urlsafe(12)
        cfg=dict(protection=event['id'],roster=[dict(id=t['id'],name=t['definition']['name']) for t in orc_roster()])
        self.connection.execute('''INSERT INTO arena_raids(token,chat_id,creator_id,created_at,deadline,boss_id,silent,encounter_json)
            VALUES(?,?,?,?,?,'encounter',1,?)''',(token,event['chat'],event['owner'],now(),min(event['deadline'],now()+RAID_LOBBY_SECONDS),json.dumps(cfg,ensure_ascii=False)))
        p['raid']=token
        self.connection.execute('UPDATE enterprise_threats SET data=?,revision=revision+1,notified=0 WHERE id=?',(json.dumps(p),event['id']))
        return token

    def _protection_combat_locked(self,row,members,sources,classes,skills):
        from arena_encounters import create_encounter,set_intents
        cfg=json.loads(row['encounter_json']);event=self.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(cfg['protection'],)).fetchone()
        if not event or event['status']!='open' or event['deadline']<=now():raise ValueError('Угроза уже завершена.')
        if json.loads(event['data']).get('raid')!=row['token']:raise ValueError('Это устаревший сбор защиты.')
        if not 2<=len(members)<=3:raise ValueError('Против трёх орков A-ранга нужны 2–3 игрока.')
        data=create_encounter(members,sources,classes,skills,orc_roster(),row['creator_id'])
        data.update(rp_mode=False,protection_event=event['id'])
        for f in data['enemies'].values():f.update(guild_monster='orc',guild_sprite='/static/assets/guild/orc-v1.png',rp_flip=True)
        set_intents(data,skills)
        return data

    def _protection_battle_finished_locked(self,row,battle):
        e=self.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(battle['protection_event'],)).fetchone()
        if e and e['status']=='open' and json.loads(e['data']).get('raid')==row['token']:
            self._protection_resolve_locked(e,'defended' if battle['won'] else 'lost',0 if battle['won'] else 12)
        battle.update(rewards={},result='Орочья инспекция разгромлена. Предприятия спасены; отдельных наград нет.' if battle['won'] else 'Орки разграбили предприятия: простой 12 часов. Работники и постоянная прогрессия сохранены.')

    async def protection_notifications(self):
        async with self._lock:
            with self.connection:
                for p in self.connection.execute('SELECT chat,owner FROM enterprise_protection').fetchall():self._protection_tick_locked(p['chat'],p['owner'])
                result=[]
                for e in self.connection.execute("SELECT * FROM enterprise_threats WHERE status='open' AND notified<=? ORDER BY created LIMIT 10",(now(),)):
                    # Lease bounds retries without polling Telegram every five seconds.
                    self.connection.execute('UPDATE enterprise_threats SET notified=? WHERE id=?',(now()+300,e['id']))
                    result.append(dict(e,raid=json.loads(e['data']).get('raid')))
                return result

    async def protection_notified(self,ident):
        async with self._lock:
            with self.connection:self.connection.execute('UPDATE enterprise_threats SET notified=? WHERE id=?',(2**62,ident))
