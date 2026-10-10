"""Saved raid lobbies, exclusive fighter reservations and atomic round rewards."""

import json
import random
import secrets
import time

from arena_engine import BUILTIN_PASSIVES, BUILTIN_SKILLS, validate_skill
from arena_raid_engine import (
    RAID_SIZE,
    RAID_ROUND_SECONDS,
    BOSSES,
    create_raid_state,
    alive_players,
    pair_state,
    resolve_round,
    finish_if_needed,
)
from arena_wasteland import victory_xp
from arena_archprogress import skill_branch

RAID_LOBBY_SECONDS = 600


class RaidMixin:
    def _connect_raids(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_raids (
                token TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, creator_id INTEGER NOT NULL,
                message_id INTEGER, status TEXT NOT NULL DEFAULT 'lobby',
                revision INTEGER NOT NULL DEFAULT 0, round INTEGER NOT NULL DEFAULT 0,
                data_json TEXT, created_at INTEGER NOT NULL, deadline INTEGER NOT NULL,
                finished_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_raids_deadline ON arena_raids(status,deadline);
            CREATE TABLE IF NOT EXISTS arena_raid_players (
                token TEXT NOT NULL REFERENCES arena_raids(token), actor_id INTEGER NOT NULL,
                fighter_id INTEGER NOT NULL, personal INTEGER NOT NULL,
                slave_owner INTEGER NOT NULL,
                PRIMARY KEY(token,actor_id), UNIQUE(token,fighter_id)
            );
            CREATE INDEX IF NOT EXISTS idx_raid_players_user ON arena_raid_players(actor_id,fighter_id);
            CREATE TABLE IF NOT EXISTS arena_raid_loot_pity (
                chat_id INTEGER NOT NULL, actor_id INTEGER NOT NULL, boss_id TEXT NOT NULL,
                misses INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat_id,actor_id,boss_id)
            );
        """)
        columns = {
            r["name"] for r in self.connection.execute("PRAGMA table_info(arena_raids)")
        }
        if "boss_id" not in columns:
            self.connection.execute(
                "ALTER TABLE arena_raids ADD COLUMN boss_id TEXT NOT NULL DEFAULT 'iron'"
            )
        self.connection.commit()

    def _raid_row_locked(self, token):
        raw = self.connection.execute(
            "SELECT * FROM arena_raids WHERE token=?", (token,)
        ).fetchone()
        if not raw:
            raise ValueError("Рейд не найден.")
        row = dict(raw)
        row["participants"] = [
            dict(p)
            for p in self.connection.execute(
                "SELECT * FROM arena_raid_players WHERE token=? ORDER BY actor_id",
                (token,),
            ).fetchall()
        ]
        return row

    def _raid_busy_locked(self, chat, user, exclude="", active_only=False):
        return bool(
            self.connection.execute(
                """SELECT 1 FROM arena_raids r JOIN arena_raid_players p ON p.token=r.token
               WHERE r.chat_id=? AND r.token<>? AND r.status IN ('lobby','active')
               AND (?=0 OR r.status='active') AND (p.actor_id=? OR p.fighter_id=?)""",
                (chat, exclude, int(active_only), user, user),
            ).fetchone()
        )

    def _raid_validate_fighter_locked(self, chat, actor, fighter, personal, token):
        if personal and fighter != actor:
            raise ValueError("Личный персонаж может быть только своим.")
        owner = actor
        if not personal:
            if actor == fighter:
                raw = self.connection.execute(
                    "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                    (chat, actor),
                ).fetchone()
                if not raw:
                    raise ValueError("Вы не состоите в рабстве.")
                owner = int(raw["owner_id"])
            self._arena_require_combat_locked(chat, owner, fighter)
        for user in {actor, fighter}:
            if self._arena_busy_locked(chat, user, raid_exclude=token):
                raise ValueError(
                    "Этот участник или боец уже занят боем, рейдом или забегом."
                )
        return owner

    def _raid_save_locked(self, row, data, status=None):
        status = status or row["status"]
        self.connection.execute(
            """UPDATE arena_raids SET data_json=?,status=?,round=?,deadline=?,
               revision=revision+1,finished_at=? WHERE token=?""",
            (
                json.dumps(data, ensure_ascii=False),
                status,
                data.get("round", row["round"]),
                (
                    int(time.time()) + RAID_ROUND_SECONDS
                    if status == "active"
                    else row["deadline"]
                ),
                int(time.time()) if status in {"finished", "cancelled"} else None,
                row["token"],
            ),
        )

    def _raid_finish_locked(self, row, data):
        # The raid and all grants are saved in the caller's transaction. Replays
        # cannot reach this method once status is finished.
        if row["status"] != "active":
            raise ValueError("Рейд уже закрыт.")
        if data["won"]:
            rng = random.SystemRandom()
            pool = [
                ("skill", s.skill_id, s.rarity, s.name)
                for s in BUILTIN_SKILLS.values()
                if s.class_id != "ragamuffin"
                and not skill_branch(s)
                and "raid_loot" not in s.tags
            ]
            pool += [
                ("passive", p.skill_id, p.rarity, p.name)
                for p in BUILTIN_PASSIVES.values()
            ]
            for key, player in data["players"].items():
                if (
                    player["withdrawn"]
                    or player["reward_blocked"]
                    or player["manual_turns"] < 2
                ):
                    continue
                if not self._raid_player_valid_locked(row, player):
                    continue
                table = "personal_profiles" if player["personal"] else "slave_profiles"
                chat, fighter = row["chat_id"], player["fighter_id"]
                before = self._arena_profile_locked(chat, fighter, player["personal"])[
                    "xp"
                ]
                self._grant_profile_xp_locked(
                    table, chat, fighter, 2 * victory_xp(data["boss"]["level"])
                )
                xp = (
                    self._arena_profile_locked(chat, fighter, player["personal"])["xp"]
                    - before
                )
                francs = 40 + 3 * data["boss"]["level"]
                self._add_francs_locked(chat, player["actor_id"], francs)
                loot = ""
                if row.get("boss_id", "iron") == "lei_heng":
                    pity = self.connection.execute(
                        "SELECT misses FROM arena_raid_loot_pity WHERE chat_id=? AND actor_id=? AND boss_id=?",
                        (chat, player["actor_id"], "lei_heng"),
                    ).fetchone()
                    misses = pity["misses"] if pity else 0
                    dropped = misses >= 4 or rng.random() < 0.2
                    self.connection.execute(
                        """INSERT INTO arena_raid_loot_pity VALUES(?,?,?,?)
                        ON CONFLICT(chat_id,actor_id,boss_id) DO UPDATE SET misses=excluded.misses""",
                        (
                            chat,
                            player["actor_id"],
                            "lei_heng",
                            0 if dropped else misses + 1,
                        ),
                    )
                    if dropped:
                        tractate = BUILTIN_SKILLS["tigerslayer_flurry"]
                        loot = tractate.name
                        self._arena_add_item_locked(
                            chat,
                            player["actor_id"],
                            "skill",
                            tractate.skill_id,
                            tractate.rarity,
                        )
                elif pool and rng.random() < 0.3:
                    kind, content, rarity, loot = rng.choice(pool)
                    self._arena_add_item_locked(
                        chat, player["actor_id"], kind, content, rarity
                    )
                data["rewards"][key] = dict(xp=xp, francs=francs, loot=loot)
        self._raid_save_locked(row, data, "finished")

    def _raid_player_valid_locked(self, row, player):
        if player["personal"]:
            return True
        try:
            self._arena_require_combat_locked(
                row["chat_id"], player["slave_owner"], player["fighter_id"]
            )
        except ValueError:
            return False
        return True

    def _raid_cleanup_locked(self, row):
        if row["status"] != "active":
            return row
        data = json.loads(row["data_json"])
        changed = False
        for key, player in data["players"].items():
            if not player["withdrawn"] and not self._raid_player_valid_locked(
                row, player
            ):
                player.update(withdrawn=True, selected=None, reward_blocked=True)
                data["log"].append(
                    dict(
                        round=data["round"],
                        actor=key,
                        target=key,
                        text="Боец выбыл: владелец или боевой слот изменился.",
                    )
                )
                changed = True
        if changed:
            if finish_if_needed(data):
                self._raid_finish_locked(row, data)
            elif all(p["selected"] is not None for p in alive_players(data).values()):
                self._raid_resolve_locked(row, data)
            else:
                # Cleanup must not renew the remaining players' round timer.
                deadline = row["deadline"]
                self._raid_save_locked(row, data)
                self.connection.execute(
                    "UPDATE arena_raids SET deadline=? WHERE token=?",
                    (deadline, row["token"]),
                )
            return self._raid_row_locked(row["token"])
        return row

    def _raid_resolve_locked(self, row, data):
        _, skills = self._fighter_catalog_locked()
        resolve_round(data, skills)
        if data["finished"]:
            self._raid_finish_locked(row, data)
        else:
            self._raid_save_locked(row, data)

    def _raid_expire_locked(self):
        changed = []
        now = int(time.time())
        rows = self.connection.execute(
            "SELECT token FROM arena_raids WHERE status IN ('lobby','active')"
        ).fetchall()
        for raw in rows:
            original = self._raid_row_locked(raw["token"])
            row = self._raid_cleanup_locked(original)
            if row["status"] == "lobby" and (
                row["deadline"] <= now
                or row["message_id"] is None
                and row["created_at"] + 60 <= now
            ):
                self.connection.execute(
                    "UPDATE arena_raids SET status='cancelled',revision=revision+1,finished_at=? WHERE token=?",
                    (now, row["token"]),
                )
            elif row["status"] == "active" and row["deadline"] <= now:
                self._raid_resolve_locked(row, json.loads(row["data_json"]))
            fresh = self._raid_row_locked(row["token"])
            if fresh["revision"] != original["revision"]:
                changed.append(fresh)
        return changed

    async def arena_raid_expire(self):
        async with self._lock:
            try:
                changed = self._raid_expire_locked()
                self.connection.commit()
                return changed
            except Exception:
                self.connection.rollback()
                raise

    async def arena_raid_get(self, token):
        async with self._lock:
            return self._raid_row_locked(token)

    async def arena_raid_list(self, chat, actor):
        async with self._lock:
            return [
                dict(r)
                for r in self.connection.execute(
                    """SELECT DISTINCT r.token,r.status,r.round FROM arena_raids r
                   JOIN arena_raid_players p ON p.token=r.token WHERE r.chat_id=?
                   AND p.actor_id=? ORDER BY r.created_at DESC LIMIT 5""",
                    (chat, actor),
                ).fetchall()
            ]

    async def arena_raid_set_message(self, token, message):
        async with self._lock:
            self.connection.execute(
                "UPDATE arena_raids SET message_id=? WHERE token=?", (message, token)
            )
            self.connection.commit()

    async def arena_raid_create(self, chat, actor, boss_id="iron"):
        if boss_id not in BOSSES:
            raise ValueError("Неизвестный босс.")
        async with self._lock:
            try:
                self._raid_expire_locked()
                self._arena_expire_locked()
                self._raid_validate_fighter_locked(chat, actor, actor, True, "")
                self._arena_profile_locked(chat, actor, True)
                now, token = int(time.time()), secrets.token_urlsafe(12)
                self.connection.execute(
                    "INSERT INTO arena_raids(token,chat_id,creator_id,created_at,deadline,boss_id) VALUES(?,?,?,?,?,?)",
                    (token, chat, actor, now, now + RAID_LOBBY_SECONDS, boss_id),
                )
                self.connection.execute(
                    "INSERT INTO arena_raid_players VALUES(?,?,?,?,?)",
                    (token, actor, actor, 1, actor),
                )
                self.connection.commit()
                return self._raid_row_locked(token)
            except Exception:
                self.connection.rollback()
                raise

    async def arena_raid_setup(
        self, token, actor, action, fighter=0, personal=True, expected_revision=None
    ):
        async with self._lock:
            try:
                row = self._raid_row_locked(token)
                if row["status"] != "lobby":
                    raise ValueError("Состав рейда уже закрыт.")
                if row["deadline"] <= int(time.time()):
                    raise ValueError("Время сбора рейда истекло.")
                if (
                    expected_revision is not None
                    and row["revision"] != expected_revision
                ):
                    raise ValueError(
                        "Состав рейда изменился. Обновите его перед стартом."
                    )
                members = row["participants"]
                current = next((p for p in members if p["actor_id"] == actor), None)
                if action == "join":
                    if type(personal) is not bool or type(fighter) is not int:
                        raise ValueError("Некорректный выбор бойца.")
                    fighter = fighter or actor
                    if not current and len(members) >= RAID_SIZE:
                        raise ValueError("Все три места уже заняты.")
                    if any(
                        p["fighter_id"] == fighter and p["actor_id"] != actor
                        for p in members
                    ):
                        raise ValueError("Этот боец уже занимает место в рейде.")
                    owner = self._raid_validate_fighter_locked(
                        row["chat_id"], actor, fighter, personal, token
                    )
                    self._arena_profile_locked(row["chat_id"], fighter, personal)
                    self.connection.execute(
                        """INSERT INTO arena_raid_players VALUES(?,?,?,?,?) ON CONFLICT(token,actor_id)
                           DO UPDATE SET fighter_id=excluded.fighter_id,personal=excluded.personal,slave_owner=excluded.slave_owner""",
                        (token, actor, fighter, int(personal), owner),
                    )
                elif action == "leave":
                    if not current:
                        raise ValueError("Вы не участвуете в рейде.")
                    if actor == row["creator_id"]:
                        raise ValueError("Создатель может отменить сбор рейда.")
                    self.connection.execute(
                        "DELETE FROM arena_raid_players WHERE token=? AND actor_id=?",
                        (token, actor),
                    )
                elif action in {"start", "cancel"}:
                    if actor != row["creator_id"]:
                        raise ValueError("Это доступно только создателю рейда.")
                    if action == "cancel":
                        self.connection.execute(
                            "UPDATE arena_raids SET status='cancelled',finished_at=? WHERE token=?",
                            (int(time.time()), token),
                        )
                    else:
                        if not 1 <= len(members) <= RAID_SIZE:
                            raise ValueError(
                                "Для старта нужны от одного до трёх участников."
                            )
                        sources = []
                        for p in members:
                            self._raid_validate_fighter_locked(
                                row["chat_id"],
                                p["actor_id"],
                                p["fighter_id"],
                                bool(p["personal"]),
                                token,
                            )
                            self._arena_require_choice_locked(
                                row["chat_id"], p["fighter_id"], bool(p["personal"])
                            )
                            sources.append(
                                self._arena_source_locked(
                                    row["chat_id"],
                                    p["fighter_id"],
                                    p["actor_id"],
                                    not p["personal"]
                                    and p["fighter_id"] != p["actor_id"],
                                    bool(p["personal"]),
                                )
                            )
                        classes, skills = self._fighter_catalog_locked()
                        data = create_raid_state(
                            members, sources, classes, skills, row["boss_id"]
                        )
                        self._raid_save_locked(row, data, "active")
                else:
                    raise ValueError("Действие недоступно.")
                if action != "start":
                    self.connection.execute(
                        "UPDATE arena_raids SET revision=revision+1 WHERE token=?",
                        (token,),
                    )
                self.connection.commit()
                return self._raid_row_locked(token)
            except Exception:
                self.connection.rollback()
                raise

    async def arena_raid_action(self, token, actor, round_number, skill):
        async with self._lock:
            try:
                row = self._raid_cleanup_locked(self._raid_row_locked(token))
                # Commit external ownership cleanup even if the queued click is stale.
                self.connection.commit()
                if row["status"] != "active":
                    raise ValueError("Рейд завершён.")
                if row["deadline"] <= int(time.time()):
                    self._raid_resolve_locked(row, json.loads(row["data_json"]))
                    self.connection.commit()
                    raise ValueError("Время выбора истекло. Обновите рейд.")
                data = json.loads(row["data_json"])
                if type(round_number) is not int or round_number != data["round"]:
                    raise ValueError("Раунд уже изменился. Обновите рейд.")
                player = alive_players(data).get(str(actor))
                if not player:
                    raise ValueError("Вы не управляете живым бойцом этого рейда.")
                if player["selected"] is not None and skill != "surrender":
                    raise ValueError("Действие на этот раунд уже выбрано.")
                if skill == "surrender":
                    player.update(withdrawn=True, reward_blocked=True, selected=None)
                    data["log"].append(
                        dict(
                            round=data["round"],
                            actor=str(actor),
                            target=str(actor),
                            text="Участник покинул бой. Без награды.",
                        )
                    )
                else:
                    if not isinstance(skill, str):
                        raise ValueError("Некорректный навык.")
                    if skill != "defend":
                        _, skills = self._fighter_catalog_locked()
                        validate_skill(
                            pair_state(player["fighter"], data["boss"]),
                            "a",
                            skill,
                            skills,
                        )
                    player["selected"] = skill
                if finish_if_needed(data):
                    self._raid_finish_locked(row, data)
                elif all(
                    p["selected"] is not None for p in alive_players(data).values()
                ):
                    self._raid_resolve_locked(row, data)
                else:
                    # Readiness changes a revision, NOT the round or its deadline.
                    self._raid_save_locked(row, data)
                    self.connection.execute(
                        "UPDATE arena_raids SET deadline=? WHERE token=?",
                        (row["deadline"], token),
                    )
                self.connection.commit()
                return self._raid_row_locked(token)
            except Exception:
                self.connection.rollback()
                raise
