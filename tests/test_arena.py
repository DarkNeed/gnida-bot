import asyncio
import hashlib
import hmac
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode
from aiohttp.test_utils import TestClient, TestServer
from arena_engine import (
    create_battle_state,
    resolve_skill,
    BUILTIN_SKILLS,
    stats_for,
    level_from_total_xp,
    Skill,
)
from arena_web import validate_init_data, create_arena_app, battle_view, menu_view
from database import Database
from handlers.arena import OFFER_RE, ArenaPublisher, create_arena_router

TOKEN = "123456:unit-test"


def signed(user=10, now=1000, **extra):
    data = {"auth_date": str(now), "user": json.dumps({"id": user}), **extra}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret,
        "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(data)


class ArenaAuthTests(unittest.TestCase):
    def test_valid_signature(self):
        self.assertEqual(validate_init_data(signed(), TOKEN, 1000)["id"], 10)

    def test_bad_signature(self):
        with self.assertRaises(ValueError):
            validate_init_data(signed().replace("1000", "1001"), TOKEN, 1000)

    def test_old_and_future(self):
        for now in (90000, 900):
            with self.assertRaises(ValueError):
                validate_init_data(signed(), TOKEN, now)

    def test_duplicates(self):
        with self.assertRaises(ValueError):
            validate_init_data(signed() + "&auth_date=1000", TOKEN, 1000)

    def test_commands(self):
        for text in (
            "/бой",
            "/бой @username",
            "я выбираю тебя @user",
            "Я выбираю тебя @user",
            "/дуэль @user 50",
            "!бой",
        ):
            self.assertIsNotNone(OFFER_RE.match(text), text)
        self.assertIsNone(OFFER_RE.match("/бойня @user"))

    def test_personal_battle_commands(self):
        for text in (
            "/бой",
            "!бой @user",
            "бой @user",
            "/бой@GnidoBot @user 50",
            "/дуэль @user",
        ):
            match = OFFER_RE.match(text)
            self.assertTrue(match["personal"], text)
            self.assertFalse(match["slave"], text)
        for text in ("/бой рабами @user", "!бой рабы @user", "Я выбираю тебя @user"):
            match = OFFER_RE.match(text)
            self.assertTrue(match["slave"], text)
            self.assertEqual(match["payload"], "@user")


class ArenaEngineTests(unittest.TestCase):
    def state(self, cls="ragamuffin", level=1):
        source = dict(
            slave_id=10,
            owner_id=1,
            class_id=cls,
            level=level,
            controlled=False,
            loadout=None,
        )
        return create_battle_state(source, dict(source, slave_id=20, owner_id=2))

    def test_one_click(self):
        state = self.state()
        event = resolve_skill(state, "a", "bum_punch", rng=random.Random(1))
        self.assertLess(state["sides"]["b"]["hp"], 20)
        self.assertEqual(state["active_side"], "b")
        self.assertEqual(state["flow"], "single_click")
        self.assertNotIn("pending_action", state)
        self.assertTrue(event["hit"])
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "bum_punch")

    def test_control_all_stats(self):
        base = stats_for("jock", 5)
        controlled = stats_for("jock", 5, True)
        for key in base:
            self.assertLessEqual(controlled[key], base[key], key)
        self.assertEqual(controlled["max_hp"], round(base["max_hp"] * 0.8))

    def test_buffs_and_cooldown(self):
        state = self.state("cutie", 7)
        state["sides"]["a"]["loadout"] = ["posing", "bum_punch"]
        resolve_skill(state, "a", "posing", rng=random.Random(0))
        self.assertEqual(state["sides"]["a"]["effects"][0]["duration"], 3)
        self.assertEqual(state["sides"]["a"]["cooldowns"]["posing"], 3)
        resolve_skill(state, "b", "bum_punch", rng=random.Random(0))
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "posing")
        resolve_skill(state, "a", "bum_punch", rng=random.Random(0))
        self.assertEqual(state["sides"]["a"]["effects"][0]["duration"], 2)

    def test_insufficient_and_not_equipped(self):
        state = self.state("nerd", 9)
        state["sides"]["a"]["resource"] = 0
        state["sides"]["a"]["loadout"] = ["mother_joke"]
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "mother_joke")
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "meow")

    def test_xp(self):
        self.assertEqual(level_from_total_xp(72), 5)

    def test_skill_cost_is_not_refunded_even_in_legacy_battle(self):
        state = self.state(level=3)
        side = state["sides"]["a"]
        side["stats"]["resource_regen"] = 15  # Old persisted battles.
        event = resolve_skill(state, "a", "dust_in_eyes", rng=random.Random(1))
        self.assertEqual(side["resource"], 80)
        self.assertEqual(
            event["before"]["a"]["resource"] - event["after"]["a"]["resource"], 20
        )

    def test_repeated_skill_costs_and_explicit_recovery(self):
        from dataclasses import replace

        state = self.state("nerd", 9)
        state["sides"]["a"]["loadout"] = ["dust_in_eyes", "go_to_store"]
        skills = dict(
            BUILTIN_SKILLS,
            dust_in_eyes=replace(BUILTIN_SKILLS["dust_in_eyes"], cooldown=0),
        )
        for expected in (80, 68, 56, 44, 32, 20, 8):
            resolve_skill(state, "a", "dust_in_eyes", skills, rng=random.Random(1))
            self.assertEqual(state["sides"]["a"]["resource"], expected)
            resolve_skill(state, "b", "dust_in_eyes", skills, rng=random.Random(1))
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "dust_in_eyes", skills)
        self.assertEqual(state["sides"]["a"]["resource"], 16)
        resolve_skill(state, "a", "go_to_store", skills, rng=random.Random(1))
        self.assertEqual(state["sides"]["a"]["resource"], 61)

    def test_miss_still_consumes_full_energy(self):
        state = self.state(level=3)
        event = resolve_skill(state, "a", "dust_in_eyes", rng=random.Random(0))
        self.assertFalse(event["hit"])
        self.assertEqual(state["sides"]["a"]["resource"], 80)


class ArenaStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_stake_display_matches_credit(self):
        for user in (10, 20):
            self.db._add_francs_locked(1, user, 100)
        self.db.connection.commit()
        row = await self.duel(1)
        row = await self.db.arena_action(row["token"], 10, row["revision"], "surrender")
        self.assertEqual(json.loads(row["state_json"])["payout"], 2)
        self.assertEqual(self.balance(20), 101)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "bot.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Чат")
        for user in (10, 20, 30, 40, 50):
            await self.db.upsert_user(1, user, str(user), "User " + str(user))
        await self.db.force_enslave(1, 30, 10)
        await self.db.force_enslave(1, 40, 20)
        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(
                    status="member", user=SimpleNamespace(is_bot=False)
                )
            )
        )

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def balance(self, user):
        r = self.db.connection.execute(
            "SELECT balance FROM franc_balances WHERE chat_id=1 AND user_id=?", (user,)
        ).fetchone()
        return r["balance"] if r else 0

    async def duel(self, stake=0):
        r = await self.db.arena_offer(1, 10, 20, "personal", stake)
        await self.db.arena_set_message(r["token"], 1)
        with patch("arena_store.random.SystemRandom") as rng:
            rng.return_value.choice.return_value = "a"
            return await self.db.arena_setup(r["token"], 20, "accept")

    async def test_menu_and_profile_independence(self):
        await self.db.grant_slave_xp(1, 10, 20)
        data = await menu_view(self.db, 1, 10)
        self.assertEqual(data["personal"]["level"], 1)
        self.assertEqual(data["slaves"], [])
        self.assertEqual(data["owner"], {})

    async def test_personal_duel_needs_no_slaves(self):
        await self.db.release_all_slaves(1, 10)
        await self.db.release_all_slaves(1, 20)
        row = await self.duel()
        self.assertEqual(row["status"], "active")
        state = json.loads(row["state_json"])
        self.assertEqual(state["sides"]["a"]["slave_id"], 10)
        self.assertEqual(state["sides"]["a"]["controller_id"], 10)

    async def test_personal_command_handler_reply_and_tag_without_slaves(self):
        from aiogram.types import User

        await self.db.release_all_slaves(1, 10)
        await self.db.release_all_slaves(1, 20)
        publisher = ArenaPublisher(self.db, self.bot, "GnidoBot")
        router = create_arena_router(self.db, self.bot, "GnidoBot", True, publisher)
        handler = next(
            h.callback
            for h in router.message.handlers
            if h.callback.__name__ == "battle_offer"
        )
        target = User(id=20, is_bot=False, first_name="User 20", username="20")
        for text, reply in (
            ("/бой", SimpleNamespace(from_user=target, sender_chat=None)),
            ("!бой @20", None),
        ):
            message = SimpleNamespace(
                from_user=User(id=10, is_bot=False, first_name="User 10"),
                chat=SimpleNamespace(id=1, type="supergroup"),
                text=text,
                caption=None,
                reply_to_message=reply,
                answer=AsyncMock(return_value=SimpleNamespace(message_id=99)),
            )
            await handler(message)
            row = dict(
                self.db.connection.execute(
                    "SELECT * FROM arena_battles ORDER BY id DESC LIMIT 1"
                ).fetchone()
            )
            self.assertEqual(row["mode"], "personal")
            self.assertEqual(row["a_fighter"], 10)
            self.assertEqual(row["b_fighter"], 20)
            self.assertEqual(row["message_id"], 99)
            await self.db.arena_setup(row["token"], 10, "cancel")












    async def test_view_spectator(self):
        r = await self.db.arena_offer(1, 10, 20)
        view = await battle_view(self.db, r, 50)
        self.assertIsNone(view["own_side"])
        self.assertEqual(view["available"], [])
        view = await battle_view(self.db, r, 10)
        self.assertEqual(view["available"], [])

    async def test_stale_revision_and_outsider(self):
        r = await self.duel()
        with self.assertRaises(ValueError):
            await self.db.arena_action(r["token"], 50, r["revision"], "bum_punch")
        await self.db.arena_action(r["token"], 10, r["revision"], "bum_punch")
        with self.assertRaises(ValueError):
            await self.db.arena_action(r["token"], 10, r["revision"], "bum_punch")

    async def test_stake_accept_once_refund_once(self):
        for user in (10, 20):
            self.db._add_francs_locked(1, user, 100)
        self.db.connection.commit()
        r = await self.db.arena_offer(1, 10, 20, "personal", 50)
        self.assertEqual(self.balance(10), 50)
        self.assertEqual(self.balance(20), 100)
        await self.db.arena_setup(r["token"], 20, "accept")
        with self.assertRaises(ValueError):
            await self.db.arena_setup(r["token"], 20, "accept")
        self.assertEqual(self.balance(20), 50)
        await self.db.arena_set_module(1, 10, "arena", False, 0)
        self.assertEqual(self.balance(10), 100)
        self.assertEqual(self.balance(20), 100)
        await self.db.arena_set_module(1, 10, "arena", False, 1)
        self.assertEqual(self.balance(10), 100)

    async def test_not_enough_stake(self):
        with self.assertRaises(ValueError):
            await self.db.arena_offer(1, 10, 20, "personal", 50)
        self.assertEqual((await self.db.arena_menu(1, 10))["active"], [])

    async def test_finish_payout_and_no_slave_transfer(self):
        for user in (10, 20):
            self.db._add_francs_locked(1, user, 100)
        self.db.connection.commit()
        r = await self.duel(50)
        st = json.loads(r["state_json"])
        st["sides"]["b"]["hp"] = 1
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(st), r["token"]),
        )
        self.db.connection.commit()
        with patch("arena_engine.random.SystemRandom", return_value=random.Random(1)):
            r = await self.db.arena_action(r["token"], 10, r["revision"], "bum_punch")
        self.assertEqual(r["status"], "finished")
        self.assertEqual(self.balance(10), 140)
        self.assertEqual((await self.db.get_owner(1, 40))["owner_id"], 20)
        with self.assertRaises(ValueError):
            await self.db.arena_action(r["token"], 10, r["revision"], "bum_punch")
        self.assertEqual(self.balance(10), 140)

    async def test_restart_and_expiry(self):
        r = await self.db.arena_offer(1, 10, 20, "personal")
        await self.db.arena_set_message(r["token"], 1)
        await self.db.close()
        self.db = Database(Path(self.temp.name) / "bot.sqlite3")
        await self.db.connect()
        self.assertEqual((await self.db.arena_get(r["token"]))["status"], "pending")
        with patch("arena_store.utc_timestamp", return_value=r["deadline"] + 1):
            await self.db.arena_expire()
        self.assertEqual((await self.db.arena_get(r["token"]))["status"], "expired")
        self.assertEqual(await self.db.arena_expire(), [])


    async def test_wasteland_bot_moves_and_reward(self):
        r = await self.db.arena_wasteland(1, 10)
        st = json.loads(r["state_json"])
        st["sides"]["b"]["hp"] = 100
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(st), r["token"]),
        )
        self.db.connection.commit()
        r = await self.db.arena_action(r["token"], 10, r["revision"], "bum_punch")
        st = json.loads(r["state_json"])
        self.assertEqual(len(st["log"]), 2)
        self.assertEqual(st["active_side"], "a")

    async def test_class_selection_personal_and_slave_rejected(self):
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, 72)
        self.db.connection.commit()
        await self.db.arena_edit_profile(1, 10, 10, True, "class", "nerd")
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["class_id"], "nerd")
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 10, 30, False, "class", "jock")

    async def test_http_auth_membership_and_assets(self):
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        try:
            response = await client.get("/health")
            self.assertEqual(response.status, 200)
            response = await client.get("/api/menu/1")
            self.assertEqual(response.status, 400)
            import time

            headers = {"X-Telegram-Init-Data": signed(now=int(time.time()))}
            response = await client.get("/api/menu/1", headers=headers)
            self.assertEqual(response.status, 200, await response.text())
            self.bot.get_chat_member.return_value = SimpleNamespace(status="left")
            response = await client.post(
                "/api/menu/1", headers=headers, json={"action": "wasteland"}
            )
            self.assertEqual(response.status, 400)
            response = await client.get("/static/client.js")
            self.assertIn("javascript", response.headers["Content-Type"])
            self.assertEqual(response.status, 200)
            response = await client.get("/static/assets/cutie.png")
            self.assertEqual(response.status, 200)
        finally:
            await client.close()

    async def test_concurrent_moves_only_one_succeeds(self):
        r = await self.duel()
        responses = await asyncio.gather(
            *(
                self.db.arena_action(r["token"], 10, r["revision"], "bum_punch")
                for _ in range(2)
            ),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(x, ValueError) for x in responses), 1)
        self.assertEqual(
            json.loads((await self.db.arena_get(r["token"]))["state_json"])["turn"], 2
        )

    async def test_orphan_refunds(self):
        self.db._add_francs_locked(1, 10, 100)
        self.db._add_francs_locked(1, 20, 100)
        self.db.connection.commit()
        r = await self.db.arena_offer(1, 10, 20, "personal", 50)
        with patch("arena_store.utc_timestamp", return_value=r["created_at"] + 61):
            await self.db.arena_expire()
        self.assertEqual((await self.db.arena_get(r["token"]))["status"], "cancelled")
        self.assertEqual(self.balance(10), 100)




    async def test_http_outsider_write_and_admin_gate(self):
        import time

        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        try:
            headers = {"X-Telegram-Init-Data": signed(50, int(time.time()))}
            response = await client.post(
                "/api/menu/1",
                headers=headers,
                json={
                    "action": "create_content",
                    "type": "skill",
                    "id": "bad",
                    "definition": {"name": "BAD"},
                },
            )
            self.assertEqual(response.status, 400)
            r = await self.duel()
            response = await client.post(
                "/api/battle/" + r["token"],
                headers=headers,
                json={
                    "action": "skill",
                    "revision": r["revision"],
                    "skill": "bum_punch",
                },
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(
                (await self.db.arena_get(r["token"]))["revision"], r["revision"]
            )
        finally:
            await client.close()
