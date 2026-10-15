import asyncio
import json
import sqlite3
import shutil
import time
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from aiohttp.test_utils import TestClient, TestServer

import test_account_rpg as account
import test_arena_daily_balance as daily
import test_arena
import test_arena_market_client as client_tests
from arena_characters import CHARACTER_PACK, CHARACTER_PRICE, CHARACTER_TERMS_VERSION
from arena_web import menu_view, create_arena_app, battle_view
from handlers.pets import create_pet_router


class SlotTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=account.AccountTests.asyncSetUp
    asyncTearDown=account.AccountTests.asyncTearDown
    level=account.AccountTests.level
    profile=account.AccountTests.profile
    finish=daily.DailyBalanceStoreTests.finish

    async def unlock(self,user=10,charge='slots-charge'):
        order=await self.db.pet_create_order(user,CHARACTER_PACK,CHARACTER_TERMS_VERSION)
        await self.db.pet_check_order(user,order['payload'],'XTR',200)
        await self.db.pet_payment(user,order['payload'],'XTR',200,charge)
        return order

    async def select(self,slot,user=10,chat=1):
        view=await self.db.arena_characters(user)
        await self.db.arena_select_character(chat,user,slot,view['revision'])

    async def test_default_one_slot_no_data_or_balance_loss(self):
        self.level(18,'nerd')
        await self.db.credit_francs(1,10,100)
        view=await menu_view(self.db,2,10)
        self.assertEqual((view['characters']['active_slot'],view['characters']['capacity']),(1,1))
        self.assertEqual(sum(s['locked'] for s in view['characters']['slots']),4)
        self.assertEqual(view['personal']['xp'],account.xp_at(18))
        self.assertEqual(await self.db.franc_balance(1,10),100)
        with self.assertRaises(ValueError):await self.select(2)

    async def test_payment_is_200_stars_once_and_not_pet_tickets(self):
        order=await self.unlock()
        self.assertEqual((order['stars'],order['tickets']),(CHARACTER_PRICE,0))
        self.assertEqual((await self.db.arena_characters(10))['capacity'],5)
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)
        replay=await self.db.pet_payment(10,order['payload'],'XTR',200,'slots-charge')
        self.assertTrue(replay['replay'])
        with self.assertRaises(ValueError):await self.db.pet_create_order(10,CHARACTER_PACK,CHARACTER_TERMS_VERSION)
        with self.assertRaises(ValueError):await self.db.pet_payment(10,order['payload'],'XTR',200,'second-charge')
        self.assertEqual((await self.db.arena_characters(20))['capacity'],1)

    async def test_pending_invoice_reused_concurrently_and_success_replay_safe(self):
        orders=await asyncio.gather(*(self.db.pet_create_order(10,CHARACTER_PACK,CHARACTER_TERMS_VERSION) for _ in range(3)))
        self.assertEqual(len({o['id'] for o in orders}),1)
        results=await asyncio.gather(*(self.db.pet_payment(10,orders[0]['payload'],'XTR',200,'charge') for _ in range(2)))
        self.assertEqual(sum(r['replay'] for r in results),1)

    async def test_wrong_payment_cannot_unlock(self):
        with self.assertRaises(ValueError):await self.db.pet_create_order(10,CHARACTER_PACK,'wrong')
        order=await self.db.pet_create_order(10,CHARACTER_PACK,CHARACTER_TERMS_VERSION)
        for actor,currency,total in ((20,'XTR',200),(10,'USD',200),(10,'XTR',1),(10,'XTR',True)):
            with self.assertRaises(ValueError):await self.db.pet_check_order(actor,order['payload'],currency,total)
            with self.assertRaises(ValueError):await self.db.pet_payment(actor,order['payload'],currency,total,'bad')
        self.assertEqual((await self.db.arena_characters(10))['capacity'],1)

    async def test_telegram_successful_payment_handler_unlocks_and_reports_slots(self):
        order=await self.db.pet_create_order(10,CHARACTER_PACK,CHARACTER_TERMS_VERSION)
        router=create_pet_router(self.db,'TestBot',True)
        handler=next(h.callback for h in router.message.handlers if h.callback.__name__=='payment')
        message=SimpleNamespace(from_user=SimpleNamespace(id=10),answer=AsyncMock(),bot=self.bot,
            successful_payment=SimpleNamespace(invoice_payload=order['payload'],currency='XTR',total_amount=200,telegram_payment_charge_id='telegram-charge'))
        await handler(message)
        self.assertIn('4 дополнительных слота',message.answer.await_args.args[0])
        self.assertEqual((await self.db.arena_characters(10))['capacity'],5)
        message.answer.reset_mock();await handler(message)
        message.answer.assert_not_awaited()

    async def test_all_five_slots_independent_and_survive_restart(self):
        self.level(18,'nerd')
        await self.db.arena_set_sprite(1,10,b'first-sprite',True)
        self.db._arena_add_item_locked(1,10,'passive','stone_skin','common',2)
        self.db.connection.commit()
        item=self.db._arena_inventory_locked(1,10)[0]['id']
        await self.db.arena_use_item(1,10,item,10)
        await self.unlock()
        for slot in range(2,6):
            await self.select(slot,chat=2)
            self.assertEqual((self.profile()['level'],self.profile()['xp']),(1,0))
            self.assertEqual(self.db._arena_learned_locked(2,10,True,'passive'),set())
            self.db._grant_profile_xp_locked('personal_profiles',2,10,slot)
            self.db.connection.commit()
        await self.select(2)
        await self.db.arena_use_item(2,10,item,10)
        await self.db.arena_set_sprite(2,10,b'second-sprite',False,expected_slot=2)
        self.db._grant_profile_xp_locked('personal_profiles',1,10,4)
        self.db.connection.commit()
        await self.db.close();await self.db.connect()
        self.assertEqual(self.profile()['xp'],6)  # Live projection, not stale snapshot.
        self.assertEqual((await self.db.arena_characters(10))['active_slot'],2)
        await self.select(1)
        self.assertEqual((self.profile()['class_id'],self.profile()['xp']),('nerd',account.xp_at(18)))
        self.assertEqual(self.db._arena_learned_locked(2,10,True,'passive'),{'stone_skin'})
        self.assertTrue((await self.db.arena_sprite_info(2,10))['pixel_art'])
        for slot,expected in ((2,6),(3,3),(4,4),(5,5)):
            await self.select(slot)
            self.assertEqual(self.profile()['xp'],expected)
        self.assertFalse(self.db._arena_inventory_locked(1,10))

    async def test_stale_profile_item_sprite_and_new_activity_requests_rejected(self):
        await self.unlock();await self.select(2)
        self.db._arena_add_item_locked(1,10,'candy','experience','common')
        self.db.connection.commit();item=self.db._arena_inventory_locked(1,10)[0]['id']
        operations=(self.db.arena_edit_profile(1,10,10,True,'loadout',['bum_punch'],expected_slot=1),
            self.db.arena_use_item(1,10,item,10,expected_slot=1),
            self.db.arena_set_sprite(1,10,b'test',False,expected_slot=1),
            self.db.arena_reset_sprite(1,10,expected_slot=1),
            self.db.arena_wasteland(1,10,expected_slot=1),
            self.db.arena_mirror_start(1,10,expected_slot=1),
            self.db.arena_raid_create(1,10,expected_slot=1))
        for operation in operations:
            with self.assertRaises(ValueError):await operation
        self.assertEqual(self.profile()['xp'],0)
        self.assertEqual(self.db._arena_inventory_locked(1,10)[0]['quantity'],1)

    async def test_selection_revision_owner_and_valid_slot(self):
        await self.unlock();old=await self.db.arena_characters(10)
        await self.select(2)
        with self.assertRaises(ValueError):await self.db.arena_select_character(1,10,3,old['revision'])
        with self.assertRaises(ValueError):await self.select(2,user=20)
        for slot in (0,6,True,'2'):
            with self.assertRaises(ValueError):await self.select(slot)

    async def test_switching_blocked_in_every_mode_across_chats(self):
        await self.unlock();await self.select(2)
        duel=await self.db.arena_offer(1,10,20,'personal')
        self.assertEqual(duel['a_character_slot'],2)
        with self.assertRaises(ValueError):await self.select(1,chat=2)
        await self.db.arena_setup(duel['token'],10,'cancel')
        row=await self.db.arena_wasteland(1,10,expected_slot=2)
        with self.assertRaises(ValueError):await self.select(1,chat=2)
        await self.db.arena_action(row['token'],10,row['revision'],'surrender')
        raid=await self.db.arena_raid_create(1,10,expected_slot=2)
        with self.assertRaises(ValueError):await self.select(1,chat=2)
        await self.db.arena_raid_setup(raid['token'],10,'cancel')
        run=await self.db.arena_mirror_start(1,10,expected_slot=2)
        self.assertEqual((await self.db.arena_get(run['battle_token']))['a_character_slot'],2)
        with self.assertRaises(ValueError):await self.select(1,chat=2)
        await self.db.arena_leave_mirror(2,10,run['token']);await self.select(1)

    async def test_battle_sprite_binds_to_slot_and_floor_cannot_be_reused(self):
        await self.unlock();await self.select(2)
        await self.db.arena_set_sprite(1,10,b'slot-two',False)
        url=(await self.db.arena_sprite_info(1,10))['sprite_url']
        row=await self.db.arena_wasteland(1,10)
        state=json.loads(row['state_json']);state.update(finished=True,winner='a',finish_reason='knockout')
        self.db._arena_finish_locked(row,state)
        self.db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',(json.dumps(state),row['token']))
        self.db.connection.commit()
        await self.select(1)
        view=await battle_view(self.db,await self.db.arena_get(row['token']),10)
        self.assertEqual(view['state']['sides']['a']['sprite_url'],url)
        self.assertEqual(await self.db.arena_sprite_png(url.split('/')[-1][:-4]),b'slot-two')
        with self.assertRaises(ValueError):await self.db.arena_wasteland(1,10,previous=row['token'])

    async def test_raid_daily_and_pet_limits_do_not_reset_when_switching(self):
        await self.unlock()
        first=await self.db.arena_raid_create(1,10)
        first=await self.db.arena_raid_setup(first['token'],10,'start')
        reward=self.finish(first)
        self.assertTrue(reward['full_reward'])
        misses=self.db.connection.execute('SELECT misses FROM arena_raid_global_pity WHERE actor_id=10').fetchone()[0]
        await self.select(2,chat=2)
        second=await self.db.arena_raid_create(2,10)
        second=await self.db.arena_raid_setup(second['token'],10,'start')
        reward=self.finish(second)
        self.assertFalse(reward['full_reward']);self.assertFalse(reward['pet_rewards']);self.assertFalse(reward['loot'])
        self.assertEqual(self.db.connection.execute('SELECT misses FROM arena_raid_global_pity WHERE actor_id=10').fetchone()[0],misses)
        view=await self.db.pet_view(10)
        view=await self.db.pet_action(10,view['wallet']['revision'],'daily')
        tickets=view['wallet']['tickets']
        await self.select(3)
        view=await self.db.pet_action(10,view['wallet']['revision'],'daily')
        self.assertEqual(view['wallet']['tickets'],tickets)

    async def test_pvp_pair_limit_counts_account_not_character_slot(self):
        await self.unlock()
        for index,slot in enumerate((1,2,3,4)):
            await self.select(slot)
            row=await self.db.arena_offer(1,10,20,'personal')
            row=await self.db.arena_setup(row['token'],20,'accept')
            state=json.loads(row['state_json'])
            state.update(finished=True,winner='a',finish_reason='knockout',had_player_action=True)
            self.db._arena_finish_locked(row,state);self.db.connection.commit()
            self.assertEqual(state['rewards']['a'],10 if index<3 else 1)
        self.assertEqual(self.db.connection.execute('SELECT count FROM arena_pair_rewards WHERE chat_id=0').fetchone()[0],4)

    async def test_sprite_reads_leave_no_transaction_before_payment(self):
        await self.db.arena_character_sprite_info(10,1)
        self.assertFalse(self.db.connection.in_transaction)
        await self.unlock()

    async def test_refund_in_team_raid_withdraws_only_buyer(self):
        order=await self.unlock();await self.select(2)
        row=await self.db.arena_raid_create(1,10)
        await self.db.arena_raid_setup(row['token'],20,'join')
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        await self.db.pet_start_refund(order['id'])
        row=await self.db.arena_raid_get(row['token'])
        self.assertEqual(row['status'],'active')
        self.assertTrue(json.loads(row['data_json'])['players']['10']['withdrawn'])
        self.assertFalse(json.loads(row['data_json'])['players']['20']['withdrawn'])
        self.assertTrue(self.db._arena_busy_locked(1,20))
        self.assertFalse(self.db._arena_busy_locked(1,10))

    async def test_refund_closes_extra_slot_battle_refunds_stakes_preserves_character(self):
        order=await self.unlock();await self.select(2)
        self.db._grant_profile_xp_locked('personal_profiles',1,10,15);self.db.connection.commit()
        for user in (10,20):await self.db.credit_francs(1,user,100)
        row=await self.db.arena_offer(1,10,20,'personal',50)
        row=await self.db.arena_setup(row['token'],20,'accept')
        await self.db.pet_start_refund(order['id'])
        self.assertEqual((await self.db.arena_get(row['token']))['status'],'cancelled')
        self.assertEqual((await self.db.arena_characters(10))['active_slot'],1)
        self.assertEqual(self.profile()['xp'],0)
        for user in (10,20):self.assertEqual(await self.db.franc_balance(1,user),100)
        self.db.connection.commit()
        await self.db.pet_finish_refund(order['id'])
        await self.db.pet_receive_refund(order['payload'],'XTR',200,'slots-charge')
        self.assertEqual((await self.db.arena_characters(10))['capacity'],1)
        self.assertEqual((await self.db.pet_view(10))['wallet']['ticket_debt'],0)
        await self.unlock(charge='repurchase');await self.select(2)
        self.assertEqual(self.profile()['xp'],15)

    async def test_refund_before_payment_never_unlocks(self):
        order=await self.db.pet_create_order(10,CHARACTER_PACK,CHARACTER_TERMS_VERSION)
        await self.db.pet_receive_refund(order['payload'],'XTR',200,'charge')
        result=await self.db.pet_payment(10,order['payload'],'XTR',200,'charge')
        self.assertEqual(result['status'],'refunded')
        self.assertEqual((await self.db.arena_characters(10))['capacity'],1)

    async def test_failed_switch_rolls_back_profile_sprite_learned_and_revision(self):
        await self.unlock();await self.db.arena_set_sprite(1,10,b'original',False)
        before=await self.db.arena_characters(10)
        self.db.connection.execute("CREATE TRIGGER reject_character BEFORE INSERT ON personal_profiles WHEN NEW.chat_id=0 AND NOT EXISTS(SELECT 1 FROM personal_profiles WHERE chat_id=0 AND user_id=NEW.user_id) BEGIN SELECT RAISE(ABORT,'test failure'); END")
        self.db.connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):await self.select(2)
        self.assertEqual((await self.db.arena_characters(10))['revision'],before['revision'])
        self.assertEqual((await self.db.arena_characters(10))['active_slot'],1)
        self.assertIsNotNone((await self.db.arena_sprite_info(2,10))['sprite_url'])

    async def test_refund_failure_is_atomic(self):
        order=await self.unlock();await self.select(2)
        battle=await self.db.arena_wasteland(1,10)
        with patch.object(self.db,'_character_switch_locked',side_effect=RuntimeError('storage fail')):
            with self.assertRaises(RuntimeError):await self.db.pet_start_refund(order['id'])
        self.assertEqual((await self.db.arena_get(battle['token']))['status'],'active')
        self.assertEqual((await self.db.arena_characters(10))['active_slot'],2)
        self.assertEqual((await self.db.arena_characters(10))['capacity'],5)

    async def test_invoice_api_signed_actor_fixed_price_and_disabled_sales(self):
        self.bot.create_invoice_link=__import__('unittest.mock',fromlist=['AsyncMock']).AsyncMock(return_value='https://t.me/$test')
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,test_arena.TOKEN,pets_payments_enabled=True)))
        await client.start_server()
        headers={'X-Telegram-Init-Data':test_arena.signed(10,int(time.time()))}
        try:
            body=dict(chat=1,accept_terms=True,terms_version=CHARACTER_TERMS_VERSION,stars=1,user=20)
            self.assertEqual((await client.post('/api/characters/invoice',json=body)).status,400)
            self.assertEqual((await client.post('/api/characters/invoice',headers=headers,json={**body,'accept_terms':False})).status,400)
            response=await client.post('/api/characters/invoice',headers=headers,json=body)
            self.assertEqual(response.status,200)
            call=self.bot.create_invoice_link.await_args.kwargs
            self.assertEqual(call['currency'],'XTR');self.assertEqual(call['prices'][0].amount,200)
            order=self.db.connection.execute('SELECT * FROM pet_orders WHERE payload=?',(call['payload'],)).fetchone()
            self.assertEqual(order['user_id'],10)
            await self.db.pet_payment(10,call['payload'],'XTR',200,'api-charge')
            view=await (await client.get('/api/menu/2',headers=headers)).json()
            response=await client.post('/api/menu/2',headers=headers,json=dict(action='select_character',slot=2,character_revision=view['characters']['revision'],user=20))
            self.assertEqual(response.status,200)
            self.assertEqual((await self.db.arena_characters(20))['capacity'],1)
            self.assertEqual((await client.post('/api/menu/2',headers=headers,json=dict(action='loadout',user=10,personal=True,value=['bum_punch']))).status,400)
            self.assertEqual((await client.post('/api/menu/2',headers=headers,json=dict(action='loadout',character_slot=2,user=10,personal=True,value=['bum_punch']))).status,200)
        finally:await client.close()
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,test_arena.TOKEN,pets_payments_enabled=False)))
        await client.start_server()
        try:self.assertEqual((await client.post('/api/characters/invoice',headers=headers,json=body)).status,400)
        finally:await client.close()


@unittest.skipUnless(shutil.which('node'),'Client tests need Node')
class CharacterClientTests(unittest.TestCase):
    run_client=client_tests.ArenaMarketClientTests.run_client

    def data(self,unlocked=False,busy=False):
        data=client_tests.ArenaMarketClientTests().menu_data()
        data['characters']=dict(active_slot=1,capacity=5 if unlocked else 1,unlocked=unlocked,busy=busy,
            price=200,terms='Одна покупка без подписки. При возврате персонажи сохраняются.',payments_enabled=True,
            slots=[dict(slot=i,active=i==1,locked=i>1 and not unlocked,created=i==1,level=20 if i==1 else 1,
                        class_name='Оборванец',avatar_url='/static/assets/ragamuffin.png') for i in range(1,6)])
        return data

    def test_one_free_four_locked_and_whole_package_price(self):
        body=self.run_client("page='personal';menuScreen(input);",self.data())
        self.assertEqual(body.count('class="character-option'),5)
        self.assertEqual(body.count('character-option locked'),4)
        self.assertIn('Открыть все 4 слота · 200 ☆',body)
        self.assertNotIn('data-do="character:2"',body)

    def test_paid_empty_slots_can_be_created_but_busy_switch_disabled(self):
        body=self.run_client("page='personal';menuScreen(input);",self.data(True))
        self.assertIn('data-do="character:5"',body)
        self.assertIn('Создать персонажа',body)
        self.assertNotIn('Открыть все 4 слота',body)
        body=self.run_client("page='personal';menuScreen(input);",self.data(True,True))
        self.assertIn('data-do="character:2" disabled',body)

    def test_purchase_requires_checkbox_and_does_not_auto_pay(self):
        body=self.run_client("page='charactersPurchase';menuScreen(input);",self.data())
        self.assertIn('id="characters-agree"',body)
        self.assertIn('data-do="characterinvoice" disabled',body)
        self.assertIn('без подписки',body)
