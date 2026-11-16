import asyncio
from copy import deepcopy
from datetime import datetime
import json
import secrets
import unittest
from unittest.mock import patch
from arena_equipment import CATALOG,PRICES,CHANCES,item_price,public_item
from arena_market import MSK
import test_guild as guild_tests

NOW=int(datetime(2026,11,15,12,tzinfo=MSK).timestamp())


class GearMarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await guild_tests.GuildTests.asyncSetUp(self)
        self.enterContext(patch('arena_market.market_now',return_value=NOW))
        with self.db.connection:
            self.db.connection.execute('UPDATE guild_hunters SET rank=6')
            for actor in (10,20):
                self.db._add_francs_locked(-100,actor,100000)
                self.db._add_francs_locked(-200,actor,100000)
            self.db.connection.execute('INSERT INTO arena_merchant_visits(chat_id,day,visit,starts,ends) VALUES(0,?,1,?,?)',
                ('2026-11-15',NOW-60,NOW+3600))
        self.visit=dict(self.db.connection.execute('SELECT * FROM arena_merchant_visits').fetchone())
        with self.db.connection:self.rows=self.db._gear_guild_stock_locked('S','2026-11-15')

    asyncTearDown=guild_tests.GuildTests.asyncTearDown

    def balance(self,chat=-100,actor=10):
        return self.db.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=? AND user_id=?',(chat,actor)).fetchone()[0]

    def stock(self):return [json.loads(r['data']) for r in self.rows]

    async def buy(self,item,actor=10,chat=-100,nonce=None):
        return await self.db.gear_guild_buy(chat,actor,item['id'],nonce or secrets.token_hex(16),True,expected_price=item_price(item))

    async def sell(self,item,actor=10,**extra):
        v=await self.db.gear_view(-100,actor)
        return await self.db.gear_action(-100,actor,dict(action='sell',item=item['id'],revision=v['revision'],
            character_slot=v['character_slot'],nonce=secrets.token_hex(16),confirm=True,price=public_item(item)['sell_price'],**extra))

    def test_prices_ceiling_and_drop_odds_unchanged(self):
        self.assertEqual(max(max(r) for r in PRICES),20000)
        self.assertEqual(CHANCES,((55,35,10,0,0),(55,35,10,0,0),(15,45,35,5,0),(15,45,35,5,0),(0,20,55,23,2),(0,20,55,23,2),(0,0,55,40,5)))

    async def test_stock_persistent_global_and_no_exclusive_or_hidden_roll(self):
        a=await self.db.gear_guild_view(-100,10,'S');b=await self.db.gear_guild_view(-200,20,'S')
        self.assertEqual(a['offers'],b['offers']);self.assertEqual(sum(i['daily'] for i in a['offers']),4)
        self.assertEqual(sum(not i['daily'] for i in a['offers']),2*len([v for v in CATALOG.values() if v['biome']!='nazarick']))
        for i in a['offers']:
            self.assertNotEqual(i['biome'],'nazarick');self.assertNotEqual(i['rarity'],'legendary');self.assertEqual(i['upgrade'],0)
        self.db.connection.commit();await self.db.close();await self.db.connect()
        self.assertEqual(a['offers'],(await self.db.gear_guild_view(-100,10,'S'))['offers'])

    async def test_buy_once_preserves_properties_and_debits_only_selected_wallet(self):
        item=next(i for i in self.stock() if i['rarity']=='rare');nonce=secrets.token_hex(16);before=self.balance();other=self.balance(-200)
        await self.buy(item,nonce=nonce);await self.buy(item,nonce=nonce)
        self.assertEqual(self.balance(),before-item_price(item));self.assertEqual(self.balance(-200),other)
        owned=(await self.db.gear_view(-100,10))['items'];self.assertEqual(len(owned),1)
        self.assertEqual(owned[0]['affixes'],item['affixes']);self.assertNotEqual(owned[0]['id'],item['id'])
        await self.buy(item)
        self.assertEqual(self.balance(),before-2*item_price(item))
        different=next(i for i in self.stock() if i['id']!=item['id'])
        with self.assertRaises(ValueError):await self.buy(different,nonce=nonce)
        await self.buy(item,actor=20)

    async def test_concurrent_duplicate_offer_cannot_charge_twice(self):
        item=self.stock()[0];before=self.balance();nonce=secrets.token_hex(16)
        results=await asyncio.gather(self.buy(item,nonce=nonce),self.buy(item,nonce=nonce),return_exceptions=True)
        self.assertFalse(any(isinstance(r,Exception) for r in results))
        self.assertEqual(len((await self.db.gear_view(-100,10))['items']),1)
        self.assertEqual(self.balance(),before-item_price(item))

    async def test_rank_funds_expiry_and_rollback(self):
        item=self.stock()[-1]
        with self.db.connection:self.db.connection.execute('UPDATE guild_hunters SET rank=0 WHERE actor_id=10')
        with self.assertRaises(ValueError):await self.buy(item)
        with self.db.connection:
            self.db.connection.execute('UPDATE guild_hunters SET rank=6 WHERE actor_id=10')
            self.db.connection.execute('UPDATE franc_balances SET balance=0 WHERE chat_id=-100 AND user_id=10')
        with self.assertRaises(ValueError):await self.buy(item)
        with self.db.connection:self.db._add_francs_locked(-100,10,100000)
        before=self.balance()
        with patch.object(self.db,'_gear_save_locked',side_effect=RuntimeError('storage')):
            with self.assertRaises(RuntimeError):await self.buy(item)
        self.assertEqual(self.balance(),before)
        epic=next(i for i in self.stock() if i['rarity']=='epic')
        permanent=next(i for i in self.stock() if i['rarity']=='uncommon')
        with patch('arena_market.market_now',return_value=NOW+86400):
            with self.assertRaises(ValueError):await self.buy(epic)
            await self.buy(permanent)

    async def test_permanent_supply_and_one_epic_per_day_across_chats(self):
        stock=self.stock()
        epics=[i for i in stock if i['rarity']=='epic'];normal=next(i for i in stock if i['rarity']=='uncommon')
        await self.buy(epics[0])
        with self.assertRaises(ValueError):await self.buy(epics[1],chat=-200)
        for _ in range(3):await self.buy(normal,chat=-200)
        with patch('arena_market.market_now',return_value=NOW+86400):
            tomorrow=await self.db.gear_guild_view(-100,10,'S')
            self.assertNotEqual([i['id'] for i in tomorrow['offers'] if i['daily']],[i['id'] for i in epics])
            await self.buy(next(i for i in tomorrow['offers'] if i['daily']))

    async def test_old_merchant_endpoint_cannot_buy_and_epic_quota_is_preserved(self):
        before=self.balance()
        with self.assertRaises(ValueError):await self.db.gear_merchant_buy(-100,10,self.stock()[0]['id'],'legacy-request',True)
        self.assertEqual(self.balance(),before)
        with self.db.connection:self.db.connection.execute('INSERT INTO gear_merchant_purchases VALUES(10,?,1,?,?)',('legacy-epic','2026-11-15','epic'))
        with self.assertRaises(ValueError):await self.buy(next(i for i in self.stock() if i['rarity']=='epic'))

    async def test_rank_plus_one_is_not_allowed_and_shop_opens_at_night(self):
        with self.db.connection:self.db.connection.execute('UPDATE guild_hunters SET rank=0 WHERE actor_id=10')
        with patch('arena_market.market_now',return_value=NOW-10*3600):
            own=await self.db.gear_guild_view(-100,10,'F');higher=await self.db.gear_guild_view(-100,10,'E')
            await self.buy(own['offers'][0])
            with self.assertRaises(ValueError):await self.buy(higher['offers'][0])

    async def test_sale_5_percent_no_upgrade_premium_and_replay_safe(self):
        with self.db.connection:
            i=self.db._gear_grant_locked(10,'nz_frost','S','legendary');i['upgrade']=5;self.db._gear_save_locked(10,i)
        self.assertEqual(public_item(i)['sell_price'],item_price(i)//20)
        v=await self.db.gear_view(-100,10);body=dict(action='sell',item=i['id'],revision=v['revision'],character_slot=1,nonce=secrets.token_hex(16),confirm=True,price=item_price(i)//20)
        before=self.balance();await self.db.gear_action(-100,10,body);await self.db.gear_action(-100,10,body)
        self.assertEqual(self.balance(),before+item_price(i)//20);self.assertFalse((await self.db.gear_view(-100,10))['items'])

    async def test_old_20_percent_quote_rejected_then_new_quote_can_be_confirmed(self):
        with self.db.connection:i=self.db._gear_grant_locked(10,'fang','S','legendary')
        v=await self.db.gear_view(-100,10);before=self.balance();other=self.balance(-200)
        body=dict(action='sell',item=i['id'],revision=v['revision'],character_slot=1,
                  nonce=secrets.token_hex(16),confirm=True,price=item_price(i)//5)
        with self.assertRaisesRegex(ValueError,'Цена изменилась'):
            await self.db.gear_action(-100,10,body)
        current=await self.db.gear_view(-100,10)
        self.assertEqual(current['revision'],v['revision'])
        self.assertEqual(current['sell_percent'],5)
        self.assertEqual(len(current['items']),1)
        self.assertEqual(self.balance(),before)
        self.assertEqual(self.db._gear_market_locked(-100,10)['sell_percent'],5)
        body['price']=current['items'][0]['sell_price']
        await self.db.gear_action(-100,10,body)
        await self.db.gear_action(-100,10,body)
        self.assertEqual(self.balance(),before+body['price'])
        self.assertEqual(self.balance(-200),other)

    async def test_stale_buy_and_sale_quotes_do_not_move_money_or_items(self):
        item=self.stock()[0];before=self.balance()
        with patch('arena_gear_market.item_price',return_value=item_price(item)+50):
            with self.assertRaises(ValueError):await self.buy(item)
        self.assertEqual(self.balance(),before)
        with self.db.connection:i=self.db._gear_grant_locked(10,'fang','C','epic')
        v=await self.db.gear_view(-100,10)
        with self.assertRaises(ValueError):
            await self.db.gear_action(-100,10,dict(action='sell',item=i['id'],revision=v['revision'],
                character_slot=1,nonce=secrets.token_hex(16),confirm=True,price=public_item(i)['sell_price']+1))
        self.assertEqual(self.balance(),before);self.assertEqual(len((await self.db.gear_view(-100,10))['items']),1)

    async def test_foreign_favorite_equipped_and_unconfirmed_sales_rejected(self):
        with self.db.connection:i=self.db._gear_grant_locked(10,'fang','C','epic')
        v=await self.db.gear_view(-100,10)
        with self.assertRaises(ValueError):
            await self.db.gear_action(-100,10,dict(action='sell',item=i['id'],revision=v['revision'],character_slot=1,nonce='unconfirmed-sale',confirm=False))
        with self.assertRaises(ValueError):await self.sell(i,actor=20)
        for favorite,equipped in ((True,False),(False,True)):
            with self.db.connection:
                i['favorite']=favorite;self.db._gear_save_locked(10,i)
                if equipped:self.db.connection.execute("INSERT INTO gear_loadouts VALUES(10,1,'weapon',?)",(i['id'],))
            with self.assertRaises(ValueError):await self.sell(i)

    async def test_menu_api_uses_authenticated_actor_not_payload_owner_or_price(self):
        import time
        from aiohttp.test_utils import TestClient,TestServer
        from arena_web import create_arena_app
        from test_arena import signed,TOKEN
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)));await client.start_server()
        try:
            item=self.stock()[0];payload=dict(chat=-100,offer=item['id'],nonce=secrets.token_hex(16),confirm=True,owner=20,price=1,rank='S')
            self.assertEqual((await client.post('/api/guild/equipment',json=payload)).status,400)
            headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
            before=self.balance();other=self.balance(actor=20)
            bad=await client.post('/api/guild/equipment',json=dict(payload,rank='SSS'),headers=headers)
            self.assertEqual(bad.status,400);self.assertEqual(self.balance(),before)
            forged=await client.post('/api/guild/equipment',json=payload,headers=headers)
            self.assertEqual(forged.status,400);self.assertEqual(self.balance(),before)
            payload['price']=item_price(item)
            response=await client.post('/api/guild/equipment',json=payload,headers=headers)
            self.assertEqual(response.status,200,await response.text())
            self.assertEqual(self.balance(),before-item_price(item));self.assertEqual(self.balance(actor=20),other)
            self.assertGreater(len((await response.json())['shop']['offers']),6)
            legacy=await client.post('/api/menu/-100',json=dict(payload,action='buy_gear'),headers=headers)
            self.assertEqual(legacy.status,400)
            gear=await self.db.gear_view(-100,10);owned=gear['items'][0];before_sale=self.balance()
            sale=dict(action='sell_gear',item=owned['id'],nonce=secrets.token_hex(16),
                      gear_revision=gear['revision'],character_slot=gear['character_slot'],
                      confirm=True,price=owned['sell_price'])
            response=await client.post('/api/menu/-100',json=sale,headers=headers)
            self.assertEqual(response.status,200,await response.text())
            self.assertIn('5% оценочной стоимости +0',(await response.json())['notice'])
            self.assertEqual(self.balance(),before_sale+owned['sell_price'])
        finally:await client.close()


if __name__=='__main__':unittest.main()
