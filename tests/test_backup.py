import sqlite3
import asyncio
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiogram.exceptions import TelegramEntityTooLarge, TelegramRetryAfter
from aiogram.methods import SendDocument
from backup_archive import archive_snapshot, restore_archive, split_archive

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
            restored = Path(self.temp_dir.name) / "restored.sqlite3"
            restore_archive(path, restored)
            with closing(sqlite3.connect(restored)) as snapshot:
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

    def handler_and_message(self):
        router = create_router(self.database)
        handler = next(item.callback for item in router.message.handlers
                       if item.callback.__name__ == "owner_backup")
        return handler, SimpleNamespace(
            chat=SimpleNamespace(type="private"), from_user=SimpleNamespace(id=CUSTOM_COMMAND_OWNER_ID),
            answer_document=AsyncMock(), answer=AsyncMock(),
        )

    async def test_parts_roundtrip_and_corruption_no_overwrite(self):
        await self.database.upsert_chat(1, "Данные в WAL")
        snapshot = Path(self.temp_dir.name) / "snapshot.sqlite3"
        await self.database.backup_to(snapshot)
        archive = archive_snapshot(snapshot)
        parts, manifest = split_archive(archive, 4096)
        self.assertGreater(len(parts), 1)
        restored = Path(self.temp_dir.name) / "restored.sqlite3"
        restore_archive(manifest, restored)
        self.assertEqual(snapshot.read_bytes(), restored.read_bytes())
        with self.assertRaises(FileExistsError):
            restore_archive(manifest, restored)
        parts[0].write_bytes(b"corrupt")
        other = Path(self.temp_dir.name) / "never-created.sqlite3"
        with self.assertRaisesRegex(ValueError, "Повреждена"):
            restore_archive(manifest, other)
        self.assertFalse(other.exists())

    async def test_missing_parts_order_and_unsafe_names_are_rejected(self):
        snapshot = Path(self.temp_dir.name) / "snapshot.sqlite3"
        await self.database.backup_to(snapshot)
        parts, manifest = split_archive(archive_snapshot(snapshot), 4096)
        data = json.loads(manifest.read_text())
        data["parts"].reverse()
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            restore_archive(manifest, Path(self.temp_dir.name) / "wrong-order.sqlite3")
        data["parts"][0]["name"] = "../snapshot.sqlite3"
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Небезопасное"):
            restore_archive(manifest, Path(self.temp_dir.name) / "unsafe.sqlite3")
        data["parts"][0]["name"] = "missing.part"
        manifest.write_text(json.dumps(data))
        with self.assertRaises(FileNotFoundError):
            restore_archive(manifest, Path(self.temp_dir.name) / "missing.sqlite3")

    async def test_oversize_upload_falls_back_to_complete_smaller_series(self):
        handler, message = self.handler_and_message()
        sent = []
        async def upload(document, **kwargs):
            path = Path(document.path)
            if path.suffix == ".zip" or path.stat().st_size > 8192:
                raise TelegramEntityTooLarge(SendDocument(chat_id=1, document="test"), "too big")
            copied = Path(self.temp_dir.name) / path.name
            copied.write_bytes(path.read_bytes())
            sent.append(copied)
        message.answer_document.side_effect = upload
        with patch("handlers.routes.BACKUP_PART_BYTES", 1024 * 1024), patch("handlers.routes.MIN_BACKUP_PART_BYTES", 4096):
            await handler(message)
        self.assertTrue(sent[-1].name.endswith(".backup.json"))
        restored = Path(self.temp_dir.name) / "uploaded.sqlite3"
        restore_archive(sent[-1], restored)
        self.assertTrue(restored.exists())
        self.assertFalse(any("Не удалось" in c.args[0] for c in message.answer.call_args_list))

    async def test_retry_after_and_concurrent_backup_are_safe(self):
        handler, message = self.handler_and_message()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def upload(document, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TelegramRetryAfter(SendDocument(chat_id=1, document="test"), "wait", retry_after=0)
            entered.set()
            await release.wait()
        message.answer_document.side_effect = upload
        task = asyncio.create_task(handler(message))
        await entered.wait()
        await handler(message)
        self.assertIn("Предыдущий", message.answer.call_args.args[0])
        release.set()
        await task
        self.assertEqual(calls, 2)

if __name__ == "__main__":
    unittest.main()
