"""Persistent, no-stakes chat duels. No connection to the RPG or wallets."""
import json
import random
import secrets


INVITE_SECONDS = 120
TURN_SECONDS = 45
MAX_ROUNDS = 8
HIT_CHANCES = (25, 55, 85)
DISRUPT_CHANCE = 50
ACTIONS = {"shoot": "🔫 Выстрелить", "aim": "🎯 Прицелиться", "disrupt": "💨 Сбить прицел"}


class DuelError(ValueError):
    """An error that can be shown to a player."""


def resolve_round(fighters, moves, rng):
    """Resolve disruptions first, then simultaneous shots; never mutate the input."""
    after = [dict(fighter) for fighter in fighters]
    blocked = [False, False]
    effects = [[], []]
    for i, move in enumerate(moves):
        fighter, opponent = after[i], after[1 - i]
        fighter["cooldown"] = move == "disrupt"
        if move != "disrupt":
            continue
        opposing_move = moves[1 - i]
        if opposing_move != "aim" and not (opposing_move == "shoot" and opponent["aim"]):
            effects[i].append("сбивать нечего")
        elif rng.randrange(100) >= DISRUPT_CHANCE:
            effects[i].append("не удалось сбить прицел")
        else:
            if opposing_move == "aim":
                blocked[1 - i] = True
            else:
                opponent["aim"] -= 1
            effects[i].append("прицел сбит")

    hits = [False, False]
    for i, move in enumerate(moves):
        fighter = after[i]
        if move == "aim":
            if not blocked[i]:
                fighter["aim"] = min(2, fighter["aim"] + 1)
                effects[i].append("+1 прицел")
            else:
                effects[i].append("прицеливание сорвано")
        elif move == "shoot":
            chance = HIT_CHANCES[fighter["aim"]]
            hits[i] = rng.randrange(100) < chance
            effects[i].append(f"{'💥 попадание' if hits[i] else '🌫 промах'} · {chance}%")
            fighter["aim"] = 0
    for i, hit in enumerate(hits):
        if hit:
            after[1 - i]["hp"] = 0
    return after, effects


def action_enabled(fighter, action):
    return action in ACTIONS and not (action == "disrupt" and fighter["cooldown"]
                                     or action == "aim" and fighter["aim"] == 2)


class QuickDuelMixin:
    def _connect_quick_duels(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS quick_duels (
                id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, source_id INTEGER NOT NULL,
                message_id INTEGER, creator INTEGER NOT NULL, guest INTEGER NOT NULL,
                status TEXT NOT NULL, deadline INTEGER NOT NULL, state_json TEXT NOT NULL,
                UNIQUE(chat_id,source_id));
            CREATE INDEX IF NOT EXISTS quick_duels_deadline ON quick_duels(deadline)
                WHERE status IN ('pending','active');
            CREATE INDEX IF NOT EXISTS quick_duels_creator ON quick_duels(chat_id,creator,status,deadline);
            CREATE INDEX IF NOT EXISTS quick_duels_guest ON quick_duels(chat_id,guest,deadline)
                WHERE status='active';
        """)

    def _quick_duel_locked(self, ident):
        row = self.connection.execute('SELECT * FROM quick_duels WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise DuelError("Дуэль не найдена.")
        duel = dict(row)
        duel['state'] = json.loads(duel.pop('state_json'))
        return duel

    def _quick_duel_save_locked(self, duel):
        self.connection.execute('UPDATE quick_duels SET status=?,deadline=?,state_json=? WHERE id=?',
            (duel['status'], duel['deadline'], json.dumps(duel['state'], ensure_ascii=False), duel['id']))

    def _quick_duel_busy_locked(self, chat, players, now):
        return any(self.connection.execute(f"""SELECT 1 FROM quick_duels WHERE chat_id=?
            AND {column} IN (?,?) AND status='active' AND deadline>?""",
            (chat, *players, now)).fetchone() for column in ('creator', 'guest'))

    async def quick_duel_create(self, chat, source, creator, guest, names):
        from database import utc_timestamp
        if chat >= 0 or creator == guest or min(creator, guest) <= 0:
            raise DuelError("Выбери другого участника чата.")
        async with self._lock:
            with self.connection:
                if self.connection.execute('SELECT 1 FROM quick_duels WHERE chat_id=? AND source_id=?',
                                           (chat, source)).fetchone():
                    return None  # duplicate Telegram delivery
                now = utc_timestamp()
                if self._quick_duel_busy_locked(chat, (creator, guest), now):
                    raise DuelError("Кто-то из вас уже участвует в перестрелке в этом чате.")
                if self.connection.execute("""SELECT 1 FROM quick_duels WHERE chat_id=?
                    AND creator=? AND status='pending' AND deadline>?""", (chat, creator, now)).fetchone():
                    raise DuelError("Твой предыдущий вызов ещё ждёт ответа.")
                ident = secrets.token_hex(8)
                state = dict(round=0, fighters=[dict(name=name, hp=1, aim=0, cooldown=False) for name in names],
                             choices=[None, None], last=None, winner=None, reason=None)
                self.connection.execute("""INSERT INTO quick_duels
                    (id,chat_id,source_id,creator,guest,status,deadline,state_json) VALUES(?,?,?,?,?,'pending',?,?)""",
                    (ident, chat, source, creator, guest, now + INVITE_SECONDS, json.dumps(state, ensure_ascii=False)))
                return self._quick_duel_locked(ident)

    async def quick_duel_bind(self, ident, message_id):
        async with self._lock:
            with self.connection:
                if message_id is None:
                    self.connection.execute("UPDATE quick_duels SET status='unpublished' WHERE id=? AND message_id IS NULL AND status='pending'", (ident,))
                else:
                    self.connection.execute('UPDATE quick_duels SET message_id=? WHERE id=? AND message_id IS NULL', (message_id, ident))

    def _quick_duel_expire_locked(self, duel, now):
        if duel['status'] not in ('pending', 'active') or duel['deadline'] > now:
            return False
        state = duel['state']
        if duel['status'] == 'pending':
            duel['status'] = 'expired'
        else:
            duel['status'] = 'finished'
            chosen = [i for i, move in enumerate(state['choices']) if move is not None]
            state.update(reason='timeout', winner=chosen[0] if chosen else None, choices=[None, None])
        self._quick_duel_save_locked(duel)
        return True

    async def quick_duels_due(self):
        from database import utc_timestamp
        async with self._lock:
            return [r[0] for r in self.connection.execute("""SELECT id FROM quick_duels
                WHERE status IN ('pending','active') AND deadline<=? ORDER BY deadline LIMIT 32""", (utc_timestamp(),))]

    async def quick_duel_expire(self, ident):
        from database import utc_timestamp
        async with self._lock:
            with self.connection:
                duel = self._quick_duel_locked(ident)
                return duel if self._quick_duel_expire_locked(duel, utc_timestamp()) else None

    async def quick_duel_action(self, ident, chat, message, user, round_no, action, *, rng=None):
        from database import utc_timestamp
        async with self._lock:
            with self.connection:
                duel = self._quick_duel_locked(ident)
                if (chat, message) != (duel['chat_id'], duel['message_id']):
                    raise DuelError("Кнопка не из сообщения этой дуэли.")
                players = (duel['creator'], duel['guest'])
                if user not in players:
                    raise DuelError("Это не твоя дуэль.")
                now = utc_timestamp()
                self._quick_duel_expire_locked(duel, now)
                status, state = duel['status'], duel['state']
                if status not in ('pending', 'active'):
                    return "Дуэль уже завершена.", duel
                if round_no != state['round']:
                    return "Этот раунд уже закончился.", duel
                if status == 'pending':
                    if user == duel['guest'] and action in ('accept', 'decline'):
                        if action == 'accept':
                            # A pending invite does not reserve the guest. If either
                            # player started another match in the meantime, don't start two.
                            if self._quick_duel_busy_locked(chat, players, now):
                                raise DuelError("Кто-то из вас уже участвует в перестрелке в этом чате.")
                            duel.update(status='active', deadline=now + TURN_SECONDS)
                            state['round'] = 1
                        else:
                            duel['status'] = 'declined'
                    elif user == duel['creator'] and action == 'cancel':
                        duel['status'] = 'cancelled'
                    else:
                        raise DuelError("Эта кнопка для другого участника.")
                else:
                    index = players.index(user)
                    if state['choices'][index] is not None:
                        return "Ход уже принят. Ждём соперника.", None
                    if not action_enabled(state['fighters'][index], action):
                        raise DuelError("Это действие сейчас недоступно.")
                    state['choices'][index] = action
                    if None in state['choices']:
                        self._quick_duel_save_locked(duel)
                        return "Ход принят. Соперник его не видит.", None
                    moves = state['choices']
                    fighters, effects = resolve_round(state['fighters'], moves, rng or random.SystemRandom())
                    state.update(fighters=fighters, choices=[None, None],
                                 last=dict(round=round_no, moves=moves, effects=effects))
                    living = [i for i, fighter in enumerate(fighters) if fighter['hp']]
                    if len(living) != 2 or round_no >= MAX_ROUNDS:
                        duel['status'] = 'finished'
                        state.update(reason='shots' if len(living) != 2 else 'round_limit',
                                     winner=living[0] if len(living) == 1 else None)
                    else:
                        state['round'] += 1
                        duel['deadline'] = now + TURN_SECONDS
                self._quick_duel_save_locked(duel)
                return None, duel
