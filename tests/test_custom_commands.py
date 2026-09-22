import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from custom_commands import (
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
