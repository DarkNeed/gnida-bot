import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from uuid import uuid4

from database import Database,business_income_tax
from enterprise_protection import HOUR,DAY,orc_roster


class ProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.db=Database(Path(self.folder.name)/'protection.sqlite')
        await self.db.connect();self.stamp=1800000000
        self.clock=patch('database.utc_timestamp',side_effect=lambda:self.stamp);self.clock.start()
        self.raid_clock=patch('arena_raid.time.time',side_effect=lambda:self.stamp);self.raid_clock.start()
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Тест')
            for user in (10,20,30,100,101,102,103):await self.db.upsert_user(chat,user,str(user),str(user))
            for user in (100,101,102,103):await self.db.force_enslave(chat,user,10)
            await self.db.credit_francs(chat,10,20000)
            await self.db.enterprise_create(chat,10,'mine')
        for user in (10,20,30):
            self.db._arena_profile_locked(-100,user,True)
            self.db.connection.execute("UPDATE personal_profiles SET class_id='warrior',level=20,progression_level=20,progression_pending_level=0,loadout='[\"bum_punch\",\"armor_split\"]' WHERE chat_id=0 AND user_id=?",(user,))
        self.db.connection.commit()

    async def asyncTearDown(self):
        self.raid_clock.stop();self.clock.stop();await self.db.close();self.folder.cleanup()

    async def act(self,action,chat=-100,actor=10,**values):
        return await self.db.protection_action(chat,actor,dict(action=action,confirm=True,nonce=uuid4().hex,**values))

    async def off(self):return await self.act('protection_toggle',enabled=False,revision=0)

    def event(self,kind):
        with self.db.connection:ident=self.db._protection_event_locked(-100,10,kind)
        return self.db.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(ident,)).fetchone()

    async def raid(self):
        event=self.event('orcs');result=await self.act('protection_raid',id=event['id'],revision=event['revision'])
        return await self.db.arena_raid_get(result['raid'])

    async def test_tax_default_exemption_local_scope_and_no_catchup(self):
        with self.db.connection:
            a=self.db._credit_business_income_locked(-100,10,'2026-11-02',1000)
        self.assertEqual(a,(895,105))
        await self.off()
        site=self.db._enterprise_locked(-100,10)
        with self.db.connection:
            self.assertEqual(self.db._enterprise_credit_site_locked(site,'2026-11-02',1000),(1000,0))
            self.assertEqual(self.db._credit_business_income_locked(-100,10,'2026-11-02',100),(65,35))
            other=self.db._enterprise_locked(-200,10)
            self.assertEqual(self.db._enterprise_credit_site_locked(other,'2026-11-02',1000),(895,105))
        before=await self.db.franc_balance(-100,10)
        await self.act('protection_toggle',enabled=True,revision=1)
        self.assertEqual(await self.db.franc_balance(-100,10),before-250)
        with self.db.connection:
            net,tax=self.db._enterprise_credit_site_locked(site,'2026-11-02',1000)
        self.assertEqual(tax,business_income_tax(2100)-business_income_tax(1100))
        self.assertEqual(net+tax,1000)

    async def test_toggle_idempotency_validation_and_old_income_settled_first(self):
        site=self.db._enterprise_locked(-100,10)
        for u in (100,101,102,103):await self.db.enterprise_assign(-100,10,u,'worker',site['id'])
        self.stamp+=24*HOUR
        b=dict(action='protection_toggle',confirm=True,nonce=uuid4().hex,enabled=False,revision=0)
        await self.db.protection_action(-100,10,b)
        before=await self.db.franc_balance(-100,10)
        await self.db.protection_action(-100,10,b)
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertEqual(self.db.connection.execute('SELECT last_accrued FROM businesses WHERE id=?',(site['id'],)).fetchone()[0],self.stamp)
        with self.assertRaises(ValueError):await self.act('protection_toggle',enabled=True,revision=0)
        with self.assertRaises(ValueError):await self.act('protection_toggle',actor=20,enabled=False,revision=0)
        with self.assertRaises(ValueError):await self.act('protection_toggle',enabled='false',revision=1)

    async def test_schedule_deadlines_reconnect_and_restart_do_not_erase_threat(self):
        await self.off();self.stamp+=DAY
        with patch('enterprise_protection.random.SystemRandom') as rng:
            rng.return_value.choice.return_value='orcs'
            view=await self.db.holdings_view(-100,10)
        event=next(e for e in view['protection']['events'] if e['status']=='open');deadline=event['deadline']
        await self.act('protection_toggle',enabled=True,revision=1)
        view=await self.db.holdings_view(-100,10)
        self.assertEqual(view['protection']['events'][0]['deadline'],deadline)
        self.db._init_protection();view=await self.db.holdings_view(-100,10)
        self.assertEqual(view['protection']['events'][0]['status'],'open')
        self.stamp=deadline+1;view=await self.db.holdings_view(-100,10)
        self.assertEqual(view['protection']['events'][0]['status'],'lost')
        self.assertEqual(view['protection']['outage_until'],self.stamp+12*HOUR)

    async def test_strike_spends_once_and_outage_stops_npc_and_human_income(self):
        site=self.db._enterprise_locked(-100,10)
        await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        market=(await self.db.holdings_view(-100,10))['npc']['market'][0]
        await self.db.npc_action(-100,10,dict(action='npc_buy',id=market['id'],nonce=uuid4().hex))
        r=self.db._npc_decode(self.db.connection.execute('SELECT * FROM fictional_workers WHERE id=?',(market['id'],)).fetchone())
        await self.db.npc_action(-100,10,dict(action='npc_assign',id=r['id'],site=site['id'],revision=r['revision'],nonce=uuid4().hex))
        event=self.event('strike');before=await self.db.franc_balance(-100,10)
        await self.act('protection_strike',id=event['id'],revision=0,paid=True)
        after=await self.db.franc_balance(-100,10);self.assertEqual(before-after,140)
        self.stamp+=6*HOUR
        result=await self.db.settle_business(-100,10)
        self.assertEqual(result['gross_income'],0)
        self.assertGreater(result['upkeep'],0)
        with self.assertRaises(ValueError):await self.act('protection_strike',id=event['id'],revision=0,paid=True)
        self.stamp+=HOUR;result=await self.db.settle_business(-100,10)
        self.assertGreater(result['gross_income'],0)

    async def test_mass_escape_is_bounded_and_ownership_epoch_safe(self):
        e=self.event('escape');self.stamp=e['deadline']+1
        view=await self.db.holdings_view(-100,10)
        opened=self.db.connection.execute("SELECT * FROM workforce_events WHERE json_extract(data,'$.protection_event')=?",(e['id'],)).fetchall()
        self.assertEqual(len(opened),3)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM ownership WHERE chat_id=-100 AND owner_id=10').fetchone()[0],4)
        for r in opened:self.assertEqual(r['deadline'],self.stamp+8*HOUR)
        worker=int(opened[0]['worker']);await self.db.force_enslave(-100,worker,20)
        self.stamp+=9*HOUR;await self.db.holdings_view(-100,10)
        self.assertTrue(self.db._arena_owns_locked(-100,20,worker))
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM ownership WHERE chat_id=-100 AND owner_id=10').fetchone()[0],1)

    async def test_three_fixed_a_rank_orcs_team_required_and_no_rp_injection(self):
        from arena_raid_web import raid_view
        row=await self.raid();token=row['token']
        await self.db.arena_raid_setup(token,10,'join')
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(token,10,'start')
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(token,20,'join',rp_template='invalid')
        await self.db.arena_raid_setup(token,20,'join')
        row=await self.db.arena_raid_setup(token,10,'start')
        d=json.loads(row['data_json']);self.assertEqual(len(d['enemies']),3)
        self.assertFalse(d['rp_mode']);self.assertEqual(len(d['enemy_intents']),3)
        self.assertEqual(sorted(f['stats']['max_hp'] for f in d['enemies'].values()),[410,450,480])
        self.assertTrue(all(f['npc_tier']==3 and f['level']==19 for f in d['enemies'].values()))
        v=await raid_view(self.db,row,10);self.assertTrue(v['enterprise_defense']);self.assertFalse(v['is_master'])
        self.assertTrue(all(f['rp_flip'] for f in v['data']['enemies'].values()))
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(token,10,'finish')
        self.assertEqual([t['definition']['stats']['max_hp'] for t in orc_roster()],[480,450,410])

    async def test_conditions_raise_loyalty_and_prevent_escape_without_identity_changes(self):
        v=await self.db.holdings_view(-100,10);worker=v['npc']['market'][0]
        await self.db.npc_action(-100,10,dict(action='npc_buy',id=worker['id'],nonce=uuid4().hex))
        before=self.db._npc_decode(self.db.connection.execute('SELECT * FROM fictional_workers WHERE id=?',(worker['id'],)).fetchone())['data']
        e=self.event('escape');await self.act('protection_conditions',id=e['id'],revision=0)
        after=self.db._npc_decode(self.db.connection.execute('SELECT * FROM fictional_workers WHERE id=?',(worker['id'],)).fetchone())['data']
        self.assertEqual(after['loyalty'],min(100,before['loyalty']+10))
        for key in ('name','rarity','appearance'):self.assertEqual(after[key],before[key])

    async def test_victory_is_rewardless_and_failure_penalty_once(self):
        for won in (True,False):
            row=await self.raid();token=row['token']
            for user in (10,20):await self.db.arena_raid_setup(token,user,'join')
            row=await self.db.arena_raid_setup(token,10,'start');d=json.loads(row['data_json'])
            before=await self.db.franc_balance(-100,10);profile=dict(self.db._arena_profile_locked(-100,10,True))
            d.update(finished=True,won=won)
            with self.db.connection:self.db._raid_finish_locked(row,d)
            self.assertEqual(await self.db.franc_balance(-100,10),before)
            self.assertEqual(self.db._arena_profile_locked(-100,10,True)['xp'],profile['xp'])
            e=self.db.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(d['protection_event'],)).fetchone()
            self.assertEqual(e['status'],'defended' if won else 'lost')
            self.assertEqual(len(d['rewards']),0)
            with self.assertRaises(ValueError):
                with self.db.connection:self.db._raid_finish_locked(await self.db.arena_raid_get(token),d)

    async def test_notifications_lease_and_chat_invite_only_once(self):
        from enterprise_protection_notices import publish_protection
        from handlers.raids import RaidPublisher
        row=await self.raid()
        bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)))
        publisher=RaidPublisher(self.db,bot,'GnidoBot')
        await publish_protection(self.db,bot,'GnidoBot',publisher)
        await publish_protection(self.db,bot,'GnidoBot',publisher)
        self.assertEqual(bot.send_message.await_count,1)
        self.assertEqual(bot.send_message.await_args.args[0],-100)
        self.assertIn('A-ранга',bot.send_message.await_args.args[1])
        self.assertEqual((await self.db.arena_raid_get(row['token']))['message_id'],42)

    async def test_regular_encounter_still_rejects_four_enemies(self):
        from arena_encounters import validate_roster,create_encounter
        with self.assertRaises(ValueError):validate_roster(['goblin']*4)
        with self.assertRaises(ValueError):create_encounter([],[],{}, {},orc_roster()+orc_roster()[:1],10)

    async def test_foreign_event_cannot_be_resolved_and_cancelled_lobby_does_not_win(self):
        e=self.event('orcs')
        with self.assertRaises(ValueError):await self.act('protection_raid',actor=20,id=e['id'],revision=0)
        result=await self.act('protection_raid',id=e['id'],revision=0)
        await self.db.arena_raid_setup(result['raid'],10,'cancel')
        current=self.db.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(e['id'],)).fetchone()
        self.assertEqual(current['status'],'open')
        new=await self.act('protection_raid',id=e['id'],revision=current['revision'])
        self.assertNotEqual(new['raid'],result['raid'])

    async def test_each_enemy_defense_is_part_of_real_qte_flow(self):
        await self.db.arena_combat_settings(20,enabled=False)
        row=await self.raid();token=row['token']
        for user in (10,20):await self.db.arena_raid_setup(token,user,'join')
        row=await self.db.arena_raid_setup(token,10,'start')
        d=json.loads(row['data_json'])
        # Force all three threats onto the tester to exercise a multi-enemy flow.
        for intent in d['enemy_intents'].values():intent['targets']=['10']
        with self.db.connection:self.db._raid_save_locked(row,d)
        await self.db.arena_interactive_raid(token,10,1,'bum_punch',target='e2')
        flow=self.db._qte_load_locked('raid',token,10)
        self.assertEqual([s['kind'] for s in flow['stages']],['attack'])
        await self.db.arena_interactive_raid(token,10,1,proof=dict(abort=True),challenge_id=flow['stages'][0]['id'])
        await self.db.arena_interactive_raid(token,20,1,'defend')
        flow=self.db._qte_load_locked('raid',token,10)
        self.assertEqual(flow['stages'][0]['version'],4)
        self.assertEqual([s['encounter_enemy'] for s in flow['stages'][0]['members']],['e1','e2','e3'])


if __name__=='__main__':unittest.main()
