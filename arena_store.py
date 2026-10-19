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
from arena_mirror import MirrorMixin
from arena_raid import RaidMixin
from arena_wasteland import enemy_source, victory_xp
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
    passive_skill_limit,
    fighter_xp_limit,
    effective_stat,
    effective_skill,
    validate_skill,
)
from arena_archclasses import ARCHCLASSES, ARCHCLASS_LEVEL, branch_options
from arena_progression import pending_choice
from arena_pet_store import PetMixin
from arena_global import GlobalArenaMixin, RPG_SCOPE
from arena_characters import CharacterMixin
from arena_qte_live import ArenaQteMixin

OWNER_RECORD_XP = 2
ARENA_PREPARATION_SECONDS = 3 * 60 * 60
ARENA_TURN_SECONDS = 2 * 60
ARENA_FEE_PERCENT = 10
COMBAT_SLAVE_CAPACITY = 5


def utc_timestamp() -> int:
    return int(time.time())


class ArenaMixin(ArenaMarketMixin, MirrorMixin, RaidMixin, PetMixin, GlobalArenaMixin, CharacterMixin, ArenaQteMixin):
    def _connect_arena(self) -> None:
        self._connect_qte()
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
            CREATE TABLE IF NOT EXISTS arena_account_chats (
                user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
                PRIMARY KEY(user_id,chat_id));
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

        for table in ("slave_profiles", "personal_profiles"):
            self._ensure_column(table, 'skill_offers', "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(table, "archclass_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(table, "archclass_pending_at", "INTEGER")
            self._ensure_column(
                table, "progression_level", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(table, "archclass_stage", "INTEGER NOT NULL DEFAULT 10")
            self._ensure_column(
                table, "progression_pending_level", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(table, "progression_pending_at", "INTEGER")
        self._connect_arena_market()
        self._connect_mirror()
        self._connect_raids()
        self._connect_pets()
        self._connect_global_arena()
        self._connect_characters()
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
        self, table: str, chat_id: int, user_id: int, amount: int, *, battle: bool = False
    ) -> tuple[int, int]:
        if table not in {"slave_profiles", "personal_profiles", "owner_profiles"}:
            raise ValueError("Unknown profile table")
        if table == 'personal_profiles':
            chat_id = RPG_SCOPE
        if table in {"slave_profiles", "personal_profiles"}:
            before = self._arena_profile_locked(
                chat_id, user_id, table == "personal_profiles"
            )
        else:
            before = self._ensure_owner_profile_locked(chat_id, user_id)
        old_level = int(before["level"])
        amount = max(0, int(amount))
        target = int(before["catchup_target_xp"]) if table != "owner_profiles" else 0
        gap = max(0, target - int(before["xp"]))
        if battle and gap:
            # Double only the catch-up portion. Overflow past the old level is
            # normal XP, and repeated resets never multiply the multiplier.
            amount = min(2 * amount, gap) + max(0, amount - (gap + 1) // 2)
        total_xp = int(before["xp"]) + amount
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
        if table != "owner_profiles" and target and total_xp >= target:
            self.connection.execute(
                f"UPDATE {table} SET catchup_target_xp=0 WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
        if table != "owner_profiles" and new_level > old_level:
            self.connection.execute(
                f"UPDATE {table} SET skills_pending_at=COALESCE(skills_pending_at, ?) WHERE chat_id=? AND user_id=?",
                (utc_timestamp(), chat_id, user_id),
            )
            if (
                new_level >= ARCHCLASS_LEVEL
                and branch_options(before["class_id"])
                and before["progression_level"] < 10
            ):
                self.connection.execute(
                    f"UPDATE {table} SET archclass_pending_at=COALESCE(archclass_pending_at,?) WHERE chat_id=? AND user_id=? AND archclass_id=''",
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
        if table != "owner_profiles":
            self._arena_profile_locked(chat_id, user_id, table == "personal_profiles")
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
            "SELECT class_id, definition_json FROM custom_fighter_classes WHERE hidden=0"
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
                if not json.loads(row['definition_json']).get('merchant_available', False):
                    continue
                if skill.class_id in classes:
                    skills[skill.skill_id] = skill
            except (TypeError, ValueError, json.JSONDecodeError, KeyError):
                continue
        return classes, skills

    def _granted_content_locked(
        self, chat_id: int, user_id: int, content_type: str
    ) -> set[str]:
        return set()  # Historical exclusive grants are no longer combat content.

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

    async def grant_custom_fighter_content(self, *args, **kwargs):
        raise ValueError('Эксклюзивные навыки и классы больше не выдаются.')

    async def get_fighter_catalog(self) -> tuple[dict[str, Any], dict[str, Any]]:
        async with self._lock:
            return self._fighter_catalog_locked()

    async def arena_admin_grant(self, *args, **kwargs):
        raise ValueError('Эксклюзивные навыки и классы удалены.')

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
            profile = self._arena_profile_locked(chat_id, user_id)
            if int(profile["level"]) < CLASS_SELECTION_LEVEL:
                return "low_level"
            if (
                profile["class_id"] != "ragamuffin"
                or pending_choice(dict(profile)) != 5
            ):
                return "already_chosen"
            if self._arena_choice_busy_locked(chat_id, user_id):
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
            if class_id is None or class_id == "ragamuffin" or not self._arena_class_enabled_locked(chat_id,class_id):
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
                       skills_pending_at=?, updated_at=?,archclass_id='',archclass_stage=10,progression_level=5,progression_pending_level=0,progression_pending_at=NULL,archclass_pending_at=NULL
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
                profile["archclass_id"],
                profile['progression_level'],
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
        if personal:
            if chat_id != RPG_SCOPE:
                self.connection.execute('INSERT OR IGNORE INTO arena_account_chats VALUES(?,?)',(user_id,chat_id))
            chat_id = RPG_SCOPE
        if not personal:
            self._ensure_slave_profile_locked(chat_id, user_id)
        else:
            self.connection.execute(
                """INSERT OR IGNORE INTO personal_profiles(chat_id,user_id,level,xp,class_id,loadout,updated_at)
                   VALUES(?,?,1,0,'ragamuffin','["bum_punch"]',?)""",
                (chat_id, user_id, utc_timestamp()),
            )
        table = "personal_profiles" if personal else "slave_profiles"
        row = self.connection.execute(
            f"SELECT * FROM {table} WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()
        stage = pending_choice(dict(row))
        if stage != row["progression_pending_level"]:
            stamp = utc_timestamp() if stage else None
            # Preserve an already running delegation clock on migration.
            if stage in {5, 10}:
                previous_stamp = row[
                    "class_choice_pending_at" if stage == 5 else "archclass_pending_at"
                ]
                if previous_stamp is not None:
                    stamp = previous_stamp
            self.connection.execute(
                f"UPDATE {table} SET progression_pending_level=?,progression_pending_at=? WHERE chat_id=? AND user_id=?",
                (stage, stamp, chat_id, user_id),
            )
            row = self.connection.execute(
                f"SELECT * FROM {table} WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        if (
            stage == 10
            and not row["archclass_id"]
            and row["archclass_pending_at"] is None
            and branch_options(row["class_id"])
        ):
            self.connection.execute(
                f"UPDATE {table} SET archclass_pending_at=? WHERE chat_id=? AND user_id=?",
                (utc_timestamp(), chat_id, user_id),
            )
            row = self.connection.execute(
                f"SELECT * FROM {table} WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return row

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

    def _arena_busy_locked(
        self, chat: int, user: int, exclude=0, raid_exclude=""
    ) -> bool:
        return bool(
            self.connection.execute(
                """SELECT 1 FROM arena_battles WHERE status IN ('pending','active')
               AND id<>? AND (a_owner=? OR b_owner=? OR a_fighter=? OR b_fighter=?)""",
                (exclude, user, user, user, user),
            ).fetchone()
            or self._raid_busy_locked(chat, user, raid_exclude)
            or self.connection.execute(
                "SELECT 1 FROM arena_mirror_runs WHERE status='active' AND (actor_id=? OR fighter_id=?)",
                (user, user),
            ).fetchone()
        )

    def _arena_choice_busy_locked(self, chat, user):
        return bool(
            self.connection.execute(
                "SELECT 1 FROM arena_battles WHERE status='active' AND (a_owner=? OR b_owner=? OR a_fighter=? OR b_fighter=?)",
                (user, user, user, user),
            ).fetchone()
            or self._raid_busy_locked(chat, user, active_only=True)
            or self.connection.execute(
                "SELECT 1 FROM arena_mirror_runs WHERE status='active' AND (actor_id=? OR fighter_id=?)",
                (user, user),
            ).fetchone()
        )

    def _arena_require_choice_locked(self, chat, user, personal):
        profile = self._arena_profile_locked(chat, user, personal)
        if not self._arena_class_enabled_locked(chat, profile['class_id']):
            raise ValueError("Этот класс больше недоступен. Используй сброс класса в арене.")
        stage = pending_choice(dict(profile))
        if stage:
            raise ValueError(
                f"Боец {user}: сначала сделайте выбор класса / подкласса {stage} уровня в арене → «Класс и навыки». Можно оставить текущий класс."
            )

    def _arena_combat_slot_locked(self, chat, owner, slave):
        return None

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

    async def arena_equip_slave(self, chat, actor, slave, equipped):
        raise ValueError('Боевые рабы удалены. Используй личного персонажа.')

    async def arena_combat_slaves(self, chat: int, owner: int) -> list[dict]:
        data = await self.arena_menu(chat, owner)
        return [s for s in data["slaves"] if s["combat_slot"] and not s["working_role"]]

    def _arena_refund_locked(self, row: dict, status: str) -> None:
        state = json.loads(row["state_json"]) if row["state_json"] else {}
        if state.get("mirror_token"):
            run = self._mirror_row_locked(state["mirror_token"])
            if run["status"] == "active":
                self._mirror_close_locked(
                    run, "Бой отменён. Забег закрыт без награды за босса."
                )
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
            pet=self._pet_source_locked(chat, owner if controlled else user),
            class_id=profile["class_id"],
            archclass_id=profile["archclass_id"],
            archclass_stage=profile["archclass_stage"],
            progression_level=profile["progression_level"],
            level=profile["level"],
            loadout=[k for k in json.loads(profile["loadout"]) if self._arena_content_enabled_locked(chat,'skill',k)],
            granted_skills=[k for k in self._arena_grants_locked(chat, user, personal) if self._arena_content_enabled_locked(chat,'skill',k)],
            known_skills=[k for k in self._arena_known_skills_locked(chat, user, personal) if self._arena_content_enabled_locked(chat,'skill',k)],
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
        for key in ("a", "b"):
            self._arena_require_choice_locked(
                row["chat_id"], row[key + "_fighter"], row["mode"] == "personal"
            )
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
        state['qte_modes']={str(s['controller_id']):self._qte_enabled_locked(s['controller_id']) for s in state['sides'].values()}
        if row.get("ranked"):
            state.update(ranked=True, ranked_actions={"a": 0, "b": 0}, ranked_timeouts={"a": 0, "b": 0})
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
        self, chat: int, actor: int, target: int, mode="personal", stake=0, *, ranked=False
    ) -> dict:
        if (
            mode != "personal"
            or actor == target
            or stake < 0
            or stake > 1000000
            or type(ranked) is not bool
            or (ranked and stake != 0)
        ):
            raise ValueError("Некорректный вызов.")
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            if ranked:
                reason = self._rating_block_locked(actor, target, utc_timestamp())
                if reason:
                    raise ValueError(reason)
            a_slot=self._character_require_locked(actor)
            b_slot=self._character_require_locked(target)
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
            if mode == "personal":
                for user in (actor, target):
                    self._arena_require_choice_locked(chat, user, True)
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
            self.connection.execute("UPDATE arena_battles SET a_character_slot=?,b_character_slot=? WHERE token=?",(a_slot,b_slot,token))
            if ranked:
                self.connection.execute("UPDATE arena_battles SET ranked=1 WHERE token=?", (token,))
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
            if row["status"] == "active" and json.loads(row["state_json"] or "{}").get(
                "mirror_token"
            ):
                self._mirror_cleanup_locked(row["chat_id"])
                self.connection.commit()
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
            self._require_feature_locked(row['chat_id'], 'arena')
            if row['mode'] != 'personal':
                raise ValueError('Боевые рабы удалены.')
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
                if row.get("ranked"):
                    reason = self._rating_block_locked(row["a_owner"], row["b_owner"], utc_timestamp())
                    if reason:
                        raise ValueError(reason)
                if row["mode"] == "personal":
                    for user in (row["a_fighter"], row["b_fighter"]):
                        self._arena_require_choice_locked(row["chat_id"], user, True)
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
                self._arena_require_choice_locked(row["chat_id"], fighter, False)
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
        if state.get("mirror_token"):
            self._mirror_finish_battle_locked(row, state)
            return
        winner = state["winner"]
        self._rating_finish_locked(row, state, utc_timestamp())
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
                (RPG_SCOPE, first, second, day),
            ).fetchone()
            low_reward = bool(previous and previous["count"] >= 3)
            self.connection.execute(
                "INSERT INTO arena_pair_rewards VALUES(?,?,?,?,1) ON CONFLICT(chat_id,first_id,second_id,day) DO UPDATE SET count=count+1",
                (RPG_SCOPE, first, second, day),
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
            if row.get("ranked") and not all(state.get("ranked_actions", {}).get(side, 0) > 0 for side in ("a", "b")):
                xp = 0  # Early ranked concessions/timeouts are not an XP farm.
            if row["mode"] == "wasteland":
                xp = (
                    0
                    if state.get("finish_reason") in {"surrender", "timeout"}
                    else (
                        victory_xp(state["sides"]["b"]["level"]) if winner == k else 3
                    )
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
                table, row["chat_id"], row[k + "_fighter"], xp, battle=True
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
        if (row["mode"] == "wasteland" and winner == "a"
                and state.get("finish_reason") not in {"surrender", "timeout", "turn_limit"}
                and any(e.get("side") == "a" and e.get("skill_id") for e in state["log"])):
            state["pet_rewards"] = self._pet_reward_locked(
                row["a_owner"] if row["a_control"] else row["a_fighter"],
                "wasteland", "waste:" + row["token"])
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
            return self._arena_action_locked(token,actor,revision,skill_id)

    def _arena_action_locked(self,token,actor,revision,skill_id,*,_qte=None,_interactive=False):
        with self.connection:
            row = self._arena_row_locked(token)
            if row["status"] == "active" and json.loads(row["state_json"] or "{}").get(
                "mirror_token"
            ):
                self._mirror_cleanup_locked(row["chat_id"])
                self.connection.commit()
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
                        (RPG_SCOPE, actor),
                    ).fetchone()
                    if not item:
                        raise ValueError("Нет зелья.")
                    self._arena_consume_item_locked(item)
                    use_healing_potion(state, key)
                else:
                    resolve_skill(state, key, skill_id, skills,qte=_qte)
                    if row.get("ranked"):
                        state.setdefault("ranked_actions", {"a": 0, "b": 0})[key] += 1
                        state.setdefault("ranked_timeouts", {"a": 0, "b": 0})[key] = 0
                while (
                    not _interactive and row["mode"] == "wasteland"
                    and not state["finished"]
                    and state["active_side"] == "b"
                ):
                    ai = state["sides"]["b"]
                    choices = []
                    for candidate in ai["loadout"]:
                        try:
                            validate_skill(state, "b", candidate, skills)
                        except ValueError:
                            continue
                        choices.append(candidate)
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
        # Expiry can finish a ranked duel, award XP and refund escrow. Keep
        # these changes atomic even when triggered by a read/another offer.
        if not self.connection.in_transaction:
            self.connection.execute("BEGIN")
        self.connection.execute("SAVEPOINT arena_expiry")
        try:
            result = self._arena_expire_rows_locked()
        except Exception:
            self.connection.execute("ROLLBACK TO arena_expiry")
            self.connection.execute("RELEASE arena_expiry")
            raise
        self.connection.execute("RELEASE arena_expiry")
        return result

    def _arena_expire_rows_locked(self) -> list[dict]:
        self._qte_expire_locked('battle')
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
                expired_side = state["active_side"]
                skip_turn(state)
                if row.get("ranked") and not state["finished"]:
                    misses = state.setdefault("ranked_timeouts", {"a": 0, "b": 0})
                    misses[expired_side] += 1
                    if misses[expired_side] >= 3:
                        state.update(finished=True, winner="b" if expired_side == "a" else "a", finish_reason="ranked_inactivity")
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
        self, chat: int, actor: int, fighter=0, previous="", personal: bool = True, *, expected_slot=None
    ) -> dict:
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            slot=self._character_require_locked(actor,expected_slot)
            if not personal or (fighter and fighter != actor):
                raise ValueError('Боевые рабы удалены. Используй своего личного персонажа.')
            floor = 1
            previous_class = None
            if previous:
                old = self._arena_row_locked(previous)
                if json.loads(old["state_json"] or "{}").get("mirror_token"):
                    raise ValueError("Продолжайте зеркальный забег через его меню.")
                if (
                    old["mode"] != "wasteland"
                    or old["a_character_slot"] != slot
                    or old["a_owner"] != actor
                    or old["chat_id"] != chat
                    or old["status"] != "finished"
                    or json.loads(old["state_json"])["winner"] != "a"
                ):
                    raise ValueError("Сначала победите на текущем этаже.")
                floor = old["floor"] + 1
                previous_class = json.loads(old["state_json"])["sides"]["b"]["class_id"]
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
            self._arena_require_choice_locked(chat, fighter, personal)
            source = self._arena_source_locked(chat, fighter, actor, False, personal)
            source["controlled"] = False
            enemy = enemy_source(source["level"] + floor - 1, previous_class, enabled_classes={k for k in FIGHTER_CLASSES if self._arena_class_enabled_locked(chat,k)})
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
            state['qte_modes']={str(s['controller_id']):self._qte_enabled_locked(s['controller_id']) for s in state['sides'].values()}
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
            self.connection.execute("UPDATE arena_battles SET a_character_slot=? WHERE token=?",(slot,token))
            self.connection.commit()
            return self._arena_row_locked(token)

    async def arena_set_sprite(
        self, chat: int, actor: int, png: bytes, pixel_art: bool, *, expected_slot=None
    ) -> str:
        # HTTP boundary has already decoded/validated PNG. No user/target supplied by caller.
        key = hashlib.sha256(png).hexdigest()
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            self._character_require_locked(actor,expected_slot)
            self.connection.execute(
                """INSERT INTO arena_sprites(chat_id,user_id,sprite_key,png,pixel_art)
                   VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
                   sprite_key=excluded.sprite_key,png=excluded.png,pixel_art=excluded.pixel_art""",
                (RPG_SCOPE, actor, key, png, int(pixel_art)),
            )
            self._character_save_locked(actor)
            self.connection.commit()
        return key

    async def arena_reset_sprite(self, chat: int, actor: int, *, expected_slot=None) -> None:
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            self._character_require_locked(actor,expected_slot)
            self.connection.execute(
                "DELETE FROM arena_sprites WHERE chat_id=? AND user_id=?", (RPG_SCOPE, actor)
            )
            self._character_save_locked(actor)
            self.connection.commit()

    async def arena_sprite_info(self, chat: int, user: int) -> dict:
        async with self._lock:
            row = self.connection.execute(
                "SELECT sprite_key,pixel_art FROM arena_sprites WHERE chat_id=? AND user_id=?",
                (RPG_SCOPE, user),
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
                "SELECT png FROM arena_sprites WHERE chat_id=0 AND sprite_key=? UNION ALL SELECT png FROM arena_character_slots WHERE sprite_key=? LIMIT 1", (key,key)
            ).fetchone()
            return bytes(row["png"]) if row else None

    async def arena_menu(self, chat, actor):
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            personal = dict(self._arena_profile_locked(chat, actor, True))
            personal['loadout'] = json.loads(personal['loadout'])
            personal['name'] = 'Мой персонаж'
            active = [dict(r) for r in self.connection.execute(
                "SELECT token,mode,status,chat_id FROM arena_battles WHERE status IN ('pending','active') AND (a_owner=? OR b_owner=?)",
                (actor,actor))]
            self.connection.commit()
            return dict(personal=personal,slaves=[],self_slave=None,owner={},active=active,
                        combat_capacity=0,combat_count=0,global_progression=True)

    async def arena_edit_profile(
        self, chat: int, actor: int, user: int, personal: bool, action: str, value, *, expected_slot=None
    ) -> str:
        async with self._lock:
            self._require_feature_locked(chat, 'arena')
            self._character_require_locked(actor,expected_slot)
            if not personal or actor != user:
                raise ValueError('Можно менять только своего личного персонажа.')
            profile = self._arena_profile_locked(chat, user, personal)
            if action in {"module_class","restore_class"}:
                raise ValueError("Модули классов удалены.")
            choice_action = action in {"progression", "class", "archclass"}
            if (
                self._arena_choice_busy_locked(chat, user)
                if choice_action
                else self._arena_busy_locked(chat, user)
            ):
                raise ValueError("Нельзя менять навыки во время боя.")
            classes, skills = self._fighter_catalog_locked()
            chat = RPG_SCOPE
            table = "personal_profiles"
            progression_stage = None
            if action == "reset_class":
                if value is not True:
                    raise ValueError(
                        "Подтверди сброс класса, уровня, опыта и всех навыков."
                    )
                self._arena_reset_profile_locked(chat, user, personal)
                self.connection.commit()
                return "Класс сброшен: Оборванец, уровень 5. Прежние навыки забыты. Боевой опыт ×2 до возвращения прежнего уровня."
            if action == "progression":
                stage = pending_choice(dict(profile))
                progression_stage = stage
                if not stage or not isinstance(value, str):
                    raise ValueError("Этот выбор уже сделан или ещё не открыт.")
                if value == "stay":
                    pass
                elif stage == 5 or profile['class_id']=='ragamuffin':
                    # Reuse the existing class validation and initialization.
                    action = "class"
                    progression_stage = 5
                elif stage == 20 and profile["archclass_id"]:
                    if value != "advance":
                        raise ValueError(
                            "Можно развить выбранную ветку или оставить её текущую ступень."
                        )
                    self.connection.execute(
                        f"UPDATE {table} SET archclass_stage=20 WHERE chat_id=? AND user_id=?",
                        (chat, user),
                    )
                else:
                    entry = ARCHCLASSES.get(value)
                    if not entry or entry["class_id"] != profile["class_id"]:
                        raise ValueError("Подкласс недоступен этому классу.")
                    self.connection.execute(
                        f"UPDATE {table} SET archclass_id=?,archclass_stage=? WHERE chat_id=? AND user_id=?",
                        (value, stage, chat, user),
                    )
            if action == "archclass":
                if profile["level"] < ARCHCLASS_LEVEL:
                    raise ValueError("Архикласс открывается с 10 уровня.")
                if profile["archclass_id"]:
                    raise ValueError(
                        "Архикласс уже выбран. Изменить ветку можно после сброса или смены класса."
                    )
                if pending_choice(dict(profile)) != 10:
                    raise ValueError(
                        "Выбор уже сохранён. Новый выбор доступен на следующей ступени развития."
                    )
                entry = ARCHCLASSES.get(value) if isinstance(value, str) else None
                if not entry or entry["class_id"] != profile["class_id"]:
                    raise ValueError("Архикласс недоступен этому классу.")
                self.connection.execute(
                    f"UPDATE {table} SET archclass_id=?,archclass_stage=10,progression_level=MAX(progression_level,10),archclass_pending_at=NULL,updated_at=? WHERE chat_id=? AND user_id=?",
                    (value, utc_timestamp(), chat, user),
                )
            elif action == "class":
                if (
                    profile["level"] < 5
                    or profile["class_id"] != "ragamuffin"
                    or (pending_choice(dict(profile)) != 5 and progression_stage != 5)
                ):
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
                            or VISIBLE_CLASS_ALIASES.get(str(value).casefold()) == k
                        )
                    ),
                    None,
                )
                if not chosen or chosen == "ragamuffin" or not self._arena_class_enabled_locked(chat, chosen):
                    raise ValueError("Класс недоступен.")
                loadout = normalize_loadout(
                    chosen,
                    profile["level"],
                    None,
                    skills,
                    self._arena_grants_locked(chat, user, personal),
                    self._arena_known_skills_locked(
                        chat, user, personal, dict(profile, class_id=chosen, progression_level=5, archclass_id='')
                    ),
                )
                self.connection.execute(
                    f"UPDATE {table} SET class_id=?,loadout=?,archclass_id='',archclass_stage=10,progression_level=5,progression_pending_level=0,progression_pending_at=NULL,archclass_pending_at=NULL,class_choice_pending_at=NULL,skills_pending_at=? WHERE chat_id=? AND user_id=?",
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
                    profile["archclass_id"],
                    profile['progression_level'],
                )
                if any(k not in unlocked or not self._arena_content_enabled_locked(chat,'skill',k,skills) for k in value):
                    raise ValueError("Навык ещё не открыт.")
                loadout = normalize_loadout(
                    profile["class_id"],
                    profile["level"],
                    value,
                    skills,
                    self._arena_grants_locked(chat, user, personal),
                    self._arena_known_skills_locked(chat, user, personal),
                    profile["archclass_id"],
                    profile['progression_level'],
                )
                self.connection.execute(
                    f"UPDATE {table} SET loadout=?,skills_pending_at=NULL WHERE chat_id=? AND user_id=?",
                    (json.dumps(loadout), chat, user),
                )
            elif action == 'skill_offer':
                with self.connection:
                    self._arena_resolve_skill_offer_locked(chat,user,personal,value)
            elif action == "passives":
                if (
                    not isinstance(value, list)
                    or len(value) > passive_skill_limit(profile["level"])
                    or any(not isinstance(k, str) for k in value)
                    or len(value) != len(set(value))
                ):
                    raise ValueError(
                        f"Выбери максимум {passive_skill_limit(profile['level'])} разные пассивки."
                    )
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
                        archclass_id=profile["archclass_id"],
                        progression_level=profile['progression_level'],
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
                    if kind=='skill' and not self._arena_content_enabled_locked(chat,kind,value,skills):
                        raise ValueError("Модуль навыка выключен. Изученный навык сохранён.")
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
                        profile["archclass_id"],
                        profile['progression_level'],
                    )
                self.connection.execute(
                    f"UPDATE {table} SET {column}=? WHERE chat_id=? AND user_id=?",
                    (json.dumps(selected), chat, user),
                )
            elif action != "progression":
                raise ValueError("Неизвестное действие.")
            if progression_stage:
                self.connection.execute(
                    f"UPDATE {table} SET progression_level=?,progression_pending_level=0,progression_pending_at=NULL,class_choice_pending_at=NULL,archclass_pending_at=NULL,updated_at=? WHERE chat_id=? AND user_id=?",
                    (progression_stage, utc_timestamp(), chat, user),
                )
            self._arena_profile_locked(chat, user, personal)
            self.connection.commit()
            return "Сохранено."
