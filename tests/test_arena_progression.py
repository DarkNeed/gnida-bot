import json
import logging
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from aiohttp.test_utils import TestClient, TestServer

from arena_archclasses import ARCHCLASSES
from arena_engine import xp_for_next_level
from arena_progression import choice_avatar
from arena_web import menu_view, battle_view, create_arena_app
from database import Database
import test_arena_market_client as client_tests


class ProgressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        for chat in (1, 2):
            await self.db.upsert_chat(chat, "Test")
            for user in (10, 20, 30):
                await self.db.upsert_user(chat, user, str(user), str(user))
                await self.db.arena_menu(chat, user)
        await self.db.force_enslave(1, 30, 10)
        await self.db.arena_equip_slave(1, 10, 30, True)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def level(self, level, cls="ragamuffin", user=10, personal=True, chat=1):
        table = "personal_profiles" if personal else "slave_profiles"
        self.db.connection.execute(
            f"UPDATE {table} SET level=?,class_id=?,xp=? WHERE chat_id=? AND user_id=?",
            (level, cls, sum(xp_for_next_level(n) for n in range(1, level)), chat, user),
        )
        self.db.connection.commit()

    async def profile(self, user=10, personal=True, actor=10, chat=1):
        view = await menu_view(self.db, chat, actor)
        if personal:
            return view["personal"]
        return next(p for p in view["slaves"] if p["user_id"] == user)

    async def choose(self, value, user=10, personal=True, actor=10):
        return await self.db.arena_edit_profile(1, actor, user, personal, "progression", value)

    async def test_stay_at_five_persists_and_cannot_bypass_through_old_class_action(self):
        self.level(5)
        p = await self.profile()
        choice = p["progression_choice"]
        self.assertEqual(choice["level"], 5)
        self.assertTrue(choice["options"][0]["current"])
        self.assertEqual(choice["options"][0]["id"], "stay")
        self.assertEqual(len(choice["options"]), 9)
        before = (p["xp"], p["loadout"])
        await self.choose("stay")
        p = await self.profile()
        self.assertEqual((p["xp"], p["loadout"]), before)
        self.assertIsNone(p["progression_choice"])
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 10, 10, True, "class", "jock")
        await self.db.close()
        await self.db.connect()
        self.assertIsNone((await self.profile())["progression_choice"])
        self.assertEqual((await self.profile(chat=2))["progression_level"], 0)
        self.assertEqual((await self.profile(user=30, personal=False))["progression_level"], 0)
        await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
        self.level(5)
        self.assertEqual((await self.profile())["progression_choice"]["level"], 5)

    async def test_skipped_levels_require_sequential_choices_final_stay_and_skin(self):
        self.level(20)
        await self.choose("jock")
        p = await self.profile()
        self.assertEqual(p["progression_choice"]["level"], 10)
        await self.choose("mge_bro")
        p = await self.profile()
        self.assertEqual(p["archclass"]["stage"], 10)
        self.assertEqual(p["class_avatar_url"], choice_avatar("jock", "mge_bro"))
        self.assertEqual([o["id"] for o in p["progression_choice"]["options"]], ["stay", "advance"])
        await self.choose("stay")
        p = await self.profile()
        self.assertEqual((p["progression_level"], p["archclass"]["stage"]), (20, 10))
        await self.db.close()
        await self.db.connect()
        p = await self.profile()
        self.assertIsNone(p["progression_choice"])
        self.assertEqual(p["archclass"]["stage"], 10)
        battle = await self.db.arena_wasteland(1, 10)
        side = (await battle_view(self.db, battle, 10))["state"]["sides"]["a"]
        self.assertEqual(side["archclass"]["stage"], 10)
        self.assertEqual(side["class_avatar_url"], p["class_avatar_url"])

    async def test_stay_at_ten_then_select_final_branch_at_twenty(self):
        self.level(10, "pinky")
        await self.choose("stay")
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 10, 10, True, "archclass", "pinky_tiansha")
        self.level(20, "pinky")
        p = await self.profile()
        self.assertEqual(p["progression_choice"]["level"], 20)
        self.assertEqual(len(p["progression_choice"]["options"]), 3)
        await self.choose("pinky_tiansha")
        p = await self.profile()
        self.assertEqual(p["class_name"], "Звезда Тяньган")
        self.assertEqual(p["archclass"]["stage"], 20)
        self.assertIsNone(p["progression_choice"])

    async def test_final_advance_is_explicit_and_invalid_choices_are_atomic(self):
        self.level(10, "thumb")
        for value in ("princess", "advance", {}, None):
            with self.assertRaises(ValueError):
                await self.choose(value)
            self.assertEqual((await self.profile())["archclass_id"], "")
        await self.choose("thumb_execution")
        self.level(20, "thumb")
        with self.assertRaises(ValueError):
            await self.choose("thumb_discipline")
        self.assertEqual((await self.profile())["archclass_stage"], 10)
        await self.choose("advance")
        self.assertEqual((await self.profile())["class_name"], "Соттокапо: Расстрел")
        with self.assertRaises(ValueError):
            await self.choose("advance")

    async def test_owner_wait_and_wrong_actor_personal_scope(self):
        self.level(10, "jock", user=30, personal=False)
        with patch("arena_store.utc_timestamp", return_value=100000):
            p = await self.profile(user=30, personal=False)
            stamp = p["progression_pending_at"]
            with self.assertRaises(ValueError):
                await self.choose("mge_bro", user=30, personal=False)
            with self.assertRaises(ValueError):
                await self.choose("mge_bro", user=30, personal=False, actor=20)
            await self.db.arena_edit_profile(1, 30, 30, False, "loadout", ["bum_punch"])
        await self.db.close()
        await self.db.connect()
        self.assertEqual((await self.profile(user=30, personal=False))["progression_pending_at"], stamp)
        with patch("arena_store.utc_timestamp", return_value=stamp + 48 * 3600):
            await self.choose("mge_bro", user=30, personal=False)
        self.assertEqual((await self.profile(user=30, personal=False))["archclass_id"], "mge_bro")
        self.level(10, "jock", user=20)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 10, 20, True, "progression", "mge_bro")

    async def test_unresolved_fighter_blocks_pvp_wasteland_mirror_without_spending(self):
        self.level(10, "jock")
        await self.db.credit_francs(1, 10, 100)
        await self.db.credit_francs(1, 20, 100)
        for attempt in (
            self.db.arena_offer(1, 10, 20, "personal", 50),
            self.db.arena_wasteland(1, 10),
            self.db.arena_mirror_start(1, 10),
        ):
            with self.assertRaisesRegex(ValueError, "выбор"):
                await attempt
        self.assertEqual(await self.db.franc_balance(1, 10), 100)
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_battles").fetchone()[0], 0)

    async def test_pending_migrated_duel_choice_does_not_lock_or_debit_opponent(self):
        await self.db.credit_francs(1, 10, 100)
        await self.db.credit_francs(1, 20, 100)
        row = await self.db.arena_offer(1, 10, 20, "personal", 50)
        self.level(10, "jock")
        with self.assertRaises(ValueError):
            await self.db.arena_setup(row["token"], 20, "accept")
        self.assertEqual(await self.db.franc_balance(1, 20), 100)
        self.assertFalse((await self.db.arena_get(row["token"]))["b_accepted"])
        await self.choose("mge_bro")
        accepted = await self.db.arena_setup(row["token"], 20, "accept")
        self.assertEqual(accepted["status"], "active")
        self.assertEqual(await self.db.franc_balance(1, 20), 50)

    async def test_active_battle_keeps_snapshot_and_choice_waits(self):
        offer = await self.db.arena_offer(1, 10, 20, "personal")
        row = await self.db.arena_setup(offer["token"], 20, "accept")
        self.level(10, "jock")
        with self.assertRaisesRegex(ValueError, "во время боя"):
            await self.choose("mge_bro")
        view = await battle_view(self.db, row, 10)
        self.assertEqual(view["state"]["sides"]["a"]["class_id"], "ragamuffin")
        self.assertFalse((await self.profile())["progression_choice"]["can_choose"])
        await self.db.arena_action(row["token"], 10, row["revision"], "surrender")
        await self.choose("mge_bro")

    async def test_active_mirror_choice_waits_without_breaking_run(self):
        run = await self.db.arena_mirror_start(1, 10)
        self.level(10, "jock")
        with self.assertRaisesRegex(ValueError, "во время боя"):
            await self.choose("mge_bro")
        self.assertEqual((await self.db.arena_mirror_get(run["token"], 10))["status"], "active")
        self.assertTrue((await self.profile())["progression_choice"]["busy"])

    async def test_class_scroll_clears_progression_and_preserves_custom_sprite(self):
        self.level(10, "jock")
        await self.choose("mge_bro")
        im = Image.new("RGBA", (36, 36))
        im.paste((255, 255, 255, 255), (3, 3, 33, 33))
        data = BytesIO()
        im.save(data, format="PNG")
        await self.db.arena_set_sprite(1, 10, data.getvalue(), False)
        async with self.db._lock:
            self.db._arena_add_item_locked(1, 10, "class", "cutie", "uncommon")
            self.db.connection.commit()
        item = (await self.db.arena_market_view(1, 10))["inventory"][0]["id"]
        sprite_url = (await self.profile())["sprite_url"]
        await self.db.arena_use_item(1, 10, item, 10, True, True)
        p = await self.profile()
        self.assertEqual((p["level"], p["progression_level"], p["archclass_id"]), (1, 0, ""))
        self.assertEqual(p["sprite_url"], sprite_url)

    async def test_old_delegation_clock_survives_progression_schema_migration(self):
        self.level(10, "jock", user=30, personal=False)
        self.db.connection.execute(
            "UPDATE slave_profiles SET archclass_pending_at=0 "
            "WHERE chat_id=1 AND user_id=30"
        )
        self.db.connection.commit()
        await self.db.close()
        import sqlite3

        with closing(sqlite3.connect(Path(self.temp.name) / "test.sqlite3")) as con:
            for table in ("personal_profiles", "slave_profiles"):
                for column in (
                    "progression_level", "archclass_stage",
                    "progression_pending_level", "progression_pending_at",
                ):
                    con.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            con.commit()
        await self.db.connect()
        p = await self.profile(user=30, personal=False)
        self.assertEqual(p["progression_pending_at"], 0)
        self.assertTrue(p["progression_choice"]["can_choose"])
        self.assertEqual(p["progression_choice"]["level"], 10)
        self.assertEqual((await self.db.get_owner(1, 30))["owner_id"], 10)
        await self.choose("mge_bro", user=30, personal=False)
        self.assertEqual((await self.profile(user=30, personal=False))["archclass_id"], "mge_bro")


class ProgressionClientTests(unittest.TestCase):
    def test_required_choice_has_avatar_row_and_no_confirmation(self):
        runner = client_tests.ArenaMarketClientTests()
        for level in (5, 10, 20):
            data = runner.menu_data()
            data["personal"]["progression_choice"] = dict(
                level=level, can_choose=True, busy=False,
                options=[dict(id="stay", name="Текущий класс", avatar_url=choice_avatar("jock"), current=True),
                         dict(id="mge_bro", name="Мге-браток", avatar_url=choice_avatar("jock", "mge_bro"), current=False)],
            )
            body = runner.run_client("page='personal';menuScreen(input);", data)
            self.assertIn('class="class-row"', body)
            self.assertIn('data-do="progression:stay"', body)
            self.assertIn('data-do="progression:mge_bro"', body)
            self.assertIn("/static/assets/archclasses/mge_bro.png", body)
            self.assertNotIn("Подтвердить", body)

    def test_custom_skin_has_priority_over_branch_and_base_fallback(self):
        runner = client_tests.ArenaMarketClientTests()
        url = "/sprites/" + "a" * 64 + ".png"
        profile = dict(sprite_url=url, class_avatar_url=choice_avatar("jock", "mge_bro"), sprite="jock")
        self.assertEqual(runner.run_client("out=sprite(input);", profile), url)
        profile.pop("sprite_url")
        self.assertEqual(runner.run_client("out=sprite(input);", profile), choice_avatar("jock", "mge_bro"))


class ArchclassAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_branch_asset_served_and_is_transparent(self):
        app = create_arena_app(SimpleNamespace(), SimpleNamespace(), "test-token")
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for key in ARCHCLASSES:
                response = await client.get(choice_avatar("", key))
                self.assertEqual(response.status, 200, key)
                raw = await response.read()
                self.assertLess(len(raw), 700000)
                with Image.open(BytesIO(raw)) as im:
                    self.assertEqual(im.size, (512, 768))
                    self.assertEqual(im.mode, "RGBA")
                    self.assertEqual(im.getchannel("A").getextrema(), (0, 255))
                    self.assertEqual(im.getpixel((0, 0)), (0, 0, 0, 0))
        finally:
            await client.close()
