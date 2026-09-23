import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import User

from checkers import Move, MoveResult, WHITE, initial_board
from database import Database
from handlers.routes import BET_RE, COMPETITION_RE, create_router
from parsing import parse_duration


class CompetitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "competition.sqlite3")
        await self.database.connect()
        await self.database.upsert_chat(-100, "Тестовый чат")
        for user_id, username in ((1, "player_one"), (2, "player_two"), (3, "viewer"), (4, "viewer2")):
            await self.database.upsert_user(-100, user_id, username, username)
        for user_id in (3, 4):
            self.database.connection.execute(
                """INSERT INTO franc_balances(chat_id, user_id, balance, updated_at)
                   VALUES (-100, ?, 100, 1)""",
                (user_id,),
            )
        self.database.connection.commit()

    async def asyncTearDown(self):
        await self.database.close()
        self.temp_dir.cleanup()

    async def create_competition(self, duration=60):
        challenge_id = await self.database.create_challenge(
            -100, 1, 2, game_type="checkers", friendly=True,
            awaiting_acceptance=True, competition_bet_seconds=duration,
        )
        await self.database.set_challenge_message(challenge_id, 123)
        accepted = await self.database.accept_checkers_competition(challenge_id, 2)
        self.assertEqual(accepted["status"], "betting")
        return challenge_id

    async def start_game(self, challenge_id):
        competition = await self.database.get_checkers_competition(challenge_id)
        with patch("database.utc_timestamp", return_value=int(competition["bets_close_at"])):
            started = await self.database.start_checkers_competition(challenge_id)
        self.assertEqual(started["status"], "active")

    async def test_command_spellings_and_duration_formats(self):
        for text, seconds in (
            ("Соревнование шашки 5 минут", 300),
            ("соревнование шашки 400 сек", 400),
            ("соревнование шашки 120 секунд", 120),
            ("соревнование шашки 4 мин", 240),
        ):
            match = COMPETITION_RE.fullmatch(text)
            self.assertIsNotNone(match)
            self.assertEqual(parse_duration(match.group(1)).seconds, seconds)
        self.assertIsNotNone(BET_RE.fullmatch("ставка 50 на @player_one"))
        self.assertIsNotNone(BET_RE.fullmatch("ставка 120 франков на @player_two"))
        with self.assertRaises(ValueError):
            await self.database.create_challenge(
                -100, 1, 2, game_type="checkers", friendly=True,
                competition_bet_seconds=59,
            )

    async def test_bets_are_atomic_paid_proportionally_and_not_paid_twice(self):
        challenge_id = await self.create_competition()
        self.assertEqual(
            await self.database.place_checkers_bet(challenge_id, -100, 3, 2, 10, "Зритель"),
            "placed",
        )
        self.assertEqual(
            await self.database.place_checkers_bet(challenge_id, -100, 4, 1, 20, "Зритель2"),
            "placed",
        )
        self.assertEqual(
            await self.database.place_checkers_bet(challenge_id, -100, 3, 1, 5, "Зритель"),
            "already_bet",
        )
        self.assertEqual(
            await self.database.place_checkers_bet(challenge_id, -100, 1, 2, 5, "Игрок"),
            "player",
        )
        self.assertEqual(await self.database.franc_balance(-100, 3), 90)
        self.assertEqual(await self.database.franc_balance(-100, 4), 80)
        await self.start_game(challenge_id)
        with patch("database.legal_checkers_moves", return_value={40: [Move(40, 33)]}), patch(
            "database.apply_checkers_move",
            return_value=MoveResult(initial_board(), False, WHITE, "победа", None),
        ):
            self.assertEqual((await self.database.checkers_click(challenge_id, 2, 40))["status"], "selected")
            result = await self.database.checkers_click(challenge_id, 2, 33)
        self.assertEqual(result["status"], "finished")
        self.assertEqual(await self.database.franc_balance(-100, 3), 120)
        self.assertEqual(await self.database.franc_balance(-100, 4), 80)
        competition = await self.database.get_checkers_competition(challenge_id)
        self.assertEqual(competition["settlement"], "paid")
        self.assertFalse(await self.database.finish_challenge(challenge_id))
        self.assertEqual(await self.database.franc_balance(-100, 3), 120)

    async def test_one_sided_bets_are_refunded_before_play(self):
        challenge_id = await self.create_competition()
        await self.database.place_checkers_bet(challenge_id, -100, 3, 2, 40, "Зритель")
        self.assertEqual(await self.database.franc_balance(-100, 3), 60)
        await self.database.close()
        await self.database.connect()
        await self.start_game(challenge_id)
        self.assertEqual(await self.database.franc_balance(-100, 3), 100)
        competition = await self.database.get_checkers_competition(challenge_id)
        self.assertEqual(competition["settlement"], "refunded")

    async def test_resignation_refunds_both_sides(self):
        challenge_id = await self.create_competition()
        await self.database.place_checkers_bet(challenge_id, -100, 3, 1, 20, "Зритель")
        await self.database.place_checkers_bet(challenge_id, -100, 4, 2, 30, "Зритель2")
        await self.start_game(challenge_id)
        self.assertTrue(await self.database.finish_challenge(challenge_id, "finished"))
        self.assertEqual(await self.database.franc_balance(-100, 3), 100)
        self.assertEqual(await self.database.franc_balance(-100, 4), 100)
        self.assertEqual(
            (await self.database.get_checkers_competition(challenge_id))["settlement"],
            "refunded",
        )

    async def test_deadline_refunds_bets_once(self):
        challenge_id = await self.create_competition()
        await self.database.place_checkers_bet(challenge_id, -100, 3, 1, 20, "Зритель")
        await self.database.place_checkers_bet(challenge_id, -100, 4, 2, 30, "Зритель2")
        await self.start_game(challenge_id)
        challenge = await self.database.get_challenge(challenge_id)
        with patch("database.utc_timestamp", return_value=int(challenge["deadline"])):
            self.assertIsNotNone(await self.database.claim_expired_challenge(challenge_id))
            self.assertIsNone(await self.database.claim_expired_challenge(challenge_id))
        self.assertEqual(await self.database.franc_balance(-100, 3), 100)
        self.assertEqual(await self.database.franc_balance(-100, 4), 100)
        self.assertEqual(
            (await self.database.get_checkers_competition(challenge_id))["settlement"],
            "refunded",
        )

    async def test_chat_bet_updates_one_message_and_removes_command(self):
        challenge_id = await self.create_competition()
        router = create_router(self.database)
        handler = next(
            item.callback for item in router.message.handlers
            if item.callback.__name__ == "checkers_bet"
        )
        user = User(id=3, is_bot=False, first_name="Зритель", username="viewer")
        message = SimpleNamespace(
            text="ставка 50 на @player_one", caption=None, from_user=user,
            chat=SimpleNamespace(id=-100, type="supergroup"),
            answer=AsyncMock(), delete=AsyncMock(),
        )
        async def get_chat_member(chat_id, user_id):
            username = "player_one" if user_id == 1 else "viewer"
            return SimpleNamespace(
                status="member",
                user=User(id=user_id, is_bot=False, first_name=username, username=username),
            )
        bot = SimpleNamespace(
            get_chat_member=get_chat_member, edit_message_text=AsyncMock(),
        )
        await handler(message, bot)
        self.assertEqual(await self.database.franc_balance(-100, 3), 50)
        message.delete.assert_awaited_once()
        body = bot.edit_message_text.await_args.args[0]
        self.assertIn("Зритель: 50 ₣", body)
        self.assertIn("Общий банк: <b>50 ₣</b>", body)
        self.assertEqual(
            (await self.database.list_checkers_bets(challenge_id))[0]["target_id"], 1
        )
