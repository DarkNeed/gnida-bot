"""Persistent merchant visits, atomic franc purchases and transferable inventory."""

from __future__ import annotations
import json
import random
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from arena_engine import (
    BUILTIN_PASSIVES,
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    MAX_FIGHTER_LEVEL,
    MAX_PASSIVE_SKILLS,
    MAX_LEARNED_ACTIVE_SKILLS,
    MAX_LEARNED_PASSIVE_SKILLS,
    PassiveSkill,
    RARITY_LABELS,
    fighter_xp_limit,
    normalize_loadout,
    unlocked_skill_ids,
)

MSK = timezone(timedelta(hours=3))
MERCHANT_DURATION = 2 * 3600
MERCHANT_OPEN_HOUR = 10
MERCHANT_CLOSE_HOUR = 22
MERCHANT_WINDOWS = ((1, MERCHANT_OPEN_HOUR, 13), (2, 15, 20))
CLASS_SCROLL_CHANCE = 0.03
PRICES = {"common": 80, "uncommon": 140, "rare": 260, "epic": 500}
CLASS_PRICES = {"common": 500, "uncommon": 750, "rare": 1200, "epic": 2000}
WEIGHTS = {"common": 6, "uncommon": 3, "rare": 1, "epic": 0.2}


def market_now() -> int:
    return int(time.time())


def merchant_is_open(now: int) -> bool:
    return (
        MERCHANT_OPEN_HOUR
        <= datetime.fromtimestamp(now, MSK).hour
        < MERCHANT_CLOSE_HOUR
    )


class ArenaMarketMixin:
    def _connect_arena_market(self):
        for table in ("slave_profiles", "personal_profiles"):
            self._ensure_column(table, "passive_loadout", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(table, "skills_reset", "INTEGER NOT NULL DEFAULT 0")
            for kind in ("skill", "passive"):
                self._ensure_column(table, kind + "_memory", "TEXT DEFAULT NULL")
                self._ensure_column(table, kind + "_seen", "TEXT NOT NULL DEFAULT '[]'")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS arena_inventory(
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL, kind TEXT NOT NULL, content_id TEXT NOT NULL,
                rarity TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
                UNIQUE(chat_id,owner_id,kind,content_id)
            );
            CREATE TABLE IF NOT EXISTS arena_learned(
                chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, personal INTEGER NOT NULL,
                kind TEXT NOT NULL, content_id TEXT NOT NULL,
                PRIMARY KEY(chat_id,user_id,personal,kind,content_id)
            );
            CREATE TABLE IF NOT EXISTS arena_merchant_visits(
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                day TEXT NOT NULL, visit INTEGER NOT NULL, starts INTEGER NOT NULL,
                ends INTEGER NOT NULL, notified INTEGER NOT NULL DEFAULT 0,
                UNIQUE(chat_id,day,visit)
            );
            CREATE TABLE IF NOT EXISTS arena_merchant_offers(
                id INTEGER PRIMARY KEY AUTOINCREMENT, visit_id INTEGER NOT NULL,
                kind TEXT NOT NULL, content_id TEXT NOT NULL, rarity TEXT NOT NULL,
                price INTEGER NOT NULL, per_user INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS arena_merchant_purchases(
                offer_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL, PRIMARY KEY(offer_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS arena_market_migrations(name TEXT PRIMARY KEY);
        """)
        if not self.connection.execute(
            "SELECT 1 FROM arena_market_migrations WHERE name='inventory_v1'"
        ).fetchone():
            for row in self.connection.execute(
                "SELECT * FROM owner_profiles"
            ).fetchall():
                for column, kind, content in (
                    ("healing_potions", "potion", "healing"),
                    ("candies", "candy", "experience"),
                ):
                    if row[column] > 0:
                        self._arena_add_item_locked(
                            row["chat_id"],
                            row["user_id"],
                            kind,
                            content,
                            "common",
                            row[column],
                        )
            self.connection.execute(
                "UPDATE owner_profiles SET healing_potions=0,candies=0"
            )
            classes, _ = self._fighter_catalog_locked()
            for table in ("slave_profiles", "personal_profiles"):
                self.connection.execute(
                    f"UPDATE {table} SET level=MIN(level,?),xp=MIN(xp,?)",
                    (MAX_FIGHTER_LEVEL, fighter_xp_limit()),
                )
                for row in self.connection.execute(
                    f"SELECT chat_id,user_id,class_id FROM {table}"
                ).fetchall():
                    cls = classes.get(row["class_id"])
                    if cls and cls.passives:
                        defaults = [
                            f"inherent:{cls.class_id}:{i}"
                            for i in range(min(MAX_PASSIVE_SKILLS, len(cls.passives)))
                        ]
                        self.connection.execute(
                            f"UPDATE {table} SET passive_loadout=? WHERE chat_id=? AND user_id=?",
                            (json.dumps(defaults), row["chat_id"], row["user_id"]),
                        )
            self.connection.execute(
                "INSERT INTO arena_market_migrations VALUES('inventory_v1')"
            )
        if not self.connection.execute(
            "SELECT 1 FROM arena_market_migrations WHERE name='merchant_hours_10_22_v1'"
        ).fetchone():
            # Keep offer IDs, purchases and notification claims when moving old
            # unexpired visits into the new hours. Never revive expired visits.
            for row in self.connection.execute(
                "SELECT * FROM arena_merchant_visits WHERE ends>?", (market_now(),)
            ).fetchall():
                day = datetime.fromisoformat(row["day"]).date()
                midnight = int(
                    datetime.combine(day, datetime.min.time(), tzinfo=MSK).timestamp()
                )
                _, lo, hi = next(w for w in MERCHANT_WINDOWS if w[0] == row["visit"])
                starts = max(
                    midnight + lo * 3600, min(row["starts"], midnight + hi * 3600)
                )
                ends = starts + MERCHANT_DURATION
                if (starts, ends) != (row["starts"], row["ends"]):
                    self.connection.execute(
                        "UPDATE arena_merchant_visits SET starts=?,ends=? WHERE id=?",
                        (starts, ends, row["id"]),
                    )
            self.connection.execute(
                "INSERT INTO arena_market_migrations VALUES('merchant_hours_10_22_v1')"
            )
        self.connection.commit()

    def _arena_add_item_locked(self, chat, owner, kind, content, rarity, quantity=1):
        self.connection.execute(
            """INSERT INTO arena_inventory(chat_id,owner_id,kind,content_id,rarity,quantity)
            VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id,owner_id,kind,content_id)
            DO UPDATE SET quantity=quantity+excluded.quantity""",
            (chat, owner, kind, content, rarity, quantity),
        )

    def _arena_consume_item_locked(self, row):
        if row["quantity"] > 1:
            self.connection.execute(
                "UPDATE arena_inventory SET quantity=quantity-1 WHERE id=?",
                (row["id"],),
            )
        else:
            self.connection.execute(
                "DELETE FROM arena_inventory WHERE id=?", (row["id"],)
            )

    def _arena_item_locked(self, chat, actor, item):
        row = self.connection.execute(
            "SELECT * FROM arena_inventory WHERE id=? AND chat_id=? AND owner_id=?",
            (item, chat, actor),
        ).fetchone()
        if not row:
            raise ValueError("Предмета нет в твоём инвентаре этого чата.")
        return row

    def _arena_learned_locked(self, chat, user, personal, kind):
        return {
            r["content_id"]
            for r in self.connection.execute(
                "SELECT content_id FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=? AND kind=?",
                (chat, user, int(personal), kind),
            )
        }

    def _arena_grants_locked(self, chat, user, personal):
        profile = self._arena_profile_locked(chat, user, personal)
        learned = self._arena_learned_locked(chat, user, personal, "skill")
        return learned | (
            set()
            if profile["skills_reset"]
            else self._granted_content_locked(chat, user, "skill")
        )

    def _arena_memory_locked(self, chat, user, personal, kind, eligible, profile=None):
        """Stable capped memory; overflow remains available, never silently deleted.

        Only newly unlocked class skills auto-fill free slots. Forgetting a skill
        does not immediately relearn it or another previously seen skill.
        """
        profile = profile or self._arena_profile_locked(chat, user, personal)
        table = "personal_profiles" if personal else "slave_profiles"
        column = kind + "_memory"
        limit = (
            MAX_LEARNED_ACTIVE_SKILLS if kind == "skill" else MAX_LEARNED_PASSIVE_SKILLS
        )
        eligible = list(dict.fromkeys(eligible))
        previous = profile[column]
        seen = set(json.loads(profile[kind + "_seen"]))
        if previous is None:
            equipped = json.loads(
                profile["loadout" if kind == "skill" else "passive_loadout"]
            )
            priority = (["bum_punch"] if kind == "skill" else []) + equipped
            priority += sorted(self._arena_learned_locked(chat, user, personal, kind))
            priority += eligible
            memory = [k for k in dict.fromkeys(priority) if k in eligible][:limit]
        else:
            memory = [k for k in dict.fromkeys(json.loads(previous)) if k in eligible][
                :limit
            ]
            for key in eligible:
                if key not in seen and key not in memory and len(memory) < limit:
                    memory.append(key)
        seen.update(eligible)
        encoded, encoded_seen = json.dumps(memory), json.dumps(sorted(seen))
        if previous != encoded or profile[kind + "_seen"] != encoded_seen:
            self.connection.execute(
                f"UPDATE {table} SET {column}=?,{kind}_seen=? WHERE chat_id=? AND user_id=?",
                (encoded, encoded_seen, chat, user),
            )
        return memory

    def _arena_known_skills_locked(self, chat, user, personal, profile=None):
        profile = profile or self._arena_profile_locked(chat, user, personal)
        _, skills = self._fighter_catalog_locked()
        eligible = unlocked_skill_ids(
            profile["class_id"],
            profile["level"],
            skills,
            self._arena_grants_locked(chat, user, personal),
        )
        return self._arena_memory_locked(
            chat, user, personal, "skill", eligible, profile
        )

    def _arena_remember_locked(self, chat, user, personal, kind, content):
        profile = self._arena_profile_locked(chat, user, personal)
        memory = json.loads(profile[kind + "_memory"] or "[]")
        limit = (
            MAX_LEARNED_ACTIVE_SKILLS if kind == "skill" else MAX_LEARNED_PASSIVE_SKILLS
        )
        if content not in memory:
            if len(memory) >= limit:
                raise ValueError(
                    f"Максимум {limit} изученных {'активных' if kind == 'skill' else 'пассивных'} навыков. Сначала забудь один. Трактат не потрачен."
                )
            memory.append(content)
        seen = set(json.loads(profile[kind + "_seen"])) | {content}
        table = "personal_profiles" if personal else "slave_profiles"
        self.connection.execute(
            f"UPDATE {table} SET {kind}_memory=?,{kind}_seen=? WHERE chat_id=? AND user_id=?",
            (json.dumps(memory), json.dumps(sorted(seen)), chat, user),
        )

    def _arena_passive_catalog_locked(
        self, chat, user, personal, profile=None, all_available=False
    ):
        profile = profile or self._arena_profile_locked(chat, user, personal)
        classes, _ = self._fighter_catalog_locked()
        cls = classes.get(profile["class_id"], FIGHTER_CLASSES["ragamuffin"])
        available = {
            k: asdict(BUILTIN_PASSIVES[k])
            for k in self._arena_learned_locked(chat, user, personal, "passive")
            if k in BUILTIN_PASSIVES
        }
        for i, item in enumerate(cls.passives):
            key = f"inherent:{cls.class_id}:{i}"
            available[key] = asdict(
                PassiveSkill(
                    key, item.get("name", f"Пассивка класса {i+1}"), (item,), cls.rarity
                )
            )
        unseen_inherent = [
            k
            for k in available
            if k.startswith(f"inherent:{cls.class_id}:")
            and k not in set(json.loads(profile["passive_seen"]))
        ]
        memory = self._arena_memory_locked(
            chat, user, personal, "passive", available, profile
        )
        # Fill free slots only on first discovery, never repeatedly re-equip a
        # passive the player deliberately removed, and never replace their build.
        selected = [
            k
            for k in dict.fromkeys(json.loads(profile["passive_loadout"]))
            if k in memory
        ][:MAX_PASSIVE_SKILLS]
        for key in unseen_inherent:
            if (
                key in memory
                and key not in selected
                and len(selected) < MAX_PASSIVE_SKILLS
            ):
                selected.append(key)
        if selected != json.loads(profile["passive_loadout"]):
            table = "personal_profiles" if personal else "slave_profiles"
            self.connection.execute(
                f"UPDATE {table} SET passive_loadout=? WHERE chat_id=? AND user_id=?",
                (json.dumps(selected), chat, user),
            )
        return available if all_available else {k: available[k] for k in memory}

    def _arena_selected_passives_locked(self, chat, user, personal, profile=None):
        profile = profile or self._arena_profile_locked(chat, user, personal)
        available = self._arena_passive_catalog_locked(chat, user, personal, profile)
        profile = self._arena_profile_locked(chat, user, personal)
        return [
            available[k]
            for k in dict.fromkeys(json.loads(profile["passive_loadout"]))
            if k in available
        ][:MAX_PASSIVE_SKILLS]

    def _arena_shop_catalog_locked(self):
        classes, skills = self._fighter_catalog_locked()
        public_classes = set(FIGHTER_CLASSES) | {
            r["class_id"]
            for r in self.connection.execute(
                "SELECT class_id FROM custom_fighter_classes WHERE hidden=0"
            )
        }
        public_skills = set(BUILTIN_SKILLS)
        for row in self.connection.execute(
            "SELECT skill_id,definition_json FROM custom_fighter_skills"
        ):
            try:
                definition = json.loads(row["definition_json"])
            except (TypeError, ValueError):
                continue
            if (
                isinstance(definition, dict)
                and definition.get("merchant_available") is True
            ):
                public_skills.add(row["skill_id"])
        catalog = {}
        for kind, source, allowed in (
            ("skill", skills, public_skills),
            ("passive", BUILTIN_PASSIVES, set(BUILTIN_PASSIVES)),
            ("class", classes, public_classes),
        ):
            for key, content in source.items():
                if key not in allowed or (kind == "skill" and key == "bum_punch"):
                    continue
                catalog[(kind, key)] = {
                    "kind": kind,
                    "content_id": key,
                    "name": content.name,
                    "rarity": content.rarity,
                    "details": asdict(content),
                }
        catalog[("potion", "healing")] = {
            "kind": "potion",
            "content_id": "healing",
            "name": "Зелье лечения",
            "rarity": "common",
            "details": {
                "description": "Восстанавливает 30% HP в бою. Одно на бой, без расхода хода."
            },
        }
        catalog[("candy", "experience")] = {
            "kind": "candy",
            "content_id": "experience",
            "name": "Конфета опыта",
            "rarity": "common",
            "details": {
                "description": "Даёт выбранному бойцу 30 XP. На максимальном уровне не расходуется."
            },
        }
        return catalog

    def _arena_describe_item_locked(self, row, catalog=None):
        catalog = catalog or self._arena_shop_catalog_locked()
        if (row["kind"], row["content_id"]) not in catalog and row["kind"] in {
            "skill",
            "class",
        }:
            classes, skills = self._fighter_catalog_locked()
            content = (classes if row["kind"] == "class" else skills).get(
                row["content_id"]
            )
            if content:
                catalog = dict(catalog)
                catalog[(row["kind"], row["content_id"])] = dict(
                    kind=row["kind"],
                    content_id=row["content_id"],
                    name=content.name,
                    rarity=content.rarity,
                    details=asdict(content),
                )
        data = dict(
            catalog.get(
                (row["kind"], row["content_id"]),
                {"name": "Недоступный предмет", "details": {}},
            )
        )
        data.update(dict(row))
        data["rarity_name"] = RARITY_LABELS.get(data["rarity"], data["rarity"])
        return data

    def _arena_inventory_locked(self, chat, actor):
        catalog = self._arena_shop_catalog_locked()
        return [
            self._arena_describe_item_locked(r, catalog)
            for r in self.connection.execute(
                "SELECT * FROM arena_inventory WHERE chat_id=? AND owner_id=? ORDER BY kind,id",
                (chat, actor),
            )
        ]

    def _arena_make_visits_locked(self, chat, day):
        rng = random.SystemRandom()
        midnight = int(
            datetime.combine(day, datetime.min.time(), tzinfo=MSK).timestamp()
        )
        catalog = self._arena_shop_catalog_locked()
        for visit, lo, hi in MERCHANT_WINDOWS:
            if self.connection.execute(
                "SELECT 1 FROM arena_merchant_visits WHERE chat_id=? AND day=? AND visit=?",
                (chat, day.isoformat(), visit),
            ).fetchone():
                continue
            starts = midnight + rng.randint(lo * 3600, hi * 3600)
            cursor = self.connection.execute(
                "INSERT INTO arena_merchant_visits(chat_id,day,visit,starts,ends) VALUES(?,?,?,?,?)",
                (chat, day.isoformat(), visit, starts, starts + MERCHANT_DURATION),
            )
            visit_id = cursor.lastrowid
            selected = []
            for kind in ("skill", "passive", "any"):
                choices = [
                    c
                    for c in catalog.values()
                    if c["kind"] in ({"skill", "passive"} if kind == "any" else {kind})
                    and (c["kind"], c["content_id"]) not in selected
                    and c["details"].get("unlock_level", 1) <= MAX_FIGHTER_LEVEL
                ]
                chosen = rng.choices(
                    choices, weights=[WEIGHTS[c["rarity"]] for c in choices]
                )[0]
                selected.append((chosen["kind"], chosen["content_id"]))
            selected += [("potion", "healing"), ("candy", "experience")]
            if rng.random() < CLASS_SCROLL_CHANCE:
                choices = [
                    c
                    for c in catalog.values()
                    if c["kind"] == "class" and c["content_id"] != "ragamuffin"
                ]
                chosen = rng.choices(
                    choices, weights=[WEIGHTS[c["rarity"]] for c in choices]
                )[0]
                selected.append(("class", chosen["content_id"]))
            for kind, content in selected:
                rarity = catalog[(kind, content)]["rarity"]
                price = (
                    25
                    if kind == "potion"
                    else (
                        50
                        if kind == "candy"
                        else CLASS_PRICES[rarity] if kind == "class" else PRICES[rarity]
                    )
                )
                self.connection.execute(
                    "INSERT INTO arena_merchant_offers(visit_id,kind,content_id,rarity,price,per_user) VALUES(?,?,?,?,?,?)",
                    (
                        visit_id,
                        kind,
                        content,
                        rarity,
                        price,
                        3 if kind in {"potion", "candy"} else 1,
                    ),
                )

    def _arena_merchant_view_locked(self, chat, actor):
        now = market_now()
        day = datetime.fromtimestamp(now, MSK).date()
        for date in (day, day + timedelta(days=1)):
            self._arena_make_visits_locked(chat, date)
        visit = self.connection.execute(
            "SELECT * FROM arena_merchant_visits WHERE chat_id=? AND starts<=? AND ends>? ORDER BY starts DESC LIMIT 1",
            (chat, now, now),
        ).fetchone()
        if not merchant_is_open(now):
            visit = None
        next_visit = self.connection.execute(
            "SELECT starts FROM arena_merchant_visits WHERE chat_id=? AND starts>? ORDER BY starts LIMIT 1",
            (chat, now),
        ).fetchone()
        offers = []
        if visit:
            catalog = self._arena_shop_catalog_locked()
            for row in self.connection.execute(
                """SELECT o.*,COALESCE(p.quantity,0) AS bought FROM arena_merchant_offers o
                LEFT JOIN arena_merchant_purchases p ON p.offer_id=o.id AND p.user_id=? WHERE o.visit_id=? ORDER BY o.id""",
                (actor, visit["id"]),
            ):
                item = self._arena_describe_item_locked(row, catalog)
                item["remaining"] = row["per_user"] - row["bought"]
                offers.append(item)
        return dict(
            visit_id=visit["id"] if visit else None,
            ends=visit["ends"] if visit else None,
            next_starts=next_visit["starts"] if next_visit else None,
            offers=offers,
        )

    async def arena_due_merchants(self):
        async with self._lock:
            now = market_now()
            day = datetime.fromtimestamp(now, MSK).date()
            chats = self.connection.execute(
                "SELECT DISTINCT chat_id FROM personal_profiles WHERE chat_id<0"
            ).fetchall()
            for row in chats:
                self._arena_make_visits_locked(row["chat_id"], day)
            if not merchant_is_open(now):
                self.connection.commit()
                return []
            due = [
                dict(r)
                for r in self.connection.execute(
                    "SELECT * FROM arena_merchant_visits WHERE chat_id<0 AND starts<=? AND ends>? AND notified=0",
                    (now, now),
                )
            ]
            # Claim notifications before sending: no duplicated chat posts after restart.
            for row in due:
                self.connection.execute(
                    "UPDATE arena_merchant_visits SET notified=1 WHERE id=?",
                    (row["id"],),
                )
            self.connection.commit()
            return due

    async def arena_buy_item(self, chat, actor, offer_id):
        async with self._lock:
            try:
                now = market_now()
                if not merchant_is_open(now):
                    raise ValueError("Торговец доступен только с 10:00 до 22:00 МСК.")
                row = self.connection.execute(
                    """SELECT o.* FROM arena_merchant_offers o JOIN arena_merchant_visits v ON v.id=o.visit_id
                    WHERE o.id=? AND v.chat_id=? AND v.starts<=? AND v.ends>?""",
                    (offer_id, chat, now, now),
                ).fetchone()
                if not row:
                    raise ValueError(
                        "Торговец уже ушёл или предложение не из этого чата."
                    )
                if (
                    row["kind"],
                    row["content_id"],
                ) not in self._arena_shop_catalog_locked():
                    raise ValueError("Предмет больше недоступен.")
                bought = self.connection.execute(
                    "SELECT quantity FROM arena_merchant_purchases WHERE offer_id=? AND user_id=?",
                    (offer_id, actor),
                ).fetchone()
                if bought and bought["quantity"] >= row["per_user"]:
                    raise ValueError("Лимит покупки этого товара исчерпан.")
                if not self.connection.execute(
                    "UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?",
                    (row["price"], now, chat, actor, row["price"]),
                ).rowcount:
                    raise ValueError("Не хватает франков.")
                self._arena_add_item_locked(
                    chat, actor, row["kind"], row["content_id"], row["rarity"]
                )
                self.connection.execute(
                    "INSERT INTO arena_merchant_purchases VALUES(?,?,1) ON CONFLICT(offer_id,user_id) DO UPDATE SET quantity=quantity+1",
                    (offer_id, actor),
                )
                self.connection.commit()
                return "Предмет добавлен в инвентарь."
            except Exception:
                self.connection.rollback()
                raise

    async def arena_transfer_item(self, chat, actor, item, target):
        if actor == target or target <= 0:
            raise ValueError("Выбери другого участника.")
        async with self._lock:
            try:
                row = self._arena_item_locked(chat, actor, item)
                description = self._arena_describe_item_locked(row)
                self._arena_consume_item_locked(row)
                self._arena_add_item_locked(
                    chat, target, row["kind"], row["content_id"], row["rarity"]
                )
                self.connection.commit()
                return description["name"]
            except Exception:
                self.connection.rollback()
                raise

    def _arena_reset_profile_locked(self, chat, user, personal, class_id="ragamuffin"):
        table = "personal_profiles" if personal else "slave_profiles"
        self.connection.execute(
            "DELETE FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=?",
            (chat, user, int(personal)),
        )
        self.connection.execute(
            f"""UPDATE {table} SET class_id=?,archclass_id='',archclass_stage=10,progression_level=0,progression_pending_level=0,progression_pending_at=NULL,archclass_pending_at=NULL,level=1,xp=0,loadout='["bum_punch"]',
                passive_loadout='[]',skills_reset=1,class_choice_pending_at=NULL,
                skills_pending_at=?,updated_at=?,skill_memory=NULL,passive_memory=NULL,
                skill_seen='[]',passive_seen='[]' WHERE chat_id=? AND user_id=?""",
            (class_id, market_now(), market_now(), chat, user),
        )

    def _arena_equip_class_passives_locked(self, chat, user, personal, class_id):
        profile = dict(
            self._arena_profile_locked(chat, user, personal), class_id=class_id
        )
        available = self._arena_passive_catalog_locked(chat, user, personal, profile)
        selected = [k for k in available if k.startswith(f"inherent:{class_id}:")][
            :MAX_PASSIVE_SKILLS
        ]
        table = "personal_profiles" if personal else "slave_profiles"
        self.connection.execute(
            f"UPDATE {table} SET passive_loadout=? WHERE chat_id=? AND user_id=?",
            (json.dumps(selected), chat, user),
        )

    async def arena_use_item(
        self, chat, actor, item, user, personal=True, confirm=False, replace_skill=None
    ):
        async with self._lock:
            try:
                row = self._arena_item_locked(chat, actor, item)
                if (personal and user != actor) or (
                    not personal
                    and user != actor
                    and not self._arena_owns_locked(chat, actor, user)
                ):
                    raise ValueError("Предмет можно применить к себе или своему рабу.")
                if (
                    not personal
                    and user == actor
                    and not self.connection.execute(
                        "SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?",
                        (chat, actor),
                    ).fetchone()
                ):
                    raise ValueError("Ты не состоишь в рабстве.")
                if self._arena_busy_locked(chat, user):
                    raise ValueError(
                        "Нельзя использовать трактат или конфету во время боя."
                    )
                profile = self._arena_profile_locked(chat, user, personal)
                table = "personal_profiles" if personal else "slave_profiles"
                classes, skills = self._fighter_catalog_locked()
                kind, content = row["kind"], row["content_id"]
                if replace_skill is not None and (
                    not isinstance(replace_skill, str)
                    or kind not in {"skill", "passive"}
                ):
                    raise ValueError(
                        "Заменять можно только навык трактатом того же типа."
                    )
                replaced_name = None
                if kind == "potion":
                    raise ValueError("Зелье используется кнопкой в бою.")
                if kind == "candy":
                    if profile["level"] >= MAX_FIGHTER_LEVEL:
                        raise ValueError(
                            "Боец уже достиг 20 уровня. Конфета не потрачена."
                        )
                    self._grant_profile_xp_locked(table, chat, user, 30)
                    notice = "Боец получил 30 XP (не выше 20 уровня)."
                elif kind == "class":
                    if confirm is not True:
                        raise ValueError(
                            "Подтверди смену класса: уровень, опыт, навыки и пассивки будут сброшены."
                        )
                    if content not in classes or profile["class_id"] == content:
                        raise ValueError("Этот класс недоступен или уже выбран.")
                    self._arena_reset_profile_locked(chat, user, personal, content)
                    self._arena_equip_class_passives_locked(
                        chat, user, personal, content
                    )
                    notice = f"Новый класс: {classes[content].name}. Уровень 1; прежние навыки и пассивки забыты."
                elif kind in {"skill", "passive"}:
                    catalog = skills if kind == "skill" else BUILTIN_PASSIVES
                    if content not in catalog:
                        raise ValueError("Навык больше недоступен.")
                    if kind == "skill":
                        if catalog[content].unlock_level > profile["level"]:
                            raise ValueError(
                                f"Для изучения нужен уровень {catalog[content].unlock_level}. Трактат не потрачен."
                            )
                        known = set(
                            self._arena_known_skills_locked(chat, user, personal)
                        )
                    else:
                        known = set(
                            self._arena_passive_catalog_locked(
                                chat, user, personal, profile
                            )
                        )
                    if content in known:
                        raise ValueError(
                            "Боец уже знает этот навык. Трактат не потрачен."
                        )
                    if replace_skill is not None:
                        if replace_skill not in known or replace_skill == "bum_punch":
                            raise ValueError(
                                "Выбери изученный навык того же типа. Бесплатный удар заменить нельзя. Трактат не потрачен."
                            )
                        old_catalog = (
                            skills
                            if kind == "skill"
                            else self._arena_passive_catalog_locked(
                                chat, user, personal
                            )
                        )
                        old = old_catalog[replace_skill]
                        replaced_name = old.name if kind == "skill" else old["name"]
                        current = self._arena_profile_locked(chat, user, personal)
                        memory = [
                            k
                            for k in json.loads(current[kind + "_memory"])
                            if k != replace_skill
                        ]
                        column = "loadout" if kind == "skill" else "passive_loadout"
                        selected = [
                            content if k == replace_skill else k
                            for k in json.loads(current[column])
                        ]
                        self.connection.execute(
                            f"UPDATE {table} SET {kind}_memory=?,{column}=? WHERE chat_id=? AND user_id=?",
                            (json.dumps(memory), json.dumps(selected), chat, user),
                        )
                        profile = dict(profile)
                        profile[column] = json.dumps(selected)
                    self._arena_remember_locked(chat, user, personal, kind, content)
                    self.connection.execute(
                        "INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)",
                        (chat, user, int(personal), kind, content),
                    )
                    if kind == "skill":
                        loadout = normalize_loadout(
                            profile["class_id"],
                            profile["level"],
                            json.loads(profile["loadout"]),
                            skills,
                            self._arena_grants_locked(chat, user, personal),
                            self._arena_known_skills_locked(chat, user, personal),
                        )
                        self.connection.execute(
                            f"UPDATE {table} SET loadout=?,skills_pending_at=? WHERE chat_id=? AND user_id=?",
                            (json.dumps(loadout), market_now(), chat, user),
                        )
                    else:
                        loadout = list(
                            dict.fromkeys(json.loads(profile["passive_loadout"]))
                        )
                        if content not in loadout and len(loadout) < MAX_PASSIVE_SKILLS:
                            loadout.append(content)
                            self.connection.execute(
                                f"UPDATE {table} SET passive_loadout=?,skills_pending_at=? WHERE chat_id=? AND user_id=?",
                                (json.dumps(loadout), market_now(), chat, user),
                            )
                    notice = f"Изучено: {catalog[content].name}. Набор меняется в «Класс и навыки»."
                    if replaced_name:
                        notice += f" Заменён навык: {replaced_name}."
                else:
                    raise ValueError("Неизвестный предмет.")
                self._arena_consume_item_locked(row)
                self.connection.commit()
                return notice
            except Exception:
                self.connection.rollback()
                raise

    def _arena_potion_count_locked(self, chat, actor):
        row = self.connection.execute(
            "SELECT quantity FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind='potion' AND content_id='healing'",
            (chat, actor),
        ).fetchone()
        return row["quantity"] if row else 0

    async def arena_market_view(self, chat, actor):
        async with self._lock:
            balance = self.connection.execute(
                "SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?",
                (chat, actor),
            ).fetchone()
            result = dict(
                inventory=self._arena_inventory_locked(chat, actor),
                merchant=self._arena_merchant_view_locked(chat, actor),
                balance=balance["balance"] if balance else 0,
            )
            self.connection.commit()
            return result

    async def arena_passive_view(self, chat, user, personal):
        async with self._lock:
            profile = self._arena_profile_locked(chat, user, personal)
            known = self._arena_known_skills_locked(chat, user, personal)
            all_passives = self._arena_passive_catalog_locked(
                chat, user, personal, all_available=True
            )
            passives = self._arena_passive_catalog_locked(chat, user, personal)
            profile = self._arena_profile_locked(chat, user, personal)
            _, skills = self._fighter_catalog_locked()
            eligible = unlocked_skill_ids(
                profile["class_id"],
                profile["level"],
                skills,
                self._arena_grants_locked(chat, user, personal),
            )
            result = dict(
                passives=list(passives.values()),
                available_passives=[
                    v for k, v in all_passives.items() if k not in passives
                ],
                available_skills=[
                    asdict(skills[k]) for k in eligible if k not in known
                ],
                known_skills=known,
                learned_limits=dict(
                    active=MAX_LEARNED_ACTIVE_SKILLS, passive=MAX_LEARNED_PASSIVE_SKILLS
                ),
                loadout=normalize_loadout(
                    profile["class_id"],
                    profile["level"],
                    json.loads(profile["loadout"]),
                    skills,
                    self._arena_grants_locked(chat, user, personal),
                    known,
                ),
                passive_loadout=[
                    k
                    for k in dict.fromkeys(json.loads(profile["passive_loadout"]))
                    if k in passives
                ][:MAX_PASSIVE_SKILLS],
                granted=self._arena_grants_locked(chat, user, personal),
            )
            self.connection.commit()
            return result

    async def arena_potion_count(self, chat, actor):
        async with self._lock:
            return self._arena_potion_count_locked(chat, actor)
