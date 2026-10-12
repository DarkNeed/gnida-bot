import asyncio
import json
import random
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from arena_engine import BUILTIN_SKILLS, create_battle_state, resolve_skill, validate_skill
from arena_pet_store import next_odds
from arena_pets import PETS, PET_ODDS, PET_TERMS_VERSION, pet_cost, pet_snapshot
from arena_web import create_arena_app
from database import Database
from handlers.pets import create_pet_router
from tests.test_arena import signed, TOKEN


class FixedRandom:
    def __init__(self, roll=0): self.roll=roll
    def random(self): return self.roll
    def choice(self, values): return values[0]
    def uniform(self, low, high): return (low+high)/2


class PetEngineTests(unittest.TestCase):
    def state(self, pet='sandwich', level=1):
        source=dict(slave_id=10,owner_id=10,controlled=False,class_id='ragamuffin',level=12,
                    loadout=['bum_punch','dust_in_eyes'],pet=dict(id=pet,level=level,power=3 if level==10 else 0,tempo=0))
        other=dict(source,slave_id=20,pet=None)
        return create_battle_state(source,other)

    def test_all_pets_execute_without_changing_integer_resources(self):
        for pet in PETS:
            for level in (1,2,10):
                with self.subTest(pet=pet,level=level):
                    state=self.state(pet,level)
                    for _ in range(10):
                        state['sides']['b']['hp']=state['sides']['b']['stats']['max_hp']=10000
                        state['sides']['a']['hp']=state['sides']['a']['stats']['max_hp']
                        state['active_side']='a';state['finished']=False
                        state['sides']['a']['resource']=50
                        resolve_skill(state,'a','bum_punch',rng=random.Random(3),advance_turn=False)
                        self.assertIsInstance(state['sides']['a']['resource'],int)
                        self.assertIsInstance(state['sides']['b']['resource'],int)
                    self.assertEqual(state['sides']['a']['pet_state']['steps'],10)

    def test_sandwich_heals_once_and_never_revives(self):
        s=self.state();a=s['sides']['a'];a['hp']=5
        resolve_skill(s,'a','bum_punch',rng=random.Random(3),advance_turn=False)
        self.assertGreater(a['hp'],5);self.assertTrue(a['pet_state']['used'])
        a['hp']=5
        resolve_skill(s,'a','bum_punch',rng=random.Random(3),advance_turn=False)
        self.assertEqual(a['hp'],5)
        from arena_pets import _sandwich
        a['hp']=0;a['pet_state']={}
        self.assertEqual(_sandwich(a),[]);self.assertEqual(a['hp'],0)

    def test_ready_discount_is_same_in_validation_and_resolution(self):
        s=self.state('poro');a=s['sides']['a'];a['pet_state']['ready']=True;a['resource']=16
        skill=validate_skill(s,'a','dust_in_eyes')
        self.assertEqual(pet_cost(a,skill,20),16)
        e=resolve_skill(s,'a','dust_in_eyes',rng=random.Random(3),advance_turn=False)
        self.assertEqual(e['after']['a']['resource'],0)
        self.assertFalse(a['pet_state']['ready'])

    def test_six_hits_have_one_pet_proc(self):
        from arena_pets import pet_after_action
        s=self.state('bonzi');a=s['sides']['a'];a['pet_state']['charge']=3
        skill=replace(BUILTIN_SKILLS['bum_punch'],tags=('six_strike',))
        catalog=dict(BUILTIN_SKILLS,bum_punch=skill)
        e=resolve_skill(s,'a','bum_punch',catalog,rng=random.Random(3),advance_turn=False)
        self.assertEqual(len(e['hits']),6)
        self.assertEqual(a['pet_state']['steps'],1)
        self.assertEqual(s['sides']['b']['resource'],98)

    def test_pet_snapshot_is_detached_and_level_bounded(self):
        raw=dict(id='rat',level=999,power=999,tempo=999)
        self.assertEqual(pet_snapshot(raw)['level'],10)
        self.assertEqual(pet_snapshot(raw)['power'],3)
        self.assertEqual(pet_snapshot(raw)['tempo'],0)
        self.assertIsNone(pet_snapshot(dict(id='invalid')))

    def test_all_approved_assets_have_alpha_and_exact_size(self):
        from PIL import Image
        root=Path(__file__).resolve().parents[1]/'webapp/assets/pets'
        for pet in PETS:
            with Image.open(root/(pet+'.png')) as image:
                self.assertEqual(image.size,(768,768));self.assertEqual(image.mode,'RGBA')
                self.assertEqual(image.getchannel('A').getextrema(),(0,255))

    def test_printer_never_asks_for_nonexistent_support(self):
        s=self.state('printer');a=s['sides']['a']
        a['loadout']=['bum_punch','go_to_store'];a['pet_state']['task']='support';a['resource']=30
        resolve_skill(s,'a','bum_punch',rng=FixedRandom(),advance_turn=False)
        self.assertEqual(a['pet_state']['task'],'restore')

    def test_pet_bleed_ticks_only_on_target_attack(self):
        s=self.state('smesharik');a,b=s['sides']['a'],s['sides']['b']
        a['pet_state']['charge']=4;b['hp']=b['stats']['max_hp']=1000
        resolve_skill(s,'a','bum_punch',rng=FixedRandom())
        self.assertTrue(any(e.get('pet') and e['kind']=='bleed' for e in b['effects']))
        hp=b['hp'];resolve_skill(s,'b','bum_punch',rng=FixedRandom())
        self.assertEqual(b['hp'],hp-1)


class PetStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(Path(self.temp.name)/'test.sqlite')
        await self.db.connect();await self.db.upsert_chat(1,'One');await self.db.upsert_chat(2,'Two')
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
                                 create_invoice_link=AsyncMock(return_value='https://t.me/$fake'))

    async def asyncTearDown(self):
        await self.db.close();self.temp.cleanup()

    async def wallet(self, tickets=1, food=0, essence=0, shards=0):
        await self.db.pet_view(10)
        self.db.connection.execute('UPDATE pet_wallets SET tickets=?,food=?,essence=?,shards=? WHERE user_id=10',(tickets,food,essence,shards))
        self.db.connection.commit()

    async def open(self, nonce='first_open', roll=0, chat=1):
        v=await self.db.pet_view(10)
        return await self.db.pet_open(10,v['wallet']['revision'],nonce,chat,rng=FixedRandom(roll))

    async def test_odds_and_pity(self):
        self.assertEqual(PET_ODDS,dict(common=20,rare=50,epic=27,legendary=3))
        await self.wallet(50)
        for i in range(10):r=await self.open('epic_open_'+str(i),0)
        self.assertEqual(r['result']['pet']['rarity'],'epic')
        for i in range(20):r=await self.open('legend_'+str(i),0)
        self.assertEqual(r['result']['pet']['rarity'],'legendary')
        self.assertEqual(r['view']['pity'],dict(epic=10,legendary=30))

    async def test_boundary_rolls(self):
        await self.wallet(20)
        for i,(roll,tier) in enumerate(((0,'common'),(.19999,'common'),(.2,'rare'),(.6999,'rare'),(.7,'epic'),(.9699,'epic'),(.97,'legendary'),(.99999,'legendary'))):
            r=await self.open('boundary_'+str(i),roll)
            self.assertEqual(r['result']['pet']['rarity'],tier)

    async def test_same_nonce_replay_across_chats_and_restart(self):
        await self.wallet();one=await self.open()
        await self.db.close();await self.db.connect()
        two=await self.db.pet_open(10,-1,'first_open',2)
        self.assertEqual(one['result'],two['result']);self.assertEqual(two['view']['wallet']['tickets'],0)
        self.assertEqual(len(two['view']['owned']),1)

    async def test_concurrent_double_click_spends_one_ticket(self):
        await self.wallet()
        a,b=await asyncio.gather(*(self.db.pet_open(10,0,'same_nonce',1,rng=FixedRandom()) for _ in range(2)))
        self.assertEqual(a['result'],b['result']);self.assertEqual(b['view']['wallet']['tickets'],0)

    async def test_two_different_nonces_with_stale_revision(self):
        await self.wallet(2);await self.open()
        with self.assertRaises(ValueError):await self.db.pet_open(10,0,'second_open')
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],1)

    async def test_duplicates_and_global_inventory_local_equipment(self):
        await self.wallet(2);await self.open();r=await self.open('second_open')
        self.assertTrue(r['result']['duplicate']);self.assertEqual(r['view']['wallet']['shards'],10)
        rev=r['view']['wallet']['revision'];await self.db.pet_action(10,rev,'equip','sandwich',chat=1)
        self.assertEqual((await self.db.pet_view(10,1))['equipped'],'sandwich')
        self.assertIsNone((await self.db.pet_view(10,2))['equipped'])
        self.assertEqual(len((await self.db.pet_view(10,2))['owned']),1)

    async def test_daily_and_reward_caps_global_replay_safe(self):
        await self.db.pet_action(10,0,'daily')
        v=await self.db.pet_view(10,2);await self.db.pet_action(10,v['wallet']['revision'],'daily')
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],1)
        async with self.db._lock:
            for i in range(12):self.db._pet_reward_locked(10,'wasteland','waste:'+str(i))
            self.assertEqual(self.db._pet_reward_locked(10,'wasteland','waste:0'),{})
            self.db.connection.commit()
        w=(await self.db.pet_view(10))['wallet'];self.assertEqual(w['tickets'],2);self.assertEqual(w['food'],24)

    async def test_upgrade_choices_max_and_exchange(self):
        await self.wallet(1,1000,100,1000);await self.open()
        for level in range(2,11):
            v=await self.db.pet_view(10);rev=v['wallet']['revision']
            if level in (3,6,10):
                with self.assertRaises(ValueError):await self.db.pet_action(10,rev,'upgrade','sandwich')
            await self.db.pet_action(10,rev,'upgrade','sandwich','power' if level in (3,6,10) else '')
        v=await self.db.pet_view(10);self.assertEqual(v['owned'][0]['power'],3)
        with self.assertRaises(ValueError):await self.db.pet_action(10,v['wallet']['revision'],'upgrade','sandwich')
        v=await self.db.pet_action(10,v['wallet']['revision'],'exchange','moon_mimic')
        self.assertEqual(len(v['owned']),2);self.assertEqual(v['wallet']['shards'],650)

    async def test_insufficient_upgrade_rolls_back(self):
        await self.wallet();await self.open();before=await self.db.pet_view(10)
        with self.assertRaises(ValueError):await self.db.pet_action(10,before['wallet']['revision'],'upgrade','sandwich')
        self.assertEqual(before,await self.db.pet_view(10))

    async def test_payment_confirmation_only_and_replays(self):
        order=await self.db.pet_create_order(10,'five',PET_TERMS_VERSION)
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)
        await self.db.pet_check_order(10,order['payload'],'XTR',110)
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)
        for user,currency,amount in ((20,'XTR',110),(10,'RUB',110),(10,'XTR',109)):
            with self.assertRaises(ValueError):await self.db.pet_payment(user,order['payload'],currency,amount,'charge')
        a,b=await asyncio.gather(*(self.db.pet_payment(10,order['payload'],'XTR',110,'charge') for _ in range(2)))
        self.assertFalse(a['replay']);self.assertTrue(b['replay'])
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],5)
        second=await self.db.pet_create_order(10,'one',PET_TERMS_VERSION)
        with self.assertRaises(sqlite3.IntegrityError):await self.db.pet_payment(10,second['payload'],'XTR',25,'charge')
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],5)

    async def test_refund_debt_and_replay_do_not_recredit(self):
        order=await self.db.pet_create_order(10,'one',PET_TERMS_VERSION)
        await self.db.pet_payment(10,order['payload'],'XTR',25,'charge');await self.open()
        await self.db.pet_start_refund(order['id'])
        await self.db.pet_finish_refund(order['id']);await self.db.pet_finish_refund(order['id'])
        await self.db.pet_payment(10,order['payload'],'XTR',25,'charge')
        v=await self.db.pet_view(10);self.assertEqual(v['wallet']['ticket_debt'],1)
        with self.assertRaises(ValueError):await self.db.pet_action(10,v['wallet']['revision'],'equip','sandwich',chat=1)
        await self.db.pet_action(10,v['wallet']['revision'],'daily')
        self.assertEqual((await self.db.pet_view(10))['wallet']['ticket_debt'],0)

    async def test_unknown_terms_and_pending_refund_block(self):
        with self.assertRaises(ValueError):await self.db.pet_create_order(10,'one','old')
        order=await self.db.pet_create_order(10,'five',PET_TERMS_VERSION)
        await self.db.pet_payment(10,order['payload'],'XTR',110,'charge');await self.db.pet_start_refund(order['id'])
        with self.assertRaises(ValueError):await self.open()
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],5)

    async def test_http_signed_identity_membership_and_disabled_sales(self):
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)))
        await client.start_server();headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
        try:
            self.assertEqual((await client.get('/api/pets')).status,400)
            r=await client.post('/api/pets',headers=headers,json=dict(action='daily',revision=0,user=20))
            self.assertEqual(r.status,200,await r.text());self.assertEqual((await self.db.pet_view(20))['wallet']['tickets'],0)
            self.bot.get_chat_member.return_value=SimpleNamespace(status='left')
            r=await client.post('/api/pets',headers=headers,json=dict(action='equip',revision=1,chat=1,pet_id='sandwich'))
            self.assertEqual(r.status,400)
            r=await client.post('/api/pets/invoice',headers=headers,json=dict(pack='one',accept_terms=True,terms_version=PET_TERMS_VERSION))
            self.assertEqual(r.status,400);self.bot.create_invoice_link.assert_not_awaited()
            self.assertEqual((await client.get('/pets')).status,200)
        finally:await client.close()

    async def test_invoice_server_price_and_acceptance(self):
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN,pets_payments_enabled=True)))
        await client.start_server();headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
        try:
            bad=await client.post('/api/pets/invoice',headers=headers,json=dict(pack='one',accept_terms=False,terms_version=PET_TERMS_VERSION))
            self.assertEqual(bad.status,400)
            good=await client.post('/api/pets/invoice',headers=headers,json=dict(pack='ten',accept_terms=True,terms_version=PET_TERMS_VERSION,stars=1,user=20))
            self.assertEqual(good.status,200,await good.text())
            kwargs=self.bot.create_invoice_link.await_args.kwargs
            self.assertEqual(kwargs['prices'][0].amount,200);self.assertEqual(kwargs['currency'],'XTR');self.assertEqual(kwargs['provider_token'],'')
            self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)
        finally:await client.close()

    async def test_router_registered_checkout_before_general_handlers(self):
        router=create_pet_router(self.db,'Example',False)
        self.assertEqual(len(router.pre_checkout_query.handlers),1)
        self.assertGreaterEqual(len(router.message.handlers),6)

    async def test_controller_pet_snapshot(self):
        await self.wallet();await self.open();v=await self.db.pet_view(10)
        await self.db.pet_action(10,v['wallet']['revision'],'equip','sandwich',chat=1)
        await self.db.upsert_user(1,10,'owner','Owner');await self.db.upsert_user(1,30,'slave','Slave')
        await self.db.force_enslave(1,30,10)
        async with self.db._lock:
            controlled=self.db._arena_source_locked(1,30,10,True,False)
            own=self.db._arena_source_locked(1,30,10,False,False)
        self.assertEqual(controlled['pet']['id'],'sandwich');self.assertIsNone(own['pet'])

    async def test_wasteland_victory_grants_food_but_surrender_does_not(self):
        await self.db.upsert_user(1,10,'player','Player')
        row=await self.db.arena_wasteland(1,10)
        state=json.loads(row['state_json']);state['sides']['b']['hp']=1
        self.db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',(json.dumps(state),row['token']))
        self.db.connection.commit()
        with patch('arena_engine.random.SystemRandom',return_value=FixedRandom()):
            await self.db.arena_action(row['token'],10,row['revision'],'bum_punch')
        self.assertEqual((await self.db.pet_view(10))['wallet']['food'],2)
        saved=await self.db.arena_get(row['token']);self.assertEqual(json.loads(saved['state_json'])['pet_rewards']['food'],2)
        with self.assertRaises(ValueError):await self.db.arena_action(row['token'],10,row['revision'],'bum_punch')
        row=await self.db.arena_wasteland(1,10)
        await self.db.arena_action(row['token'],10,row['revision'],'surrender')
        self.assertEqual((await self.db.pet_view(10))['wallet']['food'],2)

    async def test_confirmed_payment_handler_even_when_sales_disabled(self):
        order=await self.db.pet_create_order(10,'one',PET_TERMS_VERSION)
        router=create_pet_router(self.db,'Example',False)
        message=SimpleNamespace(from_user=SimpleNamespace(id=10),answer=AsyncMock(),successful_payment=SimpleNamespace(
            invoice_payload=order['payload'],currency='XTR',total_amount=25,telegram_payment_charge_id='tg-charge'))
        handler=next(h.callback for h in router.message.handlers if h.callback.__name__=='payment')
        await handler(message)
        await handler(message)
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],1)
        self.assertEqual(message.answer.await_count,1)

    async def test_checkout_rejects_disabled_sales_without_grant(self):
        order=await self.db.pet_create_order(10,'one',PET_TERMS_VERSION)
        query=SimpleNamespace(from_user=SimpleNamespace(id=10),answer=AsyncMock(),invoice_payload=order['payload'],currency='XTR',total_amount=25)
        await create_pet_router(self.db,'Example',False).pre_checkout_query.handlers[0].callback(query)
        self.assertFalse(query.answer.await_args.kwargs['ok'])
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)

    async def test_orphan_payment_refund_does_not_debit_valid_order(self):
        order=await self.db.pet_create_order(10,'one',PET_TERMS_VERSION)
        await self.db.pet_payment(10,order['payload'],'XTR',25,'valid-charge')
        issue=await self.db.pet_record_payment_issue(10,order['payload'],'XTR',25,'second-charge')
        refund=await self.db.pet_refund_order(order['payload'],'XTR',25,'second-charge')
        self.assertTrue(refund['issue'])
        await self.db.pet_payment_issue_refunded(issue['id'])
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],1)
        self.assertTrue((await self.db.pet_payment_issue(issue['id']))['refunded_at'])
        replay=await self.db.pet_record_payment_issue(10,order['payload'],'XTR',25,'valid-charge')
        with self.assertRaises(ValueError):await self.db.pet_payment_issue(replay['id'])

    async def test_refund_update_before_payment_survives_restart(self):
        order=await self.db.pet_create_order(10,'one',PET_TERMS_VERSION)
        await self.db.pet_receive_refund(order['payload'],'XTR',25,'early-charge')
        await self.db.close();await self.db.connect()
        result=await self.db.pet_payment(10,order['payload'],'XTR',25,'early-charge')
        self.assertEqual(result['status'],'refunded')
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)
        await self.db.pet_receive_refund(order['payload'],'XTR',25,'early-charge')
        self.assertEqual((await self.db.pet_view(10))['wallet']['ticket_debt'],0)

    async def test_refund_update_after_payment_is_idempotent(self):
        order=await self.db.pet_create_order(10,'five',PET_TERMS_VERSION)
        await self.db.pet_payment(10,order['payload'],'XTR',110,'charge')
        await self.db.pet_receive_refund(order['payload'],'XTR',110,'charge')
        await self.db.pet_receive_refund(order['payload'],'XTR',110,'charge')
        self.assertEqual((await self.db.pet_view(10))['wallet']['tickets'],0)
        self.assertEqual((await self.db.pet_view(10))['wallet']['ticket_debt'],0)


if __name__=='__main__':unittest.main()
