"""Batch syntax, authorization, rollback, replay and legacy-router coverage."""

import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database, PIROJOK_USERNAME
from handlers.arena import ArenaPublisher, create_arena_router, ITEM_TRANSFER_RE
from handlers.routes import create_router, IMMUNE_USERNAME
from transfer_batch import parse_transfer_message


class TransferParsingTests(unittest.TestCase):
    def test_old_and_list_syntax(self):
        for text in ("/передать @a @b @owner", "/передать рабов @a, @b @owner"):
            request, = parse_transfer_message(text)
            self.assertEqual(request.kind, "slave")
            self.assertEqual(request.entries, (("@a", 1), ("@b", 1)))
            self.assertEqual(request.recipient, "@owner")
        request, = parse_transfer_message("/передать @a @b", reply=True)
        self.assertIsNone(request.recipient)
        self.assertEqual(len(request.entries), 2)

    def test_items_quantity_aliases_and_plural(self):
        for mark in ("x", "х", "×", "*", ":"):
            request, = parse_transfer_message(f"!передать@GnidoBot предметы 42{mark}3, 57 @owner")
            self.assertEqual(request.entries, (("42", 3), ("57", 1)))
        self.assertTrue(ITEM_TRANSFER_RE.match("Передать трактаты 42x3, 57 @owner"))
        self.assertTrue(ITEM_TRANSFER_RE.match("/передать предмет неверно"))

    def test_multiline_mixed_and_wrapped(self):
        requests = parse_transfer_message("/передать\n@a @owner\n\n/передать предмет 42x3\n57 @other")
        self.assertEqual([r.kind for r in requests], ["slave", "item"])
        self.assertEqual(requests[1].entries, (("42", 3), ("57", 1)))
        self.assertEqual(requests[1].recipient, "@other")

    def test_reply_item_explicit_override(self):
        request, = parse_transfer_message("/передать предмет 42x3, 57", reply=True)
        self.assertIsNone(request.recipient)
        request, = parse_transfer_message("/передать предмет 42 @other", reply=True)
        self.assertEqual(request.recipient, "@other")

    def test_invalid_suffixes_empty_numbers_and_limits(self):
        for text in (
            "", "/передать", "/передать @a", "/передать предмет 0 @owner",
            "/передать предмет 42x0 @owner", "/передать предмет 42x10001 @owner",
            "/передать предмет 42x3xxx @owner", "/передать предмет 42,,57 @owner",
            "/передать предмет -42 @owner", "/передать предмет 42 @owner\n/освободить @a",
            "/передать предмет " + " ".join(str(n) for n in range(1, 52)) + " @owner",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_transfer_message(text)


class BatchTransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "batch.sqlite3")
        await self.db.connect()
        self.users = {}
        for uid in (10, 20, 30, 31, 40, 50):
            self.users[uid] = SimpleNamespace(id=uid, username=f"u{uid}", full_name=f"User {uid}", is_bot=uid == 50)
        for chat in (-100, -200):
            await self.db.upsert_chat(chat, "QA")
            for user in self.users.values():
                await self.db.upsert_user(chat, user.id, user.username, user.full_name)
        for uid in (30, 31):
            await self.db.force_enslave(-100, uid, 10)
        self.candy = self.add("candy", "experience", 10)
        self.potion = self.add("potion", "healing", 4)
        self.bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=self.member))

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def member(self, chat, user):
        return SimpleNamespace(status="member", user=self.users[user])

    def add(self, kind, content, quantity, owner=10):
        self.db._arena_add_item_locked(-100, owner, kind, content, "common", quantity)
        self.db.connection.commit()
        return self.db.connection.execute("SELECT id FROM arena_inventory WHERE owner_id=? AND content_id=?", (owner, content)).fetchone()[0]

    def quantity(self, owner=10, content="experience"):
        row = self.db.connection.execute("SELECT quantity FROM arena_inventory WHERE chat_id=0 AND owner_id=? AND content_id=?", (owner, content)).fetchone()
        return row[0] if row else 0

    def slave(self, uid=30, target=20):
        return dict(kind="slave", id=uid, target=target)

    def item(self, uid=None, quantity=3, target=20):
        return dict(kind="item", id=uid or self.candy, target=target, quantity=quantity)

    def message(self, text, *, reply=None, private=False, message_id=101):
        return SimpleNamespace(text=text, caption=None, entities=[], caption_entities=[],
            message_id=message_id, chat=SimpleNamespace(id=10 if private else -100, type="private" if private else "supergroup"),
            from_user=self.users[10], reply_to_message=reply, answer=AsyncMock())

    async def dispatch(self, message, *, item=False):
        if item:
            router = create_arena_router(self.db, self.bot, "GnidoBot", True, ArenaPublisher(self.db, self.bot, "GnidoBot"))
            handler = next(h.callback for h in router.message.handlers if h.callback.__name__ == "transfer_arena_item")
            await handler(message)
        else:
            router = create_router(self.db)
            handler = next(h.callback for h in router.message.handlers if h.callback.__name__ == "transfer_slave")
            await handler(message, self.bot)

    async def assert_unchanged(self):
        self.assertEqual(self.quantity(), 10)
        self.assertEqual(self.quantity(20), 0)
        self.assertEqual((await self.db.get_owner(-100, 30))["owner_id"], 10)
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM transfer_batches").fetchone()[0], 0)

    async def test_mixed_batch_merges_stacks_and_transfers_multiple_slaves(self):
        self.add("candy", "experience", 2, owner=20)
        receipt = await self.db.transfer_batch(-100, 10, [self.slave(), self.slave(31), self.item(), self.item(quantity=2), self.item(self.potion, 4)])
        self.assertEqual(len(receipt), 5)
        self.assertEqual(self.quantity(), 5)
        self.assertEqual(self.quantity(20), 7)
        self.assertEqual(self.quantity(20, "healing"), 4)
        for uid in (30, 31):
            self.assertEqual((await self.db.get_owner(-100, uid))["owner_id"], 20)

    async def test_missing_item_rolls_back_ownership_workers_and_first_item(self):
        await self.db.create_business(-100, 10, "field")
        await self.db.set_business_worker_role(-100, 10, 30, "collector")
        with self.assertRaises(ValueError):
            await self.db.transfer_batch(-100, 10, [self.slave(), self.item(), self.item(999999)], source_chat=-100, message_id=1)
        await self.assert_unchanged()
        worker = self.db.connection.execute("SELECT owner_id FROM business_workers WHERE chat_id=-100 AND worker_id=30").fetchone()
        self.assertEqual(worker[0], 10)

    async def test_success_removes_old_worker_and_survives_restart(self):
        await self.db.create_business(-100, 10, "field")
        await self.db.set_business_worker_role(-100, 10, 30, "collector")
        await self.db.transfer_batch(-100, 10, [self.slave(), self.slave(31)])
        await self.db.close()
        await self.db.connect()
        self.assertEqual((await self.db.get_owner(-100, 30))["owner_id"], 20)
        self.assertIsNone(self.db.connection.execute("SELECT * FROM business_workers WHERE chat_id=-100 AND worker_id=30").fetchone())

    async def test_insufficient_total_quantity_and_legacy_alias_roll_back(self):
        self.db.connection.execute("INSERT INTO arena_global_item_aliases VALUES(900001,?,10)", (self.candy,))
        self.db.connection.commit()
        with self.assertRaises(ValueError):
            await self.db.transfer_batch(-100, 10, [self.item(quantity=6), self.item(900001, 5)])
        await self.assert_unchanged()

    async def test_recipient_rules_duplicate_and_wrong_owner(self):
        for operations in (
            [self.slave(), self.slave(40)], [self.slave(), self.slave()],
            [self.slave(target=31)], [self.slave(target=30)], [self.slave(target=10)],
            [self.item(), self.item(target=10)], [self.item(quantity=0)],
        ):
            with self.subTest(operations=operations), self.assertRaises(ValueError):
                await self.db.transfer_batch(-100, 10, operations)
            await self.assert_unchanged()

    async def test_exception_in_middle_rolls_back_everything(self):
        with patch.object(self.db, "_arena_add_item_locked", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                await self.db.transfer_batch(-100, 10, [self.slave(), self.item()], source_chat=-100, message_id=3)
        await self.assert_unchanged()

    async def test_replay_and_edit_protection_persist(self):
        operations = [self.slave(), self.item(quantity=10)]
        receipt = await self.db.transfer_batch(-100, 10, operations, source_chat=-100, message_id=4)
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.transfer_batch(-100, 10, operations, source_chat=-100, message_id=4), receipt)
        self.assertEqual(self.quantity(20), 10)
        with self.assertRaises(ValueError):
            await self.db.transfer_batch(-100, 10, [self.item(quantity=1)], source_chat=-100, message_id=4)
        self.assertEqual(self.quantity(20), 10)

    async def test_concurrent_duplicates_only_spend_once(self):
        results = await asyncio.gather(*[self.db.transfer_batch(-100, 10, [self.item(quantity=10)], source_chat=-100, message_id=5) for _ in range(2)])
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.quantity(20), 10)

    async def test_modules_respected_in_mixed_batch(self):
        self.db.connection.execute("INSERT INTO chat_feature_modules(chat_id,disabled_json,updated_at) VALUES(-100,?,0)", (json.dumps(["arena"]),))
        self.db.connection.commit()
        with self.assertRaises(ValueError):
            await self.db.transfer_batch(-100, 10, [self.slave(), self.item()])
        await self.assert_unchanged()

    async def test_group_list_and_multiline_mixed_with_different_recipients(self):
        message = self.message(f"/передать @u30, @u31 @u20\n/передать предмет {self.candy}x3 @u40")
        await self.dispatch(message)
        self.assertEqual((await self.db.get_owner(-100, 31))["owner_id"], 20)
        self.assertEqual(self.quantity(40), 3)
        self.assertEqual(message.answer.await_count, 1)

    async def test_item_router_handles_mixed_and_reply(self):
        message = self.message(f"/передать предмет {self.candy}x2\n/передать @u30 @u31", reply=SimpleNamespace(sender_chat=None, from_user=self.users[20]))
        await self.dispatch(message, item=True)
        self.assertEqual(self.quantity(20), 2)
        self.assertEqual((await self.db.get_owner(-100, 30))["owner_id"], 20)

    async def test_private_selected_chat_numeric_recipient_and_quantities(self):
        await self.db.select_menu_chat(10, -200)
        message = self.message(f"/передать предмет {self.candy}x2, {self.potion}x3 20", private=True)
        # A reply to the bot in private must not replace the explicit numeric recipient.
        message.reply_to_message = SimpleNamespace(sender_chat=None, from_user=self.users[50])
        await self.dispatch(message, item=True)
        self.assertEqual(self.quantity(20), 2)
        self.assertEqual(self.quantity(20, "healing"), 3)
        self.bot.get_chat_member.assert_any_await(-200, 20)

    async def test_unknown_stale_bot_nonmember_and_private_slave_reject_entire_batch(self):
        for tag in ("@unknown", "@u50"):
            message = self.message(f"/передать предмет {self.candy} @u20\n/передать @u30 {tag}")
            await self.dispatch(message, item=True)
            await self.assert_unchanged()
        self.users[20].username = "new_name"
        await self.dispatch(self.message(f"/передать предмет {self.candy} @u20"), item=True)
        await self.assert_unchanged()
        self.users[20].username = "u20"
        self.bot.get_chat_member.side_effect = None
        self.bot.get_chat_member.return_value = SimpleNamespace(status="left", user=self.users[20])
        await self.dispatch(self.message(f"/передать предмет {self.candy} @u20"), item=True)
        await self.assert_unchanged()
        await self.dispatch(self.message("/передать @u30 @u20", private=True))
        await self.assert_unchanged()

    async def test_immunity_in_second_entry_rejects_whole_message(self):
        await self.db.upsert_user(-100, 31, IMMUNE_USERNAME, "Immune")
        message = self.message(f"/передать предмет {self.candy} @u20\n/передать 30 31 @u20")
        await self.dispatch(message, item=True)
        await self.assert_unchanged()

    async def test_numeric_recipient_cannot_bypass_current_username_restriction(self):
        # Stored username is stale; the live recipient is the restricted owner.
        self.users[20].username = PIROJOK_USERNAME
        message = self.message(f"/передать предмет {self.candy} 20\n/передать 30 20")
        await self.dispatch(message, item=True)
        await self.assert_unchanged()

    async def test_caption_and_repeated_message_do_not_double_transfer(self):
        message = self.message(f"/передать предмет {self.candy}x3 @u20")
        message.caption, message.text = message.text, None
        await self.dispatch(message, item=True)
        await self.dispatch(message, item=True)
        self.assertEqual(self.quantity(20), 3)

    async def test_parse_or_last_quantity_error_does_not_partially_transfer(self):
        for text in (f"/передать @u30 @u20\n/передать предмет {self.candy}x11 @u20", "/передать @u30 @u20\n/передать предмет ? @u20"):
            message = self.message(text)
            await self.dispatch(message)
            self.assertIn("Ничего не передано", message.answer.await_args.args[0])
            await self.assert_unchanged()
