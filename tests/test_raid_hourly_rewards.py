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
