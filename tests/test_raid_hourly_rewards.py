"""A rolling hour per account/boss, not a calendar reset or sliding repeats."""
import time
import unittest
from datetime import datetime
from unittest.mock import patch
import test_arena_daily_balance as daily
import test_character_slots as slots
from arena_raid import MSK, RAID_REWARD_COOLDOWN


class HourlyRewardTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = daily.DailyBalanceStoreTests.asyncTearDown
    profile = daily.DailyBalanceStoreTests.profile
    raid = daily.DailyBalanceStoreTests.raid
    unlock = slots.SlotTests.unlock
    select = slots.SlotTests.select

    async def asyncSetUp(self):
        await daily.DailyBalanceStoreTests.asyncSetUp(self)
        self.now = int(time.time())
        self.clock = patch('arena_raid.raid_reward_now', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def finish(self, row, **options):
        reward = daily.DailyBalanceStoreTests.finish(self, row, **options)
        self.db.connection.execute('UPDATE arena_raids SET finished_at=? WHERE token=?', (self.now, row['token']))
        self.db.connection.commit()
        return reward

    async def status(self, boss='lei_heng'):
        return (await self.db.arena_raid_reward_status(10))[boss]

    async def test_exact_hour_boundary_and_repeats_do_not_extend_cooldown(self):
        self.assertTrue((await self.status())['full_reward'])
        first = self.finish(await self.raid())
        deadline = self.now + RAID_REWARD_COOLDOWN
        self.assertTrue(first['full_reward'])
        self.assertEqual(first['reward_available_at'], deadline)
        self.now += 3599
        status = await self.status()
        self.assertEqual((status['full_reward'], status['cooldown_remaining']), (False, 1))
        repeat = self.finish(await self.raid())
        self.assertFalse(repeat['full_reward'])
        self.assertEqual(repeat['reward_available_at'], deadline)
        self.assertFalse(repeat['loot'])
        self.assertFalse(repeat['pet_rewards'])
        self.now += 1
        self.assertTrue((await self.status())['full_reward'])
        reward = self.finish(await self.raid())
        self.assertTrue(reward['full_reward'])
        self.assertEqual((await self.status())['cooldown_remaining'], 3600)

    async def test_midnight_does_not_reset_a_recent_claim(self):
        self.now = int(datetime(2026, 10, 14, 23, 59, 30, tzinfo=MSK).timestamp())
        self.finish(await self.raid())
        self.now += 60
        status = await self.status()
        self.assertEqual((status['full_reward'], status['cooldown_remaining']), (False, 3540))

    async def test_cooldown_shared_with_other_chat_slot_restart_but_not_other_boss(self):
        first = self.finish(await self.raid())
        await self.db.upsert_chat(2, 'Other chat')
        await self.db.upsert_user(2, 10, '10', 'Player')
        await self.unlock()
        await self.select(2, chat=2)
        await self.db.close()
        await self.db.connect()
        repeat = self.finish(await self.raid(chat=2))
        self.assertFalse(repeat['full_reward'])
        self.assertEqual(first['reward_available_at'], repeat['reward_available_at'])
        self.assertTrue((await self.status('doofenshmirtz'))['full_reward'])
        self.assertTrue(self.finish(await self.raid('doofenshmirtz', chat=2))['full_reward'])

    async def test_loss_inactivity_and_withdrawal_do_not_claim_or_extend(self):
        for options in (dict(won=False), dict(manual=1), dict(withdrawn=True)):
            self.assertIsNone(self.finish(await self.raid(), **options))
            self.assertTrue((await self.status())['full_reward'])
        first = self.finish(await self.raid())
        self.now += 300
        self.finish(await self.raid(), won=False)
        self.assertEqual((await self.status())['resets_at'], first['reward_available_at'])

    async def test_failed_payout_rolls_back_the_claim(self):
        row = await self.raid()
        with patch.object(self.db, '_add_francs_locked', side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):
                self.finish(row)
            self.db.connection.rollback()
        self.assertTrue((await self.status())['full_reward'])
        self.assertTrue(self.finish(row)['full_reward'])

    def remigrate(self):
        self.db.connection.execute('DELETE FROM arena_raid_reward_cooldowns')
        self.db.connection.execute("DELETE FROM arena_raid_migrations WHERE name='hourly_rewards_v1'")
        self.db.connection.commit()
        self.db._connect_raids()

    async def test_migration_keeps_last_full_claim_not_later_repeat_and_runs_once(self):
        self.now -= 1800
        full = self.finish(await self.raid())
        self.now += 1770
        repeat = self.finish(await self.raid())
        self.assertFalse(repeat['full_reward'])
        self.now += 30
        self.remigrate()
        status = await self.status()
        self.assertEqual((status['resets_at'], status['cooldown_remaining']), (full['reward_available_at'], 1800))
        self.now += 1800
        await self.db.close()
        await self.db.connect()
        self.assertTrue((await self.status())['full_reward'])

    async def test_migration_old_full_rewards_and_daily_claims_do_not_block(self):
        self.now -= 7200
        self.finish(await self.raid())
        self.now += 7200
        self.remigrate()
        self.assertTrue((await self.status())['full_reward'])

    async def test_reward_available_at_is_part_of_saved_result(self):
        row = await self.raid()
        reward = self.finish(row)
        import json
        saved = json.loads((await self.db.arena_raid_get(row['token']))['data_json'])
        self.assertEqual(saved['rewards']['10']['reward_available_at'], reward['reward_available_at'])

    async def test_seventy_percent_boundary_for_every_available_boss(self):
        for boss in ('lei_heng','doofenshmirtz','kit'):
            for roll,dropped in ((.699999,True),(.7,False)):
                with self.subTest(boss=boss,roll=roll):
                    self.now+=3600
                    reward=self.finish(await self.raid(boss),roll=roll)
                    self.assertEqual(bool(reward['loot']),dropped)
                    self.assertTrue(reward['full_reward'])
                    status=await self.status(boss)
                    self.assertEqual(status['full_reward'],not dropped)
                    self.assertEqual(status['cooldown_remaining'],3600 if dropped else 0)
                    self.assertEqual(reward['reward_available_at'],self.now+3600 if dropped else 0)

    async def test_no_drop_keeps_full_cash_xp_and_immediate_retry_after_restart(self):
        first=self.finish(await self.raid(),roll=1)
        self.assertFalse(first['loot'])
        self.assertEqual(first['reward_available_at'],0)
        self.assertTrue((await self.status())['full_reward'])
        await self.db.close();await self.db.connect()
        import json
        retry_row=await self.raid()
        level=json.loads(retry_row['data_json'])['boss']['level']
        retry=self.finish(retry_row,roll=1)
        self.assertEqual((retry['francs'],retry['xp']),(40+3*level,10+4*level))
        self.assertTrue(retry['full_reward'])
        self.assertTrue((await self.status())['full_reward'])
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM arena_raid_reward_cooldowns WHERE actor_id=10').fetchone())
        dropped=self.finish(await self.raid())
        self.assertTrue(dropped['loot'])
        self.assertEqual((await self.status())['cooldown_remaining'],3600)
        repeat_row=await self.raid()
        level=json.loads(repeat_row['data_json'])['boss']['level']
        repeat=self.finish(repeat_row,roll=0)
        self.assertFalse(repeat['full_reward'])
        self.assertFalse(repeat['loot'])
        self.assertEqual(repeat['francs'],(40+3*level)//5)

    async def test_no_drop_attempts_share_pity_across_chats_slots_and_restart(self):
        self.finish(await self.raid(),roll=1)
        await self.db.upsert_chat(2,'Other chat')
        await self.db.upsert_user(2,10,'10','Player')
        await self.unlock();await self.select(2,chat=2)
        await self.db.close();await self.db.connect()
        self.assertTrue((await self.status())['full_reward'])
        reward=self.finish(await self.raid(chat=2),roll=1)
        self.assertTrue(reward['full_reward'])
        self.assertEqual(self.db.connection.execute('SELECT misses FROM arena_raid_global_pity WHERE actor_id=10 AND boss_id="lei_heng"').fetchone()[0],2)

    async def test_no_drop_saved_result_cannot_be_paid_twice(self):
        row=await self.raid();reward=self.finish(row,roll=1)
        before=self.db.connection.execute('SELECT SUM(quantity) FROM arena_inventory').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'закрыт'):
            self.finish(row,roll=0)
        self.assertEqual(before,self.db.connection.execute('SELECT SUM(quantity) FROM arena_inventory').fetchone()[0])
        self.assertEqual(reward['reward_available_at'],0)

    async def test_failed_item_grant_rolls_back_claim_pity_and_cash(self):
        row=await self.raid()
        before=self.profile()['xp']
        balance=await self.db.franc_balance(1,10)
        with patch.object(self.db,'_arena_add_item_locked',side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):self.finish(row)
            self.db.connection.rollback()
        self.assertEqual(self.profile()['xp'],before)
        self.assertEqual(await self.db.franc_balance(1,10),balance)
        self.assertTrue((await self.status())['full_reward'])
        self.assertIsNone(self.db.connection.execute('SELECT misses FROM arena_raid_global_pity WHERE actor_id=10 AND boss_id="lei_heng"').fetchone())
        self.assertTrue(self.finish(row)['loot'])

    async def test_upgrade_clears_only_known_failed_loot_claims_once(self):
        miss_row=await self.raid()
        self.finish(miss_row,roll=1)
        hit=self.finish(await self.raid('doofenshmirtz'))
        self.db.connection.execute('INSERT INTO arena_raid_reward_cooldowns VALUES(?,?,?,?)',(10,'lei_heng',self.now,miss_row['token']))
        self.db.connection.execute("DELETE FROM arena_raid_migrations WHERE name='loot_reward_cooldowns_v1'")
        self.db.connection.commit()
        self.db._connect_raids()
        self.assertTrue((await self.status())['full_reward'])
        self.assertEqual((await self.status('doofenshmirtz'))['resets_at'],hit['reward_available_at'])
        self.db.connection.execute('INSERT INTO arena_raid_reward_cooldowns VALUES(?,?,?,?)',(10,'lei_heng',self.now,'unknown-history'))
        self.db.connection.commit()
        self.db._connect_raids()
        self.assertFalse((await self.status())['full_reward'])  # Migration is one-time.
