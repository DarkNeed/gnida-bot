"""Settlements: real wallet transactions, shared hex claims and reward-free combat."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from uuid import uuid4
from aiohttp.test_utils import TestClient,TestServer
from database import Database
from arena_kingdom_rules import neighbours,distance,terrain,capacity,SITES,HOUR,DAY,INCIDENTS,incident_kind,NEUTRAL_LANDS,land_cap
from arena_raid_engine import finish_if_needed
from arena_web import create_arena_app
from test_arena import signed,TOKEN


class KingdomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.db=Database(Path(self.folder.name)/'world.sqlite3');await self.db.connect()
        self.now=1800000000;self.clock=patch('arena_kingdom.kingdom_now',side_effect=lambda:self.now);self.clock.start();self.addCleanup(self.clock.stop)
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Тестовый мир')
            for actor in (10,20,30):
                await self.db.upsert_user(chat,actor,str(actor),'Игрок '+str(actor))
                self.db._arena_profile_locked(chat,actor,True);self.db._guild_hunter_locked(actor)
                self.db._add_francs_locked(chat,actor,1000000)
        self.db.connection.execute("UPDATE personal_profiles SET class_id='warrior',level=20,progression_level=20,progression_pending_level=0,loadout='[\"bum_punch\",\"steel_charge\"]'")
        self.db.connection.execute('UPDATE guild_hunters SET rank=5,peak_rank=5')
        self.db.connection.commit()
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))

    async def asyncTearDown(self):await self.db.close();self.folder.cleanup()

    async def view(self,actor=10,chat=-100):return await self.db.kingdom_view(chat,actor)

    async def action(self,action,actor=10,chat=-100,**fields):
        view=await self.view(actor,chat);town=next((t for t in view['towns'] if t['own']),None)
        body=dict(action=action,confirm=True,nonce=uuid4().hex,**({} if town is None else dict(town=town['id'],revision=town['revision'])),**fields)
        return await self.db.kingdom_action(chat,actor,body)

    async def found(self,actor=10,chat=-100,q=7,r=5):
        result=await self.action('found',actor,chat,q=q,r=r,name='Рассвет')
        # Pre-existing development tests use a funded municipal budget. This
        # fixture grant is not a production founding bonus or a wallet debit.
        from arena_kingdom_finance import credit
        row=self.town(actor,chat);credit(self.db,row,3000000);self.db._kingdom_save_locked(row);self.db.connection.commit()
        result['view']=await self.view(actor,chat);return result

    def budget(self,actor=10,chat=-100):
        from arena_kingdom_finance import balance
        return balance(self.db,self.town(actor,chat))

    def town(self,actor=10,chat=-100):
        row=self.db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=? AND owner=?',(chat,actor)).fetchone()
        return self.db._kingdom_row_locked(row['id'])

    def incident(self,kind='bandits',actor=10):
        row=self.town(actor);row['data']['event']=dict(id='test-event-'+str(actor),kind=kind,started=self.now,deadline=self.now+24*HOUR,escrow=0,battle=None,attempted=[])
        self.db._kingdom_save_locked(row);self.db.connection.commit()

    async def finish(self,token,won=True):
        async with self.db._lock:
            with self.db.connection:
                row=self.db._raid_row_locked(token);data=json.loads(row['data_json'])
                if won:
                    for f in data['enemies'].values():f['hp']=0
                else:
                    for p in data['players'].values():p['fighter']['hp']=0
                self.assertTrue(finish_if_needed(data));self.db._raid_finish_locked(row,data)
        return row,data

    def test_hex_geometry_and_terrain_are_consistent(self):
        for q in range(15):
            for r in range(11):
                for other in neighbours(q,r):
                    self.assertIn((q,r),neighbours(*other));self.assertEqual(distance((q,r),other),1)
        self.assertEqual(terrain('seed',3,0),'river')
        self.assertEqual(terrain('seed',12,2),'road')

    async def test_found_wallet_ownership_chat_isolation_and_no_passive_money(self):
        before=await self.db.franc_balance(-100,10);result=await self.found()
        self.assertEqual(result['view']['balance'],before-20000)
        self.assertEqual(len(result['view']['towns']),1)
        self.assertFalse((await self.view(chat=-200))['towns'])
        other=await self.view(actor=20);self.assertNotIn('resources',other['towns'][0])
        self.now+=12*HOUR
        await self.view()
        self.assertEqual(await self.db.franc_balance(-100,10),before-20000)

    async def test_found_eligibility_and_capital_spacing(self):
        self.db.connection.execute('UPDATE guild_hunters SET rank=2 WHERE actor_id=10');self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'ранг'):await self.found()
        self.db.connection.execute('UPDATE guild_hunters SET rank=3 WHERE actor_id=10');self.db.connection.commit()
        for q,r in ((3,0),(1,2),(-1,0),(True,0)):
            with self.assertRaises(ValueError):await self.found(q=q,r=r)
        await self.found()
        with self.assertRaises(ValueError):await self.found()
        with self.assertRaisesRegex(ValueError,'три'):await self.found(actor=20,q=7,r=4)

    async def test_competing_claim_and_same_nonce_only_charge_once(self):
        request=dict(action='found',q=7,r=5,name='Город',confirm=True,nonce=uuid4().hex)
        results=await asyncio.gather(*(self.db.kingdom_action(-100,10,request) for _ in range(2)))
        self.assertEqual(results[0]['view']['balance'],980000);self.assertEqual(results[1]['view']['balance'],980000)
        with self.assertRaises(ValueError):await self.db.kingdom_action(-100,10,dict(request,name='Другой'))
        with self.assertRaises(ValueError):await self.db.kingdom_action(-100,20,dict(request,nonce=uuid4().hex))

    async def test_foreign_owner_cross_chat_stale_revision_cannot_spend(self):
        await self.found();town=self.town()
        body=dict(action='build',building='barracks',town=town['id'],revision=town['revision'],confirm=True,nonce=uuid4().hex)
        for chat,actor in ((-100,20),(-200,10)):
            with self.assertRaises(ValueError):await self.db.kingdom_action(chat,actor,body)
        await self.db.kingdom_action(-100,10,body)
        with self.assertRaises(ValueError):await self.db.kingdom_action(-100,10,dict(body,nonce=uuid4().hex))
        self.assertEqual(await self.db.franc_balance(-100,10),980000)
        self.assertEqual(self.budget(),3000000-9000)

    async def test_build_clock_queue_caps_and_consumption(self):
        await self.found();await self.action('build',building='sawmill')
        with self.assertRaises(ValueError):await self.action('build',building='quarry')
        self.assertEqual(self.town()['data']['buildings']['sawmill'],0)
        self.now+=6*HOUR;await self.view();self.assertEqual(self.town()['data']['buildings']['sawmill'],1)
        row=self.town();row['data']['event']=None;row['data']['next_event']=self.now+30*24*HOUR;self.db._kingdom_save_locked(row);self.db.connection.commit()
        self.now+=8*24*HOUR;await self.view();d=self.town()['data']
        self.assertLessEqual(d['resources']['wood'],capacity(d));self.assertEqual(d['resources']['wood'],capacity(d))
        self.assertLessEqual(d['population'],55)
        await self.action('build',building='sawmill');self.now+=DAY;await self.view()
        with self.assertRaises(ValueError):await self.action('build',building='sawmill')

    async def test_production_preserves_earned_order_above_recovery_cap(self):
        await self.found();row=self.town();row['data']['order']=95
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        self.now+=HOUR;await self.view()
        self.assertEqual(self.town()['data']['order'],95)

    async def test_population_is_slow_and_poll_frequency_cannot_create_people(self):
        await self.found()
        for _ in range(5):self.now+=HOUR;await self.view()
        self.assertEqual(self.town()['data']['population'],36)
        self.now+=HOUR;await self.view()
        self.assertEqual(self.town()['data']['population'],37)

    async def test_money_cannot_bypass_build_time_promotion_age_or_neutral_land(self):
        await self.found();await self.action('build',building='barracks',finish=0,price=0)
        self.now+=HOUR;await self.view()
        self.assertEqual(self.town()['data']['buildings']['barracks'],0)
        self.assertEqual(self.town()['data']['construction']['finish']-self.now,5*HOUR)
        with self.assertRaises(ValueError):await self.action('annex',q=8,r=5)
        row=self.town();row['data'].update(population=55,prestige=100,construction=None)
        row['data']['buildings'].update(hall=2,sawmill=2,quarry=2)
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'Возраст'):await self.action('promote',founded_at=0)
        self.assertEqual(land_cap(row['data']),3)
        row['data']['stage']=2;self.assertEqual(land_cap(row['data']),5)
        row['data']['stage']=3;self.assertEqual(land_cap(row['data']),7)

    async def test_faction_choice_persists_relation_and_scheduled_followup_without_money_mint(self):
        await self.found();self.incident('velvet_coup');balance=await self.db.franc_balance(-100,10)
        before=deepcopy(self.town()['data']['resources'])
        await self.action('event',choice='envoy')
        d=self.town()['data'];self.assertEqual(d['factions']['velvet'],2)
        self.assertEqual(d['stories'],['velvet_embassy']);self.assertEqual(d['resources']['wood'],before['wood']-80)
        self.assertEqual(await self.db.franc_balance(-100,10),balance)
        self.now+=18*HOUR;await self.view()
        self.assertEqual(self.town()['data']['event']['kind'],'velvet_embassy')
        self.assertEqual(self.town()['data']['stories'],[])
        await self.action('event',choice='exchange')
        self.assertEqual(self.town()['data']['factions']['velvet'],4)

    async def test_capital_requires_a_month_and_cannot_expand_past_seven(self):
        await self.found();row=self.town()
        row['data'].update(stage=2,founded_at=self.now-35*DAY,population=75,prestige=18)
        row['data']['buildings']={key:1 for key in row['data']['buildings']};row['data']['buildings']['hall']=3
        self.db._kingdom_save_locked(row)
        self.db._add_francs_locked(-100,10,2000000)
        self.db.connection.execute('UPDATE guild_hunters SET rank=6 WHERE actor_id=10');self.db.connection.commit()
        before=await self.db.franc_balance(-100,10);result=await self.action('promote',price=1)
        capital=next(t for t in result['view']['towns'] if t['own'])
        self.assertEqual(capital['stage'],3);self.assertEqual(capital['territory_cap'],7)
        self.assertIsNone(capital['promotion']);self.assertEqual(result['view']['balance'],before)
        self.assertEqual(self.budget(),3000000-1500000)
        hall=next(b for b in capital['building_options'] if b['id']=='hall')
        self.assertEqual(hall['quote']['finish']-hall['quote']['started'],7*DAY)
        with self.assertRaises(ValueError):await self.action('promote')

    def test_mundane_incidents_are_rare_and_followups_never_spawn_randomly(self):
        self.assertEqual(sum(e.get('weight',0) for e in INCIDENTS.values()),100)
        self.assertEqual(INCIDENTS['fire']['weight']+INCIDENTS['blight']['weight'],4)
        for index in range(1000):self.assertGreater(INCIDENTS[incident_kind('stable',index)]['weight'],0)

    async def test_legacy_town_gets_additive_metadata_without_losing_job(self):
        await self.found();await self.action('build',building='quarry');row=self.town()
        job=deepcopy(row['data']['construction'])
        for key in ('founded_at','growth_hours','factions','stories'):row['data'].pop(key)
        self.db._kingdom_save_locked(row);self.db.connection.commit();await self.view()
        self.assertEqual(self.town()['data']['construction'],job)
        self.assertEqual(self.town()['data']['founded_at'],self.now)

    async def test_insufficient_materials_francs_and_injected_failure_roll_back(self):
        await self.found();row=self.town();row['data']['resources']['wood']=0;self.db._kingdom_save_locked(row);self.db.connection.commit()
        before=await self.db.franc_balance(-100,10)
        with self.assertRaises(ValueError):await self.action('build',building='farm')
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        with patch.object(self.db,'_kingdom_save_locked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):await self.action('supplies')
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        with self.assertRaises(ValueError):await self.action('build',building=[])

    async def test_annex_only_adjacent_unoccupied_land_and_stage_cap(self):
        await self.found();await self.action('annex',q=7,r=4);await self.action('annex',q=8,r=4)
        self.assertEqual(len((await self.view())['towns'][0]['tiles']),3)
        with self.assertRaises(ValueError):await self.action('annex',q=10,r=5)
        await self.found(actor=20,q=12,r=5)
        with self.assertRaises(ValueError):await self.action('annex',q=0,r=0,actor=20)

    async def test_promotion_requirements_and_cost_server_owned(self):
        await self.found()
        with self.assertRaises(ValueError):await self.action('promote')
        row=self.town();row['data']['population']=50;row['data']['buildings'].update(hall=2,sawmill=1,quarry=1)
        row['data'].update(founded_at=self.now-14*DAY,prestige=6)
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        before=await self.db.franc_balance(-100,10)
        await self.action('promote',price=0)
        self.assertEqual(self.town()['data']['stage'],2);self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertEqual(self.budget(),3000000-250000)
        with self.assertRaises(ValueError):await self.action('promote')

    async def test_disaster_options_and_automatic_expiry_do_not_destroy_houses(self):
        await self.found();self.incident('fire')
        await self.action('event',choice='bucket');self.assertIsNone(self.town()['data']['event'])
        self.incident('blight')
        with self.assertRaises(ValueError):await self.action('event',choice='reserve')
        before=deepcopy(self.town()['data']['buildings']);self.now+=25*HOUR
        await self.view();row=self.town()
        self.assertEqual(row['data']['buildings'],before);self.assertIsNone(row['data']['event'])

    async def test_bounty_escrow_paid_once_through_real_reward_free_combat(self):
        await self.found();self.incident()
        before=await self.db.franc_balance(-100,10);helper_before=await self.db.franc_balance(-100,20)
        await self.action('event',choice='bounty');self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertEqual(self.budget(),3000000-5000)
        town=self.town();profile=dict(self.db._arena_profile_locked(-100,20,True))
        result=await self.action('help',actor=20,town=town['id'],revision=town['revision'])
        raid=await self.db.arena_raid_get(result['battle']);battle=json.loads(raid['data_json'])
        self.assertTrue(battle['rp_mode']);self.assertFalse(battle['rewards_enabled'])
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(result['battle'],20,'finish')
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(result['battle'],20,'join',rp_template='injected')
        with self.assertRaises(ValueError):await self.action('help',actor=30,town=town['id'],revision=self.town()['revision'])
        row,data=await self.finish(result['battle'])
        self.assertEqual(await self.db.franc_balance(-100,20),helper_before+4500)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_inventory').fetchone()[0],0)
        self.assertEqual(self.db._arena_profile_locked(-100,20,True)['xp'],profile['xp'])
        self.assertIsNone(self.town()['data']['event'])
        with self.assertRaises(ValueError):
            with self.db.connection:self.db._raid_finish_locked(row,data)
        self.assertEqual(await self.db.franc_balance(-100,20),helper_before+4500)

    async def test_failed_helper_one_attempt_and_expired_order_refunds_owner(self):
        await self.found();self.incident();await self.action('event',choice='bounty')
        row=self.town();result=await self.action('help',actor=20,town=row['id'],revision=row['revision'])
        await self.finish(result['battle'],False)
        row=self.town()
        with self.assertRaises(ValueError):await self.action('help',actor=20,town=row['id'],revision=row['revision'])
        self.now+=25*HOUR;await self.view()
        self.assertEqual(await self.db.franc_balance(-100,10),980000)
        self.assertEqual(await self.db.franc_balance(-100,20),1000000)

    async def test_late_battle_win_cannot_claim_expired_escrow(self):
        await self.found();self.incident();await self.action('event',choice='bounty')
        row=self.town();result=await self.action('help',actor=20,town=row['id'],revision=row['revision'])
        self.now+=25*HOUR;await self.finish(result['battle'])
        self.assertEqual(await self.db.franc_balance(-100,10),980000)
        self.assertEqual(await self.db.franc_balance(-100,20),1000000)

    async def test_restart_keeps_world_build_and_resources(self):
        await self.found();await self.action('build',building='quarry');before=await self.view()
        await self.db.close();await self.db.connect();after=await self.view()
        self.assertEqual(before,after)

    async def test_incident_deadline_is_not_delayed_by_staying_offline(self):
        await self.found();self.now+=31*HOUR;view=await self.view()
        row=self.town()
        self.assertIsNone(row['data']['event'])
        self.assertTrue(any('истекло во время отсутствия' in h['text'] for h in row['data']['history']))
        self.assertEqual(row['data']['next_event'],self.now+18*HOUR)

    async def test_real_client_renders_map_founder_and_pre_data_errors(self):
        import shutil,subprocess
        if not shutil.which('node'):self.skipTest('Node required')
        await self.found();self.incident();view=await self.view()
        result=subprocess.run(['node','tests/kingdom_client.cjs'],input=json.dumps(view),cwd=Path(__file__).resolve().parents[1],
                              text=True,encoding='utf-8',capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    async def test_command_group_and_private_entries_are_separate(self):
        from handlers.kingdom import create_kingdom_router,KINGDOM_RE
        router=create_kingdom_router(self.db,self.bot,'GnidoBot',True)
        callback=router.message.handlers[0].callback
        self.assertIsNotNone(KINGDOM_RE.fullmatch('/королевство@GnidoBot'))
        self.assertIsNotNone(KINGDOM_RE.fullmatch('/карта@GnidoBot'))
        self.assertIsNotNone(KINGDOM_RE.fullmatch('/карта'))
        self.assertIsNone(KINGDOM_RE.fullmatch('/королевство чужой'))
        message=SimpleNamespace(from_user=SimpleNamespace(id=10,is_bot=False,username='tester',full_name='Tester'),
            chat=SimpleNamespace(id=-100,type='supergroup',title='Тестовый мир'),answer=AsyncMock())
        await callback(message)
        button=message.answer.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
        self.assertIn('kingdom_-100',button.url)
        message.chat=SimpleNamespace(id=10,type='private');message.answer.reset_mock()
        await callback(message)
        button=message.answer.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
        self.assertIn('startapp=kingdom',button.url)
        self.assertNotIn('kingdom_-100',button.url)

    async def test_http_signed_identity_live_membership_and_no_foreign_chat(self):
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN)));await client.start_server()
        headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
        body=dict(chat=-100,action='found',q=7,r=5,name='HTTP',nonce=uuid4().hex,confirm=True,price=0,actor=20)
        try:
            self.assertEqual((await client.get('/api/kingdom/world?chat=-100')).status,400)
            self.assertEqual((await client.get('/api/kingdom/world?chat=-999',headers=headers)).status,400)
            self.bot.get_chat_member.return_value.status='left'
            self.assertEqual((await client.post('/api/kingdom/world',headers=headers,json=body)).status,400)
            self.bot.get_chat_member.return_value.status='member'
            response=await client.post('/api/kingdom/world',headers=headers,json=body)
            self.assertEqual(response.status,200,await response.text());self.assertEqual((await response.json())['view']['balance'],980000)
            self.assertFalse((await self.view(actor=20))['towns'][0]['own'])
            # The client cannot inject another contract or fabricate a POI.
            self.assertEqual((await client.post('/api/kingdom/activity',headers=headers,json=dict(chat=-100,q=0,r=0,target='s_dungeon',nonce=uuid4().hex))).status,400)
            self.assertEqual((await client.post('/api/kingdom/activity',headers=headers,json=dict(chat=-100,q=10,r=1,target='chaplain',nonce=uuid4().hex))).status,400)
            response=await client.post('/api/kingdom/activity',headers=headers,json=dict(chat=-100,q=1,r=2,target='s_dungeon',nonce=uuid4().hex))
            self.assertEqual(response.status,200,await response.text())
            run=await self.db.guild_get((await response.json())['id'],10)
            self.assertEqual(run['contract']['id'],'f_dungeon')
        finally:await client.close()


if __name__=='__main__':unittest.main()
