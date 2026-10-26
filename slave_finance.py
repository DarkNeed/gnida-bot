"""Fictional-franc loans and NPC worker custody. All writes use the economy lock.

No Stars, external payments or real credit. Quotes/receipts are owner-bound;
NPC inventory is not a public player and cannot be captured through old commands.
"""
import hashlib
import json
import random
import re
from slave_finance_commands import FinanceCommandsMixin
from slave_finance_phrases import flavor

NPC_ID = -1
WIN_PERCENT = 17
WAGER_COOLDOWN = 300
LOAN_SECONDS = 72 * 3600
WARNING_GRACE = 3600
BUYOUT_DECAY_SECONDS = 72 * 3600
PASSIVE_HOURLY_PERCENT = 1
VALUES = dict(common=100, uncommon=200, rare=400, epic=800, legendary=1600)


def now():
    from database import utc_timestamp
    return utc_timestamp()


def positive(value, label='Сумма'):
    from database import MAX_FRANC_BALANCE
    if type(value) is not int or not 1 <= value <= MAX_FRANC_BALANCE // 10:
        raise ValueError(label + ': нужно положительное целое число в пределах кошелька.')
    return value


class SlaveFinanceMixin(FinanceCommandsMixin):
    def _init_slave_finance(self):
        self._init_finance_commands()
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS npc_loans(
                id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
                principal INTEGER NOT NULL,total INTEGER NOT NULL,remaining INTEGER NOT NULL CHECK(remaining>=0),
                status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,due_at INTEGER NOT NULL,
                warned_at INTEGER,enforce_after INTEGER,passive_at INTEGER,closed_at INTEGER);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_npc_one_loan ON npc_loans(user_id)
                WHERE status IN ('active','enslaved');
            CREATE TABLE IF NOT EXISTS npc_workers(
                chat_id INTEGER NOT NULL,worker_id INTEGER NOT NULL,base_value INTEGER NOT NULL,
                price INTEGER NOT NULL,reason TEXT NOT NULL,loan_id INTEGER,created_at INTEGER NOT NULL,
                PRIMARY KEY(chat_id,worker_id));
            CREATE TABLE IF NOT EXISTS npc_buyout_premiums(
                chat_id INTEGER NOT NULL,worker_id INTEGER NOT NULL,owner_id INTEGER NOT NULL,
                price INTEGER NOT NULL,bought_at INTEGER NOT NULL,
                PRIMARY KEY(chat_id,worker_id));
            CREATE TABLE IF NOT EXISTS npc_finance_receipts(
                user_id INTEGER NOT NULL,nonce TEXT NOT NULL,request TEXT NOT NULL,result TEXT NOT NULL,
                PRIMARY KEY(user_id,nonce));
            CREATE TABLE IF NOT EXISTS npc_wager_quotes(
                id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,fingerprint TEXT NOT NULL,expires_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS npc_loan_notices(
                loan_id INTEGER NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,sent INTEGER NOT NULL DEFAULT 0,
                next_at INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(loan_id,kind));
            CREATE TRIGGER IF NOT EXISTS npc_custody_no_insert BEFORE INSERT ON ownership
            WHEN NEW.owner_id<>-1 AND EXISTS(SELECT 1 FROM npc_workers WHERE chat_id=NEW.chat_id AND worker_id=NEW.slave_id)
            BEGIN SELECT RAISE(ABORT,'Работник у NPC: сначала выкупи его у работорговца.'); END;
            CREATE TRIGGER IF NOT EXISTS npc_custody_no_transfer BEFORE UPDATE OF owner_id ON ownership
            WHEN NEW.owner_id<>-1 AND EXISTS(SELECT 1 FROM npc_workers WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id)
            BEGIN SELECT RAISE(ABORT,'Работник у NPC: сначала выкупи его у работорговца.'); END;
            CREATE TRIGGER IF NOT EXISTS npc_custody_no_release BEFORE DELETE ON ownership
            WHEN EXISTS(SELECT 1 FROM npc_workers WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id)
            BEGIN SELECT RAISE(ABORT,'Работник у NPC: сначала выкупи его у работорговца.'); END;
            CREATE TRIGGER IF NOT EXISTS npc_premium_owner_changed AFTER UPDATE OF owner_id,acquired_at ON ownership
            BEGIN UPDATE npc_buyout_premiums SET owner_id=NEW.owner_id WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id; END;
            CREATE TRIGGER IF NOT EXISTS npc_premium_released AFTER DELETE ON ownership
            BEGIN DELETE FROM npc_buyout_premiums WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id; END;
            CREATE TRIGGER IF NOT EXISTS npc_loan_paid AFTER UPDATE OF remaining ON npc_loans
            WHEN NEW.remaining=0 AND OLD.remaining>0
            BEGIN
                DELETE FROM npc_workers WHERE loan_id=NEW.id;
                DELETE FROM ownership WHERE owner_id=-1 AND slave_id=NEW.user_id AND chat_id=NEW.chat_id AND OLD.status='enslaved';
                UPDATE npc_loans SET status='paid',closed_at=CAST(strftime('%s','now') AS INTEGER) WHERE id=NEW.id;
                INSERT OR IGNORE INTO npc_loan_notices(loan_id,kind,text)
                    VALUES(NEW.id,'paid','Долг погашен. Удержание дохода прекращено. Текущий статус владения смотри в боте.');
            END;
        ''')
        # Intercept ALL wallet credits, including legacy direct SQL payouts.
        # Nested balance decreases cannot recurse; NEW/OLD remain the outer credit.
        for event, delta, condition in (
            ('INSERT', 'NEW.balance', 'NEW.balance>0'),
            ('UPDATE OF balance', '(NEW.balance-OLD.balance)', 'NEW.balance>OLD.balance'),
        ):
            name = 'insert' if event == 'INSERT' else 'update'
            self.connection.executescript(f'''
                CREATE TRIGGER IF NOT EXISTS npc_debt_credit_{name} AFTER {event} ON franc_balances
                WHEN {condition} AND EXISTS(SELECT 1 FROM npc_loans l JOIN npc_workers w ON w.loan_id=l.id
                    WHERE l.user_id=NEW.user_id AND l.status='enslaved' AND l.remaining>0)
                BEGIN
                    UPDATE franc_balances SET balance=balance-MIN({delta},(SELECT remaining FROM npc_loans
                        WHERE user_id=NEW.user_id AND status='enslaved'))
                        WHERE chat_id=NEW.chat_id AND user_id=NEW.user_id;
                    UPDATE npc_loans SET remaining=MAX(0,remaining-{delta})
                        WHERE user_id=NEW.user_id AND status='enslaved';
                END;
            ''')

    def _npc_reserved_locked(self, chat, worker):
        return self.connection.execute('SELECT 1 FROM npc_workers WHERE chat_id=? AND worker_id=?', (chat, worker)).fetchone() is not None

    def _finance_loan_locked(self, actor):
        return self.connection.execute("SELECT * FROM npc_loans WHERE user_id=? AND status IN ('active','enslaved')", (actor,)).fetchone()

    def _finance_limit_locked(self, actor):
        from database import MAX_FRANC_BALANCE
        balance = sum(r['balance'] for r in self.connection.execute('SELECT balance FROM franc_balances WHERE user_id=?', (actor,)))
        return min(MAX_FRANC_BALANCE // 10, max(2000, balance * 2))

    def _finance_value_locked(self, chat, owner, worker):
        identity = self._trader_identity_public_locked(chat, owner, worker)
        if not identity.get('appraised'):
            return 100
        from slave_identity import TRAITS
        trait = TRAITS[identity['trait_id']]
        bonus = max(trait.get('work_all', 0), max(trait.get('work', {}).values(), default=0))
        return VALUES[identity['rarity']] * (100 + bonus) // 100

    def _finance_quote_locked(self, chat, actor, worker):
        row = self._trader_worker_locked(chat, actor, worker, available=True)
        if self._trader_listed_locked(chat, worker):
            raise ValueError('Сначала сними работника с продажи.')
        value = self._finance_value_locked(chat, actor, worker)
        fingerprint = hashlib.sha256(json.dumps([chat, actor, worker, row['acquired_at'], value], separators=(',', ':')).encode()).hexdigest()
        return dict(worker=worker, name=row['display_name'], value=value, payout=value*5,
                    npc_price=(value*120+99)//100, chance=WIN_PERCENT, fingerprint=fingerprint)

    def _npc_take_locked(self, chat, worker, value, reason, loan_id=None):
        old = self.connection.execute('SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?', (chat, worker)).fetchone()
        if old:
            self._enterprise_settle_owner_locked(chat, old['owner_id'], now())
        self._enterprise_settle_owner_locked(chat, worker, now())
        self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND worker_id=?', (chat, worker))
        self.connection.execute('INSERT OR IGNORE INTO users(chat_id,user_id,username,display_name,last_seen) VALUES(?,-1,NULL,?,0)', (chat, 'Работорговец · NPC'))
        self.connection.execute('''INSERT INTO ownership(chat_id,slave_id,owner_id,acquired_at,last_forced_at)
            VALUES(?,?,-1,?,NULL) ON CONFLICT(chat_id,slave_id) DO UPDATE SET
            owner_id=-1,acquired_at=excluded.acquired_at,last_forced_at=NULL,transfer_priority=0''', (chat, worker, now()))
        self.connection.execute('INSERT INTO npc_workers VALUES(?,?,?,?,?,?,?)',
            (chat, worker, value, (value*120+99)//100, reason, loan_id, now()))

    def _finance_notice_locked(self, loan, kind, text):
        category='warning' if kind.startswith('warn_') else kind
        if category in ('warning','collection'):
            text+='\n\n'+flavor(category)
        self.connection.execute('INSERT OR IGNORE INTO npc_loan_notices(loan_id,kind,text) VALUES(?,?,?)', (loan['id'], kind, text))

    def _finance_tick_locked(self):
        stamp = now()
        for loan in self.connection.execute("SELECT * FROM npc_loans WHERE status IN ('active','enslaved')").fetchall():
            if loan['status'] == 'enslaved':
                hours = max(0, (stamp - loan['passive_at']) // 3600)
                if hours:
                    paid = min(loan['remaining'],hours * max(1, (loan['total'] * PASSIVE_HOURLY_PERCENT + 99)//100))
                    self.connection.execute('UPDATE npc_loans SET passive_at=passive_at+?,remaining=MAX(0,remaining-?) WHERE id=?', (hours*3600, paid, loan['id']))
                continue
            if not self._feature_enabled_locked(loan['chat_id'], 'slavery'):
                continue
            left = loan['due_at'] - stamp
            if left <= 3600:
                self.connection.execute("UPDATE npc_loan_notices SET sent=1 WHERE loan_id=? AND kind='warn_day'",(loan['id'],))
                self._finance_notice_locked(loan, 'warn_hour', f'До взыскания долга осталось не больше часа. Остаток: {loan["remaining"]} ₣. Если срок уже истёк, после этого предупреждения будет час на оплату.')
            elif left <= 86400:
                self._finance_notice_locked(loan, 'warn_day', f'Ростовщик напоминает: долг {loan["remaining"]} ₣. Срок возврата — 72 часа с выдачи. После срока будут взысканы рабы, а при нехватке — ты сам. Управление: Владения → Торговец.')
            if left > 0 or loan['warned_at'] is None or stamp < (loan['enforce_after'] or loan['due_at']):
                continue
            remaining = loan['remaining']
            # Do not mint money or pay the debtor for stock sent to the creditor.
            workers = self.connection.execute('SELECT chat_id,slave_id FROM ownership WHERE owner_id=? ORDER BY (chat_id=?) DESC,acquired_at,chat_id,slave_id', (loan['user_id'],loan['chat_id'])).fetchall()
            for worker in workers:
                if not self._feature_enabled_locked(worker['chat_id'], 'slavery'):
                    continue
                value = self._finance_value_locked(worker['chat_id'], loan['user_id'], worker['slave_id'])
                self._npc_take_locked(worker['chat_id'], worker['slave_id'], value, 'collection')
                surplus = max(0,value-remaining)
                remaining = max(0, remaining-value)
                self.connection.execute('UPDATE npc_loans SET remaining=? WHERE id=?', (remaining, loan['id']))
                if surplus:
                    from database import MAX_FRANC_BALANCE
                    room=max(0,MAX_FRANC_BALANCE-self._trader_balance_locked(worker['chat_id'],loan['user_id']))
                    self._add_francs_locked(worker['chat_id'],loan['user_id'],min(room,surplus))
                if not remaining:
                    break
            if remaining:
                # Existing third-party ownership is not confiscated: wait, rather
                # than taking someone else's worker to pay this borrower's debt.
                owner = self.connection.execute('SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?', (loan['chat_id'], loan['user_id'])).fetchone()
                if owner:
                    continue
                value = max(100, remaining)
                self._npc_take_locked(loan['chat_id'], loan['user_id'], value, 'debtor', loan['id'])
                self.connection.execute("UPDATE npc_loans SET status='enslaved',passive_at=? WHERE id=?", (stamp, loan['id']))
            self._finance_notice_locked(loan, 'collection', 'Долг просрочен: проведено взыскание. '+(
                'Рабов забрал NPC, остаток долга переведён в долговое рабство. Все поступления погашают долг, дополнительно списывается 1% исходного долга в час. Выкуп доступен в торговце.' if remaining else
                'Рабов на сумму долга забрал NPC. Долг закрыт; превышение оценки над долгом возвращено в кошелёк.'))

    def _finance_buyout_cost_locked(self, chat, worker, owner):
        from database import BUYOUT_COST_FRANCS
        stock = self.connection.execute('SELECT * FROM npc_workers WHERE chat_id=? AND worker_id=?', (chat, worker)).fetchone()
        if stock:
            if stock['loan_id']:
                remaining = self.connection.execute('SELECT remaining FROM npc_loans WHERE id=?', (stock['loan_id'],)).fetchone()['remaining']
                return max(BUYOUT_COST_FRANCS, (remaining*120+99)//100)
            return stock['price']
        premium = self.connection.execute('SELECT * FROM npc_buyout_premiums WHERE chat_id=? AND worker_id=? AND owner_id=?', (chat, worker, owner)).fetchone()
        if not premium:
            return BUYOUT_COST_FRANCS
        seconds = max(0, BUYOUT_DECAY_SECONDS - max(0, now()-premium['bought_at']))
        return BUYOUT_COST_FRANCS + (max(0,premium['price']-BUYOUT_COST_FRANCS)*seconds + BUYOUT_DECAY_SECONDS-1)//BUYOUT_DECAY_SECONDS

    def _finance_view_locked(self, chat, actor):
        loan = self._finance_loan_locked(actor)
        offers = []
        for stock in self.connection.execute('''SELECT w.*,u.display_name FROM npc_workers w
            LEFT JOIN users u ON u.chat_id=w.chat_id AND u.user_id=w.worker_id
            WHERE w.chat_id=? ORDER BY w.created_at DESC,worker_id LIMIT 50''', (chat,)):
            offers.append(dict(worker=stock['worker_id'],name=stock['display_name'] or str(stock['worker_id']),
                               price=self._finance_buyout_cost_locked(chat,stock['worker_id'],NPC_ID),reason=stock['reason']))
        return dict(loan=dict(loan) if loan else None,limit=self._finance_limit_locked(actor),offers=offers,
                    chance=WIN_PERCENT,multiplier=5,cooldown=WAGER_COOLDOWN,loan_hours=72,interest_percent=15,
                    passive_hourly_percent=PASSIVE_HOURLY_PERCENT,decay_hours=72,
                    notices=[r['text'] for r in self.connection.execute('''SELECT n.text FROM npc_loan_notices n JOIN npc_loans l
                        ON l.id=n.loan_id WHERE l.user_id=? ORDER BY n.rowid DESC LIMIT 3''',(actor,))])

    async def finance_action(self, chat, actor, body, rng=None):
        from database import MAX_FRANC_BALANCE
        if type(chat) is not int or chat>=0 or type(actor) is not int or actor<=0 or not isinstance(body,dict):
            raise ValueError('Некорректный запрос.')
        kind = body.get('action')
        if kind not in ('finance_quote','finance_wager','finance_borrow','finance_repay','finance_buy'):
            raise ValueError('Неизвестное действие ростовщика.')
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'slavery')
                if not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?', (chat,actor)).fetchone():
                    raise ValueError('Участник не найден в чате.')
                self._finance_tick_locked()
                if kind=='finance_quote':
                    quote = self._finance_quote_locked(chat,actor,body.get('worker'))
                    import secrets
                    offer = secrets.token_hex(16)
                    self.connection.execute('DELETE FROM npc_wager_quotes WHERE expires_at<=?', (now(),))
                    self.connection.execute('INSERT INTO npc_wager_quotes VALUES(?,?,?,?,?,?)', (offer,actor,chat,quote['worker'],quote['fingerprint'],now()+300))
                    return dict(quote={k:v for k,v in quote.items() if k!='fingerprint'},offer=offer)
                nonce = body.get('nonce')
                if body.get('confirm') is not True or not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',nonce):
                    raise ValueError('Подтверди действие заново.')
                request = json.dumps(dict(chat=chat,body=body),sort_keys=True,ensure_ascii=False)
                receipt = self.connection.execute('SELECT * FROM npc_finance_receipts WHERE user_id=? AND nonce=?',(actor,nonce)).fetchone()
                if receipt:
                    if receipt['request']!=request:
                        raise ValueError('Подтверждение относится к другому действию.')
                    return json.loads(receipt['result'])
                if kind=='finance_wager':
                    if not isinstance(body.get('offer'),str) or not re.fullmatch(r'[0-9a-f]{32}',body['offer']):
                        raise ValueError('Некорректное предложение ставки.')
                    offer = self.connection.execute('SELECT * FROM npc_wager_quotes WHERE id=? AND user_id=? AND chat_id=?',(body.get('offer'),actor,chat)).fetchone()
                    if not offer or offer['expires_at']<=now():
                        raise ValueError('Предложение истекло. Выбери раба заново.')
                    quote = self._finance_quote_locked(chat,actor,offer['worker_id'])
                    if quote['fingerprint']!=offer['fingerprint']:
                        raise ValueError('Владение или оценка изменились. Проверь ставку заново.')
                    limit = self._deposit_limit_locked(actor)
                    if limit['cooldown_until']>now():
                        raise ValueError(f'Казино отдыхает: ещё {limit["cooldown_until"]-now()} сек. Кулдаун общий с депом франков.')
                    self._enterprise_settle_owner_locked(chat,actor,now())
                    if self._trader_balance_locked(chat,actor)>MAX_FRANC_BALANCE-quote['payout']:
                        raise ValueError('Возможная выплата превысит предел кошелька.')
                    won = (rng or random.SystemRandom()).randrange(100)<WIN_PERCENT
                    if won:
                        self._add_francs_locked(chat,actor,quote['payout'])
                    else:
                        self._npc_take_locked(chat,quote['worker'],quote['value'],'wager')
                    self.connection.execute('UPDATE franc_deposit_limits SET cooldown_until=?,cooldown_warned=0 WHERE user_id=?',(now()+WAGER_COOLDOWN,actor))
                    self.connection.execute('DELETE FROM npc_wager_quotes WHERE id=?',(offer['id'],))
                    result = dict(won=won,worker=quote['worker'],stake_value=quote['value'],chance=WIN_PERCENT,created_at=now(),payout=quote['payout'] if won else 0,
                        notice=(f'+{quote["payout"]} ₣, работник остаётся у тебя.\n\n'+flavor('win') if won else
                                f'{quote["name"]} теперь у NPC. Выкуп: {quote["npc_price"]} ₣.\n\n'+flavor('loss')))
                elif kind=='finance_borrow':
                    amount = positive(body.get('amount'))
                    if self._finance_loan_locked(actor):
                        raise ValueError('Сначала закрой текущий долг. Он общий для всех чатов и персонажей.')
                    if self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?',(chat,actor)).fetchone():
                        raise ValueError('Для нового займа нужно быть свободным в выбранном чате.')
                    if amount>self._finance_limit_locked(actor):
                        raise ValueError('Лимит изменился. Обнови размер займа.')
                    if self._trader_balance_locked(chat,actor)>MAX_FRANC_BALANCE-amount:
                        raise ValueError('Предел кошелька.')
                    total = amount+(amount*15+99)//100
                    self.connection.execute('INSERT INTO npc_loans(user_id,chat_id,principal,total,remaining,created_at,due_at) VALUES(?,?,?,?,?,?,?)',
                        (actor,chat,amount,total,total,now(),now()+LOAN_SECONDS))
                    self._add_francs_locked(chat,actor,amount)
                    result = dict(notice=f'Получено {amount} ₣. Вернуть {total} ₣ за 72 часа. Переплата фиксированная, проценты на проценты не растут. Деньги можно переводить и депать.\n\n'+flavor('borrow'))
                elif kind=='finance_repay':
                    loan = self._finance_loan_locked(actor)
                    amount = positive(body.get('amount'))
                    if not loan or type(body.get('loan')) is not int or body['loan']!=loan['id']:
                        raise ValueError('Этот долг уже закрыт или изменился.')
                    if amount>loan['remaining']:
                        raise ValueError('Остаток долга меньше. Обнови сумму.')
                    self._trader_debit_locked(chat,actor,amount)
                    self.connection.execute('UPDATE npc_loans SET remaining=remaining-? WHERE id=?',(amount,loan['id']))
                    result = dict(notice=f'В счёт долга внесено {amount} ₣. Осталось {loan["remaining"]-amount} ₣.\n\n'+flavor('repay'))
                else:
                    worker = positive(body.get('worker'),'Работник')
                    stock = self.connection.execute('SELECT * FROM npc_workers WHERE chat_id=? AND worker_id=?',(chat,worker)).fetchone()
                    if not stock:
                        raise ValueError('Работник уже недоступен у NPC.')
                    price = self._finance_buyout_cost_locked(chat,worker,NPC_ID)
                    if type(body.get('price')) is not int or price!=body['price']:
                        raise ValueError('Цена изменилась. Обнови предложение.')
                    if worker!=actor and self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?',(chat,actor)).fetchone():
                        raise ValueError('Покупатель сам находится в рабстве.')
                    self._trader_debit_locked(chat,actor,price)
                    self.connection.execute('DELETE FROM npc_workers WHERE chat_id=? AND worker_id=?',(chat,worker))
                    if worker==actor:
                        self.connection.execute('DELETE FROM ownership WHERE chat_id=? AND slave_id=? AND owner_id=-1',(chat,worker))
                    else:
                        status = self._transfer_slave_locked(chat,NPC_ID,worker,actor)
                        if status!='transferred':
                            raise ValueError('Покупка недоступна: '+status)
                        if stock['reason']=='debtor':
                            self.connection.execute('INSERT OR REPLACE INTO npc_buyout_premiums VALUES(?,?,?,?,?)',(chat,worker,actor,price,now()))
                    if stock['loan_id']:
                        self.connection.execute('UPDATE npc_loans SET remaining=0 WHERE id=?',(stock['loan_id'],))
                    result = dict(notice=f'Выкуп у NPC: {price} ₣. '+('Теперь ты свободен.' if worker==actor else
                        'Работник теперь принадлежит тебе. '+('Его цена самостоятельного выкупа снизится до 100 ₣ за 72 часа.' if stock['reason']=='debtor' else '')))
                    result['notice']+='\n\n'+flavor('buy')
                self.connection.execute('INSERT INTO npc_finance_receipts VALUES(?,?,?,?)',(actor,nonce,request,json.dumps(result,ensure_ascii=False)))
                return result

    async def finance_wager_members(self, chat, actor, body):
        """Fresh membership for settlement, not just when the quote was opened."""
        async with self._lock:
            if not isinstance(body.get('offer'),str) or not re.fullmatch(r'[0-9a-f]{32}',body['offer']):
                raise ValueError('Некорректное предложение ставки.')
            if isinstance(body.get('nonce'),str) and self.connection.execute(
                'SELECT 1 FROM npc_finance_receipts WHERE user_id=? AND nonce=?',(actor,body['nonce'])).fetchone():
                return []  # Receipt identity is checked again in the transaction.
            quote=self.connection.execute('SELECT worker_id FROM npc_wager_quotes WHERE id=? AND chat_id=? AND user_id=?',
                (body.get('offer'),chat,actor)).fetchone()
            if not quote:
                raise ValueError('Предложение истекло или относится к другому владельцу.')
            return [quote['worker_id']]

    async def finance_sweep(self):
        async with self._lock:
            with self.connection:
                self._finance_tick_locked()
                rows = self.connection.execute('''SELECT n.*,l.user_id,l.chat_id FROM npc_loan_notices n JOIN npc_loans l
                    ON l.id=n.loan_id WHERE n.sent=0 AND n.next_at<=?
                    AND (n.kind NOT LIKE 'warn_%' OR l.status='active') ORDER BY n.rowid LIMIT 20''',(now(),)).fetchall()
                for row in rows:
                    self.connection.execute('UPDATE npc_loan_notices SET next_at=? WHERE loan_id=? AND kind=?',(now()+300,row['loan_id'],row['kind']))
                return [dict(r) for r in rows]

    async def slave_buyout_cost(self, chat, worker, owner):
        async with self._lock:
            return self._finance_buyout_cost_locked(chat,worker,owner)

    async def finance_notice_sent(self, ident, kind):
        async with self._lock:
            with self.connection:
                self.connection.execute('UPDATE npc_loan_notices SET sent=1 WHERE loan_id=? AND kind=?',(ident,kind))
                if kind.startswith('warn_'):
                    self.connection.execute('''UPDATE npc_loans SET warned_at=COALESCE(warned_at,?),
                        enforce_after=COALESCE(enforce_after,MAX(due_at,?)) WHERE id=?''',(now(),now()+WARNING_GRACE,ident))
