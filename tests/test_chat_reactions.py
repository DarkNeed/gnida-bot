import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.types import Chat, Message, User, Update
from PIL import Image

from handlers.routes import (
    BRYANSK_NORTH_RE, BRYANSK_NORTH_STICKER_PATH,
    BOT_CRITICISM_RE, BOT_CRITICISM_REPLIES, BOT_PRAISE_RE,
    BOT_PRAISE_STICKER_PATHS, create_router,
)


class ChatReactionPatternTests(unittest.TestCase):
    def test_bryansk_command(self):
        for text in ("Брянск север", "БРЯНСК СЕВЕР!", " Брянск  север "):
            self.assertIsNotNone(BRYANSK_NORTH_RE.fullmatch(text))
        for text in ("едем в Брянск север", "Брянск северный", "Брянск"):
            self.assertIsNone(BRYANSK_NORTH_RE.fullmatch(text))

    def test_criticism(self):
        for text in ("Гнидабот плохой", "Гнида-бот тупой", "Бот тупой",
                     "ГНИДА БОТ, ТЫ ПЛОХОЙ!", "По-моему, гнидабот очень глупый."):
            self.assertIsNotNone(BOT_CRITICISM_RE.search(text), text)
        for text in ("Гнидабот не плохой", "Мой кот тупой", "чатбот тупой",
                     "Гнидабот тупойкой", "Гнидабот хороший"):
            self.assertIsNone(BOT_CRITICISM_RE.search(text), text)

    def test_praise(self):
        for text in ("Гнида-бот хороший", "Гнидабот хороший", "Гнида бот молодец!",
                     "Вот гнидабот просто лучший", "Бот умный"):
            self.assertIsNotNone(BOT_PRAISE_RE.search(text), text)
        for text in ("Гнидабот не хороший", "Кот хороший", "чатбот хороший",
                     "Гнидабот хорошийка", "Бот плохой"):
            self.assertIsNone(BOT_PRAISE_RE.search(text), text)

    def test_telegram_sticker_files(self):
        for path in (BRYANSK_NORTH_STICKER_PATH, *BOT_PRAISE_STICKER_PATHS):
            self.assertTrue(path.is_file())
            self.assertLessEqual(path.stat().st_size, 512 * 1024)
            with Image.open(path) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(max(image.size), 512)
                self.assertLessEqual(min(image.size), 512)
                image.verify()


class ChatReactionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = SimpleNamespace(upsert_chat=AsyncMock(), upsert_user=AsyncMock(),
                                  complete_leg_requests=AsyncMock(),
                                  recent_users=AsyncMock(return_value=[]))
        self.router = create_router(self.db)

    def handler(self, name):
        return next(item.callback for item in self.router.message.handlers
                    if item.callback.__name__ == name)

    async def test_correct_sticker_mapping(self):
        message = SimpleNamespace(answer_sticker=AsyncMock())
        await self.handler("bryansk_north_sticker")(message)
        self.assertEqual(message.answer_sticker.await_args.args[0].path,
                         BRYANSK_NORTH_STICKER_PATH)
        for selected in BOT_PRAISE_STICKER_PATHS:
            with patch("handlers.routes.random.choice", return_value=selected) as choice:
                await self.handler("bot_praise_sticker")(message)
            choice.assert_called_once_with(BOT_PRAISE_STICKER_PATHS)
            self.assertEqual(message.answer_sticker.await_args.args[0].path, selected)

    async def test_all_requested_text_responses(self):
        message = SimpleNamespace(answer=AsyncMock())
        self.assertEqual(BOT_CRITICISM_REPLIES, (
            "Пошёл нахуй", "Нет, пошёл нахуй", "Проветрись. То есть пошёл нахуй"))
        for response in BOT_CRITICISM_REPLIES:
            with patch("handlers.routes.random.choice", return_value=response) as choice:
                await self.handler("bot_criticism_reply")(message)
            choice.assert_called_once_with(BOT_CRITICISM_REPLIES)
            message.answer.assert_awaited_with(response, parse_mode=None)

    async def test_dispatcher_does_not_swallow_new_reactions(self):
        dp = Dispatcher()
        dp.include_router(self.router)
        bot = Bot("123456:abcdefghijklmnopqrstuvwxyzABCDEF123456789")
        bot.session.make_request = AsyncMock(return_value=True)
        try:
            phrases = (
                dict(text="Брянск север"),
                dict(text="Гнида-бот плохой"),
                dict(text="Гнидабот хороший"),
                dict(caption="Гнида-бот хороший!", photo=[
                    dict(file_id="p", file_unique_id="p", width=1, height=1)]),
                dict(text="Бот тупой", chat=Chat(id=10, type="private")),
            )
            for mid, payload in enumerate(phrases, 1):
                message = Message(message_id=mid,
                    date=datetime.now(timezone.utc),
                    from_user=User(id=10, is_bot=False, first_name="Тестер"),
                    **(dict(chat=Chat(id=-100, type="supergroup")) | payload))
                await dp.feed_update(bot, Update(update_id=mid, message=message))
            methods = [call.args[1] for call in bot.session.make_request.await_args_list]
            self.assertEqual(len(methods), 5)
            self.assertEqual(methods[0].sticker.path, BRYANSK_NORTH_STICKER_PATH)
            self.assertIn(methods[1].text, BOT_CRITICISM_REPLIES)
            self.assertIn(methods[2].sticker.path, BOT_PRAISE_STICKER_PATHS)
            self.assertIn(methods[3].sticker.path, BOT_PRAISE_STICKER_PATHS)
            self.assertIn(methods[4].text, BOT_CRITICISM_REPLIES)
            self.db.recent_users.assert_not_awaited()
        finally:
            await bot.session.close()
