import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from database import (
    BUSINESS_STATS_TZ,
    CHALLENGE_DEADLINE_SECONDS,
    FORCE_OWNER_COOLDOWN_SECONDS,
    Database,
    utc_timestamp,
)


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

    async def test_priority_slave_is_transferred_last_and_priority_resets(self):
        await self.database.upsert_user(1, 40, "winner", "Winner")
        await self.database.force_enslave(1, 20, 10)
        await self.database.force_enslave(1, 30, 10)
        self.assertEqual(
            await self.database.set_slave_priority(1, 10, 20, True), "updated"
        )
        first_outcome, first_slave = await self.database.transfer_after_loss(1, 10, 40)
        self.assertEqual((first_outcome, first_slave), ("transferred", 30))
        self.assertEqual((await self.database.get_owner(1, 20))["transfer_priority"], 1)
        second_outcome, second_slave = await self.database.transfer_after_loss(1, 10, 40)
        self.assertEqual((second_outcome, second_slave), ("transferred", 20))
        self.assertEqual((await self.database.get_owner(1, 20))["transfer_priority"], 0)

    async def test_global_slave_list_contains_chat_title_and_username(self):
        await self.database.transfer_after_loss(1, 20, 10)
        rows = await self.database.list_slaves_globally(10)
        self.assertEqual(rows[0]["chat_title"], "Тестовый чат")
        self.assertEqual(rows[0]["username"], "loser")

    async def test_profile_queries_return_ownership_and_game_statistics(self):
        await self.database.force_enslave(1, 20, 10)
        owners = await self.database.list_owners_globally(20)
        self.assertEqual(owners[0]["owner_id"], 10)

        await self.database.create_challenge(1, 10, 20, game_type="rps")
        stats = await self.database.game_stats_for_user(10)
        self.assertEqual((stats["total"], stats["active"], stats["rps"]), (1, 1, 1))

    async def test_global_user_lookup(self):
        rows = await self.database.resolve_users_globally("@LOSER")
        self.assertEqual(rows[0]["user_id"], 20)
        self.assertEqual(rows[0]["chat_title"], "Тестовый чат")

    async def test_only_participants_can_choose(self):
        challenge_id = await self.database.create_challenge(1, 10, 20)
        self.assertIsNone(await self.database.choose(challenge_id, 999, "rock"))
        row = await self.database.choose(challenge_id, 10, "rock")
        self.assertEqual(row["challenger_choice"], "rock")

    async def test_blackjack_challenge_is_persistent_and_finishes(self):
        challenge_id = await self.database.create_challenge(
            1, 10, 20, game_type="blackjack"
        )
        challenge = await self.database.get_challenge(challenge_id)
        game = await self.database.get_blackjack_game(challenge_id)
        self.assertEqual(challenge["game_type"], "blackjack")
        self.assertEqual(len(json.loads(game["deck"])), 48)

        self.database.connection.execute(
            """UPDATE blackjack_games SET
                   challenger_hand=?, opponent_hand=?, turn_user_id=10
               WHERE challenge_id=?""",
            (json.dumps(["K♠", "Q♥"]), json.dumps(["10♣", "8♦"]), challenge_id),
        )
        self.database.connection.commit()
        first = await self.database.blackjack_action(challenge_id, 10, "stand")
        self.assertEqual(first["status"], "updated")
        result = await self.database.blackjack_action(challenge_id, 20, "stand")
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["winner_id"], 10)
        self.assertEqual((await self.database.get_challenge(challenge_id))["status"], "finished")
        stats = await self.database.game_stats_for_user(10)
        self.assertEqual((stats["wins"], stats["losses"], stats["draws"]), (1, 0, 0))

    async def test_recorded_resignation_counts_as_a_loss_and_win(self):
        challenge_id = await self.database.create_challenge(1, 10, 20)
        self.assertTrue(await self.database.finish_challenge(challenge_id))
        await self.database.record_challenge_result(challenge_id, 20)
        challenger_stats = await self.database.game_stats_for_user(10)
        opponent_stats = await self.database.game_stats_for_user(20)
        self.assertEqual((challenger_stats["wins"], challenger_stats["losses"]), (0, 1))
        self.assertEqual((opponent_stats["wins"], opponent_stats["losses"]), (1, 0))

    async def test_friendly_game_cannot_be_forced_or_target_newcomers(self):
        challenge_id = await self.database.create_challenge(
            1,
            10,
            20,
            forced=True,
            opponent_newcomer=True,
            game_type="blackjack",
            friendly=True,
        )
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["friendly"], 1)
        self.assertEqual(challenge["forced"], 0)
        self.assertEqual(challenge["opponent_newcomer"], 0)
        self.assertEqual(
            challenge["deadline"] - challenge["created_at"],
            CHALLENGE_DEADLINE_SECONDS,
        )

    async def test_checkers_challenge_is_persistent_and_moves(self):
        challenge_id = await self.database.create_challenge(
            1, 10, 20, opponent_newcomer=True, game_type="checkers"
        )
        challenge = await self.database.get_challenge(challenge_id)
        game = await self.database.get_checkers_game(challenge_id)
        board = json.loads(game["board"])
        self.assertEqual(challenge["game_type"], "checkers")
        self.assertEqual(board.count("b"), 12)
        self.assertEqual(board.count("w"), 12)
        self.assertEqual(game["turn_user_id"], 20)

        selected = await self.database.checkers_click(challenge_id, 20, 40)
        self.assertEqual(selected["status"], "selected")
        moved = await self.database.checkers_click(challenge_id, 20, 33)
        self.assertEqual(moved["status"], "moved")
        self.assertEqual(moved["turn_user_id"], 10)
        extended = await self.database.get_challenge(challenge_id)
        self.assertGreater(extended["deadline"] - extended["created_at"], 300)
        persisted = await self.database.get_checkers_game(challenge_id)
        self.assertEqual(persisted["move_count"], 1)
        self.assertTrue(persisted["opponent_acted"])

    async def test_challenge_can_store_inline_message_id(self):
        challenge_id = await self.database.create_challenge(1, 10, 20)
        await self.database.set_challenge_inline_message(challenge_id, "inline-123")
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["inline_message_id"], "inline-123")

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

    async def test_captcha_tracks_attempts_and_can_be_completed(self):
        captcha_id = await self.database.create_captcha(1, 20, "🐸", 4102444800)
        await self.database.set_captcha_join_message(captcha_id, 123)
        self.assertEqual((await self.database.get_captcha(captcha_id))["join_message_id"], 123)
        self.assertEqual(len(await self.database.pending_captchas()), 1)
        self.assertEqual(
            await self.database.submit_captcha(captcha_id, 20, "🍉", 3),
            ("retry", 2),
        )
        self.assertEqual(
            await self.database.submit_captcha(captcha_id, 20, "🐸", 3),
            ("passed", 2),
        )
        self.assertEqual((await self.database.get_captcha(captcha_id))["status"], "passed")

    async def test_expired_captcha_is_claimed_once(self):
        captcha_id = await self.database.create_captcha(1, 20, "🐸", 0)
        claimed = await self.database.claim_expired_captcha(captcha_id)
        self.assertEqual(claimed["user_id"], 20)
        self.assertIsNone(await self.database.claim_expired_captcha(captcha_id))

    async def test_death_note_can_be_cancelled_by_target_or_timer_message(self):
        entry_id = await self.database.create_death_note_entry(1, 20, 10, 4102444800)
        self.assertEqual(len(await self.database.pending_death_note_entries()), 1)
        self.assertIsNone(await self.database.create_death_note_entry(1, 20, 10, 4102444800))
        await self.database.set_death_note_message(entry_id, 123)
        cancelled = await self.database.cancel_death_note_by_message(1, 123)
        self.assertEqual(cancelled["target_id"], 20)
        self.assertIsNone(await self.database.cancel_death_note_by_target(1, 20))

    async def test_expired_death_note_is_claimed_once(self):
        entry_id = await self.database.create_death_note_entry(1, 20, 10, 0)
        claimed = await self.database.claim_expired_death_note_entry(entry_id)
        self.assertEqual(claimed["author_id"], 10)
        self.assertIsNone(await self.database.claim_expired_death_note_entry(entry_id))

    async def test_random_phrases_do_not_repeat_before_bag_is_empty(self):
        phrases = ("первая", "вторая", "третья")
        picked = [
            await self.database.take_random_phrase(1, phrases) for _ in phrases
        ]
        self.assertEqual(set(picked), set(phrases))
        self.assertIn(await self.database.take_random_phrase(1, phrases), phrases)

    async def test_random_message_schedule_is_persistent_and_claimed_once(self):
        initial = await self.database.get_or_create_random_message_schedule(
            1, "2026-09-16", [100, 200]
        )
        repeated = await self.database.get_or_create_random_message_schedule(
            1, "2026-09-16", [300]
        )
        self.assertEqual([row["scheduled_at"] for row in repeated], [100, 200])
        await self.database.skip_expired_random_messages(1, "2026-09-16", 150)
        pending = await self.database.next_pending_random_message(1, "2026-09-16")
        self.assertEqual(pending["scheduled_at"], 200)
        claimed = await self.database.claim_random_message(int(pending["id"]))
        self.assertEqual(claimed["id"], pending["id"])
        self.assertIsNone(await self.database.claim_random_message(int(pending["id"])))

    async def test_slave_cannot_receive_another_slave(self):
        await self.database.force_enslave(1, 20, 10)
        await self.database.force_enslave(1, 30, 10)
        result = await self.database.transfer_slave(1, 10, 30, 20)
        self.assertEqual(result, "recipient_is_slave")

    async def test_cannot_transfer_someone_elses_slave_to_yourself(self):
        await self.database.force_enslave(1, 30, 20)
        result = await self.database.transfer_slave(1, 10, 30, 10)
        self.assertEqual(result, "not_owned")

    async def test_pirojok_cannot_receive_slaves(self):
        await self.database.upsert_user(
            1, 40, "pirojoksostajem", "Пирожок с остаже́м"
        )
        outcome, _ = await self.database.transfer_after_loss(1, 20, 40)
        self.assertEqual(outcome, "pirojok_cannot_own")
        self.assertIsNone(await self.database.get_owner(1, 20))
        self.assertEqual(
            await self.database.force_enslave(1, 20, 40),
            "pirojok_cannot_own",
        )
        await self.database.force_enslave(1, 30, 10)
        self.assertEqual(
            await self.database.transfer_slave(1, 10, 30, 40),
            "pirojok_cannot_own",
        )

    async def test_jug_hiding_has_five_minute_state_and_one_hour_cooldown(self):
        hidden_until = await self.database.start_jug_hiding(1, 20)
        self.assertIsNotNone(hidden_until)
        self.assertTrue(await self.database.is_jug_hidden(1, 20))
        self.assertIsNone(await self.database.start_jug_hiding(1, 20))
        pending = await self.database.pending_jug_hidings()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["cooldown_until"] - pending[0]["hidden_until"], 3600)

        self.database.connection.execute(
            "UPDATE jug_hiding SET hidden_until=0 WHERE chat_id=1 AND user_id=20"
        )
        self.database.connection.commit()
        self.assertTrue(await self.database.finish_jug_hiding(1, 20))
        self.assertFalse(await self.database.is_jug_hidden(1, 20))
        self.assertIsNone(await self.database.start_jug_hiding(1, 20))

        self.database.connection.execute(
            "UPDATE jug_hiding SET cooldown_until=0 WHERE chat_id=1 AND user_id=20"
        )
        self.database.connection.commit()
        self.assertIsNotNone(await self.database.start_jug_hiding(1, 20))

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

    async def test_forced_owner_challenge_is_weekly(self):
        await self.database.force_enslave(1, 20, 10)
        self.assertFalse(await self.database.can_force_owner(1, 20, 10))
        now = utc_timestamp()
        self.database.connection.execute(
            "UPDATE ownership SET acquired_at=? WHERE chat_id=1 AND slave_id=20",
            (now - FORCE_OWNER_COOLDOWN_SECONDS,),
        )
        self.database.connection.commit()
        self.assertTrue(await self.database.can_force_owner(1, 20, 10))
        challenge_id = await self.database.create_challenge(1, 20, 10, forced=True)
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["forced"], 1)
        self.assertEqual(challenge["deadline"] - challenge["created_at"], 10800)
        self.assertFalse(await self.database.can_force_owner(1, 20, 10))
        self.database.connection.execute(
            "UPDATE ownership SET last_forced_at=? WHERE chat_id=1 AND slave_id=20",
            (now - FORCE_OWNER_COOLDOWN_SECONDS,),
        )
        self.database.connection.commit()
        self.assertTrue(await self.database.can_force_owner(1, 20, 10))

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

    async def test_pending_challenge_requires_the_invited_opponent_to_accept(self):
        challenge_id = await self.database.create_challenge(
            1, 10, 20, awaiting_acceptance=True, opponent_newcomer=True
        )
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["status"], "pending")
        self.assertEqual(challenge["deadline"] - challenge["created_at"], 300)
        self.assertIsNone(await self.database.create_challenge(1, 10, 30))
        self.assertIsNone(await self.database.accept_challenge(challenge_id, 10))

        accepted = await self.database.accept_challenge(challenge_id, 20)
        self.assertEqual(accepted["status"], "active")
        self.assertGreaterEqual(
            accepted["deadline"] - accepted["created_at"],
            CHALLENGE_DEADLINE_SECONDS,
        )

    async def test_challenge_creator_can_cancel_an_unaccepted_offer(self):
        challenge_id = await self.database.create_challenge(
            1, 10, 20, awaiting_acceptance=True
        )
        self.assertFalse(await self.database.cancel_challenge_offer(challenge_id, 20))
        self.assertTrue(await self.database.cancel_challenge_offer(challenge_id, 10))
        self.assertEqual(
            (await self.database.get_challenge(challenge_id))["status"], "cancelled"
        )
        self.assertFalse(await self.database.cancel_challenge_offer(challenge_id, 10))

    async def test_challenge_remembers_newcomer_status(self):
        challenge_id = await self.database.create_challenge(
            1, 10, 20, opponent_newcomer=True
        )
        challenge = await self.database.get_challenge(challenge_id)
        self.assertEqual(challenge["opponent_newcomer"], 1)
        self.assertEqual(challenge["deadline"] - challenge["created_at"], 300)

    async def test_old_active_challenge_deadline_is_shortened_on_restart(self):
        challenge_id = await self.database.create_challenge(1, 10, 20)
        challenge = await self.database.get_challenge(challenge_id)
        self.database.connection.execute(
            "UPDATE challenges SET deadline=? WHERE id=?",
            (int(challenge["created_at"]) + 86400, challenge_id),
        )
        self.database.connection.commit()

        await self.database.close()
        await self.database.connect()

        migrated = await self.database.get_challenge(challenge_id)
        self.assertEqual(migrated["deadline"] - migrated["created_at"], 10800)

    async def test_counter_increments_persistently(self):
        self.assertEqual(await self.database.increment_counter(1, "stolen_art"), 1)
        self.assertEqual(await self.database.increment_counter(1, "stolen_art", 3), 4)
        self.assertEqual(await self.database.increment_counter(2, "stolen_art"), 1)

    async def test_basement_membership_is_separate_and_removable(self):
        self.assertTrue(await self.database.add_basement_member(1, 20, 10))
        self.assertFalse(await self.database.add_basement_member(1, 20, 10))
        self.assertTrue(await self.database.is_basement_member(1, 20))
        members = await self.database.list_basement_members(1)
        self.assertEqual(members[0]["username"], "loser")
        self.assertEqual(members[0]["rank"], 1)
        self.assertEqual(await self.database.change_basement_rank(1, 20, 1), (1, 2))
        self.assertEqual(await self.database.change_basement_rank(1, 20, 5), (2, 4))
        self.assertEqual(await self.database.change_basement_rank(1, 20, -10), (4, 1))
        self.assertTrue(await self.database.remove_basement_member(1, 20))
        self.assertFalse(await self.database.is_basement_member(1, 20))

    async def test_business_income_shifts_transfers_and_buyout(self):
        self.assertEqual(await self.database.create_business(1, 10, "brothel"), "no_slaves")
        self.assertEqual(await self.database.force_enslave(1, 20, 10), "enslaved")
        self.assertEqual(await self.database.create_business(1, 10, "brothel"), "created")
        self.assertEqual(
            await self.database.set_business_worker_role(1, 10, 20, "courtesan"),
            "updated",
        )
        self.database.connection.execute(
            "UPDATE businesses SET last_accrued=last_accrued-21600 WHERE chat_id=1 AND owner_id=10"
        )
        self.database.connection.commit()
        settled = await self.database.settle_business(1, 10)
        self.assertEqual(settled["owner_income"], 24)
        self.assertEqual(await self.database.franc_balance(1, 10), 24)
        self.assertEqual(await self.database.franc_balance(1, 20), 1)

        result, worker_pay, owner_pay, _ = await self.database.work_at_business(1, 10, 30)
        self.assertEqual((result, worker_pay, owner_pay), ("worked", 2, 1))
        result, *_ = await self.database.work_at_business(1, 10, 30)
        self.assertEqual(result, "cooldown")
        self.assertEqual(await self.database.transfer_francs(1, 10, 30, 3), "transferred")
        self.assertEqual(await self.database.franc_balance(1, 30), 5)

        self.database.connection.execute(
            "UPDATE users SET last_seen=? WHERE chat_id=1 AND user_id=20",
            (utc_timestamp() - 2 * 24 * 60 * 60,),
        )
        self.database.connection.execute(
            "UPDATE businesses SET last_accrued=last_accrued-21600 WHERE chat_id=1 AND owner_id=10"
        )
        self.database.connection.commit()
        settled = await self.database.settle_business(1, 10)
        self.assertEqual(settled["owner_income"], 6)
        self.assertEqual(await self.database.franc_balance(1, 20), 1)

        await self.database.upsert_user(1, 20, "loser", "Loser")
        self.database.connection.execute(
            """UPDATE slave_labor_earnings SET window_started=?, earned=99
               WHERE chat_id=1 AND user_id=20""",
            (utc_timestamp(),),
        )
        self.database.connection.commit()
        result, worker_pay, _, _ = await self.database.work_at_business(1, 10, 20)
        self.assertEqual((result, worker_pay), ("worked", 1))

        self.database.connection.execute(
            "UPDATE franc_balances SET balance=100 WHERE chat_id=1 AND user_id=20"
        )
        self.database.connection.commit()
        self.assertEqual(await self.database.buyout_slave(1, 10, 20), "released")
        self.assertIsNone(await self.database.get_owner(1, 20))

    async def test_business_income_periods_and_chat_listing(self):
        await self.database.force_enslave(1, 20, 10)
        self.assertEqual(await self.database.create_business(1, 10, "field"), "created")
        today = datetime.now(BUSINESS_STATS_TZ).date()
        yesterday = today - timedelta(days=1)
        six_days_ago = today - timedelta(days=6)
        self.database.connection.executemany(
            """INSERT INTO business_income_daily(chat_id, owner_id, income_day, owner_income)
               VALUES (1, 10, ?, ?)""",
            [(yesterday.isoformat(), 11), (six_days_ago.isoformat(), 9)],
        )
        self.database.connection.commit()
        self.assertEqual(await self.database.business_income_periods(1, 10), (11, 20))
        businesses = await self.database.list_chat_businesses(1)
        self.assertEqual((businesses[0]["owner_id"], businesses[0]["business_type"]), (10, "field"))
        visible = await self.database.list_visible_businesses(20)
        self.assertEqual(visible[0]["owner_id"], 10)
        self.assertTrue(await self.database.user_knows_chat(20, 1))

    async def test_pirojok_basement_escape_has_persistent_hour_cooldown(self):
        await self.database.add_basement_member(1, 20, 10)
        result, cooldown_until = await self.database.escape_basement_with_cooldown(1, 20)
        self.assertEqual(result, "escaped")
        self.assertFalse(await self.database.is_basement_member(1, 20))

        await self.database.add_basement_member(1, 20, 10)
        result, repeated_until = await self.database.escape_basement_with_cooldown(1, 20)
        self.assertEqual(result, "cooldown")
        self.assertEqual(repeated_until, cooldown_until)
        self.assertTrue(await self.database.is_basement_member(1, 20))

        self.database.connection.execute(
            "UPDATE basement_escape_cooldowns SET cooldown_until=0 WHERE chat_id=1 AND user_id=20"
        )
        self.database.connection.commit()
        result, _ = await self.database.escape_basement_with_cooldown(1, 20)
        self.assertEqual(result, "escaped")


if __name__ == "__main__":
    unittest.main()
