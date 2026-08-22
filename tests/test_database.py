import asyncio
import tempfile
import unittest
from pathlib import Path

from database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.database.connect()
        await self.database.upsert_chat(1, "Тестовый чат")
        await self.database.upsert_user(1, 10, "owner", "Owner")
        await self.database.upsert_user(1, 20, "loser", "Loser")
        await self.database.upsert_user(1, 30, "slave", "Slave")

    async def asyncTearDown(self):
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_username_lookup_is_case_insensitive(self):
        row = await self.database.resolve_user(1, "@OwNeR")
        self.assertEqual(row["user_id"], 10)

    async def test_action_counts_and_history(self):
        await self.database.record_action(1, 20, "warn", "причина", 10)
        await self.database.record_action(1, 20, "warn", "ещё одна", 10)
        stats = await self.database.action_stats(1, 20)
        history = await self.database.action_history(1, 20)
        self.assertEqual(stats["warn"], 2)
        self.assertEqual(history[0]["reason"], "ещё одна")

    async def test_deactivate_mutes_and_clear_reputation(self):
        await self.database.record_action(
            1, 20, "mute", "причина", 10, duration_seconds=3600, active_until=4102444800
        )
        await self.database.record_action(1, 20, "warn", "пред", 10)
        await self.database.deactivate_mutes(1, 20)
        stats = await self.database.action_stats(1, 20)
        self.assertIsNone(stats["active_mute_until"])
        self.assertEqual(await self.database.clear_actions(1, 20), 2)
        cleared = await self.database.action_stats(1, 20)
        self.assertEqual((cleared["mute"], cleared["warn"], cleared["ban"]), (0, 0, 0))

    async def test_loser_is_enslaved_when_they_own_nobody(self):
        outcome, slave_id = await self.database.transfer_after_loss(1, 20, 10)
        slaves = await self.database.list_slaves(1, 10)
        self.assertEqual((outcome, slave_id), ("enslaved", 20))
        self.assertEqual([row["user_id"] for row in slaves], [20])

    async def test_loser_transfers_existing_slave(self):
        await self.database.transfer_after_loss(1, 30, 20)
        outcome, slave_id = await self.database.transfer_after_loss(1, 20, 10)
        slaves = await self.database.list_slaves(1, 10)
        self.assertEqual((outcome, slave_id), ("transferred", 30))
        self.assertEqual([row["user_id"] for row in slaves], [30])

    async def test_global_slave_list_contains_chat_title_and_username(self):
        await self.database.transfer_after_loss(1, 20, 10)
        rows = await self.database.list_slaves_globally(10)
        self.assertEqual(rows[0]["chat_title"], "Тестовый чат")
        self.assertEqual(rows[0]["username"], "loser")

    async def test_global_user_lookup(self):
        rows = await self.database.resolve_users_globally("@LOSER")
        self.assertEqual(rows[0]["user_id"], 20)
        self.assertEqual(rows[0]["chat_title"], "Тестовый чат")

    async def test_only_participants_can_choose(self):
        challenge_id = await self.database.create_challenge(1, 10, 20)
        self.assertIsNone(await self.database.choose(challenge_id, 999, "rock"))
        row = await self.database.choose(challenge_id, 10, "rock")
        self.assertEqual(row["challenger_choice"], "rock")

    async def test_leg_request_can_be_completed_before_deadline(self):
        request_id = await self.database.create_leg_request(1, 20, 10, 4102444800)
        self.assertEqual(len(await self.database.pending_leg_requests()), 1)
        self.assertEqual(await self.database.complete_leg_requests(1, 20), 1)
        self.assertIsNone(await self.database.claim_expired_leg_request(request_id))

    async def test_expired_leg_request_is_claimed_once(self):
        request_id = await self.database.create_leg_request(1, 20, 10, 0)
        claimed = await self.database.claim_expired_leg_request(request_id)
        self.assertEqual(claimed["target_id"], 20)
        self.assertIsNone(await self.database.claim_expired_leg_request(request_id))

    async def test_slave_cannot_receive_another_slave(self):
        await self.database.force_enslave(1, 20, 10)
        await self.database.force_enslave(1, 30, 10)
        result = await self.database.transfer_slave(1, 10, 30, 20)
        self.assertEqual(result, "recipient_is_slave")

    async def test_beating_owner_frees_slave(self):
        await self.database.force_enslave(1, 20, 10)
        outcome, affected = await self.database.transfer_after_loss(1, 10, 20)
        self.assertEqual((outcome, affected), ("freed", 20))
        self.assertIsNone(await self.database.get_owner(1, 20))

    async def test_slave_winner_cannot_own_unrelated_loser(self):
        await self.database.force_enslave(1, 20, 10)
        outcome, _ = await self.database.transfer_after_loss(1, 30, 20)
        self.assertEqual(outcome, "no_reward")
        self.assertEqual((await self.database.get_owner(1, 20))["owner_id"], 10)

    async def test_enslaving_an_owner_releases_their_slaves(self):
        await self.database.force_enslave(1, 30, 20)
        await self.database.force_enslave(1, 20, 10)
        self.assertEqual(await self.database.list_slaves(1, 20), [])
        self.assertIsNone(await self.database.get_owner(1, 30))

    async def test_forced_owner_challenge_is_monthly(self):
        await self.database.force_enslave(1, 20, 10)
        self.database.connection.execute(
            "UPDATE ownership SET acquired_at=0 WHERE chat_id=1 AND slave_id=20"
        )
        self.database.connection.commit()
        self.assertTrue(await self.database.can_force_owner(1, 20, 10))
        challenge_id = await self.database.create_challenge(1, 20, 10, forced=True)
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["forced"], 1)
        self.assertEqual(challenge["deadline"] - challenge["created_at"], 86400)
        self.assertFalse(await self.database.can_force_owner(1, 20, 10))

    async def test_expired_challenge_is_claimed_once(self):
        challenge_id = await self.database.create_challenge(1, 10, 20)
        self.database.connection.execute(
            "UPDATE challenges SET deadline=0 WHERE id=?", (challenge_id,)
        )
        self.database.connection.commit()
        claimed = await self.database.claim_expired_challenge(challenge_id)
        self.assertEqual(claimed["challenger_id"], 10)
        self.assertIsNone(await self.database.claim_expired_challenge(challenge_id))

    async def test_each_user_can_have_only_one_active_challenge(self):
        first = await self.database.create_challenge(1, 10, 20)
        self.assertIsNotNone(first)
        self.assertIsNone(await self.database.create_challenge(1, 10, 30))
        self.assertIsNone(await self.database.create_challenge(1, 30, 20))
        await self.database.finish_challenge(first)
        self.assertIsNotNone(await self.database.create_challenge(1, 10, 30))

    async def test_challenge_remembers_newcomer_status(self):
        challenge_id = await self.database.create_challenge(
            1, 10, 20, opponent_newcomer=True
        )
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["opponent_newcomer"], 1)


if __name__ == "__main__":
    unittest.main()
