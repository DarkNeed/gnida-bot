import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import User

from database import Database, utc_timestamp
from handlers.routes import CANCEL_CHALLENGE_RE, create_router


class ChallengeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "recovery.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(-100, "Чат")
        self.users = {}
        for user_id in (1, 2, 3, 4):
            user = User(id=user_id, is_bot=False, first_name=f"Игрок {user_id}", username=f"player{user_id}")
            self.users[user_id] = user
            await self.db.upsert_user(-100, user_id, user.username, user.full_name)
            self.db.connection.execute(
                "INSERT INTO franc_balances(chat_id, user_id, balance, updated_at) VALUES (-100, ?, 1000, 1)",
                (user_id,),
            )
        self.db.connection.commit()
        self.router = create_router(self.db, kargassia_chat_id=-100)
        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
            edit_message_text=AsyncMock(),
        )

    async def asyncTearDown(self):
        for handler in self.router.shutdown.handlers:
            await handler.callback()
        await asyncio.sleep(0)
        await self.db.close()
        self.folder.cleanup()

    def handler(self, name):
        return next(item.callback for item in self.router.message.handlers if item.callback.__name__ == name)

    def message(self, text="Игра кнб 50", actor=1, opponent=2, private=False):
        return SimpleNamespace(
            text=text, caption=None, sender_chat=None,
            chat=SimpleNamespace(id=actor if private else -100, type="private" if private else "supergroup"),
            from_user=self.users[actor],
            reply_to_message=SimpleNamespace(sender_chat=None, from_user=self.users[opponent]),
            answer=AsyncMock(return_value=SimpleNamespace(message_id=123)),
        )

    def age_challenge(self, challenge_id, *, expired=False):
        self.db.connection.execute(
            "UPDATE challenges SET created_at=?, deadline=? WHERE id=?",
            (utc_timestamp() - 120, 0 if expired else utc_timestamp() + 10800, challenge_id),
        )
        self.db.connection.commit()

    async def offer(self, *, active=False, newcomer=False, stake=50):
        return await self.db.create_challenge(
            -100, 1, 2, awaiting_acceptance=not active,
            friendly=not newcomer, opponent_newcomer=newcomer,
            player_stake=stake, game_type="blackjack" if active else "rps",
        )

    async def test_failed_telegram_send_releases_slot_and_refunds_all_games(self):
        for game in ("кнб", "блекджек", "шашки"):
            with self.subTest(game=game):
                message = self.message(f"Игра {game} 50")
                message.answer.side_effect = TelegramBadRequest(
                    method=SendMessage(chat_id=-100, text="offer"), message="send failed",
                )
                with self.assertRaises(TelegramBadRequest):
                    await self.handler("challenge")(message, self.bot)
                self.assertEqual(await self.db.blocking_challenges(-100, (1, 2)), [])
                self.assertEqual(await self.db.franc_balance(-100, 1), 1000)
                self.assertEqual(await self.db.franc_balance(-100, 2), 1000)

    async def test_failed_message_id_save_also_refunds(self):
        with patch.object(self.db, "set_challenge_message", AsyncMock(side_effect=RuntimeError("save failed"))):
            with self.assertRaises(RuntimeError):
                await self.handler("challenge")(self.message(), self.bot)
        self.assertEqual(await self.db.blocking_challenges(-100, (1,)), [])
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)

    async def test_text_cancel_in_private_refunds_once_without_message(self):
        challenge_id = await self.offer()
        message = self.message("Отменить вызов", private=True)
        await self.handler("cancel_own_challenge")(message, self.bot)
        await self.handler("cancel_own_challenge")(message, self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "cancelled")
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)
        self.bot.edit_message_text.assert_not_awaited()
        self.assertIn("нет активного", message.answer.await_args.args[0])

    async def test_invitee_cannot_cancel_fresh_offer_or_started_game(self):
        challenge_id = await self.offer()
        await self.db.set_challenge_message(challenge_id, 123)
        await self.handler("cancel_own_challenge")(self.message(actor=2), self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "pending")
        await self.db.accept_challenge(challenge_id, 2)
        await self.handler("cancel_own_challenge")(self.message(), self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "active")
        self.assertEqual(await self.db.franc_balance(-100, 1), 950)
        self.assertEqual(await self.db.franc_balance(-100, 2), 950)

    async def test_old_unpublished_offer_is_recovered_on_new_challenge(self):
        challenge_id = await self.offer(newcomer=True, stake=0)
        self.age_challenge(challenge_id, expired=True)
        await self.handler("challenge")(self.message(opponent=3), self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "cancelled")
        self.assertIsNone(await self.db.get_owner(-100, 2))
        rows = await self.db.blocking_challenges(-100, (1,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opponent_id"], 3)

    async def test_fresh_in_flight_offer_is_not_recovered(self):
        challenge_id = await self.offer()
        message = self.message(opponent=3)
        await self.handler("challenge")(message, self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "pending")
        self.assertIn("уже есть", message.answer.await_args.args[0])
        self.assertEqual(await self.db.franc_balance(-100, 1), 950)

    async def test_expired_published_offer_and_game_release_slot_and_refund(self):
        for active in (False, True):
            with self.subTest(active=active):
                challenge_id = await self.offer(active=active)
                await self.db.set_challenge_message(challenge_id, 321)
                self.age_challenge(challenge_id, expired=True)
                await self.handler("challenge")(self.message(opponent=3), self.bot)
                self.assertIn((await self.db.get_challenge(challenge_id))["status"], {"deadline", "pending_deadline"})
                self.assertEqual(await self.db.franc_balance(-100, 1), 950)
                self.assertEqual(await self.db.franc_balance(-100, 2), 1000)
                rows = await self.db.blocking_challenges(-100, (1,))
                self.assertEqual(len(rows), 1)
                await self.db.cancel_challenge_offer(int(rows[0]["id"]), 1)
                await asyncio.sleep(0)

    async def test_startup_cleans_orphan_with_no_newcomer_penalty(self):
        challenge_id = await self.offer(newcomer=True, stake=0)
        self.age_challenge(challenge_id, expired=True)
        router = create_router(self.db)
        for startup in router.startup.handlers:
            await startup.callback(self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "cancelled")
        self.assertIsNone(await self.db.get_owner(-100, 2))

    async def test_command_spellings(self):
        for text in ("Отменить вызов", "!отменить вызов", "/отменить вызов", "/cancel_challenge@GnidoBot"):
            self.assertIsNotNone(CANCEL_CHALLENGE_RE.fullmatch(text))

    async def test_existing_inline_game_is_not_mistaken_for_unpublished(self):
        challenge_id = await self.offer(active=True)
        await self.db.set_challenge_inline_message(challenge_id, "inline-game")
        self.age_challenge(challenge_id)
        message = self.message(opponent=3)
        await self.handler("challenge")(message, self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "active")
        self.assertEqual(await self.db.franc_balance(-100, 1), 950)
        self.assertIn("уже есть", message.answer.await_args.args[0])

    async def test_orphan_competition_refunds_players_and_spectators_once(self):
        challenge_id = await self.db.create_challenge(
            -100, 1, 2, game_type="checkers", friendly=True,
            awaiting_acceptance=True, competition_bet_seconds=60, player_stake=50,
        )
        await self.db.accept_checkers_competition(challenge_id, 2)
        self.assertEqual(
            await self.db.place_checkers_bet(challenge_id, -100, 3, 1, 75, "Зритель"),
            "placed",
        )
        self.age_challenge(challenge_id)
        message = self.message("Отменить вызов", actor=2)
        await self.handler("cancel_own_challenge")(message, self.bot)
        await self.handler("cancel_own_challenge")(message, self.bot)
        self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "failed")
        for user_id in (1, 2, 3):
            self.assertEqual(await self.db.franc_balance(-100, user_id), 1000)


if __name__ == "__main__":
    unittest.main()
