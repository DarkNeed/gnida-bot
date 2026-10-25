"""Permanent worker passports. Luck/trait belong to a user, never to their owner.

Rarity is rolled once and stored explicitly. Activity, sale, recapture and
appraisals never change it. Historical pre-passport income remains unmodified.
"""
import random
from custom_commands import CUSTOM_COMMAND_OWNER_ID as LEGENDARY_WORKER_ID

RARITIES = {
    'common': dict(name='Обычный',income_bonus=0,expedition_bonus=0,color='#9eabbc'),
    'uncommon': dict(name='Необычный',income_bonus=10,expedition_bonus=2,color='#80cfa2'),
    'rare': dict(name='Редкий',income_bonus=25,expedition_bonus=4,color='#7cbbf8'),
    'epic': dict(name='Эпический',income_bonus=45,expedition_bonus=7,color='#be96ef'),
    'legendary': dict(name='Легендарный',income_bonus=70,expedition_bonus=10,color='#f2ca79'),
}
RARITY_BOUNDARIES = (5000,7800,9300,9900)
RARITY_CHANCES = (50,28,15,6,1)
TRAITS = {
    'mine': dict(name='Шахтёр последней смены',flavor='Свет в конце тоннеля? Опять переработка.',
                 effect='Выработка в шахте +30%.',work={'mine':30}),
    'tavern': dict(name='Барный некромант',flavor='Поднимает мёртвых. Обычно к третьей кружке.',
                   effect='Выработка в таверне +30%.',work={'tavern':30}),
    'workshop': dict(name='Патологоанатом механизмов',flavor='Вскрытие показало: мастерская тоже умерла от переработки.',
                     effect='Выработка в мастерской +30%.',work={'workshop':30}),
    'field': dict(name='Агроном братской грядки',flavor='Удобрение натуральное. Происхождение не уточняйте.',
                  effect='Выработка на хлопковом поле +30%.',work={'field':30}),
    'brothel': dict(name='Сутенёр загробного сервиса',flavor='Даже фраза «через мой труп» здесь не повод отменять бронь.',
                    effect='Выработка в борделе +30%.',work={'brothel':30}),
    'custom': dict(name='Сертифицированный расходник',flavor='В должностной инструкции: «и другие поручения палача».',
                   effect='Выработка в кастомном предприятии +30%.',work={'custom':30}),
    'accountant': dict(name='Бухгалтер апокалипсиса',flavor='Конец света — не повод не сдать отчётность.',
                       effect='Выработка на любом предприятии +10%.',work_all=10),
    'posthumous': dict(name='Работник месяца. Посмертно',flavor='Умер на работе. В табеле всё равно прогул.',
                       effect='Выработка везде +20%; риск освобождения в экспедиции +2 п.п.',work_all=20,loss=2),
    'manager': dict(name='Прораб крематория',flavor='Коллектив сгорает на работе. Он называет это сплочением.',
                    effect='В должности управляющего: ещё +5 п.п. к бонусу активной выручки.',manager=5),
    'survivor': dict(name='Профессиональный недотруп',flavor='Гроб уже заказали, но он снова вышел на смену.',
                     effect='Риск освобождения в экспедиции −4 п.п.',loss=-4),
    'scout': dict(name='Турист морга',flavor='Сувениры привозит сам. Иногда сувениры привозят его.',
                  effect='Сила экспедиции +10%.',power=10),
    'ruins': dict(name='Экскурсовод последнего пути',flavor='«Не отставайте от группы» звучит всё менее добровольно.',
                  effect='В Проклятых руинах сила экспедиции +20%.',mission_power={'ruins':20}),
    'insured': dict(name='Страховой случай',flavor='Страховщик плачет каждый раз, когда он возвращается живым.',
                    effect='При провале экспедиции риск освобождения −7 п.п.',failure_loss=-7),
}


def draw_identity():
    rng=random.SystemRandom()
    return rng.randrange(10000),rng.choice(tuple(TRAITS))


def now():
    from database import utc_timestamp
    return utc_timestamp()


def rarity_for(luck):
    return tuple(RARITIES)[sum(luck>=b for b in RARITY_BOUNDARIES)]


def identity_at(context,at):
    row=context
    rarity=row['rarity']
    trait_id=row['trait'];trait=TRAITS[trait_id]
    return dict(rarity=rarity,rarity_name=RARITIES[rarity]['name'],color=RARITIES[rarity]['color'],
                income_bonus=RARITIES[rarity]['income_bonus'],expedition_bonus=RARITIES[rarity]['expedition_bonus'],
                trait_id=trait_id,trait_name=trait['name'],trait_flavor=trait['flavor'],trait_effect=trait['effect'],
                permanent=True,
                effective_at=row['created_at'],active=at>=row['created_at'])


def work_percent(identity,kind):
    if not identity['active']:return 100
    trait=TRAITS[identity['trait_id']]
    return 100+identity['income_bonus']+trait.get('work_all',0)+trait.get('work',{}).get(kind,0)


def manager_bonus(identity):
    return TRAITS[identity['trait_id']].get('manager',0) if identity['active'] else 0


class SlaveIdentityMixin:
    def _init_slave_identities(self):
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS slave_identities(
                user_id INTEGER PRIMARY KEY,luck INTEGER NOT NULL CHECK(luck BETWEEN 0 AND 9999),
                trait TEXT NOT NULL,created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS slave_activity_days(
                user_id INTEGER NOT NULL,activity_day TEXT NOT NULL,first_seen INTEGER NOT NULL,
                PRIMARY KEY(user_id,activity_day));
            CREATE INDEX IF NOT EXISTS idx_slave_activity_time ON slave_activity_days(user_id,first_seen);
        ''')
        self._ensure_column('slave_identities','rarity','TEXT')
        # Freeze already-issued passports at their current quality once. Do not
        # demote a previously promoted worker, and never consult activity again.
        stamp=now()
        for row in self.connection.execute('''SELECT i.*, (SELECT COUNT(*) FROM slave_activity_days a
            WHERE a.user_id=i.user_id AND a.first_seen<=?) AS days FROM slave_identities i
            WHERE i.rarity IS NULL''',(stamp,)).fetchall():
            boundaries=(2000,5000,8000,9500) if row['days']>=60 else (3000,6000,8500,9700) if row['days']>=21 else (4000,7000,9000,9800) if row['days']>=7 else RARITY_BOUNDARIES
            rarity=tuple(RARITIES)[sum(row['luck']>=b for b in boundaries)]
            self.connection.execute('UPDATE slave_identities SET rarity=? WHERE user_id=?',(rarity,row['user_id']))
        self._slave_identity_row_locked(LEGENDARY_WORKER_ID)
        self._ensure_column('businesses','income_subcent','INTEGER NOT NULL DEFAULT 0')

    def _slave_identity_row_locked(self,user):
        row=self.connection.execute('SELECT * FROM slave_identities WHERE user_id=?',(user,)).fetchone()
        if row is None:
            luck,trait=draw_identity()
            rarity='legendary' if user==LEGENDARY_WORKER_ID else rarity_for(luck)
            self.connection.execute('INSERT INTO slave_identities(user_id,luck,trait,created_at,rarity) VALUES(?,?,?,?,?)',(user,luck,trait,now(),rarity))
            row=self.connection.execute('SELECT * FROM slave_identities WHERE user_id=?',(user,)).fetchone()
        elif user==LEGENDARY_WORKER_ID and row['rarity']!='legendary':
            self.connection.execute("UPDATE slave_identities SET rarity='legendary' WHERE user_id=?",(user,))
            row=self.connection.execute('SELECT * FROM slave_identities WHERE user_id=?',(user,)).fetchone()
        return row

    def _slave_identity_locked(self,user,at=None):
        return identity_at(self._slave_identity_context_locked(user),now() if at is None else at)

    def _slave_identity_context_locked(self,user):
        return self._slave_identity_row_locked(user)

    def _slave_work_percent_locked(self,user,kind,at):
        return work_percent(self._slave_identity_locked(user,at),kind)

    def _slave_manager_bonus_locked(self,user,at):
        return manager_bonus(self._slave_identity_locked(user,at))
