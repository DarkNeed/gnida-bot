"""Regression cases: irreversible virtual-item operations use disposable databases."""
import asyncio
import time
from datetime import datetime
from uuid import uuid4
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer

import test_arena_forge as fixtures
from arena_engine import BUILTIN_SKILLS
from arena_forge import forge_distribution
from arena_web import create_arena_app
from test_arena import signed, TOKEN
import test_arena_epic as combat_fixtures
from arena_engine import effective_stat, unlocked_skill_ids
from arena_market import MSK
from arena_relics import TICKET_ID


class EconomyComplaintTests(IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ForgeTests.asyncSetUp
    asyncTearDown=fixtures.ForgeTests.asyncTearDown
    add=fixtures.ForgeTests.add
    qty=fixtures.ForgeTests.qty
    resources=fixtures.ForgeTests.resources
    request=fixtures.ForgeTests.request
    perform=fixtures.ForgeTests.perform

    async def test_page_exchange_directions_loss_and_replay(self):
        self.resources(pages={'epic':3})
        request=await self.request('exchange',rarity='epic',direction='down',quantity=3)
        notices=await asyncio.gather(*(self.db.arena_forge_action(1,10,request) for _ in range(2)))
        self.assertEqual(notices[0],notices[1])
        self.assertEqual((await self.db.arena_forge_view(1,10))['pages'],{'epic':0,'rare':6})
        await self.perform('exchange',rarity='rare',direction='up',quantity=1)
        self.assertEqual((await self.db.arena_forge_view(1,10))['pages'],{'epic':1,'rare':1})
        self.assertEqual(await self.db.franc_balance(1,10),10000)
        self.assertFalse((await self.db.arena_forge_view(1,20))['pages'])
        await self.db.close();await self.db.connect()
        self.assertEqual(await self.db.arena_forge_action(1,10,request),notices[0])
        with self.assertRaises(ValueError):
            await self.db.arena_forge_action(1,10,dict(request,quantity=1))

    async def test_exchange_validation_and_atomic_insufficient_balance(self):
        self.resources(pages={'rare':4})
        for fields in (dict(rarity='common',direction='down',quantity=1),dict(rarity='legendary',direction='up',quantity=1),
                       dict(rarity='rare',direction='up',quantity=1),dict(rarity='rare',direction='down',quantity=True),
                       dict(rarity=[],direction='up',quantity=1),dict(rarity='rare',direction='down',quantity=0)):
            with self.subTest(fields=fields),self.assertRaises(ValueError):await self.perform('exchange',**fields)
        self.assertEqual((await self.db.arena_forge_view(1,10))['pages'],{'rare':4})

    async def test_legendary_roll_is_real_and_not_boss_loot(self):
        self.resources(pages={'epic':12})
        catalog=self.db._forge_catalog_locked()
        for kind in ('skill','passive'):
            self.assertEqual(forge_distribution(catalog,kind,[('epic',1)],pages=True)['legendary'],1)
            with patch('arena_forge.random.SystemRandom') as rng:
                rng.return_value.random.return_value=.995
                rng.return_value.choice.side_effect=lambda pool:pool[0]
                await self.perform('craft',kind=kind,rarity='epic')
        rows=self.db._arena_inventory_locked(1,10)
        self.assertEqual({(r['kind'],r['rarity']) for r in rows},{('skill','legendary'),('passive','legendary')})
        for r in rows:
            if r['kind']=='skill':self.assertNotIn('raid_loot',BUILTIN_SKILLS[r['content_id']].tags)
        await self.perform('dismantle',items=[dict(id=r['id'],quantity=1) for r in rows])
        self.assertEqual((await self.db.arena_forge_view(1,10))['pages']['legendary'],4)

    async def test_sale_partial_batch_replay_foreign_and_paid_ticket(self):
        item=self.add('last_argument',5)
        nonce=uuid4().hex
        notices=await asyncio.gather(*(self.db.arena_sell_item(1,10,item,2,nonce,True) for _ in range(2)))
        self.assertEqual(notices[0],notices[1]);self.assertEqual(self.qty('last_argument'),3)
        self.assertEqual(await self.db.franc_balance(1,10),10500)
        self.assertEqual(await self.db.franc_balance(2,10),10000)
        with self.assertRaises(ValueError):await self.db.arena_sell_item(1,20,item,1,uuid4().hex,True)
        with self.assertRaises(ValueError):await self.db.arena_sell_item(1,10,item,4,uuid4().hex,True)
        with self.assertRaises(ValueError):await self.db.arena_sell_item(1,10,item,1,nonce,True)
        self.db._arena_add_item_locked(1,10,'class_ticket',TICKET_ID,'legendary');self.db.connection.commit()
        ticket=self.db.connection.execute("SELECT id FROM arena_inventory WHERE kind='class_ticket'").fetchone()[0]
        with self.assertRaises(ValueError):await self.db.arena_sell_item(1,10,ticket,1,uuid4().hex,True)
        self.assertEqual(self.qty('last_argument'),3)
        await self.db.close();await self.db.connect()
        self.assertEqual(await self.db.arena_sell_item(1,10,item,2,nonce,True),notices[0])

    async def test_free_and_dependent_scrolls_excluded_but_working_cross_class_retained(self):
        own=dict(kind='skill',content_id='dust_in_eyes')
        self.assertIn('бесплатно',self.db._arena_purchase_warning_locked(1,10,own))
        foreign=dict(kind='skill',content_id='mana_overload')
        self.assertIn('механику',self.db._arena_purchase_warning_locked(1,10,foreign))
        self.assertEqual(self.db._arena_purchase_warning_locked(1,10,dict(kind='skill',content_id='smack')),'')
        self.db._arena_profile_locked(1,10,True)
        self.db.connection.execute("UPDATE personal_profiles SET class_id='mage' WHERE chat_id=0 AND user_id=10")
        catalog=self.db._forge_catalog_locked(1,10)
        self.assertIn(('skill','smack'),catalog)
        self.assertIn(('skill','catch_breath'),catalog)
        self.assertNotIn(('skill','mana_focus'),catalog)
        self.assertNotIn(('skill','mana_overload'),catalog)

    async def test_sale_failure_rolls_back_items_money_and_receipt(self):
        item=self.add('last_argument',2)
        with patch.object(self.db,'_add_francs_locked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):await self.db.arena_sell_item(1,10,item,1,uuid4().hex,True)
        self.assertEqual(self.qty('last_argument'),2)
        self.assertEqual(await self.db.franc_balance(1,10),10000)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_merchant_sales').fetchone()[0],0)

    async def test_server_rejects_free_and_trait_only_purchases_without_payment(self):
        now=int(datetime(2026,10,31,12,tzinfo=MSK).timestamp())
        visit=self.db.connection.execute("INSERT INTO arena_merchant_visits(chat_id,day,visit,starts,ends) VALUES(0,'guard-test',1,?,?)",(now-1,now+100)).lastrowid
        offers={}
        for ident in ('dust_in_eyes','mana_overload','smack'):
            s=BUILTIN_SKILLS[ident]
            offers[ident]=self.db.connection.execute('INSERT INTO arena_merchant_offers(visit_id,kind,content_id,rarity,price,per_user) VALUES(?,?,?,?,80,1)',(visit,'skill',ident,s.rarity)).lastrowid
        self.db.connection.commit()
        with patch('arena_market.market_now',return_value=now):
            for ident in ('dust_in_eyes','mana_overload'):
                with self.assertRaises(ValueError):await self.db.arena_buy_item(1,10,offers[ident])
            self.assertEqual(await self.db.franc_balance(1,10),10000)
            await self.db.arena_buy_item(1,10,offers['smack'])
        self.assertEqual(await self.db.franc_balance(1,10),9920)
        self.assertEqual(self.qty('smack'),1)

    async def test_http_sale_uses_signed_owner_server_price_and_confirmation(self):
        item=self.add('last_argument',2)
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)))
        await client.start_server()
        headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
        request=dict(action='sell_item',item=item,quantity=1,nonce=uuid4().hex,confirm=True,price=999999,actor=20)
        try:
            self.assertEqual((await client.post('/api/menu/1',json=request)).status,400)
            self.assertEqual((await client.post('/api/menu/1',headers=headers,json=dict(request,confirm=False))).status,400)
            response=await client.post('/api/menu/1',headers=headers,json=request)
            self.assertEqual(response.status,200,await response.text())
            self.assertEqual((await response.json())['menu']['balance'],10250)
            self.assertEqual((await client.post('/api/menu/1',headers=headers,json=request)).status,200)
            self.assertEqual(self.qty('last_argument'),1)
        finally:await client.close()


class PublicScrollCombatTests(TestCase):
    def test_new_scrolls_really_work_for_physical_and_magic_classes(self):
        fixture=combat_fixtures.EpicTests()
        for cls in ('warrior','mage'):
            for ident in ('sweeping_kick','rupturing_strike','royal_verdict'):
                with self.subTest(cls=cls,skill=ident):
                    state=fixture.state(cls=cls);actor=state['sides']['a'];before=actor['resource']
                    result=fixture.use(state,ident)
                    self.assertGreater(result['damage'],0)
                    self.assertEqual(actor['resource'],before-BUILTIN_SKILLS[ident].cost)
            state=fixture.state(cls=cls);actor=state['sides']['a'];actor['resource']=0
            fixture.use(state,'catch_breath');self.assertEqual(actor['resource'],25)
            state=fixture.state(cls=cls);actor=state['sides']['a'];actor['hp']=500
            fixture.use(state,'field_dressing');self.assertEqual(actor['hp'],650)
            plain=fixture.state(cls=cls)['sides']['a']
            armored=fixture.state(['unyielding_will'],cls=cls)['sides']['a']
            for stat in ('physical_defense','magic_defense'):
                self.assertAlmostEqual(effective_stat(armored,stat),effective_stat(plain,stat)*1.25)
            free=unlocked_skill_ids(cls,20,BUILTIN_SKILLS)
            self.assertNotIn('royal_verdict',free)
            self.assertNotIn('catch_breath',free)
