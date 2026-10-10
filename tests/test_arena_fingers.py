import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    VISIBLE_CLASS_ALIASES,
    create_battle_state,
    effective_stat,
    resolve_skill,
    stats_for,
    unlocked_skill_ids,
)
from arena_fingers import FINGER_IDS
from arena_archprogress import skill_branch
from arena_web import menu_view, create_arena_app
from database import Database
from test_arena import signed, TOKEN


class AlwaysHit:
    def random(self):
        return 0

    def uniform(self, a, b):
        return 1

    def choice(self, choices):
        return choices[0]


class FingerEngineTests(unittest.TestCase):
    def state(self, cls, other="ragamuffin", passives=None):
        first = dict(slave_id=10, owner_id=10, class_id=cls, level=20)
        if passives is not None:
            first["passive_details"] = passives
        state = create_battle_state(
            first, dict(slave_id=20, owner_id=20, class_id=other, level=20)
        )
        # Exercise all catalog skills while keeping the public four-slot cap.
        state["sides"]["a"]["loadout"] = unlocked_skill_ids(cls, 20)
        return state

    def tap(self, state, skill, side="a"):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=AlwaysHit())

    def test_catalog_memory_cost_and_alpha_assets(self):
        for cls in FINGER_IDS:
            with self.subTest(cls=cls):
                self.assertIn(cls, VISIBLE_CLASS_ALIASES.values())
                self.assertEqual(len(unlocked_skill_ids(cls, 20)), 6)
                self.assertEqual(len(FIGHTER_CLASSES[cls].passives), 2)
                self.assertEqual(stats_for(cls, 20), stats_for(cls, 100))
                state = self.state(cls)
                self.assertEqual(len(state["sides"]["a"]["passive_details"]), 2)
                for skill in BUILTIN_SKILLS.values():
                    if skill.class_id != cls or not skill.cost or skill_branch(skill):
                        continue
                    state = self.state(cls, passives=[])
                    self.tap(state, skill.skill_id)
                    self.assertEqual(state["sides"]["a"]["resource"], 100 - skill.cost)
                    self.assertEqual(state["active_side"], "b")
                    self.assertEqual(state["flow"], "single_click")
                path = (
                    Path(__file__).resolve().parents[1]
                    / "webapp"
                    / "assets"
                    / (cls + ".png")
                )
                with Image.open(path) as img:
                    self.assertEqual(img.mode, "RGBA")
                    self.assertEqual(img.getchannel("A").getextrema()[0], 0)
                    self.assertGreater(img.getchannel("A").getextrema()[1], 200)

    def test_thumb_chain_consumed_by_shot_and_repetition_resets(self):
        state = self.state("thumb")
        self.tap(state, "bayonet")
        self.tap(state, "bum_punch")
        self.assertEqual(state["sides"]["a"]["mechanics"]["order"], 2)
        boosted = self.tap(state, "warning_shot")["damage"]
        self.assertEqual(state["sides"]["a"]["mechanics"]["order"], 0)
        plain = self.tap(self.state("thumb", passives=[]), "warning_shot")["damage"]
        self.assertGreater(boosted, plain)
        self.tap(state, "bayonet")
        self.tap(state, "bayonet")
        self.assertEqual(state["sides"]["a"]["mechanics"]["order"], 0)
        actor = state["sides"]["a"]
        self.assertAlmostEqual(
            effective_stat(actor, "physical_defense"),
            actor["stats"]["physical_defense"] * 1.15,
        )
        actor["hp"] = 1
        self.assertEqual(
            effective_stat(actor, "physical_defense"),
            actor["stats"]["physical_defense"],
        )

    def test_index_prescript_refund_and_other_cooldown(self):
        state = self.state("index")
        actor = state["sides"]["a"]
        actor["resource"] = 10
        self.tap(state, "receive_prescript")
        self.assertEqual(actor["resource"], 45)
        selected = actor["mechanics"]["prescript"]
        self.assertIn(selected, actor["loadout"])
        actor["cooldowns"]["unrelated"] = 3
        event = self.tap(state, selected)
        self.assertIn("предписание исполнено", event["text"])
        self.assertEqual(actor["resource"], 55 - BUILTIN_SKILLS[selected].cost)
        self.assertEqual(actor["cooldowns"]["unrelated"], 1)
        self.assertNotIn("prescript", actor["mechanics"])

    def test_middle_grudges_and_low_health_defense(self):
        state = self.state("middle")
        actor = state["sides"]["a"]
        for _ in range(2):
            self.tap(state, "bum_punch", "b")
        self.assertEqual(actor["mechanics"]["grudge"], 2)
        damage = self.tap(state, "answer_for_it")["damage"]
        plain = self.tap(self.state("middle", passives=[]), "answer_for_it")["damage"]
        self.assertGreater(damage, plain)
        self.assertEqual(actor["mechanics"]["grudge"], 0)
        actor["hp"] = 1
        self.assertAlmostEqual(
            effective_stat(actor, "magic_defense"),
            actor["stats"]["magic_defense"] * 1.25,
        )

    def test_ring_bleed_can_finish_and_muse_only_new_effect(self):
        state = self.state("ring")
        actor, target = state["sides"]["a"], state["sides"]["b"]
        event = self.tap(state, "red_etude")
        self.assertEqual(event["bleed_damage"], 3)
        self.assertEqual(actor["resource"], 88)
        actor["cooldowns"].clear()
        self.tap(state, "red_etude")
        self.assertEqual(actor["resource"], 68)  # refreshing isn't a new type
        target["hp"] = 2
        actor["cooldowns"].clear()
        self.tap(state, "unfinished_portrait")
        self.assertTrue(state["finished"])
        self.assertEqual(state["winner"], "a")
        self.assertEqual(target["hp"], 0)

    def test_pinky_focus_critical_retained_and_foreign_skill_no_traits(self):
        state = self.state("pinky")
        actor = state["sides"]["a"]
        self.tap(state, "calm_breath")
        self.assertEqual(actor["mechanics"]["focus"], 2)
        event = self.tap(state, "silent_cut")
        self.assertTrue(event["critical"])
        self.assertEqual(actor["mechanics"]["focus"], 3)
        foreign = self.state("ragamuffin", passives=[])
        foreign["sides"]["a"]["loadout"].append("calm_breath")
        foreign["sides"]["a"]["resource"] = 10
        self.tap(foreign, "calm_breath")
        self.assertEqual(foreign["sides"]["a"]["resource"], 45)
        self.assertNotIn("focus", foreign["sides"]["a"]["mechanics"])

    def test_state_round_trip_and_effects_expire(self):
        state = self.state("ring")
        self.tap(state, "red_etude")
        state = json.loads(json.dumps(state))
        for _ in range(3):
            self.tap(state, "bum_punch", "b")
        self.assertFalse(
            any(e["kind"] == "bleed" for e in state["sides"]["b"]["effects"])
        )

    def test_critical_miss_does_not_consume_focus(self):
        class Miss:
            def __init__(self):
                self.rolls = iter((0, 1))

            def random(self):
                return next(self.rolls)

        state = self.state("pinky")
        actor = state["sides"]["a"]
        actor["mechanics"] = {"focus": 2}
        event = resolve_skill(state, "a", "silent_cut", rng=Miss())
        self.assertFalse(event["hit"])
        self.assertFalse(event["critical"])
        self.assertEqual(actor["mechanics"]["focus"], 2)

    def test_forgetting_class_passive_disables_mechanic(self):
        state = self.state("middle", passives=[])
        self.tap(state, "bum_punch", "b")
        self.assertNotIn("grudge", state["sides"]["a"].get("mechanics", {}))


class FingerStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        for user in (10, 20, 30):
            await self.db.upsert_user(1, user, str(user), str(user))
        await self.db.force_enslave(1, 30, 10)
        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(
                    status="member", user=SimpleNamespace(is_bot=False)
                )
            )
        )

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def level(self, user=10, personal=True):
        await self.db.arena_menu(1, user)
        table = "personal_profiles" if personal else "slave_profiles"
        self.db.connection.execute(
            f"UPDATE {table} SET level=20,xp=1234,skills_pending_at=0 WHERE chat_id=1 AND user_id=?",
            (user,),
        )
        self.db.connection.commit()

    async def test_all_classes_menu_passives_and_shop(self):
        for cls in FINGER_IDS:
            await self.level()
            await self.db.arena_edit_profile(1, 10, 10, True, "class", cls)
            menu = await menu_view(self.db, 1, 10)
            p = menu["personal"]
            self.assertEqual(p["sprite"], cls)
            self.assertEqual(len(p["skills"]), 6)
            self.assertEqual(len(p["passives"]), 2)
            self.assertEqual(len(p["passive_loadout"]), 2)
            self.assertTrue(FINGER_IDS.issubset({c["id"] for c in p["classes"]}))
            self.assertIn(("class", cls), self.db._arena_shop_catalog_locked())
            await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)

    @patch("arena_store.utc_timestamp")
    async def test_reset_preserves_property_and_other_profiles(self, clock):
        # A real second of passive accrual must not look like a reset side effect.
        clock.return_value = int(time.time())
        await self.level()
        await self.db.arena_edit_profile(1, 10, 10, True, "class", "thumb")
        self.db._arena_add_item_locked(1, 10, "candy", "experience", "common", 2)
        self.db._add_francs_locked(1, 10, 345)
        await self.db.grant_owner_xp(1, 10, 99)
        await self.db.arena_set_sprite(1, 10, b"test-sprite", False)
        before_owner = await self.db.get_owner_profile(1, 10)
        self.db.connection.execute(
            "INSERT INTO arena_learned VALUES(1,10,1,'skill','meow')"
        )
        self.db.connection.commit()
        inventory = (await self.db.arena_market_view(1, 10))["inventory"]
        await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
        menu = await menu_view(self.db, 1, 10)
        p = menu["personal"]
        self.assertEqual((p["class_id"], p["level"], p["xp"]), ("ragamuffin", 1, 0))
        self.assertEqual(p["known_skills"], ["bum_punch"])
        self.assertEqual(p["passives"], [])
        self.assertTrue(p["sprite_url"])
        self.assertEqual(menu["balance"], 345)
        self.assertEqual(menu["inventory"], inventory)
        self.assertEqual(await self.db.get_owner_profile(1, 10), before_owner)
        self.assertEqual(len(menu["slaves"]), 1)
        await self.level()
        self.assertNotIn(
            "meow", (await menu_view(self.db, 1, 10))["personal"]["known_skills"]
        )

    async def test_reset_strict_confirmation_and_permission(self):
        await self.level()
        for confirm in (False, None, "true", 1):
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(
                    1, 10, 10, True, "reset_class", confirm
                )
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 20, 10, True, "reset_class", True)
        await self.level(30, False)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 20, 30, False, "reset_class", True)
        await self.db.arena_edit_profile(1, 10, 30, False, "reset_class", True)
        self.assertEqual((await self.db.get_slave_profile(1, 30))["level"], 1)

    async def test_reset_busy_and_http_endpoint(self):
        await self.level()
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        try:
            headers = {"X-Telegram-Init-Data": signed(now=int(time.time()))}
            response = await client.post(
                "/api/menu/1",
                headers=headers,
                json=dict(action="reset_class", user=10, personal=True, value=True),
            )
            self.assertEqual(response.status, 200)
            self.assertIn("Класс сброшен", (await response.json())["notice"])
            await self.db.arena_wasteland(1, 10, 10, personal=True)
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
        finally:
            await client.close()
