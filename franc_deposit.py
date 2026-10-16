"""Fictional franc wager: 20% gross x5, atomic and Telegram-message idempotent."""

import random
import re

DEPOSIT_RE = re.compile(r'^\s*[!/]?депнуть(?:@\w+)?(?:\s|$)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'([0-9]{1,19})(?:(?:\s+(?:франк|франка|франков))|\s*₣)?', re.IGNORECASE)

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
    match=AMOUNT_RE.fullmatch(text[prefix.end():].strip()) if prefix else None
    if not match:
        raise ValueError('Напиши: депнуть 100 или депнуть 13400 франков. Ставка — целое положительное число.')
    value=int(match[1])
    from database import MAX_FRANC_BALANCE
    if not 1<=value<=MAX_FRANC_BALANCE//5:
        raise ValueError(f'Ставка должна быть от 1 до {MAX_FRANC_BALANCE//5} ₣.')
    return value


class DepositMixin:
    def _init_deposits(self):
        self.connection.execute('''CREATE TABLE IF NOT EXISTS franc_deposits(
            message_chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,stake INTEGER NOT NULL,
            won INTEGER NOT NULL,payout INTEGER NOT NULL,balance_after INTEGER NOT NULL,
            phrase TEXT NOT NULL,created_at INTEGER NOT NULL,
            PRIMARY KEY(message_chat_id,message_id))''')

    async def deposit_francs(self,chat,user,stake,message_chat,message_id,rng=None):
        from database import MAX_FRANC_BALANCE,utc_timestamp
        if (any(type(v) is not int for v in (chat,user,stake,message_chat,message_id))
                or chat>=0 or user<=0 or message_id<=0 or message_chat not in (chat,user)
                or not 1<=stake<=MAX_FRANC_BALANCE//5):
            raise ValueError('Некорректная ставка.')
        rng=rng or random.SystemRandom()
        async with self._lock:
            with self.connection:
                old=self.connection.execute('SELECT * FROM franc_deposits WHERE message_chat_id=? AND message_id=?',(message_chat,message_id)).fetchone()
                if old:
                    if old['chat_id']!=chat or old['user_id']!=user or old['stake']!=stake:
                        raise ValueError('Это сообщение уже использовано для другой ставки.')
                    return dict(old)
                row=self.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,user)).fetchone()
                balance=row['balance'] if row else 0
                if balance<stake:
                    raise ValueError(f'Не хватает франков: ставка {stake} ₣, на балансе {balance} ₣.')
                if balance>MAX_FRANC_BALANCE-4*stake:
                    raise ValueError('Возможный выигрыш превысит лимит кошелька. Уменьши ставку.')
                won=rng.randrange(100)<20
                payout=stake*5 if won else 0
                after=balance-stake+payout
                phrase=rng.choice(WIN_PHRASES if won else LOSS_PHRASES)
                self.connection.execute('UPDATE franc_balances SET balance=?,updated_at=? WHERE chat_id=? AND user_id=?',(after,utc_timestamp(),chat,user))
                self.connection.execute('INSERT INTO franc_deposits VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (message_chat,message_id,chat,user,stake,int(won),payout,after,phrase,utc_timestamp()))
                return dict(self.connection.execute('SELECT * FROM franc_deposits WHERE message_chat_id=? AND message_id=?',(message_chat,message_id)).fetchone())
