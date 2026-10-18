"""Catch-up progression, adaptive raids and account-wide hourly settlement."""
import json
import random
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import test_arena
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, xp_for_next_level, stats_for
from arena_progression import pending_choice
from arena_raid import raid_day
from arena_raid_engine import create_raid_state, raid_boss_level
from arena_raid_web import raid_view
from arena_web import menu_view


def level_xp(level):
    return sum(xp_for_next_level(i) for i in range(1, level))


class NoLoot(random.Random):
    def random(self):
        return 1


class LootRoll(random.Random):
    def __init__(self, roll):
        super().__init__(0)
        self.roll=roll

    def random(self):
        return self.roll


class AdaptiveRaidTests(unittest.TestCase):
    def test_levels_and_actual_boss_growth_player_cap_unchanged(self):
        for levels, expected in (([18]*3,20),([19]*3,21),([20]*3,22),([1,1,20],21),([16,17,17],19),([1],3)):
            self.assertEqual(raid_boss_level(levels), expected)
            members=[dict(actor_id=i,fighter_id=i,personal=True,slave_owner=i) for i in range(len(levels))]
            sources=[dict(slave_id=i,owner_id=i,class_id='middle',level=level) for i,level in enumerate(levels)]
            for boss_id in ('lei_heng','doofenshmirtz'):
                data=create_raid_state(members,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,boss_id)
                self.assertEqual(data['boss']['level'],expected)
                self.assertEqual([p['fighter']['level'] for p in data['players'].values()],levels)
                self.assertEqual(data['boss']['raid_damage_multiplier'],1.15)
                hp=round(sum(p['fighter']['stats']['max_hp'] for p in data['players'].values())*1.4)
                if boss_id=='doofenshmirtz': hp=round(hp*1.05)
                self.assertEqual(data['boss']['hp'],round(hp*1.25))
        self.assertEqual(stats_for('middle',22),stats_for('middle',20))
        self.assertGreater(stats_for('middle',22,boss=True)['physical_attack'],stats_for('middle',20)['physical_attack'])

    def test_moscow_midnight_not_host_timezone(self):
        before=datetime(2026,10,14,20,59,59,tzinfo=timezone.utc).timestamp()
        self.assertEqual(raid_day(before),'2026-10-14')
        self.assertEqual(raid_day(before+1),'2026-10-15')


class DailyBalanceStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown=test_arena.ArenaStoreTests.asyncTearDown

    def profile(self,personal=True,chat=1,user=10):
        return dict(self.db._arena_profile_locked(chat,user,personal))

    def level(self,level,personal=True,chat=1,user=10):
        self.profile(personal,chat,user)
        chat = 0 if personal else chat
        table='personal_profiles' if personal else 'slave_profiles'
        self.db.connection.execute(f'UPDATE {table} SET level=?,xp=?,progression_level=? WHERE chat_id=? AND user_id=?',
            (level,level_xp(level),level,chat,user))
        self.db.connection.commit()

    async def raid(self,boss='lei_heng',chat=1,slave=False):
        p=self.profile(chat=chat)
        if pending_choice(p): await self.db.arena_edit_profile(chat,10,10,True,'progression','stay')
        row=await self.db.arena_raid_create(chat,10,boss)
        if slave:
            await self.db.arena_raid_setup(row['token'],10,'join',30,False)
        return await self.db.arena_raid_setup(row['token'],10,'start')

    def finish(self,row,won=True,manual=2,withdrawn=False,roll=0):
        data=json.loads(row['data_json'])
        data.update(won=won,finished=True,result='done')
        player=data['players']['10']
        player.update(manual_turns=manual,withdrawn=withdrawn)
        with patch('arena_raid.random.SystemRandom',return_value=LootRoll(roll)):
            self.db._raid_finish_locked(row,data)
        self.db.connection.commit()
        return data['rewards'].get('10')

    async def test_reset_level_choice_boost_nonstack_and_restart(self):
        self.level(18)
        await self.db.arena_set_sprite(1,10,b'test-sprite',False)
        self.db._add_francs_locked(1,10,50)
        self.db._arena_add_item_locked(1,10,'candy','experience','common',3)
        self.db.connection.commit()
        await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        p=self.profile()
        self.assertEqual((p['level'],p['xp'],pending_choice(p)),(5,level_xp(5),5))
        self.assertEqual(p['catchup_target_xp'],level_xp(18))
        await self.db.arena_edit_profile(1,10,10,True,'progression','stay')
        self.db._grant_profile_xp_locked('personal_profiles',1,10,30,battle=True)
        self.assertEqual(self.profile()['xp'],level_xp(5)+60)
        await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        await self.db.close(); await self.db.connect()
        self.db._grant_profile_xp_locked('personal_profiles',1,10,30,battle=True)
        self.assertEqual(self.profile()['xp'],level_xp(5)+60)
        self.assertEqual(self.profile()['catchup_target_xp'],level_xp(18))
        view=await menu_view(self.db,1,10)
        self.assertEqual(view['personal']['catchup_level'],18)
        self.assertTrue(view['personal']['sprite_url'])
        self.assertEqual(view['balance'],50)
        self.assertEqual(view['inventory'][0]['quantity'],3)

    async def test_boost_stops_at_old_level_overflow_normal_and_candy_unboosted(self):
        self.level(10)
        await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        await self.db.arena_edit_profile(1,10,10,True,'progression','stay')
        before=self.profile()['xp']
        self.db._arena_add_item_locked(1,10,'candy','experience','common')
        item=self.db.connection.execute('SELECT id FROM arena_inventory').fetchone()['id']
        self.db.connection.commit()
        await self.db.arena_use_item(1,10,item,10)
        self.assertEqual(self.profile()['xp'],before+30)
        self.db.connection.execute('UPDATE personal_profiles SET xp=?,level=9 WHERE chat_id=0 AND user_id=10',(level_xp(10)-9,))
        self.db._grant_profile_xp_locked('personal_profiles',1,10,20,battle=True)
        self.assertEqual(self.profile()['xp'],level_xp(10)+15)
        self.assertEqual(self.profile()['catchup_target_xp'],0)
        self.db._grant_profile_xp_locked('personal_profiles',1,10,20,battle=True)
        self.assertEqual(self.profile()['xp'],level_xp(10)+35)

    async def test_no_low_level_xp_creation_and_class_scroll_resets_to_five(self):
        with self.assertRaisesRegex(ValueError,'5 уровня'):
            await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        self.assertEqual(self.profile()['xp'],0)
        self.level(12)
        self.db._arena_add_item_locked(1,10,'class','nerd','uncommon')
        item=self.db.connection.execute('SELECT id FROM arena_inventory').fetchone()['id']
        self.db.connection.commit()
        await self.db.arena_use_item(1,10,item,10,confirm=True)
        p=self.profile()
        self.assertEqual((p['level'],p['xp'],p['class_id']),(5,level_xp(5),'nerd'))
        self.assertEqual(p['catchup_target_xp'],level_xp(12))

    async def test_hourly_global_across_chat_and_fighter_distinct_boss_restart(self):
        now = int(time.time())
        with patch('arena_raid.raid_reward_now',return_value=now):
            first=self.finish(await self.raid())
            self.assertTrue(first['full_reward'])
            self.assertEqual((first['francs'],first['xp']),(49,22))
            await self.db.close(); await self.db.connect()
            second=self.finish(await self.raid())
            self.assertFalse(second['full_reward'])
            self.assertFalse(second['pet_rewards'])
            await self.db.upsert_chat(2,'Другой чат')
            await self.db.upsert_user(2,10,'10','User10')
            self.assertFalse(self.finish(await self.raid(chat=2))['full_reward'])
            self.assertTrue(self.finish(await self.raid('doofenshmirtz',chat=2))['full_reward'])
            status=await self.db.arena_raid_reward_status(10)
            self.assertFalse(status['lei_heng']['full_reward'])
        with patch('arena_raid.raid_reward_now',return_value=now + 3600):
            self.assertTrue(self.finish(await self.raid(chat=2))['full_reward'])

    async def test_failed_rolls_retry_immediately_and_fifth_is_guaranteed(self):
        now = int(time.time())
        for attempt in range(1,6):
            with patch('arena_raid.raid_reward_now',return_value=now):
                reward=self.finish(await self.raid(),roll=1)
                self.assertTrue(reward['full_reward'])
                self.assertEqual(bool(reward['loot']),attempt==5)
                expected=attempt if attempt<5 else 0
                if attempt==5:
                    repeat=self.finish(await self.raid())
                    self.assertFalse(repeat['loot'])
                    self.assertFalse(repeat['full_reward'])
                else:
                    self.assertTrue((await self.db.arena_raid_reward_status(10))['lei_heng']['full_reward'])
                misses=self.db.connection.execute('SELECT misses FROM arena_raid_global_pity WHERE actor_id=10 AND boss_id="lei_heng"').fetchone()[0]
                self.assertEqual(misses,expected)

    async def test_boss_level_rewards_uncapped_and_raid_xp_boosted(self):
        self.level(18)
        row=await self.raid()
        data=json.loads(row['data_json'])
        data['boss']['level']=22
        row['data_json']=json.dumps(data)
        reward=self.finish(row)
        self.assertEqual((reward['francs'],reward['xp']),(106,98))
        await self.db.arena_edit_profile(1,10,10,True,'reset_class',True)
        await self.db.arena_edit_profile(1,10,10,True,'progression','stay')
        with patch('arena_raid.raid_reward_now',return_value=int(time.time()) + 3600):
            reward=self.finish(await self.raid())
        self.assertEqual(reward['xp'],2*(10+4*7))


    async def test_defeat_inactive_withdrawal_do_not_spend_daily_reward(self):
        for options in (dict(won=False),dict(manual=1),dict(withdrawn=True)):
            self.assertIsNone(self.finish(await self.raid(),**options))
            self.assertTrue((await self.db.arena_raid_reward_status(10))['lei_heng']['full_reward'])
        row=await self.raid()
        self.assertTrue(self.finish(row)['full_reward'])
        with self.assertRaisesRegex(ValueError,'закрыт'): self.finish(row)

    async def test_grant_failure_rolls_back_claim_and_all_payouts(self):
        row=await self.raid()
        before=self.profile()['xp']
        with patch.object(self.db,'_add_francs_locked',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError): self.finish(row)
            self.db.connection.rollback()
        self.assertEqual(self.profile()['xp'],before)
        self.assertTrue((await self.db.arena_raid_reward_status(10))['lei_heng']['full_reward'])
        self.assertTrue(self.finish(row)['full_reward'])

    async def test_retired_boss_new_calls_rejected_saved_battle_unchanged(self):
        with self.assertRaises(ValueError): await self.db.arena_raid_create(1,10,'iron')
        row=await self.raid()
        view=await raid_view(self.db,row,10)
        self.assertAlmostEqual(view['data']['boss']['damage_bonus'],.15)
        saved=json.loads(row['data_json'])
        saved['boss']['level']=20
        saved['boss'].pop('raid_damage_multiplier',None)
        self.db.connection.execute('UPDATE arena_raids SET boss_id="iron",data_json=? WHERE token=?',(json.dumps(saved),row['token']))
        self.db.connection.commit()
        await self.db.close(); await self.db.connect()
        row=await self.db.arena_raid_get(row['token'])
        self.assertEqual(json.loads(row['data_json'])['boss'],saved['boss'])
        self.assertTrue(self.finish(row)['full_reward'])
        self.assertNotIn('iron',[b['id'] for b in (await menu_view(self.db,1,10))['raid_bosses']])

    async def test_upgrade_backfills_paid_rewards_and_global_pity_once(self):
        row=await self.raid()
        self.finish(row)
        self.db.connection.execute('DELETE FROM arena_raid_daily_claims')
        self.db.connection.execute('DELETE FROM arena_raid_reward_cooldowns')
        self.db.connection.execute('DELETE FROM arena_raid_global_pity')
        self.db.connection.execute("DELETE FROM arena_raid_migrations WHERE name='daily_rewards_v1'")
        self.db.connection.execute("DELETE FROM arena_raid_migrations WHERE name='hourly_rewards_v1'")
        self.db.connection.execute("INSERT INTO arena_raid_loot_pity VALUES(1,10,'lei_heng',2)")
        self.db.connection.execute("INSERT INTO arena_raid_loot_pity VALUES(2,10,'lei_heng',4)")
        self.db.connection.commit()
        self.db._connect_raids()
        self.assertFalse((await self.db.arena_raid_reward_status(10))['lei_heng']['full_reward'])
        self.assertEqual(self.db.connection.execute('SELECT misses FROM arena_raid_global_pity').fetchone()[0],4)
        self.db.connection.execute('UPDATE arena_raid_global_pity SET misses=0')
        self.db.connection.commit()
        self.db._connect_raids()
        self.assertEqual(self.db.connection.execute('SELECT misses FROM arena_raid_global_pity').fetchone()[0],0)
