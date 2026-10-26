"""Durable, actor/chat/message-bound confirmations for public finance commands."""
import hashlib
import json


class FinanceCommandsMixin:
    def _init_finance_commands(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS npc_finance_commands(
                id TEXT PRIMARY KEY,chat_id INTEGER NOT NULL,source_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,body TEXT NOT NULL,summary TEXT NOT NULL,
                created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(chat_id,source_id,actor_id));
        ''')

    async def finance_command_existing(self, chat, source, actor):
        async with self._lock:
            row=self.connection.execute('SELECT * FROM npc_finance_commands WHERE chat_id=? AND source_id=? AND actor_id=?',
                                        (chat,source,actor)).fetchone()
            return dict(row) if row else None

    async def finance_command_state(self, chat, actor):
        from slave_finance import now
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'slavery')
                self._finance_tick_locked()
                loan=self._finance_loan_locked(actor)
                return dict(loan=dict(loan) if loan else None,limit=self._finance_limit_locked(actor),
                            balance=self._trader_balance_locked(chat,actor),server_time=now())

    async def finance_command_create(self, chat, source, actor, body, summary):
        from slave_finance import now, positive
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'slavery')
                kind=body.get('action')
                if kind=='finance_borrow':
                    amount=positive(body.get('amount'))
                    if self._finance_loan_locked(actor):
                        raise ValueError('Сначала верни текущий долг. Вторую могилу в кредит не выдаём.')
                    if amount>self._finance_limit_locked(actor):
                        raise ValueError('Сумма выше доступного лимита. Напиши «долг», чтобы посмотреть лимит.')
                    if self.connection.execute('SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?',(chat,actor)).fetchone():
                        raise ValueError('Сначала нужно освободиться в этом чате, затем брать новый заём.')
                elif kind=='finance_wager':
                    quote=self.connection.execute('SELECT * FROM npc_wager_quotes WHERE id=? AND chat_id=? AND user_id=?',
                        (body.get('offer'),chat,actor)).fetchone()
                    if not quote or quote['expires_at']<=now():
                        raise ValueError('Расчёт ставки истёк. Отправь команду заново.')
                    limit=self._deposit_limit_locked(actor)
                    if limit['cooldown_until']>now():
                        raise ValueError(f'Казино ещё пересчитывает похоронные. Подожди {limit["cooldown_until"]-now()} сек.')
                elif kind=='finance_repay':
                    amount=positive(body.get('amount'))
                    loan=self._finance_loan_locked(actor)
                    if not loan or loan['id']!=body.get('loan') or amount>loan['remaining']:
                        raise ValueError('Остаток долга изменился. Напиши «долг» и проверь сумму.')
                    if amount>self._trader_balance_locked(chat,actor):
                        raise ValueError('Не хватает франков в кошельке этого чата. Можно внести меньший платёж.')
                else:
                    raise ValueError('Некорректное действие команды.')
                ident=hashlib.sha256(f'finance-command:{chat}:{source}:{actor}'.encode()).hexdigest()[:32]
                self.connection.execute('''INSERT INTO npc_finance_commands
                    (id,chat_id,source_id,actor_id,body,summary,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)''',
                    (ident,chat,source,actor,json.dumps(body,sort_keys=True),summary,now(),now()+300))
                return dict(self.connection.execute('SELECT * FROM npc_finance_commands WHERE id=?',(ident,)).fetchone())

    async def finance_command_bind(self, ident, actor, message):
        async with self._lock:
            with self.connection:
                self.connection.execute('UPDATE npc_finance_commands SET message_id=? WHERE id=? AND actor_id=? AND message_id IS NULL',
                                        (message,ident,actor))

    async def finance_command_get(self, ident, chat, message, actor):
        from slave_finance import now
        async with self._lock:
            row=self.connection.execute('SELECT * FROM npc_finance_commands WHERE id=?',(ident,)).fetchone()
            if not row or row['chat_id']!=chat or row['message_id']!=message:
                raise ValueError('Это подтверждение относится к другому сообщению.')
            if row['actor_id']!=actor:
                raise ValueError('Подтверждать может только автор команды. Чужие похороны не оплачивай.')
            receipt=self.connection.execute('SELECT result FROM npc_finance_receipts WHERE user_id=? AND nonce=?',(actor,ident)).fetchone()
            result=dict(row)
            if receipt:
                result.update(status='done',result=json.loads(receipt['result']))
                return result
            if row['status']=='cancelled':
                return result
            if row['expires_at']<=now():
                raise ValueError('Пять минут истекли. Отправь команду заново; деньги и рабы не списаны.')
            return result

    async def finance_command_close(self, ident, actor, *, cancelled=False):
        async with self._lock:
            with self.connection:
                self.connection.execute('UPDATE npc_finance_commands SET status=? WHERE id=? AND actor_id=?',
                                        ('cancelled' if cancelled else 'done',ident,actor))
