from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_timestamp() -> int:
    return int(datetime.now(timezone.utc).timestamp())


class Database:
    """Small async-friendly SQLite repository for one aiogram process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                display_name TEXT NOT NULL,
                last_seen INTEGER NOT NULL,
                vulnerable_until INTEGER,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_users_username
                ON users(chat_id, username COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_users_recent
                ON users(chat_id, last_seen DESC);

            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL CHECK(action_type IN ('ban', 'mute', 'warn')),
                reason TEXT NOT NULL,
                duration_seconds INTEGER,
                moderator_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                active_until INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_actions_user
                ON actions(chat_id, user_id, action_type);

            CREATE TABLE IF NOT EXISTS ownership (
                chat_id INTEGER NOT NULL,
                slave_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                acquired_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, slave_id),
                CHECK (slave_id != owner_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ownership_owner
                ON ownership(chat_id, owner_id);

            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                challenger_id INTEGER NOT NULL,
                opponent_id INTEGER NOT NULL,
                challenger_choice TEXT,
                opponent_choice TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_pair
                ON challenges(chat_id, challenger_id, opponent_id)
                WHERE status = 'active';

            CREATE TABLE IF NOT EXISTS leg_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                requester_id INTEGER NOT NULL,
                deadline INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leg_requests_pending
                ON leg_requests(status, deadline);
            """
        )
        self._ensure_column("ownership", "last_forced_at", "INTEGER")
        self._ensure_column(
            "challenges", "forced", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("challenges", "deadline", "INTEGER")
        self._connection.execute(
            """UPDATE challenges SET deadline=created_at + 86400
               WHERE deadline IS NULL"""
        )
        # Apply the invariant introduced later: an enslaved user cannot own slaves.
        self._connection.execute(
            """DELETE FROM ownership
               WHERE EXISTS (
                   SELECT 1 FROM ownership parent
                   WHERE parent.chat_id=ownership.chat_id
                     AND parent.slave_id=ownership.owner_id
               )"""
        )
        self._connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    async def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected")
        return self._connection

    async def upsert_user(
        self,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str,
        *,
        vulnerable_until: int | None = None,
        touch: bool = True,
    ) -> None:
        now = utc_timestamp()
        async with self._lock:
            self.connection.execute(
                """
                INSERT INTO users(chat_id, user_id, username, display_name, last_seen, vulnerable_until)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    username=excluded.username,
                    display_name=excluded.display_name,
                    last_seen=CASE WHEN ? THEN excluded.last_seen ELSE users.last_seen END,
                    vulnerable_until=COALESCE(excluded.vulnerable_until, users.vulnerable_until)
                """,
                (chat_id, user_id, username, display_name, now, vulnerable_until, int(touch)),
            )
            self.connection.commit()

    async def upsert_chat(self, chat_id: int, title: str) -> None:
        async with self._lock:
            self.connection.execute(
                """INSERT INTO chats(chat_id, title, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       title=excluded.title, updated_at=excluded.updated_at""",
                (chat_id, title, utc_timestamp()),
            )
            self.connection.commit()

    async def resolve_user(self, chat_id: int, token: str) -> sqlite3.Row | None:
        token = token.strip()
        async with self._lock:
            if token.lstrip("-").isdigit():
                return self.connection.execute(
                    "SELECT * FROM users WHERE chat_id=? AND user_id=?",
                    (chat_id, int(token)),
                ).fetchone()
            username = token.removeprefix("@").casefold()
            return self.connection.execute(
                "SELECT * FROM users WHERE chat_id=? AND username=? COLLATE NOCASE",
                (chat_id, username),
            ).fetchone()

    async def resolve_users_globally(self, token: str) -> list[sqlite3.Row]:
        token = token.strip()
        async with self._lock:
            if token.lstrip("-").isdigit():
                return self.connection.execute(
                    """SELECT u.*, c.title AS chat_title FROM users u
                       LEFT JOIN chats c ON c.chat_id=u.chat_id
                       WHERE u.user_id=? ORDER BY u.chat_id""",
                    (int(token),),
                ).fetchall()
            username = token.removeprefix("@").casefold()
            return self.connection.execute(
                """SELECT u.*, c.title AS chat_title FROM users u
                   LEFT JOIN chats c ON c.chat_id=u.chat_id
                   WHERE u.username=? COLLATE NOCASE ORDER BY u.chat_id""",
                (username,),
            ).fetchall()

    async def get_user(self, chat_id: int, user_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM users WHERE chat_id=? AND user_id=?", (chat_id, user_id)
            ).fetchone()

    async def recent_users(self, chat_id: int, limit: int = 20) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM users
                   WHERE chat_id=?
                   ORDER BY last_seen DESC LIMIT ?""",
                (chat_id, limit),
            ).fetchall()

    async def record_action(
        self,
        chat_id: int,
        user_id: int,
        action_type: str,
        reason: str,
        moderator_id: int,
        *,
        duration_seconds: int | None = None,
        active_until: int | None = None,
    ) -> int:
        async with self._lock:
            cursor = self.connection.execute(
                """INSERT INTO actions(
                       chat_id, user_id, action_type, reason, duration_seconds,
                       moderator_id, created_at, active_until
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chat_id,
                    user_id,
                    action_type,
                    reason,
                    duration_seconds,
                    moderator_id,
                    utc_timestamp(),
                    active_until,
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    async def action_stats(self, chat_id: int, user_id: int) -> dict[str, Any]:
        now = utc_timestamp()
        async with self._lock:
            counts = self.connection.execute(
                """SELECT action_type, COUNT(*) AS amount
                   FROM actions WHERE chat_id=? AND user_id=?
                   GROUP BY action_type""",
                (chat_id, user_id),
            ).fetchall()
            active_mute = self.connection.execute(
                """SELECT active_until FROM actions
                   WHERE chat_id=? AND user_id=? AND action_type='mute'
                     AND active_until > ?
                   ORDER BY active_until DESC LIMIT 1""",
                (chat_id, user_id, now),
            ).fetchone()
            last_ban = self.connection.execute(
                """SELECT created_at FROM actions
                   WHERE chat_id=? AND user_id=? AND action_type='ban'
                   ORDER BY created_at DESC LIMIT 1""",
                (chat_id, user_id),
            ).fetchone()
        result: dict[str, Any] = {"ban": 0, "mute": 0, "warn": 0}
        result.update({row["action_type"]: row["amount"] for row in counts})
        result["active_mute_until"] = active_mute["active_until"] if active_mute else None
        result["has_ban"] = last_ban is not None
        return result

    async def action_history(self, chat_id: int, user_id: int, limit: int = 5) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT action_type, reason, created_at FROM actions
                   WHERE chat_id=? AND user_id=?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (chat_id, user_id, limit),
            ).fetchall()

    async def deactivate_mutes(self, chat_id: int, user_id: int) -> None:
        now = utc_timestamp()
        async with self._lock:
            self.connection.execute(
                """UPDATE actions SET active_until=?
                   WHERE chat_id=? AND user_id=? AND action_type='mute'
                     AND active_until > ?""",
                (now, chat_id, user_id, now),
            )
            self.connection.commit()

    async def clear_actions(self, chat_id: int, user_id: int) -> int:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM actions WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            self.connection.commit()
            return cursor.rowcount

    async def create_challenge(
        self,
        chat_id: int,
        challenger_id: int,
        opponent_id: int,
        *,
        forced: bool = False,
    ) -> int | None:
        async with self._lock:
            existing = self.connection.execute(
                """SELECT id FROM challenges WHERE chat_id=? AND status='active'
                   AND ((challenger_id=? AND opponent_id=?)
                     OR (challenger_id=? AND opponent_id=?))""",
                (chat_id, challenger_id, opponent_id, opponent_id, challenger_id),
            ).fetchone()
            if existing:
                return None
            now = utc_timestamp()
            cursor = self.connection.execute(
                """INSERT INTO challenges(
                       chat_id, challenger_id, opponent_id, forced, created_at, deadline
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (chat_id, challenger_id, opponent_id, int(forced), now, now + 86400),
            )
            if forced:
                self.connection.execute(
                    """UPDATE ownership SET last_forced_at=?
                       WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                    (now, chat_id, challenger_id, opponent_id),
                )
            self.connection.commit()
            return int(cursor.lastrowid)

    async def set_challenge_message(self, challenge_id: int, message_id: int) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE challenges SET message_id=? WHERE id=?", (message_id, challenge_id)
            )
            self.connection.commit()

    async def get_challenge(self, challenge_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()

    async def pending_challenges(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM challenges
                   WHERE status IN ('active', 'deadline') ORDER BY deadline"""
            ).fetchall()

    async def claim_expired_challenge(self, challenge_id: int) -> sqlite3.Row | None:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM challenges
                   WHERE id=? AND status='active' AND deadline <= ?""",
                (challenge_id, now),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE challenges SET status='deadline' WHERE id=?",
                (challenge_id,),
            )
            self.connection.commit()
            return row

    async def choose(self, challenge_id: int, user_id: int, choice: str) -> sqlite3.Row | None:
        async with self._lock:
            challenge = self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()
            if challenge is None or challenge["status"] != "active":
                return challenge
            if user_id == challenge["challenger_id"]:
                column = "challenger_choice"
            elif user_id == challenge["opponent_id"]:
                column = "opponent_choice"
            else:
                return None
            self.connection.execute(
                f"UPDATE challenges SET {column}=? WHERE id=? AND {column} IS NULL",
                (choice, challenge_id),
            )
            self.connection.commit()
            return self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()

    async def finish_challenge(self, challenge_id: int, status: str = "finished") -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                "UPDATE challenges SET status=? WHERE id=? AND status='active'",
                (status, challenge_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def transfer_after_loss(self, chat_id: int, loser_id: int, winner_id: int) -> tuple[str, int]:
        """Apply slavery consequences while preserving the no-slave-owners rule."""
        async with self._lock:
            winner_owner = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, winner_id),
            ).fetchone()
            if winner_owner:
                if int(winner_owner["owner_id"]) == loser_id:
                    self.connection.execute(
                        "DELETE FROM ownership WHERE chat_id=? AND slave_id=?",
                        (chat_id, winner_id),
                    )
                    self.connection.commit()
                    return "freed", winner_id
                self.connection.commit()
                return "no_reward", loser_id
            loser_owner = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, loser_id),
            ).fetchone()
            if loser_owner and int(loser_owner["owner_id"]) == winner_id:
                self.connection.commit()
                return "kept", loser_id
            owned = self.connection.execute(
                """SELECT slave_id FROM ownership
                   WHERE chat_id=? AND owner_id=? AND slave_id != ?
                   ORDER BY RANDOM() LIMIT 1""",
                (chat_id, loser_id, winner_id),
            ).fetchone()
            if owned:
                slave_id = int(owned["slave_id"])
                self.connection.execute(
                    """UPDATE ownership SET owner_id=?, acquired_at=?, last_forced_at=NULL
                       WHERE chat_id=? AND slave_id=?""",
                    (winner_id, utc_timestamp(), chat_id, slave_id),
                )
                outcome = "transferred"
            else:
                slave_id = loser_id
                self.connection.execute(
                    """INSERT INTO ownership(
                           chat_id, slave_id, owner_id, acquired_at, last_forced_at
                       ) VALUES (?, ?, ?, ?, NULL)
                       ON CONFLICT(chat_id, slave_id) DO UPDATE SET
                           owner_id=excluded.owner_id,
                           acquired_at=excluded.acquired_at,
                           last_forced_at=NULL""",
                    (chat_id, slave_id, winner_id, utc_timestamp()),
                )
                outcome = "enslaved"
            self.connection.commit()
            return outcome, slave_id

    async def get_owner(self, chat_id: int, slave_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                """SELECT o.*, u.username, u.display_name
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.owner_id
                   WHERE o.chat_id=? AND o.slave_id=?""",
                (chat_id, slave_id),
            ).fetchone()

    async def can_force_owner(self, chat_id: int, slave_id: int, owner_id: int) -> bool:
        month = 30 * 86400
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT acquired_at, last_forced_at FROM ownership
                   WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                (chat_id, slave_id, owner_id),
            ).fetchone()
            if not row or now < int(row["acquired_at"]) + month:
                return False
            return row["last_forced_at"] is None or now >= int(row["last_forced_at"]) + month

    async def transfer_slave(
        self, chat_id: int, current_owner_id: int, slave_id: int, new_owner_id: int
    ) -> str:
        async with self._lock:
            if slave_id == new_owner_id:
                return "self"
            if current_owner_id == new_owner_id:
                return "same_owner"
            owned = self.connection.execute(
                """SELECT 1 FROM ownership
                   WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                (chat_id, slave_id, current_owner_id),
            ).fetchone()
            if not owned:
                return "not_owned"
            recipient_is_slave = self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, new_owner_id),
            ).fetchone()
            if recipient_is_slave:
                return "recipient_is_slave"
            self.connection.execute(
                """UPDATE ownership
                   SET owner_id=?, acquired_at=?, last_forced_at=NULL
                   WHERE chat_id=? AND slave_id=?""",
                (new_owner_id, utc_timestamp(), chat_id, slave_id),
            )
            self.connection.commit()
            return "transferred"

    async def force_enslave(self, chat_id: int, slave_id: int, owner_id: int) -> str:
        async with self._lock:
            if slave_id == owner_id:
                return "self"
            owner_is_slave = self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, owner_id),
            ).fetchone()
            if owner_is_slave:
                return "owner_is_slave"
            self.connection.execute(
                "DELETE FROM ownership WHERE chat_id=? AND owner_id=?",
                (chat_id, slave_id),
            )
            self.connection.execute(
                """INSERT INTO ownership(
                       chat_id, slave_id, owner_id, acquired_at, last_forced_at
                   ) VALUES (?, ?, ?, ?, NULL)
                   ON CONFLICT(chat_id, slave_id) DO UPDATE SET
                       owner_id=excluded.owner_id,
                       acquired_at=excluded.acquired_at,
                       last_forced_at=NULL""",
                (chat_id, slave_id, owner_id, utc_timestamp()),
            )
            self.connection.commit()
            return "enslaved"

    async def release_all_slaves(self, chat_id: int, owner_id: int) -> int:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM ownership WHERE chat_id=? AND owner_id=?",
                (chat_id, owner_id),
            )
            self.connection.commit()
            return cursor.rowcount

    async def list_slaves(self, chat_id: int, owner_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT u.* FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   WHERE o.chat_id=? AND o.owner_id=? ORDER BY o.acquired_at DESC""",
                (chat_id, owner_id),
            ).fetchall()

    async def list_slaves_globally(self, owner_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT u.*, o.chat_id AS ownership_chat_id, c.title AS chat_title
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   LEFT JOIN chats c ON c.chat_id=o.chat_id
                   WHERE o.owner_id=? ORDER BY o.chat_id, o.acquired_at DESC""",
                (owner_id,),
            ).fetchall()

    async def release_slave(self, chat_id: int, owner_id: int, slave_id: int) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?",
                (chat_id, owner_id, slave_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def top_owners(self, chat_id: int, limit: int = 10) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT o.owner_id, COUNT(*) AS amount, u.display_name, u.username
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.owner_id
                   WHERE o.chat_id=?
                   GROUP BY o.owner_id
                   ORDER BY amount DESC, o.owner_id ASC LIMIT ?""",
                (chat_id, limit),
            ).fetchall()

    async def is_vulnerable(self, chat_id: int, user_id: int) -> bool:
        row = await self.get_user(chat_id, user_id)
        return bool(row and row["vulnerable_until"] and row["vulnerable_until"] > utc_timestamp())

    async def create_leg_request(
        self, chat_id: int, target_id: int, requester_id: int, deadline: int
    ) -> int:
        async with self._lock:
            self.connection.execute(
                """UPDATE leg_requests SET status='replaced'
                   WHERE chat_id=? AND target_id=? AND status='pending'""",
                (chat_id, target_id),
            )
            cursor = self.connection.execute(
                """INSERT INTO leg_requests(
                       chat_id, target_id, requester_id, deadline, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (chat_id, target_id, requester_id, deadline, utc_timestamp()),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    async def get_leg_request(self, request_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM leg_requests WHERE id=?", (request_id,)
            ).fetchone()

    async def pending_leg_requests(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM leg_requests
                   WHERE status IN ('pending', 'enforcing') ORDER BY deadline"""
            ).fetchall()

    async def complete_leg_requests(self, chat_id: int, target_id: int) -> int:
        async with self._lock:
            cursor = self.connection.execute(
                """UPDATE leg_requests SET status='completed'
                   WHERE chat_id=? AND target_id=? AND status='pending'""",
                (chat_id, target_id),
            )
            self.connection.commit()
            return cursor.rowcount

    async def claim_expired_leg_request(self, request_id: int) -> sqlite3.Row | None:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM leg_requests
                   WHERE id=? AND status='pending' AND deadline <= ?""",
                (request_id, now),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE leg_requests SET status='enforcing' WHERE id=?",
                (request_id,),
            )
            self.connection.commit()
            return row

    async def finish_leg_request(self, request_id: int, status: str) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE leg_requests SET status=? WHERE id=?",
                (status, request_id),
            )
            self.connection.commit()
