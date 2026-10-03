"""Regression tests for branching and weighted franc events."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

from aiogram.types import User

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from franc_events import FrancEventStore, event_config
from handlers.franc_events import create_franc_event_router


class EventOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.folder.name) / "events.sqlite3")
        await self.database.connect()
        await self.database.upsert_chat(-100, "Тест")
        await self.database.select_menu_chat(CUSTOM_COMMAND_OWNER_ID, -100)
        self.menu_bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")))
        self.store = FrancEventStore(self.database)

    async def asyncTearDown(self):
        await self.database.close()
        self.folder.cleanup()

    async def test_choice_buttons_have_independent_outcomes_and_rewards(self):
        template_id = await self.store.create_template(-100, "choice")
        await self.store.update_scalar(template_id, "prompt", "Выбери дверь")
        for label in ("Левая", "Средняя", "Правая"):
            await self.store.change_list(template_id, "options", "add", value=label)
        await self.store.toggle_outcome_mode(template_id)
        self.assertIn("каждой кнопки", (await self.store.toggle_template(template_id))[1])
        for index, reward in enumerate((0, 25, 50)):
            await self.store.change_outcome(
                template_id, "choice", "reward", index=index, value=str(reward)
            )
            await self.store.change_outcome(
                template_id, "choice", "message_add", index=index,
                value=f"Дверь {index + 1}: {{amount}} ₣",
            )
        await self.store.change_outcome(
            template_id, "choice", "message_add", index=1,
            value="Альтернативная фраза: {amount} ₣",
        )
        self.assertEqual((await self.store.toggle_template(template_id)), (True, None))
        event, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(error)
        await self.store.activate_event(int(event["id"]), 123)
        with patch("franc_events.random.choice", return_value="Альтернативная фраза: {amount} ₣"):
            result = await self.store.submit_attempt(int(event["id"]), 10, "1")
        self.assertEqual((result["reward"], result["phrase"], result["resolved"]),
                         (25, "Альтернативная фраза: {amount} ₣", True))
        self.assertEqual(await self.database.franc_balance(-100, 10), 25)
        self.assertEqual((await self.store.submit_attempt(int(event["id"]), 11, "2"))["status"], "closed")

    async def test_choice_outcomes_follow_buttons_when_deleted(self):
        template_id = await self.store.create_template(-100, "choice")
        for label in ("A", "B", "C"):
            await self.store.change_list(template_id, "options", "add", value=label)
        await self.store.toggle_outcome_mode(template_id)
        await self.store.change_outcome(template_id, "choice", "reward", index=2, value="60")
        await self.store.change_list(template_id, "options", "delete", index=1)
        config = event_config(await self.store.get_template(template_id))
        self.assertEqual(config["options"], ["A", "C"])
        self.assertEqual([item["reward"] for item in config["choice_outcomes"]], [0, 60])

    async def test_luck_outcomes_use_weights_and_snapshot_rewards(self):
        template_id = await self.store.create_template(-100, "luck")
        await self.store.update_scalar(template_id, "prompt", "Тяни билет")
        await self.store.toggle_outcome_mode(template_id)
        await self.store.change_outcome(template_id, "luck", "add")
        for index, (weight, reward) in enumerate(((80, 0), (15, 20), (5, 100))):
            await self.store.change_outcome(template_id, "luck", "weight", index=index, value=str(weight))
            await self.store.change_outcome(template_id, "luck", "reward", index=index, value=str(reward))
            await self.store.change_outcome(
                template_id, "luck", "message_add", index=index, value=f"Выпал {index + 1}"
            )
        self.assertEqual((await self.store.toggle_template(template_id)), (True, None))
        event, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(error)
        await self.store.activate_event(int(event["id"]), 124)
        await self.store.change_outcome(template_id, "luck", "reward", index=2, value="200")
        self.assertEqual(json.loads(event["snapshot_json"])["luck_outcomes"][2]["reward"], 100)
        with patch("franc_events.random.choices", return_value=[2]) as weighted:
            result = await self.store.submit_attempt(int(event["id"]), 10, "go")
        self.assertEqual(weighted.call_args.kwargs["weights"], [80, 15, 5])
        self.assertEqual((result["reward"], result["phrase"], result["resolved"]),
                         (100, "Выпал 3", True))
        self.assertEqual(await self.database.franc_balance(-100, 10), 100)

    async def test_legacy_modes_survive_switching_back(self):
        template_id = await self.store.create_template(-100, "choice")
        await self.store.change_list(template_id, "options", "add", value="Нет")
        await self.store.change_list(template_id, "options", "add", value="Да")
        await self.store.set_correct_option(template_id, 1)
        await self.store.toggle_outcome_mode(template_id)
        await self.store.toggle_outcome_mode(template_id)
        config = event_config(await self.store.get_template(template_id))
        self.assertEqual(config["choice_mode"], "quiz")
        self.assertEqual(config["correct_index"], 1)

    async def test_owner_can_configure_button_outcome_in_private_menu(self):
        template_id = await self.store.create_template(-100, "choice")
        await self.store.change_list(template_id, "options", "add", value="Левая дверь")
        await self.store.change_list(template_id, "options", "add", value="Правая дверь")
        router = create_franc_event_router(self.database)
        callback_handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "event_admin_callback"
        )
        input_handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "event_input"
        )

        class State:
            data = {}

            async def clear(self):
                self.data = {}

            async def set_state(self, _value):
                return None

            async def update_data(self, **values):
                self.data.update(values)

            async def get_data(self):
                return self.data

        state = State()
        actor = User(id=CUSTOM_COMMAND_OWNER_ID, is_bot=False, first_name="Владелец")
        private_message = SimpleNamespace(
            chat=SimpleNamespace(type="private"), edit_text=AsyncMock(), answer=AsyncMock()
        )
        callback = SimpleNamespace(
            from_user=actor, message=private_message, answer=AsyncMock(),
            data=f"evm:mode:{template_id}",
        )
        await callback_handler(callback, state, self.menu_bot)
        self.assertIn("исход для каждой кнопки", private_message.edit_text.await_args.args[0])
        callback.data = f"evm:outcome:{template_id}:choice:1"
        await callback_handler(callback, state, self.menu_bot)
        self.assertIn("Правая дверь", private_message.edit_text.await_args.args[0])
        callback.data = f"evm:ofield:{template_id}:choice:1:reward"
        await callback_handler(callback, state, self.menu_bot)
        self.assertIn("Награда", private_message.answer.await_args.args[0])
        input_message = SimpleNamespace(
            text="-35", chat=SimpleNamespace(type="private"), from_user=actor,
            answer=AsyncMock(),
        )
        await input_handler(input_message, state, self.menu_bot)
        config = event_config(await self.store.get_template(template_id))
        self.assertEqual(config["choice_outcomes"][1]["reward"], -35)


if __name__ == "__main__":
    unittest.main()
