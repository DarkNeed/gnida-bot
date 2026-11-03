"""Management warnings, daily account rolls and recoveries with an outer deadline.

Never create fake loyalty for human users. Ownership epochs invalidate searches.
Only a delivered notification or an opened management page starts a warning clock.
"""
import json
import random
from uuid import uuid4

from npc_worker_rules import DAY,HOUR,PROFESSIONS
from slave_recovery import code_feedback, RECOVERY_SYMBOLS


def now():
    from database import utc_timestamp
    return utc_timestamp()


class WorkforceMixin:
    def _init_workforce(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS workforce_events(
                id TEXT PRIMARY KEY,chat INTEGER NOT NULL,owner INTEGER NOT NULL,
                worker TEXT NOT NULL,worker_type TEXT NOT NULL,epoch INTEGER NOT NULL,
                name TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,
                created INTEGER NOT NULL,activated INTEGER,deadline INTEGER,ended INTEGER,
                revision INTEGER NOT NULL DEFAULT 0,data TEXT NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS workforce_open ON workforce_events(status,deadline);
            CREATE TABLE IF NOT EXISTS workforce_rolls(owner INTEGER NOT NULL,day INTEGER NOT NULL,PRIMARY KEY(owner,day));
            CREATE TABLE IF NOT EXISTS workforce_warnings(
                chat INTEGER NOT NULL,owner INTEGER NOT NULL,created INTEGER NOT NULL,
                seen INTEGER,deadline INTEGER,reason TEXT NOT NULL,status TEXT NOT NULL,
                PRIMARY KEY(chat,owner));
            CREATE TRIGGER IF NOT EXISTS workforce_release AFTER DELETE ON ownership BEGIN
                UPDATE workforce_events SET status='cancelled',revision=revision+1,
                    ended=CAST(strftime('%s','now') AS INTEGER)
                    WHERE chat=OLD.chat_id AND owner=OLD.owner_id AND worker=CAST(OLD.slave_id AS TEXT)
                    AND worker_type='human' AND status IN ('announcing','open','playing','search'); END;
            CREATE TRIGGER IF NOT EXISTS workforce_transfer AFTER UPDATE OF owner_id,acquired_at ON ownership
                WHEN OLD.owner_id<>NEW.owner_id OR OLD.acquired_at<>NEW.acquired_at BEGIN
                UPDATE workforce_events SET status='cancelled',revision=revision+1,
                    ended=CAST(strftime('%s','now') AS INTEGER)
                    WHERE chat=OLD.chat_id AND owner=OLD.owner_id AND worker=CAST(OLD.slave_id AS TEXT)
                    AND worker_type='human' AND status IN ('announcing','open','playing','search'); END;
        ''')

    def _workforce_away_locked(self, chat, owner, worker, begin, end):
        return bool(self.connection.execute("""SELECT 1 FROM workforce_events WHERE chat=? AND owner=?
            AND worker=? AND worker_type='human' AND activated<? AND (ended IS NULL OR ended>?)
            AND activated IS NOT NULL LIMIT 1""",(chat,owner,str(worker),end,begin)).fetchone())

    def _workforce_risk_locked(self, chat, owner):
        estate=self._npc_estate_locked(chat,owner);rows=self._npc_rows_locked(chat,owner)
        reasons=[];score=0
        present=[r for r in rows if r['status'] not in ('missing','expedition')]
        daily=sum(PROFESSIONS[r['data']['profession']]['upkeep'] for r in present)
        wallet=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,owner)).fetchone()
        if daily and (not wallet or wallet['balance']<daily):score+=1;reasons.append('в кошельке не хватает франков на сутки содержания')
        if any(r['data']['unpaid']>=24 for r in present):score+=1;reasons.append('содержание не оплачено больше суток')
        if any(r['data']['fatigue']>=80 or r['data']['loyalty']<40 or r['data']['health']<50 for r in present):
            score+=1;reasons.append('истощение, плохое здоровье или низкая лояльность NPC')
        human_count=self.connection.execute('SELECT COUNT(*) FROM business_workers WHERE chat_id=? AND owner_id=?',(chat,owner)).fetchone()[0]
        leaders=self.connection.execute("SELECT COUNT(*) FROM business_workers WHERE chat_id=? AND owner_id=? AND role IN ('leader','manager','overseer')",(chat,owner)).fetchone()[0]
        leaders+=sum(r['status']=='work' and r['data'].get('role')=='leader' for r in present)
        unmanaged=human_count+sum(r['status']=='work' for r in present)>10 and not leaders
        if unmanaged:score+=1;reasons.append('больше десяти работников без управляющего')
        if (rows or human_count) and estate['care']+2*DAY<now():score+=1;reasons.append('условия не проверялись больше 48 часов')
        # Guards prevent kidnappings; a diplomat also lowers escape pressure.
        protection=any(r['data']['trait']=='guard' and r['data']['health']>=60 and r['data']['fatigue']<80 for r in present)
        diplomacy=any(r['data']['trait']=='diplomat' and r['data']['health']>=60 and r['data']['fatigue']<80 for r in present)
        score=max(0,min(3,score)-int(diplomacy))
        return dict(tier=score,chance=(0,2,5,10)[score],reasons=reasons,protected=bool(protection),daily_upkeep=daily)

    def _workforce_valid_locked(self, event):
        if event['worker_type']=='npc':
            return bool(self.connection.execute('SELECT 1 FROM fictional_workers WHERE id=? AND chat=? AND owner=?',(event['worker'],event['chat'],event['owner'])).fetchone())
        return bool(self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=? AND acquired_at=?',
            (event['chat'],event['owner'],int(event['worker']),event['epoch'])).fetchone())

    def _workforce_pay_bounty_locked(self, event, beneficiary):
        current=self.connection.execute('SELECT data FROM workforce_events WHERE id=?',(event['id'],)).fetchone()
        payload=json.loads(current['data'])
        if payload.get('bounty') and not payload.get('bounty_paid'):
            self._credit_labor_income_locked(event['chat'],beneficiary,payload['bounty'],now())
            payload['bounty_paid']=True
            self.connection.execute('UPDATE workforce_events SET data=? WHERE id=?',(json.dumps(payload),event['id']))

    def _workforce_finish_locked(self, event, success):
        valid=self._workforce_valid_locked(event)
        payload=json.loads(event['data'])
        effective_end=min(now(),payload.get('search_ends',now())) if success and event['status']=='search' else now()
        if success and valid:
            self.connection.execute('UPDATE workforce_events SET ended=? WHERE id=?',(effective_end,event['id']))
        # Settle before stopping absence / deleting ownership. This function is never
        # called recursively from NPC settlement.
        self._enterprise_settle_owner_locked(event['chat'],event['owner'],now())
        status=('returned' if success else 'lost') if valid else 'cancelled'
        self.connection.execute('UPDATE workforce_events SET status=?,ended=?,revision=revision+1 WHERE id=?',(status,effective_end,event['id']))
        if valid and event['worker_type']=='npc':
            r=self._npc_decode(self.connection.execute('SELECT * FROM fictional_workers WHERE id=?',(event['worker'],)).fetchone())
            r['status']='rest' if success else 'runaway';r['site']=None;r['tick']=effective_end
            if not success:r['owner']=None
            r['data']['history']=(r['data']['history']+[dict(at=now(),text='Возвращён после розыска' if success else 'Стал беглецом')])[-30:]
            self._npc_save_locked(r)
            if success:self._npc_tick_locked(event['chat'],event['owner'],now())
        elif valid and not success:
            self.connection.execute('DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(event['chat'],event['owner'],int(event['worker'])))
            self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?',(event['chat'],event['owner'],int(event['worker'])))
        if payload.get('bounty'):
            beneficiary=payload.get('helper') if success and payload.get('helper') else event['owner']
            self._workforce_pay_bounty_locked(event,beneficiary)

    def _workforce_activate_locked(self, event):
        if not self._workforce_valid_locked(event):
            self.connection.execute("UPDATE workforce_events SET status='cancelled',ended=? WHERE id=?",(now(),event['id']));return
        self._enterprise_settle_owner_locked(event['chat'],event['owner'],now())
        self.connection.execute("UPDATE workforce_events SET status='open',activated=?,deadline=?,notified=1,revision=revision+1 WHERE id=? AND status='announcing'",(now(),now()+8*HOUR,event['id']))
        if event['worker_type']=='npc':
            self.connection.execute("UPDATE fictional_workers SET status='missing',revision=revision+1 WHERE id=?",(event['worker'],))

    def _workforce_tick_locked(self, chat, owner):
        stamp=now()
        for e in self.connection.execute("SELECT * FROM workforce_events WHERE chat=? AND owner=? AND status='cancelled' AND json_extract(data,'$.bounty')>0 AND COALESCE(json_extract(data,'$.bounty_paid'),0)=0",(chat,owner)).fetchall():
            self._workforce_pay_bounty_locked(e,owner)
        if not self._feature_enabled_locked(chat,'slavery'):
            for e in self.connection.execute("SELECT * FROM workforce_events WHERE chat=? AND owner=? AND status IN ('announcing','open','playing','search')",(chat,owner)).fetchall():
                self._workforce_finish_locked(e,True)
                self.connection.execute("UPDATE workforce_events SET status='cancelled' WHERE id=?",(e['id'],))
            self.connection.execute("UPDATE workforce_warnings SET status='resolved' WHERE chat=? AND owner=?",(chat,owner));return
        risk=self._workforce_risk_locked(chat,owner)
        warning=self.connection.execute('SELECT * FROM workforce_warnings WHERE chat=? AND owner=?',(chat,owner)).fetchone()
        if risk['tier']==0:
            self.connection.execute("UPDATE workforce_warnings SET status='resolved' WHERE chat=? AND owner=? AND status='warning'",(chat,owner))
        elif not warning or warning['status']!='warning':
            self.connection.execute("INSERT OR REPLACE INTO workforce_warnings VALUES(?,?,?,NULL,NULL,?,'warning')",(chat,owner,stamp,json.dumps(risk['reasons'],ensure_ascii=False)))
        for event in self.connection.execute("SELECT * FROM workforce_events WHERE chat=? AND owner=? AND status IN ('open','playing','search')",(chat,owner)).fetchall():
            p=json.loads(event['data'])
            if not self._workforce_valid_locked(event):self._workforce_finish_locked(event,False)
            elif event['status']=='search' and p['search_ends']<=stamp:
                if p['search_success']:self._workforce_finish_locked(event,True)
                else:
                    self.connection.execute("UPDATE workforce_events SET status='open',revision=revision+1 WHERE id=?",(event['id'],))
                    # Search can fail without consuming the remaining recovery window.
                    if event['deadline']<=stamp:self._workforce_finish_locked(event,False)
            elif event['deadline']<=stamp or (event['status']=='playing' and p['game_ends']<=stamp):self._workforce_finish_locked(event,False)

    def _workforce_roll_locked(self, rng=None):
        rng=rng or random.SystemRandom();stamp=now();day=(stamp+3*HOUR)//DAY
        accounts=self.connection.execute('''SELECT chat_id AS chat,owner_id AS owner FROM ownership WHERE owner_id>0 UNION
            SELECT chat,owner FROM fictional_workers WHERE owner>0''').fetchall()
        grouped={}
        for a in accounts:
            if not self._feature_enabled_locked(a['chat'],'slavery'):continue
            self._enterprise_settle_owner_locked(a['chat'],a['owner'],stamp)
            self._workforce_tick_locked(a['chat'],a['owner'])
            risk=self._workforce_risk_locked(a['chat'],a['owner'])
            warning=self.connection.execute("SELECT * FROM workforce_warnings WHERE chat=? AND owner=? AND status='warning'",(a['chat'],a['owner'])).fetchone()
            if warning and warning['deadline'] and warning['deadline']<=stamp and risk['tier']:
                grouped.setdefault(a['owner'],[]).append((a['chat'],risk))
        for owner,choices in grouped.items():
            # One daily chance for the account, not one lottery per chat/refresh.
            if not self.connection.execute('INSERT OR IGNORE INTO workforce_rolls VALUES(?,?)',(owner,day)).rowcount:continue
            if self.connection.execute("SELECT 1 FROM workforce_events WHERE owner=? AND (status IN ('announcing','open','playing','search') OR created>?)",(owner,stamp-DAY)).fetchone():continue
            chat,risk=max(choices,key=lambda x:(x[1]['tier'],-x[0]))
            if rng.random()*100>=risk['chance']:continue
            candidates=[]
            for r in self._npc_rows_locked(chat,owner):
                if r['status'] in ('work','rest'):candidates.append(('npc',r['id'],r['created'],r['data']['name']))
            for r in self.connection.execute('''SELECT o.slave_id,o.acquired_at,u.display_name FROM ownership o
                    LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id WHERE o.chat_id=? AND o.owner_id=?''',(chat,owner)):
                if not self._enterprise_away_locked(chat,owner,r['slave_id'],stamp,stamp+1) and not self._trader_listed_locked(chat,r['slave_id']):
                    candidates.append(('human',str(r['slave_id']),r['acquired_at'],r['display_name'] or str(r['slave_id'])))
            if not candidates:continue
            typ,worker,epoch,name=rng.choice(candidates)
            kind='escaped' if risk['protected'] else rng.choice(('escaped','kidnapped'))
            payload=dict(secret=rng.sample(range(len(RECOVERY_SYMBOLS)),3),history=[],bounty=0)
            self.connection.execute("INSERT INTO workforce_events VALUES(?,?,?,?,?,?,?,?, 'announcing',?,NULL,NULL,NULL,0,?,0)",
                (uuid4().hex,chat,owner,worker,typ,epoch,name,kind,stamp,json.dumps(payload)))

    def _workforce_view_locked(self, chat, owner):
        self._workforce_tick_locked(chat,owner)
        warning=self.connection.execute('SELECT * FROM workforce_warnings WHERE chat=? AND owner=?',(chat,owner)).fetchone()
        if warning and warning['status']=='warning' and warning['seen'] is None:
            self.connection.execute('UPDATE workforce_warnings SET seen=?,deadline=? WHERE chat=? AND owner=?',(now(),now()+DAY,chat,owner))
            warning=self.connection.execute('SELECT * FROM workforce_warnings WHERE chat=? AND owner=?',(chat,owner)).fetchone()
        for event in self.connection.execute("SELECT * FROM workforce_events WHERE chat=? AND owner=? AND status='announcing'",(chat,owner)).fetchall():self._workforce_activate_locked(event)
        events=[]
        for r in self.connection.execute('SELECT * FROM workforce_events WHERE chat=? AND (owner=? OR status IN (\'open\',\'playing\',\'search\')) ORDER BY created DESC LIMIT 15',(chat,owner)):
            p=json.loads(r['data'])
            if r['owner']!=owner and not p.get('bounty'):continue
            e=dict(r);e.pop('data');e.update({k:v for k,v in p.items() if k not in ('secret','search_success')})
            e['mine']=r['owner']==owner;events.append(e)
        return dict(risk=self._workforce_risk_locked(chat,owner),warning=dict(warning) if warning and warning['status']=='warning' else None,
            events=events,symbols=RECOVERY_SYMBOLS)

    def _workforce_action_locked(self, chat, actor, b):
        if not isinstance(b.get('id'),str) or len(b['id'])!=32:raise ValueError('Некорректный розыск.')
        row=self.connection.execute('SELECT * FROM workforce_events WHERE id=? AND chat=?',(b.get('id'),chat)).fetchone()
        if row:
            self._workforce_tick_locked(chat,row['owner'])
            row=self.connection.execute('SELECT * FROM workforce_events WHERE id=?',(row['id'],)).fetchone()
        if not row or row['status'] not in ('open','playing','search'):raise ValueError('Розыск уже завершён. Обнови страницу.')
        if row['revision']!=b.get('revision'):raise ValueError('Состояние розыска изменилось. Обнови страницу.')
        p=json.loads(row['data']);action=b['action'];mine=row['owner']==actor;stamp=now()
        if not mine and action!='workforce_help':raise ValueError('Это розыск другого владельца.')
        if mine and action=='workforce_help':raise ValueError('Свою награду получить нельзя. Отправь обычную поисковую группу.')
        if action=='workforce_abandon':
            if not b.get('confirm'):raise ValueError('Подтверди отказ от розыска.')
            self._workforce_finish_locked(row,False);return dict(notice='Раб освобождён. NPC сохраняет свою личность и становится беглецом.')
        if row['status']=='search':raise ValueError('Поисковая группа уже в пути.')
        if action=='workforce_start':
            if p.get('game_ends'):raise ValueError('Повторной попытки мини-игры нет.')
            p['game_ends']=min(row['deadline'],stamp+180)
            self.connection.execute("UPDATE workforce_events SET status='playing' WHERE id=?",(row['id'],))
        elif action=='workforce_guess':
            guess=b.get('guess')
            if row['status']!='playing' or not isinstance(guess,list) or len(guess)!=3 or any(type(v) is not int or not 0<=v<6 for v in guess) or len(set(guess))!=3:raise ValueError('Нужны три разных символа.')
            exact,near=code_feedback(p['secret'],guess);p['history'].append(dict(guess=guess,exact=exact,near=near))
            if exact==3:self._workforce_finish_locked(row,True);return dict(notice='Код найден. Работник возвращён.')
            if len(p['history'])>=6:self._workforce_finish_locked(row,False);return dict(notice='Шесть попыток исчерпаны. Работник потерян.')
        elif action in ('workforce_search','workforce_help'):
            helper=not mine
            if helper and (not p.get('bounty') or p.get('helper')):raise ValueError('Нет свободного заказа на розыск.')
            if stamp+2*HOUR>=row['deadline']:raise ValueError('До конца розыска меньше двух часов.')
            if not helper:self._npc_pay_locked(chat,actor,100)
            chance=.8 if helper else .65
            if any(r['data']['trait']=='diplomat' and r['status'] not in ('missing','expedition') for r in self._npc_rows_locked(chat,row['owner'])):chance+=.1
            p.update(search_ends=stamp+2*HOUR,search_success=random.SystemRandom().random()<chance,helper=actor if helper else None)
            self.connection.execute("UPDATE workforce_events SET status='search' WHERE id=?",(row['id'],))
        elif action=='workforce_bounty':
            if p['bounty']:raise ValueError('Награда уже размещена.')
            amount=b.get('amount')
            if type(amount) is not int or not 50<=amount<=10000:raise ValueError('Награда от 50 до 10 000 франков.')
            self._npc_pay_locked(chat,actor,amount);p['bounty']=amount
        elif action=='workforce_ransom':
            if row['kind']!='kidnapped':raise ValueError('С беглецом выкуп не работает.')
            self._npc_pay_locked(chat,actor,300);self._workforce_finish_locked(row,True)
            return dict(notice='Выкуп 300 франков уплачен. Работник возвращён.')
        else:raise ValueError('Неизвестный способ розыска.')
        self.connection.execute('UPDATE workforce_events SET data=?,revision=revision+1 WHERE id=?',(json.dumps(p),row['id']))
        return dict(notice='Розыск обновлён. Внешний срок не останавливается.')

    async def workforce_notifications(self):
        async with self._lock:
            with self.connection:
                for e in self.connection.execute("SELECT * FROM workforce_events WHERE status='cancelled' AND json_extract(data,'$.bounty')>0 AND COALESCE(json_extract(data,'$.bounty_paid'),0)=0 LIMIT 100").fetchall():
                    self._workforce_pay_bounty_locked(e,e['owner'])
                self._workforce_roll_locked()
                warnings=[dict(kind='warning',**dict(r)) for r in self.connection.execute("SELECT * FROM workforce_warnings WHERE status='warning' AND seen IS NULL LIMIT 10")]
                events=[dict(r,kind='incident') for r in self.connection.execute("SELECT * FROM workforce_events WHERE status='announcing' LIMIT 10")]
                return warnings+events

    async def workforce_notified(self, row):
        async with self._lock:
            with self.connection:
                if row['kind']=='warning':
                    self.connection.execute("UPDATE workforce_warnings SET seen=?,deadline=? WHERE chat=? AND owner=? AND created=? AND seen IS NULL",(now(),now()+DAY,row['chat'],row['owner'],row['created']))
                else:
                    e=self.connection.execute("SELECT * FROM workforce_events WHERE id=? AND status='announcing'",(row['id'],)).fetchone()
                    if e:self._workforce_activate_locked(e)
