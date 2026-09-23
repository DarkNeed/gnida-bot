import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import User

from checkers import Move, MoveResult, WHITE, initial_board
from database import Database, InsufficientFrancStake
from handlers.routes import (
    CHALLENGE_RE, COMPETITION_RE, COMPETITION_STAKE_RE, GAME_RE, create_router,
)
from parsing import parse_duration


class PlayerWagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "wagers.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(-100, "Чат")
        for user_id in (1, 2, 3, 4):
            await self.db.upsert_user(-100, user_id, f"player{user_id}", f"Игрок {user_id}")
            self.db.connection.execute(
                """INSERT INTO franc_balances(chat_id, user_id, balance, updated_at)
                   VALUES (-100, ?, 1000, 1)""",
                (user_id,),
            )
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    async def create_offer(self, game="rps", stake=50, competition=False):
        return await self.db.create_challenge(
            -100, 1, 2, game_type=game, friendly=True,
            awaiting_acceptance=True, player_stake=stake,
            competition_bet_seconds=60 if competition else None,
        )

    async def test_spellings(self):
        self.assertEqual(GAME_RE.fullmatch("игра блекджек 50").group(2), "50")
        self.assertEqual(GAME_RE.fullmatch("игра кнб 120 франков").group(2), "120")
        self.assertEqual(CHALLENGE_RE.fullmatch("вызов шашки 600 франков").group(2), "600")
        raw = COMPETITION_RE.fullmatch(
            "соревнование шашки 5 мин 120 франков"
        ).group(1)
        match = COMPETITION_STAKE_RE.fullmatch(raw)
        self.assertEqual(parse_duration(match.group(1)).seconds, 300)
        self.assertEqual(int(match.group(2)), 120)

    async def test_creation_checks_both_balances_and_reserves_only_creator(self):
        self.db.connection.execute(
            "UPDATE franc_balances SET balance=20 WHERE chat_id=-100 AND user_id=2"
        )
        self.db.connection.commit()
        with self.assertRaises(InsufficientFrancStake) as raised:
            await self.create_offer()
        self.assertEqual(raised.exception.user_id, 2)
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)
        self.db.connection.execute(
            "UPDATE franc_balances SET balance=1000 WHERE chat_id=-100 AND user_id=2"
        )
        self.db.connection.commit()
        challenge_id = await self.create_offer()
        self.assertEqual(await self.db.franc_balance(-100, 1), 950)
        self.assertEqual(await self.db.franc_balance(-100, 2), 1000)
        self.assertEqual((await self.db.get_challenge(challenge_id))["friendly"], 1)
        self.assertTrue(await self.db.cancel_challenge_offer(challenge_id, 1))
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)

    async def test_acceptance_race_cancels_and_refunds(self):
        challenge_id = await self.create_offer()
        self.db.connection.execute(
            "UPDATE franc_balances SET balance=0 WHERE chat_id=-100 AND user_id=2"
        )
        self.db.connection.commit()
        with self.assertRaises(InsufficientFrancStake):
            await self.db.accept_challenge(challenge_id, 2)
        self.assertTrue(await self.db.finish_challenge(challenge_id, "failed"))
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)
        self.assertEqual((await self.db.get_challenge_wager(challenge_id))["settlement"], "refunded")

    async def test_rps_win_pays_once_and_draw_refunds(self):
        challenge_id = await self.create_offer(stake=120)
        await self.db.accept_challenge(challenge_id, 2)
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (880, 880))
        await self.db.choose(challenge_id, 1, "rock")
        await self.db.choose(challenge_id, 2, "scissors")
        self.assertTrue(await self.db.finish_challenge(challenge_id))
        self.assertFalse(await self.db.finish_challenge(challenge_id))
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (1120, 880))
        challenge_id = await self.create_offer(stake=50)
        await self.db.accept_challenge(challenge_id, 2)
        await self.db.choose(challenge_id, 1, "paper")
        await self.db.choose(challenge_id, 2, "paper")
        await self.db.finish_challenge(challenge_id)
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (1120, 880))

    async def test_blackjack_natural_finish_pays_winner(self):
        challenge_id = await self.create_offer(game="blackjack")
        await self.db.accept_challenge(challenge_id, 2)
        self.db.connection.execute(
            """UPDATE blackjack_games SET challenger_hand=?, opponent_hand=?, turn_user_id=1
               WHERE challenge_id=?""",
            (json.dumps(["K♠", "Q♥"]), json.dumps(["10♣", "8♦"]), challenge_id),
        )
        self.db.connection.commit()
        await self.db.blackjack_action(challenge_id, 1, "stand")
        result = await self.db.blackjack_action(challenge_id, 2, "stand")
        self.assertEqual((result["status"], result["winner_id"]), ("finished", 1))
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (1050, 950))

    async def test_competition_stake_and_spectator_bets_are_separate(self):
        challenge_id = await self.create_offer(game="checkers", stake=120, competition=True)
        accepted = await self.db.accept_checkers_competition(challenge_id, 2)
        self.assertEqual(accepted["status"], "betting")
        self.assertEqual(await self.db.place_checkers_bet(challenge_id, -100, 3, 2, 100, "Третий"), "placed")
        self.assertEqual(await self.db.place_checkers_bet(challenge_id, -100, 4, 1, 100, "Четвёртый"), "placed")
        competition = await self.db.get_checkers_competition(challenge_id)
        with patch("database.utc_timestamp", return_value=int(competition["bets_close_at"])):
            await self.db.start_checkers_competition(challenge_id)
        with patch("database.legal_checkers_moves", return_value={40: [Move(40, 33)]}), patch(
            "database.apply_checkers_move",
            return_value=MoveResult(initial_board(), False, WHITE, "победа", None),
        ):
            await self.db.checkers_click(challenge_id, 2, 40)
            result = await self.db.checkers_click(challenge_id, 2, 33)
        self.assertEqual((result["status"], result["winner_id"]), ("finished", 2))
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (880, 1120))
        self.assertEqual((await self.db.franc_balance(-100, 3), await self.db.franc_balance(-100, 4)), (1100, 900))
        self.assertEqual((await self.db.get_challenge_wager(challenge_id))["settlement"], "paid")

    async def test_checkers_surrender_pays_other_player(self):
        challenge_id = await self.create_offer(game="checkers")
        await self.db.accept_challenge(challenge_id, 2)
        self.assertTrue(await self.db.finish_challenge(challenge_id, winner_id=2))
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (950, 1050))

    async def test_expired_offer_refunds_creator(self):
        challenge_id = await self.create_offer(stake=75)
        challenge = await self.db.get_challenge(challenge_id)
        with patch("database.utc_timestamp", return_value=int(challenge["deadline"])):
            self.assertIsNotNone(await self.db.claim_expired_challenge(challenge_id))
            self.assertIsNone(await self.db.claim_expired_challenge(challenge_id))
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)

    async def test_unfinished_game_timeout_refunds_both_players(self):
        challenge_id = await self.create_offer(game="blackjack", stake=80)
        await self.db.accept_challenge(challenge_id, 2)
        challenge = await self.db.get_challenge(challenge_id)
        with patch("database.utc_timestamp", return_value=int(challenge["deadline"])):
            self.assertIsNotNone(await self.db.claim_expired_challenge(challenge_id))
        self.assertEqual((await self.db.franc_balance(-100, 1), await self.db.franc_balance(-100, 2)), (1000, 1000))

    async def test_competition_acceptance_needs_opponent_funds(self):
        challenge_id = await self.create_offer(game="checkers", competition=True)
        self.db.connection.execute(
            "UPDATE franc_balances SET balance=0 WHERE chat_id=-100 AND user_id=2"
        )
        self.db.connection.commit()
        with self.assertRaises(InsufficientFrancStake):
            await self.db.accept_checkers_competition(challenge_id, 2)
        self.assertTrue(await self.db.finish_challenge(challenge_id, "failed"))
        self.assertEqual(await self.db.franc_balance(-100, 1), 1000)

    async def test_chat_wagered_challenge_accepts_without_slavery(self):
        router = create_router(self.db)
        create_handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "challenge"
        )
        callback_handler = next(
            item.callback for item in router.callback_query.handlers
            if item.callback.__name__ == "checkers_callback"
        )
        first = User(id=1, is_bot=False, first_name="Первый", username="player1")
        second = User(id=2, is_bot=False, first_name="Второй", username="player2")
        answer = AsyncMock(return_value=SimpleNamespace(message_id=123))
        message = SimpleNamespace(
            text="Вызов шашки 600 франков", caption=None, sender_chat=None,
            chat=SimpleNamespace(id=-100, type="supergroup"), from_user=first,
            reply_to_message=SimpleNamespace(sender_chat=None, from_user=second),
            answer=answer,
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
            edit_message_text=AsyncMock(),
        )
        try:
            await create_handler(message, bot)
            challenge_id = self.db.connection.execute(
                "SELECT MAX(id) FROM challenges"
            ).fetchone()[0]
            challenge = await self.db.get_challenge(challenge_id)
            self.assertEqual((challenge["status"], challenge["friendly"]), ("pending", 1))
            self.assertEqual(await self.db.franc_balance(-100, 1), 400)
            self.assertIn("600 ₣", answer.await_args.args[0])
            callback = SimpleNamespace(
                data=f"ck:{challenge_id}:accept", from_user=second, answer=AsyncMock(),
            )
            await callback_handler(callback, bot)
            self.assertEqual((await self.db.get_challenge(challenge_id))["status"], "active")
            self.assertEqual(await self.db.franc_balance(-100, 2), 400)
            self.assertIn("1200 ₣", bot.edit_message_text.await_args.args[0])
        finally:
            for shutdown in router.shutdown.handlers:
                await shutdown.callback()

    async def test_chat_competition_combines_timer_and_player_stake(self):
        router = create_router(self.db)
        handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "challenge"
        )
        first = User(id=1, is_bot=False, first_name="Первый", username="player1")
        second = User(id=2, is_bot=False, first_name="Второй", username="player2")
        message = SimpleNamespace(
            text="соревнование шашки 5 мин 120 франков", caption=None,
            sender_chat=None, chat=SimpleNamespace(id=-100, type="supergroup"),
            from_user=first,
            reply_to_message=SimpleNamespace(sender_chat=None, from_user=second),
            answer=AsyncMock(return_value=SimpleNamespace(message_id=123)),
        )
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
        )
        try:
            await handler(message, bot)
            challenge_id = self.db.connection.execute(
                "SELECT MAX(id) FROM challenges"
            ).fetchone()[0]
            competition = await self.db.get_checkers_competition(challenge_id)
            wager = await self.db.get_challenge_wager(challenge_id)
            self.assertEqual((competition["bet_duration"], wager["stake"]), (300, 120))
            self.assertEqual(await self.db.franc_balance(-100, 1), 880)
            self.assertEqual(await self.db.franc_balance(-100, 2), 1000)
            self.assertIn("240 ₣", message.answer.await_args.args[0])
        finally:
            for shutdown in router.shutdown.handlers:
                await shutdown.callback()
