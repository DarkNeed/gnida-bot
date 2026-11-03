"""Fictional adult workers. All writes run inside Database's lock/transaction.

NPC UUIDs never enter Telegram users, ownership, arena or the human market.
Hourly integer accounting is independent of how often the UI is refreshed.
"""
import hashlib
import json
import random
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from npc_worker_rules import DAY, HOUR, PROFESSIONS, create, public, efficiency, power, appearance
from slave_expeditions import EXPEDITIONS
from workforce_events import WorkforceMixin


def now():
    from database import utc_timestamp
    return utc_timestamp()


class NpcWorkersMixin(WorkforceMixin):
    def _init_npc_workers(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS npc_estates(
                chat INTEGER NOT NULL,owner INTEGER NOT NULL,reserve INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,care INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat,owner));
            CREATE TABLE IF NOT EXISTS npc_slots(owner INTEGER PRIMARY KEY,level INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS npc_upkeep_daily(
                chat INTEGER NOT NULL,owner INTEGER NOT NULL,day TEXT NOT NULL,paid INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat,owner,day));
            CREATE TABLE IF NOT EXISTS fictional_workers(
                id TEXT PRIMARY KEY,chat INTEGER NOT NULL,owner INTEGER,
                status TEXT NOT NULL,site INTEGER,price INTEGER NOT NULL,data TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,tick INTEGER NOT NULL,created INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS npc_workers_owner ON fictional_workers(chat,owner);
            CREATE TABLE IF NOT EXISTS npc_stock_days(chat INTEGER NOT NULL,day INTEGER NOT NULL,PRIMARY KEY(chat,day));
            CREATE TABLE IF NOT EXISTS npc_receipts(
                owner INTEGER NOT NULL,nonce TEXT NOT NULL,action TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(owner,nonce));
            CREATE TABLE IF NOT EXISTS npc_trips(
                id TEXT PRIMARY KEY,chat INTEGER NOT NULL,owner INTEGER NOT NULL,mission TEXT NOT NULL,
                started INTEGER NOT NULL,ends INTEGER NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL);
        ''')
        self._init_workforce()
        # One-time visual migration only. No identity, rarity or economics reroll.
        for raw in self.connection.execute('SELECT id,data FROM fictional_workers').fetchall():
            d=json.loads(raw['data']);gender,key=appearance(d)
            if d.get('gender')!=gender or d.get('appearance')!=key:
                d.update(gender=gender,appearance=key)
                self.connection.execute('UPDATE fictional_workers SET data=?,revision=revision+1 WHERE id=?',
                    (json.dumps(d,ensure_ascii=False),raw['id']))

    def _npc_estate_locked(self, chat, owner):
        self.connection.execute('INSERT OR IGNORE INTO npc_estates(chat,owner,care) VALUES(?,?,?)',(chat,owner,now()))
        row=dict(self.connection.execute('SELECT * FROM npc_estates WHERE chat=? AND owner=?',(chat,owner)).fetchone())
        # Old demo reserves are refunded once, atomically; the reserve is retired.
        if row['reserve']:
            self.connection.execute('UPDATE npc_estates SET reserve=0 WHERE chat=? AND owner=?',(chat,owner))
            self._credit_labor_income_locked(chat,owner,row['reserve'],now());row['reserve']=0
        return row

    def _npc_rows_locked(self, chat, owner):
        return [self._npc_decode(r) for r in self.connection.execute('SELECT * FROM fictional_workers WHERE chat=? AND owner=? ORDER BY created,id',(chat,owner))]

    @staticmethod
    def _npc_decode(row):
        r=dict(row);r['data']=json.loads(r['data']);return r

    def _npc_save_locked(self, row):
        self.connection.execute('UPDATE fictional_workers SET owner=?,status=?,site=?,data=?,tick=?,revision=revision+1 WHERE id=?',
            (row['owner'],row['status'],row['site'],json.dumps(row['data'],ensure_ascii=False),row['tick'],row['id']))

    def _npc_count_locked(self, site):
        return self.connection.execute('SELECT COUNT(*) FROM fictional_workers WHERE site=? AND owner=? AND chat=?',
            (site['id'],site['owner_id'],site['chat_id'])).fetchone()[0]

    def _npc_leader_locked(self, site, begin, end, exclude=()):
        return any(r['id'] not in exclude and r['site']==site['id'] and r['data'].get('role')=='leader'
            and r['status']=='work' and r['data']['health']>=30 and r['data'].get('work_since',r['created'])<end
            for r in (self._npc_decode(row) for row in self.connection.execute('SELECT * FROM fictional_workers WHERE chat=? AND owner=? AND site=?',(site['chat_id'],site['owner_id'],site['id']))))

    def _npc_pause_locked(self, chat, enabled):
        stamp=now()
        if not enabled:
            for row in self.connection.execute('SELECT DISTINCT owner FROM fictional_workers WHERE chat=? AND owner IS NOT NULL',(chat,)).fetchall():
                self._npc_tick_locked(chat,row['owner'],stamp)
        for r in [self._npc_decode(row) for row in self.connection.execute('SELECT * FROM fictional_workers WHERE chat=? AND owner IS NOT NULL',(chat,))]:
            training=r['data'].get('training')
            if training:
                if enabled and 'remaining' in training:training['ends']=stamp+training.pop('remaining')
                elif not enabled:training['remaining']=max(0,training['ends']-stamp)
            r['tick']=stamp;self._npc_save_locked(r)

    def _npc_pay_locked(self, chat, actor, amount):
        if type(amount) is not int or amount<0:raise ValueError('Некорректная сумма.')
        if amount and not self.connection.execute('UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?',
            (amount,now(),chat,actor,amount)).rowcount:raise ValueError('Недостаточно франков в кошельке этого чата.')

    def _npc_stock_locked(self, chat):
        day=(now()+3*HOUR)//DAY
        if self.connection.execute('INSERT OR IGNORE INTO npc_stock_days VALUES(?,?)',(chat,day)).rowcount:
            self.connection.execute("DELETE FROM fictional_workers WHERE chat=? AND owner IS NULL AND status='stock'",(chat,))
            rng=random.SystemRandom()
            for profession in rng.sample(list(PROFESSIONS),3):
                self.connection.execute('INSERT INTO fictional_workers VALUES(?,?,NULL,\'stock\',NULL,?,?,0,?,?)',
                    (uuid4().hex,chat,PROFESSIONS[profession]['price'],json.dumps(create(profession),ensure_ascii=False),now(),now()))

    def _npc_tick_locked(self, chat, owner, stamp):
        """Settle every complete hour once. No wallet overdrafts; no offline cap."""
        result=dict(hours=0,owner_income=0,gross_income=0,tax=0,upkeep=0)
        estate=self.connection.execute('SELECT * FROM npc_estates WHERE chat=? AND owner=?',(chat,owner)).fetchone()
        if not estate:return result
        self._npc_estate_locked(chat,owner)
        if not self._feature_enabled_locked(chat,'slavery'):
            self.connection.execute('UPDATE fictional_workers SET tick=? WHERE chat=? AND owner=?',(stamp,chat,owner));return result
        self._npc_trips_finish_locked(chat,owner,stamp)
        sites={s['id']:s for s in self.connection.execute('SELECT * FROM businesses WHERE chat_id=? AND owner_id=?',(chat,owner))}
        from enterprises import config
        leaders={s['id']:[w for w in self._enterprise_workers_locked(s) if w['role']==config(s)['leader_role']] for s in sites.values()}
        # Settle income and wallet upkeep chronologically. Refreshing the page
        # must not fund more hours than leaving the same period offline.
        rows=self._npc_rows_locked(chat,owner)
        result['hours']=max((max(0,(stamp-r['tick'])//HOUR) for r in rows),default=0)
        end=min((r['tick']+HOUR for r in rows),default=stamp+1)
        while end<=stamp:
            credits={}
            for site_id,s in list(sites.items()):
                earned=self._enterprise_settle_site_locked(s,end)
                for key in ('owner_income','gross_income','tax'):result[key]+=earned[key]
                sites[site_id]=self.connection.execute('SELECT * FROM businesses WHERE id=?',(site_id,)).fetchone()
            for r in rows:
                if end<r['tick']+HOUR:continue
                d=r['data'];r['tick']+=HOUR
                if r['status'] in ('missing','expedition'):continue
                d['cost_remainder']+=PROFESSIONS[d['profession']]['upkeep']
                cost,d['cost_remainder']=divmod(d['cost_remainder'],24)
                if cost:
                    fed=bool(self.connection.execute('UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?',(cost,end,chat,owner,cost)).rowcount)
                else:
                    balance=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,owner)).fetchone()
                    fed=bool(balance and balance['balance']>0)
                if fed:
                    d['unpaid']=0;result['upkeep']+=cost
                    if cost:
                        day=datetime.fromtimestamp(end-1,timezone(timedelta(hours=3))).date().isoformat()
                        self.connection.execute('INSERT INTO npc_upkeep_daily VALUES(?,?,?,?) ON CONFLICT(chat,owner,day) DO UPDATE SET paid=paid+excluded.paid',(chat,owner,day,cost))
                else:d['unpaid']+=1
                if end//(6*HOUR)!=(end-HOUR)//(6*HOUR):
                    d['loyalty']=min(100,max(0,d['loyalty']+(1 if fed else -3)))
                    d['health']=min(100,max(20,d['health']+(1 if fed else -2)))
                if r['status']=='training' and end>=d['training']['ends']:
                    target=d['training']['kind']
                    d['profession_level' if target=='work' else 'level']+=1
                    d['history']=(d['history']+[dict(at=end,text='Обучение завершено')])[-30:]
                    d['training']=None;r['status']='rest'
                s=sites.get(r['site'])
                on_break=self._protection_outage_locked(chat,owner,end-HOUR,end)
                working=r['status']=='work' and s is not None and fed and d['health']>=30 and end>=d.get('work_since',r['created'])+HOUR and not on_break
                if working:
                    rate=config(s)['owner_per_producer']
                    if any(not self._enterprise_away_locked(chat,owner,w['worker_id'],end-HOUR,end) for w in leaders[s['id']]) or self._npc_leader_locked(s,end-HOUR,end):rate*=1.2
                    if d.get('role')=='leader':rate=0
                    # 1/10,000 franc precision, credited as whole francs per site/day.
                    d['remainder']+=round(rate*efficiency(d,s['business_type'])*10000)
                    gross,d['remainder']=divmod(d['remainder'],10000)
                    day=datetime.fromtimestamp(end-1,timezone(timedelta(hours=3))).date().isoformat()
                    key=(s['id'],day);credits[key]=credits.get(key,0)+gross
                    d['experience']+=1
                    if d['experience']>=240 and d['profession_level']<10:
                        d['experience']-=240;d['profession_level']+=1
                    if end//(3*HOUR)!=(end-HOUR)//(3*HOUR):
                        d['fatigue']=min(100,d['fatigue']+(1 if d['trait']=='veteran' and PROFESSIONS[d['profession']]['work']==s['business_type'] else 2))
                elif r['status']=='rest' or r['status']=='work' and on_break:d['fatigue']=max(0,d['fatigue']-3)
            for (site,day),gross in credits.items():
                if gross:
                    net,tax=self._enterprise_credit_site_locked(sites[site],day,gross)
                    result['owner_income']+=net;result['gross_income']+=gross;result['tax']+=tax
            end=min((r['tick']+HOUR for r in rows),default=stamp+1)
        for r in rows:
            if r['tick']!=self.connection.execute('SELECT tick FROM fictional_workers WHERE id=?',(r['id'],)).fetchone()[0]:self._npc_save_locked(r)
        return result

    def _npc_trips_finish_locked(self, chat, owner, stamp):
        for trip in self.connection.execute("SELECT * FROM npc_trips WHERE chat=? AND owner=? AND status='active' AND ends<=?",(chat,owner,stamp)).fetchall():
            payload=json.loads(trip['data']);mission=EXPEDITIONS[trip['mission']]
            returned_at=trip['ends']
            # Outcomes were drawn once, at dispatch; refresh/restart cannot reroll.
            survivors=[];member_results=[]
            human_rows=self.connection.execute('SELECT * FROM slave_expedition_members WHERE expedition_id=?',(trip['id'],)).fetchall()
            lost_humans={m['user_id'] for m in payload.get('humans',[]) if m['lost']}
            for member in human_rows:
                self.connection.execute('UPDATE slave_expedition_members SET ended_at=COALESCE(ended_at,?) WHERE expedition_id=? AND user_id=?',
                    (stamp if member['user_id'] in lost_humans else returned_at,trip['id'],member['user_id']))
            # Real participants keep their jobs. Settle absence before releasing
            # a lost participant; ownership epochs protect subsequent transfers.
            if human_rows:
                for site in self.connection.execute('SELECT * FROM businesses WHERE chat_id=? AND owner_id=?',(chat,owner)).fetchall():
                    self._enterprise_settle_site_locked(site,stamp)
            for member in human_rows:
                valid=member['active'] and self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=? AND acquired_at=?',
                    (chat,owner,member['user_id'],member['acquired_at'])).fetchone()
                self.connection.execute('UPDATE slave_expedition_members SET active=0 WHERE expedition_id=? AND user_id=?',(trip['id'],member['user_id']))
                if not valid:
                    member_results.append(dict(user_id=member['user_id'],outcome='removed'));continue
                member_results.append(dict(user_id=member['user_id'],outcome='freed' if member['user_id'] in lost_humans else 'returned'))
                if member['user_id'] in lost_humans:
                    self.connection.execute('DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(chat,owner,member['user_id']))
                    self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?',(chat,owner,member['user_id']))
                else:
                    survivors.append(member['user_id'])
                    self._credit_labor_income_locked(chat,member['user_id'],max(5,mission['francs']//5),stamp)
            for npc_id,lost in payload['outcomes']:
                row=self.connection.execute('SELECT * FROM fictional_workers WHERE id=? AND chat=? AND owner=?',(npc_id,chat,owner)).fetchone()
                if not row:
                    member_results.append(dict(user_id=npc_id,outcome='removed'));continue
                member_results.append(dict(user_id=npc_id,outcome='freed' if lost else 'returned'))
                r=self._npc_decode(row);d=r['data'];r['tick']=returned_at;r['status']='runaway' if lost else ('work' if r['site'] and self._enterprise_locked(chat,owner,r['site']) else 'rest')
                d['work_since']=returned_at
                d['ready_at']=trip['started']+6*HOUR;d['fatigue']=min(100,d['fatigue']+25);d['health']=max(30,d['health']-10)
                d['history']=(d['history']+[dict(at=returned_at,text='Покинул отряд' if lost else 'Вернулся из экспедиции')])[-30:]
                if lost:r['owner']=None;r['site']=None
                else:d['level']=min(20,d['level']+1);survivors.append(npc_id)
                self._npc_save_locked(r)
            if survivors:
                day=datetime.fromtimestamp(returned_at,timezone(timedelta(hours=3))).date().isoformat()
                francs,tax=self._credit_business_income_locked(chat,owner,day,mission['francs']*len(survivors))
                wallet=self._forge_wallet_locked(0,owner)
                wallet['pages'][mission['page_rarity']]=wallet['pages'].get(mission['page_rarity'],0)+mission['pages']
                self._forge_save_wallet_locked(0,owner,wallet)
                payload.update(francs=francs,tax=tax,pages=mission['pages'],page_rarity=mission['page_rarity'])
                # Recruits are ordinary owned workers; there is no NPC-only quota.
                if payload.get('recruit'):
                    profession=payload['recruit'];d=create(profession)
                    self.connection.execute("INSERT INTO fictional_workers VALUES(?,?,?,'rest',NULL,?,?,0,?,?)",
                        (uuid4().hex,chat,owner,PROFESSIONS[profession]['price'],json.dumps(d),returned_at,returned_at))
            payload['survivors']=survivors
            payload['results']=member_results
            self.connection.execute("UPDATE npc_trips SET status='finished',data=? WHERE id=?",(json.dumps(payload),trip['id']))

    def _npc_view_locked(self, chat, owner):
        self._npc_stock_locked(chat);estate=self._npc_estate_locked(chat,owner)
        workforce=self._workforce_view_locked(chat,owner)
        estate=self._npc_estate_locked(chat,owner)
        owned=self._npc_rows_locked(chat,owner)
        market=[public(self._npc_decode(r)) for r in self.connection.execute("SELECT * FROM fictional_workers WHERE chat=? AND owner IS NULL AND status IN ('stock','runaway') ORDER BY created DESC LIMIT 12",(chat,))]
        trips=[]
        for row in self.connection.execute('SELECT * FROM npc_trips WHERE chat=? AND owner=? ORDER BY started DESC LIMIT 5',(chat,owner)):
            d=dict(row);p=json.loads(d.pop('data'))
            ids=[i[0] for i in p.get('outcomes',[])]+[m['user_id'] for m in p.get('humans',[])]
            p['members']=[dict(user_id=i,name=p['names'][n]) for n,i in enumerate(ids)]
            p.pop('outcomes',None);p.pop('recruit',None);p.pop('humans',None);d.update(p);trips.append(d)
        day=datetime.fromtimestamp(now(),timezone(timedelta(hours=3))).date().isoformat()
        paid=self.connection.execute('SELECT paid FROM npc_upkeep_daily WHERE chat=? AND owner=? AND day=?',(chat,owner,day)).fetchone()
        return dict(workers=[public(r) for r in owned],market=market,care=estate['care'],upkeep_today=paid[0] if paid else 0,
            daily_upkeep=sum(PROFESSIONS[r['data']['profession']]['upkeep'] for r in owned if r['status'] not in ('missing','expedition')),
            trips=trips,workforce=workforce,missions=[dict(id=k,**v) for k,v in EXPEDITIONS.items()])

    async def npc_action(self, chat, actor, body):
        action=body.get('action');nonce=body.get('nonce')
        if not isinstance(nonce,str) or not 16<=len(nonce)<=80:raise ValueError('Обнови страницу: отсутствует ключ действия.')
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            with self.connection:
                old=self.connection.execute('SELECT * FROM npc_receipts WHERE owner=? AND nonce=?',(actor,nonce)).fetchone()
                signature=hashlib.sha256(json.dumps([chat,body],sort_keys=True).encode()).hexdigest()
                if old:
                    if old['action']!=signature:raise ValueError('Ключ уже использован другим действием.')
                    return json.loads(old['result'])
                self._npc_estate_locked(chat,actor)
                self._expedition_finish_due_locked()
                self._enterprise_settle_owner_locked(chat,actor,now())
                self._workforce_tick_locked(chat,actor)
                if action.startswith('workforce_'):result=self._workforce_action_locked(chat,actor,body)
                else:result=self._npc_action_locked(chat,actor,body)
                self.connection.execute('INSERT INTO npc_receipts VALUES(?,?,?,?)',(actor,nonce,signature,json.dumps(result)))
                return result

    def _npc_action_locked(self, chat, actor, b):
        action=b['action'];stamp=now();estate=self._npc_estate_locked(chat,actor)
        if action in ('npc_fund','npc_housing'):
            raise ValueError('Резерв и отдельный лимит NPC отменены. Содержание списывается из кошелька.')
        if action=='npc_care':
            self.connection.execute('UPDATE npc_estates SET care=? WHERE chat=? AND owner=?',(stamp,chat,actor))
            return dict(notice='Управляющий проверил условия. Проверка действует 48 часов; еду и отдых она не заменяет.')
        if action in ('npc_trip','npc_trip_quote'):return self._npc_trip_start_locked(chat,actor,b)
        if not isinstance(b.get('id'),str) or len(b['id'])!=32:raise ValueError('Некорректный NPC.')
        row=self.connection.execute('SELECT * FROM fictional_workers WHERE id=? AND chat=?',(b.get('id'),chat)).fetchone()
        if not row:raise ValueError('NPC больше недоступен.')
        r=self._npc_decode(row);d=r['data']
        if action=='npc_buy':
            self._npc_stock_locked(chat)
            current=self.connection.execute('SELECT * FROM fictional_workers WHERE id=?',(r['id'],)).fetchone()
            if not current or current['owner'] is not None or current['status'] not in ('stock','runaway'):raise ValueError('NPC уже приобретён или предложение устарело.')
            self._npc_pay_locked(chat,actor,r['price']);r['owner']=actor;r['status']='rest';r['site']=None;r['tick']=stamp
            d['loyalty']=max(40,d['loyalty']);d['history']=(d['history']+[dict(at=stamp,text='Новый владелец')])[-30:]
        else:
            if r['owner']!=actor:raise ValueError('Это не твой NPC.')
            if r['revision']!=b.get('revision'):raise ValueError('Состояние NPC изменилось. Обнови карточку.')
            if r['status'] in ('missing','expedition'):raise ValueError('Сначала дождись возвращения NPC.')
            if action=='npc_appraise':
                if d['appraised']:raise ValueError('Редкость уже известна и никогда не меняется.')
                self._npc_pay_locked(chat,actor,50);d['appraised']=True
            elif action=='npc_assign':
                from enterprises import CAPACITIES
                if r['status']=='training':raise ValueError('Сначала закончи обучение.')
                site=self._enterprise_locked(chat,actor,b.get('site'))
                if not site:raise ValueError('Выбери своё предприятие.')
                used=len(self._enterprise_workers_locked(site))+self._npc_count_locked(site)-(1 if r['site']==site['id'] else 0)
                if used>=CAPACITIES[site['level']]:raise ValueError('Нет свободных рабочих мест.')
                r['site']=site['id'];r['status']='work';d['role']='worker';d['work_since']=stamp
            elif action=='npc_rest':
                if r['status']=='training':raise ValueError('Обучение уже оплачено; дождись окончания.')
                r['status']='rest';r['site']=None
            elif action=='npc_train':
                if r['status']=='training':raise ValueError('Обучение уже идёт.')
                kind=b.get('kind');key='profession_level' if kind=='work' else 'level'
                if kind not in ('work','combat') or d[key]>=(10 if kind=='work' else 20):raise ValueError('Обучение недоступно.')
                self._npc_pay_locked(chat,actor,100*d[key]);r['status']='training';r['site']=None
                d['training']=dict(kind=kind,ends=stamp+(12 if kind=='work' else 18)*HOUR)
            elif action=='npc_release':
                if b.get('confirm') is not True:raise ValueError('Подтверди освобождение NPC.')
                r['owner']=None;r['status']='runaway';r['site']=None
            else:raise ValueError('Неизвестное действие NPC.')
        self._npc_save_locked(r)
        return dict(notice='Готово. Редкость и история NPC сохранены.')

    def _npc_trip_start_locked(self, chat, actor, b):
        self._require_feature_locked(chat,'arena')
        ids=b.get('ids');mission=EXPEDITIONS.get(b.get('mission'))
        if not mission or not isinstance(ids,list) or not 1<=len(ids)<=5 or any(not isinstance(i,str) or len(i)!=32 for i in ids) or len(set(ids))!=len(ids):raise ValueError('Выбери миссию и от одного до пяти разных NPC.')
        if self.connection.execute("SELECT 1 FROM npc_trips WHERE owner=? AND status='active' UNION ALL SELECT 1 FROM slave_expeditions WHERE owner_id=? AND status='active'",(actor,actor)).fetchone():raise ValueError('На аккаунте уже идёт экспедиция.')
        users=b.get('users',[])
        if not isinstance(users,list) or any(type(i) is not int or i<=0 for i in users) or len(set(users))!=len(users) or len(ids)+len(users)>5:
            raise ValueError('Отряд: до пяти разных игроков и NPC вместе.')
        humans=[]
        for user in users:
            owned=self.connection.execute('SELECT acquired_at FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(chat,actor,user)).fetchone()
            if not owned or self._enterprise_away_locked(chat,actor,user,now(),now()+1) or self._trader_listed_locked(chat,user):raise ValueError('Участник больше не твой или сейчас недоступен.')
            recent=self.connection.execute('SELECT MAX(started_at) AS latest,MAX(active) AS active FROM slave_expedition_members WHERE user_id=?',(user,)).fetchone()
            if recent['active'] or recent['latest'] is not None and recent['latest']+6*HOUR>now():raise ValueError('Участник уже в походе или не прошло шесть часов.')
            snapshot=self._expedition_source_locked(chat,user)
            name=self.connection.execute('SELECT display_name FROM users WHERE chat_id=? AND user_id=?',(chat,user)).fetchone()
            humans.append(dict(user_id=user,epoch=owned['acquired_at'],name=name[0] if name else str(user),power=snapshot['power'],snapshot=snapshot))
        rows=[]
        for npc_id in ids:
            row=self.connection.execute('SELECT * FROM fictional_workers WHERE id=? AND chat=? AND owner=?',(npc_id,chat,actor)).fetchone()
            if not row:raise ValueError('Один из NPC больше не твой.')
            r=self._npc_decode(row)
            if r['status'] not in ('rest','work') or r['data']['ready_at']>now():raise ValueError('NPC недоступен или ещё не прошло шесть часов с прошлого похода.')
            rows.append(r)
        avg=(sum(power(r['data']) for r in rows)+sum(p['power'] for p in humans))/(len(rows)+len(humans))
        chance=min(.75,max(.03,mission['base_loss']/100+(mission['power']-avg)/200))
        names=[r['data']['name'] for r in rows]+[p['name'] for p in humans]
        quote=dict(names=names,loss_percent=round(chance*100),francs=mission['francs']*(len(rows)+len(humans)),
            pages=mission['pages'],page_rarity=mission['page_rarity'],duration=mission['duration'])
        fingerprint=hashlib.sha256(json.dumps([b['mission'],[(r['id'],r['revision']) for r in rows],humans],sort_keys=True).encode()).hexdigest()
        if b['action']=='npc_trip_quote':return dict(quote=dict(**quote,revision=fingerprint),notice='Риск рассчитан. Отряд ещё не отправлен.')
        if b.get('revision')!=fingerprint:raise ValueError('Сначала рассчитай отряд. Его состав или состояние могли измениться.')
        rng=random.SystemRandom();payload=dict(names=names,loss_percent=round(chance*100),
            outcomes=[(r['id'],rng.random()<chance) for r in rows],recruit=rng.choice(list(PROFESSIONS)) if rng.random()<.08 else None)
        payload['humans']=[dict(user_id=p['user_id'],lost=rng.random()<chance) for p in humans]
        token=uuid4().hex
        for p in humans:
            self.connection.execute('INSERT INTO slave_expedition_members VALUES(?,?,?,?,?,1,?,NULL,?)',
                (token,p['user_id'],chat,actor,p['epoch'],now(),json.dumps(p['snapshot'])))
        for r in rows:r['status']='expedition';self._npc_save_locked(r)
        self.connection.execute("INSERT INTO npc_trips VALUES(?,?,?,?,?,?,'active',?)",(token,chat,actor,b['mission'],now(),now()+mission['duration'],json.dumps(payload)))
        return dict(notice=f'Отряд отправлен. Риск освобождения каждого: {round(chance*100)}%. Результат зафиксирован на сервере.')
