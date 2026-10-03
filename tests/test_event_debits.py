"""Signed event amounts debit balances once without creating debt."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from database import Database
from franc_events import FrancEventStore, event_config
from handlers.franc_events import create_franc_event_router


class EventDebitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "events.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(-100, "Тест")
        self.store = FrancEventStore(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    async def make_event(self, kind, *, reward=-50, failure=False, custom=False):
        template_id = await self.store.create_template(-100, kind)
        await self.store.update_scalar(template_id, "prompt", "Выбирай")
        if kind == "choice":
            for label in ("А", "Б"):
                await self.store.change_list(template_id, "options", "add", value=label)
        elif kind == "text":
            await self.store.change_list(template_id, "answers", "add", value="да")
        if custom:
            await self.store.toggle_outcome_mode(template_id)
            for index in range(2):
                self.assertEqual(await self.store.change_outcome(
                    template_id, kind, "reward", index=index, value=str(reward)
                ), "updated")
                await self.store.change_outcome(
                    template_id, kind, "message_add", index=index, value="Изменение: {amount} ₣"
                )
        else:
            field = "failure" if failure else "success"
            await self.store.update_scalar(template_id, f"{field}_reward", str(reward))
            await self.store.change_list(
                template_id, field, "edit", index=0, value="Изменение: {amount} ₣"
            )
            if kind == "luck":
                await self.store.update_scalar(template_id, "success_chance", 0 if failure else 100)
        event, error = await self.store.begin_manual_event(template_id)
        self.assertIsNone(error)
        await self.store.activate_event(int(event["id"]), 123)
        if kind == "luck":
            action = "go"
        elif kind == "choice":
            action = "1" if failure else "0"
        else:
            action = "нет" if failure else "да"
        return await self.store.get_event(int(event["id"])), action

    async def test_debits_for_every_event_mode_and_success_or_failure(self):
        cases = [
            ("choice", False, False), ("choice", True, False),
            ("text", False, False), ("text", True, False),
            ("luck", False, False), ("luck", True, False),
            ("choice", False, True), ("luck", False, True),
        ]
        for user_id, (kind, failure, custom) in enumerate(cases, start=10):
            with self.subTest(kind=kind, failure=failure, custom=custom):
                await self.db.credit_francs(-100, user_id, 80)
                event, action = await self.make_event(kind, failure=failure, custom=custom)
                result = await self.store.submit_attempt(int(event["id"]), user_id, action)
                self.assertEqual(result["reward"], -50)
                self.assertEqual(await self.db.franc_balance(-100, user_id), 30)
                self.assertEqual(result["resolved"], custom or not failure or kind == "luck")
                repeat = await self.store.submit_attempt(int(event["id"]), user_id, action)
                self.assertIn(repeat["status"], {"already", "closed"})
                self.assertEqual(await self.db.franc_balance(-100, user_id), 30)
                recorded = self.db.connection.execute(
                    "SELECT reward FROM franc_event_attempts WHERE event_id=? AND user_id=?",
                    (int(event["id"]), user_id),
                ).fetchone()
                self.assertEqual(recorded["reward"], -50)
                await self.store.expire_event(int(event["id"]))

    async def test_insufficient_empty_and_missing_balances_never_create_debt(self):
        for user_id, starting in ((10, 30), (11, 0), (12, None)):
            with self.subTest(starting=starting):
                if starting is not None:
                    await self.db.credit_francs(-100, user_id, starting or 1)
                    if starting == 0:
                        await self.db.spend_francs(-100, user_id, 1)
                event, action = await self.make_event("luck")
                result = await self.store.submit_attempt(int(event["id"]), user_id, action)
                self.assertEqual(result["reward"], -(starting or 0))
                self.assertEqual(await self.db.franc_balance(-100, user_id), 0)
                recorded = self.db.connection.execute(
                    "SELECT reward FROM franc_event_attempts WHERE event_id=?", (int(event["id"]),)
                ).fetchone()
                self.assertEqual(recorded["reward"], -(starting or 0))

    async def test_signed_amount_validation_does_not_allow_negative_weights(self):
        template_id = await self.store.create_template(-100, "luck")
        for field in ("success_reward", "failure_reward"):
            await self.store.update_scalar(template_id, field, "-500")
            self.assertEqual((await self.store.get_template(template_id))[field], -500)
            with self.assertRaises(ValueError):
                await self.store.update_scalar(template_id, field, "-501")
        await self.store.toggle_outcome_mode(template_id)
        for value in ("-501", "501", "--50", "-1.5", "no"):
            self.assertEqual(await self.store.change_outcome(
                template_id, "luck", "reward", index=0, value=value
            ), "invalid")
        self.assertEqual(await self.store.change_outcome(
            template_id, "luck", "weight", index=0, value="-5"
        ), "invalid")
        self.assertEqual(await self.store.change_outcome(
            template_id, "luck", "reward", index=0, value=" -50 "
        ), "updated")
        self.assertEqual(event_config(await self.store.get_template(template_id))["luck_outcomes"][0]["reward"], -50)

    async def test_concurrent_clicks_debit_once_and_survive_restart(self):
        await self.db.credit_francs(-100, 10, 100)
        event, action = await self.make_event("choice", failure=True)
        await self.store.update_scalar(int(event["template_id"]), "failure_reward", "-100")
        self.assertEqual(json.loads(event["snapshot_json"])["failure_reward"], -50)
        await self.db.close()
        await self.db.connect()
        results = await asyncio.gather(*[
            self.store.submit_attempt(int(event["id"]), 10, action) for _ in range(5)
        ])
        self.assertEqual([r["status"] for r in results].count("failure"), 1)
        self.assertEqual([r["status"] for r in results].count("already"), 4)
        self.assertEqual(await self.db.franc_balance(-100, 10), 50)

    async def test_public_result_uses_actual_signed_amount_without_extra_text(self):
        await self.db.credit_francs(-100, 10, 30)
        event, _ = await self.make_event("luck", failure=True)
        router = create_franc_event_router(self.db)
        handler = next(item.callback for item in router.callback_query.handlers
                       if item.callback.__name__ == "event_button")
        callback = SimpleNamespace(
            data=f"fe:{event['id']}:go",
            from_user=User(id=10, is_bot=False, first_name="Участник"),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100)), answer=AsyncMock(),
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
            edit_message_text=AsyncMock(), send_message=AsyncMock(),
        )
        await handler(callback, bot)
        self.assertEqual(bot.edit_message_text.await_args.args[0], "Изменение: -30 ₣")
        self.assertEqual(await self.db.franc_balance(-100, 10), 0)
