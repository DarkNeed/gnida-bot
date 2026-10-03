"""Owner constructors follow the same selected chat as the private menu."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from franc_events import FrancEventStore
from handlers.franc_events import create_franc_event_router
from handlers.routes import create_router


class ConstructorChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "constructors.sqlite3")
        await self.db.connect()
        self.owner = User(id=CUSTOM_COMMAND_OWNER_ID, is_bot=False, first_name="Владелец")
        self.store = FrancEventStore(self.db)
        self.commands = {}
        self.events = {}
        for chat_id, title, trigger in ((-100, "Каргассия", "Первая команда"), (-200, "Другой чат", "Вторая команда")):
            await self.db.upsert_chat(chat_id, title)
            await self.db.upsert_user(chat_id, self.owner.id, None, "Владелец")
            self.commands[chat_id] = await self.db.save_custom_command(
                chat_id, trigger, trigger.casefold(), 0, 100, ["Первый ответ"], [], None, self.owner.id
            )
            template_id = await self.store.create_template(chat_id, "luck")
            await self.store.update_scalar(template_id, "prompt", f"Событие: {title}")
            self.events[chat_id] = template_id
        await self.db.select_menu_chat(self.owner.id, -100)
        self.present = {-100: True, -200: True}

        async def get_chat_member(chat_id, user_id):
            return SimpleNamespace(status="member" if self.present[chat_id] else "left")

        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(side_effect=get_chat_member),
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=123)),
        )
        self.router = create_router(self.db)
        self.event_router = create_franc_event_router(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    def state(self, data=None):
        return SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock(),
                               get_data=AsyncMock(return_value=data or {}))

    def callback(self, data):
        return SimpleNamespace(
            data=data, from_user=self.owner, answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(type="private"),
                                    edit_text=AsyncMock(), answer=AsyncMock()),
        )

    def message(self, text):
        return SimpleNamespace(text=text, caption=None, from_user=self.owner,
                               chat=SimpleNamespace(type="private"), answer=AsyncMock())

    def handler(self, router, name, callbacks=True):
        handlers = router.callback_query.handlers if callbacks else router.message.handlers
        return next(item.callback for item in handlers if item.callback.__name__ == name)

    async def custom(self, data, state=None):
        callback = self.callback(data)
        await self.handler(self.router, "custom_command_menu_callback")(callback, state or self.state(), self.bot)
        return callback

    async def event(self, data, state=None):
        callback = self.callback(data)
        await self.handler(self.event_router, "event_admin_callback")(callback, state or self.state(), self.bot)
        return callback

    def buttons(self, callback):
        markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
        return [b for row in markup.inline_keyboard for b in row]

    async def test_lists_follow_selection_from_menu_and_direct_commands(self):
        for chat_id, title, wanted, excluded in (
            (-100, "Каргассия", "Первая команда", "Вторая команда"),
            (-200, "Другой чат", "Вторая команда", "Первая команда"),
        ):
            await self.db.select_menu_chat(self.owner.id, chat_id)
            for source in ("menu", "callback", "command"):
                with self.subTest(chat_id=chat_id, source=source):
                    if source == "menu":
                        callback = self.callback("sm:custom")
                        await self.handler(self.router, "slave_menu_callback")(callback, self.bot)
                        body = callback.message.edit_text.await_args.args[0]
                    elif source == "callback":
                        callback = await self.custom("cc:list:0")
                        body = callback.message.edit_text.await_args.args[0]
                    else:
                        message = self.message("/команды")
                        await self.handler(self.router, "custom_command_list", False)(message, self.bot)
                        body = message.answer.await_args.args[0]
                        # Triggers are button labels, not repeated in the body.
                        body += " " + " ".join(b.text for row in message.answer.await_args.kwargs["reply_markup"].inline_keyboard for b in row)
                    if source != "command":
                        body += " " + " ".join(b.text for b in self.buttons(callback))
                    self.assertIn(f"Чат: {title}", body)
                    self.assertIn(wanted, body)
                    self.assertNotIn(excluded, body)
            event = await self.event("evm:list")
            body = event.message.edit_text.await_args.args[0]
            self.assertIn(f"Чат: {title}", body)
            data = {b.callback_data for b in self.buttons(event)}
            self.assertIn(f"evm:detail:{self.events[chat_id]}", data)
            other = -200 if chat_id == -100 else -100
            self.assertNotIn(f"evm:detail:{self.events[other]}", data)
            message = self.message("/events")
            await self.handler(self.event_router, "events_menu", False)(message, self.bot)
            self.assertIn(f"Чат: {title}", message.answer.await_args.args[0])

    async def test_new_commands_and_events_only_offer_selected_chat(self):
        callback = await self.custom("cc:chats")
        self.assertIn("Чат: Каргассия", callback.message.edit_text.await_args.args[0])
        self.assertIn("cc:new:-100", {b.callback_data for b in self.buttons(callback)})
        self.assertNotIn("cc:new:-200", {b.callback_data for b in self.buttons(callback)})
        state = self.state()
        await self.custom("cc:new:-100", state)
        state.update_data.assert_awaited_once_with(chat_id=-100)
        callback = await self.event("evm:chats")
        self.assertIn("Чат: Каргассия", callback.message.edit_text.await_args.args[0])
        self.assertIn("evm:new:-100:luck", {b.callback_data for b in self.buttons(callback)})
        await self.event("evm:new:-100:luck")
        self.assertEqual(len([row for row in await self.store.list_templates() if row["chat_id"] == -100]), 2)
        state = self.state()
        await self.custom("cc:new:-200", state)
        state.set_state.assert_not_awaited()
        await self.event("evm:new:-200:luck")
        self.assertEqual(len([row for row in await self.store.list_templates() if row["chat_id"] == -200]), 1)

    async def test_old_constructor_buttons_cannot_edit_or_delete_other_chat(self):
        await self.db.select_menu_chat(self.owner.id, -200)
        for action in ("detail", "confirm", "edit"):
            suffix = ":cost" if action == "edit" else ""
            callback = await self.custom(f"cc:{action}:{self.commands[-100]}{suffix}")
            self.assertIn("другому чату", callback.answer.await_args.args[0])
        self.assertIsNotNone(await self.db.get_custom_command_by_id(self.commands[-100]))
        self.db.connection.execute("UPDATE custom_commands SET enabled=0 WHERE id=?", (self.commands[-100],))
        self.db.connection.commit()
        await self.custom(f"cc:confirm:{self.commands[-100]}")
        self.assertIsNotNone(self.db.connection.execute(
            "SELECT id FROM custom_commands WHERE id=?", (self.commands[-100],)
        ).fetchone())
        for action in ("detail", "confirm", "toggle", "launch"):
            callback = await self.event(f"evm:{action}:{self.events[-100]}")
            self.assertIn("другому чату", callback.answer.await_args.args[0])
        self.assertEqual((await self.store.get_template(self.events[-100]))["enabled"], 0)
        self.bot.send_message.assert_not_awaited()

    async def test_no_selection_or_left_chat_shows_picker_without_records(self):
        for unavailable in ("missing", "left"):
            if unavailable == "missing":
                await self.db.select_menu_chat(self.owner.id, -9999)
            else:
                await self.db.select_menu_chat(self.owner.id, -100)
                self.present[-100] = False
            for callback in (await self.custom("cc:list:0"), await self.event("evm:list")):
                body = callback.message.edit_text.await_args.args[0]
                self.assertIn("Выбери чат", body)
                self.assertFalse(any((b.callback_data or "").startswith(("cc:detail:", "evm:detail:")) for b in self.buttons(callback)))

    async def test_switch_during_input_does_not_modify_previous_chat(self):
        await self.db.select_menu_chat(self.owner.id, -200)
        state = self.state({"command_id": self.commands[-100], "field": "cost"})
        await self.handler(self.router, "custom_command_edit_value", False)(self.message("100"), state, self.bot)
        self.assertEqual((await self.db.get_custom_command_by_id(self.commands[-100]))["cost"], 0)
        state = self.state({"template_id": self.events[-100], "field": "success_reward", "action": "field"})
        await self.handler(self.event_router, "event_input", False)(self.message("-100"), state, self.bot)
        self.assertEqual((await self.store.get_template(self.events[-100]))["success_reward"], 15)
        state = self.state({"chat_id": -100, "success_chance": 100, "trigger": "Новая команда"})
        await self.handler(self.router, "custom_command_failures", False)(self.message("нет"), state, self.bot)
        self.assertEqual(len(await self.db.list_all_custom_commands()), 2)

    async def test_manual_event_launch_respects_selection_but_auto_events_remain_enabled(self):
        for template_id in self.events.values():
            await self.store.toggle_template(template_id)
        message = self.message(f"/event {self.events[-200]}")
        handler = self.handler(self.event_router, "event_manual_command", False)
        await handler(message, self.bot, self.state())
        self.bot.send_message.assert_not_awaited()
        self.assertIn("выбранном чате", message.answer.await_args.args[0])
        await self.db.select_menu_chat(self.owner.id, -200)
        await handler(message, self.bot, self.state())
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.await_args.args[0], -200)
        self.assertEqual(set(await self.store.enabled_chats()), {-100, -200})

    async def test_other_chat_records_do_not_affect_pagination_or_empty_lists(self):
        for index in range(10):
            await self.db.save_custom_command(-200, f"Чужая {index}", f"чужая {index}", 0, 100,
                                              ["Да"], [], None, self.owner.id)
            await self.store.create_template(-200, "luck")
        for callback in (await self.custom("cc:list:0"), await self.event("evm:list")):
            body = callback.message.edit_text.await_args.args[0]
            self.assertIn("1 шт.", body)
            self.assertIn("1/1", body)
        await self.db.upsert_chat(-400, "Пустой чат")
        self.present[-400] = True
        await self.db.select_menu_chat(self.owner.id, -400)
        for callback in (await self.custom("cc:list:0"), await self.event("evm:list")):
            self.assertIn("Чат: Пустой чат", callback.message.edit_text.await_args.args[0])
            self.assertFalse(any((b.callback_data or "").startswith(("cc:detail:", "evm:detail:")) for b in self.buttons(callback)))
