"""Multi-enterprise economy. All mutations and settlements share Database._lock."""

import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from uuid import uuid4
from slave_recovery import RecoveryMixin

MAX_ENTERPRISES = 3
CAPACITIES = {1: 10, 2: 15, 3: 20}
UPGRADE_PRICES = {1: 400, 2: 1000}
CATALOG = {
    'brothel': dict(name='Бордель', emoji='🏩', producer='Куртизанка', leader='Управляющий', price=0),
    'field': dict(name='Хлопковое поле', emoji='🌾', producer='Сборщик', leader='Надзиратель', price=0),
    'tavern': dict(name='Таверна', emoji='🍺', producer='Трактирщик', leader='Управляющий', price=500),
    'mine': dict(name='Шахта', emoji='⛏', producer='Шахтёр', leader='Бригадир', price=750),
    'workshop': dict(name='Мастерская', emoji='🔨', producer='Мастер', leader='Старший мастер', price=1000),
    'custom': dict(name='Своё предприятие', emoji='🏢', producer='Работник', leader='Управляющий', price=750),
}
NEW_CONFIG = {
    key: dict(producer_role='worker', leader_role='leader', owner_per_producer=rate,
              inactive_owner_per_producer=1, producer_wage=1, producer_wage_period_hours=6,
              leader_wage=1, leader_wage_period_hours=12, shift_owner=shift)
    for key, rate, shift in (('tavern', 2, 3), ('mine', 3, 1), ('workshop', 4, 1), ('custom', 3, 1))
}


def now():
    from database import utc_timestamp
    return utc_timestamp()


def config(site):
    from database import BUSINESS_CONFIG
    return BUSINESS_CONFIG[site['business_type']]


def title(site):
    return site['name'] or CATALOG[site['business_type']]['name']


def role_labels(site):
    defaults = CATALOG[site['business_type']]
    return (site['producer_title'] or defaults['producer'], site['leader_title'] or defaults['leader'])


class EnterpriseMixin(RecoveryMixin):
    async def business_for_worker(self, chat, owner, worker):
        async with self._lock:
            return self._enterprise_locked(chat,owner,worker=worker)

    def _enterprise_backup_before_migration(self):
        folder=self.path.parent/'backups'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'before-enterprises-{now()}-{uuid4().hex[:8]}.sqlite3'
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(path)) as snapshot:
                source.backup(snapshot)
                if snapshot.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise RuntimeError('Не удалось проверить резервную копию предприятий.')
        logging.info('Enterprise migration backup: %s',path)

    def _init_enterprises(self):
        """Retain an immutable pre-migration table; preserve IDs/jobs/balances."""
        columns = {r['name'] for r in self.connection.execute('PRAGMA table_info(businesses)')}
        if 'id' not in columns:
            if self.connection.execute('SELECT 1 FROM businesses LIMIT 1').fetchone():
                self._enterprise_backup_before_migration()
            with self.connection:
                self.connection.execute('SAVEPOINT enterprise_schema')
                self.connection.execute('ALTER TABLE businesses RENAME TO businesses_legacy_backup')
                self.connection.execute('''CREATE TABLE businesses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                    owner_id INTEGER NOT NULL, business_type TEXT NOT NULL CHECK(business_type IN ('brothel','field','tavern','mine','workshop','custom')),
                    created_at INTEGER NOT NULL,last_accrued INTEGER NOT NULL,
                    income_remainder INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 3),
                    name TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',
                    producer_title TEXT NOT NULL DEFAULT '',leader_title TEXT NOT NULL DEFAULT '',
                    rules_since INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(chat_id,owner_id,business_type))''')
                self.connection.execute('''INSERT INTO businesses(chat_id,owner_id,business_type,
                    created_at,last_accrued,income_remainder,rules_since)
                    SELECT chat_id,owner_id,business_type,created_at,last_accrued,income_remainder,?
                    FROM businesses_legacy_backup''', (now(),))
                self.connection.execute('RELEASE enterprise_schema')
        self._ensure_column('business_workers','business_id','INTEGER')
        self.connection.execute('''UPDATE business_workers SET business_id=(
            SELECT MIN(b.id) FROM businesses b WHERE b.chat_id=business_workers.chat_id
            AND b.owner_id=business_workers.owner_id) WHERE business_id IS NULL''')
        self.connection.executescript('''
            CREATE INDEX IF NOT EXISTS idx_business_owner ON businesses(chat_id,owner_id);
            CREATE INDEX IF NOT EXISTS idx_business_site_workers ON business_workers(business_id);
            CREATE TABLE IF NOT EXISTS enterprise_income_daily(
                business_id INTEGER NOT NULL,income_day TEXT NOT NULL,gross_income INTEGER NOT NULL DEFAULT 0,
                net_income INTEGER NOT NULL DEFAULT 0,tax_paid INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(business_id,income_day));
        ''')
        self._init_recovery_events()

    def _enterprise_locked(self, chat, owner, site_id=None, worker=None):
        if site_id is None and worker is not None:
            assigned=self.connection.execute('SELECT business_id FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?', (chat,owner,worker)).fetchone()
            if assigned and assigned['business_id'] is not None:
                site_id=assigned['business_id']
        rows=self.connection.execute('SELECT * FROM businesses WHERE chat_id=? AND owner_id=? ORDER BY id',(chat,owner)).fetchall()
        if site_id is not None:
            return next((b for b in rows if b['id']==site_id),None)
        return rows[0] if len(rows)==1 else None

    def _enterprise_workers_locked(self, site):
        # Nullable IDs only support old/imported single-site rows. They never
        # count toward two businesses after an expansion.
        return self.connection.execute('''SELECT w.*,u.last_seen,u.username,u.display_name
            FROM business_workers w JOIN ownership o ON o.chat_id=w.chat_id
            AND o.owner_id=w.owner_id AND o.slave_id=w.worker_id
            LEFT JOIN users u ON u.chat_id=w.chat_id AND u.user_id=w.worker_id
            WHERE w.chat_id=? AND w.owner_id=? AND (w.business_id=? OR
            (w.business_id IS NULL AND 1=(SELECT COUNT(*) FROM businesses WHERE chat_id=? AND owner_id=?)))
            ORDER BY w.assigned_at,w.worker_id''',(site['chat_id'],site['owner_id'],site['id'],site['chat_id'],site['owner_id'])).fetchall()

    def _enterprise_away_locked(self, chat, owner, worker, begin, end):
        return self.connection.execute('''SELECT 1 FROM slave_recovery_events WHERE chat_id=?
            AND owner_id=? AND slave_id=? AND activated_at IS NOT NULL AND activated_at<?
            AND (ended_at IS NULL OR ended_at>?) LIMIT 1''',(chat,owner,worker,end,begin)).fetchone() is not None

    def _enterprise_credit_site_locked(self, site, day, gross):
        net,tax=self._credit_business_income_locked(site['chat_id'],site['owner_id'],day,gross)
        self.connection.execute('''INSERT INTO enterprise_income_daily VALUES(?,?,?,?,?)
            ON CONFLICT(business_id,income_day) DO UPDATE SET gross_income=gross_income+excluded.gross_income,
            net_income=net_income+excluded.net_income,tax_paid=tax_paid+excluded.tax_paid''',
            (site['id'],day,gross,net,tax))
        return net,tax

    def _enterprise_settle_site_locked(self, site, timestamp):
        from database import BUSINESS_HOUR_SECONDS, BUSINESS_ACTIVE_SECONDS, BUSINESS_STATS_TZ
        chat,owner=site['chat_id'],site['owner_id']
        hours=max(0,(timestamp-site['last_accrued'])//BUSINESS_HOUR_SECONDS)
        result=dict(hours=hours,owner_income=0,gross_income=0,tax=0,business_type=site['business_type'])
        if not hours or not self._feature_enabled_locked(chat,'slavery'):
            result['hours']=0
            return result
        workers=self._enterprise_workers_locked(site); cfg=config(site)
        remainder=site['income_remainder']; daily={}; wage_hours={w['worker_id']:0 for w in workers}
        for hour in range(hours):
            begin=site['last_accrued']+hour*BUSINESS_HOUR_SECONDS; end=begin+BUSINESS_HOUR_SECONDS
            legacy=end<=site['rules_since']
            leaders=[w for w in workers if w['role']==cfg['leader_role']]
            producers=[w for w in workers if w['role']==cfg['producer_role']]
            if not legacy:
                leaders=leaders[:1]
                producers=producers[:CAPACITIES[site['level']]-len(leaders)]
            present=[w for w in (*leaders,*producers) if not self._enterprise_away_locked(chat,owner,w['worker_id'],begin,end)]
            live_leaders=[w for w in leaders if w in present]
            bonus=sum(20//(2**i) for i in range(min(5,len(live_leaders)))) if legacy else (20 if live_leaders else 0)
            active=sum(w['role']==cfg['producer_role'] and w['last_seen'] is not None and end<=w['last_seen']+BUSINESS_ACTIVE_SECONDS for w in present)
            inactive=sum(w['role']==cfg['producer_role'] for w in present)-active
            gross,remainder=divmod(active*cfg['owner_per_producer']*(100+bonus)+inactive*cfg['inactive_owner_per_producer']*100+remainder,100)
            day=datetime.fromtimestamp(end-1,BUSINESS_STATS_TZ).date().isoformat()
            daily[day]=daily.get(day,0)+gross
            for w in present:
                if w['last_seen'] is not None and end<=w['last_seen']+BUSINESS_ACTIVE_SECONDS:
                    wage_hours[w['worker_id']]+=1
        for day,gross in daily.items():
            net,tax=self._enterprise_credit_site_locked(site,day,gross)
            result['gross_income']+=gross;result['owner_income']+=net;result['tax']+=tax
        for w in workers:
            leader=w['role']==cfg['leader_role']; period=cfg['leader_wage_period_hours' if leader else 'producer_wage_period_hours']
            payouts,left=divmod(w['wage_hours']+wage_hours[w['worker_id']],period)
            if payouts:self._credit_labor_income_locked(chat,w['worker_id'],payouts*cfg['leader_wage' if leader else 'producer_wage'],timestamp)
            self.connection.execute('UPDATE business_workers SET wage_hours=? WHERE chat_id=? AND owner_id=? AND worker_id=?',(left,chat,owner,w['worker_id']))
        self.connection.execute('UPDATE businesses SET last_accrued=last_accrued+?,income_remainder=? WHERE id=?',(hours*BUSINESS_HOUR_SECONDS,remainder,site['id']))
        return result

    def _enterprise_settle_owner_locked(self, chat, owner, timestamp):
        sites=self.connection.execute('SELECT * FROM businesses WHERE chat_id=? AND owner_id=? ORDER BY id',(chat,owner)).fetchall()
        if not sites:return None
        total=dict(hours=0,owner_income=0,gross_income=0,tax=0,business_type=sites[0]['business_type'])
        for site in sites:
            r=self._enterprise_settle_site_locked(site,timestamp)
            total['hours']=max(total['hours'],r['hours'])
            for key in ('owner_income','gross_income','tax'):total[key]+=r[key]
        return total

    async def enterprise_create(self, chat, owner, kind):
        if kind not in CATALOG:raise ValueError('Unknown business type')
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            with self.connection:
                sites=self.connection.execute('SELECT * FROM businesses WHERE chat_id=? AND owner_id=?',(chat,owner)).fetchall()
                if any(s['business_type']==kind for s in sites):return 'exists'
                if len(sites)>=MAX_ENTERPRISES:return 'limit'
                if not self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=?',(chat,owner)).fetchone():return 'no_slaves'
                price=CATALOG[kind]['price']
                balance=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,owner)).fetchone()
                if price and (not balance or balance['balance']<price):return 'insufficient'
                if price:
                    paid=self.connection.execute('UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?',(price,now(),chat,owner,price))
                    if not paid.rowcount:return 'insufficient'
                timestamp=now()
                # Bind any old/imported rows before adding a second site.
                if len(sites)==1:self.connection.execute('UPDATE business_workers SET business_id=? WHERE chat_id=? AND owner_id=? AND business_id IS NULL',(sites[0]['id'],chat,owner))
                self.connection.execute('INSERT INTO businesses(chat_id,owner_id,business_type,created_at,last_accrued,rules_since) VALUES(?,?,?,?,?,?)',(chat,owner,kind,timestamp,timestamp,timestamp))
                return 'created'

    async def enterprise_assign(self, chat, owner, worker, role, site_id=None):
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            with self.connection:
                site=self._enterprise_locked(chat,owner,site_id,worker)
                if not site:return 'no_business'
                cfg=config(site)
                if role is not None and role not in (cfg['producer_role'],cfg['leader_role']):return 'invalid_role'
                if not self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(chat,owner,worker)).fetchone():return 'not_owned'
                if self.connection.execute("SELECT 1 FROM slave_recovery_events WHERE chat_id=? AND owner_id=? AND slave_id=? AND status IN ('pending','playing')",(chat,owner,worker)).fetchone():return 'away'
                rows=self._enterprise_workers_locked(site)
                others=[w for w in rows if w['worker_id']!=worker]
                if role is not None:
                    if len(others)>=CAPACITIES[site['level']]:return 'full'
                    if role==cfg['leader_role'] and any(w['role']==role for w in others):return 'leader_full'
                timestamp=now()
                self._enterprise_settle_owner_locked(chat,owner,timestamp)
                current=self.connection.execute('SELECT * FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?',(chat,owner,worker)).fetchone()
                if role is None:
                    if current and current['business_id'] not in (None,site['id']):return 'other_business'
                    self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?',(chat,owner,worker))
                    return 'removed'
                self.connection.execute('''INSERT INTO business_workers(chat_id,owner_id,worker_id,role,assigned_at,business_id,wage_hours)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(chat_id,owner_id,worker_id) DO UPDATE SET
                    role=excluded.role,assigned_at=excluded.assigned_at,business_id=excluded.business_id,wage_hours=excluded.wage_hours''',
                    (chat,owner,worker,role,timestamp,site['id'],current['wage_hours'] if current and current['role']==role else 0))
                return 'updated'

    async def enterprise_edit(self, chat, owner, site_id, field, value):
        limits={'name':60,'description':500,'producer_title':30,'leader_title':30}
        if field not in limits or not isinstance(value,str):raise ValueError('Недопустимое поле.')
        value=value.strip()
        if len(value)>limits[field] or (not value and field!='description') or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError(f'Допустимо от 1 до {limits[field]} символов.')
        if field!='description' and ('\n' in value or '\t' in value):raise ValueError('Нужна одна строка.')
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            site=self._enterprise_locked(chat,owner,site_id)
            if not site:raise ValueError('Предприятие недоступно.')
            if field.endswith('_title') and site['business_type']!='custom':raise ValueError('Должности переименовываются только в своём предприятии.')
            self.connection.execute(f'UPDATE businesses SET {field}=? WHERE id=?',(value,site_id));self.connection.commit()

    async def enterprise_upgrade(self, chat, owner, site_id, expected_level):
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            with self.connection:
                site=self._enterprise_locked(chat,owner,site_id)
                if not site:return 'missing'
                if site['level']!=expected_level:return 'stale'
                if site['level']>=3:return 'max'
                price=UPGRADE_PRICES[site['level']]
                row=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,owner)).fetchone()
                if not row or row['balance']<price:return 'insufficient'
                self._enterprise_settle_owner_locked(chat,owner,now())
                paid=self.connection.execute('UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?',(price,now(),chat,owner,price))
                if not paid.rowcount:return 'insufficient'
                self.connection.execute('UPDATE businesses SET level=level+1 WHERE id=?',(site_id,))
                return 'upgraded'

    async def enterprise_view(self, chat, site_id, actor=None):
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            site=self.connection.execute('SELECT * FROM businesses WHERE chat_id=? AND id=?',(chat,site_id)).fetchone()
            if not site:return None
            self._enterprise_settle_owner_locked(chat,site['owner_id'],now())
            site=dict(self.connection.execute('SELECT * FROM businesses WHERE id=?',(site_id,)).fetchone())
            workers=[dict(w) for w in self._enterprise_workers_locked(site)]
            for w in workers:w['away']=self._enterprise_away_locked(chat,site['owner_id'],w['worker_id'],now(),now()+1)
            site.update(workers=workers,capacity=CAPACITIES[site['level']],can_edit=actor==site['owner_id'])
            self.connection.commit()
            return site

    async def enterprise_statistics(self, chat, owner, site_id):
        async with self._lock:
            self._require_feature_locked(chat,'slavery')
            if not self._enterprise_locked(chat,owner,site_id):raise ValueError('Предприятие недоступно.')
            self._enterprise_settle_owner_locked(chat,owner,now())
            rows=[dict(r) for r in self.connection.execute('SELECT * FROM enterprise_income_daily WHERE business_id=? ORDER BY income_day DESC LIMIT 7',(site_id,))]
            self.connection.commit()
            return rows
