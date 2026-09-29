import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from handlers.routes import BACKUP_RE, create_router


class BackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "live.sqlite3")
        await self.database.connect()

    async def asyncTearDown(self):
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_online_backup_includes_wal_data_and_is_independent(self):
        await self.database.upsert_chat(1, "До копии")
        backup_path = Path(self.temp_dir.name) / "backup.sqlite3"
        await self.database.backup_to(backup_path)
        await self.database.upsert_chat(1, "После копии")

        with closing(sqlite3.connect(backup_path)) as snapshot:
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            title = snapshot.execute("SELECT title FROM chats WHERE chat_id = 1").fetchone()[0]
        self.assertEqual(title, "До копии")

    async def test_backup_command_is_private_and_owner_only(self):
        self.assertIsNotNone(BACKUP_RE.fullmatch("/backup"))
        self.assertIsNotNone(BACKUP_RE.fullmatch("/бэкап"))
        router = create_router(self.database)
        handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "owner_backup"
        )
        sent_paths = []

        async def capture_document(document, **kwargs):
            path = Path(document.path)
            self.assertTrue(path.exists())
            with closing(sqlite3.connect(path)) as snapshot:
                self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            sent_paths.append(path)

        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            from_user=SimpleNamespace(id=CUSTOM_COMMAND_OWNER_ID),
            answer_document=AsyncMock(side_effect=capture_document),
            answer=AsyncMock(),
        )
        await handler(message)
        message.answer_document.assert_awaited_once()
        self.assertFalse(sent_paths[0].exists())

        message.answer_document.reset_mock()
        message.from_user.id = 123
        await handler(message)
        message.answer_document.assert_not_awaited()

        message.from_user.id = CUSTOM_COMMAND_OWNER_ID
        message.chat.type = "supergroup"
        await handler(message)
        message.answer_document.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
