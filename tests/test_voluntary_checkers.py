import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import User

from database import CHALLENGE_DEADLINE_SECONDS, FORCE_OWNER_COOLDOWN_SECONDS, Database, utc_timestamp
from handlers.routes import blackjack_text, challenge_offer_text, create_router


class VoluntaryCheckersTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "games.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(-100, "Чат")
        self.users = {}
        for user_id in (1, 2):
            user = User(id=user_id, is_bot=False, first_name=f"Игрок {user_id}", username=f"player{user_id}")
            self.users[user_id] = user
            await self.db.upsert_user(-100, user_id, user.username, user.full_name,
                                      vulnerable_until=utc_timestamp() + 300)
            self.db._add_francs_locked(-100, user_id, 100)
        self.db.connection.commit()
        self.router = create_router(self.db)
        self.bot = SimpleNamespace(edit_message_text=AsyncMock())

    async def asyncTearDown(self):
        for handler in self.router.shutdown.handlers:
            await handler.callback()
        await asyncio.sleep(0)
        await self.db.close()
        self.folder.cleanup()

    def callback(self, challenge_id, prefix="ck", action="refuse", actor=2):
        return SimpleNamespace(data=f"{prefix}:{challenge_id}:{action}",
                               from_user=self.users[actor], answer=AsyncMock())

    def handler(self, name):
        return next(item.callback for item in self.router.callback_query.handlers if item.callback.__name__ == name)

    async def offer(self, **kwargs):
        challenge_id = await self.db.create_challenge(
            -100, 1, 2, game_type="checkers", awaiting_acceptance=True, **kwargs,
        )
        await self.db.set_challenge_message(challenge_id, 123)
        return challenge_id

    async def test_checkers_offer_never_forced_and_has_normal_deadline(self):
        challenge_id = await self.offer(forced=True, opponent_newcomer=True)
        challenge = await self.db.get_challenge(challenge_id)
        self.assertEqual((challenge["forced"], challenge["opponent_newcomer"]), (0, 0))
        self.assertEqual(challenge["deadline"] - challenge["created_at"], CHALLENGE_DEADLINE_SECONDS)
        text = await challenge_offer_text(self.db, challenge)
        self.assertNotIn("не может отказаться", text)
        self.assertNotIn("станет рабом", text)
        self.assertIn("3 часа", text)

    async def test_newcomer_can_refuse_checkers_and_stake_is_refunded_once(self):
        challenge_id = await self.offer(friendly=True, player_stake=50)
        self.assertEqual(await self.db.franc_balance(-100, 1), 50)
        callback = self.callback(challenge_id)
        await self.handler("checkers_callback")(callback, self.bot)
        await self.handler("checkers_callback")(callback, self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "refused")
        self.assertEqual(await self.db.franc_balance(-100, 1), 100)
        self.assertEqual(await self.db.franc_balance(-100, 2), 100)
        self.assertIsNone(await self.db.get_owner(-100, 2))
        self.bot.edit_message_text.assert_awaited_once()
        self.assertIsNone(self.bot.edit_message_text.await_args.kwargs.get("reply_markup"))

    async def test_newcomer_can_refuse_accepted_checkers_before_first_move(self):
        challenge_id = await self.offer(opponent_newcomer=True)
        await self.db.accept_challenge(challenge_id, 2)
        await self.handler("checkers_callback")(self.callback(challenge_id), self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "refused")
        self.assertIsNone(await self.db.get_owner(-100, 2))

    async def test_checkers_does_not_consume_weekly_force_attempt(self):
        await self.db.force_enslave(-100, 1, 2)
        self.db.connection.execute("UPDATE ownership SET acquired_at=?", (utc_timestamp() - FORCE_OWNER_COOLDOWN_SECONDS,))
        self.db.connection.commit()
        self.assertTrue(await self.db.can_force_owner(-100, 1, 2))
        challenge_id = await self.offer(forced=True)
        self.assertEqual((await self.db.get_challenge(challenge_id))["forced"], 0)
        self.assertTrue(await self.db.can_force_owner(-100, 1, 2))

    async def test_existing_forced_offer_is_migrated_and_cooldown_restored(self):
        await self.db.force_enslave(-100, 1, 2)
        challenge_id = await self.offer()
        challenge = await self.db.get_challenge(challenge_id)
        self.db.connection.execute(
            "UPDATE ownership SET acquired_at=?,last_forced_at=?",
            (utc_timestamp() - FORCE_OWNER_COOLDOWN_SECONDS, challenge["created_at"]),
        )
        self.db.connection.execute("UPDATE challenges SET forced=1,opponent_newcomer=1,deadline=created_at+300 WHERE id=?", (challenge_id,))
        self.db.connection.commit()
        await self.db.close()
        await self.db.connect()
        challenge = await self.db.get_challenge(challenge_id)
        self.assertEqual((challenge["forced"], challenge["opponent_newcomer"]), (0, 0))
        self.assertEqual(challenge["deadline"] - challenge["created_at"], CHALLENGE_DEADLINE_SECONDS)
        self.assertTrue(await self.db.can_force_owner(-100, 1, 2))
        await self.handler("checkers_callback")(self.callback(challenge_id), self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "refused")

    async def test_ignored_newcomer_checkers_has_no_slave_penalty(self):
        challenge_id = await self.offer(opponent_newcomer=True)
        # Exercise recovery of a legacy expired offer, even before migration clears flags.
        self.db.connection.execute("UPDATE challenges SET opponent_newcomer=1,deadline=0 WHERE id=?", (challenge_id,))
        self.db.connection.commit()
        for startup in self.router.startup.handlers:
            await startup.callback(self.bot)
        for _ in range(30):
            await asyncio.sleep(0.01)
            if self.bot.edit_message_text.await_count:
                break
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "pending_deadline")
        self.assertIsNone(await self.db.get_owner(-100, 2))
        self.assertIn("Последствий нет", self.bot.edit_message_text.await_args.args[0])

    async def test_other_games_still_cannot_be_refused_by_newcomer(self):
        for game, prefix, handler_name in (("blackjack", "bj", "blackjack_callback"), ("rps", "rps", "rps_callback")):
            for pending in (True, False):
                with self.subTest(game=game, pending=pending):
                    challenge_id = await self.db.create_challenge(-100, 1, 2, game_type=game,
                                                                  opponent_newcomer=True, awaiting_acceptance=pending)
                    await self.db.set_challenge_message(challenge_id, 123)
                    await self.handler(handler_name)(self.callback(challenge_id, prefix=prefix), self.bot)
                    self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "pending" if pending else "active")
                    await self.db.finish_challenge(challenge_id, "cancelled")

    async def test_blackjack_guide_for_newcomer_in_offer_and_game(self):
        challenge_id = await self.db.create_challenge(-100, 1, 2, game_type="blackjack",
                                                     opponent_newcomer=True, awaiting_acceptance=True)
        challenge = await self.db.get_challenge(challenge_id)
        offer = await challenge_offer_text(self.db, challenge)
        await self.db.accept_challenge(challenge_id, 2)
        challenge = await self.db.get_challenge(challenge_id)
        text = await blackjack_text(self.db, challenge, await self.db.get_blackjack_game(challenge_id))
        for body in (offer, text):
            for expected in ("📖", "21", "➕ Ещё", "✋ Хватит", "👁 Мои карты", "11 или 1"):
                self.assertIn(expected, body)

    async def test_blackjack_guide_for_friendly_newcomer_but_not_regular_member(self):
        challenge_id = await self.db.create_challenge(-100, 1, 2, game_type="blackjack",
                                                     friendly=True, awaiting_acceptance=True)
        challenge = await self.db.get_challenge(challenge_id)
        self.assertIn("📖", await challenge_offer_text(self.db, challenge))
        self.db.connection.execute("UPDATE users SET vulnerable_until=0")
        self.db.connection.commit()
        self.assertNotIn("📖", await challenge_offer_text(self.db, challenge))


if __name__ == "__main__":
    unittest.main()
