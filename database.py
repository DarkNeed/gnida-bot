from __future__ import annotations

import asyncio
import json
import random
import secrets
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
from slave_battle import (
    BUILTIN_SKILLS,
    CLASS_SELECTION_LEVEL,
    FIGHTER_CLASSES,
    SKILL_DELEGATION_SECONDS,
    VISIBLE_CLASS_ALIASES,
    create_battle_state,
    fighter_class_from_dict,
    level_from_total_xp,
    normalize_loadout,
    resolve_turn,
    skill_from_dict,
    unlocked_skill_ids,
    use_healing_potion,
    validate_action,
)


CHALLENGE_DEADLINE_SECONDS = 3 * 60 * 60
NEWCOMER_CHALLENGE_DEADLINE_SECONDS = 5 * 60
FORCE_OWNER_COOLDOWN_SECONDS = 7 * 24 * 60 * 60
PIROJOK_USERNAME = "pirojoksostajem"
JUG_HIDING_SECONDS = 5 * 60
JUG_COOLDOWN_SECONDS = 60 * 60
BASEMENT_ESCAPE_COOLDOWN_SECONDS = 60 * 60
SLAVE_WIN_XP = 10
SLAVE_DRAW_XP = 8
SLAVE_LOSS_XP = 7
OWNER_WIN_XP = 6
OWNER_RECORD_XP = 2
FULL_XP_PAIR_BATTLES_PER_DAY = 3
SLAVE_BATTLE_DEADLINE_SECONDS = 24 * 60 * 60
SLAVE_BATTLE_TURN_SECONDS = 3 * 60 * 60
WASTELAND_BASE_XP = 5
WASTELAND_FLOOR_XP = 2


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

            CREATE TABLE IF NOT EXISTS slave_battles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                challenger_owner_id INTEGER NOT NULL,
                defender_owner_id INTEGER NOT NULL,
                challenger_slave_id INTEGER NOT NULL,
                defender_slave_id INTEGER NOT NULL,
                challenger_owner_accepted INTEGER NOT NULL DEFAULT 1,
                defender_owner_accepted INTEGER NOT NULL DEFAULT 0,
                challenger_slave_accepted INTEGER NOT NULL DEFAULT 0,
                defender_slave_accepted INTEGER NOT NULL DEFAULT 0,
                challenger_control INTEGER NOT NULL DEFAULT 0,
                defender_control INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                state_json TEXT,
                winner_slave_id INTEGER,
                created_at INTEGER NOT NULL,
                deadline INTEGER NOT NULL,
                finished_at INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_slave_battles_status
                ON slave_battles(chat_id, status, deadline);

            CREATE TABLE IF NOT EXISTS wasteland_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                slave_id INTEGER NOT NULL,
                floor INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                state_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                finished_at INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_wasteland_runs_active
                ON wasteland_runs(chat_id, owner_id, slave_id, status);

            CREATE TABLE IF NOT EXISTS slave_battle_actions (
                battle_id INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                side TEXT NOT NULL,
                actor_id INTEGER NOT NULL,
                action_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (battle_id, turn, side)
            );

            CREATE TABLE IF NOT EXISTS slave_battle_pair_rewards (
                chat_id INTEGER NOT NULL,
                first_slave_id INTEGER NOT NULL,
                second_slave_id INTEGER NOT NULL,
                day_key TEXT NOT NULL,
                battle_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, first_slave_id, second_slave_id, day_key)
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

            CREATE TABLE IF NOT EXISTS counters (
                chat_id INTEGER NOT NULL,
                counter_key TEXT NOT NULL,
                value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, counter_key)
            );

            CREATE TABLE IF NOT EXISTS basement_members (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER NOT NULL,
                added_at INTEGER NOT NULL,
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
        self._ensure_column(
            "ownership", "transfer_priority", "INTEGER NOT NULL DEFAULT 0"
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
    ) -> int | None:
        if game_type not in {"rps", "blackjack", "checkers"}:
            raise ValueError("Unknown challenge game type")
        if friendly:
            forced = False
            opponent_newcomer = False
        async with self._lock:
            existing = self.connection.execute(
                """SELECT id FROM challenges WHERE chat_id=? AND status='active'
                   AND (challenger_id IN (?, ?) OR opponent_id IN (?, ?))""",
                (chat_id, challenger_id, opponent_id, challenger_id, opponent_id),
            ).fetchone()
            if existing:
                return None
            now = utc_timestamp()
            cursor = self.connection.execute(
                """INSERT INTO challenges(
                       chat_id, challenger_id, opponent_id, forced,
                       opponent_newcomer, game_type, friendly, created_at, deadline
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chat_id,
                    challenger_id,
                    opponent_id,
                    int(forced),
                    int(opponent_newcomer),
                    game_type,
                    int(friendly),
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
                    "UPDATE challenges SET status='finished' WHERE id=?",
                    (challenge_id,),
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
                    "UPDATE challenges SET status='finished' WHERE id=?",
                    (challenge_id,),
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
        if table not in {"slave_profiles", "owner_profiles"}:
            raise ValueError("Unknown profile table")
        if table == "slave_profiles":
            before = self._ensure_slave_profile_locked(chat_id, user_id)
        else:
            before = self._ensure_owner_profile_locked(chat_id, user_id)
        old_level = int(before["level"])
        total_xp = int(before["xp"]) + max(0, amount)
        new_level = level_from_total_xp(total_xp)
        extra = ", updated_at=?" if table == "slave_profiles" else ""
        params: tuple[Any, ...]
        if table == "slave_profiles":
            params = (total_xp, new_level, utc_timestamp(), chat_id, user_id)
        else:
            params = (total_xp, new_level, chat_id, user_id)
        self.connection.execute(
            f"UPDATE {table} SET xp=?, level=?{extra} WHERE chat_id=? AND user_id=?",
            params,
        )
        if table == "slave_profiles" and old_level < CLASS_SELECTION_LEVEL <= new_level:
            self.connection.execute(
                """UPDATE slave_profiles
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
        return self._slave_count_locked(chat_id, owner_id) < self._owner_capacity_for_level(
            int(profile["level"])
        )

    def _settle_materials_locked(self, chat_id: int, owner_id: int) -> sqlite3.Row:
        profile = self._ensure_owner_profile_locked(chat_id, owner_id)
        now = utc_timestamp()
        level = int(profile["level"])
        elapsed = max(0, now - int(profile["material_updated_at"]))
        fraction = float(profile["material_fraction"])
        raw = int(profile["raw_material"])
        if level >= 5 and elapsed:
            produced = fraction + elapsed * self._slave_count_locked(chat_id, owner_id) / 3600
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
                skill = skill_from_dict(str(row["skill_id"]), json.loads(row["definition_json"]))
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
        if not content_id or len(content_id) > 48 or not content_id.replace("_", "").isalnum():
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
            self.connection.execute(
                """INSERT INTO granted_fighter_content(
                       chat_id, user_id, content_type, content_id, granted_by, granted_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id, user_id, content_type, content_id) DO NOTHING""",
                (chat_id, user_id, content_type, content_id, granted_by, utc_timestamp()),
            )
            self.connection.commit()
            return "granted"

    async def get_fighter_catalog(self) -> tuple[dict[str, Any], dict[str, Any]]:
        async with self._lock:
            return self._fighter_catalog_locked()

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
                "material_capacity": self._material_capacity_for_level(int(profile["level"])),
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
            return {"old_level": old_level, "new_level": new_level, "xp": int(row["xp"])}

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
            return {"old_level": old_level, "new_level": new_level, "xp": int(row["xp"])}

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
            granted_skills = self._granted_content_locked(chat_id, user_id, "skill")
            loadout = normalize_loadout(
                class_id, int(profile["level"]), None, skills, granted_skills
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
                if pending_at is None or utc_timestamp() < int(pending_at) + SKILL_DELEGATION_SECONDS:
                    return "too_early"
            _classes, skills = self._fighter_catalog_locked()
            granted_skills = self._granted_content_locked(chat_id, slave_id, "skill")
            normalized = normalize_loadout(
                str(profile["class_id"]),
                int(profile["level"]),
                skill_ids,
                skills,
                granted_skills,
            )
            self.connection.execute(
                """UPDATE slave_profiles SET loadout=?, skills_pending_at=NULL, updated_at=?
                   WHERE chat_id=? AND user_id=?""",
                (json.dumps(normalized), utc_timestamp(), chat_id, slave_id),
            )
            self.connection.commit()
            return "updated"

    async def craft_owner_item(self, chat_id: int, owner_id: int, item: str) -> str:
        recipes = {
            "potion": (5, 50, "healing_potions"),
            "candy": (7, 100, "candies"),
        }
        if item not in recipes:
            return "unknown"
        required_level, cost, column = recipes[item]
        async with self._lock:
            profile = self._settle_materials_locked(chat_id, owner_id)
            if int(profile["level"]) < required_level:
                self.connection.commit()
                return "low_level"
            if int(profile["raw_material"]) < cost:
                self.connection.commit()
                return "not_enough_material"
            self.connection.execute(
                f"""UPDATE owner_profiles
                    SET raw_material=raw_material-?, {column}={column}+1
                    WHERE chat_id=? AND user_id=?""",
                (cost, chat_id, owner_id),
            )
            self.connection.commit()
            return "crafted"

    async def give_candy(self, chat_id: int, owner_id: int, slave_id: int) -> str:
        async with self._lock:
            owned = self.connection.execute(
                "SELECT 1 FROM ownership WHERE chat_id=? AND owner_id=? AND slave_id=?",
                (chat_id, owner_id, slave_id),
            ).fetchone()
            if not owned:
                return "not_owned"
            profile = self._ensure_owner_profile_locked(chat_id, owner_id)
            if int(profile["candies"]) < 1:
                self.connection.commit()
                return "no_candy"
            self.connection.execute(
                """UPDATE owner_profiles SET candies=candies-1
                   WHERE chat_id=? AND user_id=?""",
                (chat_id, owner_id),
            )
            self._grant_profile_xp_locked("slave_profiles", chat_id, slave_id, 30)
            self.connection.commit()
            return "given"

    def _battle_side_for_user(self, battle: sqlite3.Row, user_id: int) -> str | None:
        if user_id in {
            int(battle["challenger_owner_id"]),
            int(battle["challenger_slave_id"]),
        }:
            return "a"
        if user_id in {
            int(battle["defender_owner_id"]),
            int(battle["defender_slave_id"]),
        }:
            return "b"
        return None

    def _try_activate_slave_battle_locked(self, battle_id: int) -> sqlite3.Row:
        battle = self.connection.execute(
            "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
        ).fetchone()
        if not battle or battle["status"] != "pending":
            return battle
        first_ready = bool(battle["challenger_control"] or battle["challenger_slave_accepted"])
        second_ready = bool(battle["defender_control"] or battle["defender_slave_accepted"])
        if not (
            battle["challenger_owner_accepted"]
            and battle["defender_owner_accepted"]
            and first_ready
            and second_ready
        ):
            return battle
        first_profile = self._ensure_slave_profile_locked(
            int(battle["chat_id"]), int(battle["challenger_slave_id"])
        )
        second_profile = self._ensure_slave_profile_locked(
            int(battle["chat_id"]), int(battle["defender_slave_id"])
        )
        classes, skills = self._fighter_catalog_locked()
        first_granted_skills = self._granted_content_locked(
            int(battle["chat_id"]), int(battle["challenger_slave_id"]), "skill"
        )
        second_granted_skills = self._granted_content_locked(
            int(battle["chat_id"]), int(battle["defender_slave_id"]), "skill"
        )
        state = create_battle_state(
            {
                "slave_id": battle["challenger_slave_id"],
                "owner_id": battle["challenger_owner_id"],
                "controlled": bool(battle["challenger_control"]),
                "class_id": first_profile["class_id"],
                "level": first_profile["level"],
                "loadout": json.loads(first_profile["loadout"]),
                "granted_skills": first_granted_skills,
            },
            {
                "slave_id": battle["defender_slave_id"],
                "owner_id": battle["defender_owner_id"],
                "controlled": bool(battle["defender_control"]),
                "class_id": second_profile["class_id"],
                "level": second_profile["level"],
                "loadout": json.loads(second_profile["loadout"]),
                "granted_skills": second_granted_skills,
            },
            classes=classes,
            skills=skills,
        )
        self.connection.execute(
            """UPDATE slave_battles SET status='active', state_json=?, deadline=?
               WHERE id=? AND status='pending'""",
            (json.dumps(state), utc_timestamp() + SLAVE_BATTLE_TURN_SECONDS, battle_id),
        )
        return self.connection.execute(
            "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
        ).fetchone()

    async def create_slave_battle(
        self,
        chat_id: int,
        challenger_owner_id: int,
        challenger_slave_id: int,
        defender_slave_id: int,
        *,
        initiated_by_slave: bool = False,
    ) -> tuple[str, int | None]:
        async with self._lock:
            challenger_ownership = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, challenger_slave_id),
            ).fetchone()
            defender_ownership = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, defender_slave_id),
            ).fetchone()
            if not challenger_ownership or int(challenger_ownership["owner_id"]) != challenger_owner_id:
                return "challenger_not_owned", None
            if not defender_ownership:
                return "defender_not_slave", None
            if challenger_slave_id == defender_slave_id:
                return "same_slave", None
            active = self.connection.execute(
                """SELECT id FROM slave_battles
                   WHERE chat_id=? AND status IN ('pending', 'active')
                     AND (challenger_slave_id IN (?, ?) OR defender_slave_id IN (?, ?))""",
                (
                    chat_id,
                    challenger_slave_id,
                    defender_slave_id,
                    challenger_slave_id,
                    defender_slave_id,
                ),
            ).fetchone()
            if active:
                return "busy", None
            first_profile = self._ensure_slave_profile_locked(chat_id, challenger_slave_id)
            second_profile = self._ensure_slave_profile_locked(chat_id, defender_slave_id)
            if (
                int(first_profile["level"]) >= CLASS_SELECTION_LEVEL
                and first_profile["class_id"] == "ragamuffin"
            ) or (
                int(second_profile["level"]) >= CLASS_SELECTION_LEVEL
                and second_profile["class_id"] == "ragamuffin"
            ):
                self.connection.commit()
                return "class_required", None
            defender_owner_id = int(defender_ownership["owner_id"])
            now = utc_timestamp()
            cursor = self.connection.execute(
                """INSERT INTO slave_battles(
                       token, chat_id, challenger_owner_id, defender_owner_id,
                       challenger_slave_id, defender_slave_id,
                       challenger_slave_accepted, defender_owner_accepted,
                       created_at, deadline
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    secrets.token_urlsafe(18),
                    chat_id,
                    challenger_owner_id,
                    defender_owner_id,
                    challenger_slave_id,
                    defender_slave_id,
                    int(initiated_by_slave),
                    int(defender_owner_id == challenger_owner_id),
                    now,
                    now + SLAVE_BATTLE_DEADLINE_SECONDS,
                ),
            )
            self.connection.commit()
            return "created", int(cursor.lastrowid)

    async def set_slave_battle_message(self, battle_id: int, message_id: int) -> None:
        async with self._lock:
            self.connection.execute(
                "UPDATE slave_battles SET message_id=? WHERE id=?",
                (message_id, battle_id),
            )
            self.connection.commit()

    async def get_slave_battle(
        self, battle_id: int | None = None, token: str | None = None
    ) -> sqlite3.Row | None:
        if battle_id is None and token is None:
            return None
        async with self._lock:
            if battle_id is not None:
                return self.connection.execute(
                    "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
                ).fetchone()
            return self.connection.execute(
                "SELECT * FROM slave_battles WHERE token=?", (token,)
            ).fetchone()

    async def pending_slave_battles(self) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT * FROM slave_battles
                   WHERE status IN ('pending', 'active') ORDER BY deadline"""
            ).fetchall()

    async def expire_slave_battle(self, battle_id: int) -> sqlite3.Row | None:
        """Close a timed-out lobby or award a technical win for a timed-out turn."""
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] not in {"pending", "active"}:
                return None
            if int(battle["deadline"]) > utc_timestamp():
                return battle
            if battle["status"] == "pending":
                self.connection.execute(
                    "UPDATE slave_battles SET status='expired', finished_at=? WHERE id=?",
                    (utc_timestamp(), battle_id),
                )
            else:
                state = json.loads(battle["state_json"])
                rows = self.connection.execute(
                    """SELECT side FROM slave_battle_actions
                       WHERE battle_id=? AND turn=?""",
                    (battle_id, int(state["turn"])),
                ).fetchall()
                acted = {str(row["side"]) for row in rows}
                if acted == {"a"}:
                    winner = "a"
                elif acted == {"b"}:
                    winner = "b"
                else:
                    winner = "draw"
                state["winner"] = winner
                state["finished"] = True
                winner_id = None if winner == "draw" else int(state["sides"][winner]["slave_id"])
                self.connection.execute(
                    """UPDATE slave_battles SET status='finished', state_json=?,
                           winner_slave_id=?, finished_at=? WHERE id=?""",
                    (json.dumps(state), winner_id, utc_timestamp(), battle_id),
                )
                self._reward_finished_slave_battle_locked(battle, state)
            self.connection.commit()
            return self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()

    async def accept_slave_battle_owner(self, battle_id: int, user_id: int) -> str:
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] != "pending":
                return "inactive"
            if user_id not in {
                int(battle["challenger_owner_id"]),
                int(battle["defender_owner_id"]),
            }:
                return "forbidden"
            column = (
                "challenger_owner_accepted"
                if user_id == int(battle["challenger_owner_id"])
                else "defender_owner_accepted"
            )
            self.connection.execute(
                f"UPDATE slave_battles SET {column}=1 WHERE id=?", (battle_id,)
            )
            updated = self._try_activate_slave_battle_locked(battle_id)
            self.connection.commit()
            return str(updated["status"])

    async def set_slave_battle_control(
        self,
        battle_id: int,
        owner_id: int,
        enabled: bool = True,
        side: str | None = None,
    ) -> str:
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] != "pending":
                return "inactive"
            if side == "a" and owner_id == int(battle["challenger_owner_id"]):
                column = "challenger_control"
            elif side == "b" and owner_id == int(battle["defender_owner_id"]):
                column = "defender_control"
            elif side is None and owner_id == int(battle["challenger_owner_id"]):
                column = "challenger_control"
            elif side is None and owner_id == int(battle["defender_owner_id"]):
                column = "defender_control"
            else:
                return "forbidden"
            self._ensure_owner_profile_locked(int(battle["chat_id"]), owner_id)
            self.connection.execute(
                f"UPDATE slave_battles SET {column}=? WHERE id=?",
                (int(enabled), battle_id),
            )
            updated = self._try_activate_slave_battle_locked(battle_id)
            self.connection.commit()
            return str(updated["status"])

    async def accept_slave_battle_slave(self, battle_id: int, user_id: int) -> str:
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] != "pending":
                return "inactive"
            if user_id == int(battle["challenger_slave_id"]):
                column = "challenger_slave_accepted"
            elif user_id == int(battle["defender_slave_id"]):
                column = "defender_slave_accepted"
            else:
                return "forbidden"
            self.connection.execute(
                f"UPDATE slave_battles SET {column}=1 WHERE id=?", (battle_id,)
            )
            updated = self._try_activate_slave_battle_locked(battle_id)
            self.connection.commit()
            return str(updated["status"])

    async def refuse_slave_battle(self, battle_id: int, user_id: int) -> bool:
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] != "pending":
                return False
            if self._battle_side_for_user(battle, user_id) is None:
                return False
            cursor = self.connection.execute(
                "UPDATE slave_battles SET status='refused', finished_at=? WHERE id=? AND status='pending'",
                (utc_timestamp(), battle_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def _reward_finished_slave_battle_locked(
        self, battle: sqlite3.Row, state: dict[str, Any]
    ) -> None:
        first = min(int(battle["challenger_slave_id"]), int(battle["defender_slave_id"]))
        second = max(int(battle["challenger_slave_id"]), int(battle["defender_slave_id"]))
        day_key = (datetime.now(timezone.utc) + timedelta(hours=3)).date().isoformat()
        reward = self.connection.execute(
            """SELECT battle_count FROM slave_battle_pair_rewards
               WHERE chat_id=? AND first_slave_id=? AND second_slave_id=? AND day_key=?""",
            (battle["chat_id"], first, second, day_key),
        ).fetchone()
        count = int(reward["battle_count"]) + 1 if reward else 1
        self.connection.execute(
            """INSERT INTO slave_battle_pair_rewards(
                   chat_id, first_slave_id, second_slave_id, day_key, battle_count
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(chat_id, first_slave_id, second_slave_id, day_key)
               DO UPDATE SET battle_count=excluded.battle_count""",
            (battle["chat_id"], first, second, day_key, count),
        )
        if count > FULL_XP_PAIR_BATTLES_PER_DAY:
            for slave_id in (battle["challenger_slave_id"], battle["defender_slave_id"]):
                self._grant_profile_xp_locked(
                    "slave_profiles", int(battle["chat_id"]), int(slave_id), 1
                )
            return
        winner_side = state.get("winner")
        if winner_side == "draw":
            for slave_id in (battle["challenger_slave_id"], battle["defender_slave_id"]):
                self._grant_profile_xp_locked(
                    "slave_profiles", int(battle["chat_id"]), int(slave_id), SLAVE_DRAW_XP
                )
            return
        loser_side = "b" if winner_side == "a" else "a"
        winner = state["sides"][winner_side]
        loser = state["sides"][loser_side]
        self._grant_profile_xp_locked(
            "slave_profiles", int(battle["chat_id"]), int(winner["slave_id"]), SLAVE_WIN_XP
        )
        self._grant_profile_xp_locked(
            "slave_profiles", int(battle["chat_id"]), int(loser["slave_id"]), SLAVE_LOSS_XP
        )
        self._grant_profile_xp_locked(
            "owner_profiles", int(battle["chat_id"]), int(winner["owner_id"]), OWNER_WIN_XP
        )

    async def submit_slave_battle_action(
        self, battle_id: int, actor_id: int, action: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] != "active" or not battle["state_json"]:
                return {"status": "inactive"}
            state = json.loads(battle["state_json"])
            allowed_sides = [
                side_name
                for side_name, fighter in state["sides"].items()
                if int(fighter["controller_id"]) == actor_id
            ]
            requested_side = action.get("side")
            if requested_side in allowed_sides:
                side = str(requested_side)
            elif len(allowed_sides) == 1:
                side = allowed_sides[0]
            elif not allowed_sides:
                return {"status": "forbidden"}
            else:
                return {"status": "choose_side"}
            try:
                _classes, skills = self._fighter_catalog_locked()
                validation_error = validate_action(state, side, action, skills)
            except (KeyError, TypeError, ValueError):
                validation_error = "Некорректное действие."
            if validation_error:
                return {"status": "invalid", "error": validation_error}
            turn = int(state["turn"])
            try:
                self.connection.execute(
                    """INSERT INTO slave_battle_actions(
                           battle_id, turn, side, actor_id, action_json, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (battle_id, turn, side, actor_id, json.dumps(action), utc_timestamp()),
                )
            except sqlite3.IntegrityError:
                return {"status": "already_acted"}
            rows = self.connection.execute(
                """SELECT side, action_json FROM slave_battle_actions
                   WHERE battle_id=? AND turn=?""",
                (battle_id, turn),
            ).fetchall()
            if len(rows) < 2:
                self.connection.commit()
                return {"status": "waiting", "state": state}
            actions = {str(row["side"]): json.loads(row["action_json"]) for row in rows}
            try:
                state = resolve_turn(state, actions, skills=skills)
            except ValueError as error:
                self.connection.execute(
                    "DELETE FROM slave_battle_actions WHERE battle_id=? AND turn=?",
                    (battle_id, turn),
                )
                self.connection.commit()
                return {"status": "invalid", "error": str(error)}
            if state["finished"]:
                winner_side = state.get("winner")
                winner_id = (
                    None
                    if winner_side == "draw"
                    else int(state["sides"][winner_side]["slave_id"])
                )
                self.connection.execute(
                    """UPDATE slave_battles SET status='finished', state_json=?,
                           winner_slave_id=?, finished_at=?, deadline=? WHERE id=?""",
                    (
                        json.dumps(state),
                        winner_id,
                        utc_timestamp(),
                        utc_timestamp(),
                        battle_id,
                    ),
                )
                self._reward_finished_slave_battle_locked(battle, state)
                status = "finished"
            else:
                self.connection.execute(
                    "UPDATE slave_battles SET state_json=?, deadline=? WHERE id=?",
                    (json.dumps(state), utc_timestamp() + SLAVE_BATTLE_TURN_SECONDS, battle_id),
                )
                status = "resolved"
            self.connection.commit()
            return {"status": status, "state": state}

    async def use_slave_battle_potion(
        self, battle_id: int, owner_id: int, side: str | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            battle = self.connection.execute(
                "SELECT * FROM slave_battles WHERE id=?", (battle_id,)
            ).fetchone()
            if not battle or battle["status"] != "active" or not battle["state_json"]:
                return {"status": "inactive"}
            state = json.loads(battle["state_json"])
            owner_sides = [
                side_name
                for side_name, fighter in state["sides"].items()
                if int(fighter["owner_id"]) == owner_id
            ]
            if side not in owner_sides:
                side = owner_sides[0] if len(owner_sides) == 1 else None
            if side is None:
                return {"status": "forbidden"}
            profile = self._ensure_owner_profile_locked(int(battle["chat_id"]), owner_id)
            if int(profile["healing_potions"]) < 1:
                self.connection.commit()
                return {"status": "no_potion"}
            try:
                healed = use_healing_potion(state, side)
            except ValueError as error:
                return {"status": "invalid", "error": str(error)}
            self.connection.execute(
                """UPDATE owner_profiles SET healing_potions=healing_potions-1
                   WHERE chat_id=? AND user_id=?""",
                (battle["chat_id"], owner_id),
            )
            self.connection.execute(
                "UPDATE slave_battles SET state_json=? WHERE id=?",
                (json.dumps(state), battle_id),
            )
            self.connection.commit()
            return {"status": "used", "healed": healed, "state": state}

    def _wasteland_state_locked(
        self, chat_id: int, owner_id: int, slave_id: int, floor: int
    ) -> tuple[str, dict[str, Any] | None]:
        ownership = self.connection.execute(
            "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
            (chat_id, slave_id),
        ).fetchone()
        if not ownership or int(ownership["owner_id"]) != owner_id:
            return "not_owned", None
        profile = self._ensure_slave_profile_locked(chat_id, slave_id)
        if int(profile["level"]) >= CLASS_SELECTION_LEVEL and profile["class_id"] == "ragamuffin":
            return "class_required", None
        classes, skills = self._fighter_catalog_locked()
        granted_skills = self._granted_content_locked(chat_id, slave_id, "skill")
        enemy_level = max(1, int(profile["level"]) + floor - 1)
        state = create_battle_state(
            {
                "slave_id": slave_id,
                "owner_id": owner_id,
                "controlled": False,
                "class_id": profile["class_id"],
                "level": profile["level"],
                "loadout": json.loads(profile["loadout"]),
                "granted_skills": granted_skills,
            },
            {
                "slave_id": 0,
                "owner_id": 0,
                "controlled": False,
                "class_id": "ragamuffin",
                "level": enemy_level,
            },
            classes=classes,
            skills=skills,
        )
        # The owner leads PvE without the -20% coercion penalty.
        state["sides"]["a"]["controller_id"] = owner_id
        state["wasteland"] = {"floor": floor, "enemy_level": enemy_level}
        return "ready", state

    def _wasteland_ai_action_locked(
        self, state: dict[str, Any], skills: dict[str, Any]
    ) -> dict[str, Any]:
        fighter = state["sides"]["b"]
        available = [
            skills[skill_id]
            for skill_id in fighter["loadout"]
            if skill_id in skills
            and fighter["resource"] >= skills[skill_id].cost
            and not fighter["cooldowns"].get(skill_id, 0)
        ]
        skill = random.choice(available)
        return {
            "skill_id": skill.skill_id,
            "attack_direction": random.choice(["left", "right"]) if skill.hostile else None,
            "dodge_direction": random.choice(["left", "right"]),
        }

    async def start_wasteland_run(
        self, chat_id: int, owner_id: int, slave_id: int
    ) -> tuple[str, sqlite3.Row | None]:
        async with self._lock:
            existing = self.connection.execute(
                """SELECT * FROM wasteland_runs WHERE chat_id=? AND owner_id=? AND slave_id=?
                   AND status IN ('active', 'victory') ORDER BY id DESC LIMIT 1""",
                (chat_id, owner_id, slave_id),
            ).fetchone()
            if existing:
                return "existing", existing
            state_status, state = self._wasteland_state_locked(chat_id, owner_id, slave_id, 1)
            if not state:
                self.connection.commit()
                return state_status, None
            now = utc_timestamp()
            cursor = self.connection.execute(
                """INSERT INTO wasteland_runs(
                       token, chat_id, owner_id, slave_id, floor, status, state_json, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, 1, 'active', ?, ?, ?)""",
                (secrets.token_urlsafe(18), chat_id, owner_id, slave_id, json.dumps(state), now, now),
            )
            self.connection.commit()
            return "created", self.connection.execute(
                "SELECT * FROM wasteland_runs WHERE id=?", (cursor.lastrowid,)
            ).fetchone()

    async def get_wasteland_run(
        self, run_id: int | None = None, token: str | None = None
    ) -> sqlite3.Row | None:
        if run_id is None and token is None:
            return None
        async with self._lock:
            if run_id is not None:
                return self.connection.execute(
                    "SELECT * FROM wasteland_runs WHERE id=?", (run_id,)
                ).fetchone()
            return self.connection.execute(
                "SELECT * FROM wasteland_runs WHERE token=?", (token,)
            ).fetchone()

    async def submit_wasteland_action(
        self, run_id: int, owner_id: int, action: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._lock:
            run = self.connection.execute(
                "SELECT * FROM wasteland_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run or run["status"] != "active":
                return {"status": "inactive"}
            if int(run["owner_id"]) != owner_id:
                return {"status": "forbidden"}
            state = json.loads(run["state_json"])
            _classes, skills = self._fighter_catalog_locked()
            try:
                error = validate_action(state, "a", action, skills)
            except (KeyError, TypeError, ValueError):
                error = "Некорректное действие."
            if error:
                return {"status": "invalid", "error": error}
            try:
                state = resolve_turn(
                    state,
                    {"a": action, "b": self._wasteland_ai_action_locked(state, skills)},
                    skills=skills,
                )
            except ValueError as error:
                return {"status": "invalid", "error": str(error)}
            now = utc_timestamp()
            if state["finished"]:
                if state["winner"] == "a":
                    reward = WASTELAND_BASE_XP + int(run["floor"]) * WASTELAND_FLOOR_XP
                    self._grant_profile_xp_locked(
                        "slave_profiles", int(run["chat_id"]), int(run["slave_id"]), reward
                    )
                    status = "victory"
                else:
                    reward = 0
                    status = "defeated"
                state.setdefault("wasteland", {})["reward_xp"] = reward
                self.connection.execute(
                    """UPDATE wasteland_runs SET status=?, state_json=?, updated_at=?,
                           finished_at=? WHERE id=?""",
                    (status, json.dumps(state), now, now, run_id),
                )
                self.connection.commit()
                return {"status": status, "state": state, "reward_xp": reward}
            self.connection.execute(
                "UPDATE wasteland_runs SET state_json=?, updated_at=? WHERE id=?",
                (json.dumps(state), now, run_id),
            )
            self.connection.commit()
            return {"status": "resolved", "state": state}

    async def advance_wasteland_run(self, run_id: int, owner_id: int) -> dict[str, Any]:
        async with self._lock:
            run = self.connection.execute(
                "SELECT * FROM wasteland_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run or int(run["owner_id"]) != owner_id:
                return {"status": "forbidden"}
            if run["status"] != "victory":
                return {"status": "inactive"}
            next_floor = int(run["floor"]) + 1
            state_status, state = self._wasteland_state_locked(
                int(run["chat_id"]), owner_id, int(run["slave_id"]), next_floor
            )
            if not state:
                return {"status": state_status}
            self.connection.execute(
                """UPDATE wasteland_runs SET floor=?, status='active', state_json=?,
                       updated_at=?, finished_at=NULL WHERE id=?""",
                (next_floor, json.dumps(state), utc_timestamp(), run_id),
            )
            self.connection.commit()
            return {"status": "active", "state": state, "floor": next_floor}

    async def transfer_after_loss(self, chat_id: int, loser_id: int, winner_id: int) -> tuple[str, int]:
        """Apply slavery consequences while preserving the no-slave-owners rule."""
        async with self._lock:
            winner_owner = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, winner_id),
            ).fetchone()
            if winner_owner:
                if int(winner_owner["owner_id"]) == loser_id:
                    self._settle_materials_locked(chat_id, loser_id)
                    self.connection.execute(
                        "DELETE FROM ownership WHERE chat_id=? AND slave_id=?",
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
            owned = self.connection.execute(
                """SELECT slave_id FROM ownership
                   WHERE chat_id=? AND owner_id=? AND slave_id != ?
                   ORDER BY transfer_priority ASC, RANDOM() LIMIT 1""",
                (chat_id, loser_id, winner_id),
            ).fetchone()
            if not self._owner_has_capacity_locked(chat_id, winner_id):
                self.connection.commit()
                return "owner_full", loser_id
            self._settle_materials_locked(chat_id, winner_id)
            if owned:
                slave_id = int(owned["slave_id"])
                self._settle_materials_locked(chat_id, loser_id)
                self.connection.execute(
                    """UPDATE ownership SET owner_id=?, acquired_at=?, last_forced_at=NULL,
                           transfer_priority=0
                       WHERE chat_id=? AND slave_id=?""",
                    (winner_id, utc_timestamp(), chat_id, slave_id),
                )
                outcome = "transferred"
            else:
                slave_id = loser_id
                if loser_owner:
                    self._settle_materials_locked(
                        chat_id, int(loser_owner["owner_id"])
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
                    (chat_id, slave_id, winner_id, utc_timestamp()),
                )
                outcome = "enslaved"
            self._ensure_slave_profile_locked(chat_id, slave_id)
            self._refresh_owner_record_locked(chat_id, winner_id)
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
            if current_owner_id == new_owner_id:
                return "same_owner"
            owned = self.connection.execute(
                """SELECT 1 FROM ownership
                   WHERE chat_id=? AND slave_id=? AND owner_id=?""",
                (chat_id, slave_id, current_owner_id),
            ).fetchone()
            if not owned:
                return "not_owned"
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
            if not self._owner_has_capacity_locked(chat_id, new_owner_id):
                self.connection.commit()
                return "owner_full"
            self._settle_materials_locked(chat_id, current_owner_id)
            self._settle_materials_locked(chat_id, new_owner_id)
            self.connection.execute(
                """UPDATE ownership
                   SET owner_id=?, acquired_at=?, last_forced_at=NULL,
                       transfer_priority=0
                   WHERE chat_id=? AND slave_id=?""",
                (new_owner_id, utc_timestamp(), chat_id, slave_id),
            )
            self._ensure_slave_profile_locked(chat_id, slave_id)
            self._refresh_owner_record_locked(chat_id, new_owner_id)
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
            existing_owner = self.connection.execute(
                "SELECT owner_id FROM ownership WHERE chat_id=? AND slave_id=?",
                (chat_id, slave_id),
            ).fetchone()
            same_owner = bool(
                existing_owner and int(existing_owner["owner_id"]) == owner_id
            )
            if not same_owner and not self._owner_has_capacity_locked(chat_id, owner_id):
                self.connection.commit()
                return "owner_full"
            self._settle_materials_locked(chat_id, owner_id)
            self._settle_materials_locked(chat_id, slave_id)
            if existing_owner and not same_owner:
                self._settle_materials_locked(
                    chat_id, int(existing_owner["owner_id"])
                )
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
                        last_forced_at=NULL,
                        transfer_priority=0""",
                (chat_id, slave_id, owner_id, utc_timestamp()),
            )
            self._ensure_slave_profile_locked(chat_id, slave_id)
            self._refresh_owner_record_locked(chat_id, owner_id)
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

    async def increment_counter(self, chat_id: int, key: str) -> int:
        async with self._lock:
            self.connection.execute(
                """INSERT INTO counters(chat_id, counter_key, value) VALUES (?, ?, 1)
                   ON CONFLICT(chat_id, counter_key) DO UPDATE SET value=value + 1""",
                (chat_id, key),
            )
            row = self.connection.execute(
                "SELECT value FROM counters WHERE chat_id=? AND counter_key=?",
                (chat_id, key),
            ).fetchone()
            self.connection.commit()
            return int(row["value"])

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

    async def list_basement_members(self, chat_id: int) -> list[sqlite3.Row]:
        async with self._lock:
            return self.connection.execute(
                """SELECT b.user_id, b.added_at, u.username, u.display_name
                   FROM basement_members b
                   LEFT JOIN users u ON u.chat_id=b.chat_id AND u.user_id=b.user_id
                   WHERE b.chat_id=? ORDER BY b.added_at, b.user_id""",
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
