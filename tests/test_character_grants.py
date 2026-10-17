import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from arena_characters import CHARACTER_OWNER_ID, CHARACTER_PACK, CHARACTER_TERMS_VERSION
from database import Database
from handlers.character_grants import create_character_grant_router


class CharacterGrantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)/'test.sqlite3'
        self.db = Database(self.path)
        await self.db.connect()
        await self.db.upsert_chat(-100, 'Test')
        self.owner = User(id=CHARACTER_OWNER_ID, is_bot=False, first_name='Owner')
        self.player = User(id=10, is_bot=False, first_name='<Player>', username='player')
        self.bot = SimpleNamespace(id=999, get_chat_member=AsyncMock(
            return_value=SimpleNamespace(user=self.player)))

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    def message(self, text='/выдать анлок', *, sender=None, reply=None, private=False):
        return SimpleNamespace(text=text, from_user=sender or self.owner,
            sender_chat=None, reply_to_message=reply, answer=AsyncMock(),
            chat=SimpleNamespace(id=self.owner.id if private else -100,
                                 type='private' if private else 'supergroup'))

    async def dispatch(self, message):
        router = create_character_grant_router(self.db, 'GnidoBot')
        await router.propagate_event('message', message, bot=self.bot)

    async def gift(self, user=10):
        return await self.db.arena_grant_character_slots(user, self.owner.id)

    async def test_grant_global_persistent_audited_and_idempotent(self):
        before = await self.db.arena_characters(10)
        results = await asyncio.gather(*(self.gift() for _ in range(3)))
        self.assertEqual(sum(results), 1)
        view = await self.db.arena_characters(10)
        self.assertEqual(view['capacity'], 5)
        self.assertEqual(view['revision'], before['revision']+1)
        self.assertEqual(view['slots'], [dict(s, locked=False) for s in before['slots']])
        self.assertEqual((await self.db.arena_characters(20))['capacity'], 1)
        row = self.db.connection.execute('SELECT * FROM arena_character_grants').fetchone()
        self.assertEqual((row['user_id'], row['granted_by']), (10, self.owner.id))
        self.assertGreater(row['granted_at'], 0)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM pet_orders').fetchone()[0], 0)
        await self.db.close()
        self.db = Database(self.path)
        await self.db.connect()
        self.assertEqual((await self.db.arena_characters(10))['capacity'], 5)
        with self.assertRaises(ValueError):
            await self.db.pet_create_order(10, CHARACTER_PACK, CHARACTER_TERMS_VERSION)

    async def test_grant_does_not_change_profile_or_money(self):
        await self.db.credit_francs(-100, 10, 123)
        before = await self.db.arena_characters(10)
        await self.gift()
        after = await self.db.arena_characters(10)
        self.assertEqual(after['slots'][0], before['slots'][0])
        self.assertEqual(await self.db.franc_balance(-100,10), 123)
        await self.db.arena_select_character(-100,10,2,after['revision'])
        self.assertEqual((await self.db.arena_characters(10))['active_slot'], 2)

    async def test_only_owner_and_valid_ids(self):
        for actor in (10, None, True):
            with self.assertRaises(ValueError):
                await self.db.arena_grant_character_slots(10,actor)
        for target in (0, -1, True, '10', None, 2**63):
            with self.assertRaises(ValueError):await self.gift(target)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_character_grants').fetchone()[0],0)

    async def test_refund_does_not_revoke_gift_or_switch_active_slot(self):
        order = await self.db.pet_create_order(10, CHARACTER_PACK, CHARACTER_TERMS_VERSION)
        await self.db.pet_payment(10,order['payload'],'XTR',200,'charge')
        await self.gift()
        view = await self.db.arena_characters(10)
        await self.db.arena_select_character(-100,10,2,view['revision'])
        await self.db.pet_start_refund(order['id'])
        await self.db.pet_receive_refund(order['payload'],'XTR',200,'charge')
        view = await self.db.arena_characters(10)
        self.assertEqual((view['capacity'],view['active_slot']), (5,2))

    async def test_gift_blocks_pending_checkout_and_duplicate_payment(self):
        order = await self.db.pet_create_order(10, CHARACTER_PACK, CHARACTER_TERMS_VERSION)
        await self.gift()
        with self.assertRaises(ValueError):
            await self.db.pet_check_order(10,order['payload'],'XTR',200)
        with self.assertRaises(ValueError):
            await self.db.pet_payment(10,order['payload'],'XTR',200,'late-charge')
        self.assertEqual((await self.db.arena_characters(10))['capacity'],5)

    async def test_reply_and_repeat(self):
        msg = self.message(reply=SimpleNamespace(from_user=self.player,sender_chat=None))
        await self.dispatch(msg)
        self.assertEqual((await self.db.arena_characters(10))['capacity'],5)
        self.assertIn('&lt;Player&gt;',msg.answer.await_args.args[0])
        await self.dispatch(msg)
        self.assertIn('уже выдавался',msg.answer.await_args.args[0])

    async def test_id_in_private_without_existing_user(self):
        msg = self.message('/выдать@GnidoBot анлок 12345',private=True)
        await self.dispatch(msg)
        self.assertEqual((await self.db.arena_characters(12345))['capacity'],5)

    async def test_username_global_checked_live_and_deduplicated(self):
        for chat in (-100,-200):
            await self.db.upsert_user(chat,10,'player',self.player.full_name)
        await self.dispatch(self.message('/ВЫДАТЬ АНЛОК @PLAYER',private=True))
        self.assertEqual((await self.db.arena_characters(10))['capacity'],5)
        self.assertEqual(self.bot.get_chat_member.await_count,2)

    async def test_stale_or_unknown_username_not_granted(self):
        await self.db.upsert_user(-100,10,'old_name','Player')
        for token in ('@old_name','@unknown'):
            msg = self.message('/выдать анлок '+token)
            await self.dispatch(msg)
            self.assertIn('не удалось',msg.answer.await_args.args[0].lower())
        self.assertEqual((await self.db.arena_characters(10))['capacity'],1)

    async def test_nonowner_anonymous_and_wrong_bot_commands_denied(self):
        ordinary = self.message('/выдать анлок 10',sender=self.player)
        anonymous = self.message('/выдать анлок 10')
        anonymous.sender_chat = SimpleNamespace(id=-100)
        other_bot = self.message('/выдать@OtherBot анлок 10')
        for msg in (ordinary,anonymous,other_bot):
            await self.dispatch(msg)
            msg.answer.assert_not_awaited()
        self.assertEqual((await self.db.arena_characters(10))['capacity'],1)

    async def test_help_bad_id_and_nonhuman_reply(self):
        messages = [self.message(), self.message('/выдать анлок -1'),
                    self.message('/выдать анлок '+str(2**63)),
                    self.message('/выдать анлок 999'),
                    self.message(reply=SimpleNamespace(sender_chat=SimpleNamespace(id=-100))),
                    self.message(reply=SimpleNamespace(sender_chat=None,from_user=User(
                        id=777,is_bot=True,first_name='Bot')))]
        for msg in messages:
            await self.dispatch(msg)
            msg.answer.assert_awaited_once()
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_character_grants').fetchone()[0],0)


if __name__ == '__main__':unittest.main()
