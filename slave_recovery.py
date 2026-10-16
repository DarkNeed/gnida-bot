"""Persisted code-breaking recovery game with a publication-based deadline."""

import json
import random
from datetime import datetime, timedelta, timezone

RECOVERY_THRESHOLD = 20
RECOVERY_COOLDOWN = 86400
RECOVERY_CHAT_COOLDOWN = 6*3600
RECOVERY_GAME_SECONDS = 300
RECOVERY_CODE_LENGTH = 3
RECOVERY_MAX_ATTEMPTS = 6
RECOVERY_SYMBOLS = ('🔺','🌙','⚡','💀','🔥','👁')
RECOVERY_OWNER_ACTIVE_SECONDS = 3600
RECOVERY_TZ = timezone(timedelta(hours=3), name='MSK')


def code_feedback(secret, guess):
    exact=sum(a==b for a,b in zip(secret,guess))
    misplaced=len(set(secret)&set(guess))-exact
    return exact,misplaced


def timestamp():
    from database import utc_timestamp
    return utc_timestamp()


class RecoveryMixin:
    def _init_recovery_events(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS slave_recovery_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,slave_id INTEGER NOT NULL,kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'announcing',created_at INTEGER NOT NULL,
                activated_at INTEGER,ended_at INTEGER,deadline INTEGER,
                pattern_json TEXT NOT NULL,step INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,
                message_chat INTEGER,message_id INTEGER);
            CREATE INDEX IF NOT EXISTS idx_recovery_owner ON slave_recovery_events(chat_id,owner_id,created_at);
            CREATE INDEX IF NOT EXISTS idx_recovery_open ON slave_recovery_events(status,deadline);
            CREATE TRIGGER IF NOT EXISTS recovery_cancel_on_release AFTER DELETE ON ownership
            BEGIN UPDATE slave_recovery_events SET status='cancelled',revision=revision+1,
                ended_at=CAST(strftime('%s','now') AS INTEGER)
                WHERE chat_id=OLD.chat_id AND owner_id=OLD.owner_id AND slave_id=OLD.slave_id
                AND status IN ('announcing','pending','playing'); END;
            CREATE TRIGGER IF NOT EXISTS recovery_cancel_on_transfer AFTER UPDATE OF owner_id,acquired_at ON ownership
            WHEN NEW.owner_id<>OLD.owner_id OR NEW.acquired_at<>OLD.acquired_at
            BEGIN UPDATE slave_recovery_events SET status='cancelled',revision=revision+1,
                ended_at=CAST(strftime('%s','now') AS INTEGER)
                WHERE chat_id=OLD.chat_id AND owner_id=OLD.owner_id AND slave_id=OLD.slave_id
                AND status IN ('announcing','pending','playing'); END;
        ''')
        self._ensure_column('slave_recovery_events','result_notified','INTEGER NOT NULL DEFAULT 0')
        self._ensure_column('slave_recovery_events','game_type',"TEXT NOT NULL DEFAULT 'memory'")
        self._ensure_column('slave_recovery_events','guess_json',"TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column('slave_recovery_events','history_json',"TEXT NOT NULL DEFAULT '[]'")
        # Old memory games were announced without an automatic-loss deadline.
        # Cancel rather than retroactively imposing new destructive rules.
        self.connection.execute("""UPDATE slave_recovery_events SET status='cancelled',
            ended_at=?,deadline=NULL,revision=revision+1 WHERE game_type<>'code'
            AND status IN ('announcing','pending','playing')""",(timestamp(),))

    async def enterprise_due_recoveries(self, rng=None):
        rng=rng or random.SystemRandom();now=timestamp();created=[]
        async with self._lock:
            with self.connection:
                # An interrupted publication never pauses work or loses a slave.
                self.connection.execute("UPDATE slave_recovery_events SET status='cancelled',ended_at=?,revision=revision+1 WHERE status='announcing' AND created_at<?",(now,now-300))
                if not 10<=datetime.fromtimestamp(now,RECOVERY_TZ).hour<22:return []
                owners=self.connection.execute('SELECT chat_id,owner_id,COUNT(*) AS amount FROM ownership GROUP BY chat_id,owner_id HAVING COUNT(*)>? ORDER BY chat_id,owner_id',(RECOVERY_THRESHOLD,)).fetchall()
                for owner in owners:
                    chat,user=owner['chat_id'],owner['owner_id']
                    if not self._feature_enabled_locked(chat,'slavery'):continue
                    active=self.connection.execute('SELECT last_seen FROM users WHERE chat_id=? AND user_id=?',(chat,user)).fetchone()
                    if not active or active['last_seen'] is None or not now-RECOVERY_OWNER_ACTIVE_SECONDS<=active['last_seen']<=now:continue
                    if self.connection.execute("SELECT 1 FROM slave_recovery_events WHERE chat_id=? AND owner_id=? AND (status IN ('announcing','pending','playing') OR created_at>?)",(chat,user,now-RECOVERY_COOLDOWN)).fetchone():continue
                    if self.connection.execute('SELECT 1 FROM slave_recovery_events WHERE chat_id=? AND created_at>?',(chat,now-RECOVERY_CHAT_COOLDOWN)).fetchone():continue
                    if rng.random()>=.10:continue
                    workers=self.connection.execute('''SELECT slave_id FROM ownership WHERE chat_id=? AND owner_id=?
                        AND slave_id NOT IN (SELECT user_id FROM slave_expedition_members WHERE active=1) ORDER BY slave_id''',(chat,user)).fetchall()
                    if not workers:continue
                    worker=rng.choice(workers)['slave_id'];pattern=rng.sample(range(len(RECOVERY_SYMBOLS)),RECOVERY_CODE_LENGTH)
                    cursor=self.connection.execute("INSERT INTO slave_recovery_events(chat_id,owner_id,slave_id,kind,created_at,pattern_json,game_type) VALUES(?,?,?,?,?,?,'code')",(chat,user,worker,rng.choice(('escaped','kidnapped')),now,json.dumps(pattern)))
                    created.append(dict(self.connection.execute('SELECT * FROM slave_recovery_events WHERE id=?',(cursor.lastrowid,)).fetchone()))
        return created

    async def recovery_published(self, event_id, chat, message_id):
        async with self._lock:
            with self.connection:
                row=self.connection.execute('SELECT * FROM slave_recovery_events WHERE id=?',(event_id,)).fetchone()
                if not row:return False
                if row['status']!='announcing':
                    self.connection.execute('UPDATE slave_recovery_events SET message_chat=?,message_id=? WHERE id=?',(chat,message_id,event_id))
                    return False
                if not self._feature_enabled_locked(row['chat_id'],'slavery'):
                    self.connection.execute("UPDATE slave_recovery_events SET status='cancelled',ended_at=?,message_chat=?,message_id=?,revision=revision+1 WHERE id=?",(timestamp(),chat,message_id,event_id))
                    return False
                self._enterprise_settle_owner_locked(row['chat_id'],row['owner_id'],timestamp())
                now=timestamp()
                self.connection.execute("UPDATE slave_recovery_events SET status='pending',activated_at=?,deadline=?,message_chat=?,message_id=? WHERE id=?",(now,now+RECOVERY_GAME_SECONDS,chat,message_id,event_id))
                return True

    async def recovery_cancel_publication(self, event_id):
        async with self._lock:
            self.connection.execute("UPDATE slave_recovery_events SET status='cancelled',ended_at=?,revision=revision+1 WHERE id=? AND status='announcing'",(timestamp(),event_id));self.connection.commit()

    async def recovery_cancel_delivery(self, event_id, actor, revision):
        """An undelivered game screen must not run a destructive timer.

        Do not undo finished games, transfers, or a newer successful action.
        """
        async with self._lock:
            with self.connection:
                self.connection.execute("""UPDATE slave_recovery_events
                    SET status='cancelled',ended_at=?,deadline=NULL,revision=revision+1
                    WHERE id=? AND owner_id=? AND revision=? AND status IN ('pending','playing')""",
                    (timestamp(),event_id,actor,revision))

    def _recovery_end_locked(self, row, won):
        owned=self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(row['chat_id'],row['owner_id'],row['slave_id'])).fetchone()
        self._enterprise_settle_owner_locked(row['chat_id'],row['owner_id'],timestamp())
        status=('returned' if won else 'lost') if owned else 'cancelled'
        self.connection.execute('UPDATE slave_recovery_events SET status=?,ended_at=?,deadline=NULL,revision=revision+1 WHERE id=?',(status,timestamp(),row['id']))
        if owned and not won:
            self.connection.execute('DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(row['chat_id'],row['owner_id'],row['slave_id']))
            self.connection.execute('DELETE FROM business_workers WHERE chat_id=? AND owner_id=? AND worker_id=?',(row['chat_id'],row['owner_id'],row['slave_id']))

    async def recovery_get(self, event_id):
        async with self._lock:
            row=self.connection.execute('SELECT * FROM slave_recovery_events WHERE id=?',(event_id,)).fetchone()
            return dict(row) if row else None

    async def recovery_action(self, event_id, actor, revision, action):
        async with self._lock:
            with self.connection:
                row=self.connection.execute('SELECT * FROM slave_recovery_events WHERE id=?',(event_id,)).fetchone()
                if not row or row['owner_id']!=actor:raise ValueError('Вернуть раба может только его владелец.')
                if row['status'] not in ('pending','playing'):
                    if action=='view':return dict(row)
                    raise ValueError('Событие уже завершено.')
                self._require_feature_locked(row['chat_id'],'slavery')
                owned=self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?',(row['chat_id'],actor,row['slave_id'])).fetchone()
                if not owned:
                    self._recovery_end_locked(row,False)
                elif timestamp()>=row['deadline']:
                    self._recovery_end_locked(row,False)
                elif action=='view':
                    return dict(row)
                elif row['revision']!=revision:
                    raise ValueError('Это старая кнопка. Обнови игру.')
                elif row['status']=='pending':
                    if action!='start':raise ValueError('Сначала начни мини-игру.')
                    self.connection.execute("UPDATE slave_recovery_events SET status='playing',revision=revision+1 WHERE id=?",(event_id,))
                else:
                    guess=json.loads(row['guess_json']);history=json.loads(row['history_json'])
                    if action=='undo':guess=guess[:-1]
                    elif action=='clear':guess=[]
                    elif action in tuple(str(i) for i in range(len(RECOVERY_SYMBOLS))):
                        symbol=int(action)
                        if symbol in guess:raise ValueError('Символы не повторяются. Выбери другой или убери последний.')
                        guess.append(symbol)
                    else:raise ValueError('Некорректный ответ.')
                    won=False
                    if len(guess)==RECOVERY_CODE_LENGTH:
                        exact,misplaced=code_feedback(json.loads(row['pattern_json']),guess)
                        history.append(dict(guess=guess,exact=exact,misplaced=misplaced))
                        won=exact==RECOVERY_CODE_LENGTH;guess=[]
                    self.connection.execute('UPDATE slave_recovery_events SET guess_json=?,history_json=?,revision=revision+1 WHERE id=?',(json.dumps(guess),json.dumps(history),event_id))
                    if won or len(history)>=RECOVERY_MAX_ATTEMPTS:self._recovery_end_locked(row,won)
                return dict(self.connection.execute('SELECT * FROM slave_recovery_events WHERE id=?',(event_id,)).fetchone())

    async def recovery_expire(self):
        async with self._lock:
            with self.connection:
                opened=self.connection.execute("SELECT * FROM slave_recovery_events WHERE status IN ('pending','playing')").fetchall()
                for event in opened:
                    if not self._feature_enabled_locked(event['chat_id'],'slavery'):
                        self.connection.execute("UPDATE slave_recovery_events SET status='cancelled',ended_at=?,deadline=NULL,revision=revision+1 WHERE id=?",(timestamp(),event['id']))
                rows=self.connection.execute("SELECT * FROM slave_recovery_events WHERE status IN ('pending','playing') AND deadline<=?",(timestamp(),)).fetchall()
                for row in rows:self._recovery_end_locked(row,False)
                return [dict(r) for r in self.connection.execute("SELECT * FROM slave_recovery_events WHERE status IN ('lost','returned','cancelled') AND message_id IS NOT NULL AND result_notified=0 ORDER BY id LIMIT 20")]

    async def recovery_notified(self, event_id):
        async with self._lock:
            self.connection.execute('UPDATE slave_recovery_events SET result_notified=1 WHERE id=?',(event_id,));self.connection.commit()

    async def recovery_pending(self, chat, owner):
        async with self._lock:
            return [dict(r) for r in self.connection.execute("SELECT * FROM slave_recovery_events WHERE chat_id=? AND owner_id=? AND status IN ('pending','playing') ORDER BY id",(chat,owner))]
