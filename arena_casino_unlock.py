"""Account-wide secret invitation; free, revision-checked trial with play chips."""
import json
import random
import time


class CasinoUnlockMixin:
    def _connect_casino(self):
        self.connection.execute('''CREATE TABLE IF NOT EXISTS arena_casino_unlocks(
            user_id INTEGER PRIMARY KEY, invited INTEGER NOT NULL DEFAULT 0,
            unlocked INTEGER NOT NULL DEFAULT 0, trial_json TEXT NOT NULL DEFAULT '{}',
            revision INTEGER NOT NULL DEFAULT 0, retry_at INTEGER NOT NULL DEFAULT 0)''')
        self.connection.execute('''INSERT OR IGNORE INTO arena_casino_unlocks(user_id,invited)
            SELECT DISTINCT user_id,1 FROM franc_deposits WHERE won=1''')

    def _casino_row_locked(self,user):
        self.connection.execute('INSERT OR IGNORE INTO arena_casino_unlocks(user_id) VALUES(?)',(user,))
        return self.connection.execute('SELECT * FROM arena_casino_unlocks WHERE user_id=?',(user,)).fetchone()

    def _arena_secret_classes_locked(self,user):
        return {'gambler'} if self._casino_row_locked(user)['unlocked'] else set()

    async def arena_casino_view(self,chat,user):
        async with self._lock:
            with self.connection:
                row=self._casino_row_locked(user)
                merchant=self._arena_merchant_view_locked(chat,user)
                return dict(invited=bool(row['invited']),unlocked=bool(row['unlocked']),
                    merchant=bool(merchant['visit_id']),trial=json.loads(row['trial_json']),
                    revision=row['revision'],retry_at=row['retry_at'])

    async def arena_casino_action(self,chat,user,body,expected_slot=1,*,rng=None):
        rng=rng or random.SystemRandom()
        async with self._lock:
            with self.connection:
                self._require_feature_locked(chat,'arena')
                self._character_require_locked(user,expected_slot)
                row=self._casino_row_locked(user)
                if type(body.get('revision')) is not int or body['revision']!=row['revision']:
                    raise ValueError('Стол уже изменился. Обнови меню.')
                action=body.get('move')
                if action=='equip':
                    if not row['unlocked']:raise ValueError('Секретный класс ещё не открыт.')
                    if body.get('confirm') is not True:raise ValueError('Подтверди смену: уровень станет 5, текущий билд будет сброшен.')
                    if self._arena_choice_busy_locked(chat,user):raise ValueError('Сначала заверши текущий бой.')
                    from arena_global import RPG_SCOPE
                    self._arena_reset_profile_locked(RPG_SCOPE,user,True,'gambler')
                    self._arena_equip_class_passives_locked(RPG_SCOPE,user,True,'gambler')
                    self.connection.execute('UPDATE arena_casino_unlocks SET revision=revision+1 WHERE user_id=?',(user,))
                    return 'Выбран Лудоман. Уровень 5; прежний опыт возвращается с ускорением. Открытие сохранено для всех слотов.'
                if row['unlocked']:raise ValueError('Класс уже открыт.')
                if not row['invited']:raise ValueError('Торговец пока не приглашал тебя за тайный стол.')
                trial=json.loads(row['trial_json'])
                if action=='start':
                    if trial.get('active'):raise ValueError('Испытание уже начато.')
                    if row['retry_at']>time.time():raise ValueError('Новая попытка будет доступна через несколько минут.')
                    if not self._arena_merchant_view_locked(chat,user)['visit_id']:raise ValueError('Начать испытание можно у торговца во время визита.')
                    trial=dict(active=True,chips=10,round=0,card=rng.randint(1,13),last='')
                    notice='Пять раз выбери: следующая карта выше или ниже текущей. Нужно закончить с 14 фишками. Это бесплатные временные фишки.'
                elif action in ('high','low'):
                    if not trial.get('active'):raise ValueError('Сначала начни испытание.')
                    card=rng.randint(1,13)
                    won=card>trial['card'] if action=='high' else card<trial['card']
                    trial.update(chips=trial['chips']+(3 if won else -2),round=trial['round']+1,
                                 last=f'{trial["card"]} → {card}: '+('+3 фишки' if won else '−2 фишки'),card=card)
                    success=trial['round']>=5 and trial['chips']>=14
                    finished=trial['round']>=5
                    trial['active']=not finished
                    self.connection.execute('UPDATE arena_casino_unlocks SET unlocked=?,retry_at=? WHERE user_id=?',
                        (int(success),int(time.time())+600 if finished and not success else 0,user))
                    notice='Лудоман открыт! Доступ общий для аккаунта.' if success else 'Стол закрыт. Повтори бесплатно через 10 минут.' if finished else trial['last']
                else:raise ValueError('Неизвестное действие за столом.')
                self.connection.execute('UPDATE arena_casino_unlocks SET trial_json=?,revision=revision+1 WHERE user_id=?',
                                        (json.dumps(trial,ensure_ascii=False),user))
                return notice
