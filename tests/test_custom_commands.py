import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from custom_commands import (
    command_responses,
    normalize_custom_trigger,
    parse_response_lines,
    render_custom_template,
    template_placeholders,
)
from database import Database
from handlers.routes import create_router


class CustomCommandTemplateTests(unittest.TestCase):
    def test_trigger_normalization_ignores_case_spacing_and_final_punctuation(self):
        self.assertEqual(
            normalize_custom_trigger("  Послать   ОМОНА!!!  "),
            "послать омона",
        )

    def test_response_parser_accepts_bulleted_multiline_text(self):
        self.assertEqual(
            parse_response_lines("- Первый ответ\n- Второй ответ"),
            ["Первый ответ", "Второй ответ"],
        )

    def test_template_supports_both_placeholder_styles_and_escapes_html(self):
        template = "<b>{actor}</b> поймал (тег2), а виноват {random}"
        self.assertEqual(template_placeholders(template), {"actor", "target", "random"})
        rendered = render_custom_template(
            template,
            actor_mention='<a href="tg://user?id=1">Автор</a>',
            target_mention='<a href="tg://user?id=2">Цель</a>',
            random_mention='<a href="tg://user?id=3">Случайный</a>',
        )
        self.assertIn("&lt;b&gt;", rendered)
        self.assertIn('tg://user?id=1', rendered)
        self.assertIn('tg://user?id=2', rendered)
        self.assertIn('tg://user?id=3', rendered)


class CustomCommandDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "custom.sqlite3")
        await self.database.connect()
        await self.database.upsert_chat(1, "Тест")
        await self.database.upsert_user(1, 10, "actor", "Автор")

    async def asyncTearDown(self):
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_command_is_persistent_updatable_and_deletable(self):
        command_id = await self.database.save_custom_command(
            1,
            "Подарить ламборгини",
            "подарить ламборгини",
            10,
            75,
            ["{actor} подарил машину {target}"],
            ["Сделка сорвалась"],
            None,
            1980056841,
        )
        row = await self.database.get_custom_command(1, "подарить ламборгини")
        self.assertEqual(row["id"], command_id)
        self.assertEqual(row["cost"], 10)

        await self.database.save_custom_command(
            1,
            "Подарить ламборгини",
            "подарить ламборгини",
            50,
            30,
            ["Успех"],
            ["Неудача"],
            10,
            1980056841,
        )
        rows = await self.database.list_custom_commands(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["cost"], rows[0]["exclusive_user_id"]), (50, 10))
        self.assertTrue(await self.database.delete_custom_command(1, "подарить ламборгини"))
        self.assertIsNone(await self.database.get_custom_command(1, "подарить ламборгини"))

    async def test_franc_spending_is_atomic_and_never_goes_negative(self):
        self.database.connection.execute(
            "INSERT INTO franc_balances(chat_id, user_id, balance, updated_at) VALUES (1, 10, 50, 1)"
        )
        self.database.connection.commit()
        self.assertFalse(await self.database.spend_francs(1, 10, 51))
        self.assertEqual(await self.database.franc_balance(1, 10), 50)
        self.assertTrue(await self.database.spend_francs(1, 10, 20))
        self.assertEqual(await self.database.franc_balance(1, 10), 30)

    async def test_menu_edits_keep_other_responses_and_validate_required_outcomes(self):
        command_id = await self.database.save_custom_command(
            1, "Подарить ламборгини", "подарить ламборгини", 50, 30,
            ["Первый успех"], ["Первая неудача"], None, 1980056841,
        )
        self.assertEqual(
            await self.database.modify_custom_command_response(
                command_id, "success", "add", text="Второй успех"
            ), "updated",
        )
        self.assertEqual(
            await self.database.modify_custom_command_response(
                command_id, "success", "edit", index=0, text="Исправленный успех"
            ), "updated",
        )
        self.assertEqual(
            await self.database.modify_custom_command_response(
                command_id, "failure", "delete", index=0
            ), "last_required",
        )
        self.assertEqual(
            await self.database.update_custom_command_setting(command_id, "cost", 75),
            "updated",
        )
        self.assertEqual(
            await self.database.update_custom_command_setting(command_id, "success_chance", 100),
            "updated",
        )
        self.assertEqual(
            await self.database.modify_custom_command_response(
                command_id, "failure", "delete", index=0
            ), "updated",
        )
        self.assertEqual(
            await self.database.update_custom_command_setting(command_id, "success_chance", 30),
            "needs_failure",
        )
        self.assertEqual(
            await self.database.modify_custom_command_response(
                command_id, "success", "delete", index=0
            ), "updated",
        )
        self.assertEqual(
            await self.database.modify_custom_command_response(
                command_id, "success", "delete", index=0
            ), "last_required",
        )
        row = await self.database.get_custom_command_by_id(command_id)
        self.assertEqual(row["cost"], 75)
        self.assertEqual(row["success_responses"], '["Второй успех"]')
        self.assertEqual(row["failure_responses"], '[]')
        self.assertEqual(len(await self.database.list_all_custom_commands()), 1)
        self.assertEqual(len(await self.database.list_custom_command_chats(10)), 1)

    async def test_renaming_command_cannot_overwrite_another_trigger(self):
        first_id = await self.database.save_custom_command(
            1, "Первая", "первая", 0, 100, ["Один"], [], None, 1980056841,
        )
        await self.database.save_custom_command(
            1, "Вторая", "вторая", 0, 100, ["Два"], [], None, 1980056841,
        )
        self.assertEqual(
            await self.database.update_custom_command_setting(first_id, "trigger", "Вторая"),
            "exists",
        )
        self.assertEqual(
            (await self.database.get_custom_command_by_id(first_id))["trigger"], "Первая"
        )

    async def test_private_menu_adds_one_response_to_existing_command(self):
        command_id = await self.database.save_custom_command(
            1, "Подарить ламборгини", "подарить ламборгини", 0, 100,
            ["Первый вариант"], [], None, 1980056841,
        )
        router = create_router(self.database)
        callback_handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "custom_command_menu_callback"
        )
        edit_handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "custom_command_edit_value"
        )
        state = SimpleNamespace(
            clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock(),
            get_data=AsyncMock(return_value={
                "command_id": command_id, "field": "response",
                "outcome": "success", "action": "add", "index": None,
            }),
        )
        menu_message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            answer=AsyncMock(), edit_text=AsyncMock(),
        )
        callback = SimpleNamespace(
            from_user=User(id=1980056841, is_bot=False, first_name="Владелец"),
            message=menu_message, data=f"cc:add:{command_id}:s", answer=AsyncMock(),
        )

        await callback_handler(callback, state, SimpleNamespace())

        state.update_data.assert_awaited_once_with(
            command_id=command_id, field="response", outcome="success",
            action="add", index=None,
        )
        self.assertIn("Пришли вариант", menu_message.answer.await_args.args[0])
        response_message = SimpleNamespace(
            text="Второй вариант", caption=None,
            chat=SimpleNamespace(type="private"),
            from_user=callback.from_user, answer=AsyncMock(),
        )

        await edit_handler(response_message, state)

        row = await self.database.get_custom_command_by_id(command_id)
        self.assertEqual(
            command_responses(row, "success_responses"),
            ["Первый вариант", "Второй вариант"],
        )
        self.assertIn("✅ Вариант добавлен", response_message.answer.await_args.args[0])
        self.assertEqual(state.clear.await_count, 1)

        response_message.text = "Третий вариант"
        await edit_handler(response_message, state)
        row = await self.database.get_custom_command_by_id(command_id)
        self.assertEqual(
            command_responses(row, "success_responses"),
            ["Первый вариант", "Второй вариант", "Третий вариант"],
        )
        self.assertEqual(state.clear.await_count, 1)

        callback.data = f"cc:out:{command_id}:s:0"
        await callback_handler(callback, state, SimpleNamespace())
        self.assertEqual(state.clear.await_count, 2)

    async def test_franc_menu_lists_only_available_commands_in_current_chats(self):
        await self.database.save_custom_command(
            1, "Общая команда", "общая команда", 12, 75,
            ["Успех"], ["Неудача"], None, 1980056841,
        )
        await self.database.save_custom_command(
            1, "Личная команда", "личная команда", 0, 100,
            ["Успех"], [], 10, 1980056841,
        )
        await self.database.save_custom_command(
            1, "Чужая команда", "чужая команда", 0, 100,
            ["Успех"], [], 99, 1980056841,
        )
        await self.database.upsert_chat(2, "Покинутый чат")
        await self.database.upsert_user(2, 10, "actor", "Автор")
        await self.database.save_custom_command(
            2, "Старая команда", "старая команда", 0, 100,
            ["Успех"], [], None, 1980056841,
        )
        rows = await self.database.list_available_custom_commands(10)
        self.assertEqual(len(rows), 3)

        router = create_router(self.database)
        handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "slave_menu_callback"
        )
        callback = SimpleNamespace(
            from_user=User(id=10, is_bot=False, first_name="Автор"),
            message=SimpleNamespace(
                chat=SimpleNamespace(type="private"),
                edit_text=AsyncMock(), answer=AsyncMock(),
            ),
            data="sm:offers:0", answer=AsyncMock(),
        )
        async def get_chat_member(chat_id, user_id):
            return SimpleNamespace(status="member" if chat_id == 1 else "left")

        await handler(callback, SimpleNamespace(get_chat_member=get_chat_member))
        body = callback.message.edit_text.await_args.args[0]
        self.assertIn("Общая команда — 12 ₣ · успех 75%", body)
        self.assertIn("Личная команда", body)
        self.assertNotIn("Чужая команда", body)
        self.assertNotIn("Старая команда", body)

    async def test_start_shows_public_guide_and_menu_button(self):
        router = create_router(self.database)
        handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "start"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"), answer=AsyncMock(),
        )
        await handler(message)
        body = message.answer.await_args.args[0]
        self.assertIn("Игры", body)
        self.assertIn("Франки", body)
        self.assertIn("Рофлы", body)
        keyboard = message.answer.await_args.kwargs["reply_markup"]
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "sm:home")

    async def test_route_uses_reply_target_random_recent_user_and_charges_actor(self):
        await self.database.upsert_user(1, 20, "target", "Цель")
        await self.database.upsert_user(1, 30, "random", "Случайный")
        self.database.connection.execute(
            "INSERT INTO franc_balances(chat_id, user_id, balance, updated_at) VALUES (1, 10, 50, 1)"
        )
        self.database.connection.commit()
        await self.database.save_custom_command(
            1,
            "Послать отряд омона",
            "послать отряд омона",
            10,
            100,
            ["{actor} отправил ОМОН к {target}; свидетель: {random}"],
            [],
            None,
            1980056841,
        )
        router = create_router(self.database)
        handler = next(
            item.callback
            for item in router.message.handlers
            if item.callback.__name__ == "run_custom_command"
        )
        actor = User(id=10, is_bot=False, first_name="Автор", username="actor")
        target = User(id=20, is_bot=False, first_name="Цель", username="target")
        message = SimpleNamespace(
            text="ПОСЛАТЬ   ОТРЯД ОМОНА!!!",
            caption=None,
            chat=SimpleNamespace(id=1, type="supergroup"),
            from_user=actor,
            reply_to_message=SimpleNamespace(from_user=target, sender_chat=None),
            answer=AsyncMock(),
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(status="member")
            )
        )

        await handler(message, bot)

        response = message.answer.await_args.args[0]
        self.assertIn('tg://user?id=10', response)
        self.assertIn('tg://user?id=20', response)
        self.assertIn('tg://user?id=30', response)
        self.assertEqual(await self.database.franc_balance(1, 10), 40)

    async def test_random_target_skips_user_who_left_and_does_not_charge_without_target(self):
        await self.database.upsert_user(1, 30, "left", "Ушёл")
        self.database.connection.execute(
            "INSERT INTO franc_balances(chat_id, user_id, balance, updated_at) VALUES (1, 10, 50, 1)"
        )
        self.database.connection.commit()
        await self.database.save_custom_command(
            1, "Подарить ламборгини", "подарить ламборгини", 10, 100,
            ["{actor} подарил машину {target}"], [], None, 1980056841,
        )
        router = create_router(self.database)
        handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "run_custom_command"
        )
        message = SimpleNamespace(
            text="Подарить ламборгини", caption=None,
            chat=SimpleNamespace(id=1, type="supergroup"),
            from_user=User(id=10, is_bot=False, first_name="Автор"),
            reply_to_message=None, answer=AsyncMock(),
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="left"))
        )

        await handler(message, bot)

        self.assertIn("Не удалось выбрать цель", message.answer.await_args.args[0])
        self.assertEqual(await self.database.franc_balance(1, 10), 50)


if __name__ == "__main__":
    unittest.main()
