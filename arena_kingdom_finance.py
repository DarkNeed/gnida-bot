"""Opt-in taxes and isolated municipal budgets; never auto-debits a wallet."""
import math

HOUR=3600
DAY=24*HOUR
RATES={
    'holiday':dict(name='Налоговые каникулы',rate=0,order=10,growth=1.5),
    'low':dict(name='Низкие',rate=8,order=6,growth=1.25),
    'normal':dict(name='Обычные',rate=16,order=0,growth=1),
    'high':dict(name='Высокие',rate=24,order=-10,growth=.75),
    'extortion':dict(name='Поборы',rate=32,order=-20,growth=0),
}


def initialize(d,now):
    return d.setdefault('finance',dict(rate='normal',last_at=now,next_rate_at=0,strike_until=0,
        income_rem=0,cost_rem=0,order_rem=0,arrears=0,economy=False,
        collected=0,paid=0,ever_active=False))


def connect(db):
    db.connection.executescript('''
      CREATE TABLE IF NOT EXISTS kingdom_budgets(
        town TEXT PRIMARY KEY REFERENCES kingdom_towns(id),balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0));
      CREATE TABLE IF NOT EXISTS kingdom_tax_towns(
        town TEXT PRIMARY KEY REFERENCES kingdom_towns(id),active_until INTEGER NOT NULL DEFAULT 0);
      INSERT OR IGNORE INTO kingdom_budgets(town) SELECT id FROM kingdom_towns;
    ''')
    # Preserve towns enabled in the earlier local prototype without retaining
    # its one-town-per-account constraint or touching balances/debts.
    if db.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kingdom_tax_accounts'").fetchone():
        columns={r['name'] for r in db.connection.execute('PRAGMA table_info(kingdom_tax_accounts)')}
        until='active_until' if 'active_until' in columns else '0'
        db.connection.execute('INSERT OR IGNORE INTO kingdom_tax_towns(town,active_until) SELECT town,'+until+' FROM kingdom_tax_accounts')


def balance(db,row):
    db.connection.execute('INSERT OR IGNORE INTO kingdom_budgets(town) VALUES(?)',(row['id'],))
    return db.connection.execute('SELECT balance FROM kingdom_budgets WHERE town=?',(row['id'],)).fetchone()['balance']


def active(db,row):
    return bool(db.connection.execute('SELECT 1 FROM kingdom_tax_towns WHERE town=?',(row['id'],)).fetchone())


def deadline(db,row):
    account=db.connection.execute('SELECT active_until FROM kingdom_tax_towns WHERE town=?',(row['id'],)).fetchone()
    return account['active_until'] if account else 0


def touch(db,row,now):
    # Only authenticated owner reads/actions renew activity. A spectator or
    # background siege sweep cannot keep another owner's passive income alive.
    db.connection.execute('UPDATE kingdom_tax_towns SET active_until=MAX(active_until,?) WHERE town=?',
                          (now+48*HOUR,row['id']))


def upkeep(d):
    from arena_kingdom_war import UNITS,initialize as army_initialize
    people=d['population']*2
    buildings=10*sum(level*level for level in d['buildings'].values())
    administration={1:60,2:180,3:360}[d['stage']]
    army=sum(UNITS[u['kind']]['price']//100 for u in army_initialize(d)['units'])
    return dict(people=people,buildings=buildings,administration=administration,army=army,
                total=people+buildings+administration+army)


def collection(order):
    return 100 if order>=70 else 80 if order>=50 else 50 if order>=30 else 0


def quote(d,now):
    f=initialize(d,now);rate=RATES['holiday' if f['strike_until']>now else f['rate']]
    gross=d['population']*rate['rate']*d['stage']
    income=gross*collection(d['order'])/100
    costs=upkeep(d)
    return dict(gross=gross,income=income,collection=collection(d['order']),upkeep=costs,
                net=income-costs['total'],order_daily=rate['order'],growth=rate['growth'])


def spend(db,row,amount):
    f=initialize(row['data'],0);balance(db,row)
    if f['arrears']:raise ValueError('Сначала погаси задолженность по содержанию через бюджет поселения.')
    if not db.connection.execute('UPDATE kingdom_budgets SET balance=balance-? WHERE town=? AND balance>=?',
                                 (amount,row['id'],amount)).rowcount:
        raise ValueError('В бюджете поселения не хватает франков. Пополни его вручную из кошелька во вкладке «Бюджет».')


def credit(db,row,amount):
    f=initialize(row['data'],0);repaid=min(f['arrears'],amount);f['arrears']-=repaid
    f['paid']+=repaid
    if not f['arrears']:f['economy']=False
    balance(db,row)
    db.connection.execute('UPDATE kingdom_budgets SET balance=balance+? WHERE town=?',(amount-repaid,row['id']))


def accrue(db,row,until):
    """Called chronologically before each production/growth tick, at most 48h."""
    d=row['data'];f=initialize(d,until);start=f['last_at']
    if until<=start:return
    # A rate change/activation can split a resource hour. Exact integer carries
    # keep both sides of that boundary without float money or retroactive taxes.
    dt=until-start
    if d['order']<30 and f['strike_until']<=start:
        f['strike_until']=start+DAY;f['rate']='holiday';f['next_rate_at']=max(f['next_rate_at'],start+DAY)
        db._kingdom_log(row,'Налоговая забастовка: сутки без налогов. Город и войска сохранены.',start)
    rate=RATES['holiday' if f['strike_until']>start else f['rate']]
    income,f['income_rem']=divmod(f['income_rem']+d['population']*rate['rate']*d['stage']*collection(d['order'])*dt,DAY*100)
    cost,f['cost_rem']=divmod(f['cost_rem']+(0 if f['economy'] else upkeep(d)['total'])*dt,DAY)
    previous_debt=f['arrears']
    available=balance(db,row)+income;due=previous_debt+cost;paid=min(available,due)
    f['arrears']=due-paid;f['collected']+=income;f['paid']+=paid
    cap=2*upkeep(d)['total']
    if f['arrears']>=cap:
        # Dismissing expensive troops may reduce future bills, never erase
        # already incurred debt. Only actual payments reduce the old amount.
        f['arrears']=min(f['arrears'],max(previous_debt,cap));f['economy']=True
    if not f['arrears']:f['economy']=False
    db.connection.execute('UPDATE kingdom_budgets SET balance=? WHERE town=?',(available-paid,row['id']))
    numerator=f['order_rem']+rate['order']*dt
    drift=math.trunc(numerator/DAY);f['order_rem']=numerator-drift*DAY
    if drift>0:
        if d['order']<85:d['order']=min(85,d['order']+drift)
        else:f['order_rem']=0
    elif drift<0:d['order']=max(20,d['order']+drift)
    f['last_at']=until
    if d['order']<30 and f['strike_until']<=until:
        f['strike_until']=until+DAY;f['rate']='holiday';f['next_rate_at']=max(f['next_rate_at'],until+DAY)
        db._kingdom_log(row,'Налоговая забастовка: сутки без налогов. Верни доверие жителей.',until)


def settle_partial(db,row,now):
    f=initialize(row['data'],now)
    if active(db,row):
        accrue(db,row,min(now,deadline(db,row)))
    f['last_at']=max(f['last_at'],now)


def guard(row):
    if row['data'].get('finance',{}).get('arrears'):
        raise ValueError('Есть задолженность по содержанию: новый найм, походы и реформы приостановлены. Пополни бюджет.')


def view(db,row,now):
    f=initialize(row['data'],now);enabled=active(db,row);funds=balance(db,row)
    q=quote(row['data'],now);reserve=q['upkeep']['total'] if enabled else 0
    return dict(balance=funds,active=enabled,rate=f['rate'],rates=RATES,quote=q,
        reserve=reserve,
        arrears=f['arrears'],economy=f['economy'],collected=f['collected'],paid=f['paid'],
        next_rate_at=f['next_rate_at'],strike_until=f['strike_until'],offline_hours=48,
        can_activate=not enabled)


def action(db,row,command,payload,now):
    f=initialize(row['data'],now)
    if command=='tax_activate':
        if active(db,row):raise ValueError('Это поселение уже собирает налоги.')
        if row['data']['military'].get('siege_lock') or row['data']['military']['campaign']:
            raise ValueError('Во время похода или осады налоговую систему не включить.')
        db.connection.execute('INSERT INTO kingdom_tax_towns(town,active_until) VALUES(?,?)',(row['id'],now+48*HOUR))
        f.update(ever_active=True,rate='normal',last_at=now,next_rate_at=now+DAY)
        db._kingdom_log(row,'Включены налоги и содержание. Обычная ставка; списания только из бюджета поселения.',now)
        return 'Налоги включены для этого поселения. Доход и содержание идут через его бюджет; другие поселения не отключаются.'
    if command=='tax_rate':
        if not active(db,row):raise ValueError('Сначала включи налоги для этого поселения.')
        rate=payload.get('rate')
        if not isinstance(rate,str) or rate not in RATES or rate==f['rate']:raise ValueError('Выбери другую доступную ставку.')
        if max(f['next_rate_at'],f['strike_until'])>now:raise ValueError('Ставка меняется раз в сутки; при забастовке нужно дождаться её конца.')
        settle_partial(db,row,now)
        if f['strike_until']>now:return 'Началась налоговая забастовка. Вместо повышения ставки введены каникулы на сутки.'
        f.update(rate=rate,next_rate_at=now+DAY)
        db._kingdom_log(row,'Ставка налогов: '+RATES[rate]['name']+'.',now)
        return 'Новая ставка действует с этого момента. Прошлые часы не пересчитываются.'
    if command!='budget_deposit':raise ValueError('Прямой вывод из казны в кошелёк недоступен.')
    amount=payload.get('amount')
    if type(amount) is not int or not 1<=amount<=2_000_000_000:raise ValueError('Укажи целое число франков от 1 до 2 000 000 000.')
    settle_partial(db,row,now)
    db._forge_spend_francs_locked(row['chat'],row['owner'],amount);credit(db,row,amount)
    notice=f'В бюджет безвозвратно внесено {amount} ₣ из кошелька. Сначала погашена имеющаяся задолженность.'
    db._kingdom_log(row,notice,now)
    return notice
