"""Chat-local trader: paid reports, escrow-free market and liberation orders.

Every mutation shares the economy lock/transaction. A listing never owns a worker;
ownership changes invalidate it, including transfer-away-and-back scenarios.
"""

import json
import re
from datetime import datetime

APPRAISAL_PRICE = 50
LISTING_TTL = 86400
MAX_LISTINGS = 5
DELIVERY_COOLDOWN = 7 * 86400
ORDERS = {
    'active': dict(name='Смена на рассвете', count=1, reward=70, active=True, power=0),
    'crew': dict(name='Новая команда', count=2, reward=160, active=True, power=0),
    'veteran': dict(name='Проводник экспедиции', count=1, reward=140, active=False, power=78),
}


def now():
    from database import utc_timestamp
    return utc_timestamp()


def day():
    from database import BUSINESS_STATS_TZ
    return datetime.fromtimestamp(now(), BUSINESS_STATS_TZ).date().isoformat()


class SlaveTraderMixin:
    def _init_slave_trader(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS slave_trader_reports(
                chat_id INTEGER NOT NULL,owner_id INTEGER NOT NULL,worker_id INTEGER NOT NULL,
                acquired_at INTEGER NOT NULL,created_at INTEGER NOT NULL,report_json TEXT NOT NULL,
                PRIMARY KEY(chat_id,owner_id,worker_id));
            CREATE TABLE IF NOT EXISTS slave_trader_listings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,seller_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,acquired_at INTEGER NOT NULL,price INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
                buyer_id INTEGER,sold_at INTEGER);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trader_active_worker
                ON slave_trader_listings(chat_id,worker_id) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_trader_seller ON slave_trader_listings(seller_id,status);
            CREATE INDEX IF NOT EXISTS idx_trader_market ON slave_trader_listings(chat_id,status,id);
            CREATE TABLE IF NOT EXISTS slave_trader_receipts(
                actor_id INTEGER NOT NULL,nonce TEXT NOT NULL,request_json TEXT NOT NULL,
                result_json TEXT NOT NULL,PRIMARY KEY(actor_id,nonce));
            CREATE TABLE IF NOT EXISTS slave_trader_contracts(
                actor_id INTEGER NOT NULL,income_day TEXT NOT NULL,chat_id INTEGER NOT NULL,
                order_id TEXT NOT NULL,created_at INTEGER NOT NULL,result_json TEXT NOT NULL,
                PRIMARY KEY(actor_id,income_day));
            CREATE TABLE IF NOT EXISTS slave_trader_deliveries(
                worker_id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
                delivered_at INTEGER NOT NULL);
            CREATE TRIGGER IF NOT EXISTS trader_ownership_deleted AFTER DELETE ON ownership
            BEGIN
                UPDATE slave_trader_listings SET status='cancelled'
                WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id AND status='active';
                DELETE FROM slave_trader_reports WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id;
            END;
            CREATE TRIGGER IF NOT EXISTS trader_ownership_changed
            AFTER UPDATE OF owner_id,acquired_at ON ownership
            WHEN NEW.owner_id<>OLD.owner_id OR NEW.acquired_at<>OLD.acquired_at
            BEGIN
                UPDATE slave_trader_listings SET status='cancelled'
                WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id AND status='active';
                DELETE FROM slave_trader_reports WHERE chat_id=OLD.chat_id AND worker_id=OLD.slave_id;
            END;
        ''')

    def _trader_expire_locked(self):
        self.connection.execute("UPDATE slave_trader_listings SET status='expired' WHERE status='active' AND expires_at<=?", (now(),))

    def _trader_listed_locked(self, chat, worker):
        return self.connection.execute("SELECT 1 FROM slave_trader_listings WHERE chat_id=? AND worker_id=? AND status='active' AND expires_at>?", (chat, worker, now())).fetchone() is not None

    def _trader_worker_locked(self, chat, owner, worker, available=False):
        if type(worker) is not int or worker<=0 or worker==owner:
            raise ValueError('Выбери своего работника.')
        row=self.connection.execute('''SELECT o.*,u.display_name,u.username,u.last_seen FROM ownership o
            JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
            WHERE o.chat_id=? AND o.owner_id=? AND o.slave_id=?''', (chat,owner,worker)).fetchone()
        if not row:raise ValueError('Этот работник больше тебе не принадлежит в выбранном чате.')
        if available and (self.connection.execute("SELECT 1 FROM slave_recovery_events WHERE chat_id=? AND slave_id=? AND status IN ('announcing','pending','playing')",(chat,worker)).fetchone() or
                          self.connection.execute('SELECT 1 FROM slave_expedition_members WHERE user_id=? AND active=1',(worker,)).fetchone()):
            raise ValueError('Работник пропал или находится в экспедиции. Сначала дождись его возвращения.')
        return row

    def _trader_report_locked(self, chat, owner, worker):
        from database import BUSINESS_ACTIVE_SECONDS, BUSINESS_CONFIG
        from enterprises import CATALOG
        r=self._trader_worker_locked(chat,owner,worker)
        p=self._expedition_source_locked(chat,worker)
        active=r['last_seen'] is not None and now()-BUSINESS_ACTIVE_SECONDS<=r['last_seen']<=now()
        rates=[dict(kind=k,name=CATALOG[k]['name'],active_rate=round(c['owner_per_producer']*self._slave_work_percent_locked(worker,k,now())/100,2),
                    inactive_rate=c['inactive_owner_per_producer']) for k,c in BUSINESS_CONFIG.items() if k in CATALOG]
        best=max((c['active_rate'] if active else c['inactive_rate'] for c in rates),default=1)
        low=max(20,round(best*24+p['power']*.4))
        return dict(worker_id=worker,name=r['display_name'] or r['username'] or str(worker),created_at=now(),
                    active=active,last_seen=r['last_seen'],power=p['power'],level=p['level'],class_name=p['class_name'],
                    rates=rates,price_low=low,price_high=round(low*1.6),identity=p['identity'])

    def _trader_identity_public_locked(self,chat,owner,worker,identity=None):
        """Paid knowledge is bound to the current owner/chat/acquisition.

        Keep real modifiers internal for economy/expedition calculations. Merely
        fetching a roster or opening a passport must never disclose the rarity.
        """
        identity=identity if identity is not None else self._slave_identity_locked(worker)
        assessed=self.connection.execute('''SELECT 1 FROM slave_trader_reports r JOIN ownership o
            ON o.chat_id=r.chat_id AND o.owner_id=r.owner_id AND o.slave_id=r.worker_id AND o.acquired_at=r.acquired_at
            WHERE r.chat_id=? AND r.owner_id=? AND r.worker_id=?''',(chat,owner,worker)).fetchone() is not None
        if assessed:return dict(identity,appraised=True)
        return dict(appraised=False,permanent=True,**{k:identity[k] for k in
            ('trait_id','trait_name','trait_flavor','trait_effect') if k in identity})

    def _trader_view_locked(self, chat, actor):
        self._trader_expire_locked()
        listings=[]
        # Own offers first; a bounded public page avoids unbounded Mini App payloads.
        for r in self.connection.execute('''SELECT l.*,u.display_name,u.username,s.display_name AS seller_name
            FROM slave_trader_listings l JOIN ownership o ON o.chat_id=l.chat_id AND o.slave_id=l.worker_id
            AND o.owner_id=l.seller_id AND o.acquired_at=l.acquired_at
            JOIN users u ON u.chat_id=l.chat_id AND u.user_id=l.worker_id
            LEFT JOIN users s ON s.chat_id=l.chat_id AND s.user_id=l.seller_id
            WHERE l.chat_id=? AND l.status='active' ORDER BY (l.seller_id=?) DESC,l.id DESC LIMIT 50''',(chat,actor)):
            listings.append(dict(id=r['id'],worker_id=r['worker_id'],seller_id=r['seller_id'],
                name=r['display_name'] or r['username'] or str(r['worker_id']),seller_name=r['seller_name'] or str(r['seller_id']),
                price=r['price'],fee=(r['price']+9)//10,expires_at=r['expires_at'],
                identity=self._trader_identity_public_locked(chat,r['seller_id'],r['worker_id'])))
        reports=[json.loads(r['report_json']) for r in self.connection.execute('''SELECT r.report_json
            FROM slave_trader_reports r JOIN ownership o ON o.chat_id=r.chat_id AND o.slave_id=r.worker_id
            AND o.owner_id=r.owner_id AND o.acquired_at=r.acquired_at
            WHERE r.chat_id=? AND r.owner_id=? ORDER BY r.created_at DESC LIMIT 20''',(chat,actor))]
        completed=self.connection.execute('SELECT result_json FROM slave_trader_contracts WHERE actor_id=? AND income_day=?',(actor,day())).fetchone()
        return dict(appraisal_price=APPRAISAL_PRICE,commission=10,max_listings=MAX_LISTINGS,
                    listing_hours=24,listings=listings,reports=reports,
                    orders=[dict(id=k,**v) for k,v in ORDERS.items()],day=day(),identity_rules=self._trader_identity_rules_locked(),
                    completed=json.loads(completed['result_json']) if completed else None,
                    finance=self._finance_view_locked(chat,actor))

    def _trader_identity_rules_locked(self):
        from slave_identity import RARITIES,TRAITS,RARITY_CHANCES
        return dict(rarities=[dict(id=k,**v) for k,v in RARITIES.items()],traits=[dict(id=k,**v) for k,v in TRAITS.items()],
                    chances=list(RARITY_CHANCES),permanent=True)

    async def trader_listing_members(self, chat, listing_id):
        if type(listing_id) is not int:raise ValueError('Некорректное предложение.')
        async with self._lock:
            r=self.connection.execute('SELECT seller_id,worker_id FROM slave_trader_listings WHERE chat_id=? AND id=?',(chat,listing_id)).fetchone()
            if not r:raise ValueError('Предложение не найдено в этом чате.')
            return list(r)

    async def trader_action(self, chat, actor, body):
        """Only called after fresh Telegram membership checks at the HTTP boundary."""
        from database import MAX_FRANC_BALANCE, BUSINESS_ACTIVE_SECONDS
        if not isinstance(body,dict) or body.get('confirm') is not True:
            raise ValueError('Сначала подтверди действие работорговца.')
        nonce=body.get('nonce')
        if not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',nonce):
            raise ValueError('Обнови подтверждение действия.')
        kind=body.get('action')
        if kind not in ('trader_appraise','trader_list','trader_cancel','trader_buy','trader_order'):
            raise ValueError('Неизвестное действие работорговца.')
        request=json.dumps(dict(chat=chat,**{k:v for k,v in body.items() if k not in ('nonce','confirm')}),sort_keys=True,ensure_ascii=False)
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'slavery')
                receipt=self.connection.execute('SELECT * FROM slave_trader_receipts WHERE actor_id=? AND nonce=?',(actor,nonce)).fetchone()
                if receipt:
                    if receipt['request_json']!=request:raise ValueError('Это подтверждение относится к другому действию.')
                    return json.loads(receipt['result_json'])
                self._expedition_finish_due_locked();self._trader_expire_locked()
                result={}
                if kind in ('trader_appraise','trader_list','trader_order'):
                    self._holdings_check_locked(chat,actor,body.get('revision'))
                if kind=='trader_appraise':
                    worker=body.get('worker');r=self._trader_worker_locked(chat,actor,worker)
                    saved=self.connection.execute('SELECT * FROM slave_trader_reports WHERE chat_id=? AND owner_id=? AND worker_id=? AND acquired_at=?',(chat,actor,worker,r['acquired_at'])).fetchone()
                    if saved and body.get('refresh') is not True:
                        result=dict(notice='Сохранённая оценка открыта бесплатно.',report=json.loads(saved['report_json']))
                    else:
                        report=self._trader_report_locked(chat,actor,worker)
                        self._enterprise_settle_owner_locked(chat,actor,now())
                        self._trader_debit_locked(chat,actor,APPRAISAL_PRICE)
                        self.connection.execute('INSERT OR REPLACE INTO slave_trader_reports VALUES(?,?,?,?,?,?)',(chat,actor,worker,r['acquired_at'],now(),json.dumps(report,ensure_ascii=False)))
                        result=dict(notice='Оценка сохранена. Списано 50 ₣.',report=report)
                elif kind=='trader_list':
                    worker=body.get('worker');price=body.get('price')
                    if type(price) is not int or not 10<=price<=100000:raise ValueError('Цена: от 10 до 100 000 франков.')
                    r=self._trader_worker_locked(chat,actor,worker,available=True)
                    if self._trader_listed_locked(chat,worker):raise ValueError('Этот работник уже выставлен на продажу.')
                    count=self.connection.execute("SELECT COUNT(*) FROM slave_trader_listings WHERE seller_id=? AND status='active'",(actor,)).fetchone()[0]
                    if count>=MAX_LISTINGS:raise ValueError('Одновременно можно выставить пять работников во всех чатах.')
                    self.connection.execute('''INSERT INTO slave_trader_listings(chat_id,seller_id,worker_id,acquired_at,price,created_at,expires_at)
                        VALUES(?,?,?,?,?,?,?)''',(chat,actor,worker,r['acquired_at'],price,now(),now()+LISTING_TTL))
                    result=dict(notice='Предложение действует 24 часа. Рабочее место сохранено; экспедиции временно недоступны.')
                elif kind in ('trader_cancel','trader_buy'):
                    listing=body.get('listing')
                    if type(listing) is not int:raise ValueError('Некорректное предложение.')
                    r=self.connection.execute("SELECT * FROM slave_trader_listings WHERE chat_id=? AND id=? AND status='active'",(chat,listing)).fetchone()
                    if not r:raise ValueError('Предложение уже недоступно. Обнови рынок.')
                    if kind=='trader_cancel':
                        if r['seller_id']!=actor:raise ValueError('Это не твоё предложение.')
                        self.connection.execute("UPDATE slave_trader_listings SET status='cancelled' WHERE id=?",(listing,))
                        result=dict(notice='Предложение снято с продажи.')
                    else:
                        if r['seller_id']==actor or r['worker_id']==actor:raise ValueError('Нельзя купить собственное предложение или самого себя.')
                        if type(body.get('price')) is not int or body['price']!=r['price']:raise ValueError('Проверь цену заново.')
                        owned=self._trader_worker_locked(chat,r['seller_id'],r['worker_id'],available=True)
                        if owned['acquired_at']!=r['acquired_at']:raise ValueError('Владелец работника изменился.')
                        if not self.connection.execute('SELECT 1 FROM users WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone():raise ValueError('Покупатель не найден в этом чате.')
                        for owner in (actor,r['seller_id']):self._enterprise_settle_owner_locked(chat,owner,now())
                        fee=(r['price']+9)//10;net=r['price']-fee
                        balance=self._trader_balance_locked(chat,r['seller_id'])
                        if balance>MAX_FRANC_BALANCE-net:raise ValueError('У продавца достигнут предел кошелька.')
                        self._trader_debit_locked(chat,actor,r['price'])
                        status=self._transfer_slave_locked(chat,r['seller_id'],r['worker_id'],actor)
                        if status!='transferred':raise ValueError('Покупка недоступна: покупатель сам в рабстве или не может владеть рабами.')
                        self._add_francs_locked(chat,r['seller_id'],net)
                        # The ownership trigger cancelled this listing; mark this exact transaction sold.
                        self.connection.execute("UPDATE slave_trader_listings SET status='sold',buyer_id=?,sold_at=? WHERE id=?",(actor,now(),listing))
                        result=dict(notice=f'Работник куплен за {r["price"]} ₣. Продавцу — {net} ₣; комиссия — {fee} ₣.')
                else:
                    order=body.get('order');cfg=ORDERS.get(order) if isinstance(order,str) else None
                    users=body.get('users')
                    if not cfg or not isinstance(users,list) or len(users)!=cfg['count'] or any(type(u) is not int or u<=0 for u in users) or len(set(users))!=len(users):
                        raise ValueError('Выбери нужное число разных работников для заказа.')
                    if self.connection.execute('SELECT 1 FROM slave_trader_contracts WHERE actor_id=? AND income_day=?',(actor,day())).fetchone():raise ValueError('Заказ сегодня уже выполнен. Лимит общий для всех чатов, новый день — по Москве.')
                    for worker in users:
                        r=self._trader_worker_locked(chat,actor,worker,available=True)
                        if now()-r['acquired_at']<86400:raise ValueError('Работник должен принадлежать тебе не менее 24 часов.')
                        if self._trader_listed_locked(chat,worker):raise ValueError('Сначала сними работника с продажи.')
                        recent=self.connection.execute('SELECT delivered_at FROM slave_trader_deliveries WHERE worker_id=?',(worker,)).fetchone()
                        if recent and recent['delivered_at']+DELIVERY_COOLDOWN>now():raise ValueError('Этот работник уже участвовал в заказе за последние семь дней. Лимит общий для всех владельцев и чатов.')
                        if cfg['active'] and (r['last_seen'] is None or not now()-BUSINESS_ACTIVE_SECONDS<=r['last_seen']<=now()):raise ValueError('Для этого заказа нужен работник, активный за последние 24 часа.')
                        if cfg['power'] and self._expedition_source_locked(chat,worker)['power']<cfg['power']:raise ValueError(f'Нужна сила экспедиции не менее {cfg["power"]}.')
                    self._enterprise_settle_owner_locked(chat,actor,now())
                    if self._trader_balance_locked(chat,actor)>MAX_FRANC_BALANCE-cfg['reward']:raise ValueError('Достигнут предел кошелька.')
                    self._settle_materials_locked(chat,actor)
                    for worker in users:
                        self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND worker_id=?',(chat,worker))
                        self.connection.execute('DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(chat,actor,worker))
                        self.connection.execute('INSERT OR REPLACE INTO slave_trader_deliveries VALUES(?,?,?,?)',(worker,actor,chat,now()))
                    net,tax=self._credit_business_income_locked(chat,actor,day(),cfg['reward'])
                    result=dict(notice=f'Заказ выполнен. Работники освобождены. Получено {net} ₣, налог — {tax} ₣.',francs=net,tax=tax,users=users,chat_id=chat)
                    self.connection.execute('INSERT INTO slave_trader_contracts VALUES(?,?,?,?,?,?)',(actor,day(),chat,order,now(),json.dumps(result,ensure_ascii=False)))
                self.connection.execute('INSERT INTO slave_trader_receipts VALUES(?,?,?,?)',(actor,nonce,request,json.dumps(result,ensure_ascii=False)))
                return result

    def _trader_balance_locked(self, chat, actor):
        r=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone()
        return r['balance'] if r else 0

    def _trader_debit_locked(self, chat, actor, amount):
        paid=self.connection.execute('UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?',(amount,now(),chat,actor,amount))
        if not paid.rowcount:raise ValueError('Недостаточно франков в кошельке выбранного чата.')
