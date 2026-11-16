"""Chat-local weekly message totals; never store message text."""

import time
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))


def message_week(timestamp: int) -> int:
    day = datetime.fromtimestamp(timestamp, MSK).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int((day - timedelta(days=day.weekday())).timestamp())


class MessageActivityMixin:
    def _connect_message_activity(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS chat_message_totals (
                chat_id INTEGER NOT NULL, week_start INTEGER NOT NULL,
                user_id INTEGER NOT NULL, display_name TEXT NOT NULL,
                username TEXT, last_message_at INTEGER NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(chat_id, week_start, user_id)
            );
            CREATE TABLE IF NOT EXISTS chat_message_receipts (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                week_start INTEGER NOT NULL,
                PRIMARY KEY(chat_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_message_receipt_week
                ON chat_message_receipts(week_start);
            CREATE INDEX IF NOT EXISTS idx_chat_message_total_week
                ON chat_message_totals(week_start);
        """)
        self._message_activity_cleanup_week = None

    async def record_chat_message(
        self, chat_id, message_id, user_id, display_name, username, sent_at, *, now=None
    ):
        now = int(time.time()) if now is None else int(now)
        current_week = message_week(now)
        week = message_week(sent_at)
        # Keep only this week and the preceding one, including deduplication IDs.
        oldest = current_week - 7 * 86400
        if week < oldest or sent_at > now + 60:
            return False
        async with self._lock:
            with self.connection:
                if self._message_activity_cleanup_week != current_week:
                    self.connection.execute(
                        "DELETE FROM chat_message_receipts WHERE week_start < ?", (oldest,)
                    )
                    self.connection.execute(
                        "DELETE FROM chat_message_totals WHERE week_start < ?", (oldest,)
                    )
                inserted = self.connection.execute(
                    "INSERT OR IGNORE INTO chat_message_receipts VALUES (?, ?, ?)",
                    (chat_id, message_id, week),
                ).rowcount
                if inserted:
                    self.connection.execute("""
                        INSERT INTO chat_message_totals
                            VALUES (?, ?, ?, ?, ?, ?, 1)
                        ON CONFLICT(chat_id, week_start, user_id) DO UPDATE SET
                            message_count=message_count+1,
                            display_name=CASE WHEN excluded.last_message_at >= last_message_at
                                THEN excluded.display_name ELSE display_name END,
                            username=CASE WHEN excluded.last_message_at >= last_message_at
                                THEN excluded.username ELSE username END,
                            last_message_at=MAX(last_message_at, excluded.last_message_at)
                    """, (chat_id, week, user_id, display_name, username, sent_at))
            self._message_activity_cleanup_week = current_week
            return bool(inserted)

    async def weekly_message_top(self, chat_id, *, now=None):
        now = int(time.time()) if now is None else int(now)
        week = message_week(now)
        async with self._lock:
            entries = self.connection.execute("""
                SELECT user_id, display_name, username, message_count
                FROM chat_message_totals WHERE chat_id=? AND week_start=?
                ORDER BY message_count DESC, user_id ASC LIMIT 10
            """, (chat_id, week)).fetchall()
        start = datetime.fromtimestamp(week, MSK).date()
        return dict(start=start, end=start + timedelta(days=6), entries=entries)
