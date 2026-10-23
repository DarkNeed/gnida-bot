"""Persistent merchant visits, atomic franc purchases and transferable inventory."""

from __future__ import annotations
import json
import random
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from arena_engine import (
    BUILTIN_PASSIVES,
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    MAX_FIGHTER_LEVEL,
    passive_skill_limit,
    MAX_LEARNED_ACTIVE_SKILLS,
    MAX_LEARNED_PASSIVE_SKILLS,
    PassiveSkill,
    RARITY_LABELS,
    fighter_xp_limit,
    normalize_loadout,
    unlocked_skill_ids,
    xp_for_next_level,
)
from arena_archprogress import branch_skill_allowed, skill_branch
from arena_forge import ForgeMixin
from arena_global import RPG_SCOPE
from arena_casino_unlock import CasinoUnlockMixin

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


class ArenaMarketMixin(CasinoUnlockMixin, ForgeMixin):
    def _connect_arena_market(self):
        self._connect_casino()
        self._connect_forge()
        for table in ("slave_profiles", "personal_profiles"):
            self._ensure_column(table, "passive_loadout", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(table, "skills_reset", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(table, "catchup_target_xp", "INTEGER NOT NULL DEFAULT 0")
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
            CREATE TABLE IF NOT EXISTS arena_merchant_notifications(
                day TEXT NOT NULL, visit INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                PRIMARY KEY(day,visit,chat_id)
            );
            CREATE TABLE IF NOT EXISTS arena_merchant_notification_settings(
                chat_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
                revision INTEGER NOT NULL DEFAULT 0, updated_by INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_merchant_period ON arena_merchant_visits(day,visit);
            CREATE INDEX IF NOT EXISTS idx_merchant_offer_content ON arena_merchant_offers(visit_id,kind,content_id);
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
                    f"SELECT chat_id,user_id,class_id,level FROM {table}"
                ).fetchall():
                    cls = classes.get(row["class_id"])
                    if cls and cls.passives:
                        defaults = [
                            f"inherent:{cls.class_id}:{i}"
                            for i in range(
                                min(
                                    passive_skill_limit(row["level"]), len(cls.passives)
                                )
                            )
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
        self._connect_global_merchant()

    def _connect_global_merchant(self):
        name = 'account_merchant_v1'
        if self.connection.execute('SELECT 1 FROM arena_market_migrations WHERE name=?', (name,)).fetchone():
            return
        legacy = self.connection.execute('SELECT 1 FROM arena_merchant_visits WHERE chat_id<>0').fetchone()
        if legacy:
            # Keep an independent, WAL-consistent snapshot before promoting old
            # visits. Historical offers/purchases remain untouched below.
            backup_dir = self.path.parent / 'backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / ('before-global-merchant-' + str(int(time.time())) + '-' + uuid.uuid4().hex[:8] + '.sqlite3')
            with closing(sqlite3.connect(self.path)) as source:
                with closing(sqlite3.connect(backup_path)) as snapshot:
                    source.backup(snapshot)
        with self.connection:
            self.connection.execute('''INSERT OR IGNORE INTO arena_merchant_notifications
                SELECT day,visit,chat_id FROM arena_merchant_visits WHERE chat_id<>0 AND notified=1''')
            # Adopt one existing schedule/assortment for each period, preserving
            # its IDs and end time. Never reroll or revive an expired visit.
            for row in self.connection.execute('''SELECT MIN(id) AS id,day,visit
                FROM arena_merchant_visits GROUP BY day,visit''').fetchall():
                if not self.connection.execute('SELECT 1 FROM arena_merchant_visits WHERE chat_id=0 AND day=? AND visit=?',
                                               (row['day'], row['visit'])).fetchone():
                    self.connection.execute('UPDATE arena_merchant_visits SET chat_id=0 WHERE id=?', (row['id'],))
            self.connection.execute('INSERT INTO arena_market_migrations VALUES(?)', (name,))

    def _arena_merchant_bought_locked(self, visit, actor, kind, content):
        # Count old local purchases too, including offers not chosen as the
        # canonical global offer. Migrating must not reset anyone's limits.
        return self.connection.execute('''SELECT COALESCE(SUM(p.quantity),0) AS quantity
            FROM arena_merchant_visits v JOIN arena_merchant_offers o ON o.visit_id=v.id
            JOIN arena_merchant_purchases p ON p.offer_id=o.id
            WHERE v.day=? AND v.visit=? AND o.kind=? AND o.content_id=? AND p.user_id=?''',
            (visit['day'], visit['visit'], kind, content, actor)).fetchone()['quantity']

    def _arena_add_item_locked(self, chat, owner, kind, content, rarity, quantity=1):
        chat = RPG_SCOPE
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
        alias = self.connection.execute('SELECT new_id FROM arena_global_item_aliases WHERE old_id=? AND owner_id=?',(item,actor)).fetchone()
        item = alias['new_id'] if alias else item
        chat = RPG_SCOPE
        row = self.connection.execute(
            "SELECT * FROM arena_inventory WHERE id=? AND chat_id=? AND owner_id=?",
            (item, chat, actor),
        ).fetchone()
        if not row:
            raise ValueError("Предмета нет в твоём общем инвентаре.")
        return row

    def _arena_learned_locked(self, chat, user, personal, kind):
        chat = RPG_SCOPE if personal else chat
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
        chat = RPG_SCOPE if personal else chat
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
        if kind=='skill':
            offers=[k for k in json.loads(profile['skill_offers']) if k in eligible and k!='bum_punch']
            # Preserve migrated builds. Prompt for discoveries after initialization,
            # even if the library auto-filled a free slot; never silently replace a move.
            if previous is not None:
                offers+= [k for k in eligible if k not in seen and k not in offers and k!='bum_punch']
            self.connection.execute(f'UPDATE {table} SET skill_offers=? WHERE chat_id=? AND user_id=?',
                                    (json.dumps(offers),chat,user))
        seen.update(eligible)
        encoded, encoded_seen = json.dumps(memory), json.dumps(sorted(seen))
        if previous != encoded or profile[kind + "_seen"] != encoded_seen:
            self.connection.execute(
                f"UPDATE {table} SET {column}=?,{kind}_seen=? WHERE chat_id=? AND user_id=?",
                (encoded, encoded_seen, chat, user),
            )
        return memory

    def _arena_resolve_skill_offer_locked(self,chat,user,personal,value):
        if not isinstance(value,dict) or value.get('decision') not in ('learn','skip'):
            raise ValueError('Выбери новый навык или оставь прежние.')
        self._arena_known_skills_locked(chat,user,personal)
        profile=self._arena_profile_locked(chat,user,personal)
        offers=json.loads(profile['skill_offers']);known=json.loads(profile['skill_memory'] or '[]')
        _,skills=self._fighter_catalog_locked()
        selected=normalize_loadout(profile['class_id'],profile['level'],json.loads(profile['loadout']),skills,
            self._arena_grants_locked(chat,user,personal),known,profile['archclass_id'],profile['progression_level'])
        original_selected=list(selected)
        if not offers or offers[0]!=value.get('skill'):
            raise ValueError('Предложение навыка изменилось. Обнови меню.')
        if value.get('known')!=known or value.get('selected')!=selected:
            raise ValueError('Набор навыков изменился. Обнови меню.')
        new=offers[0];remove=value.get('replace_memory');equip=value.get('equip_replace')
        if value['decision']=='skip':
            known=[k for k in known if k!=new]
            selected=[k for k in selected if k!=new]
        else:
            if new not in known:
                if len(known)>=MAX_LEARNED_ACTIVE_SKILLS:
                    if remove not in known or remove=='bum_punch':raise ValueError('Выбери изученный навык, который забудешь. Обычный удар защищён.')
                    if equip is not None and equip!=remove:raise ValueError('Замена боевого навыка должна совпадать с забываемым.')
                    known.remove(remove)
                    selected=[new if k==remove else k for k in selected]
                elif remove is not None:raise ValueError('Есть свободное место в памяти; забывать навык не нужно.')
                known.append(new)
            elif remove is not None:raise ValueError('Новый навык уже изучен. Выбери только боевой слот.')
            if equip is not None:
                if equip not in original_selected:raise ValueError('Боевой слот изменился.')
                selected=[new if k==equip else k for k in selected]
            elif new not in selected and len(selected)<4:selected.append(new)
        # A skipped skill remains available for manual learning later.
        selected=normalize_loadout(profile['class_id'],profile['level'],selected,skills,
            self._arena_grants_locked(chat,user,personal),known,profile['archclass_id'],profile['progression_level'])
        self.connection.execute('UPDATE personal_profiles SET skill_memory=?,loadout=?,skill_offers=?,skills_pending_at=NULL WHERE chat_id=? AND user_id=?',
            (json.dumps(known),json.dumps(selected),json.dumps(offers[1:]),chat,user))

    def _arena_known_skills_locked(self, chat, user, personal, profile=None):
        chat = RPG_SCOPE if personal else chat
        profile = profile or self._arena_profile_locked(chat, user, personal)
        _, skills = self._fighter_catalog_locked()
        eligible = unlocked_skill_ids(
            profile["class_id"],
            profile["level"],
            skills,
            self._arena_grants_locked(chat, user, personal),
            archclass_id=profile["archclass_id"],
            progression_level=profile['progression_level'],
        )
        # An update may introduce a skill to an existing capped-level profile.
        # Start the normal delegation clock once, even when memory is full.
        seen = set(json.loads(profile["skill_seen"]))
        if any((skill_branch(skills[key]) or any(t.startswith('mastery:') for t in skills[key].tags)) and key not in seen for key in eligible):
            table = "personal_profiles" if personal else "slave_profiles"
            self.connection.execute(
                f"UPDATE {table} SET skills_pending_at=COALESCE(skills_pending_at,?) WHERE chat_id=? AND user_id=?",
                (market_now(), chat, user),
            )
        return self._arena_memory_locked(
            chat, user, personal, "skill", eligible, profile
        )

    def _arena_remember_locked(self, chat, user, personal, kind, content):
        chat = RPG_SCOPE if personal else chat
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
        chat = RPG_SCOPE if personal else chat
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
        ][: passive_skill_limit(profile["level"])]
        for key in unseen_inherent:
            if (
                key in memory
                and key not in selected
                and len(selected) < passive_skill_limit(profile["level"])
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
        ][: passive_skill_limit(profile["level"])]

    def _arena_shop_catalog_locked(self):
        classes, skills = self._fighter_catalog_locked()
        public_classes = (set(FIGHTER_CLASSES)-{'gambler'}) | {
            r["class_id"]
            for r in self.connection.execute(
                "SELECT class_id FROM custom_fighter_classes WHERE hidden=0"
            )
        }
        # Branch skills unlock through progression, not tradable cross-branch scrolls.
        public_skills = {
            k
            for k, s in BUILTIN_SKILLS.items()
            if s.class_id!='gambler' and not skill_branch(s) and "raid_loot" not in s.tags and not any(t.startswith('mastery:') for t in s.tags)
        }
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
        chat = RPG_SCOPE
        catalog = self._arena_shop_catalog_locked()
        return [
            self._arena_describe_item_locked(r, catalog)
            for r in self.connection.execute(
                "SELECT * FROM arena_inventory WHERE chat_id=? AND owner_id=? ORDER BY kind,id",
                (chat, actor),
            )
        ]

    def _arena_make_visits_locked(self, chat, day):
        chat = RPG_SCOPE
        rng = random.SystemRandom()
        midnight = int(
            datetime.combine(day, datetime.min.time(), tzinfo=MSK).timestamp()
        )
        catalog = {k:v for k,v in self._arena_shop_catalog_locked().items() if self._arena_content_enabled_locked(chat,*k)}
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
                if not choices:
                    continue
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
                if choices:
                    chosen = rng.choices(choices, weights=[WEIGHTS[c["rarity"]] for c in choices])[0]
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
            (RPG_SCOPE, now, now),
        ).fetchone()
        if not merchant_is_open(now):
            visit = None
        next_visit = self.connection.execute(
            "SELECT starts FROM arena_merchant_visits WHERE chat_id=? AND starts>? ORDER BY starts LIMIT 1",
            (RPG_SCOPE, now),
        ).fetchone()
        offers = []
        if visit:
            catalog = self._arena_shop_catalog_locked()
            for row in self.connection.execute(
                "SELECT * FROM arena_merchant_offers WHERE visit_id=? ORDER BY id",
                (visit["id"],),
            ):
                item = self._arena_describe_item_locked(row, catalog)
                if not self._arena_content_enabled_locked(chat,row['kind'],row['content_id']):
                    continue
                item['bought'] = self._arena_merchant_bought_locked(visit, actor, row['kind'], row['content_id'])
                item["remaining"] = max(0, row["per_user"] - item['bought'])
                offers.append(item)
        return dict(
            visit_id=visit["id"] if visit else None,
            ends=visit["ends"] if visit else None,
            next_starts=next_visit["starts"] if next_visit else None,
            offers=offers,
        )

    def _arena_merchant_notifications_locked(self, chat):
        row = self.connection.execute(
            'SELECT enabled,revision FROM arena_merchant_notification_settings WHERE chat_id=?',
            (chat,),
        ).fetchone()
        return dict(enabled=bool(row['enabled']) if row else True,
                    revision=row['revision'] if row else 0)

    async def arena_merchant_notifications(self, chat):
        async with self._lock:
            return self._arena_merchant_notifications_locked(chat)

    async def arena_set_merchant_notifications(self, chat, actor, enabled, revision):
        if type(enabled) is not bool or type(revision) is not int:
            raise ValueError('Некорректная настройка сообщений торговца.')
        async with self._lock:
            with self.connection:
                current = self._arena_merchant_notifications_locked(chat)
                if current['revision'] != revision:
                    raise ValueError('Настройки изменились. Обнови меню.')
                self.connection.execute('''INSERT INTO arena_merchant_notification_settings
                    (chat_id,enabled,revision,updated_by,updated_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled,
                    revision=excluded.revision,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                    (chat, int(enabled), revision + 1, actor, market_now()))
        return ('Сообщения торговца включены.' if enabled else
                'Сообщения торговца отключены. Магазин остаётся доступен в арене.')

    async def arena_due_merchants(self):
        async with self._lock:
            now = market_now()
            day = datetime.fromtimestamp(now, MSK).date()
            chats = self.connection.execute(
                "SELECT DISTINCT chat_id FROM arena_account_chats WHERE chat_id<0"
            ).fetchall()
            chats = [row['chat_id'] for row in chats if self._feature_enabled_locked(row['chat_id'], 'arena')]
            if chats:
                self._arena_make_visits_locked(RPG_SCOPE, day)
            if not merchant_is_open(now):
                self.connection.commit()
                return []
            visit = self.connection.execute('''SELECT * FROM arena_merchant_visits
                WHERE chat_id=0 AND starts<=? AND ends>? ORDER BY starts DESC LIMIT 1''', (now, now)).fetchone()
            due = []
            if visit:
                for chat in chats:
                    if not self._arena_merchant_notifications_locked(chat)['enabled']:
                        continue
                    if not self.connection.execute('SELECT 1 FROM arena_merchant_notifications WHERE day=? AND visit=? AND chat_id=?',
                                                   (visit['day'], visit['visit'], chat)).fetchone():
                        due.append(dict(visit, chat_id=chat))
            # Claim notifications before sending: no duplicated chat posts after restart.
            for row in due:
                self.connection.execute(
                    "INSERT INTO arena_merchant_notifications VALUES(?,?,?)",
                    (row['day'], row['visit'], row['chat_id']),
                )
            self.connection.commit()
            return due

    async def arena_buy_item(self, chat, actor, offer_id):
        async with self._lock:
            try:
                self._require_feature_locked(chat, 'arena')
                if not self.connection.in_transaction:
                    self.connection.execute('BEGIN IMMEDIATE')
                now = market_now()
                if not merchant_is_open(now):
                    raise ValueError("Торговец доступен только с 10:00 до 22:00 МСК.")
                row = self.connection.execute(
                    """SELECT o.*,v.day,v.visit FROM arena_merchant_offers o JOIN arena_merchant_visits v ON v.id=o.visit_id
                    WHERE o.id=? AND v.chat_id=? AND v.starts<=? AND v.ends>?""",
                    (offer_id, RPG_SCOPE, now, now),
                ).fetchone()
                if not row:
                    raise ValueError(
                        "Предложение торговца устарело. Обнови товары."
                    )
                if not self._arena_content_enabled_locked(chat,row['kind'],row['content_id']):
                    raise ValueError("Модуль этого предмета выключен в чате.")
                if (
                    row["kind"],
                    row["content_id"],
                ) not in self._arena_shop_catalog_locked():
                    raise ValueError("Предмет больше недоступен.")
                bought = self._arena_merchant_bought_locked(row, actor, row['kind'], row['content_id'])
                if bought >= row["per_user"]:
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
        async with self._lock:
            with self.connection:
                return self._arena_transfer_item_locked(chat, actor, item, target)

    def _arena_transfer_item_locked(self, chat, actor, item, target, quantity=1):
        """No commit: a batch can roll back every item and ownership change."""
        if actor == target or target <= 0:
            raise ValueError("Выбери другого участника.")
        if type(quantity) is not int or quantity < 1:
            raise ValueError("Количество должно быть положительным целым числом.")
        self._require_feature_locked(chat, 'arena')
        row = self._arena_item_locked(chat, actor, item)
        if row["quantity"] < quantity:
            raise ValueError(f"Не хватает предмета №{item}: есть {row['quantity']}, нужно {quantity}.")
        description = self._arena_describe_item_locked(row)
        if row["quantity"] == quantity:
            self.connection.execute("DELETE FROM arena_inventory WHERE id=?", (row["id"],))
        else:
            self.connection.execute("UPDATE arena_inventory SET quantity=quantity-? WHERE id=?", (quantity, row["id"]))
        self._arena_add_item_locked(chat, target, row["kind"], row["content_id"], row["rarity"], quantity)
        return description["name"]

    def _arena_reset_profile_locked(self, chat, user, personal, class_id="ragamuffin", *, preserve_archives=False):
        chat = RPG_SCOPE if personal else chat
        table = "personal_profiles" if personal else "slave_profiles"
        profile = dict(self._arena_profile_locked(chat, user, personal))
        if not preserve_archives and profile["level"] < 5:
            raise ValueError("Сброс класса доступен с 5 уровня.")
        reset_level = 1 if preserve_archives else 5
        reset_xp = sum(xp_for_next_level(level) for level in range(1, reset_level))
        target = profile.get("catchup_target_xp", 0)
        if not preserve_archives:
            target = max(target, sum(xp_for_next_level(level) for level in range(1, profile["level"])))
            if target <= reset_xp:
                target = 0
        if not preserve_archives:
            # A deliberate full reset/class tractate cannot be undone by an
            # old module archive to regain the sacrificed level and skills.
            self.connection.execute('DELETE FROM arena_class_archives WHERE chat_id=? AND user_id=? AND personal=?',(chat,user,int(personal)))
        self.connection.execute(
            "DELETE FROM arena_learned WHERE chat_id=? AND user_id=? AND personal=?",
            (chat, user, int(personal)),
        )
        self.connection.execute(
            f"""UPDATE {table} SET class_id=?,archclass_id='',archclass_stage=10,progression_level=0,progression_pending_level=0,progression_pending_at=NULL,archclass_pending_at=NULL,level=?,xp=?,catchup_target_xp=?,loadout='["bum_punch"]',
                passive_loadout='[]',skills_reset=1,class_choice_pending_at=NULL,
                skills_pending_at=?,updated_at=?,skill_memory=NULL,passive_memory=NULL,
                skill_seen='[]',passive_seen='[]',skill_offers='[]' WHERE chat_id=? AND user_id=?""",
            (class_id, reset_level, reset_xp, target, market_now(), market_now(), chat, user),
        )

    def _arena_equip_class_passives_locked(self, chat, user, personal, class_id):
        chat = RPG_SCOPE if personal else chat
        profile = dict(
            self._arena_profile_locked(chat, user, personal), class_id=class_id
        )
        available = self._arena_passive_catalog_locked(chat, user, personal, profile)
        selected = [k for k in available if k.startswith(f"inherent:{class_id}:")][
            : passive_skill_limit(profile["level"])
        ]
        table = "personal_profiles" if personal else "slave_profiles"
        self.connection.execute(
            f"UPDATE {table} SET passive_loadout=? WHERE chat_id=? AND user_id=?",
            (json.dumps(selected), chat, user),
        )

    async def arena_use_item(
        self, chat, actor, item, user, personal=True, confirm=False, replace_skill=None, *, expected_slot=None
    ):
        async with self._lock:
            try:
                self._require_feature_locked(chat, 'arena')
                self._character_require_locked(actor,expected_slot)
                if not personal or actor != user:
                    raise ValueError('Предмет можно применить только к своему личному персонажу.')
                chat = RPG_SCOPE
                row = self._arena_item_locked(chat, actor, item)
                if not self._arena_content_enabled_locked(chat,row['kind'],row['content_id']):
                    raise ValueError("Этот трактат больше недоступен. Предмет сохранён.")
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
                    notice = f"Новый класс: {classes[content].name}. Уровень 5; прежние навыки и пассивки забыты. Боевой опыт ×2 до возвращения прежнего уровня."
                elif kind in {"skill", "passive"}:
                    catalog = skills if kind == "skill" else BUILTIN_PASSIVES
                    if content not in catalog:
                        raise ValueError("Навык больше недоступен.")
                    if kind == "skill":
                        if not branch_skill_allowed(
                            catalog[content], profile["archclass_id"], profile["level"]
                        ):
                            raise ValueError(
                                "Навык доступен только своей ветке с 15 уровня. Трактат не потрачен."
                            )
                        from arena_mastery import skill_allowed as mastery_allowed
                        if not mastery_allowed(catalog[content],dict(profile)):
                            raise ValueError('Навык доступен только на своём пути мастерства. Трактат не потрачен.')
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
                            profile["archclass_id"],
                            profile['progression_level'],
                        )
                        self.connection.execute(
                            f"UPDATE {table} SET loadout=?,skills_pending_at=? WHERE chat_id=? AND user_id=?",
                            (json.dumps(loadout), market_now(), chat, user),
                        )
                    else:
                        loadout = list(
                            dict.fromkeys(json.loads(profile["passive_loadout"]))
                        )
                        if content not in loadout and len(
                            loadout
                        ) < passive_skill_limit(profile["level"]):
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
        chat = RPG_SCOPE
        row = self.connection.execute(
            "SELECT quantity FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind='potion' AND content_id='healing'",
            (chat, actor),
        ).fetchone()
        return row["quantity"] if row else 0

    async def arena_market_view(self, chat, actor):
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            balance = self.connection.execute(
                "SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?",
                (chat, actor),
            ).fetchone()
            result = dict(
                inventory=self._arena_inventory_locked(chat, actor),
                merchant=self._arena_merchant_view_locked(chat, actor),
                balance=balance["balance"] if balance else 0,
                forge=self._forge_view_locked(chat, actor),
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
                archclass_id=profile["archclass_id"],
                progression_level=profile['progression_level'],
            )
            result = dict(
                passives=list(passives.values()),
                skill_offers=[asdict(skills[k]) for k in json.loads(profile['skill_offers']) if k in eligible],
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
                    profile["archclass_id"],
                    profile['progression_level'],
                ),
                passive_loadout=[
                    k
                    for k in dict.fromkeys(json.loads(profile["passive_loadout"]))
                    if k in passives
                ][: passive_skill_limit(profile["level"])],
                granted=self._arena_grants_locked(chat, user, personal),
            )
            self.connection.commit()
            return result

    async def arena_potion_count(self, chat, actor):
        async with self._lock:
            return self._arena_potion_count_locked(chat, actor)
