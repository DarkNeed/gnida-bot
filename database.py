from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from blackjack import compare_stood_hands, hand_total, shuffled_deck
from checkers import (
    BLACK,
    WHITE,
    apply_move as apply_checkers_move,
    initial_board as initial_checkers_board,
    legal_moves as legal_checkers_moves,
)
from custom_commands import (
    MAX_RESPONSE_LENGTH,
    MAX_RESPONSES_PER_OUTCOME,
    MAX_TRIGGER_LENGTH,
    normalize_custom_trigger,
)


CHALLENGE_DEADLINE_SECONDS = 3 * 60 * 60
NEWCOMER_CHALLENGE_DEADLINE_SECONDS = 5 * 60
FORCE_OWNER_COOLDOWN_SECONDS = 7 * 24 * 60 * 60
PIROJOK_USERNAME = "pirojoksostajem"
JUG_HIDING_SECONDS = 5 * 60
JUG_COOLDOWN_SECONDS = 60 * 60
BASEMENT_ESCAPE_COOLDOWN_SECONDS = 60 * 60
BUSINESS_HOUR_SECONDS = 60 * 60
BUSINESS_STATS_TZ = timezone(timedelta(hours=3), name="MSK")
BUSINESS_ACTIVE_SECONDS = 24 * 60 * 60
SLAVE_EARNINGS_WEEK_SECONDS = 7 * 24 * 60 * 60
SLAVE_WEEKLY_EARNINGS_LIMIT = 100
BUYOUT_COST_FRANCS = 100
BUSINESS_CONFIG = {
    "brothel": {
        "producer_role": "courtesan",
        "leader_role": "manager",
        "owner_per_producer": 4,
        "inactive_owner_per_producer": 1,
        "producer_wage": 1,
        "producer_wage_period_hours": 6,
        "leader_wage": 1,
        "leader_wage_period_hours": 12,
        "shift_owner": 1,
        "shift_worker": 2,
    },
    "field": {
        "producer_role": "collector",
        "leader_role": "overseer",
        "owner_per_producer": 3,
        "inactive_owner_per_producer": 1,
        "producer_wage": 1,
        "producer_wage_period_hours": 6,
        "leader_wage": 1,
        "leader_wage_period_hours": 12,
        "shift_owner": 1,
        "shift_worker": 1,
    },
}


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
                transfer_priority INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS blackjack_games (
                challenge_id INTEGER PRIMARY KEY,
                deck TEXT NOT NULL,
                challenger_hand TEXT NOT NULL,
                opponent_hand TEXT NOT NULL,
                challenger_stood INTEGER NOT NULL DEFAULT 0,
                opponent_stood INTEGER NOT NULL DEFAULT 0,
                challenger_acted INTEGER NOT NULL DEFAULT 0,
                opponent_acted INTEGER NOT NULL DEFAULT 0,
                turn_user_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkers_games (
                challenge_id INTEGER PRIMARY KEY,
                board TEXT NOT NULL,
                turn_user_id INTEGER NOT NULL,
                selected_square INTEGER,
                chain_square INTEGER,
                challenger_acted INTEGER NOT NULL DEFAULT 0,
                opponent_acted INTEGER NOT NULL DEFAULT 0,
                move_count INTEGER NOT NULL DEFAULT 0
            );

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

            CREATE TABLE IF NOT EXISTS captchas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                correct_emoji TEXT NOT NULL,
                message_id INTEGER,
                join_message_id INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0,
                deadline INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_captchas_pending
                ON captchas(status, deadline);

            CREATE TABLE IF NOT EXISTS death_note_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                message_id INTEGER,
                deadline INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_death_note_pending
                ON death_note_entries(status, deadline);

            CREATE TABLE IF NOT EXISTS random_phrase_bags (
                chat_id INTEGER PRIMARY KEY,
                remaining_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS random_message_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                service_day TEXT NOT NULL,
                scheduled_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(chat_id, service_day, scheduled_at)
            );

            CREATE INDEX IF NOT EXISTS idx_random_message_schedules_pending
                ON random_message_schedules(chat_id, service_day, status, scheduled_at);

            CREATE TABLE IF NOT EXISTS counters (
                chat_id INTEGER NOT NULL,
                counter_key TEXT NOT NULL,
                value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, counter_key)
            );

            CREATE TABLE IF NOT EXISTS franc_balances (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                trigger TEXT NOT NULL,
                trigger_key TEXT NOT NULL,
                cost INTEGER NOT NULL DEFAULT 0 CHECK(cost >= 0),
                success_chance INTEGER NOT NULL DEFAULT 100
                    CHECK(success_chance BETWEEN 0 AND 100),
                success_responses TEXT NOT NULL,
                failure_responses TEXT NOT NULL,
                exclusive_user_id INTEGER,
                created_by INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(chat_id, trigger_key)
            );

            CREATE INDEX IF NOT EXISTS idx_custom_commands_chat
                ON custom_commands(chat_id, enabled, trigger_key);

            CREATE TABLE IF NOT EXISTS businesses (
                chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                business_type TEXT NOT NULL CHECK(business_type IN ('brothel', 'field')),
                created_at INTEGER NOT NULL,
                last_accrued INTEGER NOT NULL,
                PRIMARY KEY (chat_id, owner_id)
            );

            CREATE TABLE IF NOT EXISTS business_income_daily (
                chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                income_day TEXT NOT NULL,
                owner_income INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, owner_id, income_day)
            );

            CREATE INDEX IF NOT EXISTS idx_business_income_daily_period
                ON business_income_daily(chat_id, income_day);

            CREATE TABLE IF NOT EXISTS business_workers (
                chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                assigned_at INTEGER NOT NULL,
                wage_hours INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, owner_id, worker_id)
            );

            CREATE INDEX IF NOT EXISTS idx_business_workers_worker
                ON business_workers(chat_id, worker_id);

            CREATE TABLE IF NOT EXISTS business_shift_cooldowns (
                chat_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                cooldown_until INTEGER NOT NULL,
                PRIMARY KEY (chat_id, worker_id)
            );

            CREATE TABLE IF NOT EXISTS slave_labor_earnings (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                window_started INTEGER NOT NULL,
                earned INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS basement_members (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER NOT NULL,
                added_at INTEGER NOT NULL,
                rank INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_basement_members_added
                ON basement_members(chat_id, added_at);

            CREATE TABLE IF NOT EXISTS jug_hiding (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                hidden_until INTEGER NOT NULL,
                cooldown_until INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_jug_hiding_active
                ON jug_hiding(active, hidden_until);

            CREATE TABLE IF NOT EXISTS basement_escape_cooldowns (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                cooldown_until INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );
            """
        )
        self._ensure_column("ownership", "last_forced_at", "INTEGER")
        self._ensure_column("business_workers", "wage_hours", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(
            "ownership", "transfer_priority", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("captchas", "join_message_id", "INTEGER")
        self._ensure_column(
            "basement_members", "rank", "INTEGER NOT NULL DEFAULT 1"
        )
        self._ensure_column(
            "challenges", "forced", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column(
            "challenges", "opponent_newcomer", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("challenges", "deadline", "INTEGER")
        self._ensure_column(
            "challenges", "game_type", "TEXT NOT NULL DEFAULT 'rps'"
        )
        self._ensure_column(
            "challenges", "friendly", "INTEGER NOT NULL DEFAULT 0"
        )
        self._ensure_column("challenges", "inline_message_id", "TEXT")
        self._ensure_column("challenges", "winner_id", "INTEGER")
        self._ensure_column(
            "challenges", "result_recorded", "INTEGER NOT NULL DEFAULT 0"
        )
        self._connection.execute(
            """UPDATE challenges
               SET deadline=created_at + CASE
                   WHEN opponent_newcomer=1 THEN ? ELSE ? END
               WHERE deadline IS NULL OR status='active'""",
            (
                NEWCOMER_CHALLENGE_DEADLINE_SECONDS,
                CHALLENGE_DEADLINE_SECONDS,
            ),
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
        opponent_newcomer: bool = False,
        game_type: str = "rps",
        friendly: bool = False,
        awaiting_acceptance: bool = False,
    ) -> int | None:
        if game_type not in {"rps", "blackjack", "checkers"}:
            raise ValueError("Unknown challenge game type")
        if friendly:
            forced = False
            opponent_newcomer = False
        async with self._lock:
            existing = self.connection.execute(
                """SELECT id FROM challenges WHERE chat_id=?
                   AND status IN ('pending', 'active')
                   AND (challenger_id IN (?, ?) OR opponent_id IN (?, ?))""",
                (chat_id, challenger_id, opponent_id, challenger_id, opponent_id),
            ).fetchone()
            if existing:
                return None
            now = utc_timestamp()
            cursor = self.connection.execute(
                """INSERT INTO challenges(
                       chat_id, challenger_id, opponent_id, forced,
                       opponent_newcomer, game_type, friendly, status, created_at, deadline
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chat_id,
                    challenger_id,
                    opponent_id,
                    int(forced),
                    int(opponent_newcomer),
                    game_type,
                    int(friendly),
                    "pending" if awaiting_acceptance else "active",
                    now,
                    now
                    + (
                        NEWCOMER_CHALLENGE_DEADLINE_SECONDS
                        if opponent_newcomer
                        else CHALLENGE_DEADLINE_SECONDS
                    ),
                ),
            )
            challenge_id = int(cursor.lastrowid)
            if game_type == "blackjack":
                deck = shuffled_deck()
                challenger_hand = [deck.pop(), deck.pop()]
                opponent_hand = [deck.pop(), deck.pop()]
                self.connection.execute(
                    """INSERT INTO blackjack_games(
                           challenge_id, deck, challenger_hand, opponent_hand,
                           turn_user_id
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        challenge_id,
                        json.dumps(deck),
                        json.dumps(challenger_hand),
                        json.dumps(opponent_hand),
                        random.choice((challenger_id, opponent_id)),
                    ),
                )
            elif game_type == "checkers":
                self.connection.execute(
                    """INSERT INTO checkers_games(
                           challenge_id, board, turn_user_id
                       ) VALUES (?, ?, ?)""",
                    (
                        challenge_id,
                        json.dumps(initial_checkers_board()),
                        opponent_id,
                    ),
                )
            if forced:
                self.connection.execute(
                    """UPDATE ownership SET last_forced_at=?
                       WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                    (now, chat_id, challenger_id, opponent_id),
                )
            self.connection.commit()
            return challenge_id

    async def accept_challenge(
        self, challenge_id: int, opponent_id: int
    ) -> sqlite3.Row | None:
        """Activate a pending challenge when its invited opponent accepts it."""
        async with self._lock:
            accepted_at = utc_timestamp()
            cursor = self.connection.execute(
                """UPDATE challenges SET status='active', created_at=?, deadline=?
                   WHERE id=? AND opponent_id=? AND status='pending'""",
                (
                    accepted_at,
                    accepted_at + CHALLENGE_DEADLINE_SECONDS,
                    challenge_id,
                    opponent_id,
                ),
            )
            if cursor.rowcount == 0:
                self.connection.commit()
                return None
            self.connection.commit()
            return self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()

    async def cancel_challenge_offer(
        self, challenge_id: int, challenger_id: int
    ) -> bool:
        """Cancel an unaccepted offer, only on behalf of its creator."""
        async with self._lock:
            row = self.connection.execute(
                """SELECT chat_id, opponent_id, forced FROM challenges
                   WHERE id=? AND challenger_id=? AND status='pending'""",
                (challenge_id, challenger_id),
            ).fetchone()
            if row is None:
                return False
            self.connection.execute(
                "UPDATE challenges SET status='cancelled' WHERE id=?",
                (challenge_id,),
            )
            # A forced owner challenge only spends its weekly attempt once a game
            # actually starts; cancelling an offer must not consume it.
            if row["forced"]:
                self.connection.execute(
                    """UPDATE ownership SET last_forced_at=NULL
                       WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                    (int(row["chat_id"]), challenger_id, int(row["opponent_id"])),
                )
            self.connection.commit()
            return True

    async def set_challenge_message(self, challenge_id: int, message_id: int) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE challenges SET message_id=? WHERE id=?", (message_id, challenge_id)
            )
            self.connection.commit()

    async def set_challenge_inline_message(
        self, challenge_id: int, inline_message_id: str
    ) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE challenges SET inline_message_id=? WHERE id=?",
                (inline_message_id, challenge_id),
            )
            self.connection.commit()

    async def get_challenge(self, challenge_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()

    async def get_blackjack_game(self, challenge_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM blackjack_games WHERE challenge_id=?", (challenge_id,)
            ).fetchone()

    async def get_checkers_game(self, challenge_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM checkers_games WHERE challenge_id=?", (challenge_id,)
            ).fetchone()

    async def checkers_click(
        self, challenge_id: int, user_id: int, square: int
    ) -> dict[str, Any]:
        if square < 0 or square >= 64:
            return {"status": "invalid"}
        async with self._lock:
            challenge = self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()
            game = self.connection.execute(
                "SELECT * FROM checkers_games WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
            if (
                not challenge
                or challenge["status"] != "active"
                or challenge["game_type"] != "checkers"
                or not game
            ):
                return {"status": "inactive"}

            challenger_id = int(challenge["challenger_id"])
            opponent_id = int(challenge["opponent_id"])
            if user_id not in {challenger_id, opponent_id}:
                return {"status": "not_participant"}
            if user_id != int(game["turn_user_id"]):
                return {"status": "not_turn"}

            board = json.loads(game["board"])
            if not isinstance(board, list) or len(board) != 64:
                return {"status": "invalid"}
            color = BLACK if user_id == challenger_id else WHITE
            selected = (
                int(game["selected_square"])
                if game["selected_square"] is not None
                else None
            )
            chain_square = (
                int(game["chain_square"])
                if game["chain_square"] is not None
                else None
            )
            moves = legal_checkers_moves(board, color, forced_from=chain_square)

            if chain_square is None and square == selected:
                self.connection.execute(
                    "UPDATE checkers_games SET selected_square=NULL WHERE challenge_id=?",
                    (challenge_id,),
                )
                self.connection.commit()
                return {"status": "selected", "selected_square": None}
            if square in moves:
                self.connection.execute(
                    "UPDATE checkers_games SET selected_square=? WHERE challenge_id=?",
                    (square, challenge_id),
                )
                self.connection.commit()
                return {"status": "selected", "selected_square": square}
            if selected is None:
                return {"status": "invalid"}
            allowed_destinations = {
                move.destination for move in moves.get(selected, [])
            }
            if square not in allowed_destinations:
                return {"status": "invalid"}

            move_result = apply_checkers_move(board, color, selected, square)
            if move_result is None:
                return {"status": "invalid"}
            challenger_acted = bool(game["challenger_acted"])
            opponent_acted = bool(game["opponent_acted"])
            if user_id == challenger_id:
                challenger_acted = True
            else:
                opponent_acted = True
            if move_result.continuation:
                next_turn = user_id
                selected_square = chain_square = square
            else:
                next_turn = opponent_id if user_id == challenger_id else challenger_id
                selected_square = chain_square = None

            self.connection.execute(
                """UPDATE checkers_games SET
                       board=?, turn_user_id=?, selected_square=?, chain_square=?,
                       challenger_acted=?, opponent_acted=?, move_count=move_count + 1
                   WHERE challenge_id=?""",
                (
                    json.dumps(move_result.board),
                    next_turn,
                    selected_square,
                    chain_square,
                    int(challenger_acted),
                    int(opponent_acted),
                    challenge_id,
                ),
            )
            winner_id = loser_id = 0
            if move_result.winner:
                winner_id = challenger_id if move_result.winner == BLACK else opponent_id
                loser_id = opponent_id if winner_id == challenger_id else challenger_id
                self.connection.execute(
                    """UPDATE challenges
                       SET status='finished', winner_id=?, result_recorded=1
                       WHERE id=?""",
                    (winner_id, challenge_id),
                )
            else:
                self.connection.execute(
                    "UPDATE challenges SET deadline=? WHERE id=?",
                    (utc_timestamp() + CHALLENGE_DEADLINE_SECONDS, challenge_id),
                )
            self.connection.commit()
            return {
                "status": "finished" if move_result.winner else "moved",
                "board": move_result.board,
                "continuation": move_result.continuation,
                "winner_id": winner_id,
                "loser_id": loser_id,
                "reason": move_result.reason,
                "turn_user_id": next_turn,
            }

    async def blackjack_action(
        self, challenge_id: int, user_id: int, action: str
    ) -> dict[str, Any]:
        if action not in {"hit", "stand"}:
            return {"status": "invalid"}
        async with self._lock:
            challenge = self.connection.execute(
                "SELECT * FROM challenges WHERE id=?", (challenge_id,)
            ).fetchone()
            game = self.connection.execute(
                "SELECT * FROM blackjack_games WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
            if (
                not challenge
                or challenge["status"] != "active"
                or challenge["game_type"] != "blackjack"
                or not game
            ):
                return {"status": "inactive"}
            challenger_id = int(challenge["challenger_id"])
            opponent_id = int(challenge["opponent_id"])
            if user_id not in {challenger_id, opponent_id}:
                return {"status": "not_participant"}
            if user_id != int(game["turn_user_id"]):
                return {"status": "not_turn"}

            deck = json.loads(game["deck"])
            challenger_hand = json.loads(game["challenger_hand"])
            opponent_hand = json.loads(game["opponent_hand"])
            challenger_stood = bool(game["challenger_stood"])
            opponent_stood = bool(game["opponent_stood"])
            challenger_acted = bool(game["challenger_acted"])
            opponent_acted = bool(game["opponent_acted"])
            is_challenger = user_id == challenger_id
            hand = challenger_hand if is_challenger else opponent_hand
            other_id = opponent_id if is_challenger else challenger_id
            if (is_challenger and challenger_stood) or (
                not is_challenger and opponent_stood
            ):
                return {"status": "stood"}

            if is_challenger:
                challenger_acted = True
            else:
                opponent_acted = True
            if action == "hit":
                if not deck:
                    return {"status": "invalid"}
                hand.append(deck.pop())
                total = hand_total(hand)
                if total > 21:
                    winner_id, loser_id = other_id, user_id
                    reason = f"перебор — {total}"
                    finished = True
                else:
                    if total == 21:
                        if is_challenger:
                            challenger_stood = True
                        else:
                            opponent_stood = True
                    finished = False
                    winner_id = loser_id = 0
                    reason = ""
            else:
                if is_challenger:
                    challenger_stood = True
                else:
                    opponent_stood = True
                finished = False
                winner_id = loser_id = 0
                reason = ""

            if not finished and challenger_stood and opponent_stood:
                winner_index, reason = compare_stood_hands(
                    challenger_hand, opponent_hand, deck
                )
                winner_id = challenger_id if winner_index == 0 else opponent_id
                loser_id = opponent_id if winner_index == 0 else challenger_id
                finished = True

            if finished:
                next_turn = user_id
            elif is_challenger:
                next_turn = user_id if opponent_stood else opponent_id
            else:
                next_turn = user_id if challenger_stood else challenger_id

            self.connection.execute(
                """UPDATE blackjack_games SET
                       deck=?, challenger_hand=?, opponent_hand=?,
                       challenger_stood=?, opponent_stood=?,
                       challenger_acted=?, opponent_acted=?, turn_user_id=?
                   WHERE challenge_id=?""",
                (
                    json.dumps(deck),
                    json.dumps(challenger_hand),
                    json.dumps(opponent_hand),
                    int(challenger_stood),
                    int(opponent_stood),
                    int(challenger_acted),
                    int(opponent_acted),
                    next_turn,
                    challenge_id,
                ),
            )
            if finished:
                self.connection.execute(
                    """UPDATE challenges
                       SET status='finished', winner_id=?, result_recorded=1
                       WHERE id=?""",
                    (winner_id, challenge_id),
                )
            self.connection.commit()
            return {
                "status": "finished" if finished else "updated",
                "winner_id": winner_id,
                "loser_id": loser_id,
                "reason": reason,
                "challenger_hand": challenger_hand,
                "opponent_hand": opponent_hand,
                "challenger_stood": challenger_stood,
                "opponent_stood": opponent_stood,
                "turn_user_id": next_turn,
            }

    async def pending_challenges(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM challenges
                   WHERE status IN ('pending', 'active', 'deadline', 'pending_deadline')
                   ORDER BY deadline"""
            ).fetchall()

    async def claim_expired_challenge(self, challenge_id: int) -> sqlite3.Row | None:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM challenges
                   WHERE id=? AND status IN ('pending', 'active') AND deadline <= ?""",
                (challenge_id, now),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE challenges SET status=? WHERE id=?",
                (
                    "pending_deadline" if row["status"] == "pending" else "deadline",
                    challenge_id,
                ),
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
                """UPDATE challenges SET status=? WHERE id=?
                   AND status IN ('pending', 'active')""",
                (status, challenge_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def mark_challenge_unavailable(self, challenge_id: int) -> None:
        """Stop resuming a challenge whose Telegram message is no longer available."""
        async with self._lock:
            self.connection.execute(
                """UPDATE challenges SET status='unavailable'
                   WHERE id=? AND status IN ('pending', 'active', 'deadline', 'pending_deadline')""",
                (challenge_id,),
            )
            self.connection.commit()

    async def record_challenge_result(
        self, challenge_id: int, winner_id: int | None
    ) -> None:
        """Persist a result after an RPS game (including a draw)."""
        async with self._lock:
            self.connection.execute(
                """UPDATE challenges
                   SET winner_id=?, result_recorded=1,
                       status=CASE WHEN status='deadline' THEN 'finished' ELSE status END
                   WHERE id=? AND status IN ('finished', 'deadline')""",
                (winner_id, challenge_id),
            )
            self.connection.commit()

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
                    self.connection.execute(
                        "DELETE FROM business_workers WHERE chat_id=? AND worker_id=?",
                        (chat_id, winner_id),
                    )
                    self.connection.commit()
                    return "freed", winner_id
                self.connection.commit()
                return "no_reward", loser_id
            winner = self.connection.execute(
                "SELECT username FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, winner_id),
            ).fetchone()
            if (
                winner
                and winner["username"]
                and winner["username"].casefold() == PIROJOK_USERNAME
            ):
                return "pirojok_cannot_own", loser_id
            loser_owner = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, loser_id),
            ).fetchone()
            if loser_owner and int(loser_owner["owner_id"]) == winner_id:
                self.connection.commit()
                return "kept", loser_id
            if loser_owner:
                self.connection.commit()
                return "protected_slave", loser_id
            owned = self.connection.execute(
                """SELECT slave_id FROM ownership
                   WHERE chat_id=? AND owner_id=? AND slave_id != ?
                   ORDER BY transfer_priority ASC, RANDOM() LIMIT 1""",
                (chat_id, loser_id, winner_id),
            ).fetchone()
            if owned:
                slave_id = int(owned["slave_id"])
                self.connection.execute(
                    "DELETE FROM business_workers WHERE chat_id=? AND worker_id=?",
                    (chat_id, slave_id),
                )
                self.connection.execute(
                    """UPDATE ownership SET owner_id=?, acquired_at=?, last_forced_at=NULL,
                           transfer_priority=0
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
                           last_forced_at=NULL,
                           transfer_priority=0""",
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
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT acquired_at, last_forced_at FROM ownership
                   WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                (chat_id, slave_id, owner_id),
            ).fetchone()
            if not row or now < int(row["acquired_at"]) + FORCE_OWNER_COOLDOWN_SECONDS:
                return False
            return row["last_forced_at"] is None or now >= (
                int(row["last_forced_at"]) + FORCE_OWNER_COOLDOWN_SECONDS
            )

    async def transfer_slave(
        self, chat_id: int, current_owner_id: int, slave_id: int, new_owner_id: int
    ) -> str:
        async with self._lock:
            if slave_id == new_owner_id:
                return "self"
            owned = self.connection.execute(
                """SELECT 1 FROM ownership
                   WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                (chat_id, slave_id, current_owner_id),
            ).fetchone()
            if not owned:
                return "not_owned"
            if current_owner_id == new_owner_id:
                return "same_owner"
            recipient = self.connection.execute(
                "SELECT username FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, new_owner_id),
            ).fetchone()
            if (
                recipient
                and recipient["username"]
                and recipient["username"].casefold() == PIROJOK_USERNAME
            ):
                return "pirojok_cannot_own"
            recipient_is_slave = self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, new_owner_id),
            ).fetchone()
            if recipient_is_slave:
                return "recipient_is_slave"
            self.connection.execute(
                "DELETE FROM business_workers WHERE chat_id=? AND worker_id=?",
                (chat_id, slave_id),
            )
            self.connection.execute(
                """UPDATE ownership
                   SET owner_id=?, acquired_at=?, last_forced_at=NULL, transfer_priority=0
                   WHERE chat_id=? AND slave_id=?""",
                (new_owner_id, utc_timestamp(), chat_id, slave_id),
            )
            self.connection.commit()
            return "transferred"

    async def force_enslave(self, chat_id: int, slave_id: int, owner_id: int) -> str:
        async with self._lock:
            if slave_id == owner_id:
                return "self"
            owner = self.connection.execute(
                "SELECT username FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, owner_id),
            ).fetchone()
            if (
                owner
                and owner["username"]
                and owner["username"].casefold() == PIROJOK_USERNAME
            ):
                return "pirojok_cannot_own"
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
                "DELETE FROM business_workers WHERE chat_id=? AND owner_id=?",
                (chat_id, slave_id),
            )
            self.connection.execute(
                "DELETE FROM business_workers WHERE chat_id=? AND worker_id=?",
                (chat_id, slave_id),
            )
            self.connection.execute(
                """INSERT INTO ownership(
                       chat_id, slave_id, owner_id, acquired_at, last_forced_at
                   ) VALUES (?, ?, ?, ?, NULL)
                   ON CONFLICT(chat_id, slave_id) DO UPDATE SET
                       owner_id=excluded.owner_id,
                       acquired_at=excluded.acquired_at,
                       last_forced_at=NULL,
                       transfer_priority=0""",
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
            if cursor.rowcount:
                self.connection.execute(
                    "DELETE FROM business_workers WHERE chat_id=? AND owner_id=?",
                    (chat_id, owner_id),
                )
            self.connection.commit()
            return cursor.rowcount

    async def start_jug_hiding(self, chat_id: int, user_id: int) -> int | None:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                "SELECT cooldown_until FROM jug_hiding WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            if row and int(row["cooldown_until"]) > now:
                return None
            hidden_until = now + JUG_HIDING_SECONDS
            cooldown_until = hidden_until + JUG_COOLDOWN_SECONDS
            self.connection.execute(
                """INSERT INTO jug_hiding(
                       chat_id, user_id, hidden_until, cooldown_until, active
                   ) VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(chat_id, user_id) DO UPDATE SET
                       hidden_until=excluded.hidden_until,
                       cooldown_until=excluded.cooldown_until,
                       active=1""",
                (chat_id, user_id, hidden_until, cooldown_until),
            )
            self.connection.commit()
            return hidden_until

    async def is_jug_hidden(self, chat_id: int, user_id: int) -> bool:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT 1 FROM jug_hiding
                   WHERE chat_id=? AND user_id=? AND active=1 AND hidden_until>?""",
                (chat_id, user_id, now),
            ).fetchone()
            return row is not None

    async def pending_jug_hidings(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM jug_hiding WHERE active=1 ORDER BY hidden_until"
            ).fetchall()

    async def finish_jug_hiding(self, chat_id: int, user_id: int) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                """UPDATE jug_hiding SET active=0
                   WHERE chat_id=? AND user_id=? AND active=1 AND hidden_until<=?""",
                (chat_id, user_id, utc_timestamp()),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def increment_counter(self, chat_id: int, key: str, amount: int = 1) -> int:
        if amount < 1:
            raise ValueError("Counter increment must be positive")
        async with self._lock:
            self.connection.execute(
                """INSERT INTO counters(chat_id, counter_key, value) VALUES (?, ?, ?)
                   ON CONFLICT(chat_id, counter_key) DO UPDATE SET value=value + excluded.value""",
                (chat_id, key, amount),
            )
            row = self.connection.execute(
                "SELECT value FROM counters WHERE chat_id=? AND counter_key=?",
                (chat_id, key),
            ).fetchone()
            self.connection.commit()
            return int(row["value"])

    def _add_francs_locked(self, chat_id: int, user_id: int, amount: int) -> None:
        if amount < 0:
            raise ValueError("Cannot add a negative franc amount")
        now = utc_timestamp()
        self.connection.execute(
            """INSERT INTO franc_balances(chat_id, user_id, balance, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET
                   balance=balance + excluded.balance,
                   updated_at=excluded.updated_at""",
            (chat_id, user_id, amount, now),
        )

    def _credit_labor_income_locked(
        self, chat_id: int, user_id: int, amount: int, now: int
    ) -> int:
        """Credit labor income, capping only participants who are currently slaves."""
        if amount <= 0:
            return 0
        is_slave = self.connection.execute(
            "SELECT 1 FROM ownership WHERE chat_id=? AND slave_id=?",
            (chat_id, user_id),
        ).fetchone()
        if is_slave is None:
            self._add_francs_locked(chat_id, user_id, amount)
            return amount
        row = self.connection.execute(
            """SELECT window_started, earned FROM slave_labor_earnings
               WHERE chat_id=? AND user_id=?""",
            (chat_id, user_id),
        ).fetchone()
        if row is None or now >= int(row["window_started"]) + SLAVE_EARNINGS_WEEK_SECONDS:
            window_started, earned = now, 0
        else:
            window_started, earned = int(row["window_started"]), int(row["earned"])
        paid = min(amount, max(0, SLAVE_WEEKLY_EARNINGS_LIMIT - earned))
        self.connection.execute(
            """INSERT INTO slave_labor_earnings(chat_id, user_id, window_started, earned)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(chat_id, user_id) DO UPDATE SET
                   window_started=excluded.window_started, earned=excluded.earned""",
            (chat_id, user_id, window_started, earned + paid),
        )
        if paid:
            self._add_francs_locked(chat_id, user_id, paid)
        return paid

    @staticmethod
    def _active_hours_in_interval(
        last_seen: int | None, start: int, end: int
    ) -> int:
        if last_seen is None:
            return 0
        active_end = min(end, last_seen + BUSINESS_ACTIVE_SECONDS)
        return max(0, (active_end - start) // BUSINESS_HOUR_SECONDS)

    def _record_business_income_locked(
        self,
        chat_id: int,
        owner_id: int,
        start: int,
        hours: int,
        producers: list[sqlite3.Row],
        config: dict[str, int | str],
        bonus_percent: int,
        owner_income: int,
    ) -> None:
        """Split settled owner income across Moscow calendar days for public stats."""
        if owner_income <= 0:
            return
        weights: dict[str, int] = {}
        for offset in range(hours):
            hour_end = start + (offset + 1) * BUSINESS_HOUR_SECONDS
            active = sum(
                worker["last_seen"] is not None
                and hour_end <= int(worker["last_seen"]) + BUSINESS_ACTIVE_SECONDS
                for worker in producers
            )
            inactive = len(producers) - active
            hourly_income = (
                active * int(config["owner_per_producer"]) * (100 + bonus_percent) // 100
                + inactive * int(config["inactive_owner_per_producer"])
            )
            day = datetime.fromtimestamp(hour_end - 1, BUSINESS_STATS_TZ).date().isoformat()
            weights[day] = weights.get(day, 0) + hourly_income
        weight_total = sum(weights.values())
        if weight_total <= 0:
            return
        remaining = owner_income
        days = sorted(weights)
        for day in days[:-1]:
            allocated = owner_income * weights[day] // weight_total
            remaining -= allocated
            self.connection.execute(
                """INSERT INTO business_income_daily(chat_id, owner_id, income_day, owner_income)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(chat_id, owner_id, income_day) DO UPDATE SET
                       owner_income=owner_income + excluded.owner_income""",
                (chat_id, owner_id, day, allocated),
            )
        self.connection.execute(
            """INSERT INTO business_income_daily(chat_id, owner_id, income_day, owner_income)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(chat_id, owner_id, income_day) DO UPDATE SET
                   owner_income=owner_income + excluded.owner_income""",
            (chat_id, owner_id, days[-1], remaining),
        )

    def _settle_business_locked(
        self, chat_id: int, owner_id: int, now: int
    ) -> dict[str, int | str] | None:
        business = self.connection.execute(
            """SELECT * FROM businesses WHERE chat_id=? AND owner_id=?""",
            (chat_id, owner_id),
        ).fetchone()
        if business is None:
            return None
        hours = max(0, (now - int(business["last_accrued"])) // BUSINESS_HOUR_SECONDS)
        if hours == 0:
            return {"hours": 0, "owner_income": 0, "business_type": business["business_type"]}
        config = BUSINESS_CONFIG[str(business["business_type"])]
        interval_start = int(business["last_accrued"])
        interval_end = interval_start + hours * BUSINESS_HOUR_SECONDS
        workers = self.connection.execute(
            """SELECT w.worker_id, w.role, w.wage_hours, u.last_seen
               FROM business_workers w
               INNER JOIN ownership o
                   ON o.chat_id=w.chat_id AND o.owner_id=w.owner_id
                      AND o.slave_id=w.worker_id
               LEFT JOIN users u ON u.chat_id=w.chat_id AND u.user_id=w.worker_id
               WHERE w.chat_id=? AND w.owner_id=?""",
            (chat_id, owner_id),
        ).fetchall()
        producers = [worker for worker in workers if worker["role"] == config["producer_role"]]
        leaders = [worker for worker in workers if worker["role"] == config["leader_role"]]
        # The next manager contributes half the previous bonus: 20%, 10%, 5%, 2%, 1%.
        bonus_percent = sum(20 // (2**index) for index in range(min(len(leaders), 5)))
        active_producer_hours = sum(
            self._active_hours_in_interval(
                int(worker["last_seen"]) if worker["last_seen"] is not None else None,
                interval_start,
                interval_end,
            )
            for worker in producers
        )
        inactive_producer_hours = len(producers) * hours - active_producer_hours
        owner_income = (
            active_producer_hours * int(config["owner_per_producer"]) * (100 + bonus_percent) // 100
            + inactive_producer_hours * int(config["inactive_owner_per_producer"])
        )
        if owner_income:
            self._record_business_income_locked(
                chat_id,
                owner_id,
                interval_start,
                hours,
                producers,
                config,
                bonus_percent,
                owner_income,
            )
            self._add_francs_locked(chat_id, owner_id, owner_income)
        for worker in workers:
            active_hours = self._active_hours_in_interval(
                int(worker["last_seen"]) if worker["last_seen"] is not None else None,
                interval_start,
                interval_end,
            )
            if worker["role"] == config["producer_role"]:
                period = int(config["producer_wage_period_hours"])
                wage = int(config["producer_wage"])
            else:
                period = int(config["leader_wage_period_hours"])
                wage = int(config["leader_wage"])
            accrued_hours = int(worker["wage_hours"]) + active_hours
            payouts, remainder = divmod(accrued_hours, period)
            if payouts:
                self._credit_labor_income_locked(
                    chat_id, int(worker["worker_id"]), payouts * wage, now
                )
            self.connection.execute(
                """UPDATE business_workers SET wage_hours=?
                   WHERE chat_id=? AND owner_id=? AND worker_id=?""",
                (remainder, chat_id, owner_id, int(worker["worker_id"])),
            )
        self.connection.execute(
            """UPDATE businesses SET last_accrued=last_accrued + ?
               WHERE chat_id=? AND owner_id=?""",
            (hours * BUSINESS_HOUR_SECONDS, chat_id, owner_id),
        )
        return {
            "hours": hours,
            "owner_income": owner_income,
            "business_type": str(business["business_type"]),
        }

    async def settle_business(
        self, chat_id: int, owner_id: int
    ) -> dict[str, int | str] | None:
        async with self._lock:
            result = self._settle_business_locked(chat_id, owner_id, utc_timestamp())
            if result and int(result["hours"]):
                self.connection.commit()
            return result

    async def settle_businesses_for_user(self, user_id: int) -> None:
        async with self._lock:
            rows = self.connection.execute(
                """SELECT DISTINCT b.chat_id, b.owner_id
                   FROM businesses b
                   LEFT JOIN business_workers w
                       ON w.chat_id=b.chat_id AND w.owner_id=b.owner_id
                   WHERE b.owner_id=? OR w.worker_id=?""",
                (user_id, user_id),
            ).fetchall()
            now = utc_timestamp()
            changed = False
            for row in rows:
                result = self._settle_business_locked(
                    int(row["chat_id"]), int(row["owner_id"]), now
                )
                changed = changed or bool(result and int(result["hours"]))
            if changed:
                self.connection.commit()

    async def save_custom_command(
        self,
        chat_id: int,
        trigger: str,
        trigger_key: str,
        cost: int,
        success_chance: int,
        success_responses: list[str],
        failure_responses: list[str],
        exclusive_user_id: int | None,
        created_by: int,
    ) -> int:
        if cost < 0 or not 0 <= success_chance <= 100:
            raise ValueError("Invalid custom command cost or success chance")
        if not trigger_key or not success_responses:
            raise ValueError("A trigger and success response are required")
        now = utc_timestamp()
        async with self._lock:
            self.connection.execute(
                """INSERT INTO custom_commands(
                       chat_id, trigger, trigger_key, cost, success_chance,
                       success_responses, failure_responses, exclusive_user_id,
                       created_by, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id, trigger_key) DO UPDATE SET
                       trigger=excluded.trigger,
                       cost=excluded.cost,
                       success_chance=excluded.success_chance,
                       success_responses=excluded.success_responses,
                       failure_responses=excluded.failure_responses,
                       exclusive_user_id=excluded.exclusive_user_id,
                       created_by=excluded.created_by,
                       enabled=1,
                       updated_at=excluded.updated_at""",
                (
                    chat_id,
                    trigger,
                    trigger_key,
                    cost,
                    success_chance,
                    json.dumps(success_responses, ensure_ascii=False),
                    json.dumps(failure_responses, ensure_ascii=False),
                    exclusive_user_id,
                    created_by,
                    now,
                    now,
                ),
            )
            row = self.connection.execute(
                "SELECT id FROM custom_commands WHERE chat_id=? AND trigger_key=?",
                (chat_id, trigger_key),
            ).fetchone()
            self.connection.commit()
            return int(row["id"])

    async def get_custom_command(
        self, chat_id: int, trigger_key: str
    ) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM custom_commands
                   WHERE chat_id=? AND trigger_key=? AND enabled=1""",
                (chat_id, trigger_key),
            ).fetchone()

    async def list_custom_commands(self, chat_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT c.*, u.display_name AS exclusive_display_name,
                          u.username AS exclusive_username
                   FROM custom_commands c
                   LEFT JOIN users u
                     ON u.chat_id=c.chat_id AND u.user_id=c.exclusive_user_id
                   WHERE c.chat_id=? AND c.enabled=1
                   ORDER BY c.trigger_key""",
                (chat_id,),
            ).fetchall()

    async def list_all_custom_commands(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT c.*, chats.title AS chat_title
                   FROM custom_commands c
                   LEFT JOIN chats ON chats.chat_id=c.chat_id
                   WHERE c.enabled=1 ORDER BY c.chat_id, c.trigger_key"""
            ).fetchall()

    async def list_available_custom_commands(self, user_id: int) -> list[sqlite3.Row]:
        """Commands in known chats that this user may invoke; caller verifies membership."""
        async with self._lock:
            return self.connection.execute(
                """SELECT cmd.id, cmd.chat_id, cmd.trigger, cmd.cost,
                          cmd.success_chance, chats.title AS chat_title
                   FROM custom_commands cmd
                   JOIN users u ON u.chat_id=cmd.chat_id AND u.user_id=?
                   LEFT JOIN chats ON chats.chat_id=cmd.chat_id
                   WHERE cmd.enabled=1
                     AND (cmd.exclusive_user_id IS NULL OR cmd.exclusive_user_id=?)
                   ORDER BY cmd.chat_id, cmd.trigger_key""",
                (user_id, user_id),
            ).fetchall()

    async def list_custom_command_chats(self, owner_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT c.chat_id, c.title FROM chats c
                   WHERE EXISTS (SELECT 1 FROM users u
                                 WHERE u.chat_id=c.chat_id AND u.user_id=?)
                      OR EXISTS (SELECT 1 FROM custom_commands cmd
                                 WHERE cmd.chat_id=c.chat_id AND cmd.created_by=?)
                   ORDER BY c.title, c.chat_id""",
                (owner_id, owner_id),
            ).fetchall()

    async def get_custom_command_by_id(self, command_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                """SELECT cmd.*, c.title AS chat_title,
                          u.username AS exclusive_username,
                          u.display_name AS exclusive_display_name
                   FROM custom_commands cmd
                   LEFT JOIN chats c ON c.chat_id=cmd.chat_id
                   LEFT JOIN users u ON u.chat_id=cmd.chat_id
                                    AND u.user_id=cmd.exclusive_user_id
                   WHERE cmd.id=? AND cmd.enabled=1""",
                (command_id,),
            ).fetchone()

    async def update_custom_command_setting(
        self, command_id: int, field: str, value: str | int | None
    ) -> str:
        if field not in {"trigger", "cost", "success_chance", "exclusive_user_id"}:
            raise ValueError("Unknown custom command setting")
        async with self._lock:
            row = self.connection.execute(
                "SELECT * FROM custom_commands WHERE id=? AND enabled=1", (command_id,)
            ).fetchone()
            if row is None:
                return "not_found"
            if field == "trigger":
                trigger = str(value).strip()
                key = normalize_custom_trigger(trigger)
                if not key or len(trigger) > MAX_TRIGGER_LENGTH or trigger.startswith("/"):
                    return "invalid"
                try:
                    self.connection.execute(
                        """UPDATE custom_commands
                           SET trigger=?, trigger_key=?, updated_at=? WHERE id=?""",
                        (trigger, key, utc_timestamp(), command_id),
                    )
                except sqlite3.IntegrityError:
                    return "exists"
            else:
                if field == "cost" and (not isinstance(value, int) or not 0 <= value <= 1_000_000):
                    return "invalid"
                if field == "success_chance":
                    if not isinstance(value, int) or not 0 <= value <= 100:
                        return "invalid"
                    if value < 100 and not json.loads(row["failure_responses"]):
                        return "needs_failure"
                if field == "exclusive_user_id" and value is not None and (
                    not isinstance(value, int) or value <= 0
                ):
                    return "invalid"
                self.connection.execute(
                    f"UPDATE custom_commands SET {field}=?, updated_at=? WHERE id=?",
                    (value, utc_timestamp(), command_id),
                )
            self.connection.commit()
            return "updated"

    async def modify_custom_command_response(
        self, command_id: int, outcome: str, action: str,
        *, index: int | None = None, text: str | None = None,
    ) -> str:
        if outcome not in {"success", "failure"} or action not in {"add", "edit", "delete"}:
            raise ValueError("Unknown response change")
        column = "success_responses" if outcome == "success" else "failure_responses"
        async with self._lock:
            row = self.connection.execute(
                "SELECT * FROM custom_commands WHERE id=? AND enabled=1", (command_id,)
            ).fetchone()
            if row is None:
                return "not_found"
            responses = json.loads(row[column])
            if action in {"add", "edit"}:
                if not text or not text.strip() or len(text.strip()) > MAX_RESPONSE_LENGTH:
                    return "invalid"
                if action == "add":
                    if len(responses) >= MAX_RESPONSES_PER_OUTCOME:
                        return "limit"
                    responses.append(text.strip())
                else:
                    if index is None or not 0 <= index < len(responses):
                        return "not_found"
                    responses[index] = text.strip()
            else:
                if index is None or not 0 <= index < len(responses):
                    return "not_found"
                if len(responses) == 1 and (
                    outcome == "success" or int(row["success_chance"]) < 100
                ):
                    return "last_required"
                responses.pop(index)
            self.connection.execute(
                f"UPDATE custom_commands SET {column}=?, updated_at=? WHERE id=?",
                (json.dumps(responses, ensure_ascii=False), utc_timestamp(), command_id),
            )
            self.connection.commit()
            return "updated"

    async def delete_custom_command_by_id(self, command_id: int) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM custom_commands WHERE id=?", (command_id,)
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def delete_custom_command(self, chat_id: int, trigger_key: str) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM custom_commands WHERE chat_id=? AND trigger_key=?",
                (chat_id, trigger_key),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def spend_francs(self, chat_id: int, user_id: int, amount: int) -> bool:
        """Atomically debit a balance, returning False when funds are insufficient."""
        if amount < 0:
            raise ValueError("Cannot spend a negative franc amount")
        if amount == 0:
            return True
        async with self._lock:
            cursor = self.connection.execute(
                """UPDATE franc_balances
                   SET balance=balance-?, updated_at=?
                   WHERE chat_id=? AND user_id=? AND balance>=?""",
                (amount, utc_timestamp(), chat_id, user_id, amount),
            )
            self.connection.commit()
            return cursor.rowcount == 1

    async def franc_balance(self, chat_id: int, user_id: int) -> int:
        async with self._lock:
            row = self.connection.execute(
                "SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            return int(row["balance"]) if row else 0

    async def list_franc_balances(self, user_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT f.chat_id, f.balance, c.title AS chat_title
                   FROM franc_balances f
                   LEFT JOIN chats c ON c.chat_id=f.chat_id
                   WHERE f.user_id=? ORDER BY f.balance DESC, f.chat_id""",
                (user_id,),
            ).fetchall()

    async def transfer_francs(
        self, chat_id: int, sender_id: int, recipient_id: int, amount: int
    ) -> str:
        if amount <= 0:
            return "invalid_amount"
        if sender_id == recipient_id:
            return "self"
        async with self._lock:
            balance = self.connection.execute(
                "SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?",
                (chat_id, sender_id),
            ).fetchone()
            if not balance or int(balance["balance"]) < amount:
                return "insufficient"
            now = utc_timestamp()
            self.connection.execute(
                """UPDATE franc_balances SET balance=balance-?, updated_at=?
                   WHERE chat_id=? AND user_id=?""",
                (amount, now, chat_id, sender_id),
            )
            self._add_francs_locked(chat_id, recipient_id, amount)
            self.connection.commit()
            return "transferred"

    async def create_business(self, chat_id: int, owner_id: int, business_type: str) -> str:
        if business_type not in BUSINESS_CONFIG:
            raise ValueError("Unknown business type")
        async with self._lock:
            existing = self.connection.execute(
                "SELECT 1 FROM businesses WHERE owner_id=?",
                (owner_id,),
            ).fetchone()
            if existing:
                return "exists"
            slave = self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? LIMIT 1",
                (chat_id, owner_id),
            ).fetchone()
            if slave is None:
                return "no_slaves"
            now = utc_timestamp()
            self.connection.execute(
                """INSERT INTO businesses(
                       chat_id, owner_id, business_type, created_at, last_accrued
                   ) VALUES (?, ?, ?, ?, ?)""",
                (chat_id, owner_id, business_type, now, now),
            )
            self.connection.commit()
            return "created"

    async def get_business(self, chat_id: int, owner_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                """SELECT b.*, c.title AS chat_title, u.username, u.display_name
                   FROM businesses b
                   LEFT JOIN chats c ON c.chat_id=b.chat_id
                   LEFT JOIN users u ON u.chat_id=b.chat_id AND u.user_id=b.owner_id
                   WHERE b.chat_id=? AND b.owner_id=?""",
                (chat_id, owner_id),
            ).fetchone()

    async def list_owned_businesses(self, owner_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT b.*, c.title AS chat_title
                   FROM businesses b
                   LEFT JOIN chats c ON c.chat_id=b.chat_id
                   WHERE b.owner_id=? ORDER BY b.created_at DESC""",
                (owner_id,),
            ).fetchall()

    async def list_chat_businesses(self, chat_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT b.*, u.username, u.display_name
                   FROM businesses b
                   LEFT JOIN users u ON u.chat_id=b.chat_id AND u.user_id=b.owner_id
                   WHERE b.chat_id=? ORDER BY b.created_at, b.owner_id""",
                (chat_id,),
            ).fetchall()

    async def list_visible_businesses(self, user_id: int) -> list[sqlite3.Row]:
        """Businesses in chats where the bot has seen this user."""
        async with self._lock:
            return self.connection.execute(
                """SELECT b.*, c.title AS chat_title, u.username, u.display_name
                   FROM businesses b
                   INNER JOIN users participant
                       ON participant.chat_id=b.chat_id AND participant.user_id=?
                   LEFT JOIN chats c ON c.chat_id=b.chat_id
                   LEFT JOIN users u ON u.chat_id=b.chat_id AND u.user_id=b.owner_id
                   ORDER BY c.title, b.created_at, b.owner_id""",
                (user_id,),
            ).fetchall()

    async def user_knows_chat(self, user_id: int, chat_id: int) -> bool:
        async with self._lock:
            return self.connection.execute(
                "SELECT 1 FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone() is not None

    async def business_income_periods(
        self, chat_id: int, owner_id: int
    ) -> tuple[int, int]:
        """Return owner income for yesterday and the seven completed Moscow days."""
        now = datetime.now(BUSINESS_STATS_TZ).date()
        yesterday = now - timedelta(days=1)
        week_start = now - timedelta(days=7)
        async with self._lock:
            rows = self.connection.execute(
                """SELECT income_day, owner_income FROM business_income_daily
                   WHERE chat_id=? AND owner_id=? AND income_day>=? AND income_day<=?""",
                (chat_id, owner_id, week_start.isoformat(), yesterday.isoformat()),
            ).fetchall()
        yesterday_income = sum(
            int(row["owner_income"])
            for row in rows
            if row["income_day"] == yesterday.isoformat()
        )
        week_income = sum(int(row["owner_income"]) for row in rows)
        return yesterday_income, week_income

    async def list_available_businesses(self, user_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT b.*, c.title AS chat_title, u.username, u.display_name
                   FROM businesses b
                   INNER JOIN users participant
                       ON participant.chat_id=b.chat_id AND participant.user_id=?
                   LEFT JOIN chats c ON c.chat_id=b.chat_id
                   LEFT JOIN users u ON u.chat_id=b.chat_id AND u.user_id=b.owner_id
                   WHERE b.owner_id<>?
                   ORDER BY c.title, b.owner_id""",
                (user_id, user_id),
            ).fetchall()

    async def list_business_slaves(
        self, chat_id: int, owner_id: int
    ) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT o.slave_id AS user_id, u.username, u.display_name, w.role
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   LEFT JOIN business_workers w
                       ON w.chat_id=o.chat_id AND w.owner_id=o.owner_id
                          AND w.worker_id=o.slave_id
                   WHERE o.chat_id=? AND o.owner_id=? ORDER BY o.acquired_at DESC""",
                (chat_id, owner_id),
            ).fetchall()

    async def set_business_worker_role(
        self, chat_id: int, owner_id: int, worker_id: int, role: str | None
    ) -> str:
        async with self._lock:
            business = self.connection.execute(
                "SELECT business_type FROM businesses WHERE chat_id=? AND owner_id=?",
                (chat_id, owner_id),
            ).fetchone()
            if business is None:
                return "no_business"
            config = BUSINESS_CONFIG[str(business["business_type"])]
            valid_roles = {config["producer_role"], config["leader_role"]}
            if role is not None and role not in valid_roles:
                return "invalid_role"
            owned = self.connection.execute(
                """SELECT 1 FROM ownership
                   WHERE chat_id=? AND owner_id=? AND slave_id=?""",
                (chat_id, owner_id, worker_id),
            ).fetchone()
            if owned is None:
                return "not_owned"
            if role is None:
                self.connection.execute(
                    """DELETE FROM business_workers
                       WHERE chat_id=? AND owner_id=? AND worker_id=?""",
                    (chat_id, owner_id, worker_id),
                )
                self.connection.commit()
                return "removed"
            self.connection.execute(
                """INSERT INTO business_workers(
                       chat_id, owner_id, worker_id, role, assigned_at
                   ) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id, owner_id, worker_id) DO UPDATE SET role=excluded.role""",
                (chat_id, owner_id, worker_id, role, utc_timestamp()),
            )
            self.connection.commit()
            return "updated"

    async def business_worker_role(
        self, chat_id: int, owner_id: int, worker_id: int
    ) -> str | None:
        async with self._lock:
            row = self.connection.execute(
                """SELECT w.role FROM business_workers w
                   INNER JOIN ownership o
                       ON o.chat_id=w.chat_id AND o.owner_id=w.owner_id
                          AND o.slave_id=w.worker_id
                   WHERE w.chat_id=? AND w.owner_id=? AND w.worker_id=?""",
                (chat_id, owner_id, worker_id),
            ).fetchone()
            return str(row["role"]) if row else None

    async def work_at_business(
        self, chat_id: int, owner_id: int, worker_id: int
    ) -> tuple[str, int | None, int | None, int | None]:
        """Pay a one-hour temporary job. Returns status, worker pay, owner pay, cooldown."""
        async with self._lock:
            business = self.connection.execute(
                """SELECT business_type FROM businesses
                   WHERE chat_id=? AND owner_id=?""",
                (chat_id, owner_id),
            ).fetchone()
            if business is None:
                return "no_business", None, None, None
            if owner_id == worker_id:
                return "own_business", None, None, None
            now = utc_timestamp()
            cooldown = self.connection.execute(
                """SELECT cooldown_until FROM business_shift_cooldowns
                   WHERE chat_id=? AND worker_id=?""",
                (chat_id, worker_id),
            ).fetchone()
            if cooldown and int(cooldown["cooldown_until"]) > now:
                return "cooldown", None, None, int(cooldown["cooldown_until"])
            config = BUSINESS_CONFIG[str(business["business_type"])]
            worker_pay = int(config["shift_worker"])
            owner_pay = int(config["shift_owner"])
            worker = self.connection.execute(
                """SELECT o.slave_id, u.last_seen
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   WHERE o.chat_id=? AND o.slave_id=?""",
                (chat_id, worker_id),
            ).fetchone()
            inactive_slave = bool(
                worker
                and (
                    worker["last_seen"] is None
                    or now > int(worker["last_seen"]) + BUSINESS_ACTIVE_SECONDS
                )
            )
            if inactive_slave:
                worker_pay = 0
            else:
                worker_pay = self._credit_labor_income_locked(
                    chat_id, worker_id, worker_pay, now
                )
            self._add_francs_locked(chat_id, owner_id, owner_pay)
            cooldown_until = now + BUSINESS_HOUR_SECONDS
            self.connection.execute(
                """INSERT INTO business_shift_cooldowns(chat_id, worker_id, cooldown_until)
                   VALUES (?, ?, ?)
                   ON CONFLICT(chat_id, worker_id) DO UPDATE SET
                       cooldown_until=excluded.cooldown_until""",
                (chat_id, worker_id, cooldown_until),
            )
            self.connection.commit()
            return (
                "inactive_slave" if inactive_slave else "worked",
                worker_pay,
                owner_pay,
                cooldown_until,
            )

    async def buyout_slave(self, chat_id: int, owner_id: int, slave_id: int) -> str:
        async with self._lock:
            owned = self.connection.execute(
                """SELECT 1 FROM ownership
                   WHERE chat_id=? AND owner_id=? AND slave_id=?""",
                (chat_id, owner_id, slave_id),
            ).fetchone()
            if owned is None:
                return "not_owned"
            balance = self.connection.execute(
                "SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?",
                (chat_id, slave_id),
            ).fetchone()
            if not balance or int(balance["balance"]) < BUYOUT_COST_FRANCS:
                return "insufficient"
            now = utc_timestamp()
            self.connection.execute(
                """UPDATE franc_balances SET balance=balance-?, updated_at=?
                   WHERE chat_id=? AND user_id=?""",
                (BUYOUT_COST_FRANCS, now, chat_id, slave_id),
            )
            self.connection.execute(
                "DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?",
                (chat_id, owner_id, slave_id),
            )
            self.connection.execute(
                """DELETE FROM business_workers
                   WHERE chat_id=? AND owner_id=? AND worker_id=?""",
                (chat_id, owner_id, slave_id),
            )
            self.connection.commit()
            return "released"

    async def add_basement_member(
        self, chat_id: int, user_id: int, added_by: int
    ) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                """INSERT INTO basement_members(chat_id, user_id, added_by, added_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(chat_id, user_id) DO NOTHING""",
                (chat_id, user_id, added_by, utc_timestamp()),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def remove_basement_member(self, chat_id: int, user_id: int) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM basement_members WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def escape_basement_with_cooldown(
        self, chat_id: int, user_id: int
    ) -> tuple[str, int | None]:
        now = utc_timestamp()
        async with self._lock:
            member = self.connection.execute(
                "SELECT 1 FROM basement_members WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            if member is None:
                return "not_member", None
            cooldown = self.connection.execute(
                """SELECT cooldown_until FROM basement_escape_cooldowns
                   WHERE chat_id=? AND user_id=?""",
                (chat_id, user_id),
            ).fetchone()
            if cooldown and int(cooldown["cooldown_until"]) > now:
                return "cooldown", int(cooldown["cooldown_until"])
            cooldown_until = now + BASEMENT_ESCAPE_COOLDOWN_SECONDS
            self.connection.execute(
                "DELETE FROM basement_members WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            self.connection.execute(
                """INSERT INTO basement_escape_cooldowns(
                       chat_id, user_id, cooldown_until
                   ) VALUES (?, ?, ?)
                   ON CONFLICT(chat_id, user_id) DO UPDATE SET
                       cooldown_until=excluded.cooldown_until""",
                (chat_id, user_id, cooldown_until),
            )
            self.connection.commit()
            return "escaped", cooldown_until

    async def is_basement_member(self, chat_id: int, user_id: int) -> bool:
        async with self._lock:
            row = self.connection.execute(
                "SELECT 1 FROM basement_members WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            return row is not None

    async def basement_member_rank(self, chat_id: int, user_id: int) -> int | None:
        async with self._lock:
            row = self.connection.execute(
                """SELECT rank FROM basement_members
                   WHERE chat_id=? AND user_id=?""",
                (chat_id, user_id),
            ).fetchone()
            return int(row["rank"]) if row else None

    async def change_basement_rank(
        self, chat_id: int, user_id: int, amount: int
    ) -> tuple[int, int] | None:
        """Change a resident rank, clamped between miner (1) and deputy (4)."""
        async with self._lock:
            row = self.connection.execute(
                """SELECT rank FROM basement_members
                   WHERE chat_id=? AND user_id=?""",
                (chat_id, user_id),
            ).fetchone()
            if row is None:
                return None
            previous = int(row["rank"])
            updated = max(1, min(4, previous + amount))
            if updated != previous:
                self.connection.execute(
                    """UPDATE basement_members SET rank=?
                       WHERE chat_id=? AND user_id=?""",
                    (updated, chat_id, user_id),
                )
                self.connection.commit()
            return previous, updated

    async def list_basement_members(self, chat_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT b.user_id, b.added_at, b.rank, u.username, u.display_name
                   FROM basement_members b
                   LEFT JOIN users u ON u.chat_id=b.chat_id AND u.user_id=b.user_id
                   WHERE b.chat_id=? ORDER BY b.rank, b.added_at, b.user_id""",
                (chat_id,),
            ).fetchall()

    async def list_slaves(self, chat_id: int, owner_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT u.*, o.transfer_priority FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   WHERE o.chat_id=? AND o.owner_id=? ORDER BY o.acquired_at DESC""",
                (chat_id, owner_id),
            ).fetchall()

    async def list_slaves_globally(self, owner_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT u.*, o.chat_id AS ownership_chat_id, c.title AS chat_title,
                          o.transfer_priority
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.slave_id
                   LEFT JOIN chats c ON c.chat_id=o.chat_id
                   WHERE o.owner_id=? ORDER BY o.chat_id, o.acquired_at DESC""",
                (owner_id,),
            ).fetchall()

    async def list_owners_globally(self, slave_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT o.*, c.title AS chat_title, u.username, u.display_name
                   FROM ownership o
                   LEFT JOIN users u ON u.chat_id=o.chat_id AND u.user_id=o.owner_id
                   LEFT JOIN chats c ON c.chat_id=o.chat_id
                   WHERE o.slave_id=? ORDER BY o.chat_id, o.acquired_at DESC""",
                (slave_id,),
            ).fetchall()

    async def game_stats_for_user(self, user_id: int) -> sqlite3.Row:
        """Return a compact cross-chat summary of a user's recorded mini-games."""
        async with self._lock:
            return self.connection.execute(
                """SELECT
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN status='finished' THEN 1 ELSE 0 END) AS finished,
                       SUM(CASE WHEN result_recorded=1 AND winner_id=? THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result_recorded=1 AND winner_id IS NOT NULL
                                AND winner_id<>? THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN result_recorded=1 AND winner_id IS NULL THEN 1 ELSE 0 END) AS draws,
                       SUM(CASE WHEN game_type='rps' THEN 1 ELSE 0 END) AS rps,
                       SUM(CASE WHEN game_type='blackjack' THEN 1 ELSE 0 END) AS blackjack,
                       SUM(CASE WHEN game_type='checkers' THEN 1 ELSE 0 END) AS checkers
                   FROM challenges
                   WHERE challenger_id=? OR opponent_id=?""",
                (user_id, user_id, user_id, user_id),
            ).fetchone()

    async def set_slave_priority(
        self, chat_id: int, owner_id: int, slave_id: int, enabled: bool
    ) -> str:
        async with self._lock:
            row = self.connection.execute(
                """SELECT transfer_priority FROM ownership
                   WHERE chat_id=? AND owner_id=? AND slave_id=?""",
                (chat_id, owner_id, slave_id),
            ).fetchone()
            if row is None:
                return "not_owned"
            value = int(enabled)
            if int(row["transfer_priority"]) == value:
                return "unchanged"
            self.connection.execute(
                """UPDATE ownership SET transfer_priority=?
                   WHERE chat_id=? AND owner_id=? AND slave_id=?""",
                (value, chat_id, owner_id, slave_id),
            )
            self.connection.commit()
            return "updated"

    async def release_slave(self, chat_id: int, owner_id: int, slave_id: int) -> bool:
        async with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?",
                (chat_id, owner_id, slave_id),
            )
            if cursor.rowcount:
                self.connection.execute(
                    """DELETE FROM business_workers
                       WHERE chat_id=? AND owner_id=? AND worker_id=?""",
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

    async def create_death_note_entry(
        self, chat_id: int, target_id: int, author_id: int, deadline: int
    ) -> int | None:
        async with self._lock:
            existing = self.connection.execute(
                """SELECT id FROM death_note_entries
                   WHERE chat_id=? AND target_id=? AND status='pending'""",
                (chat_id, target_id),
            ).fetchone()
            if existing:
                return None
            cursor = self.connection.execute(
                """INSERT INTO death_note_entries(
                       chat_id, target_id, author_id, deadline, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (chat_id, target_id, author_id, deadline, utc_timestamp()),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    async def set_death_note_message(self, entry_id: int, message_id: int) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE death_note_entries SET message_id=? WHERE id=?",
                (message_id, entry_id),
            )
            self.connection.commit()

    async def get_death_note_entry(self, entry_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM death_note_entries WHERE id=?", (entry_id,)
            ).fetchone()

    async def pending_death_note_entries(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM death_note_entries
                   WHERE status IN ('pending', 'enforcing') ORDER BY deadline"""
            ).fetchall()

    async def claim_expired_death_note_entry(
        self, entry_id: int
    ) -> sqlite3.Row | None:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM death_note_entries
                   WHERE id=? AND status='pending' AND deadline<=?""",
                (entry_id, now),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE death_note_entries SET status='enforcing' WHERE id=?",
                (entry_id,),
            )
            self.connection.commit()
            return row

    async def cancel_death_note_by_target(
        self, chat_id: int, target_id: int
    ) -> sqlite3.Row | None:
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM death_note_entries
                   WHERE chat_id=? AND target_id=? AND status='pending'""",
                (chat_id, target_id),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE death_note_entries SET status='cancelled' WHERE id=?",
                (int(row["id"]),),
            )
            self.connection.commit()
            return row

    async def cancel_death_note_by_message(
        self, chat_id: int, message_id: int
    ) -> sqlite3.Row | None:
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM death_note_entries
                   WHERE chat_id=? AND message_id=? AND status='pending'""",
                (chat_id, message_id),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE death_note_entries SET status='cancelled' WHERE id=?",
                (int(row["id"]),),
            )
            self.connection.commit()
            return row

    async def finish_death_note_entry(self, entry_id: int, status: str) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE death_note_entries SET status=? WHERE id=?",
                (status, entry_id),
            )
            self.connection.commit()

    async def take_random_phrase(
        self, chat_id: int, phrases: list[str] | tuple[str, ...]
    ) -> str:
        """Return a shuffled phrase without repeating it until the bag is empty."""
        pool = list(dict.fromkeys(phrases))
        if not pool:
            raise ValueError("Random phrase pool cannot be empty")
        async with self._lock:
            row = self.connection.execute(
                "SELECT remaining_json FROM random_phrase_bags WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
            remaining: list[str] = []
            if row:
                try:
                    saved = json.loads(row["remaining_json"])
                    if isinstance(saved, list):
                        remaining = [phrase for phrase in saved if phrase in pool]
                except (TypeError, ValueError, json.JSONDecodeError):
                    remaining = []
            if not remaining:
                remaining = pool.copy()
                random.shuffle(remaining)
            phrase = remaining.pop()
            self.connection.execute(
                """INSERT INTO random_phrase_bags(chat_id, remaining_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       remaining_json=excluded.remaining_json,
                       updated_at=excluded.updated_at""",
                (chat_id, json.dumps(remaining, ensure_ascii=False), utc_timestamp()),
            )
            self.connection.commit()
            return phrase

    async def get_or_create_random_message_schedule(
        self, chat_id: int, service_day: str, scheduled_times: list[int]
    ) -> list[sqlite3.Row]:
        async with self._lock:
            rows = self.connection.execute(
                """SELECT * FROM random_message_schedules
                   WHERE chat_id=? AND service_day=? ORDER BY scheduled_at""",
                (chat_id, service_day),
            ).fetchall()
            if rows:
                return rows
            self.connection.executemany(
                """INSERT INTO random_message_schedules(
                       chat_id, service_day, scheduled_at
                   ) VALUES (?, ?, ?)""",
                [(chat_id, service_day, scheduled_at) for scheduled_at in scheduled_times],
            )
            self.connection.commit()
            return self.connection.execute(
                """SELECT * FROM random_message_schedules
                   WHERE chat_id=? AND service_day=? ORDER BY scheduled_at""",
                (chat_id, service_day),
            ).fetchall()

    async def skip_expired_random_messages(
        self, chat_id: int, service_day: str, before: int
    ) -> None:
        async with self._lock:
            self.connection.execute(
                """UPDATE random_message_schedules SET status='skipped'
                   WHERE chat_id=? AND service_day=? AND status='pending'
                     AND scheduled_at<?""",
                (chat_id, service_day, before),
            )
            self.connection.commit()

    async def next_pending_random_message(
        self, chat_id: int, service_day: str
    ) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM random_message_schedules
                   WHERE chat_id=? AND service_day=? AND status='pending'
                   ORDER BY scheduled_at LIMIT 1""",
                (chat_id, service_day),
            ).fetchone()

    async def claim_random_message(self, schedule_id: int) -> sqlite3.Row | None:
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM random_message_schedules
                   WHERE id=? AND status='pending'""",
                (schedule_id,),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE random_message_schedules SET status='sending' WHERE id=?",
                (schedule_id,),
            )
            self.connection.commit()
            return row

    async def finish_random_message(self, schedule_id: int, status: str) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE random_message_schedules SET status=? WHERE id=?",
                (status, schedule_id),
            )
            self.connection.commit()

    async def create_captcha(
        self, chat_id: int, user_id: int, correct_emoji: str, deadline: int
    ) -> int:
        async with self._lock:
            self.connection.execute(
                """UPDATE captchas SET status='replaced'
                   WHERE chat_id=? AND user_id=? AND status='pending'""",
                (chat_id, user_id),
            )
            cursor = self.connection.execute(
                """INSERT INTO captchas(
                       chat_id, user_id, correct_emoji, deadline, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (chat_id, user_id, correct_emoji, deadline, utc_timestamp()),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    async def set_captcha_message(self, captcha_id: int, message_id: int) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE captchas SET message_id=? WHERE id=?", (message_id, captcha_id)
            )
            self.connection.commit()

    async def set_captcha_join_message(
        self, captcha_id: int, message_id: int
    ) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE captchas SET join_message_id=? WHERE id=?",
                (message_id, captcha_id),
            )
            self.connection.commit()

    async def get_captcha(self, captcha_id: int) -> sqlite3.Row | None:
        async with self._lock:
            return self.connection.execute(
                "SELECT * FROM captchas WHERE id=?", (captcha_id,)
            ).fetchone()

    async def pending_captchas(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM captchas
                   WHERE status IN ('pending', 'enforcing') ORDER BY deadline"""
            ).fetchall()

    async def claim_expired_captcha(self, captcha_id: int) -> sqlite3.Row | None:
        now = utc_timestamp()
        async with self._lock:
            row = self.connection.execute(
                """SELECT * FROM captchas
                   WHERE id=? AND status='pending' AND deadline <= ?""",
                (captcha_id, now),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE captchas SET status='enforcing' WHERE id=?", (captcha_id,)
            )
            self.connection.commit()
            return row

    async def submit_captcha(
        self, captcha_id: int, user_id: int, emoji: str, max_attempts: int
    ) -> tuple[str, int]:
        """Return passed, retry, failed, expired, inactive, or not_owner."""
        async with self._lock:
            row = self.connection.execute(
                "SELECT * FROM captchas WHERE id=?", (captcha_id,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                return "inactive", 0
            if int(row["user_id"]) != user_id:
                return "not_owner", 0
            if int(row["deadline"]) < utc_timestamp():
                return "expired", 0
            if emoji == row["correct_emoji"]:
                self.connection.execute(
                    "UPDATE captchas SET status='passed' WHERE id=?", (captcha_id,)
                )
                self.connection.commit()
                return "passed", max_attempts - int(row["attempts"])
            attempts = int(row["attempts"]) + 1
            if attempts >= max_attempts:
                status = "failed"
                remaining = 0
            else:
                status = "pending"
                remaining = max_attempts - attempts
            self.connection.execute(
                "UPDATE captchas SET attempts=?, status=? WHERE id=?",
                (attempts, status, captcha_id),
            )
            self.connection.commit()
            return ("failed" if status == "failed" else "retry"), remaining

    async def finish_captcha(self, captcha_id: int, status: str) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE captchas SET status=? WHERE id=?", (status, captcha_id)
            )
            self.connection.commit()
