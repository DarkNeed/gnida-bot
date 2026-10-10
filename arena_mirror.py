"""Five-floor saved PvE runs, serialized by the shared database lock."""

import json
import random
import secrets
import time

from arena_engine import create_battle_state, BUILTIN_SKILLS, BUILTIN_PASSIVES
from arena_wasteland import enemy_source, victory_xp
from arena_mirror_effects import GIFTS, NORMAL_GIFTS, apply_gifts

MIRROR_FLOORS = 5


class MirrorMixin:
    def _connect_mirror(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_mirror_runs (
                token TEXT PRIMARY KEY, chat_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL, fighter_id INTEGER NOT NULL,
                personal INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 0, data_json TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_one_run
            ON arena_mirror_runs(chat_id,actor_id) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_mirror_fighter
            ON arena_mirror_runs(chat_id,fighter_id,status);
        """)
        self.connection.commit()

    def _mirror_row_locked(self, token):
        raw = self.connection.execute(
            "SELECT * FROM arena_mirror_runs WHERE token=?", (token,)
        ).fetchone()
        if not raw:
            raise ValueError("Забег не найден.")
        return dict(raw)

    def _mirror_save_locked(self, row, data, status=None):
        self.connection.execute(
            "UPDATE arena_mirror_runs SET data_json=?,status=?,revision=revision+1,updated_at=? WHERE token=?",
            (
                json.dumps(data, ensure_ascii=False),
                status or row["status"],
                int(time.time()),
                row["token"],
            ),
        )

    def _mirror_owner_valid_locked(self, row):
        if row["personal"]:
            return True
        data = json.loads(row["data_json"])
        return (
            self._arena_owns_locked(
                row["chat_id"], data["slave_owner"], row["fighter_id"]
            )
            and self._arena_combat_slot_locked(
                row["chat_id"], data["slave_owner"], row["fighter_id"]
            )
            is not None
        )

    def _mirror_close_locked(self, row, reason):
        data = json.loads(row["data_json"])
        data.update(phase="ended", result=reason)
        # No refunds/rewards on abandonment, and no dangling busy battle.
        self.connection.execute(
            "UPDATE arena_battles SET status='cancelled',finished_at=?,revision=revision+1 WHERE token=? AND status='active'",
            (int(time.time()), data["battle_token"]),
        )
        self._mirror_save_locked(row, data, "cancelled")

    def _mirror_cleanup_locked(self, chat):
        for raw in self.connection.execute(
            "SELECT * FROM arena_mirror_runs WHERE chat_id=? AND status='active'",
            (chat,),
        ).fetchall():
            row = dict(raw)
            if not self._mirror_owner_valid_locked(row):
                self._mirror_close_locked(
                    row, "Владелец бойца сменился или боевой слот снят. Забег закрыт."
                )

    def _mirror_public_locked(self, row):
        data = json.loads(row["data_json"])
        if row["status"] == "active" and data["phase"] == "combat":
            battle = self._arena_row_locked(data["battle_token"])
            side = json.loads(battle["state_json"])["sides"]["a"]
            data.update(hp=side["hp"], resource=side["resource"])
        gifts = [
            dict(id=k, name=GIFTS[k][0], description=GIFTS[k][1]) for k in data["gifts"]
        ]
        choices = [
            dict(id=k, name=GIFTS[k][0], description=GIFTS[k][1])
            for k in data.get("choices", [])
        ]
        return dict(
            token=row["token"],
            chat_id=row["chat_id"],
            actor_id=row["actor_id"],
            fighter_id=row["fighter_id"],
            personal=bool(row["personal"]),
            status=row["status"],
            revision=row["revision"],
            **{
                k: data[k]
                for k in (
                    "phase",
                    "floor",
                    "battle_token",
                    "hp",
                    "resource",
                    "max_hp",
                    "resource_max",
                    "shards",
                    "result",
                    "xp",
                    "francs",
                    "loot",
                    "event",
                )
            },
            gifts=gifts,
            choices=choices,
            total_floors=MIRROR_FLOORS
        )

    def _mirror_battle_locked(self, row, data, first=False):
        source = data["source"]
        enemy = enemy_source(
            source["level"] + data["floor"] - 1, data.get("previous_class")
        )
        classes, skills = self._fighter_catalog_locked()
        state = create_battle_state(source, enemy, classes=classes, skills=skills)
        a, b = state["sides"].values()
        if not first:
            a["hp"] = min(a["stats"]["max_hp"], data["hp"])
            a["resource"] = min(a["stats"]["resource_max"], data["resource"])
        apply_gifts(a, data["gifts"])
        if data["floor"] == MIRROR_FLOORS:
            for stat in (
                "physical_attack",
                "magic_attack",
                "physical_defense",
                "magic_defense",
            ):
                b["stats"][stat] = round(b["stats"][stat] * 1.15, 2)
            b["stats"]["max_hp"] = max(1, round(b["stats"]["max_hp"] * 1.4))
            b["hp"] = b["stats"]["max_hp"]
        state.update(mirror_token=row["token"], turn_timer_seconds=0)
        token = secrets.token_urlsafe(16)
        self.connection.execute(
            """INSERT INTO arena_battles(token,chat_id,mode,a_owner,b_owner,a_fighter,b_fighter,a_control,b_accepted,status,state_json,floor,created_at,deadline,personal_solo)
            VALUES(?,?,'wasteland',?,0,?,0,?,1,'active',?,?,?,0,?)""",
            (
                token,
                row["chat_id"],
                row["actor_id"],
                row["fighter_id"],
                int(source["controlled"]),
                json.dumps(state, ensure_ascii=False),
                data["floor"],
                int(time.time()),
                row["personal"],
            ),
        )
        data.update(
            phase="combat",
            battle_token=token,
            hp=a["hp"],
            resource=a["resource"],
            max_hp=a["stats"]["max_hp"],
            resource_max=a["stats"]["resource_max"],
            previous_class=enemy["class_id"],
        )

    async def arena_mirror_start(self, chat, actor, fighter=None, personal=True):
        async with self._lock:
            self._mirror_cleanup_locked(chat)
            self.connection.commit()
            fighter = fighter or actor
            if self._arena_busy_locked(chat, actor) or self._arena_busy_locked(
                chat, fighter
            ):
                raise ValueError("Сначала завершите текущий бой или забег.")
            slave_owner = actor
            if personal and fighter != actor:
                raise ValueError("Личный персонаж может быть только своим.")
            if not personal:
                if fighter == actor:
                    owner = self.connection.execute(
                        "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                        (chat, fighter),
                    ).fetchone()
                    if not owner:
                        raise ValueError("Вы не состоите в рабстве.")
                    slave_owner = int(owner["owner_id"])
                self._arena_require_combat_locked(chat, slave_owner, fighter)
            self._arena_require_choice_locked(chat, fighter, personal)
            source = self._arena_source_locked(
                chat, fighter, actor, not personal and fighter != actor, personal
            )
            source["granted_skills"] = sorted(source["granted_skills"])
            data = dict(
                source=source,
                slave_owner=slave_owner,
                phase="combat",
                floor=1,
                gifts=[],
                choices=[],
                shards=20,
                xp=0,
                francs=0,
                loot="",
                result="",
                event="",
                battle_token="",
                hp=0,
                resource=0,
                max_hp=0,
                resource_max=0,
            )
            token = secrets.token_urlsafe(16)
            now = int(time.time())
            try:
                self.connection.execute(
                    "INSERT INTO arena_mirror_runs(token,chat_id,actor_id,fighter_id,personal,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        token,
                        chat,
                        actor,
                        fighter,
                        int(personal),
                        json.dumps(data),
                        now,
                        now,
                    ),
                )
                row = self._mirror_row_locked(token)
                self._mirror_battle_locked(row, data, first=True)
                self._mirror_save_locked(row, data)
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self._mirror_public_locked(self._mirror_row_locked(token))

    def _mirror_finish_battle_locked(self, battle, state):
        row = self._mirror_row_locked(state["mirror_token"])
        data = json.loads(row["data_json"])
        if (
            row["status"] != "active"
            or data["phase"] != "combat"
            or data["battle_token"] != battle["token"]
        ):
            raise ValueError("Этот этап уже закрыт.")
        won = state["winner"] == "a" and state.get("finish_reason") not in {
            "surrender",
            "timeout",
            "turn_limit",
        }
        reward = 0
        status = "active"
        if won:
            table = "personal_profiles" if row["personal"] else "slave_profiles"
            before = self._arena_profile_locked(
                row["chat_id"], row["fighter_id"], bool(row["personal"])
            )["xp"]
            self._grant_profile_xp_locked(
                table,
                row["chat_id"],
                row["fighter_id"],
                victory_xp(state["sides"]["b"]["level"]),
            )
            reward = (
                self._arena_profile_locked(
                    row["chat_id"], row["fighter_id"], bool(row["personal"])
                )["xp"]
                - before
            )
            data["xp"] += reward
            if not row["personal"]:
                self._settle_materials_locked(row["chat_id"], data["slave_owner"])
                self._grant_profile_xp_locked(
                    "owner_profiles", row["chat_id"], data["slave_owner"], 6
                )
            data.update(
                hp=state["sides"]["a"]["hp"],
                resource=min(
                    data["resource_max"], state["sides"]["a"]["resource"] + 30
                ),
                shards=data["shards"] + 15,
            )
            if data["floor"] == MIRROR_FLOORS:
                status = "finished"
                data.update(
                    phase="ended",
                    result="Зеркало пройдено! Дары остались по ту сторону.",
                )
                data["francs"] = 50 + 5 * data["source"]["level"]
                self._add_francs_locked(row["chat_id"], row["actor_id"], data["francs"])
                if random.SystemRandom().random() < 0.30:
                    pool = [
                        ("skill", s.skill_id, s.rarity, s.name)
                        for s in BUILTIN_SKILLS.values()
                        if s.class_id != "ragamuffin"
                    ]
                    pool += [
                        ("passive", p.skill_id, p.rarity, p.name)
                        for p in BUILTIN_PASSIVES.values()
                    ]
                    kind, content, rarity, name = random.SystemRandom().choice(pool)
                    self._arena_add_item_locked(
                        row["chat_id"], row["actor_id"], kind, content, rarity
                    )
                    data["loot"] = name
            else:
                pool = [k for k in NORMAL_GIFTS if k not in data["gifts"]]
                data.update(
                    phase="gift" if pool else "route",
                    choices=random.SystemRandom().sample(pool, min(3, len(pool))),
                )
        else:
            status = "lost"
            data.update(
                phase="ended",
                hp=state["sides"]["a"]["hp"],
                resource=state["sides"]["a"]["resource"],
                result="Забег завершён. Опыт за уже пройденные этажи сохранён; награды за босса нет.",
            )
        self._mirror_save_locked(row, data, status)
        state.update(
            rewards={"a": max(0, reward)},
            payout=data["francs"] if status == "finished" else 0,
        )
        self.connection.execute(
            "UPDATE arena_battles SET status='finished',finished_at=? WHERE id=?",
            (int(time.time()), battle["id"]),
        )

    async def arena_mirror_get(self, token, actor):
        async with self._lock:
            row = self._mirror_row_locked(token)
            if row["actor_id"] != actor:
                raise ValueError("Это не ваш забег.")
            self._mirror_cleanup_locked(row["chat_id"])
            self.connection.commit()
            return self._mirror_public_locked(self._mirror_row_locked(token))

    async def arena_mirror_list(self, chat, actor):
        async with self._lock:
            self._mirror_cleanup_locked(chat)
            rows = self.connection.execute(
                "SELECT * FROM arena_mirror_runs WHERE chat_id=? AND actor_id=? ORDER BY created_at DESC,rowid DESC LIMIT 5",
                (chat, actor),
            ).fetchall()
            self.connection.commit()
            return [self._mirror_public_locked(dict(r)) for r in rows]

    async def arena_mirror_action(self, token, actor, revision, action, value=""):
        async with self._lock:
            row = self._mirror_row_locked(token)
            if row["actor_id"] != actor:
                raise ValueError("Это не ваш забег.")
            self._mirror_cleanup_locked(row["chat_id"])
            self.connection.commit()
            row = self._mirror_row_locked(token)
            if row["status"] != "active" or row["revision"] != revision:
                raise ValueError("Забег изменился. Обновите окно.")
            data = json.loads(row["data_json"])
            try:
                if action == "abandon":
                    self._mirror_close_locked(
                        row, "Забег оставлен. Награды за босса нет."
                    )
                elif (
                    action == "gift"
                    and data["phase"] == "gift"
                    and value in data["choices"]
                ):
                    data["gifts"].append(value)
                    data.update(phase="route", choices=[])
                    self._mirror_save_locked(row, data)
                elif (
                    action == "route"
                    and data["phase"] == "route"
                    and value in {"rest", "event", "merchant"}
                ):
                    data["phase"] = value
                    if value == "rest":
                        data["hp"] = min(
                            data["max_hp"],
                            data["hp"] + max(1, round(data["max_hp"] * 0.35)),
                        )
                        data["resource"] = min(
                            data["resource_max"], data["resource"] + 35
                        )
                        data.update(
                            phase="ready",
                            result="Отдых: восстановлены 35% HP и 35 энергии.",
                        )
                    elif value == "event":
                        data["event"] = random.SystemRandom().choice(["altar", "chest"])
                    self._mirror_save_locked(row, data)
                elif (
                    action == "event"
                    and data["phase"] == "event"
                    and value in {"risk", "safe"}
                ):
                    if value == "risk":
                        if data["event"] == "altar":
                            cost = max(1, round(data["max_hp"] * 0.20))
                            if data["hp"] <= cost or "risk" in data["gifts"]:
                                raise ValueError(
                                    "Для жертвы не хватает HP или дар уже получен."
                                )
                            data["hp"] -= cost
                            data["gifts"].append("risk")
                            data["result"] = (
                                "Алтарь принял жертву. Урон +20%, обе защиты −15% до конца забега."
                            )
                        else:
                            success = random.SystemRandom().random() < 0.6
                            if success:
                                data["shards"] += 30
                            else:
                                data["hp"] = max(
                                    1, data["hp"] - max(1, round(data["max_hp"] * 0.15))
                                )
                            data["result"] = (
                                "В сундуке 30 осколков!"
                                if success
                                else "Ловушка: потеряно 15% максимального HP."
                            )
                    else:
                        data["result"] = "Ты прошёл мимо, ничего не потеряв."
                    data["phase"] = "ready"
                    self._mirror_save_locked(row, data)
                elif (
                    action == "shop"
                    and data["phase"] == "merchant"
                    and value in {"heal", "energy", "gift", "leave"}
                ):
                    if value != "leave":
                        if data.get("shop_bought") == data["floor"]:
                            raise ValueError("Одна покупка за эту встречу.")
                        price = 30 if value == "gift" else 20
                        if data["shards"] < price:
                            raise ValueError("Не хватает осколков.")
                        if value == "gift":
                            pool = [k for k in NORMAL_GIFTS if k not in data["gifts"]]
                            if not pool:
                                raise ValueError("Все дары уже получены.")
                            data["gifts"].append(random.SystemRandom().choice(pool))
                        elif value == "heal":
                            data["hp"] = min(
                                data["max_hp"],
                                data["hp"] + max(1, round(data["max_hp"] * 0.50)),
                            )
                        else:
                            data["resource"] = min(
                                data["resource_max"], data["resource"] + 60
                            )
                        data["shards"] -= price
                        data["shop_bought"] = data["floor"]
                    data.update(phase="ready", result="Торговец остался позади.")
                    self._mirror_save_locked(row, data)
                elif action == "next" and data["phase"] == "ready":
                    data["floor"] += 1
                    self._mirror_battle_locked(row, data)
                    self._mirror_save_locked(row, data)
                else:
                    raise ValueError("Действие недоступно на этом этапе.")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self._mirror_public_locked(self._mirror_row_locked(token))
