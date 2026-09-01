from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from datetime import datetime, timezone
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


CHALLENGE_DEADLINE_SECONDS = 3 * 60 * 60
NEWCOMER_CHALLENGE_DEADLINE_SECONDS = 5 * 60
FORCE_OWNER_COOLDOWN_SECONDS = 7 * 24 * 60 * 60
PIROJOK_USERNAME = "pirojoksostajem"
JUG_HIDING_SECONDS = 5 * 60
JUG_COOLDOWN_SECONDS = 60 * 60
BASEMENT_ESCAPE_COOLDOWN_SECONDS = 60 * 60


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

    async def mark_challenge_unavailable(self, challenge_id: int) -> None:
        """Stop resuming a challenge whose Telegram message is no longer available."""
        async with self._lock:
            self.connection.execute(
                """UPDATE challenges SET status='unavailable'
                   WHERE id=? AND status IN ('active', 'deadline')""",
                (challenge_id,),
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
            if owned:
                slave_id = int(owned["slave_id"])
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
                       SUM(CASE WHEN game_type='rps' THEN 1 ELSE 0 END) AS rps,
                       SUM(CASE WHEN game_type='blackjack' THEN 1 ELSE 0 END) AS blackjack,
                       SUM(CASE WHEN game_type='checkers' THEN 1 ELSE 0 END) AS checkers
                   FROM challenges
                   WHERE challenger_id=? OR opponent_id=?""",
                (user_id, user_id),
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
