"""Private menus isolate chats and check live Telegram membership."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import GetChatMember
from aiogram.types import User

from database import Database
from handlers.routes import create_router


class PrivateMenuChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "menu.sqlite3")
        await self.db.connect()
        self.actor = User(id=10, is_bot=False, first_name="Автор", username="actor")
        for chat_id, title in ((-100, "Каргассия"), (-200, "Другой чат"), (-300, "Покинутый чат")):
            await self.db.upsert_chat(chat_id, title)
            for user_id, username in ((10, "actor"), (20, "slave"), (30, "boss")):
                await self.db.upsert_user(chat_id, user_id, username, username)
        await self.db.credit_francs(-100, 10, 1937)
        await self.db.credit_francs(-200, 10, 50)
        await self.db.credit_francs(-300, 10, 7000)
        await self.db.force_enslave(-100, 20, 10)
        await self.db.force_enslave(-200, 10, 30)
        await self.db.force_enslave(-300, 20, 10)
        self.statuses = {-100: "member", -200: "member", -300: "left"}

        async def get_chat_member(chat_id, user_id):
            status = self.statuses[chat_id]
            if isinstance(status, Exception):
                raise status
            if isinstance(status, tuple):
                return SimpleNamespace(status=status[0], is_member=status[1])
            return SimpleNamespace(status=status)

        self.bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=get_chat_member))
        self.router = create_router(self.db)
        self.handler = next(item.callback for item in self.router.callback_query.handlers
                            if item.callback.__name__ == "slave_menu_callback")

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    def callback(self, data):
        return SimpleNamespace(
            data=data, from_user=self.actor, answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(type="private"),
                                    edit_text=AsyncMock(), answer=AsyncMock()),
        )

    async def click(self, data):
        callback = self.callback(data)
        await self.handler(callback, self.bot)
        return callback

    def view(self, callback):
        call = callback.message.edit_text.await_args
        return call.args[0], call.kwargs["reply_markup"]

    def buttons(self, keyboard):
        return [button for row in keyboard.inline_keyboard for button in row]

    async def test_picker_only_lists_live_memberships_and_zero_balance_chats(self):
        self.statuses[-300] = ("restricted", False)
        await self.db.upsert_chat(-400, "Без баланса")
        self.statuses[-400] = ("restricted", True)
        callback = await self.click("sm:chats")
        _, keyboard = self.view(callback)
        data = {button.callback_data for button in self.buttons(keyboard)}
        self.assertIn("sm:select:-100", data)
        self.assertIn("sm:select:-200", data)
        self.assertIn("sm:select:-400", data)
        self.assertNotIn("sm:select:-300", data)

    async def test_switch_scopes_home_balance_status_and_survives_restart(self):
        first = await self.click("sm:select:-100")
        body, keyboard = self.view(first)
        self.assertIn("Чат: Каргассия", body)
        self.assertIn("1937 ₣", body)
        self.assertIn("Твоих рабов: 1", body)
        self.assertIn("<b>рабовладелец</b>", body)
        self.assertNotIn("Другой чат", body)
        self.assertIn("sm:c:-100:priority", {b.callback_data for b in self.buttons(keyboard)})
        second = await self.click("sm:select:-200")
        body, _ = self.view(second)
        self.assertIn("50 ₣", body)
        self.assertIn("Твоих рабов: 0", body)
        self.assertIn("<b>раб</b>", body)
        self.assertIn("@boss", body)
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.selected_menu_chat(10), -200)
        body, _ = self.view(await self.click("sm:home"))
        self.assertIn("Чат: Другой чат", body)
        self.assertIn("50 ₣", body)

    async def test_selected_chat_scopes_all_menu_sections(self):
        await self.db.create_business(-100, 10, "field")
        await self.db.create_business(-300, 10, "brothel")
        await self.db.create_challenge(-100, 10, 30, game_type="rps", friendly=True)
        await self.db.create_challenge(-200, 10, 30, game_type="blackjack", friendly=True)
        await self.db.save_custom_command(-100, "Своя команда", "своя команда", 12, 100,
                                          ["Да"], [], None, 1980056841)
        await self.db.save_custom_command(-200, "Другая команда", "другая команда", 12, 100,
                                          ["Да"], [], None, 1980056841)
        for section in ("slaves", "priority", "games", "francs", "offers:0", "business", "work", "buyout"):
            with self.subTest(section=section):
                body, keyboard = self.view(await self.click(f"sm:c:-100:{section}"))
                self.assertIn("Чат: Каргассия", body)
                self.assertNotIn("Другой чат", body)
                self.assertNotIn("Покинутый чат", body)
                for button in self.buttons(keyboard):
                    data = button.callback_data or ""
                    self.assertNotIn("-200", data)
                    self.assertNotIn("-300", data)
                    self.assertLessEqual(len(data.encode()), 64)
                if section == "games":
                    self.assertIn("Всего: 1", body)
                    self.assertIn("блэкджек: 0", body)
                if section == "offers:0":
                    self.assertIn("Своя команда", body)
                    self.assertNotIn("Другая команда", body)

    async def test_old_scoped_buttons_do_not_use_new_selection(self):
        await self.click("sm:select:-200")
        callback = await self.click("sm:c:-100:p:-100:20")
        self.assertTrue((await self.db.get_owner(-100, 20))["transfer_priority"])
        self.assertFalse((await self.db.get_owner(-300, 20))["transfer_priority"])
        body, _ = self.view(callback)
        self.assertIn("Чат: Каргассия", body)

    async def test_cross_chat_payload_cannot_modify_priority(self):
        await self.click("sm:select:-100")
        for data in ("sm:c:-100:p:-300:20", "sm:p:-300:20"):
            callback = await self.click(data)
            callback.message.edit_text.assert_not_awaited()
            self.assertIn("другому чату", callback.answer.await_args.args[0])
        self.assertFalse((await self.db.get_owner(-300, 20))["transfer_priority"])

    async def test_leaving_chat_blocks_old_mutations_and_selection(self):
        await self.click("sm:select:-100")
        self.statuses[-100] = "left"
        for action in ("p:-100:20", "bn:-100:field", "job:-100:30", "buy:-100:30", "br:-100:20:collector"):
            await self.click(f"sm:c:-100:{action}")
        self.assertFalse((await self.db.get_owner(-100, 20))["transfer_priority"])
        self.assertIsNone(await self.db.get_business(-100, 10))
        self.assertEqual(await self.db.franc_balance(-100, 10), 1937)
        callback = await self.click("sm:select:-100")
        _, keyboard = self.view(callback)
        self.assertNotIn("sm:select:-100", {b.callback_data for b in self.buttons(keyboard)})
        self.assertEqual(await self.db.selected_menu_chat(10), -100)
        body, _ = self.view(await self.click("sm:home"))
        self.assertIn("Чат: Другой чат", body)
        self.assertEqual(await self.db.selected_menu_chat(10), -200)

    async def test_no_memberships_and_telegram_errors_expose_no_chat_data(self):
        self.statuses[-100] = TelegramForbiddenError(
            method=GetChatMember(chat_id=-100, user_id=10), message="bot was kicked"
        )
        self.statuses[-200] = "kicked"
        callback = await self.click("sm:home")
        body, keyboard = self.view(callback)
        self.assertIn("Нет доступных чатов", body)
        self.assertNotIn("1937", body)
        self.assertFalse(any((b.callback_data or "").startswith("sm:select:") for b in self.buttons(keyboard)))
        # Global help stays accessible even without a group.
        callback = await self.click("sm:guide")
        self.assertIn("Краткий гайд", self.view(callback)[0])

    async def test_private_text_commands_use_selected_chat(self):
        await self.db.select_menu_chat(10, -100)
        for name, text in (("slave_menu", "/menu"), ("francs", "/франки"), ("slaves", "/рабы"),
                           ("set_slave_priority", "/приоритет @slave")):
            with self.subTest(name=name):
                handler = next(item.callback for item in self.router.message.handlers if item.callback.__name__ == name)
                message = SimpleNamespace(text=text, caption=None, from_user=self.actor,
                                          chat=SimpleNamespace(type="private"), answer=AsyncMock())
                await handler(message, self.bot)
                body = message.answer.await_args.args[0]
                self.assertIn("Каргассия", body)
                self.assertNotIn("Другой чат", body)
        self.assertTrue((await self.db.get_owner(-100, 20))["transfer_priority"])
        self.assertFalse((await self.db.get_owner(-300, 20))["transfer_priority"])

    async def test_business_role_work_and_buyout_mutate_only_the_button_chat(self):
        self.assertEqual(await self.db.create_business(-100, 10, "field"), "created")
        self.assertEqual(await self.db.create_business(-200, 30, "brothel"), "created")
        callback = await self.click("sm:c:-100:br:-100:20:collector")
        self.assertIn("Чат: Каргассия", self.view(callback)[0])
        workers = await self.db.list_business_slaves(-100, 10)
        self.assertEqual(workers[0]["role"], "collector")
        self.assertFalse((await self.db.get_owner(-300, 20))["transfer_priority"])
        callback = await self.click("sm:c:-200:job:-200:30")
        self.assertIn("Чат: Другой чат", self.view(callback)[0])
        self.assertEqual(await self.db.franc_balance(-100, 10), 1937)
        await self.db.credit_francs(-200, 10, 100)
        before = await self.db.franc_balance(-200, 10)
        callback = await self.click("sm:c:-200:buy:-200:30")
        self.assertIn("Чат: Другой чат", self.view(callback)[0])
        self.assertIsNone(await self.db.get_owner(-200, 10))
        self.assertEqual(await self.db.franc_balance(-200, 10), before - 100)
        self.assertEqual(await self.db.franc_balance(-100, 10), 1937)

    async def test_picker_paginates_and_rejects_unknown_chat(self):
        for index in range(12):
            chat_id = -1000 - index
            await self.db.upsert_chat(chat_id, f"Чат {index:02d}")
            self.statuses[chat_id] = "member"
        first = await self.click("sm:chats")
        _, keyboard = self.view(first)
        self.assertEqual(sum((b.callback_data or "").startswith("sm:select:") for b in self.buttons(keyboard)), 8)
        self.assertIn("sm:chats:1", {b.callback_data for b in self.buttons(keyboard)})
        second = await self.click("sm:chats:1")
        _, keyboard = self.view(second)
        self.assertEqual(sum((b.callback_data or "").startswith("sm:select:") for b in self.buttons(keyboard)), 6)
        await self.db.select_menu_chat(10, -100)
        await self.click("sm:select:-9999")
        self.assertEqual(await self.db.selected_menu_chat(10), -100)

    async def test_private_enterprise_statistics_follow_selected_chat_and_membership(self):
        await self.db.create_business(-100, 10, "field")
        await self.db.create_business(-200, 30, "brothel")
        await self.db.select_menu_chat(10, -200)
        handler = next(item.callback for item in self.router.message.handlers
                       if item.callback.__name__ == "enterprise_stats")
        message = SimpleNamespace(from_user=self.actor, chat=SimpleNamespace(type="private"), answer=AsyncMock())
        await handler(message, self.bot)
        body = message.answer.await_args.args[0]
        self.assertIn("Чат: Другой чат", body)
        self.assertNotIn("Каргассия", body)
        callback_handler = next(item.callback for item in self.router.callback_query.handlers
                                if item.callback.__name__ == "enterprise_stats_callback")
        callback = self.callback("es:-200:30")
        await callback_handler(callback, self.bot)
        self.assertIn("Чат: Другой чат", self.view(callback)[0])
        self.statuses[-200] = "left"
        callback = self.callback("es:-200:30")
        await callback_handler(callback, self.bot)
        callback.message.edit_text.assert_not_awaited()
        self.assertIn("недоступен", callback.answer.await_args.args[0])
