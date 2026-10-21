import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User
from aiogram import Router
from arena_characters import CHARACTER_OWNER_ID
from arena_pets import PETS
from database import Database
from handlers.pet_grants import create_pet_grant_router, find_pet
from handlers.character_grants import create_character_grant_router


class PetGrantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'test.sqlite3'
        self.db = Database(self.path)
        await self.db.connect()
        await self.db.upsert_chat(-100, 'Test')
        self.owner = User(id=CHARACTER_OWNER_ID, is_bot=False, first_name='Owner')
        self.player = User(id=10, is_bot=False, first_name='<Player>', username='player')
        self.bot = SimpleNamespace(id=999, get_chat_member=AsyncMock(return_value=SimpleNamespace(user=self.player)))
        self.sequence = 0

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    async def change(self, key, pet='gachi_duck', user=10, revoke=False):
        return await self.db.pet_admin_change(user, pet, CHARACTER_OWNER_ID, key, revoke=revoke)

    def message(self, text='/подарить гачи уточка', *, reply=True, sender=None):
        self.sequence += 1
        return SimpleNamespace(text=text, message_id=self.sequence, from_user=sender or self.owner,
            sender_chat=None, reply_to_message=SimpleNamespace(from_user=self.player, sender_chat=None) if reply else None,
            answer=AsyncMock(), chat=SimpleNamespace(id=-100, type='supergroup'))

    async def dispatch(self, msg):
        await create_pet_grant_router(self.db, 'GnidoBot').propagate_event('message', msg, bot=self.bot)

    async def test_gift_is_global_persistent_and_does_not_change_wallet_or_pity(self):
        before = await self.db.pet_view(10)
        results = await asyncio.gather(*(self.change(str(i)) for i in range(3)))
        self.assertEqual(sum(r['changed'] for r in results), 1)
        view = await self.db.pet_view(10, -100)
        self.assertEqual([p['id'] for p in view['owned']], ['gachi_duck'])
        self.assertEqual(view['owned'][0]['level'], 1)
        self.assertEqual(view['wallet'], dict(before['wallet'], revision=before['wallet']['revision'] + 1))
        self.assertEqual(view['pity'], before['pity'])
        self.assertEqual(view['orders'], [])
        self.assertEqual(view['openings'], [])
        self.assertFalse((await self.db.pet_view(20))['owned'])
        await self.db.close()
        self.db = Database(self.path)
        await self.db.connect()
        self.assertEqual((await self.db.pet_view(10))['owned'][0]['id'], 'gachi_duck')

    async def test_duplicate_keeps_upgrades_and_never_awards_shards(self):
        await self.change('first')
        self.db.connection.execute("UPDATE pet_owned SET level=6,power=1,tempo=1 WHERE user_id=10")
        self.db.connection.commit()
        before = await self.db.pet_view(10)
        result = await self.change('duplicate')
        self.assertFalse(result['changed'])
        after = await self.db.pet_view(10)
        self.assertEqual(after['owned'], before['owned'])
        self.assertEqual(after['wallet'], before['wallet'])

    async def test_revoke_clears_all_equipment_and_keeps_other_pets_and_users(self):
        await self.change('first')
        await self.change('other', 'sandwich')
        await self.change('other-user', user=20)
        self.db.connection.executemany('INSERT INTO pet_equipment VALUES(?,?,?)',
            [(0, 10, 'gachi_duck'), (-100, 10, 'gachi_duck'), (0, 20, 'gachi_duck')])
        self.db.connection.execute("UPDATE pet_owned SET level=6,power=1,tempo=1 WHERE user_id=10 AND pet_id='gachi_duck'")
        self.db.connection.commit()
        before = await self.db.pet_view(10)
        result = await self.change('take', revoke=True)
        self.assertTrue(result['changed'])
        view = await self.db.pet_view(10)
        self.assertEqual([p['id'] for p in view['owned']], ['sandwich'])
        self.assertIsNone(view['equipped'])
        self.assertEqual(view['wallet'], dict(before['wallet'], revision=before['wallet']['revision'] + 1))
        self.assertEqual((await self.db.pet_view(20))['equipped'], 'gachi_duck')
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM pet_equipment WHERE user_id=10').fetchone()[0], 0)
        audit = self.db.connection.execute("SELECT * FROM pet_admin_changes WHERE event_key='take'").fetchone()
        self.assertEqual(json.loads(audit['previous_json'])['level'], 6)
        self.assertFalse((await self.change('absent', revoke=True))['changed'])

    async def test_redelivered_gift_cannot_resurrect_and_old_revoke_cannot_remove_new_gift(self):
        await self.change('give')
        await self.change('take', revoke=True)
        await self.db.close()
        self.db = Database(self.path)
        await self.db.connect()
        self.assertTrue((await self.change('give'))['replay'])
        self.assertFalse((await self.db.pet_view(10))['owned'])
        await self.change('new-gift')
        self.assertTrue((await self.change('take', revoke=True))['replay'])
        self.assertEqual(len((await self.db.pet_view(10))['owned']), 1)
        with self.assertRaises(ValueError):
            await self.change('give', 'sandwich')

    async def test_authorization_ids_and_unknown_pet_are_checked_before_writes(self):
        for actor in (10, None, True, str(CHARACTER_OWNER_ID)):
            with self.assertRaises(ValueError):
                await self.db.pet_admin_change(10, 'gachi_duck', actor, 'denied')
        for target in (0, -1, True, '10', None, 2**63):
            with self.assertRaises(ValueError):
                await self.change('bad-id', user=target)
        with self.assertRaises(ValueError):
            await self.change('bad-pet', 'unknown')
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM pet_admin_changes').fetchone()[0], 0)

    async def test_failed_audit_rolls_back_inventory_change(self):
        self.db.connection.execute("CREATE TRIGGER fail_admin BEFORE INSERT ON pet_admin_changes BEGIN SELECT RAISE(ABORT,'test'); END")
        self.db.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.change('fail')
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM pet_owned').fetchone()[0], 0)

    async def test_reply_gift_revoke_and_redelivery(self):
        msg = self.message()
        await self.dispatch(msg)
        self.assertIn('&lt;Player&gt;', msg.answer.await_args.args[0])
        self.assertIn('подарен', msg.answer.await_args.args[0])
        await self.dispatch(msg)
        self.assertIn('уже обработана', msg.answer.await_args.args[0])
        take = self.message('/забрать гачи уточка')
        await self.dispatch(take)
        self.assertIn('изъят', take.answer.await_args.args[0])
        self.assertFalse((await self.db.pet_view(10))['owned'])

    async def test_explicit_id_and_current_username(self):
        msg = self.message('/подарить@GnidoBot ГАЧИ-УТОЧКА 12345', reply=False)
        await self.dispatch(msg)
        self.assertEqual((await self.db.pet_view(12345))['owned'][0]['id'], 'gachi_duck')
        await self.db.upsert_user(-100, 10, 'player', self.player.full_name)
        msg = self.message('/подарить gachi_duck @PLAYER', reply=False)
        await self.dispatch(msg)
        self.assertEqual((await self.db.pet_view(10))['owned'][0]['id'], 'gachi_duck')
        msg = self.message('/забрать гачи уточка @player', reply=False)
        await self.dispatch(msg)
        self.assertFalse((await self.db.pet_view(10))['owned'])

    async def test_stale_username_help_bot_and_anonymous_are_rejected(self):
        for msg in (self.message(reply=False), self.message('/подарить неизвестный 10')):
            await self.dispatch(msg)
            self.assertIn('/подарить', msg.answer.await_args.args[0])
        await self.db.upsert_user(-100, 10, 'old_name', 'Player')
        msg = self.message('/подарить гачи уточка @old_name', reply=False)
        await self.dispatch(msg)
        self.assertIn('Не удалось', msg.answer.await_args.args[0])
        for msg in (self.message(sender=self.player), self.message('/подарить@OtherBot гачи уточка')):
            await self.dispatch(msg)
            msg.answer.assert_not_awaited()
        msg = self.message()
        msg.sender_chat = SimpleNamespace(id=-100)
        await self.dispatch(msg)
        msg.answer.assert_not_awaited()
        msg = self.message('/подарить гачи уточка 999', reply=False)
        await self.dispatch(msg)
        self.assertIn('Боту питомцы не нужны', msg.answer.await_args.args[0])
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM pet_admin_changes').fetchone()[0], 0)

    async def test_revoke_unlock_and_pet_commands_do_not_conflict(self):
        root = Router()
        root.include_router(create_character_grant_router(self.db, 'GnidoBot'))
        root.include_router(create_pet_grant_router(self.db, 'GnidoBot'))
        msg = self.message('/выдать анлок 10', reply=False)
        await root.propagate_event('message', msg, bot=self.bot)
        self.assertEqual((await self.db.arena_characters(10))['capacity'], 5)
        msg = self.message('/забрать анлок 10', reply=False)
        await root.propagate_event('message', msg, bot=self.bot)
        self.assertEqual((await self.db.arena_characters(10))['capacity'], 1)
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM pet_admin_changes').fetchone()[0], 0)
        msg = self.message()
        await root.propagate_event('message', msg, bot=self.bot)
        self.assertIn('подарен', msg.answer.await_args.args[0])

    def test_names_support_spaces_hyphens_ids_case_and_yo(self):
        for key, pet in PETS.items():
            for name in (key, pet['name'], pet['name'].upper().replace('-', ' ').replace('Ё', 'Е')):
                self.assertEqual(find_pet(name), key)
        self.assertEqual(find_pet('гачи уточка'), 'gachi_duck')
        self.assertIsNone(find_pet('гачи'))
