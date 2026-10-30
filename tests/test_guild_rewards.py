"""Unlimited attempts and three account-wide full reward wins, not starts."""
from copy import deepcopy
from datetime import datetime,timezone
from random import Random
import secrets
import unittest
from unittest.mock import patch
import test_guild as fixtures
from arena_guild_rules import CONTRACTS
from handlers.guild import GuildPublisher


class GuildRewardTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.GuildTests.asyncSetUp
    asyncTearDown=fixtures.GuildTests.asyncTearDown

    def set_used(self,actor,count,day=None):
        from arena_raid import raid_day
        with self.db.connection:
            self.db.connection.execute('INSERT OR REPLACE INTO guild_reward_days VALUES(?,?,?)',(actor,day or raid_day(),count))

    async def start_run(self,contract='c_dungeon',party=False,chat=-100):
        run=await self.db.guild_create(chat,10,contract,'reward-'+secrets.token_hex(12))
        if party:run=await self.db.guild_action(run['id'],20,'join',run['revision'])
        return await self.db.guild_action(run['id'],10,'start',run['revision'])

    async def settle(self,run,won=True,retreat=False,finds=0,extra_nodes=0,excluded=None):
        async with self.db._lock:
            with self.db.connection:
                row=self.db._guild_row_locked(run['id']);row['data']['finds']=finds
                # Test only payout; native room combat is covered in test_guild.
                row['data']['nodes']=[dict(id='loot-'+str(x),kind='treasure',cleared=True,layer=x,lane=1,links=[]) for x in range(extra_nodes)]
                if excluded:row['data']['players'][str(excluded)]['reward_blocked']=True
                with patch('arena_equipment_store.random.SystemRandom',side_effect=lambda:Random(21)):
                    self.db._guild_settle_locked(row,won,'test settlement',retreat)
                if run.get('battle'):
                    self.db.connection.execute("UPDATE arena_raids SET status='completed' WHERE token=?",(run['battle'],))
        return await self.db.guild_get(run['id'],10)

    async def test_third_full_fourth_and_fifth_allowed_with_exact_rewards(self):
        self.set_used(10,2)
        first=await self.start_run();first=await self.settle(first,finds=43)
        reward=first['results']['10'];base=CONTRACTS['c_dungeon']['reward']+43
        self.assertTrue(reward['full_reward']);self.assertEqual(reward['francs'],base)
        self.assertEqual(reward['reputation'],28);self.assertIn('трактат',reward['loot'])
        self.assertEqual(self.db._guild_used_locked(10),3)
        before_skills=self.db.connection.execute("SELECT SUM(quantity) FROM arena_inventory WHERE kind='skill'").fetchone()[0]
        before_bag=sum(r[0] for r in self.db.connection.execute('SELECT quantity FROM guild_bag WHERE actor_id=10'))
        for _ in range(2):
            run=await self.start_run();run=await self.settle(run,finds=43)
            reward=run['results']['10'];self.assertFalse(reward['full_reward'])
            self.assertEqual(reward['francs'],base//4);self.assertEqual(reward['reputation'],8)
            self.assertEqual(reward['loot'],'');self.assertEqual(self.db._guild_used_locked(10),3)
            self.assertEqual(sum(d['materials'] for d in reward['equipment_loot']),1)
            self.assertEqual(sum(len(d['items']) for d in reward['equipment_loot']),1)
        self.assertEqual(self.db.connection.execute("SELECT SUM(quantity) FROM arena_inventory WHERE kind='skill'").fetchone()[0],before_skills)
        self.assertEqual(sum(r[0] for r in self.db.connection.execute('SELECT quantity FROM guild_bag WHERE actor_id=10')),before_bag)

    async def test_reputation_thirty_percent_above_rank(self):
        self.set_used(10,3)
        run=await self.start_run('b_elite');run=await self.settle(run)
        self.assertEqual(run['results']['10']['reputation'],12)
        run=await self.start_run('f_hunt');run=await self.settle(run)
        self.assertEqual(run['results']['10']['reputation'],0)

    async def test_defeat_retreat_expiry_and_cancel_do_not_spend_bonus(self):
        for _ in range(4):
            run=await self.start_run('f_hunt');await self.settle(run,False)
        self.assertEqual(self.db._guild_used_locked(10),0)
        run=await self.start_run('f_dungeon');run=await self.settle(run,False,True,finds=41)
        self.assertEqual(run['results']['10']['francs'],20)
        self.assertEqual(self.db._guild_used_locked(10),0)
        run=await self.db.guild_create(-100,10,'f_hunt','cancel-without-bonus')
        await self.db.guild_action(run['id'],10,'leave',run['revision'])
        run=await self.start_run('f_dungeon')
        self.db.connection.execute('UPDATE guild_runs SET expires=0 WHERE id=?',(run['id'],));self.db.connection.commit()
        self.assertEqual((await self.db.guild_get(run['id'],10))['status'],'failed')
        self.assertEqual(self.db._guild_used_locked(10),0)
        self.assertEqual((await self.db.gear_view(-100,10))['items'],[])

    async def test_mixed_party_preview_and_individual_settlement(self):
        self.set_used(20,3)
        run=await self.db.guild_create(-100,10,'c_dungeon','mixed-rewards-lobby')
        run=await self.db.guild_action(run['id'],20,'join',run['revision'])
        modes={p['actor_id']:p['reward_preview'] for p in run['members']}
        self.assertTrue(modes[10]['full']);self.assertFalse(modes[20]['full'])
        self.assertEqual(modes[20]['francs_pct'],25);self.assertEqual(modes[20]['equipment_pct'],100)
        text,_=GuildPublisher(self.db,self.bot,'TestBot').card(run)
        self.assertIn('повторная награда',text);self.assertIn('полная награда',text)
        run=await self.db.guild_action(run['id'],10,'start',run['revision']);run=await self.settle(run,finds=20)
        full=run['results']['10'];reduced=run['results']['20']
        self.assertTrue(full['full_reward']);self.assertFalse(reduced['full_reward'])
        self.assertEqual(reduced['francs'],full['francs']//4)
        a=full['equipment_loot'][0]['items'][0];b=reduced['equipment_loot'][0]['items'][0]
        self.assertEqual((a['key'],a['rarity'],a['rank']),(b['key'],b['rarity'],b['rank']))
        self.assertEqual(self.db._guild_used_locked(10),1);self.assertEqual(self.db._guild_used_locked(20),3)
        self.assertTrue((await self.db.guild_view(-100,20))['daily']['unlimited'])

    async def test_total_materials_halved_not_minimum_per_room(self):
        self.set_used(10,3)
        run=await self.start_run();run=await self.settle(run,extra_nodes=2)
        loot=run['results']['10']['equipment_loot']
        self.assertEqual(len(loot),3);self.assertEqual(sum(d['materials'] for d in loot),2) # (3+1+1)//2
        self.assertEqual(sum((await self.db.gear_view(-100,10))['materials'].values()),2)

    async def test_repeat_dungeon_keeps_all_extra_equipment_rolls_and_rarity_odds(self):
        self.set_used(10,3);calls=[]
        original=self.db._gear_loot_locked
        def record(*args,**kwargs):calls.append(kwargs.copy());return original(*args,**kwargs)
        run=await self.start_run()
        with patch.object(self.db,'_gear_loot_locked',side_effect=record):run=await self.settle(run,extra_nodes=2)
        self.assertTrue(calls[0]['guaranteed'])
        self.assertEqual([c.get('chance') for c in calls],[.15,.25,.25])
        self.assertEqual(len(run['results']['10']['equipment_loot'][0]['items']),1)

    async def test_bonus_is_global_across_chats_and_character_slots(self):
        self.set_used(10,2)
        run=await self.start_run('c_hunt');await self.settle(run)
        with self.db.connection:
            self.db._character_account_locked(10)
            self.db.connection.execute('INSERT OR IGNORE INTO arena_character_grants VALUES(10,1980056841,0)')
            self.db.connection.execute('UPDATE arena_character_accounts SET active_slot=2 WHERE user_id=10')
        run=await self.start_run('c_hunt',chat=-200);run=await self.settle(run)
        self.assertFalse(run['results']['10']['full_reward'])
        for chat in (-100,-200):self.assertEqual((await self.db.guild_view(chat,10))['daily']['remaining'],0)

    async def test_midnight_uses_victory_day_not_start_day_and_persists(self):
        old='2026-10-30';new='2026-10-31';self.set_used(10,3,old)
        with patch('arena_guild.raid_day',return_value=old):
            run=await self.start_run();self.assertEqual(self.db._guild_used_locked(10),3)
        with patch('arena_guild.raid_day',return_value=new):
            run=await self.settle(run);self.assertTrue(run['results']['10']['full_reward'])
            self.assertEqual(run['results']['10']['reward_day'],new)
            await self.db.close();await self.db.connect()
            self.assertEqual(self.db._guild_used_locked(10),1)
        with patch('arena_guild.raid_day',return_value=old):self.assertEqual(self.db._guild_used_locked(10),3)

    async def test_duplicate_settlement_cannot_grant_or_count_twice(self):
        self.set_used(10,2);run=await self.start_run()
        async with self.db._lock:
            with self.db.connection:
                a=self.db._guild_row_locked(run['id']);b=deepcopy(a)
                self.db._guild_settle_locked(a,True,'win')
                before=(self.db._guild_used_locked(10),balance_locked(self.db,10))
                self.db._guild_settle_locked(b,True,'same win again')
                self.assertEqual(before,(self.db._guild_used_locked(10),balance_locked(self.db,10)))
        self.assertEqual(len((await self.db.gear_view(-100,10))['items']),1)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM guild_settlements WHERE run_id=?',(run['id'],)).fetchone()[0],1)

    async def test_ineligible_member_does_not_lose_full_reward(self):
        run=await self.start_run(party=True);run=await self.settle(run,excluded=20)
        self.assertTrue(run['results']['10']['full_reward']);self.assertFalse(run['results']['20']['full_reward'])
        self.assertEqual(self.db._guild_used_locked(20),0);self.assertEqual(run['results']['20']['equipment_loot'],[])

    async def test_legacy_start_quota_never_blocks_or_consumes_win_bonus(self):
        from arena_raid import raid_day
        with self.db.connection:self.db.connection.execute('INSERT INTO guild_daily VALUES(?,?,3)',(10,raid_day()))
        await self.db.close();await self.db.connect()
        self.assertEqual(self.db._guild_used_locked(10),0)
        run=await self.start_run();run=await self.settle(run)
        self.assertTrue(run['results']['10']['full_reward'])
        self.assertEqual(self.db.connection.execute('SELECT used FROM guild_daily WHERE actor_id=10').fetchone()[0],3)

    async def test_loot_error_rolls_back_bonus_and_all_rewards(self):
        self.set_used(10,2);run=await self.start_run()
        before=balance_locked(self.db,10)
        with self.assertRaises(RuntimeError):
            async with self.db._lock:
                with self.db.connection:
                    row=self.db._guild_row_locked(run['id'])
                    with patch.object(self.db,'_gear_loot_locked',side_effect=RuntimeError('test failure')):
                        self.db._guild_settle_locked(row,True,'win')
        self.assertEqual(self.db._guild_used_locked(10),2)
        self.assertEqual(balance_locked(self.db,10),before)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM guild_bag WHERE actor_id=10').fetchone()[0],0)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM guild_settlements WHERE run_id=?',(run['id'],)).fetchone()[0],0)

    def test_calendar_reset_is_midnight_moscow_not_utc(self):
        from arena_raid import raid_day
        before=datetime(2026,10,30,20,59,59,tzinfo=timezone.utc).timestamp()
        self.assertEqual(raid_day(before),'2026-10-30')
        self.assertEqual(raid_day(before+1),'2026-10-31')


def balance_locked(db,actor):
    return db.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=-100 AND user_id=?',(actor,)).fetchone()[0]
