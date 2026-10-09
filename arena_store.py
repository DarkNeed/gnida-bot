"""Isolated arena persistence using the bot's existing SQLite transaction lock."""

from __future__ import annotations
import json
import hashlib
import random
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any
from arena_market import ArenaMarketMixin
from arena_engine import (
    FIGHTER_CLASSES,
    BUILTIN_SKILLS,
    VISIBLE_CLASS_ALIASES,
    CLASS_SELECTION_LEVEL,
    SKILL_DELEGATION_SECONDS,
    level_from_total_xp,
    normalize_loadout,
    fighter_class_from_dict,
    skill_from_dict,
    create_battle_state,
    resolve_skill,
    skip_turn,
    use_healing_potion,
    unlocked_skill_ids,
    xp_for_next_level,
    level_progress,
    MAX_FIGHTER_LEVEL,
    MAX_PASSIVE_SKILLS,
    fighter_xp_limit,
    effective_stat,
)

OWNER_RECORD_XP = 2
ARENA_PREPARATION_SECONDS = 3 * 60 * 60
ARENA_TURN_SECONDS = 3 * 60
ARENA_FEE_PERCENT = 10
COMBAT_SLAVE_CAPACITY = 5


def utc_timestamp() -> int:
    return int(time.time())


class ArenaMixin(ArenaMarketMixin):
    def _connect_arena(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS slave_profiles (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                class_id TEXT NOT NULL DEFAULT 'ragamuffin',
                loadout TEXT NOT NULL DEFAULT '["bum_punch"]',
                class_choice_pending_at INTEGER,
                skills_pending_at INTEGER,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS owner_profiles (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                slave_record INTEGER NOT NULL DEFAULT 0,
                raw_material INTEGER NOT NULL DEFAULT 0,
                material_fraction REAL NOT NULL DEFAULT 0,
                material_updated_at INTEGER NOT NULL,
                healing_potions INTEGER NOT NULL DEFAULT 0,
                candies INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS custom_fighter_classes (
                class_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                hidden INTEGER NOT NULL DEFAULT 1,
                definition_json TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS custom_fighter_skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS granted_fighter_content (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content_id TEXT NOT NULL,
                granted_by INTEGER NOT NULL,
                granted_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id, content_type, content_id)
            );


            CREATE TABLE IF NOT EXISTS arena_battles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE, chat_id INTEGER NOT NULL, message_id INTEGER,
                mode TEXT NOT NULL, a_owner INTEGER NOT NULL, b_owner INTEGER NOT NULL,
                a_fighter INTEGER, b_fighter INTEGER,
                a_control INTEGER NOT NULL DEFAULT 1, b_control INTEGER NOT NULL DEFAULT 1,
                a_consent INTEGER NOT NULL DEFAULT 0, b_consent INTEGER NOT NULL DEFAULT 0,
                b_accepted INTEGER NOT NULL DEFAULT 0,
                stake INTEGER NOT NULL DEFAULT 0, escrow_a INTEGER NOT NULL DEFAULT 0,
                escrow_b INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending', state_json TEXT,
                personal_solo INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0, floor INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL, deadline INTEGER NOT NULL, finished_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_arena_active ON arena_battles(chat_id,status,deadline);
            CREATE TABLE IF NOT EXISTS arena_combat_slots (
                chat_id INTEGER NOT NULL, owner_id INTEGER NOT NULL,
                slave_id INTEGER NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5),
                PRIMARY KEY(chat_id, slave_id), UNIQUE(chat_id, owner_id, slot)
            );
            CREATE TRIGGER IF NOT EXISTS arena_slots_release
            AFTER DELETE ON ownership BEGIN
                DELETE FROM arena_combat_slots WHERE chat_id=OLD.chat_id AND slave_id=OLD.slave_id;
            END;
            CREATE TRIGGER IF NOT EXISTS arena_slots_transfer
            AFTER UPDATE OF owner_id ON ownership WHEN OLD.owner_id<>NEW.owner_id BEGIN
                DELETE FROM arena_combat_slots WHERE chat_id=OLD.chat_id AND slave_id=OLD.slave_id;
            END;
            CREATE TABLE IF NOT EXISTS arena_pair_rewards (
                chat_id INTEGER NOT NULL, first_id INTEGER NOT NULL, second_id INTEGER NOT NULL,
                day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat_id,first_id,second_id,day)
            );
            CREATE TABLE IF NOT EXISTS arena_sprites (
                chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                sprite_key TEXT NOT NULL, png BLOB NOT NULL,
                pixel_art INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat_id,user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_arena_sprite_key ON arena_sprites(sprite_key);
        """)
        self.connection.commit()

        self._ensure_column(
            "arena_battles", "personal_solo", "INTEGER NOT NULL DEFAULT 0"
        )

        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS personal_profiles AS SELECT * FROM slave_profiles WHERE 0"
        )
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_profile ON personal_profiles(chat_id,user_id)"
        )
        self.connection.commit()

        self._connect_arena_market()
        # Upgrade live battles once. Restarting must never renew a PvP deadline.
        for raw in self.connection.execute(
            "SELECT id,mode,state_json FROM arena_battles WHERE status='active' AND state_json IS NOT NULL"
        ).fetchall():
            state = json.loads(raw["state_json"])
            timer = 0 if raw["mode"] == "wasteland" else ARENA_TURN_SECONDS
            if state.get("turn_timer_seconds") != timer:
                state["turn_timer_seconds"] = timer
                self.connection.execute(
                    "UPDATE arena_battles SET state_json=?,deadline=?,revision=revision+1 WHERE id=?",
                    (
                        json.dumps(state, ensure_ascii=False),
                        utc_timestamp() + timer if timer else 0,
                        raw["id"],
                    ),
                )
        self.connection.commit()

    def _slave_count_locked(self, chat_id: int, owner_id: int) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) AS amount FROM ownership WHERE chat_id=? AND owner_id=?",
                (chat_id, owner_id),
            ).fetchone()["amount"]
        )

    def _ensure_slave_profile_locked(self, chat_id: int, user_id: int) -> sqlite3.Row:
        now = utc_timestamp()
        self.connection.execute(
            """INSERT INTO slave_profiles(
                   chat_id, user_id, level, xp, class_id, loadout, updated_at
               ) VALUES (?, ?, 1, 0, 'ragamuffin', '["bum_punch"]', ?)
               ON CONFLICT(chat_id, user_id) DO NOTHING""",
            (chat_id, user_id, now),
        )
        return self.connection.execute(
            "SELECT * FROM slave_profiles WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()

    def _ensure_owner_profile_locked(self, chat_id: int, user_id: int) -> sqlite3.Row:
        now = utc_timestamp()
        current_slaves = self._slave_count_locked(chat_id, user_id)
        self.connection.execute(
            """INSERT INTO owner_profiles(
                   chat_id, user_id, level, xp, slave_record,
                   material_updated_at
               ) VALUES (?, ?, 1, 0, ?, ?)
               ON CONFLICT(chat_id, user_id) DO NOTHING""",
            (chat_id, user_id, current_slaves, now),
        )
        return self.connection.execute(
            "SELECT * FROM owner_profiles WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()

    def _grant_profile_xp_locked(
        self, table: str, chat_id: int, user_id: int, amount: int
    ) -> tuple[int, int]:
        if table not in {"slave_profiles", "personal_profiles", "owner_profiles"}:
            raise ValueError("Unknown profile table")
        if table in {"slave_profiles", "personal_profiles"}:
            before = self._arena_profile_locked(
                chat_id, user_id, table == "personal_profiles"
            )
        else:
            before = self._ensure_owner_profile_locked(chat_id, user_id)
        old_level = int(before["level"])
        total_xp = int(before["xp"]) + max(0, amount)
        if table != "owner_profiles":
            total_xp = min(total_xp, fighter_xp_limit())
        new_level = level_from_total_xp(
            total_xp, None if table == "owner_profiles" else MAX_FIGHTER_LEVEL
        )
        extra = ", updated_at=?" if table != "owner_profiles" else ""
        params: tuple[Any, ...]
        if table != "owner_profiles":
            params = (total_xp, new_level, utc_timestamp(), chat_id, user_id)
        else:
            params = (total_xp, new_level, chat_id, user_id)
        self.connection.execute(
            f"UPDATE {table} SET xp=?, level=?{extra} WHERE chat_id=? AND user_id=?",
            params,
        )
        if table != "owner_profiles" and new_level > old_level:
            self.connection.execute(
                f"UPDATE {table} SET skills_pending_at=COALESCE(skills_pending_at, ?) WHERE chat_id=? AND user_id=?",
                (utc_timestamp(), chat_id, user_id),
            )
        if table != "owner_profiles" and old_level < CLASS_SELECTION_LEVEL <= new_level:
            self.connection.execute(
                f"""UPDATE {table}
                   SET class_choice_pending_at=COALESCE(class_choice_pending_at, ?),
                       skills_pending_at=COALESCE(skills_pending_at, ?)
                   WHERE chat_id=? AND user_id=? AND class_id='ragamuffin'""",
                (utc_timestamp(), utc_timestamp(), chat_id, user_id),
            )
        return old_level, new_level

    def _material_capacity_for_level(self, level: int) -> int:
        return 0 if level < 5 else 100 + (level - 5) * 2

    def _owner_capacity_for_level(self, level: int) -> int:
        return 9 + level

    def _owner_has_capacity_locked(self, chat_id: int, owner_id: int) -> bool:
        profile = self._ensure_owner_profile_locked(chat_id, owner_id)
        return self._slave_count_locked(
            chat_id, owner_id
        ) < self._owner_capacity_for_level(int(profile["level"]))

    def _settle_materials_locked(self, chat_id: int, owner_id: int) -> sqlite3.Row:
        profile = self._ensure_owner_profile_locked(chat_id, owner_id)
        now = utc_timestamp()
        level = int(profile["level"])
        elapsed = max(0, now - int(profile["material_updated_at"]))
        fraction = float(profile["material_fraction"])
        raw = int(profile["raw_material"])
        if level >= 5 and elapsed:
            produced = (
                fraction + elapsed * self._slave_count_locked(chat_id, owner_id) / 3600
            )
            whole = int(produced)
            capacity = self._material_capacity_for_level(level)
            raw = min(capacity, raw + whole)
            fraction = produced - whole if raw < capacity else 0
        self.connection.execute(
            """UPDATE owner_profiles
               SET raw_material=?, material_fraction=?, material_updated_at=?
               WHERE chat_id=? AND user_id=?""",
            (raw, fraction, now, chat_id, owner_id),
        )
        return self.connection.execute(
            "SELECT * FROM owner_profiles WHERE chat_id=? AND user_id=?",
            (chat_id, owner_id),
        ).fetchone()

    def _refresh_owner_record_locked(self, chat_id: int, owner_id: int) -> None:
        profile = self._ensure_owner_profile_locked(chat_id, owner_id)
        current = self._slave_count_locked(chat_id, owner_id)
        record = int(profile["slave_record"])
        if current <= record:
            return
        increase = current - record
        self.connection.execute(
            "UPDATE owner_profiles SET slave_record=? WHERE chat_id=? AND user_id=?",
            (current, chat_id, owner_id),
        )
        self._grant_profile_xp_locked(
            "owner_profiles", chat_id, owner_id, increase * OWNER_RECORD_XP
        )

    def _fighter_catalog_locked(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return built-in combat content plus all valid superadmin content."""
        classes: dict[str, Any] = dict(FIGHTER_CLASSES)
        skills: dict[str, Any] = dict(BUILTIN_SKILLS)
        for row in self.connection.execute(
            "SELECT class_id, definition_json FROM custom_fighter_classes"
        ):
            try:
                classes[str(row["class_id"])] = fighter_class_from_dict(
                    str(row["class_id"]), json.loads(row["definition_json"])
                )
            except (TypeError, ValueError, json.JSONDecodeError, KeyError):
                continue
        for row in self.connection.execute(
            "SELECT skill_id, definition_json FROM custom_fighter_skills"
        ):
            try:
                skill = skill_from_dict(
                    str(row["skill_id"]), json.loads(row["definition_json"])
                )
                if skill.class_id in classes:
                    skills[skill.skill_id] = skill
            except (TypeError, ValueError, json.JSONDecodeError, KeyError):
                continue
        return classes, skills

    def _granted_content_locked(
        self, chat_id: int, user_id: int, content_type: str
    ) -> set[str]:
        return {
            str(row["content_id"])
            for row in self.connection.execute(
                """SELECT content_id FROM granted_fighter_content
                   WHERE chat_id=? AND user_id=? AND content_type=?""",
                (chat_id, user_id, content_type),
            )
        }

    async def create_custom_fighter_content(
        self,
        content_type: str,
        content_id: str,
        definition: dict[str, Any],
        created_by: int,
        *,
        hidden: bool = True,
    ) -> str:
        content_id = content_id.strip().lower().replace(" ", "_")
        if (
            not content_id
            or len(content_id) > 48
            or not content_id.replace("_", "").isalnum()
        ):
            return "invalid_id"
        try:
            if content_type == "class":
                if content_id in FIGHTER_CLASSES:
                    return "exists"
                fighter_class_from_dict(content_id, definition)
                table, id_column = "custom_fighter_classes", "class_id"
            elif content_type == "skill":
                if content_id in BUILTIN_SKILLS:
                    return "exists"
                skill_from_dict(content_id, definition)
                table, id_column = "custom_fighter_skills", "skill_id"
            else:
                return "invalid_type"
        except (ValueError, TypeError, KeyError):
            return "invalid_definition"
        async with self._lock:
            try:
                if content_type == "class":
                    self.connection.execute(
                        f"""INSERT INTO {table}({id_column}, name, hidden, definition_json, created_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            content_id,
                            str(definition["name"]).strip(),
                            int(hidden),
                            json.dumps(definition, ensure_ascii=False),
                            created_by,
                            utc_timestamp(),
                        ),
                    )
                else:
                    self.connection.execute(
                        f"""INSERT INTO {table}({id_column}, name, definition_json, created_by, created_at)
                            VALUES (?, ?, ?, ?, ?)""",
                        (
                            content_id,
                            str(definition["name"]).strip(),
                            json.dumps(definition, ensure_ascii=False),
                            created_by,
                            utc_timestamp(),
                        ),
                    )
            except sqlite3.IntegrityError:
                self.connection.rollback()
                return "exists"
            self.connection.commit()
            return "created"

    async def grant_custom_fighter_content(
        self,
        chat_id: int,
        user_id: int,
        content_type: str,
        content_id: str,
        granted_by: int,
        personal: bool = False,
    ) -> str:
        table = {
            "class": ("custom_fighter_classes", "class_id"),
            "skill": ("custom_fighter_skills", "skill_id"),
        }.get(content_type)
        if not table:
            return "invalid_type"
        async with self._lock:
            present = self.connection.execute(
                f"SELECT 1 FROM {table[0]} WHERE {table[1]}=?", (content_id,)
            ).fetchone()
            if not present:
                return "not_found"
            if content_type == "skill":
                from arena_engine import MAX_LEARNED_ACTIVE_SKILLS

                known = self._arena_known_skills_locked(chat_id, user_id, personal)
                if content_id not in known and len(known) >= MAX_LEARNED_ACTIVE_SKILLS:
                    self.connection.commit()
                    return "Максимум 6 изученных активных навыков. Сначала забудь один."
            self.connection.execute(
                """INSERT INTO granted_fighter_content(
                       chat_id, user_id, content_type, content_id, granted_by, granted_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id, user_id, content_type, content_id) DO NOTHING""",
                (
                    chat_id,
                    user_id,
                    content_type,
                    content_id,
                    granted_by,
                    utc_timestamp(),
                ),
            )
            self.connection.commit()
            return "granted"

    async def get_fighter_catalog(self) -> tuple[dict[str, Any], dict[str, Any]]:
        async with self._lock:
            return self._fighter_catalog_locked()

    async def arena_admin_grant(
        self,
        chat: int,
        user: int,
        kind: str,
        content_id: str,
        author: int,
        personal=False,
    ) -> str:
        if author != 1980056841:
            raise ValueError("Недостаточно прав.")
        result = await self.grant_custom_fighter_content(
            chat, user, kind, content_id, author, personal
        )
        if result == "granted" and kind == "skill":
            async with self._lock:
                self.connection.execute(
                    "INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)",
                    (chat, user, int(personal), "skill", content_id),
                )
                self._arena_known_skills_locked(chat, user, personal)
                _, catalog = self._fighter_catalog_locked()
                profile = self._arena_profile_locked(chat, user, personal)
                if catalog[content_id].unlock_level <= profile["level"]:
                    self._arena_remember_locked(
                        chat, user, personal, "skill", content_id
                    )
                self.connection.commit()
        if result != "granted" or kind != "class":
            return result
        async with self._lock:
            if self._arena_busy_locked(chat, user):
                return "Класс выдан, но назначить его можно после текущего боя."
            profile = self._arena_profile_locked(chat, user, personal)
            _, skills = self._fighter_catalog_locked()
            loadout = normalize_loadout(
                content_id,
                int(profile["level"]),
                None,
                skills,
                self._arena_grants_locked(chat, user, personal),
                self._arena_known_skills_locked(
                    chat, user, personal, dict(profile, class_id=content_id)
                ),
            )
            table = "personal_profiles" if personal else "slave_profiles"
            self.connection.execute(
                f"UPDATE {table} SET class_id=?,loadout=?,class_choice_pending_at=NULL,skills_pending_at=? WHERE chat_id=? AND user_id=?",
                (content_id, json.dumps(loadout), utc_timestamp(), chat, user),
            )
            classes, _ = self._fighter_catalog_locked()
            defaults = [
                f"inherent:{content_id}:{i}"
                for i in range(min(2, len(classes[content_id].passives)))
            ]
            self.connection.execute(
                f"UPDATE {table} SET passive_loadout=? WHERE chat_id=? AND user_id=?",
                (json.dumps(defaults), chat, user),
            )
            self.connection.commit()
            return "granted"

    async def get_slave_profile(self, chat_id: int, user_id: int) -> sqlite3.Row:
        async with self._lock:
            row = self._ensure_slave_profile_locked(chat_id, user_id)
            self.connection.commit()
            return row

    async def get_owner_profile(self, chat_id: int, user_id: int) -> dict[str, Any]:
        async with self._lock:
            profile = self._settle_materials_locked(chat_id, user_id)
            self.connection.commit()
            return {
                **dict(profile),
                "slave_count": self._slave_count_locked(chat_id, user_id),
                "slave_capacity": self._owner_capacity_for_level(int(profile["level"])),
                "material_capacity": self._material_capacity_for_level(
                    int(profile["level"])
                ),
            }

    async def grant_slave_xp(
        self, chat_id: int, user_id: int, amount: int
    ) -> dict[str, int]:
        async with self._lock:
            old_level, new_level = self._grant_profile_xp_locked(
                "slave_profiles", chat_id, user_id, amount
            )
            row = self.connection.execute(
                "SELECT xp FROM slave_profiles WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            self.connection.commit()
            return {
                "old_level": old_level,
                "new_level": new_level,
                "xp": int(row["xp"]),
            }

    async def grant_owner_xp(
        self, chat_id: int, user_id: int, amount: int
    ) -> dict[str, int]:
        async with self._lock:
            old_level, new_level = self._grant_profile_xp_locked(
                "owner_profiles", chat_id, user_id, amount
            )
            row = self.connection.execute(
                "SELECT xp FROM owner_profiles WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            self.connection.commit()
            return {
                "old_level": old_level,
                "new_level": new_level,
                "xp": int(row["xp"]),
            }

    async def choose_slave_class(
        self, chat_id: int, user_id: int, requested_name: str
    ) -> str:
        normalized = " ".join(requested_name.casefold().split())
        async with self._lock:
            profile = self._ensure_slave_profile_locked(chat_id, user_id)
            if int(profile["level"]) < CLASS_SELECTION_LEVEL:
                return "low_level"
            if profile["class_id"] != "ragamuffin":
                return "already_chosen"
            class_id = VISIBLE_CLASS_ALIASES.get(normalized)
            if class_id is None:
                # SQLite's NOCASE collation only knows ASCII; names of hidden
                # classes are normally Russian, so compare normalized text here.
                custom_rows = self.connection.execute(
                    """SELECT c.class_id, c.name FROM custom_fighter_classes c
                       JOIN granted_fighter_content g ON g.content_id=c.class_id
                       WHERE g.chat_id=? AND g.user_id=? AND g.content_type='class'""",
                    (chat_id, user_id),
                ).fetchall()
                for custom in custom_rows:
                    if " ".join(str(custom["name"]).casefold().split()) == normalized:
                        class_id = str(custom["class_id"])
                        break
            if class_id is None or class_id == "ragamuffin":
                return "unknown"
            _classes, skills = self._fighter_catalog_locked()
            granted_skills = self._arena_grants_locked(chat_id, user_id, False)
            loadout = normalize_loadout(
                class_id,
                int(profile["level"]),
                None,
                skills,
                granted_skills,
                self._arena_known_skills_locked(
                    chat_id, user_id, False, dict(profile, class_id=class_id)
                ),
            )
            self.connection.execute(
                """UPDATE slave_profiles
                   SET class_id=?, loadout=?, class_choice_pending_at=NULL,
                       skills_pending_at=?, updated_at=?
                   WHERE chat_id=? AND user_id=?""",
                (
                    class_id,
                    json.dumps(loadout),
                    utc_timestamp(),
                    utc_timestamp(),
                    chat_id,
                    user_id,
                ),
            )
            self._arena_equip_class_passives_locked(chat_id, user_id, False, class_id)
            self.connection.commit()
            return class_id

    async def set_slave_loadout(
        self,
        chat_id: int,
        slave_id: int,
        actor_id: int,
        skill_ids: list[str],
    ) -> str:
        async with self._lock:
            profile = self._ensure_slave_profile_locked(chat_id, slave_id)
            if actor_id != slave_id:
                owner = self.connection.execute(
                    "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                    (chat_id, slave_id),
                ).fetchone()
                pending_at = profile["skills_pending_at"]
                if not owner or int(owner["owner_id"]) != actor_id:
                    return "forbidden"
                if (
                    pending_at is None
                    or utc_timestamp() < int(pending_at) + SKILL_DELEGATION_SECONDS
                ):
                    return "too_early"
            _classes, skills = self._fighter_catalog_locked()
            granted_skills = self._arena_grants_locked(chat_id, slave_id, False)
            normalized = normalize_loadout(
                str(profile["class_id"]),
                int(profile["level"]),
                skill_ids,
                skills,
                granted_skills,
                self._arena_known_skills_locked(chat_id, slave_id, False),
            )
            self.connection.execute(
                """UPDATE slave_profiles SET loadout=?, skills_pending_at=NULL, updated_at=?
                   WHERE chat_id=? AND user_id=?""",
                (json.dumps(normalized), utc_timestamp(), chat_id, slave_id),
            )
            self.connection.commit()
            return "updated"

    async def craft_owner_item(self, chat_id: int, owner_id: int, item: str) -> str:
        return "Крафт убран. Зелья и конфеты продаёт странствующий торговец."

    async def give_candy(self, chat_id: int, owner_id: int, slave_id: int) -> str:
        async with self._lock:
            owned = self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?",
                (chat_id, owner_id, slave_id),
            ).fetchone()
            if not owned:
                return "not_owned"
            item = self.connection.execute(
                "SELECT id FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind='candy'",
                (chat_id, owner_id),
            ).fetchone()
            if not item:
                return "no_candy"
            item_id = item["id"]
        await self.arena_use_item(chat_id, owner_id, item_id, slave_id, False)
        return "given"

    def _arena_profile_locked(self, chat_id: int, user_id: int, personal=False):
        if not personal:
            return self._ensure_slave_profile_locked(chat_id, user_id)
        self.connection.execute(
            """INSERT OR IGNORE INTO personal_profiles(chat_id,user_id,level,xp,class_id,loadout,updated_at)
               VALUES(?,?,1,0,'ragamuffin','["bum_punch"]',?)""",
            (chat_id, user_id, utc_timestamp()),
        )
        return self.connection.execute(
            "SELECT * FROM personal_profiles WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()

    def _arena_row_locked(self, token: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM arena_battles WHERE token=?", (token,)
        ).fetchone()
        if not row:
            raise ValueError("Бой не найден.")
        return dict(row)

    def _arena_owns_locked(self, chat_id: int, owner: int, fighter: int) -> bool:
        return bool(
            self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?",
                (chat_id, owner, fighter),
            ).fetchone()
        )

    def _arena_busy_locked(self, chat: int, user: int, exclude=0) -> bool:
        return bool(
            self.connection.execute(
                """SELECT 1 FROM arena_battles WHERE chat_id=? AND status IN ('pending','active')
               AND id<>? AND (a_owner=? OR b_owner=? OR a_fighter=? OR b_fighter=?)""",
                (chat, exclude, user, user, user, user),
            ).fetchone()
        )

    def _arena_combat_slot_locked(self, chat: int, owner: int, slave: int):
        row = self.connection.execute(
            """SELECT s.slot FROM arena_combat_slots s JOIN ownership o
               ON o.chat_id=s.chat_id AND o.slave_id=s.slave_id AND o.owner_id=s.owner_id
               WHERE s.chat_id=? AND s.owner_id=? AND s.slave_id=?""",
            (chat, owner, slave),
        ).fetchone()
        return int(row["slot"]) if row else None

    def _arena_require_combat_locked(self, chat: int, owner: int, slave: int) -> None:
        if not self._arena_owns_locked(chat, owner, slave):
            raise ValueError("Этот раб больше не принадлежит участнику боя.")
        if self._arena_combat_slot_locked(chat, owner, slave) is None:
            raise ValueError(
                "Сначала экипируйте раба в одном из пяти боевых слотов в арене."
            )
        if self.connection.execute(
            "SELECT 1 FROM business_workers WHERE chat_id=? AND worker_id=?",
            (chat, slave),
        ).fetchone():
            raise ValueError("Боевой раб должен быть снят с работы.")

    async def arena_equip_slave(
        self, chat: int, actor: int, slave: int, equipped: bool
    ) -> str:
        async with self._lock:
            self._arena_expire_locked()
            self.connection.commit()
            if not self._arena_owns_locked(chat, actor, slave):
                raise ValueError("Экипировать можно только своего раба.")
            current = self._arena_combat_slot_locked(chat, actor, slave)
            if bool(current) == equipped:
                return "Без изменений."
            if self._arena_busy_locked(chat, slave):
                raise ValueError(
                    "Нельзя менять боевой слот раба, выбранного для текущего боя."
                )
            if not equipped:
                self.connection.execute(
                    "DELETE FROM arena_combat_slots WHERE chat_id=? AND slave_id=?",
                    (chat, slave),
                )
                self.connection.commit()
                return "Раб снят с боевого слота. Его снова можно назначить на работу."
            used = {
                r["slot"]
                for r in self.connection.execute(
                    "SELECT slot FROM arena_combat_slots WHERE chat_id=? AND owner_id=?",
                    (chat, actor),
                )
            }
            slot = next(
                (n for n in range(1, COMBAT_SLAVE_CAPACITY + 1) if n not in used), None
            )
            if slot is None:
                raise ValueError(
                    "Все 5 боевых слотов заняты. Сначала снимите одного из бойцов."
                )
            try:
                # Settle already earned income before taking the worker off the job.
                self._settle_business_locked(chat, actor, utc_timestamp())
                self.connection.execute(
                    "DELETE FROM business_workers WHERE chat_id=? AND worker_id=?",
                    (chat, slave),
                )
                self.connection.execute(
                    "INSERT INTO arena_combat_slots(chat_id,owner_id,slave_id,slot) VALUES(?,?,?,?)",
                    (chat, actor, slave, slot),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return f"Раб экипирован в слот {slot}/5 и снят с работы."

    async def arena_combat_slaves(self, chat: int, owner: int) -> list[dict]:
        data = await self.arena_menu(chat, owner)
        return [s for s in data["slaves"] if s["combat_slot"] and not s["working_role"]]

    def _arena_refund_locked(self, row: dict, status: str) -> None:
        for key in ("a", "b"):
            amount = int(row["escrow_" + key])
            if amount:
                self._add_francs_locked(row["chat_id"], row[key + "_owner"], amount)
        self.connection.execute(
            "UPDATE arena_battles SET status=?,escrow_a=0,escrow_b=0,finished_at=?,revision=revision+1 WHERE id=?",
            (status, utc_timestamp(), row["id"]),
        )

    def _arena_source_locked(
        self, chat: int, user: int, owner: int, controlled: bool, personal: bool
    ):
        profile = self._arena_profile_locked(chat, user, personal)
        return dict(
            slave_id=user,
            owner_id=owner,
            controlled=controlled,
            class_id=profile["class_id"],
            level=profile["level"],
            loadout=json.loads(profile["loadout"]),
            granted_skills=self._arena_grants_locked(chat, user, personal),
            known_skills=self._arena_known_skills_locked(chat, user, personal),
            passive_details=self._arena_selected_passives_locked(
                chat, user, personal, profile
            ),
        )

    def _arena_activate_locked(self, row: dict) -> None:
        if not (row["b_accepted"] and row["a_fighter"] and row["b_fighter"]):
            return
        if row["mode"] == "slaves":
            for key in ("a", "b"):
                self._arena_require_combat_locked(
                    row["chat_id"], row[key + "_owner"], row[key + "_fighter"]
                )
                if not row[key + "_control"] and not row[key + "_consent"]:
                    return
        classes, skills = self._fighter_catalog_locked()
        sources = [
            self._arena_source_locked(
                row["chat_id"],
                row[k + "_fighter"],
                row[k + "_owner"],
                bool(row[k + "_control"]),
                row["mode"] == "personal",
            )
            for k in ("a", "b")
        ]
        state = create_battle_state(*sources, classes=classes, skills=skills)
        state["turn_timer_seconds"] = ARENA_TURN_SECONDS
        a_speed, b_speed = (
            effective_stat(state["sides"][k], "speed") for k in ("a", "b")
        )
        state["active_side"] = (
            random.SystemRandom().choice(("a", "b"))
            if a_speed == b_speed
            else "a" if a_speed > b_speed else "b"
        )
        self.connection.execute(
            "UPDATE arena_battles SET status='active',state_json=?,deadline=? WHERE id=?",
            (
                json.dumps(state, ensure_ascii=False),
                utc_timestamp() + ARENA_TURN_SECONDS,
                row["id"],
            ),
        )

    async def arena_offer(
        self, chat: int, actor: int, target: int, mode="slaves", stake=0
    ) -> dict:
        if (
            mode not in {"slaves", "personal"}
            or actor == target
            or stake < 0
            or stake > 1000000
        ):
            raise ValueError("Некорректный вызов.")
        async with self._lock:
            self._arena_expire_locked()
            self.connection.commit()
            if self._arena_busy_locked(chat, actor) or self._arena_busy_locked(
                chat, target
            ):
                self.connection.commit()
                raise ValueError("У одного из игроков уже есть бой.")
            if mode == "slaves" and (
                not self._slave_count_locked(chat, actor)
                or not self._slave_count_locked(chat, target)
            ):
                raise ValueError("Для боя рабов у обоих владельцев должен быть раб.")
            if stake:
                for user in (actor, target):
                    balance = self.connection.execute(
                        "SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?",
                        (chat, user),
                    ).fetchone()
                    if not balance or balance["balance"] < stake:
                        raise ValueError("Одному из игроков не хватает франков.")
            token = secrets.token_urlsafe(16)
            now = utc_timestamp()
            self.connection.execute(
                """INSERT INTO arena_battles(token,chat_id,mode,a_owner,b_owner,a_fighter,b_fighter,
                   a_control,b_control,a_consent,b_consent,stake,escrow_a,created_at,deadline)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    token,
                    chat,
                    mode,
                    actor,
                    target,
                    actor if mode == "personal" else None,
                    target if mode == "personal" else None,
                    int(mode == "slaves"),
                    int(mode == "slaves"),
                    int(mode == "personal"),
                    int(mode == "personal"),
                    stake,
                    stake,
                    now,
                    now + ARENA_PREPARATION_SECONDS,
                ),
            )
            if stake:
                self.connection.execute(
                    "UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=?",
                    (stake, now, chat, actor),
                )
            self.connection.commit()
            return self._arena_row_locked(token)

    async def arena_set_message(self, token: str, message_id: int) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE arena_battles SET message_id=? WHERE token=?",
                (message_id, token),
            )
            self.connection.commit()

    async def arena_get(self, token: str) -> dict:
        async with self._lock:
            row = self._arena_row_locked(token)
            if (
                row["status"] in {"pending", "active"}
                and row["mode"] != "wasteland"
                and row["deadline"] <= utc_timestamp()
            ):
                self._arena_expire_locked()
                self.connection.commit()
                row = self._arena_row_locked(token)
            return row

    async def arena_setup(
        self, token: str, actor: int, action: str, fighter=0, controlled=True
    ) -> dict:
        async with self._lock:
            row = self._arena_row_locked(token)
            if row["status"] != "pending" or row["deadline"] <= utc_timestamp():
                raise ValueError("Вызов уже закрыт.")
            key = (
                "a"
                if actor == row["a_owner"]
                else "b" if actor == row["b_owner"] else None
            )
            if action == "cancel":
                if key != "a":
                    raise ValueError("Отменить может создатель вызова.")
                self._arena_refund_locked(row, "cancelled")
            elif action == "refuse":
                if key != "b":
                    raise ValueError("Отклонить может соперник.")
                self._arena_refund_locked(row, "refused")
            elif action == "accept":
                if key != "b":
                    raise ValueError("Принять может соперник.")
                if not row["b_accepted"]:
                    stake = row["stake"]
                    if stake:
                        changed = self.connection.execute(
                            "UPDATE franc_balances SET balance=balance-?,updated_at=? WHERE chat_id=? AND user_id=? AND balance>=?",
                            (stake, utc_timestamp(), row["chat_id"], actor, stake),
                        ).rowcount
                        if not changed:
                            raise ValueError("Недостаточно франков.")
                    self.connection.execute(
                        "UPDATE arena_battles SET b_accepted=1,escrow_b=? WHERE id=?",
                        (stake, row["id"]),
                    )
            elif action == "select":
                if (
                    not key
                    or row["mode"] != "slaves"
                    or not self._arena_owns_locked(row["chat_id"], actor, fighter)
                ):
                    raise ValueError("Выберите своего раба.")
                if self._arena_busy_locked(row["chat_id"], fighter, row["id"]):
                    raise ValueError("Этот боец уже участвует в другом бою.")
                self._arena_require_combat_locked(row["chat_id"], actor, fighter)
                self.connection.execute(
                    f"UPDATE arena_battles SET {key}_fighter=?,{key}_control=?,{key}_consent=0 WHERE id=?",
                    (fighter, int(controlled), row["id"]),
                )
            elif action == "consent":
                key = next(
                    (k for k in ("a", "b") if row[k + "_fighter"] == actor), None
                )
                if not key:
                    raise ValueError("Вы не выбранный боец.")
                self.connection.execute(
                    f"UPDATE arena_battles SET {key}_consent=1 WHERE id=?", (row["id"],)
                )
            else:
                raise ValueError("Неизвестное действие.")
            try:
                updated = self._arena_row_locked(token)
                if updated["status"] == "pending":
                    self._arena_activate_locked(updated)
                self.connection.execute(
                    "UPDATE arena_battles SET revision=revision+1 WHERE id=?",
                    (row["id"],),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self._arena_row_locked(token)

    def _arena_finish_locked(self, row: dict, state: dict) -> None:
        # Called only while status is active, within the action transaction.
        winner = state["winner"]
        if winner and row["escrow_a"] and row["escrow_b"]:
            pot = row["escrow_a"] + row["escrow_b"]
            self._add_francs_locked(
                row["chat_id"],
                row[winner + "_owner"],
                pot - pot * ARENA_FEE_PERCENT // 100,
            )
        elif not winner:
            for k in ("a", "b"):
                if row["escrow_" + k]:
                    self._add_francs_locked(
                        row["chat_id"], row[k + "_owner"], row["escrow_" + k]
                    )
        low_reward = False
        if row["mode"] != "wasteland":
            first, second = sorted((row["a_fighter"], row["b_fighter"]))
            day = datetime.now(timezone.utc).date().isoformat()
            previous = self.connection.execute(
                "SELECT count FROM arena_pair_rewards WHERE chat_id=? AND first_id=? AND second_id=? AND day=?",
                (row["chat_id"], first, second, day),
            ).fetchone()
            low_reward = bool(previous and previous["count"] >= 3)
            self.connection.execute(
                "INSERT INTO arena_pair_rewards VALUES(?,?,?,?,1) ON CONFLICT(chat_id,first_id,second_id,day) DO UPDATE SET count=count+1",
                (row["chat_id"], first, second, day),
            )
        rewards = {}
        for k in ("a", "b"):
            if row[k + "_fighter"] == 0:
                continue
            xp = (
                1 if low_reward else (10 if winner == k else 8 if winner is None else 7)
            )
            if state.get("finish_reason") == "turn_limit" and not state.get(
                "had_player_action"
            ):
                xp = 0  # Two idle players cannot farm XP by waiting out skips.
            if row["mode"] == "wasteland":
                xp = (
                    0
                    if state.get("finish_reason") in {"surrender", "timeout"}
                    else (5 + 2 * row["floor"] if winner == k else 3)
                )
            table = (
                "personal_profiles"
                if row["mode"] == "personal"
                or (row["mode"] == "wasteland" and row["personal_solo"])
                else "slave_profiles"
            )
            before_xp = self._arena_profile_locked(
                row["chat_id"], row[k + "_fighter"], table == "personal_profiles"
            )["xp"]
            self._grant_profile_xp_locked(
                table, row["chat_id"], row[k + "_fighter"], xp
            )
            after_xp = self._arena_profile_locked(
                row["chat_id"], row[k + "_fighter"], table == "personal_profiles"
            )["xp"]
            rewards[k] = max(0, after_xp - before_xp)
            if (
                table == "slave_profiles"
                and winner == k
                and not (
                    row["mode"] == "wasteland"
                    and state.get("finish_reason") in {"surrender", "timeout"}
                )
            ):
                actual_owner = self.connection.execute(
                    "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                    (row["chat_id"], row[k + "_fighter"]),
                ).fetchone()
                if actual_owner:
                    owner_id = int(actual_owner["owner_id"])
                    self._settle_materials_locked(row["chat_id"], owner_id)
                    self._grant_profile_xp_locked(
                        "owner_profiles",
                        row["chat_id"],
                        owner_id,
                        1 if low_reward else 6,
                    )
        state["rewards"] = rewards
        pot = row["escrow_a"] + row["escrow_b"]
        state["payout"] = pot - pot * ARENA_FEE_PERCENT // 100 if winner else 0
        self.connection.execute(
            "UPDATE arena_battles SET status='finished',escrow_a=0,escrow_b=0,finished_at=? WHERE id=?",
            (utc_timestamp(), row["id"]),
        )

    async def arena_action(
        self, token: str, actor: int, revision: int, skill_id: str
    ) -> dict:
        async with self._lock:
            row = self._arena_row_locked(token)
            if row["status"] != "active":
                raise ValueError("Бой не активен.")
            if row["mode"] != "wasteland" and row["deadline"] <= utc_timestamp():
                self._arena_expire_locked()
                self.connection.commit()
                row = self._arena_row_locked(token)
                if row["status"] != "active":
                    raise ValueError("Бой завершён.")
            if row["revision"] != revision:
                raise ValueError("Ход уже изменился. Обновите бой.")
            state = json.loads(row["state_json"])
            key = state["active_side"]
            if skill_id == "surrender":
                key = next(
                    (
                        k
                        for k, s in state["sides"].items()
                        if s["controller_id"] == actor
                    ),
                    None,
                )
                if key is None:
                    raise ValueError("Сдаться может только управляющий бойцом.")
            if state["sides"][key]["controller_id"] != actor:
                raise ValueError("Вы не управляете бойцом в этот ход.")
            if row["mode"] == "slaves" or (
                row["mode"] == "wasteland"
                and not row["personal_solo"]
                and row["a_fighter"] != actor
            ):
                for k in ("a", "b") if row["mode"] == "slaves" else ("a",):
                    if not self._arena_owns_locked(
                        row["chat_id"], row[k + "_owner"], row[k + "_fighter"]
                    ):
                        self._arena_refund_locked(row, "cancelled")
                        self.connection.commit()
                        raise ValueError("Владелец бойца сменился. Бой отменён.")
            _, skills = self._fighter_catalog_locked()
            try:
                if skill_id == "surrender":
                    state.update(
                        finished=True,
                        winner="b" if key == "a" else "a",
                        finish_reason="surrender",
                    )
                elif skill_id == "potion":
                    item = self.connection.execute(
                        "SELECT * FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind='potion' AND content_id='healing'",
                        (row["chat_id"], actor),
                    ).fetchone()
                    if not item:
                        raise ValueError("Нет зелья.")
                    self._arena_consume_item_locked(item)
                    use_healing_potion(state, key)
                else:
                    resolve_skill(state, key, skill_id, skills)
                while (
                    row["mode"] == "wasteland"
                    and not state["finished"]
                    and state["active_side"] == "b"
                ):
                    ai = state["sides"]["b"]
                    choices = [
                        s
                        for s in ai["loadout"]
                        if skills[s].cost <= ai["resource"]
                        and not ai["cooldowns"].get(s, 0)
                    ]
                    resolve_skill(
                        state, "b", random.choice(choices or ["bum_punch"]), skills
                    )
                if state["finished"]:
                    self._arena_finish_locked(row, state)
                self.connection.execute(
                    "UPDATE arena_battles SET state_json=?,revision=revision+1,deadline=? WHERE id=?",
                    (
                        json.dumps(state, ensure_ascii=False),
                        (
                            (
                                row["deadline"]
                                if skill_id == "potion"
                                else utc_timestamp() + ARENA_TURN_SECONDS
                            )
                            if row["mode"] != "wasteland"
                            else 0
                        ),
                        row["id"],
                    ),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self._arena_row_locked(token)

    def _arena_expire_locked(self) -> list[dict]:
        expired = []
        now = utc_timestamp()
        for raw in self.connection.execute(
            "SELECT * FROM arena_battles WHERE mode<>'wasteland' AND status IN ('pending','active') AND (deadline<=? OR (message_id IS NULL AND created_at<=?))",
            (now, now - 60),
        ).fetchall():
            row = dict(raw)
            invalid_owner = row["mode"] == "slaves" and any(
                row[k + "_fighter"]
                and not self._arena_owns_locked(
                    row["chat_id"], row[k + "_owner"], row[k + "_fighter"]
                )
                for k in ("a", "b")
            )
            if invalid_owner or (
                row["mode"] != "wasteland" and row["message_id"] is None
            ):
                self._arena_refund_locked(row, "cancelled")
            elif row["status"] == "active" and row["state_json"]:
                state = json.loads(row["state_json"])
                skip_turn(state)
                if state["finished"]:
                    self._arena_finish_locked(row, state)
                self.connection.execute(
                    "UPDATE arena_battles SET state_json=?,deadline=?,revision=revision+1 WHERE id=?",
                    (
                        json.dumps(state, ensure_ascii=False),
                        now + ARENA_TURN_SECONDS,
                        row["id"],
                    ),
                )
            else:
                self._arena_refund_locked(row, "expired")
            expired.append(self._arena_row_locked(row["token"]))
        return expired

    async def arena_expire(self) -> list[dict]:
        async with self._lock:
            result = self._arena_expire_locked()
            self.connection.commit()
            return result

    async def arena_wasteland(
        self, chat: int, actor: int, fighter=0, previous="", personal: bool = True
    ) -> dict:
        async with self._lock:
            floor = 1
            if previous:
                old = self._arena_row_locked(previous)
                if (
                    old["mode"] != "wasteland"
                    or old["a_owner"] != actor
                    or old["chat_id"] != chat
                    or old["status"] != "finished"
                    or json.loads(old["state_json"])["winner"] != "a"
                ):
                    raise ValueError("Сначала победите на текущем этаже.")
                floor = old["floor"] + 1
                personal = bool(old["personal_solo"])
                fighter = old["a_fighter"]
            if self._arena_busy_locked(chat, actor):
                raise ValueError("Сначала завершите текущий бой.")
            fighter = fighter or actor
            if personal and fighter != actor:
                raise ValueError("Личный персонаж может быть только своим.")
            if (
                not personal
                and fighter != actor
                and not self._arena_owns_locked(chat, actor, fighter)
            ):
                raise ValueError("Это не ваш раб.")
            if (
                not personal
                and fighter == actor
                and not self.connection.execute(
                    "SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?",
                    (chat, actor),
                ).fetchone()
            ):
                raise ValueError("Вы не состоите в рабстве.")
            if self._arena_busy_locked(chat, fighter):
                raise ValueError("Боец уже занят.")
            if not personal:
                owner = actor
                if fighter == actor:
                    owner = self.connection.execute(
                        "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                        (chat, actor),
                    ).fetchone()["owner_id"]
                self._arena_require_combat_locked(chat, owner, fighter)
            source = self._arena_source_locked(chat, fighter, actor, False, personal)
            source["controlled"] = False
            enemy = dict(
                slave_id=0,
                owner_id=0,
                controlled=False,
                class_id="ragamuffin",
                level=source["level"] + floor - 1,
                loadout=["bum_punch", "dust_in_eyes"],
            )
            classes, skills = self._fighter_catalog_locked()
            state = create_battle_state(source, enemy, classes=classes, skills=skills)
            # The owner can pilot a slave in PvE; the same 20% control penalty applies.
            if not personal and fighter != actor:
                source["controlled"] = True
                state = create_battle_state(
                    source, enemy, classes=classes, skills=skills
                )
            token = secrets.token_urlsafe(16)
            now = utc_timestamp()
            state["turn_timer_seconds"] = 0
            self.connection.execute(
                """INSERT INTO arena_battles(token,chat_id,mode,a_owner,b_owner,a_fighter,b_fighter,a_control,b_accepted,status,state_json,floor,created_at,deadline)
                   VALUES(?,?,'wasteland',?,0,?,0,?,1,'active',?,?,?,?)""",
                (
                    token,
                    chat,
                    actor,
                    fighter,
                    int(not personal and fighter != actor),
                    json.dumps(state, ensure_ascii=False),
                    floor,
                    now,
                    0,
                ),
            )
            self.connection.execute(
                "UPDATE arena_battles SET personal_solo=? WHERE token=?",
                (int(personal), token),
            )
            self.connection.commit()
            return self._arena_row_locked(token)

    async def arena_set_sprite(
        self, chat: int, actor: int, png: bytes, pixel_art: bool
    ) -> str:
        # HTTP boundary has already decoded/validated PNG. No user/target supplied by caller.
        key = hashlib.sha256(png).hexdigest()
        async with self._lock:
            self.connection.execute(
                """INSERT INTO arena_sprites(chat_id,user_id,sprite_key,png,pixel_art)
                   VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
                   sprite_key=excluded.sprite_key,png=excluded.png,pixel_art=excluded.pixel_art""",
                (chat, actor, key, png, int(pixel_art)),
            )
            self.connection.commit()
        return key

    async def arena_reset_sprite(self, chat: int, actor: int) -> None:
        async with self._lock:
            self.connection.execute(
                "DELETE FROM arena_sprites WHERE chat_id=? AND user_id=?", (chat, actor)
            )
            self.connection.commit()

    async def arena_sprite_info(self, chat: int, user: int) -> dict:
        async with self._lock:
            row = self.connection.execute(
                "SELECT sprite_key,pixel_art FROM arena_sprites WHERE chat_id=? AND user_id=?",
                (chat, user),
            ).fetchone()
            if not row:
                return dict(sprite_url=None, pixel_art=False)
            return dict(
                sprite_url="/sprites/" + row["sprite_key"] + ".png",
                pixel_art=bool(row["pixel_art"]),
            )

    async def arena_sprite_png(self, key: str) -> bytes | None:
        async with self._lock:
            row = self.connection.execute(
                "SELECT png FROM arena_sprites WHERE sprite_key=? LIMIT 1", (key,)
            ).fetchone()
            return bytes(row["png"]) if row else None

    async def arena_menu(self, chat: int, actor: int) -> dict:
        async with self._lock:
            personal = dict(self._arena_profile_locked(chat, actor, True))
            personal["loadout"] = json.loads(personal["loadout"])
            slaves = []
            for row in self.connection.execute(
                """SELECT o.slave_id,u.display_name,u.username,s.slot,w.role FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   LEFT JOIN arena_combat_slots s ON s.chat_id=o.chat_id AND s.slave_id=o.slave_id AND s.owner_id=o.owner_id
                   LEFT JOIN business_workers w ON w.chat_id=o.chat_id AND w.worker_id=o.slave_id AND w.owner_id=o.owner_id
                   WHERE o.chat_id=? AND o.owner_id=? ORDER BY s.slot IS NULL,s.slot,o.acquired_at""",
                (chat, actor),
            ).fetchall():
                profile = dict(self._arena_profile_locked(chat, row["slave_id"]))
                profile["loadout"] = json.loads(profile["loadout"])
                slaves.append(
                    {
                        **profile,
                        "name": row["display_name"] or str(row["slave_id"]),
                        "username": row["username"],
                        "combat_slot": row["slot"],
                        "working_role": row["role"],
                        "in_battle": self._arena_busy_locked(chat, row["slave_id"]),
                    }
                )
            self_slave = None
            owned_by = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat, actor),
            ).fetchone()
            if owned_by:
                self_slave = dict(self._arena_profile_locked(chat, actor))
                self_slave["loadout"] = json.loads(self_slave["loadout"])
                self_slave["name"] = "Мой персонаж-раб"
                self_slave["combat_slot"] = self._arena_combat_slot_locked(
                    chat, owned_by["owner_id"], actor
                )
            self._refresh_owner_record_locked(chat, actor)
            owner = dict(self._settle_materials_locked(chat, actor))
            active = [
                dict(r)
                for r in self.connection.execute(
                    "SELECT token,mode,status FROM arena_battles WHERE chat_id=? AND status IN ('pending','active') AND (a_owner=? OR b_owner=? OR a_fighter=? OR b_fighter=?)",
                    (chat, actor, actor, actor, actor),
                )
            ]
            self.connection.commit()
            return dict(
                personal=personal,
                slaves=slaves,
                self_slave=self_slave,
                owner=owner,
                active=active,
                combat_capacity=COMBAT_SLAVE_CAPACITY,
                combat_count=sum(bool(s["combat_slot"]) for s in slaves),
            )

    async def arena_edit_profile(
        self, chat: int, actor: int, user: int, personal: bool, action: str, value
    ) -> str:
        async with self._lock:
            profile = self._arena_profile_locked(chat, user, personal)
            if actor != user:
                pending = (
                    profile["class_choice_pending_at"]
                    if action == "class"
                    else profile["skills_pending_at"]
                )
                if (
                    personal
                    or not self._arena_owns_locked(chat, actor, user)
                    or pending is None
                    or utc_timestamp() < pending + SKILL_DELEGATION_SECONDS
                ):
                    raise ValueError(
                        "Владелец может выбрать за раба после 48 часов ожидания."
                    )
            if self._arena_busy_locked(chat, user):
                raise ValueError("Нельзя менять навыки во время боя.")
            classes, skills = self._fighter_catalog_locked()
            table = "personal_profiles" if personal else "slave_profiles"
            if action == "reset_class":
                if value is not True:
                    raise ValueError(
                        "Подтверди сброс класса, уровня, опыта и всех навыков."
                    )
                # Resetting a delegated fighter is an owner action just like
                # using a class tractate; never another user's personal fighter.
                self._arena_reset_profile_locked(chat, user, personal)
                self.connection.commit()
                return "Класс сброшен: Оборванец, уровень 1, опыт 0. Прежние навыки забыты."
            if action == "class":
                if profile["level"] < 5 or profile["class_id"] != "ragamuffin":
                    raise ValueError("Класс выбирается один раз, с 5 уровня.")
                allowed = set(
                    VISIBLE_CLASS_ALIASES.values()
                ) | self._granted_content_locked(chat, user, "class")
                chosen = next(
                    (
                        k
                        for k in allowed
                        if k in classes
                        and (
                            k == value
                            or classes[k].name.casefold() == str(value).casefold()
                        )
                    ),
                    None,
                )
                if not chosen or chosen == "ragamuffin":
                    raise ValueError("Класс недоступен.")
                loadout = normalize_loadout(
                    chosen,
                    profile["level"],
                    None,
                    skills,
                    self._arena_grants_locked(chat, user, personal),
                    self._arena_known_skills_locked(
                        chat, user, personal, dict(profile, class_id=chosen)
                    ),
                )
                self.connection.execute(
                    f"UPDATE {table} SET class_id=?,loadout=?,class_choice_pending_at=NULL,skills_pending_at=? WHERE chat_id=? AND user_id=?",
                    (chosen, json.dumps(loadout), utc_timestamp(), chat, user),
                )
                self._arena_equip_class_passives_locked(chat, user, personal, chosen)
            elif action == "loadout":
                if (
                    not isinstance(value, list)
                    or len(value) > 4
                    or any(not isinstance(k, str) for k in value)
                ):
                    raise ValueError("Выберите до четырёх навыков.")
                unlocked = unlocked_skill_ids(
                    profile["class_id"],
                    profile["level"],
                    skills,
                    self._arena_grants_locked(chat, user, personal),
                    self._arena_known_skills_locked(chat, user, personal),
                )
                if any(k not in unlocked for k in value):
                    raise ValueError("Навык ещё не открыт.")
                loadout = normalize_loadout(
                    profile["class_id"],
                    profile["level"],
                    value,
                    skills,
                    self._arena_grants_locked(chat, user, personal),
                    self._arena_known_skills_locked(chat, user, personal),
                )
                self.connection.execute(
                    f"UPDATE {table} SET loadout=?,skills_pending_at=NULL WHERE chat_id=? AND user_id=?",
                    (json.dumps(loadout), chat, user),
                )
            elif action == "passives":
                if (
                    not isinstance(value, list)
                    or len(value) > MAX_PASSIVE_SKILLS
                    or any(not isinstance(k, str) for k in value)
                    or len(value) != len(set(value))
                ):
                    raise ValueError("Выбери максимум две разные пассивки.")
                available = self._arena_passive_catalog_locked(
                    chat, user, personal, profile
                )
                if any(k not in available for k in value):
                    raise ValueError("Пассивный навык не изучен.")
                self.connection.execute(
                    f"UPDATE {table} SET passive_loadout=?,skills_pending_at=NULL WHERE chat_id=? AND user_id=?",
                    (json.dumps(value), chat, user),
                )
            elif action in {
                "forget_skill",
                "forget_passive",
                "learn_skill",
                "learn_passive",
            }:
                kind = "skill" if action.endswith("_skill") else "passive"
                if kind == "skill":
                    eligible = unlocked_skill_ids(
                        profile["class_id"],
                        profile["level"],
                        skills,
                        self._arena_grants_locked(chat, user, personal),
                    )
                    known = self._arena_known_skills_locked(chat, user, personal)
                else:
                    eligible = self._arena_passive_catalog_locked(
                        chat, user, personal, all_available=True
                    )
                    known = list(
                        self._arena_passive_catalog_locked(chat, user, personal)
                    )
                if not isinstance(value, str) or value not in eligible:
                    raise ValueError("Навык недоступен.")
                if action.startswith("forget_"):
                    if value == "bum_punch":
                        raise ValueError("Бесплатный обычный удар нельзя забыть.")
                    if value not in known:
                        raise ValueError("Навык не изучен.")
                    known.remove(value)
                    self.connection.execute(
                        f"UPDATE {table} SET {kind}_memory=? WHERE chat_id=? AND user_id=?",
                        (json.dumps(known), chat, user),
                    )
                else:
                    self._arena_remember_locked(chat, user, personal, kind, value)
                    if value not in known:
                        known.append(value)
                column = "loadout" if kind == "skill" else "passive_loadout"
                selected = [k for k in json.loads(profile[column]) if k in known]
                if kind == "skill":
                    selected = normalize_loadout(
                        profile["class_id"],
                        profile["level"],
                        selected,
                        skills,
                        self._arena_grants_locked(chat, user, personal),
                        known,
                    )
                self.connection.execute(
                    f"UPDATE {table} SET {column}=?,skills_pending_at=NULL WHERE chat_id=? AND user_id=?",
                    (json.dumps(selected), chat, user),
                )
            else:
                raise ValueError("Неизвестное действие.")
            self.connection.commit()
            return "Сохранено."
