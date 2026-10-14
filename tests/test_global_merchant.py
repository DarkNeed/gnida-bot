"""Shared merchant schedule/limits; local money, durable migration and claims."""
import asyncio
import sqlite3
import time
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from arena_web import create_arena_app

import test_arena_market as market
import test_character_slots as slots


class GlobalMerchantTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = market.ArenaMarketTests.asyncSetUp
    asyncTearDown = market.ArenaMarketTests.asyncTearDown
    open_shop = market.ArenaMarketTests.open_shop
    unlock = slots.SlotTests.unlock
    select = slots.SlotTests.select

    async def fund(self, chat=2, user=10):
        await self.db.credit_francs(chat, user, 10000)

    async def test_same_schedule_ids_assortment_balances_remain_local(self):
        a = await self.open_shop()
        b = (await self.db.arena_market_view(2, 10))['merchant']
        self.assertEqual(a, b)
        self.assertEqual(self.db.connection.execute(
            'SELECT COUNT(*) FROM arena_merchant_visits WHERE chat_id<>0').fetchone()[0], 0)
        await self.fund()
        offer = next(o for o in a['offers'] if o['kind'] == 'passive')
        await self.db.arena_buy_item(2, 10, offer['id'])
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)
        self.assertEqual(await self.db.franc_balance(2, 10), 10000 - offer['price'])
        for chat in (1, 2):
            view = await self.db.arena_market_view(chat, 10)
            self.assertEqual(len(view['inventory']), 1)
            self.assertEqual(next(o for o in view['merchant']['offers'] if o['id'] == offer['id'])['remaining'], 0)

    async def test_concurrent_purchase_across_chats_only_one_debit(self):
        offer = next(o for o in (await self.open_shop())['offers'] if o['kind'] == 'skill')
        await self.fund()
        results = await asyncio.gather(
            self.db.arena_buy_item(1, 10, offer['id']),
            self.db.arena_buy_item(2, 10, offer['id']), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(await self.db.franc_balance(1, 10) + await self.db.franc_balance(2, 10), 20000 - offer['price'])
        self.assertEqual(self.db.connection.execute('SELECT SUM(quantity) FROM arena_inventory WHERE owner_id=10').fetchone()[0], 1)

    async def test_switch_character_does_not_reset_limit_or_give_extra_items(self):
        offer = next(o for o in (await self.open_shop())['offers'] if o['kind'] == 'passive')
        await self.db.arena_buy_item(1, 10, offer['id'])
        await self.unlock()
        await self.select(2)
        await self.fund()
        with self.assertRaisesRegex(ValueError, 'Лимит'):
            await self.db.arena_buy_item(2, 10, offer['id'])
        self.assertEqual(await self.db.franc_balance(2, 10), 10000)
        self.assertEqual((await self.db.arena_market_view(2, 10))['inventory'][0]['quantity'], 1)

    async def test_other_account_has_own_limit_and_insufficient_money_is_local(self):
        offer = next(o for o in (await self.open_shop())['offers'] if o['kind'] == 'potion')
        with self.assertRaisesRegex(ValueError, 'Не хватает'):
            await self.db.arena_buy_item(2, 10, offer['id'])
        for _ in range(3):
            await self.db.arena_buy_item(1, 10, offer['id'])
        await self.fund(2, 20)
        await self.db.arena_buy_item(2, 20, offer['id'])
        remaining = next(o for o in (await self.db.arena_market_view(1, 20))['merchant']['offers'] if o['id'] == offer['id'])['remaining']
        self.assertEqual(remaining, 2)

    async def test_new_visit_resets_limit_not_refresh_or_restart(self):
        shop = await self.open_shop()
        offer = next(o for o in shop['offers'] if o['kind'] == 'potion')
        for _ in range(3):
            await self.db.arena_buy_item(1, 10, offer['id'])
        await self.db.close()
        await self.db.connect()
        with self.assertRaisesRegex(ValueError, 'Лимит'):
            await self.db.arena_buy_item(1, 10, offer['id'])
        evening = self.db.connection.execute('SELECT * FROM arena_merchant_visits WHERE chat_id=0 AND day=? AND visit=2',
                                             ('2026-10-10',)).fetchone()
        self.db.connection.execute('UPDATE arena_merchant_visits SET ends=? WHERE id=?', (self.now, shop['visit_id']))
        self.db.connection.execute('UPDATE arena_merchant_visits SET starts=?,ends=? WHERE id=?',
                                   (self.now - 1, self.now + 3600, evening['id']))
        self.db.connection.commit()
        new = next(o for o in (await self.db.arena_market_view(2, 10))['merchant']['offers'] if o['kind'] == 'potion')
        self.assertEqual(new['remaining'], 3)
        await self.fund()
        await self.db.arena_buy_item(2, 10, new['id'])
        with self.assertRaisesRegex(ValueError, 'устарело'):
            await self.db.arena_buy_item(1, 10, offer['id'])

    async def test_database_failure_rolls_back_debit_inventory_and_limit(self):
        offer = next(o for o in (await self.open_shop())['offers'] if o['kind'] == 'potion')
        self.db.connection.execute("CREATE TRIGGER fail_purchase BEFORE INSERT ON arena_merchant_purchases BEGIN SELECT RAISE(ABORT,'fail'); END")
        self.db.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.db.arena_buy_item(1, 10, offer['id'])
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)
        self.assertEqual((await self.db.arena_market_view(1, 10))['inventory'], [])
        self.assertEqual(self.db._arena_merchant_bought_locked(dict(day='2026-10-10', visit=1), 10, 'potion', 'healing'), 0)

    async def legacy(self, quantity=2):
        shop = await self.open_shop()
        offer = next(o for o in shop['offers'] if o['kind'] == 'potion')
        await self.db.arena_buy_item(1, 10, offer['id'])
        self.db.connection.execute("DELETE FROM arena_market_migrations WHERE name='account_merchant_v1'")
        self.db.connection.execute('UPDATE arena_merchant_visits SET chat_id=-100,notified=1 WHERE id=?', (shop['visit_id'],))
        old = self.db.connection.execute('''INSERT INTO arena_merchant_visits(chat_id,day,visit,starts,ends,notified)
            SELECT -200,day,visit,starts,ends,0 FROM arena_merchant_visits WHERE id=?''', (shop['visit_id'],)).lastrowid
        old_offer = self.db.connection.execute('''INSERT INTO arena_merchant_offers(visit_id,kind,content_id,rarity,price,per_user)
            SELECT ?,kind,content_id,rarity,price,per_user FROM arena_merchant_offers WHERE id=?''', (old, offer['id'])).lastrowid
        self.db.connection.execute('INSERT INTO arena_merchant_purchases VALUES(?,?,?)', (old_offer, 10, quantity))
        self.db.connection.commit()
        return shop, offer, old_offer

    async def test_legacy_migration_preserves_ids_sums_limits_backup_and_claims(self):
        await self.db.arena_menu(-100, 10)
        await self.db.arena_menu(-200, 10)
        shop, offer, old_offer = await self.legacy()
        before = await self.db.franc_balance(1, 10)
        await self.db.close()
        await self.db.connect()
        view = (await self.db.arena_market_view(2, 10))['merchant']
        self.assertEqual(view['visit_id'], shop['visit_id'])
        item = next(o for o in view['offers'] if o['id'] == offer['id'])
        self.assertEqual((item['bought'], item['remaining']), (3, 0))
        with self.assertRaisesRegex(ValueError, 'Лимит'):
            await self.db.arena_buy_item(1, 10, offer['id'])
        with self.assertRaisesRegex(ValueError, 'устарело'):
            await self.db.arena_buy_item(2, 10, old_offer)
        self.assertEqual(await self.db.franc_balance(1, 10), before)
        self.assertEqual((await self.db.arena_market_view(1, 10))['inventory'][0]['quantity'], 1)
        self.assertEqual([r['chat_id'] for r in await self.db.arena_due_merchants()], [-200])
        backups = list((self.db.path.parent / 'backups').glob('before-global-merchant-*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as snapshot:
            self.assertEqual(snapshot.execute('SELECT chat_id FROM arena_merchant_visits WHERE id=?', (shop['visit_id'],)).fetchone()[0], -100)
            self.assertEqual(snapshot.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.arena_due_merchants(), [])
        self.assertEqual(len(list((self.db.path.parent / 'backups').glob('before-global-merchant-*.sqlite3'))), 1)
        self.assertEqual(next(o for o in (await self.db.arena_market_view(1, 10))['merchant']['offers'] if o['id'] == offer['id'])['bought'], 3)

    async def test_legacy_over_limit_is_clamped_and_no_new_reward_or_charge(self):
        _, offer, _ = await self.legacy(quantity=5)
        self.db._connect_global_merchant()
        item = next(o for o in (await self.db.arena_market_view(2, 10))['merchant']['offers'] if o['id'] == offer['id'])
        self.assertEqual((item['bought'], item['remaining']), (6, 0))
        self.assertEqual((await self.db.arena_market_view(1, 10))['inventory'][0]['quantity'], 1)

    async def test_disabled_chat_cannot_buy_or_get_notifications_but_does_not_change_shop(self):
        shop = await self.open_shop()
        await self.db.arena_menu(-100, 10)
        await self.db.arena_menu(-200, 10)
        modules = await self.db.arena_modules(-100)
        await self.db.arena_set_module(-100, 1980056841, 'arena', False, modules['revision'])
        due = await self.db.arena_due_merchants()
        self.assertEqual([r['chat_id'] for r in due], [-200])
        with self.assertRaisesRegex(ValueError, 'выключен'):
            await self.db.arena_buy_item(-100, 10, shop['offers'][0]['id'])
        with self.assertRaisesRegex(ValueError, 'выключен'):
            await self.db.arena_market_view(-100, 10)
        modules = await self.db.arena_modules(-100)
        await self.db.arena_set_module(-100, 1980056841, 'arena', True, modules['revision'])
        self.assertEqual((await self.db.arena_market_view(-100, 10))['merchant']['visit_id'], shop['visit_id'])
        self.assertEqual([r['chat_id'] for r in await self.db.arena_due_merchants()], [-100])

    async def test_migration_failure_rolls_back_promotion_and_marker(self):
        shop, _, _ = await self.legacy()
        self.db.connection.execute("CREATE TRIGGER fail_migration BEFORE INSERT ON arena_market_migrations WHEN NEW.name='account_merchant_v1' BEGIN SELECT RAISE(ABORT,'fail'); END")
        self.db.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._connect_global_merchant()
        self.assertEqual(self.db.connection.execute('SELECT chat_id FROM arena_merchant_visits WHERE id=?', (shop['visit_id'],)).fetchone()[0], -100)
        self.assertFalse(self.db.connection.execute("SELECT 1 FROM arena_market_migrations WHERE name='account_merchant_v1'").fetchone())
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_merchant_notifications').fetchone()[0], 0)

    async def test_migration_does_not_revive_expired_canonical_visit(self):
        shop, offer, _ = await self.legacy()
        self.db.connection.execute('UPDATE arena_merchant_visits SET starts=?,ends=? WHERE id=?',
                                   (self.now - 8000, self.now - 100, shop['visit_id']))
        self.db.connection.commit()
        self.db._connect_global_merchant()
        self.assertEqual((await self.db.arena_market_view(2, 10))['merchant']['offers'], [])
        with self.assertRaisesRegex(ValueError, 'устарело'):
            await self.db.arena_buy_item(1, 10, offer['id'])

    async def test_signed_http_purchase_uses_invoking_chat_and_authenticated_account(self):
        offer = next(o for o in (await self.open_shop())['offers'] if o['kind'] == 'potion')
        await self.fund()
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, market.TOKEN)))
        await client.start_server()
        try:
            headers = {'X-Telegram-Init-Data': market.signed(now=int(time.time()))}
            response = await client.post('/api/menu/2', headers=headers,
                json=dict(action='buy_item', offer=offer['id'], user=20, actor=20, chat_id=1, price=0))
            self.assertEqual(response.status, 200, await response.text())
            menu = (await response.json())['menu']
            self.assertEqual(menu['balance'], 10000 - offer['price'])
            self.assertEqual(await self.db.franc_balance(1, 10), 10000)
            self.assertEqual(menu['inventory'][0]['owner_id'], 10)
            self.bot.get_chat_member.return_value = SimpleNamespace(status='left')
            response = await client.post('/api/menu/1', headers=headers,
                json=dict(action='buy_item', offer=offer['id']))
            self.assertEqual(response.status, 400)
            self.assertEqual(await self.db.franc_balance(1, 10), 10000)
        finally:
            await client.close()
