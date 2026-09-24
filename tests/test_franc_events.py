import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import User

from custom_commands import CUSTOM_COMMAND_OWNER_ID
from database import Database
from franc_events import FrancEventStore, event_config
from handlers.franc_events import (
    EventReplyFilter, create_franc_event_router, public_event_view, rendered_phrase,
    schedule_times, service_day,
)


class FrancEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "event.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(-100, "Карагассия")
        await self.db.upsert_user(-100, 3, "guest", "Участник")
        self.store = FrancEventStore(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    async def make_template(self, kind="choice"):
        template_id = await self.store.create_template(-100, kind)
        await self.store.update_scalar(template_id, "prompt", "Выбери верный ответ")
        if kind == "choice":
            await self.store.change_list(template_id, "options", "add", value="Нет")
            await self.store.change_list(template_id, "options", "add", value="Да")
            await self.store.set_correct_option(template_id, 1)
        elif kind == "text":
            await self.store.change_list(template_id, "answers", "add", value="Самовар")
        enabled, error = await self.store.toggle_template(template_id)
        self.assertTrue(enabled, error)
        return template_id

    async def make_active_event(self, kind="choice"):
        await self.make_template(kind)
        now = int(datetime.now(timezone.utc).timestamp())
        await self.store.ensure_schedule(-100, "2026-09-24", [now])
        due = await self.store.due_schedules(now)
        self.assertEqual(len(due), 1)
        event = await self.store.begin_scheduled_event(int(due[0]["id"]))
        await self.store.activate_event(int(event["id"]), 123)
        return await self.store.get_event(int(event["id"]))

    async def test_choice_constructor_and_once_only_payout(self):
        event = await self.make_active_event()
        self.assertIn("Нет", public_event_view(event)[1].inline_keyboard[0][0].text)
        first = await self.store.submit_attempt(int(event["id"]), 3, "0")
        self.assertEqual((first["status"], first["reward"], first["resolved"]), ("failure", 0, False))
        self.assertEqual((await self.store.submit_attempt(int(event["id"]), 3, "1"))["status"], "already")
        second = await self.store.submit_attempt(int(event["id"]), 4, "1")
        self.assertEqual((second["status"], second["reward"], second["resolved"]), ("success", 15, True))
        self.assertEqual(await self.db.franc_balance(-100, 4), 15)
        self.assertEqual((await self.store.submit_attempt(int(event["id"]), 5, "1"))["status"], "closed")

    async def test_text_accepts_normalized_reply_and_custom_variants(self):
        event = await self.make_active_event("text")
        template_id = int(event["template_id"])
        await self.store.change_list(template_id, "success", "add", value="{user} нашёл {amount} франков!")
        found = await self.store.event_for_reply(-100, 123)
        self.assertEqual(found["id"], event["id"])
        reply_filter = EventReplyFilter(self.store)
        message = SimpleNamespace(
            text="  сАмоВАр  ",
            from_user=User(id=3, is_bot=False, first_name="Участник"),
            chat=SimpleNamespace(id=-100, type="supergroup"),
            reply_to_message=SimpleNamespace(message_id=123),
        )
        self.assertIn("franc_event", await reply_filter(message))
        outcome = await self.store.submit_attempt(int(event["id"]), 3, message.text)
        self.assertEqual(outcome["status"], "success")
        self.assertEqual(await self.db.franc_balance(-100, 3), 15)
        self.assertEqual((await self.store.event_for_reply(-100, 123)), None)

    async def test_luck_result_and_failure_reward_survive_restart(self):
        event = await self.make_active_event("luck")
        await self.store.update_scalar(int(event["template_id"]), "failure_reward", 7)
        await self.store.update_scalar(int(event["template_id"]), "luck_button", "Тянуть билет")
        # The current event uses a snapshot; edit applies only to the next event.
        self.assertEqual(json.loads(event["snapshot_json"])["failure_reward"], 0)
        self.assertEqual(public_event_view(event)[1].inline_keyboard[0][0].text, "🎰 Испытать удачу")
        await self.db.close()
        await self.db.connect()
        with patch("franc_events.random.randint", return_value=100):
            outcome = await self.store.submit_attempt(int(event["id"]), 3, "go")
        self.assertEqual((outcome["status"], outcome["reward"]), ("failure", 0))
        self.assertEqual(await self.db.franc_balance(-100, 3), 0)

    async def test_configured_failure_can_award_francs_once(self):
        template_id = await self.make_template("luck")
        await self.store.update_scalar(template_id, "failure_reward", 7)
        await self.store.change_list(template_id, "failure", "add", value="{user} забрал {amount} ₣")
        now = int(datetime.now(timezone.utc).timestamp())
        await self.store.ensure_schedule(-100, "2026-09-25", [now])
        scheduled = (await self.store.due_schedules(now))[0]
        event = await self.store.begin_scheduled_event(int(scheduled["id"]))
        await self.store.activate_event(int(event["id"]), 124)
        with patch("franc_events.random.randint", return_value=100):
            outcome = await self.store.submit_attempt(int(event["id"]), 3, "go")
        self.assertEqual((outcome["status"], outcome["reward"]), ("failure", 7))
        self.assertEqual(await self.db.franc_balance(-100, 3), 7)
        self.assertEqual((await self.store.submit_attempt(int(event["id"]), 3, "go"))["status"], "closed")
        self.assertEqual(await self.db.franc_balance(-100, 3), 7)

    async def test_variants_editing_and_enable_validation(self):
        template_id = await self.store.create_template(-100, "choice")
        self.assertEqual((await self.store.toggle_template(template_id))[1], "Сначала напиши текст события.")
        await self.store.update_scalar(template_id, "prompt", "Вопрос")
        self.assertIn("две кнопки", (await self.store.toggle_template(template_id))[1])
        await self.store.change_list(template_id, "options", "add", value="А")
        await self.store.change_list(template_id, "options", "add", value="Б")
        await self.store.set_correct_option(template_id, 1)
        await self.store.change_list(template_id, "options", "delete", index=0)
        self.assertEqual(event_config(await self.store.get_template(template_id))["correct_index"], 0)
        await self.store.change_list(template_id, "options", "add", value="В")
        await self.store.change_list(template_id, "success", "add", value="Молодец, {user}!")
        await self.store.change_list(template_id, "success", "edit", value="Ура!", index=1)
        self.assertEqual(event_config(await self.store.get_template(template_id))["success_messages"][1], "Ура!")
        await self.store.change_list(template_id, "success", "delete", index=1)
        self.assertTrue((await self.store.toggle_template(template_id))[0])
        await self.store.change_list(template_id, "options", "delete", index=1)
        self.assertEqual((await self.store.get_template(template_id))["enabled"], 0)

    async def test_schedule_once_per_day_and_window(self):
        await self.make_template()
        now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
        day = service_day(now)
        times = schedule_times(day, now)
        self.assertIn(len(times), (1, 2))
        await self.store.ensure_schedule(-100, day, times)
        await self.store.ensure_schedule(-100, day, times)
        rows = self.db.connection.execute(
            "SELECT * FROM franc_event_schedules WHERE chat_id=-100 AND service_day=?",
            (day,),
        ).fetchall()
        self.assertEqual(len(rows), len(times))

    async def test_manual_event_does_not_consume_daily_slot_or_duplicate(self):
        template_id = await self.make_template("choice")
        await self.store.toggle_template(template_id)  # A valid disabled template can still run manually.
        event, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(error)
        self.assertEqual(event["status"], "sending")
        duplicate, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(duplicate)
        self.assertIn("уже идёт", error)
        day = service_day(datetime.now(timezone.utc))
        await self.store.ensure_schedule(-100, day, [int(datetime.now(timezone.utc).timestamp()) + 60])
        daily = self.db.connection.execute(
            "SELECT * FROM franc_event_schedules WHERE chat_id=-100 AND service_day=?", (day,)
        ).fetchall()
        self.assertEqual(len(daily), 1)
        await self.store.activate_event(int(event["id"]), 123)
        await self.store.submit_attempt(int(event["id"]), 3, "1")
        again, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(error)
        self.assertIsNotNone(again)

    async def test_manual_command_launches_event_only_for_owner_in_private(self):
        template_id = await self.make_template("luck")
        router = create_franc_event_router(self.db)
        handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "event_manual_command"
        )
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=501)))
        state = SimpleNamespace(clear=AsyncMock())
        message = SimpleNamespace(
            text=f"/event {template_id}", chat=SimpleNamespace(type="private"),
            from_user=User(id=99, is_bot=False, first_name="Чужой"), answer=AsyncMock(),
        )
        await handler(message, bot, state)
        bot.send_message.assert_not_awaited()
        message.from_user = User(id=CUSTOM_COMMAND_OWNER_ID, is_bot=False, first_name="Владелец")
        await handler(message, bot, state)
        bot.send_message.assert_awaited_once()
        self.assertIn("запущено", message.answer.await_args.args[0])
        active = self.db.connection.execute(
            "SELECT * FROM franc_events WHERE status='active'"
        ).fetchone()
        self.assertEqual(active["message_id"], 501)
        await handler(message, bot, state)
        bot.send_message.assert_awaited_once()
        self.assertIn("уже идёт", message.answer.await_args.args[0])

    async def test_button_handler_updates_existing_message(self):
        event = await self.make_active_event("luck")
        router = create_franc_event_router(self.db)
        handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "event_button"
        )
        actor = User(id=3, is_bot=False, first_name="Участник", username="guest")
        callback = SimpleNamespace(
            data=f"fe:{event['id']}:go", from_user=actor,
            message=SimpleNamespace(chat=SimpleNamespace(id=-100)),
            answer=AsyncMock(),
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
            edit_message_text=AsyncMock(), send_message=AsyncMock(),
        )
        with patch("franc_events.random.randint", return_value=1):
            await handler(callback, bot)
        self.assertEqual(await self.db.franc_balance(-100, 3), 15)
        bot.edit_message_text.assert_awaited_once()
        self.assertIn("@guest", bot.edit_message_text.await_args.args[0])
        await handler(callback, bot)
        self.assertEqual(await self.db.franc_balance(-100, 3), 15)

    async def test_user_placeholder_tags_the_participant_on_failure(self):
        template_id = await self.make_template("choice")
        await self.store.change_list(
            template_id, "failure", "edit", value="{user} не угадал", index=0
        )
        event, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(error)
        await self.store.activate_event(int(event["id"]), 900)
        router = create_franc_event_router(self.db)
        handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "event_button"
        )
        callback = SimpleNamespace(
            data=f"fe:{event['id']}:0",
            from_user=User(id=3, is_bot=False, first_name="Участник", username="guest"),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100)), answer=AsyncMock(),
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
            send_message=AsyncMock(), edit_message_text=AsyncMock(),
        )
        await handler(callback, bot)
        body = bot.send_message.await_args.args[1]
        self.assertIn('<a href="tg://user?id=3">@guest</a> не угадал', body)
        bot.edit_message_text.assert_not_awaited()
        self.assertEqual(await self.db.franc_balance(-100, 3), 0)
        self.assertIn(
            '<a href="tg://user?id=3">@guest</a>',
            rendered_phrase("{user} получил {amount} ₣", 3, "Участник", 5, username="guest"),
        )

    async def test_owner_only_constructor_detail_menu(self):
        template_id = await self.make_template("choice")
        router = create_franc_event_router(self.db)
        handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "event_admin_callback"
        )
        private_message = SimpleNamespace(
            chat=SimpleNamespace(type="private"), edit_text=AsyncMock(), answer=AsyncMock(),
        )
        state = SimpleNamespace(clear=AsyncMock())
        callback = SimpleNamespace(
            data=f"evm:detail:{template_id}",
            from_user=User(id=CUSTOM_COMMAND_OWNER_ID, is_bot=False, first_name="Владелец"),
            message=private_message, answer=AsyncMock(),
        )
        await handler(callback, state, SimpleNamespace())
        body = private_message.edit_text.await_args.args[0]
        self.assertIn("Выбор кнопки", body)
        self.assertIn("Фразы:", body)
        private_message.edit_text.reset_mock()
        callback.from_user = User(id=99, is_bot=False, first_name="Чужой")
        await handler(callback, state, SimpleNamespace())
        private_message.edit_text.assert_not_awaited()

    async def test_scheduler_sends_due_event_once(self):
        await self.make_template("choice")
        now = int(datetime.now(timezone.utc).timestamp())
        await self.store.ensure_schedule(-100, service_day(datetime.now(timezone.utc)), [now])
        router = create_franc_event_router(self.db)
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(message_id=321)),
            edit_message_text=AsyncMock(),
        )
        startup = next(item.callback for item in router.startup.handlers)
        shutdown = next(item.callback for item in router.shutdown.handlers)
        try:
            await startup(bot)
            for _ in range(30):
                if bot.send_message.await_count:
                    break
                await asyncio.sleep(0.05)
            bot.send_message.assert_awaited_once()
            active = self.db.connection.execute(
                "SELECT * FROM franc_events WHERE status='active'"
            ).fetchone()
            self.assertEqual(active["message_id"], 321)
        finally:
            await shutdown()
