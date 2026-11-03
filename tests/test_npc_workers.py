import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import uuid4

from database import Database
from npc_worker_rules import create,DAY,HOUR,PROFESSIONS,FEMALE_NAMES,FEMALE_PROFESSIONS,public


class Always:
    def random(self):return 0
    def choice(self,values):return values[0]
    def sample(self,values,n):return list(values)[:n]


class NpcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(Path(self.temp.name)/'npc.sqlite')
        await self.db.connect();self.stamp=1800000000
        self.patch=patch('database.utc_timestamp',side_effect=lambda:self.stamp);self.patch.start()
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Тест')
            for user in (10,20,100):await self.db.upsert_user(chat,user,str(user),str(user))
            await self.db.force_enslave(chat,100,10)
            await self.db.credit_francs(chat,10,50000)

    async def asyncTearDown(self):
        self.patch.stop();await self.db.close();self.temp.cleanup()

    async def act(self,action,actor=10,chat=-100,**values):
        return await self.db.npc_action(chat,actor,dict(action=action,nonce=uuid4().hex,**values))

    async def buy(self):
        v=await self.db.holdings_view(-100,10);w=next(w for w in v['npc']['market'] if w['profession']!='diplomat')
        await self.act('npc_buy',id=w['id']);return w['id']

    def row(self,id):return self.db._npc_decode(self.db.connection.execute('SELECT * FROM fictional_workers WHERE id=?',(id,)).fetchone())

    async def test_sprite_identity_survives_appraisal_rest_and_release(self):
        id=await self.buy();before=self.row(id)['data'].copy()
        view=await self.db.holdings_view(-100,10)
        shown=next(w for w in view['npc']['workers'] if w['id']==id)
        self.assertNotIn('rarity',shown)
        self.assertEqual(shown['appearance'],before['appearance'])
        for action in ('npc_appraise','npc_rest','npc_release'):
            await self.act(action,id=id,revision=self.row(id)['revision'],confirm=True)
            d=self.row(id)['data']
            for key in ('name','gender','appearance','rarity','age'):
                self.assertEqual(d[key],before[key])

    async def test_legacy_sprite_migration_is_idempotent_and_does_not_reroll(self):
        id=await self.buy();r=self.row(id);d=r['data']
        d.pop('gender');d.pop('appearance');name=d['name'];rarity=d['rarity']
        self.db.connection.execute('UPDATE fictional_workers SET data=? WHERE id=?',(json.dumps(d),id))
        self.db._init_npc_workers()
        migrated=self.row(id);revision=migrated['revision']
        self.assertEqual(migrated['data']['name'],name)
        self.assertEqual(migrated['data']['rarity'],rarity)
        self.assertEqual(migrated['data']['gender'],'male')
        self.assertEqual(migrated['data']['appearance'],d['profession']+'-male')
        self.db._init_npc_workers();self.assertEqual(self.row(id)['revision'],revision)

    async def test_purchase_hidden_rarity_and_no_fake_telegram_identity(self):
        count=self.db.connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        id=await self.buy();v=await self.db.holdings_view(-100,10);w=v['npc']['workers'][0]
        self.assertNotIn('rarity',w);self.assertIsNone(w['power']);self.assertEqual(w['quality']['name'],'Не оценён')
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM users').fetchone()[0],count)
        before=await self.db.franc_balance(-100,10)
        await self.act('npc_appraise',id=id,revision=self.row(id)['revision'])
        self.assertEqual(await self.db.franc_balance(-100,10),before-50)
        quality=self.row(id)['data']['rarity']
        with self.assertRaises(ValueError):await self.act('npc_appraise',id=id,revision=self.row(id)['revision'])
        self.assertEqual(self.row(id)['data']['rarity'],quality)

    async def test_purchase_idempotency_and_wrong_owner(self):
        v=await self.db.holdings_view(-100,10);id=v['npc']['market'][0]['id']
        b=dict(action='npc_buy',id=id,nonce=uuid4().hex)
        await self.db.npc_action(-100,10,b);balance=await self.db.franc_balance(-100,10)
        await self.db.npc_action(-100,10,b);self.assertEqual(await self.db.franc_balance(-100,10),balance)
        with self.assertRaises(ValueError):await self.act('npc_rest',actor=20,id=id,revision=self.row(id)['revision'])
        with self.assertRaises(ValueError):await self.act('npc_buy',actor=20,id=id)

    async def test_shared_capacity_close_and_income_with_wallet_upkeep(self):
        id=await self.buy();await self.db.enterprise_create(-100,10,'mine')
        v=await self.db.holdings_view(-100,10);site=v['sites'][0]
        await self.act('npc_assign',id=id,site=site['id'],revision=self.row(id)['revision'])
        before=await self.db.franc_balance(-100,10);self.stamp+=24*HOUR
        v=await self.db.holdings_view(-100,10)
        self.assertNotIn('reserve',v['npc']);self.assertGreater(await self.db.franc_balance(-100,10),before)
        self.assertGreater(self.db.connection.execute('SELECT SUM(paid) FROM npc_upkeep_daily WHERE owner=10').fetchone()[0],0)
        balance=await self.db.franc_balance(-100,10)
        await self.db.holdings_view(-100,10);self.assertEqual(await self.db.franc_balance(-100,10),balance)
        await self.db.enterprise_close(-100,10,site['id'],v['revision'])
        self.assertIsNone(self.row(id)['site']);self.assertEqual(self.row(id)['status'],'rest')

    async def test_human_cannot_overfill_npc_capacity(self):
        id=await self.buy();await self.db.enterprise_create(-100,10,'mine')
        v=await self.db.holdings_view(-100,10);site=v['sites'][0]
        await self.act('npc_assign',id=id,site=site['id'],revision=self.row(id)['revision'])
        for u in range(101,110):
            await self.db.upsert_user(-100,u,str(u),str(u));await self.db.force_enslave(-100,u,10)
            self.assertEqual(await self.db.enterprise_assign(-100,10,u,'worker',site['id']),'updated')
        self.assertEqual(await self.db.enterprise_assign(-100,10,100,'worker',site['id']),'full')

    async def test_warning_then_single_daily_account_roll_and_no_click_expiry(self):
        id=await self.buy()
        self.db.connection.execute('UPDATE franc_balances SET balance=0 WHERE chat_id=-100 AND user_id=10');self.db.connection.commit()
        v=await self.db.holdings_view(-100,10)
        self.assertEqual(v['npc']['workforce']['warning']['deadline'],self.stamp+DAY)
        with self.db.connection:self.db._workforce_roll_locked(Always())
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM workforce_events').fetchone()[0],0)
        self.stamp+=DAY+1
        with self.db.connection:self.db._workforce_roll_locked(Always());self.db._workforce_roll_locked(Always())
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM workforce_events').fetchone()[0],1)
        e=(await self.db.holdings_view(-100,10))['npc']['workforce']['events'][0]
        self.assertEqual(e['deadline'],self.stamp+8*HOUR);self.assertNotIn('secret',e)
        self.stamp+=8*HOUR+1
        with self.db.connection:self.db._workforce_tick_locked(-100,10)
        self.assertEqual(self.row(id)['status'],'runaway');self.assertIsNone(self.row(id)['owner'])

    def make_event(self,typ='human',worker='100',kind='escaped'):
        id=uuid4().hex;epoch=self.db.connection.execute('SELECT acquired_at FROM ownership WHERE chat_id=-100 AND slave_id=100').fetchone()[0]
        data=json.dumps(dict(secret=[0,1,2],history=[],bounty=0))
        self.db.connection.execute("INSERT INTO workforce_events VALUES(?,-100,10,?,?,?,'Работник',?,'announcing',?,NULL,NULL,NULL,0,?,0)",(id,worker,typ,epoch,kind,self.stamp,data))
        self.db.connection.commit();return id

    async def event(self,id):
        return next(e for e in (await self.db.holdings_view(-100,10))['npc']['workforce']['events'] if e['id']==id)

    async def test_human_transfer_cancels_search_and_never_steals_back(self):
        id=self.make_event();e=await self.event(id)
        self.assertTrue(self.db._enterprise_away_locked(-100,10,100,self.stamp,self.stamp+1))
        await self.db.force_enslave(-100,100,20)
        self.stamp+=9*HOUR
        with self.db.connection:self.db._workforce_tick_locked(-100,10)
        owner=self.db.connection.execute('SELECT owner_id FROM ownership WHERE chat_id=-100 AND slave_id=100').fetchone()[0]
        self.assertEqual(owner,20);self.assertEqual((await self.event(id))['status'],'cancelled')

    async def test_game_has_outer_and_three_minute_deadline(self):
        id=self.make_event();e=await self.event(id)
        await self.act('workforce_start',id=id,revision=e['revision'])
        e=await self.event(id);self.assertEqual(e['game_ends'],self.stamp+180)
        self.stamp+=181
        with self.db.connection:self.db._workforce_tick_locked(-100,10)
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM ownership WHERE chat_id=-100 AND slave_id=100').fetchone())

    async def test_correct_code_returns_human_without_arena_changes(self):
        id=self.make_event();e=await self.event(id)
        await self.act('workforce_start',id=id,revision=e['revision']);e=await self.event(id)
        await self.act('workforce_guess',id=id,revision=e['revision'],guess=[0,1,2])
        self.assertEqual((await self.event(id))['status'],'returned')
        self.assertFalse(self.db._enterprise_away_locked(-100,10,100,self.stamp,self.stamp+1))

    async def test_ransom_bounty_is_returned_once_and_no_self_helper(self):
        id=self.make_event(kind='kidnapped');e=await self.event(id)
        before=await self.db.franc_balance(-100,10)
        await self.act('workforce_bounty',id=id,revision=e['revision'],amount=200);e=await self.event(id)
        await self.act('workforce_ransom',id=id,revision=e['revision'])
        self.assertEqual(await self.db.franc_balance(-100,10),before-300)
        with self.assertRaises(ValueError):await self.act('workforce_ransom',id=id,revision=e['revision'])

    async def test_transfer_refunds_bounty_even_if_old_owner_never_opens_page(self):
        id=self.make_event();e=await self.event(id);before=await self.db.franc_balance(-100,10)
        await self.act('workforce_bounty',id=id,revision=e['revision'],amount=200)
        await self.db.force_enslave(-100,100,20)
        await self.db.workforce_notifications();await self.db.workforce_notifications()
        self.assertEqual(await self.db.franc_balance(-100,10),before)

    async def test_helper_reward_escrow_paid_only_once_on_success(self):
        id=self.make_event();e=await self.event(id)
        await self.act('workforce_bounty',id=id,revision=e['revision'],amount=200)
        e=await self.event(id)
        await self.act('workforce_help',actor=20,id=id,revision=e['revision'])
        row=self.db.connection.execute('SELECT data FROM workforce_events WHERE id=?',(id,)).fetchone()
        p=json.loads(row['data']);p['search_success']=True
        self.db.connection.execute('UPDATE workforce_events SET data=? WHERE id=?',(json.dumps(p),id));self.db.connection.commit()
        self.stamp+=2*HOUR
        await self.event(id);await self.event(id)
        self.assertEqual(await self.db.franc_balance(-100,20),200)

    async def test_training_is_slow_and_does_not_reroll(self):
        id=await self.buy();quality=self.row(id)['data']['rarity'];old=self.row(id)['data']['profession_level']
        await self.act('npc_train',id=id,revision=self.row(id)['revision'],kind='work')
        self.stamp+=11*HOUR;await self.db.holdings_view(-100,10)
        self.assertEqual(self.row(id)['data']['profession_level'],old)
        self.stamp+=2*HOUR;await self.db.holdings_view(-100,10)
        self.assertEqual(self.row(id)['data']['profession_level'],old+1);self.assertEqual(self.row(id)['data']['rarity'],quality)

    async def test_legacy_generator_disabled_without_destroying_active_games(self):
        self.assertEqual(await self.db.enterprise_due_recoveries(Always()),[])

    async def test_no_separate_npc_limit_across_chats(self):
        for n in range(25):
            d=create('skeleton')
            self.db.connection.execute("INSERT INTO fictional_workers VALUES(?,?,10,'rest',NULL,1300,?,0,?,?)",(uuid4().hex,-100 if n%2 else -200,json.dumps(d),self.stamp,self.stamp))
        self.db.connection.commit()
        v=await self.db.holdings_view(-100,10);id=v['npc']['market'][0]['id']
        before=await self.db.franc_balance(-100,10)
        await self.act('npc_buy',id=id)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM fictional_workers WHERE owner=10').fetchone()[0],26)
        self.assertNotIn('capacity',(await self.db.holdings_view(-200,10))['npc'])
        self.assertLess(await self.db.franc_balance(-100,10),before)
        with self.assertRaises(ValueError):await self.act('npc_housing',level=1)

    async def test_upkeep_is_automatic_and_debited_exactly_once_from_wallet(self):
        id=await self.buy();before=await self.db.franc_balance(-100,10)
        upkeep=self.row(id)['data']['profession'];from npc_worker_rules import PROFESSIONS
        self.stamp+=DAY
        await self.db.holdings_view(-100,10)
        self.assertEqual(before-await self.db.franc_balance(-100,10),PROFESSIONS[upkeep]['upkeep'])
        balance=await self.db.franc_balance(-100,10)
        await self.db.holdings_view(-100,10);self.assertEqual(balance,await self.db.franc_balance(-100,10))
        with self.assertRaises(ValueError):await self.act('npc_fund',amount=100)

    async def test_empty_wallet_does_not_overdraft_and_creates_bad_conditions(self):
        id=await self.buy()
        self.db.connection.execute('UPDATE franc_balances SET balance=0 WHERE chat_id=-100 AND user_id=10');self.db.connection.commit()
        self.stamp+=2*DAY;v=await self.db.holdings_view(-100,10)
        self.assertEqual(await self.db.franc_balance(-100,10),0)
        self.assertGreaterEqual(self.row(id)['data']['unpaid'],24)
        self.assertGreater(v['npc']['workforce']['risk']['chance'],0)

    async def test_retired_reserve_returns_to_wallet_only_once(self):
        await self.buy();before=await self.db.franc_balance(-100,10)
        self.db.connection.execute('UPDATE npc_estates SET reserve=300 WHERE chat=-100 AND owner=10');self.db.connection.commit()
        v=await self.db.holdings_view(-100,10);await self.db.holdings_view(-100,10)
        self.assertEqual(await self.db.franc_balance(-100,10),before+300)
        self.assertNotIn('reserve',v['npc']);self.assertNotIn('housing_price',v['npc'])

    async def test_mixed_bulk_assignment_and_removal_are_atomic(self):
        id=await self.buy();await self.db.enterprise_create(-100,10,'mine')
        v=await self.db.holdings_view(-100,10);site=v['sites'][0]
        await self.db.enterprise_batch(-100,10,[100],site['id'],'worker',v['revision'],npcs=[id])
        v=await self.db.holdings_view(-100,10)
        self.assertEqual(v['sites'][0]['npc_count'],1);self.assertEqual(len(v['sites'][0]['workers']),1)
        self.assertEqual(self.row(id)['site'],site['id'])
        await self.db.enterprise_batch(-100,10,[100],None,'remove',v['revision'],npcs=[id])
        self.assertIsNone(self.row(id)['site']);self.assertEqual(self.row(id)['status'],'rest')
        v=await self.db.holdings_view(-100,10)
        with self.assertRaises(ValueError):await self.db.enterprise_batch(-100,10,[100],site['id'],'worker',v['revision'],npcs=['x'*32])
        self.assertEqual((await self.db.holdings_view(-100,10))['sites'][0]['workers'],[])

    async def test_npc_can_manage_a_shared_enterprise(self):
        id=await self.buy();await self.db.enterprise_create(-100,10,'mine')
        v=await self.db.holdings_view(-100,10);site=v['sites'][0]
        await self.db.enterprise_batch(-100,10,[],site['id'],'leader',v['revision'],npcs=[id])
        self.assertEqual(await self.db.enterprise_assign(-100,10,100,'leader',site['id']),'leader_full')
        await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        self.stamp+=2*HOUR
        await self.db.holdings_view(-100,10)
        gross=self.db.connection.execute('SELECT SUM(gross_income) FROM enterprise_income_daily WHERE business_id=?',(site['id'],)).fetchone()[0]
        self.assertGreater(gross,6)

    async def mixed_trip(self):
        id=await self.buy()
        q=await self.act('npc_trip_quote',ids=[id],users=[100],mission='outskirts')
        await self.act('npc_trip',ids=[id],users=[100],mission='outskirts',revision=q['quote']['revision'])
        trip=self.db.connection.execute('SELECT * FROM npc_trips ORDER BY started DESC LIMIT 1').fetchone();p=json.loads(trip['data'])
        p['outcomes']=[[id,False]];p['humans']=[dict(user_id=100,lost=False)];p['recruit']=None
        self.db.connection.execute('UPDATE npc_trips SET data=? WHERE id=?',(json.dumps(p),trip['id']));self.db.connection.commit()
        return id,trip['id']

    async def test_unappraised_npc_and_human_can_share_one_expedition(self):
        id,token=await self.mixed_trip()
        self.assertTrue(self.db._enterprise_away_locked(-100,10,100,self.stamp,self.stamp+1))
        v=await self.db.holdings_view(-100,10);self.assertTrue(next(p for p in v['people'] if p['user_id']==100)['expedition_active'])
        self.assertNotIn('humans',v['npc']['trips'][0]);self.assertNotIn('outcomes',v['npc']['trips'][0])
        self.stamp+=HOUR;v=await self.db.holdings_view(-100,10)
        self.assertEqual(v['npc']['trips'][0]['francs'],100)
        self.assertEqual(len(v['npc']['trips'][0]['survivors']),2)
        self.assertEqual(await self.db.franc_balance(-100,100),10)
        balance=await self.db.franc_balance(-100,10);await self.db.holdings_view(-100,10)
        self.assertEqual(await self.db.franc_balance(-100,10),balance)
        self.assertFalse(self.db._enterprise_away_locked(-100,10,100,self.stamp,self.stamp+1))

    async def test_transfer_during_mixed_trip_does_not_restore_old_ownership(self):
        id,token=await self.mixed_trip()
        await self.db.force_enslave(-100,100,20)
        self.stamp+=HOUR;v=await self.db.holdings_view(-100,10)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],20)
        self.assertEqual(v['npc']['trips'][0]['francs'],50)

    async def test_disable_cancels_mixed_trip_without_leaving_human_absent(self):
        await self.mixed_trip();await self.db.arena_set_module(-100,10,'slavery',False,0)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM slave_expedition_members WHERE active=1').fetchone()[0],0)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)

    async def test_wallet_upkeep_is_same_offline_and_with_hourly_refreshes(self):
        import sqlite3
        from contextlib import closing
        id=await self.buy();await self.db.enterprise_create(-100,10,'mine')
        v=await self.db.holdings_view(-100,10);site=v['sites'][0]
        await self.db.enterprise_batch(-100,10,[100],site['id'],'worker',v['revision'],npcs=[id])
        self.db.connection.execute('UPDATE franc_balances SET balance=1 WHERE chat_id=-100 AND user_id=10');self.db.connection.commit()
        path=Path(self.temp.name)/'offline.sqlite'
        with closing(sqlite3.connect(path)) as backup:self.db.connection.backup(backup)
        clone=Database(path);await clone.connect()
        try:
            start=self.stamp
            for hour in range(1,25):self.stamp=start+hour*HOUR;await self.db.holdings_view(-100,10)
            await clone.holdings_view(-100,10)
            self.assertEqual(await self.db.franc_balance(-100,10),await clone.franc_balance(-100,10))
            a=self.row(id)['data'];b=json.loads(clone.connection.execute('SELECT data FROM fictional_workers WHERE id=?',(id,)).fetchone()[0])
            for key in ('health','loyalty','fatigue','unpaid','remainder','cost_remainder'):self.assertEqual(a[key],b[key],key)
        finally:await clone.close()

    async def test_expiry_warning_requires_delivery_and_cannot_be_reset_by_refresh(self):
        await self.buy()
        self.db.connection.execute('DELETE FROM workforce_warnings');self.db.connection.commit()
        with self.db.connection:self.db._workforce_tick_locked(-100,10)
        self.stamp+=4*DAY
        with self.db.connection:self.db._workforce_roll_locked(Always())
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM workforce_events').fetchone()[0],0)
        a=(await self.db.holdings_view(-100,10))['npc']['workforce']['warning']['deadline']
        self.stamp+=5*HOUR
        b=(await self.db.holdings_view(-100,10))['npc']['workforce']['warning']['deadline']
        self.assertEqual(a,b)

    async def test_module_disable_cancels_new_incident_without_freeing_human(self):
        id=self.make_event();await self.event(id)
        await self.db.arena_set_module(-100,10,'slavery',False,0)
        await self.db.arena_set_module(-100,10,'slavery',True,1)
        self.stamp+=DAY
        self.assertEqual((await self.event(id))['status'],'cancelled')
        self.assertIsNotNone(await self.db.get_owner(-100,100))

    async def test_disabled_module_does_not_charge_offline_upkeep_or_finish_training(self):
        id=await self.buy()
        await self.act('npc_train',id=id,revision=self.row(id)['revision'],kind='work')
        balance=await self.db.franc_balance(-100,10)
        await self.db.arena_set_module(-100,10,'slavery',False,0)
        self.stamp+=2*DAY
        await self.db.arena_set_module(-100,10,'slavery',True,1)
        v=await self.db.holdings_view(-100,10)
        self.assertEqual(await self.db.franc_balance(-100,10),balance)
        self.assertEqual(self.row(id)['data']['profession_level'],1)
        self.stamp+=12*HOUR;await self.db.holdings_view(-100,10)
        self.assertEqual(self.row(id)['data']['profession_level'],2)

    async def test_trip_snapshots_rewards_and_same_day_recruit_do_not_duplicate(self):
        id=await self.buy();await self.act('npc_appraise',id=id,revision=self.row(id)['revision'])
        q=await self.act('npc_trip_quote',ids=[id],mission='outskirts')
        await self.act('npc_trip',ids=[id],mission='outskirts',revision=q['quote']['revision'])
        trip=self.db.connection.execute('SELECT * FROM npc_trips').fetchone();data=json.loads(trip['data'])
        data['outcomes']=[[id,False]];data['recruit']=None
        self.db.connection.execute('UPDATE npc_trips SET data=? WHERE id=?',(json.dumps(data),trip['id']));self.db.connection.commit()
        with self.assertRaises(ValueError):await self.db.expedition_quote(-100,10,'outskirts',[100])
        self.stamp+=HOUR
        v=await self.db.holdings_view(-100,10)
        self.assertEqual(v['npc']['trips'][0]['pages'],1)
        self.assertEqual(self.row(id)['status'],'rest')
        before=await self.db.franc_balance(-100,10)
        await self.db.holdings_view(-100,10);self.assertEqual(before,await self.db.franc_balance(-100,10))
        with self.assertRaises(ValueError):await self.act('npc_trip',ids=[id],mission='outskirts')

    async def test_staggered_hourly_accounting_does_not_depend_on_refreshes(self):
        id=await self.buy();self.stamp+=HOUR//2
        # Worker B's tick deliberately differs by half an hour.
        second=await self.buy()
        start=self.stamp
        self.stamp=start+HOUR//2;await self.db.holdings_view(-100,10)
        self.assertEqual(self.row(id)['tick'],self.stamp)
        self.assertEqual(self.row(second)['tick'],start)
        self.stamp=start+HOUR;await self.db.holdings_view(-100,10)
        self.assertEqual(self.row(second)['tick'],self.stamp)

    async def test_api_identity_and_chat_checks_apply_to_npc_uuid_without_telegram_lookup(self):
        from aiohttp.test_utils import TestClient,TestServer
        from arena_web import create_arena_app
        from tests.test_arena import signed,TOKEN
        import time
        id=await self.buy();bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
        async with TestClient(TestServer(create_arena_app(self.db,bot,TOKEN))) as client:
            body=dict(action='npc_appraise',id=id,revision=self.row(id)['revision'],nonce=uuid4().hex)
            bad=await client.post('/api/holdings/-100',json=body)
            self.assertIn(bad.status,(400,401,403))
            result=await client.post('/api/holdings/-100',json=body,headers={'X-Telegram-Init-Data':signed(10,now=int(time.time()))})
            self.assertEqual(result.status,200,await result.text())
            self.assertEqual([c.args[1] for c in bot.get_chat_member.await_args_list],[10])
            other=await client.post('/api/holdings/-200',json={**body,'nonce':uuid4().hex},headers={'X-Telegram-Init-Data':signed(10,now=int(time.time()))})
            self.assertEqual(other.status,400)


class NpcSpriteTests(unittest.TestCase):
    def test_all_twelve_assets_are_transparent_small_and_resolve_from_public(self):
        from PIL import Image
        root=Path(__file__).resolve().parents[1]/'webapp'
        for profession in PROFESSIONS:
            for gender in ('male','female'):
                with self.subTest(profession=profession,gender=gender):
                    d=create(profession,gender=gender)
                    p=public(dict(id='test',data=d,status='rest',site=None,revision=0,price=100))
                    self.assertEqual(p['appearance'],profession+'-'+gender)
                    self.assertNotIn('rarity',p)
                    if gender=='female':
                        self.assertIn(d['name'].split(' · ')[0],FEMALE_NAMES)
                        self.assertEqual(p['profession_name'],FEMALE_PROFESSIONS[profession])
                    for key,size,limit in (('sprite_url',(512,768),450000),('thumbnail_url',(160,240),50000)):
                        path=root/p[key].removeprefix('/static/')
                        self.assertTrue(path.is_file(),path)
                        self.assertLess(path.stat().st_size,limit)
                        with Image.open(path) as img:
                            self.assertEqual(img.size,size)
                            self.assertEqual(img.mode,'RGBA')
                            self.assertEqual(img.getchannel('A').getextrema(),(0,255))
                            self.assertEqual(img.getpixel((0,0))[3],0)

    def test_bad_or_legacy_appearance_cannot_inject_an_asset_url(self):
        d=create('miner',gender='male');d.update(gender='../../oops',appearance='https://evil.invalid/a.png')
        p=public(dict(id='test',data=d,status='rest',site=None,revision=0,price=100))
        self.assertEqual(p['sprite_url'],'/static/assets/npc-workers-v1/miner-male.png')
        with self.assertRaises(ValueError):create('miner',gender='invalid')


if __name__=='__main__':unittest.main()
