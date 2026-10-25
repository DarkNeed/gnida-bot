"""Fictional franc wager: 16% gross x5, stake-based account-wide cooldown."""

import random
import re

DEPOSIT_RE = re.compile(r'^\s*[!/]?депнуть(?:@\w+)?(?:\s|$)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'([0-9]{1,19})(?:(?:\s+(?:франк|франка|франков))|\s*₣)?', re.IGNORECASE)
DEPOSIT_COOLDOWN = 60
DEPOSIT_WIN_PERCENT = 16
DEPOSIT_COOLDOWN_TIERS = ((50,600),(200,300),(500,120))
DEPOSIT_ERROR_INTERVAL = 30

LOSS_PHRASES = (
    '🪦 {user}, твои {stake} ₣ похоронены без права на наследство. Денег нет, зато финансовый опыт бесценен.',
    '🎰 {user}, казино выражает соболезнования твоему кошельку. Венок за {stake} ₣ уже оплачен.',
    '📉 {user} вложил {stake} ₣ в светлое будущее. Будущее выключило свет и съехало.',
    '⚰️ {user}, вскрытие кошелька показало: причиной смерти стали уверенность и кнопка «депнуть». Минус {stake} ₣.',
    '🦣 {user}, поздравляем с повышением до почётного мамонта. Членский взнос: {stake} ₣.',
    '🏦 {user}, твои {stake} ₣ пошли на благотворительность. На помощь владельцу казино с покупкой второй яхты.',
    '🧾 {user}, за {stake} ₣ приобретён трактат «Как не надо». Навык «Читать» всё ещё не изучен.',
    '🕯 {user}, помянем {stake} ₣. Они были хорошими франками, просто им достался плохой финансовый директор.',
    '🔬 {user}, эксперимент завершён: {stake} ₣ действительно можно превратить в нихуя.',
    '🗑 {user} отправил {stake} ₣ в фонд поддержки лохов. Фонд благодарит единственного спонсора.',
)
WIN_PHRASES = (
    '🎰 {user}, казино подавилось твоей ставкой. ×5: выплата {payout} ₣. Бухгалтеру уже несут валерьянку.',
    '🪄 {user}, из {stake} ₣ получилось {payout} ₣. Даже финансовая пирамида на секунду перестала быть пирамидой.',
    '💀 {user}, ты вынес {payout} ₣. У казино умерла прибыль, но оно ещё надеется на остальных мамонтов.',
    '🤑 {user}, ×5 — получай {payout} ₣. Сегодня посмешище не ты, а наш отдел риск-менеджмента.',
)


def parse_deposit(text):
    prefix=DEPOSIT_RE.match(text)
    payload=text[prefix.end():].strip() if prefix else ''
    modes={'всё':'all','все':'all','половину':'half'}
    if prefix and payload.casefold() in modes:
        return modes[payload.casefold()]
    match=AMOUNT_RE.fullmatch(payload) if prefix else None
    if not match:
        raise ValueError('Напиши: депнуть 100, депнуть 13400 франков, депнуть всё или депнуть половину. Ставка — целое положительное число.')
    value=int(match[1])
    from database import MAX_FRANC_BALANCE
    if not 1<=value<=MAX_FRANC_BALANCE//5:
        raise ValueError(f'Ставка должна быть от 1 до {MAX_FRANC_BALANCE//5} ₣.')
    return value


def deposit_cooldown(stake):
    """Use the paid amount, not the next requested amount or the current wallet."""
    if type(stake) is not int or stake<1:raise ValueError('Некорректная ставка.')
    return next((seconds for upper,seconds in DEPOSIT_COOLDOWN_TIERS if stake<upper),DEPOSIT_COOLDOWN)


class DepositMixin:
    def _init_deposits(self):
        self.connection.execute('''CREATE TABLE IF NOT EXISTS franc_deposits(
            message_chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,stake INTEGER NOT NULL,
            won INTEGER NOT NULL,payout INTEGER NOT NULL,balance_after INTEGER NOT NULL,
            phrase TEXT NOT NULL,created_at INTEGER NOT NULL,
            PRIMARY KEY(message_chat_id,message_id))''')
        self._ensure_column('franc_deposits','stake_mode',"TEXT NOT NULL DEFAULT 'amount'")
        # Preserve the original 60-second period on pre-update receipts. Never
        # extend a past wager retroactively when deploying or restarting.
        self._ensure_column('franc_deposits','cooldown_seconds','INTEGER NOT NULL DEFAULT 60')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS franc_deposit_limits(
                user_id INTEGER PRIMARY KEY,cooldown_until INTEGER NOT NULL DEFAULT 0,
                cooldown_warned INTEGER NOT NULL DEFAULT 0,error_next_at INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS franc_deposit_rejections(
                message_chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,PRIMARY KEY(message_chat_id,message_id));
            CREATE INDEX IF NOT EXISTS idx_deposit_user_time ON franc_deposits(user_id,created_at);
        ''')
        self.connection.execute('''INSERT OR IGNORE INTO franc_deposit_limits(user_id,cooldown_until)
            SELECT user_id,MAX(created_at+cooldown_seconds) FROM franc_deposits GROUP BY user_id''')

    def _deposit_seen_locked(self, user, source, message_id):
        return bool(self.connection.execute('SELECT 1 FROM franc_deposits WHERE message_chat_id=? AND message_id=?',
                     (source,message_id)).fetchone() or self.connection.execute(
                     'SELECT 1 FROM franc_deposit_rejections WHERE message_chat_id=? AND message_id=?',
                     (source,message_id)).fetchone())

    def _deposit_limit_locked(self, user):
        self.connection.execute('INSERT OR IGNORE INTO franc_deposit_limits(user_id) VALUES(?)',(user,))
        return self.connection.execute('SELECT * FROM franc_deposit_limits WHERE user_id=?',(user,)).fetchone()

    def _deposit_reject_locked(self, user, source, message_id, stamp):
        self.connection.execute('INSERT OR IGNORE INTO franc_deposit_rejections VALUES(?,?,?,?)',
                                (source,message_id,user,stamp))

    def _deposit_cooldown_locked(self, user, source, message_id, stamp):
        limit=self._deposit_limit_locked(user)
        if limit['cooldown_until']<=stamp:
            return None
        self._deposit_reject_locked(user,source,message_id,stamp)
        notify=not limit['cooldown_warned']
        if notify:
            self.connection.execute('UPDATE franc_deposit_limits SET cooldown_warned=1 WHERE user_id=?',(user,))
        return dict(blocked=True,notify=notify,remaining=limit['cooldown_until']-stamp)

    async def deposit_gate(self, user, source, message_id):
        """Cheap preflight before parsing, membership requests or settlement."""
        from database import utc_timestamp
        async with self._lock:
            with self.connection:
                if self._deposit_seen_locked(user,source,message_id):
                    return dict(blocked=True,notify=False,remaining=0)
                return self._deposit_cooldown_locked(user,source,message_id,utc_timestamp())

    async def deposit_error_gate(self, user, source, message_id):
        from database import utc_timestamp
        async with self._lock:
            with self.connection:
                if self._deposit_seen_locked(user,source,message_id):
                    return dict(blocked=True,notify=False,remaining=0)
                stamp=utc_timestamp()
                cooldown=self._deposit_cooldown_locked(user,source,message_id,stamp)
                if cooldown:return cooldown
                limit=self._deposit_limit_locked(user)
                self._deposit_reject_locked(user,source,message_id,stamp)
                notify=stamp>=limit['error_next_at']
                if notify:
                    self.connection.execute('UPDATE franc_deposit_limits SET error_next_at=? WHERE user_id=?',
                                            (stamp+DEPOSIT_ERROR_INTERVAL,user))
                return dict(blocked=True,notify=notify,remaining=0)

    async def deposit_francs(self,chat,user,stake,message_chat,message_id,rng=None,*,suppress_replay=False):
        from database import MAX_FRANC_BALANCE,utc_timestamp
        mode=stake if type(stake) is str and stake in ('all','half') else 'amount'
        if (any(type(v) is not int for v in (chat,user,message_chat,message_id))
                or chat>=0 or user<=0 or message_id<=0 or message_chat not in (chat,user)
                or (mode=='amount' and (type(stake) is not int or not 1<=stake<=MAX_FRANC_BALANCE//5))):
            raise ValueError('Некорректная ставка.')
        rng=rng or random.SystemRandom()
        async with self._lock:
            with self.connection:
                old=self.connection.execute('SELECT * FROM franc_deposits WHERE message_chat_id=? AND message_id=?',(message_chat,message_id)).fetchone()
                if old:
                    if (old['chat_id']!=chat or old['user_id']!=user or old['stake_mode']!=mode
                            or (mode=='amount' and old['stake']!=stake)):
                        raise ValueError('Это сообщение уже использовано для другой ставки.')
                    if suppress_replay:return dict(blocked=True,notify=False,remaining=0)
                    return dict(old)
                if self.connection.execute('SELECT 1 FROM franc_deposit_rejections WHERE message_chat_id=? AND message_id=?',
                                           (message_chat,message_id)).fetchone():
                    return dict(blocked=True,notify=False,remaining=0)
                stamp=utc_timestamp()
                blocked=self._deposit_cooldown_locked(user,message_chat,message_id,stamp)
                if blocked:return blocked
                row=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,user)).fetchone()
                balance=row['balance'] if row else 0
                if mode!='amount':
                    stake=balance if mode=='all' else balance//2
                    if stake<1:
                        raise ValueError('Для ставки половины нужно хотя бы 2 ₣.' if mode=='half' else 'На балансе нет франков для ставки.')
                    if stake>MAX_FRANC_BALANCE//5:
                        raise ValueError('Возможная выплата превысит лимит кошелька. Укажи меньшую ставку числом.')
                if balance<stake:
                    raise ValueError(f'Не хватает франков: ставка {stake} ₣, на балансе {balance} ₣.')
                if balance>MAX_FRANC_BALANCE-4*stake:
                    raise ValueError('Возможный выигрыш превысит лимит кошелька. Уменьши ставку.')
                seconds=deposit_cooldown(stake)
                won=rng.randrange(100)<DEPOSIT_WIN_PERCENT
                if won:
                    self.connection.execute('''INSERT INTO arena_casino_unlocks(user_id,invited) VALUES(?,1)
                        ON CONFLICT(user_id) DO UPDATE SET invited=1''',(user,))
                payout=stake*5 if won else 0
                after=balance-stake+payout
                phrase=rng.choice(WIN_PHRASES if won else LOSS_PHRASES)
                self.connection.execute('UPDATE franc_balances SET balance=?,updated_at=? WHERE chat_id=? AND user_id=?',(after,utc_timestamp(),chat,user))
                self.connection.execute('''INSERT INTO franc_deposits
                    (message_chat_id,message_id,chat_id,user_id,stake,won,payout,balance_after,phrase,created_at,stake_mode,cooldown_seconds)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (message_chat,message_id,chat,user,stake,int(won),payout,after,phrase,stamp,mode,seconds))
                self.connection.execute('UPDATE franc_deposit_limits SET cooldown_until=?,cooldown_warned=0 WHERE user_id=?',
                                        (stamp+seconds,user))
                return dict(self.connection.execute('SELECT * FROM franc_deposits WHERE message_chat_id=? AND message_id=?',(message_chat,message_id)).fetchone())
