"""Persistent, owner-configurable chat events that award francs."""

from __future__ import annotations

import json
import random
import re
import sqlite3
from uuid import uuid4
from typing import Any

from database import Database, utc_timestamp


EVENT_LIFETIME_SECONDS = 10 * 60
EVENT_KINDS = {"choice", "text", "luck"}
LIST_FIELDS = {
    "options": "options_json",
    "answers": "answers_json",
    "success": "success_messages_json",
    "failure": "failure_messages_json",
}
MAX_LIST_ITEMS = 20


def normalized_answer(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def event_config(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "kind": str(row["kind"]),
        "prompt": str(row["prompt"]),
        "luck_button": str(row["luck_button"]),
        "options": json.loads(row["options_json"]),
        "answers": json.loads(row["answers_json"]),
        "correct_index": int(row["correct_index"]),
        "success_chance": int(row["success_chance"]),
        "success_reward": int(row["success_reward"]),
        "failure_reward": int(row["failure_reward"]),
        "success_messages": json.loads(row["success_messages_json"]),
        "failure_messages": json.loads(row["failure_messages_json"]),
    }


def config_error(config: dict[str, Any]) -> str | None:
    if not config["prompt"].strip() or config["prompt"] == "Новое событие":
        return "Сначала напиши текст события."
    if config["kind"] == "choice" and len(config["options"]) < 2:
        return "Для выбора нужны хотя бы две кнопки."
    if config["kind"] == "text" and not config["answers"]:
        return "Добавь хотя бы один правильный ответ."
    if not config["success_messages"] or not config["failure_messages"]:
        return "Добавь фразы для успеха и неудачи."
    return None


class FrancEventStore:
    def __init__(self, database: Database):
        self.database = database

    @property
    def connection(self) -> sqlite3.Connection:
        return self.database.connection

    async def list_templates(self) -> list[sqlite3.Row]:
        async with self.database._lock:
            return self.connection.execute(
                """SELECT e.*, c.title AS chat_title FROM franc_event_templates e
                   LEFT JOIN chats c ON c.chat_id=e.chat_id
                   ORDER BY e.chat_id, e.id DESC"""
            ).fetchall()

    async def get_template(self, template_id: int) -> sqlite3.Row | None:
        async with self.database._lock:
            return self.connection.execute(
                """SELECT e.*, c.title AS chat_title FROM franc_event_templates e
                   LEFT JOIN chats c ON c.chat_id=e.chat_id WHERE e.id=?""",
                (template_id,),
            ).fetchone()

    async def create_template(self, chat_id: int, kind: str) -> int:
        if kind not in EVENT_KINDS:
            raise ValueError("Unknown event kind")
        async with self.database._lock:
            now = utc_timestamp()
            cursor = self.connection.execute(
                """INSERT INTO franc_event_templates(chat_id, kind, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (chat_id, kind, now, now),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    async def update_scalar(self, template_id: int, field: str, value: str | int) -> bool:
        bounds = {
            "prompt": (1, 500),
            "luck_button": (1, 50),
            "success_chance": (0, 100),
            "success_reward": (0, 500),
            "failure_reward": (0, 20),
        }
        if field not in bounds:
            raise ValueError("Unsupported field")
        lower, upper = bounds[field]
        if field in {"prompt", "luck_button"}:
            value = str(value).strip()
            if not lower <= len(value) <= upper:
                raise ValueError("Prompt must be 1–500 characters")
        else:
            value = int(value)
            if not lower <= value <= upper:
                raise ValueError("Value is out of range")
        async with self.database._lock:
            cursor = self.connection.execute(
                f"UPDATE franc_event_templates SET {field}=?, updated_at=? WHERE id=?",
                (value, utc_timestamp(), template_id),
            )
            if cursor.rowcount and field == "prompt":
                updated = self.connection.execute(
                    "SELECT * FROM franc_event_templates WHERE id=?", (template_id,)
                ).fetchone()
                if updated["enabled"] and config_error(event_config(updated)):
                    self.connection.execute(
                        "UPDATE franc_event_templates SET enabled=0 WHERE id=?", (template_id,)
                    )
            self.connection.commit()
            return cursor.rowcount > 0

    async def change_list(
        self, template_id: int, field: str, action: str,
        *, value: str = "", index: int | None = None,
    ) -> str:
        column = LIST_FIELDS.get(field)
        if column is None or action not in {"add", "edit", "delete"}:
            raise ValueError("Unsupported list operation")
        if action != "delete":
            value = value.strip()
            if not value or len(value) > (50 if field == "options" else 500):
                return "invalid"
        async with self.database._lock:
            row = self.connection.execute(
                f"SELECT {column}, correct_index FROM franc_event_templates WHERE id=?",
                (template_id,),
            ).fetchone()
            if row is None:
                return "missing"
            items = json.loads(row[column])
            if action == "add":
                if len(items) >= (6 if field == "options" else MAX_LIST_ITEMS):
                    return "full"
                if field == "answers" and normalized_answer(value) in {
                    normalized_answer(item) for item in items
                }:
                    return "duplicate"
                items.append(value)
            else:
                if index is None or not 0 <= index < len(items):
                    return "missing"
                if action == "edit":
                    items[index] = value
                else:
                    items.pop(index)
            correct = int(row["correct_index"])
            if field == "options" and action == "delete" and index is not None:
                if index < correct:
                    correct -= 1
                elif index == correct:
                    correct = 0
            self.connection.execute(
                f"""UPDATE franc_event_templates
                    SET {column}=?, correct_index=?, updated_at=? WHERE id=?""",
                (json.dumps(items, ensure_ascii=False), correct, utc_timestamp(), template_id),
            )
            updated = self.connection.execute(
                "SELECT * FROM franc_event_templates WHERE id=?", (template_id,)
            ).fetchone()
            if updated["enabled"] and config_error(event_config(updated)):
                self.connection.execute(
                    "UPDATE franc_event_templates SET enabled=0 WHERE id=?", (template_id,)
                )
            self.connection.commit()
            return "updated"

    async def set_correct_option(self, template_id: int, index: int) -> bool:
        async with self.database._lock:
            row = self.connection.execute(
                "SELECT options_json, kind FROM franc_event_templates WHERE id=?",
                (template_id,),
            ).fetchone()
            if row is None or row["kind"] != "choice" or not 0 <= index < len(json.loads(row["options_json"])):
                return False
            self.connection.execute(
                """UPDATE franc_event_templates SET correct_index=?, updated_at=?
                   WHERE id=?""",
                (index, utc_timestamp(), template_id),
            )
            self.connection.commit()
            return True

    async def toggle_template(self, template_id: int) -> tuple[bool, str | None]:
        async with self.database._lock:
            row = self.connection.execute(
                "SELECT * FROM franc_event_templates WHERE id=?", (template_id,)
            ).fetchone()
            if row is None:
                return False, "Событие удалено."
            enabled = not bool(row["enabled"])
            error = config_error(event_config(row)) if enabled else None
            if error:
                return False, error
            self.connection.execute(
                "UPDATE franc_event_templates SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), utc_timestamp(), template_id),
            )
            self.connection.commit()
            return enabled, None

    async def delete_template(self, template_id: int) -> bool:
        async with self.database._lock:
            cursor = self.connection.execute(
                "DELETE FROM franc_event_templates WHERE id=?", (template_id,)
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def enabled_chats(self) -> list[int]:
        async with self.database._lock:
            rows = self.connection.execute(
                "SELECT DISTINCT chat_id FROM franc_event_templates WHERE enabled=1"
            ).fetchall()
            return [int(row["chat_id"]) for row in rows]

    async def ensure_schedule(
        self, chat_id: int, service_day: str, times: list[int]
    ) -> None:
        async with self.database._lock:
            if self.connection.execute(
                "SELECT 1 FROM franc_event_schedules WHERE chat_id=? AND service_day=?",
                (chat_id, service_day),
            ).fetchone():
                return
            self.connection.executemany(
                """INSERT INTO franc_event_schedules(chat_id, service_day, slot, scheduled_at)
                   VALUES (?, ?, ?, ?)""",
                [(chat_id, service_day, index, when) for index, when in enumerate(times)],
            )
            self.connection.commit()

    async def due_schedules(self, now: int) -> list[sqlite3.Row]:
        async with self.database._lock:
            return self.connection.execute(
                """SELECT * FROM franc_event_schedules
                   WHERE status='pending' AND scheduled_at<=?
                   ORDER BY scheduled_at LIMIT 20""",
                (now,),
            ).fetchall()

    async def skip_stale_schedules(self, before: int) -> None:
        async with self.database._lock:
            self.connection.execute(
                """UPDATE franc_event_schedules SET status='skipped'
                   WHERE status='pending' AND scheduled_at<?""",
                (before,),
            )
            self.connection.commit()

    async def begin_scheduled_event(self, schedule_id: int) -> sqlite3.Row | None:
        async with self.database._lock:
            schedule = self.connection.execute(
                "SELECT * FROM franc_event_schedules WHERE id=? AND status='pending'",
                (schedule_id,),
            ).fetchone()
            if schedule is None:
                return None
            if self.connection.execute(
                """SELECT 1 FROM franc_events WHERE chat_id=? AND status IN ('sending', 'active')
                   AND expires_at>?""",
                (int(schedule["chat_id"]), utc_timestamp()),
            ).fetchone():
                self.connection.execute(
                    "UPDATE franc_event_schedules SET status='skipped' WHERE id=?",
                    (schedule_id,),
                )
                self.connection.commit()
                return None
            rows = self.connection.execute(
                """SELECT * FROM franc_event_templates
                   WHERE chat_id=? AND enabled=1 ORDER BY last_used_at, id""",
                (int(schedule["chat_id"]),),
            ).fetchall()
            rows = [row for row in rows if config_error(event_config(row)) is None]
            if not rows:
                self.connection.execute(
                    "UPDATE franc_event_schedules SET status='skipped' WHERE id=?",
                    (schedule_id,),
                )
                self.connection.commit()
                return None
            oldest = int(rows[0]["last_used_at"])
            template = random.choice([row for row in rows if int(row["last_used_at"]) == oldest])
            now = utc_timestamp()
            self.connection.execute(
                "UPDATE franc_event_schedules SET status='sending' WHERE id=?",
                (schedule_id,),
            )
            self.connection.execute(
                "UPDATE franc_event_templates SET last_used_at=? WHERE id=?",
                (now, int(template["id"])),
            )
            cursor = self.connection.execute(
                """INSERT INTO franc_events(
                       schedule_id, template_id, chat_id, snapshot_json, starts_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (schedule_id, int(template["id"]), int(schedule["chat_id"]),
                 json.dumps(event_config(template), ensure_ascii=False),
                 now, now + EVENT_LIFETIME_SECONDS),
            )
            self.connection.commit()
            return self.connection.execute(
                "SELECT * FROM franc_events WHERE id=?", (int(cursor.lastrowid),)
            ).fetchone()

    async def begin_manual_event(self, template_id: int) -> tuple[sqlite3.Row | None, str | None]:
        """Reserve one immediate event without consuming a daily schedule slot."""
        async with self.database._lock:
            template = self.connection.execute(
                "SELECT * FROM franc_event_templates WHERE id=?", (template_id,)
            ).fetchone()
            if template is None:
                return None, "Событие не найдено."
            error = config_error(event_config(template))
            if error:
                return None, error
            chat_id = int(template["chat_id"])
            now = utc_timestamp()
            if self.connection.execute(
                """SELECT 1 FROM franc_events WHERE chat_id=? AND status IN ('sending', 'active')
                   AND expires_at>?""",
                (chat_id, now),
            ).fetchone():
                return None, "В этом чате уже идёт событие. Дождись его завершения."
            schedule = self.connection.execute(
                """INSERT INTO franc_event_schedules(
                       chat_id, service_day, slot, scheduled_at, status
                   ) VALUES (?, ?, 0, ?, 'sending')""",
                (chat_id, f"manual:{uuid4().hex}", now),
            )
            event = self.connection.execute(
                """INSERT INTO franc_events(
                       schedule_id, template_id, chat_id, snapshot_json, starts_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (int(schedule.lastrowid), template_id, chat_id,
                 json.dumps(event_config(template), ensure_ascii=False),
                 now, now + EVENT_LIFETIME_SECONDS),
            )
            self.connection.commit()
            return self.connection.execute(
                "SELECT * FROM franc_events WHERE id=?", (int(event.lastrowid),)
            ).fetchone(), None

    async def activate_event(self, event_id: int, message_id: int) -> None:
        async with self.database._lock:
            self.connection.execute(
                "UPDATE franc_events SET status='active', message_id=? WHERE id=? AND status='sending'",
                (message_id, event_id),
            )
            self.connection.execute(
                """UPDATE franc_event_schedules SET status='sent'
                   WHERE id=(SELECT schedule_id FROM franc_events WHERE id=?)""",
                (event_id,),
            )
            self.connection.commit()

    async def fail_event(self, event_id: int) -> None:
        async with self.database._lock:
            self.connection.execute(
                "UPDATE franc_events SET status='failed' WHERE id=? AND status='sending'",
                (event_id,),
            )
            self.connection.execute(
                """UPDATE franc_event_schedules SET status='failed'
                   WHERE id=(SELECT schedule_id FROM franc_events WHERE id=?)""",
                (event_id,),
            )
            self.connection.commit()

    async def recover_sending_events(self) -> None:
        async with self.database._lock:
            self.connection.execute("UPDATE franc_events SET status='failed' WHERE status='sending'")
            self.connection.execute(
                "UPDATE franc_event_schedules SET status='failed' WHERE status='sending'"
            )
            self.connection.commit()

    async def active_events_to_expire(self, now: int) -> list[sqlite3.Row]:
        async with self.database._lock:
            return self.connection.execute(
                """SELECT * FROM franc_events WHERE status='active' AND expires_at<=?""",
                (now,),
            ).fetchall()

    async def expire_event(self, event_id: int) -> bool:
        async with self.database._lock:
            cursor = self.connection.execute(
                "UPDATE franc_events SET status='expired' WHERE id=? AND status='active'",
                (event_id,),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def event_for_reply(self, chat_id: int, message_id: int) -> sqlite3.Row | None:
        async with self.database._lock:
            return self.connection.execute(
                """SELECT * FROM franc_events WHERE chat_id=? AND message_id=?
                   AND status='active' AND expires_at>?""",
                (chat_id, message_id, utc_timestamp()),
            ).fetchone()

    async def get_event(self, event_id: int) -> sqlite3.Row | None:
        async with self.database._lock:
            return self.connection.execute(
                "SELECT * FROM franc_events WHERE id=?", (event_id,)
            ).fetchone()

    async def submit_attempt(self, event_id: int, user_id: int, action: str) -> dict[str, Any]:
        async with self.database._lock:
            row = self.connection.execute(
                "SELECT * FROM franc_events WHERE id=?", (event_id,)
            ).fetchone()
            if row is None or row["status"] != "active" or int(row["expires_at"]) <= utc_timestamp():
                return {"status": "closed"}
            if self.connection.execute(
                "SELECT 1 FROM franc_event_attempts WHERE event_id=? AND user_id=?",
                (event_id, user_id),
            ).fetchone():
                return {"status": "already"}
            config = json.loads(row["snapshot_json"])
            kind = config["kind"]
            if kind == "choice":
                try:
                    selected = int(action)
                except ValueError:
                    return {"status": "invalid"}
                if not 0 <= selected < len(config["options"]):
                    return {"status": "invalid"}
                won = selected == config["correct_index"]
            elif kind == "text":
                won = normalized_answer(action) in {
                    normalized_answer(answer) for answer in config["answers"]
                }
            else:
                if action != "go":
                    return {"status": "invalid"}
                won = random.randint(1, 100) <= int(config["success_chance"])
            outcome = "success" if won else "failure"
            reward = int(config[f"{outcome}_reward"])
            phrase = random.choice(config[f"{outcome}_messages"])
            now = utc_timestamp()
            self.connection.execute(
                """INSERT INTO franc_event_attempts(event_id, user_id, outcome, reward, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, user_id, outcome, reward, now),
            )
            if reward:
                self.database._add_francs_locked(int(row["chat_id"]), user_id, reward)
            resolved = won or kind == "luck"
            if resolved:
                self.connection.execute(
                    """UPDATE franc_events SET status='resolved', winner_id=?, outcome=?
                       WHERE id=?""",
                    (user_id, outcome, event_id),
                )
            self.connection.commit()
            return {
                "status": outcome,
                "reward": reward,
                "phrase": phrase,
                "resolved": resolved,
                "chat_id": int(row["chat_id"]),
                "message_id": int(row["message_id"]),
            }
