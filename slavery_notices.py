"""Durable private delivery; Telegram failures never undo economic actions."""
import json

RETRY_SECONDS=300
BLOCKED_RETRY_SECONDS=86400


def now():
    from database import utc_timestamp
    return utc_timestamp()


class SlaveryNoticesMixin:
    def _init_slavery_notices(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS workforce_delivery_attempts(
                delivery_key TEXT PRIMARY KEY,next_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS slave_buyout_notices(
                id INTEGER PRIMARY KEY AUTOINCREMENT,recipient INTEGER NOT NULL,
                chat INTEGER NOT NULL,worker INTEGER NOT NULL,buyer INTEGER NOT NULL,
                amount INTEGER NOT NULL,kind TEXT NOT NULL,details TEXT NOT NULL,
                created INTEGER NOT NULL,sent INTEGER NOT NULL DEFAULT 0,
                next_at INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS slave_buyout_notices_due ON slave_buyout_notices(sent,next_at);
        ''')

    @staticmethod
    def _workforce_delivery_key(row):
        return f"warning:{row['chat']}:{row['owner']}:{row['created']}" if row['kind']=='warning' else 'incident:'+row['id']

    def _workforce_claim_locked(self,row):
        return bool(self.connection.execute('''INSERT INTO workforce_delivery_attempts VALUES(?,?)
            ON CONFLICT(delivery_key) DO UPDATE SET next_at=excluded.next_at
            WHERE workforce_delivery_attempts.next_at<=?''',
            (self._workforce_delivery_key(row),now()+RETRY_SECONDS,now())).rowcount)

    async def workforce_delivery_failed(self,row,*,delay=RETRY_SECONDS):
        async with self._lock:
            with self.connection:
                self.connection.execute('UPDATE workforce_delivery_attempts SET next_at=? WHERE delivery_key=?',
                    (now()+max(RETRY_SECONDS,int(delay)),self._workforce_delivery_key(row)))

    def _queue_slave_buyout_notice_locked(self,chat,owner,worker,buyer,amount,kind='freedom'):
        if owner<=0:return  # The system trader is not a Telegram recipient.
        def name(user):
            row=self.connection.execute('SELECT display_name,username FROM users WHERE chat_id=? AND user_id=?',(chat,user)).fetchone()
            return ((row['display_name'] or row['username']) if row else None) or str(user)
        title=self.connection.execute('SELECT title FROM chats WHERE chat_id=?',(chat,)).fetchone()
        details=dict(worker_name=name(worker),buyer_name=name(buyer),chat_title=(title['title'] if title else None) or str(chat))
        self.connection.execute('''INSERT INTO slave_buyout_notices(recipient,chat,worker,buyer,amount,kind,details,created)
            VALUES(?,?,?,?,?,?,?,?)''',(owner,chat,worker,buyer,amount,kind,json.dumps(details,ensure_ascii=False),now()))

    async def slave_buyout_notifications(self):
        async with self._lock:
            with self.connection:
                rows=self.connection.execute('SELECT * FROM slave_buyout_notices WHERE sent=0 AND next_at<=? ORDER BY id LIMIT 20',(now(),)).fetchall()
                for r in rows:self.connection.execute('UPDATE slave_buyout_notices SET next_at=? WHERE id=?',(now()+RETRY_SECONDS,r['id']))
                return [dict(r) for r in rows]

    async def slave_buyout_notification_result(self,ident,*,delivered=False,delay=RETRY_SECONDS):
        async with self._lock:
            with self.connection:
                self.connection.execute('UPDATE slave_buyout_notices SET sent=?,next_at=? WHERE id=? AND sent=0',
                    (int(delivered),now()+max(RETRY_SECONDS,int(delay)),ident))
