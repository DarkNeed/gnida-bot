import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Chat, Message, Update, User

from database import Database
from message_activity import MSK, message_week
from handlers.message_activity import (
    MESSAGE_TOP_RE, MessageActivityMiddleware, create_message_activity_router,
    format_message_top,
)


class MessageActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "messages.sqlite3")
        await self.db.connect()
        self.now = int(datetime(2026, 10, 4, 23, 59, tzinfo=MSK).timestamp())

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def record(self, mid, user=1, chat=-100, sent=None, **kwargs):
        return await self.db.record_chat_message(
            chat, mid, user, kwargs.get("name", f"User {user}"),
            kwargs.get("username", f"user{user}"),
            self.now if sent is None else sent, now=self.now,
        )

    async def top(self, chat=-100):
        return await self.db.weekly_message_top(chat, now=self.now)

    async def test_top_ten_chat_isolation_and_ties(self):
        for user in range(1, 13):
            await self.record(user, user)
        await self.record(100, 8)
        await self.record(101, 8, chat=-200)
        top = await self.top()
        self.assertEqual(len(top["entries"]), 10)
        self.assertEqual([r["user_id"] for r in top["entries"][:3]], [8, 1, 2])
        self.assertEqual(top["entries"][0]["message_count"], 2)
        self.assertEqual((await self.top(-200))["entries"][0]["message_count"], 1)

    async def test_replay_concurrent_delivery_and_restart(self):
        results = await asyncio.gather(*(self.record(1) for _ in range(5)))
        self.assertEqual(sum(results), 1)
        await self.db.close()
        await self.db.connect()
        self.assertFalse(await self.record(1))
        self.assertEqual((await self.top())["entries"][0]["message_count"], 1)

    async def test_moscow_monday_boundary_and_retention(self):
        start = message_week(self.now)
        await self.record(1, sent=start - 1)
        await self.record(2, sent=start)
        await self.record(3, sent=start - 14 * 86400)
        self.assertEqual((await self.top())["entries"][0]["message_count"], 1)
        self.now += 60  # Monday 00:00 MSK, still Sunday in UTC.
        self.assertEqual((await self.top())["entries"], [])
        await self.record(4)
        self.assertEqual(self.db.connection.execute(
            "SELECT COUNT(*) FROM chat_message_receipts"
        ).fetchone()[0], 2)

    async def test_profile_updates_do_not_go_backwards(self):
        await self.record(1, name="Новое", username=None)
        await self.record(2, name="Старое", sent=self.now - 1)
        row = (await self.top())["entries"][0]
        self.assertEqual(row["display_name"], "Новое")
        self.assertIsNone(row["username"])
        self.assertEqual(row["message_count"], 2)

    async def test_format_exact_example_and_no_mentions_or_markup(self):
        await self.record(1, name="Егор в Кувшине", username="pirojoksostajem")
        self.assertEqual(format_message_top(await self.top()),
            "Люди без личной жизни за неделю 28.09.2026 - 04.10.2026\n"
            "1. Егор в Кувшине (pirojoksostajem) - 1")
        await self.record(2, name="@test\n2. forged <b>name</b>", username=None)
        result = format_message_top(await self.top())
        self.assertNotIn("@", result)
        self.assertEqual(len(result.splitlines()), 2)
        self.assertNotIn("None", result)

    def message(self, mid, **kwargs):
        payload = dict(message_id=mid, date=datetime.fromtimestamp(self.now, MSK),
            chat=Chat(id=-100, type="supergroup"),
            from_user=User(id=1, is_bot=False, first_name="Тестер"), text="test")
        payload.update(kwargs)
        return Message(**payload)

    async def test_middleware_content_and_exclusions(self):
        middleware = MessageActivityMiddleware(self.db)
        handler = AsyncMock()
        messages = [
            self.message(1),
            self.message(2, text=None, photo=[dict(file_id="p", file_unique_id="p", width=1, height=1)]),
            self.message(3, from_user=User(id=2, is_bot=True, first_name="Bot")),
            self.message(4, sender_chat=Chat(id=-100, type="supergroup")),
            self.message(5, text=None, new_chat_members=[User(id=3, is_bot=False, first_name="New")]),
            self.message(6, chat=Chat(id=1, type="private")),
        ]
        with patch("message_activity.time.time", return_value=self.now):
            for message in messages:
                await middleware(handler, message, {})
        self.assertEqual(handler.await_count, len(messages))
        self.assertEqual((await self.top())["entries"][0]["message_count"], 2)

    async def test_dispatcher_counts_other_routers_and_command_before_reply(self):
        dp = Dispatcher()
        dp.message.outer_middleware(MessageActivityMiddleware(self.db))
        early = Router()
        async def other_feature(message: Message):
            return "handled"
        early.message.register(other_feature, F.text == "test")
        dp.include_router(early)
        dp.include_router(create_message_activity_router(self.db))
        bot = Bot("123456:abcdefghijklmnopqrstuvwxyzABCDEF123456789")
        bot.session.make_request = AsyncMock(return_value=True)
        try:
            with patch("message_activity.time.time", return_value=self.now):
                await dp.feed_update(bot, Update(update_id=1, message=self.message(1)))
                await dp.feed_update(bot, Update(update_id=2, message=self.message(2, text="Кто больше всех пиздит?")))
                await dp.feed_update(bot, Update(update_id=3, edited_message=self.message(1, text="edited")))
            self.assertEqual((await self.top())["entries"][0]["message_count"], 2)
            sent = bot.session.make_request.await_args.args[1]
            self.assertIn("Тестер - 2", sent.text)
            self.assertIsNone(sent.parse_mode)
            self.assertIsNone(sent.entities)
        finally:
            await bot.session.close()

    async def test_private_command_and_empty_state(self):
        handler = create_message_activity_router(self.db).message.handlers[0].callback
        message = SimpleNamespace(chat=SimpleNamespace(id=1, type="private"), answer=AsyncMock())
        await handler(message)
        self.assertIn("в нужном чате", message.answer.await_args.args[0])
        self.assertIn("Пока нет", format_message_top(await self.top()))

    def test_command_matching(self):
        for text in ("Кто больше всех пиздит?", "кто больше всех пиздит", " КТО  БОЛЬШЕ ВСЕХ ПИЗДИТ ? "):
            self.assertIsNotNone(MESSAGE_TOP_RE.fullmatch(text))
        for text in ("Он спросил кто больше всех пиздит?", "Кто больше всех пиздит? ещё текст"):
            self.assertIsNone(MESSAGE_TOP_RE.fullmatch(text))
