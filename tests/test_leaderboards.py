"""Seasonal PvP, anti-farming, enterprise pages and owner-only release."""

import json
import logging
import tempfile
import time
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database
from leaderboards import MSK, elo_delta, income_period
from handlers.routes import create_router, CUSTOM_COMMAND_OWNER_ID, RELEASE_RE
from handlers.leaderboards import enterprise_top_view, enterprise_site_view
from handlers.arena import OFFER_RE, ARENA_TOP_RE
from aiohttp.test_utils import TestClient, TestServer
from arena_web import create_arena_app
from test_arena import signed, TOKEN
import test_arena_market_client as client_helpers


class LeaderboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.clock = int(datetime(2026, 10, 16, 12, tzinfo=MSK).timestamp())
        self.patches = [patch(name, side_effect=lambda: self.clock) for name in
            ("database.utc_timestamp", "arena_store.utc_timestamp")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "leaderboard.sqlite3")
        await self.db.connect()
        for chat in (-100, -200):
            await self.db.upsert_chat(chat, "QA")
            for user in range(10, 41):
                await self.db.upsert_user(chat, user, f"u{user}", f"User {user}")
        self.sequence = 0

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def battle(self, *, a=10, b=20, ranked=True, played=True):
        row = await self.db.arena_offer(-100, a, b, ranked=ranked)
        await self.db.arena_set_message(row["token"], 101)
        row = await self.db.arena_setup(row["token"], b, "accept")
        if played:
            state = json.loads(row["state_json"])
            for side in state["sides"].values():
                side["hp"] = side["stats"]["max_hp"] = 1000
            self.db.connection.execute("UPDATE arena_battles SET state_json=? WHERE token=?", (json.dumps(state), row["token"]))
            self.db.connection.commit()
            for _ in range(2):
                state = json.loads(row["state_json"])
                actor = state["sides"][state["active_side"]]["controller_id"]
                row = await self.db.arena_action(row["token"], actor, row["revision"], "bum_punch")
        return row

    async def finish(self, row, loser=20):
        return await self.db.arena_action(row["token"], loser, row["revision"], "surrender")

    def seed_result(self, a=10, b=20, winner="a", *, actions=True, token=None):
        self.sequence += 1
        row = dict(ranked=1, token=token or f"seed-{self.sequence}", a_owner=a, b_owner=b)
        state = dict(winner=winner, ranked_actions={"a": int(actions), "b": int(actions)})
        with self.db.connection:
            self.db._rating_finish_locked(row, state, self.clock)
        return row, state

    async def test_ordinary_battles_and_old_history_never_ranked(self):
        row = await self.finish(await self.battle(ranked=False))
        self.assertNotIn("rating_result", json.loads(row["state_json"]))
        await self.db.close()
        await self.db.connect()
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_ratings").fetchone()[0], 0)
        self.assertFalse((await self.db.arena_get(row["token"]))["ranked"])

    async def test_ranked_consent_result_elo_and_repeated_delivery(self):
        row = await self.battle()
        self.assertTrue(row["b_accepted"])
        self.assertTrue(json.loads(row["state_json"])["ranked"])
        row = await self.finish(row)
        state = json.loads(row["state_json"])
        self.assertEqual(state["rating_result"]["deltas"], {"a": 12, "b": -12})
        self.assertEqual((await self.db.arena_leaderboard(10))["own"]["rating"], 1012)
        with self.db.connection:
            self.db._rating_finish_locked(row, state, self.clock)
        self.assertEqual((await self.db.arena_leaderboard(10))["own"]["games"], 1)
        with self.assertRaises(ValueError):
            await self.finish(row)

    async def test_no_free_rating_for_early_surrender(self):
        row = await self.finish(await self.battle(played=False))
        result = json.loads(row["state_json"])["rating_result"]
        self.assertEqual(result["deltas"], {"a": 0, "b": -12})
        self.assertEqual(json.loads(row["state_json"])["rewards"], {"a": 0, "b": 0})
        self.assertEqual((await self.db.arena_leaderboard(10))["own"]["wins"], 0)
        self.assertEqual((await self.db.arena_leaderboard(20))["own"]["losses"], 1)

    async def test_pair_protection_cross_chat_and_character_slot(self):
        await self.finish(await self.battle())
        with self.assertRaisesRegex(ValueError, "24 часа"):
            await self.db.arena_offer(-200, 20, 10, ranked=True)
        with self.db.connection:
            self.db._character_switch_locked(10, 2)
        with self.assertRaisesRegex(ValueError, "24 часа"):
            await self.db.arena_offer(-100, 10, 20, ranked=True)
        # Protection never blocks an ordinary friendly duel.
        row = await self.db.arena_offer(-200, 10, 20)
        await self.db.arena_setup(row["token"], 10, "cancel")
        self.clock += 86400
        row = await self.db.arena_offer(-100, 10, 20, ranked=True)
        self.assertTrue(row["ranked"])

    async def test_season_calibration_archive_and_no_slot_reset(self):
        for target in range(20, 25):
            self.seed_result(b=target)
        before = await self.db.arena_leaderboard(10)
        self.assertEqual(before["own"]["place"], 1)
        self.assertEqual(before["entries"][0]["actor_id"], 10)
        self.clock = int(datetime(2026, 11, 1, 12, tzinfo=MSK).timestamp())
        current = await self.db.arena_leaderboard(10)
        old = await self.db.arena_leaderboard(10, season="2026-10")
        self.assertEqual(current["own"]["rating"], 1000)
        self.assertFalse(current["entries"])
        self.assertTrue(old["archived"])
        self.assertEqual(old["entries"][0]["title"], "Чемпион арены")
        self.assertEqual(old["own"]["rating"], before["own"]["rating"])

    async def test_daily_cap_and_moscow_day_boundary(self):
        for target in range(20, 30):
            self.seed_result(b=target)
        with self.assertRaisesRegex(ValueError, "10 учтённых"):
            await self.db.arena_offer(-100, 10, 31, ranked=True)
        self.clock = int(datetime(2026, 10, 17, 0, tzinfo=MSK).timestamp())
        self.assertTrue((await self.db.arena_offer(-100, 10, 31, ranked=True))["ranked"])

    async def test_ranked_stake_rejected_and_cancellation_free(self):
        with self.assertRaises(ValueError):
            await self.db.arena_offer(-100, 10, 20, stake=1, ranked=True)
        row = await self.db.arena_offer(-100, 10, 20, ranked=True)
        await self.db.arena_setup(row["token"], 20, "refuse")
        self.assertEqual((await self.db.arena_leaderboard(10))["own"]["rating"], 1000)

    async def test_rating_and_battle_result_roll_back_together(self):
        row = await self.battle()
        with patch.object(self.db, "_grant_profile_xp_locked", side_effect=RuntimeError("disk")):
            with self.assertRaises(RuntimeError):
                await self.finish(row)
        self.assertEqual((await self.db.arena_leaderboard(10))["own"]["rating"], 1000)
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_rating_results").fetchone()[0], 0)
        self.assertEqual((await self.db.arena_get(row["token"]))["status"], "active")
        await self.finish(row)
        self.assertEqual((await self.db.arena_leaderboard(10))["own"]["rating"], 1012)

    async def test_leave_active_ranked_is_loss_not_cancellation(self):
        row = await self.battle()
        await self.db.arena_leave_battle(-200, 20, row["token"])
        self.assertEqual((await self.db.arena_leaderboard(20))["own"]["losses"], 1)

    async def test_three_inactive_turns_end_ranked_but_no_winner_farm(self):
        row = await self.battle(played=False)
        for _ in range(6):
            if row["status"] == "finished":
                break
            self.clock = row["deadline"]
            await self.db.arena_expire()
            row = await self.db.arena_get(row["token"])
        state = json.loads(row["state_json"])
        self.assertEqual(state["finish_reason"], "ranked_inactivity")
        self.assertEqual(sorted(state["rating_result"]["deltas"].values()), [-12, 0])

    async def test_failed_expiry_cannot_commit_rating_without_battle_result(self):
        row = await self.battle(played=False)
        state = json.loads(row["state_json"])
        side = state["active_side"]
        state["ranked_timeouts"][side] = 2
        self.db.connection.execute("UPDATE arena_battles SET state_json=? WHERE token=?", (json.dumps(state), row["token"]))
        self.db.connection.commit()
        self.clock = row["deadline"]
        with patch.object(self.db, "_grant_profile_xp_locked", side_effect=RuntimeError("disk")):
            with self.assertRaises(RuntimeError):
                await self.db.arena_get(row["token"])
        # Even an unrelated later commit cannot persist half a result.
        self.db.connection.commit()
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_rating_results").fetchone()[0], 0)
        raw = self.db.connection.execute("SELECT status,state_json FROM arena_battles WHERE token=?", (row["token"],)).fetchone()
        self.assertEqual(raw["status"], "active")
        self.assertFalse(json.loads(raw["state_json"])["finished"])

    async def test_page_and_my_place(self):
        with self.db.connection:
            for actor in range(10, 35):
                self.db.connection.execute("INSERT INTO arena_ratings VALUES('2026-10',?,?,5,3,2,0)", (actor, 1100 - actor))
        data = await self.db.arena_leaderboard(34, mine=True)
        self.assertEqual((data["page"], data["own"]["place"], len(data["entries"])), (2, 25, 5))
        for season in ("2026-99", "9999-01", "2026-1", "../"):
            with self.assertRaises(ValueError):
                await self.db.arena_leaderboard(10, season=season)

    async def site(self, owner=10, kind="field", chat=-100):
        await self.db.upsert_user(chat, 1000 + owner, f"worker{owner}", "Worker")
        await self.db.force_enslave(chat, 1000 + owner, owner)
        await self.db.credit_francs(chat, owner, 10000)
        self.assertEqual(await self.db.create_business(chat, owner, kind), "created")
        return dict(await self.db.get_business(chat, owner, business_type=kind))

    def income(self, site, amount, day="2026-10-15"):
        with self.db.connection:
            return self.db._enterprise_credit_site_locked(site, day, amount)

    async def test_enterprise_owners_aggregate_net_not_wallet_or_today(self):
        field = await self.site()
        tavern = await self.site(kind="tavern")
        other = await self.site(owner=20)
        foreign = await self.site(owner=20, chat=-200)
        self.income(field, 1000)
        self.income(tavern, 100)
        self.income(other, 1000)
        self.income(other, 9000, "2026-10-16")
        self.income(foreign, 99999)
        await self.db.credit_francs(-100, 20, 999999)
        data = await self.db.enterprise_leaderboard(-100)
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual([(r["id"], r["amount"]) for r in data["entries"]], [(10, 960), (20, 895)])
        self.assertEqual(data["entries"][0]["sites"], 2)
        companies = await self.db.enterprise_leaderboard(-100, kind="sites")
        self.assertEqual(len(companies["entries"]), 3)
        self.assertEqual(max(r["amount"] for r in companies["entries"]), 1000)

    async def test_expedition_income_shares_tax_but_never_inflates_enterprise_top(self):
        site = await self.site()
        self.income(site, 100)
        stamp = self.clock - 86400
        with self.db.connection:
            net, tax = self.db._credit_business_income_locked(-100, 10, "2026-10-15", 10000)
            self.db.connection.execute("""INSERT INTO slave_expeditions(id,chat_id,owner_id,mission,status,
                started_at,ends_at,finished_at,nonce,quote_json,result_json)
                VALUES('old-trip',-100,10,'test','finished',?,?,?,'once','{}',?)""",
                (stamp - 100, stamp, stamp, json.dumps(dict(francs=net, tax=tax))))
        data = await self.db.enterprise_leaderboard(-100)
        self.assertEqual(data["entries"][0]["amount"], 100)
        totals = await self.db.enterprise_owner_periods(-100, 10)
        self.assertEqual(totals["day"], dict(net=100, tax=0))

    async def test_enterprise_periods_and_closed_history_survive_reopen(self):
        field = await self.site()
        self.income(field, 100, "2026-10-01")
        self.income(field, 200, "2026-10-14")
        self.income(field, 300)
        for period, expected in (("day", 300), ("week", 500), ("all", 600)):
            data = await self.db.enterprise_leaderboard(-100, period=period)
            self.assertEqual(data["entries"][0]["amount"], expected)
        view = await self.db.holdings_view(-100, 10)
        await self.db.enterprise_close(-100, 10, field["id"], view["revision"])
        await self.db.close()
        await self.db.connect()
        data = await self.db.enterprise_leaderboard(-100)
        self.assertEqual(data["entries"][0]["amount"], 500)
        self.assertEqual(data["entries"][0]["sites"], 0)
        companies = await self.db.enterprise_leaderboard(-100, kind="sites")
        self.assertTrue(companies["entries"][0]["closed"])
        reopened = await self.site()
        self.assertNotEqual(reopened["id"], field["id"])

    async def test_enterprise_pages_and_distinct_site_buttons(self):
        sites = [await self.site(kind=kind) for kind in ("field", "tavern")]
        for site in sites:
            self.income(site, 50)
        body, keyboard = await enterprise_top_view(self.db, -100, 10, kind="sites")
        buttons = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        for site in sites:
            self.assertIn(f'es:-100:site:{site["id"]}:week', buttons)
            detail, _ = await enterprise_site_view(self.db, -100, site["id"])
            self.assertIn("50 ₣", detail)
        for owner in range(20, 35):
            with self.db.connection:
                self.db._credit_business_income_locked(-100, owner, "2026-10-15", 1)
        data = await self.db.enterprise_leaderboard(-100, actor=34, mine=True)
        self.assertEqual((data["page"], data["own"]["place"]), (1, 16))

    async def test_owner_release_alias_reply_foreign_and_admin_compatibility(self):
        await self.db.force_enslave(-100, 30, 10)
        router = create_router(self.db)
        handler = next(h.callback for h in router.message.handlers if h.callback.__name__ == "release")
        def message(actor, text, reply=None):
            return SimpleNamespace(text=text, caption=None, entities=[], caption_entities=[],
                chat=SimpleNamespace(id=-100, type="supergroup"), from_user=SimpleNamespace(id=actor),
                reply_to_message=reply, answer=AsyncMock())
        foreign = message(20, "/освободить @u30")
        await handler(foreign)
        self.assertIsNotNone(await self.db.get_owner(-100, 30))
        self.assertIn("не ваш", foreign.answer.await_args.args[0])
        reply = SimpleNamespace(sender_chat=None, from_user=SimpleNamespace(id=30, username="u30", full_name="User 30", is_bot=False))
        own = message(10, "/освободить", reply)
        await handler(own)
        self.assertIsNone(await self.db.get_owner(-100, 30))
        self.assertTrue(RELEASE_RE.match("/отпустить @u30"))
        await self.db.force_enslave(-100, 30, 20)
        admin = message(CUSTOM_COMMAND_OWNER_ID, "/освободить @u30")
        await handler(admin)
        self.assertIsNone(await self.db.get_owner(-100, 30))
        self.assertIn("модерации", admin.answer.await_args.args[0])

    async def test_http_top_requires_signature_and_membership(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")))
        client = TestClient(TestServer(create_arena_app(self.db, bot, TOKEN)))
        await client.start_server()
        try:
            self.assertEqual((await client.get("/api/leaderboard/-100")).status, 400)
            headers = {"X-Telegram-Init-Data": signed(now=int(time.time()))}
            response = await client.get("/api/leaderboard/-100", headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["own"]["actor_id"], 10)
            response = await client.get("/api/leaderboard/-100?season=2026-99", headers=headers)
            self.assertEqual(response.status, 400)
            bot.get_chat_member.return_value = SimpleNamespace(status="left")
            # Another chat has no cached membership.
            self.assertEqual((await client.get("/api/leaderboard/-200", headers=headers)).status, 400)
        finally:
            await client.close()


class RatingMathTests(unittest.TestCase):
    def test_elo_and_completed_moscow_days(self):
        self.assertEqual(elo_delta(1000, 1000, 1), 12)
        self.assertGreater(elo_delta(1000, 1400, 1), 12)
        timestamp = int(datetime(2026, 10, 16, 0, tzinfo=MSK).timestamp())
        self.assertEqual(income_period(timestamp, "week"), ("2026-10-09", "2026-10-16"))

    def test_command_patterns(self):
        for text in ("/рейт @u20", "рейт @u20", "/рейт@GnidoBot", "/рейтинговыйбой @u20"):
            self.assertTrue(OFFER_RE.match(text)["ranked"])
        self.assertFalse(OFFER_RE.match("/бой @u20")["ranked"])
        self.assertTrue(ARENA_TOP_RE.match("/топ арены"))


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class LeaderboardClientTests(unittest.TestCase):
    run_client = client_helpers.ArenaMarketClientTests.run_client
    menu_data = client_helpers.ArenaMarketClientTests.menu_data

    def test_top_ui_archive_escaping_and_pagination(self):
        data = self.menu_data()
        data["leaderboard"] = dict(season="2026-09", current_season="2026-10", archived=True,
            own=dict(rating=1100, games=5, place=1), page=0, pages=2,
            seasons=["2026-10", "2026-09"], entries=[dict(place=1, name="<script>x</script>",
                rating=1100, wins=3, losses=2, draws=0, title="Чемпион арены")])
        body = self.run_client("page='rankings';menuScreen(input);", data)
        self.assertIn("Чемпион арены", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>x", body)
        self.assertIn("rankpage:2026-09:1", body)
        self.assertIn("rankpage:2026-10:0", body)
        self.assertIn("один рейтинг на аккаунт", body)
