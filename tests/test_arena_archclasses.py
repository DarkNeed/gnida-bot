import asyncio
import copy
import json
import logging
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from arena_archclasses import ARCHCLASSES, branch_options, archclass_view
from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    create_battle_state,
    effective_skill,
    effective_stat,
    fighter_xp_limit,
    resolve_skill,
    skip_turn,
    use_healing_potion,
    VISIBLE_CLASS_ALIASES,
)
from arena_fingers import combat_modifiers, negative_kinds
from arena_evolution import evolution_info
from arena_web import menu_view, battle_view, create_arena_app
from arena_wasteland import enemy_source
from database import Database
from test_arena_rebalance import FixedRoll
import test_arena_market_client as client_tests
from test_arena import signed, TOKEN


class ArchEngineTests(unittest.TestCase):
    SKILLS = dict(
        femboy="air_kiss",
        princess="posing",
        gachi_actor="clench",
        mge_bro="butt_peak",
        programmer="charging",
        hacker="doxxing",
        thumb_discipline="warning_shot",
        thumb_execution="senior_verdict",
        index_proxy="last_line",
        index_messenger="receive_prescript",
        middle_guardian="grit_teeth",
        middle_revenge="whole_family",
        ring_pointillist="red_etude",
        ring_fauvist="last_stroke",
        pinky_dihui="moon_arc",
        pinky_tiansha="falling_star",
    )

    def state(self, branch="programmer", level=10):
        cls = ARCHCLASSES[branch]["class_id"]
        state = create_battle_state(
            dict(
                slave_id=10, owner_id=10, class_id=cls, level=level, archclass_id=branch
            ),
            dict(slave_id=20, owner_id=20, class_id="jock", level=20),
        )
        for side in state["sides"].values():
            side["loadout"] = list(BUILTIN_SKILLS)
            side["hp"] = 10000
        return state

    def tap(self, state, skill, side="a", roll=0):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=FixedRoll(roll))

    def prepare(self, state):
        a, b = state["sides"].values()
        a["mechanics"] = dict(order=3, grudge=3, focus=3, prescript="last_line")
        b["effects"] += [
            dict(id="adoration", kind="damage_pct", value=-0.4, duration=3),
            dict(id="dust", kind="accuracy_flat", value=-10, duration=3),
            dict(id="doxxing_magic", kind="magic_defense_pct", value=-0.2, duration=3),
        ]

    def test_all_sixteen_branches_native_only_and_two_stages(self):
        self.assertEqual(len(ARCHCLASSES), 16)
        for key, sid in self.SKILLS.items():
            for level in (10, 20):
                with self.subTest(branch=key, level=level):
                    state = self.state(key, level)
                    self.prepare(state)
                    a = state["sides"]["a"]
                    variant = effective_skill(state, "a", sid)
                    self.assertNotEqual(variant.name, BUILTIN_SKILLS[sid].name)
                    self.assertEqual(variant.skill_id, sid)
                    self.assertEqual(variant.cooldown, BUILTIN_SKILLS[sid].cooldown)
                    self.assertEqual(archclass_view(a)["stage"], level)
                    before = copy.deepcopy(state)
                    a["resource"] = max(0, variant.cost - 1)
                    if variant.cost:
                        failed = copy.deepcopy(state)
                        with self.assertRaises(ValueError):
                            self.tap(state, sid)
                        self.assertEqual(state, failed)
                    state = before
                    self.tap(state, sid)
                    self.assertGreaterEqual(state["sides"]["a"]["resource"], 0)
                    self.assertLessEqual(len(state["sides"]["a"]["passive_details"]), 2)
            state = self.state(key, 9)
            self.prepare(state)
            self.assertIs(effective_skill(state, "a", sid), BUILTIN_SKILLS[sid])
            state["sides"]["a"].update(class_id="ragamuffin", level=20)
            self.assertIs(effective_skill(state, "a", sid), BUILTIN_SKILLS[sid])

    def test_wrong_branch_and_old_battle_are_harmless(self):
        state = self.state("programmer")
        a = state["sides"]["a"]
        a["archclass_id"] = "princess"
        self.assertIsNone(archclass_view(a))
        self.assertIs(
            effective_skill(state, "a", "charging"), BUILTIN_SKILLS["charging"]
        )
        a.pop("archclass_id")
        self.assertIs(
            effective_skill(state, "a", "charging"), BUILTIN_SKILLS["charging"]
        )

    def test_programmer_actual_cost_cooldown_discount_consumed_on_miss(self):
        for level, expected in ((10, 10), (20, 7)):
            state = self.state("programmer", level)
            a = state["sides"]["a"]
            a["cooldowns"]["doxxing"] = 3
            self.tap(state, "charging")
            self.assertEqual(a["cooldowns"]["doxxing"], 1)
            self.assertEqual(a["cooldowns"]["charging"], 3)
            self.assertEqual(effective_skill(state, "a", "humiliate").cost, expected)
            before = a["resource"]
            self.tap(state, "humiliate", roll=0.99)
            self.assertEqual(a["resource"], before - expected)
            self.assertEqual(effective_skill(state, "a", "humiliate").cost, 15)
            self.assertEqual(effective_skill(state, "a", "bum_punch").cost, 0)

    def test_programmer_discount_composes_with_native_evolution(self):
        state = self.state("programmer", 20)
        self.prepare(state)
        self.tap(state, "charging")
        skill = effective_skill(state, "a", "humiliate")
        self.assertEqual((skill.power, skill.cost), (15, 17))
        self.assertIn("Полный деанон", skill.name)

    def test_evolution_tooltip_matches_the_current_condition(self):
        state = self.state("programmer", 20)
        self.prepare(state)
        a, b = state["sides"].values()
        info = evolution_info(BUILTIN_SKILLS["humiliate"], "nerd", a, b, 0)
        self.assertFalse(info["specialization"])
        self.assertEqual(info["name"], "Полный деанон")
        self.assertIn("Магической защиты".casefold(), info["condition"].casefold())
        self.tap(state, "charging")
        info = evolution_info(BUILTIN_SKILLS["humiliate"], "nerd", a, b, 1)
        self.assertTrue(info["specialization"])
        self.assertIn("цена 17", info["description"])

    def test_princess_guard_refreshes_and_expires(self):
        state = self.state("princess")
        a = state["sides"]["a"]
        self.tap(state, "posing")
        self.assertAlmostEqual(
            effective_stat(a, "magic_defense"), a["stats"]["magic_defense"] * 1.2
        )
        self.tap(state, "bum_punch")
        self.assertEqual(
            effective_stat(a, "magic_defense"), a["stats"]["magic_defense"]
        )
        self.assertFalse(any(e["id"].startswith("princess_") for e in a["effects"]))

    def test_mge_real_price_and_risk(self):
        state = self.state("mge_bro", 20)
        a = state["sides"]["a"]
        self.tap(state, "butt_peak")
        self.assertEqual(a["resource"], 45)
        self.assertAlmostEqual(
            effective_stat(a, "physical_defense"), a["stats"]["physical_defense"] * 0.8
        )

    def test_hacker_steals_only_real_resource(self):
        state = self.state("hacker", 20)
        a, b = state["sides"].values()
        b["resource"] = 3
        self.tap(state, "doxxing")
        self.assertEqual((a["resource"], b["resource"]), (71, 0))

    def test_thumb_no_double_charge_bonus(self):
        state = self.state("thumb_execution", 20)
        self.prepare(state)
        a, b = state["sides"].values()
        skill = effective_skill(state, "a", "senior_verdict")
        self.assertEqual(skill.pierce, 0.6)
        self.assertEqual(combat_modifiers(a, b, skill, FixedRoll())[1], 0)
        self.tap(state, "senior_verdict", roll=0.99)
        self.assertEqual(a["mechanics"]["order"], 0)

    def test_middle_revenge_replaces_guard_instead_of_stacking(self):
        state = self.state("middle_revenge")
        self.prepare(state)
        self.tap(state, "whole_family")
        a = state["sides"]["a"]
        self.assertEqual(a["mechanics"]["grudge"], 0)
        self.assertTrue(any(e["id"].startswith("revenge_risk") for e in a["effects"]))
        self.assertFalse(any(e["id"].startswith("revenge_guard") for e in a["effects"]))

    def test_ring_consumes_negatives_on_hit_only(self):
        for roll in (0, 0.99):
            state = self.state("ring_fauvist", 20)
            self.prepare(state)
            b = state["sides"]["b"]
            self.tap(state, "last_stroke", roll=roll)
            self.assertEqual(bool(negative_kinds(b)), bool(roll))

    def test_ring_does_not_remove_buffs_or_equipped_passives(self):
        state = self.state("ring_fauvist", 20)
        self.prepare(state)
        b = state["sides"]["b"]
        b["effects"].extend(
            [
                dict(
                    id="positive_guard", kind="magic_defense_pct", value=0.3, duration=3
                ),
                dict(id="permanent", kind="accuracy_flat", value=-5, duration=1000000),
            ]
        )
        self.tap(state, "last_stroke")
        self.assertFalse(negative_kinds(b))
        self.assertEqual(
            {e["id"] for e in b["effects"]}, {"positive_guard", "permanent"}
        )

    def test_pointillist_refreshes_one_bleed_instead_of_stacking(self):
        state = self.state("ring_pointillist", 20)
        self.tap(state, "first_stroke")
        self.tap(state, "red_etude")
        bleeds = [e for e in state["sides"]["b"]["effects"] if e["kind"] == "bleed"]
        self.assertEqual(len(bleeds), 1)
        self.assertEqual(bleeds[0]["value"], 5)

    def test_messenger_penalty_clamped_at_zero_and_stun_consumes_order(self):
        state = self.state("index_messenger", 20)
        b = state["sides"]["b"]
        b["resource"] = 3
        b["effects"].append(dict(id="stun", kind="stun", value=1, duration=1))
        self.tap(state, "receive_prescript")
        self.assertEqual(b["resource"], 0)
        self.assertNotIn("enemy_prescript", b["mechanics"])
        self.assertEqual(state["active_side"], "a")

    def test_pinky_precision_no_crit_and_both_paths_spend_focus_on_miss(self):
        for branch, sid in (
            ("pinky_dihui", "moon_arc"),
            ("pinky_tiansha", "falling_star"),
        ):
            for roll in (0, 0.99):
                state = self.state(branch, 20)
                self.prepare(state)
                event = self.tap(state, sid, roll=roll)
                self.assertEqual(state["sides"]["a"]["mechanics"]["focus"], 0)
                if branch == "pinky_dihui":
                    self.assertFalse(event["critical"])

    def test_messenger_obey_violate_timeout_and_potion(self):
        for level, penalty in ((10, 8), (20, 12)):
            state = self.state("index_messenger", level)
            self.tap(state, "receive_prescript")
            b = state["sides"]["b"]
            marked = b["mechanics"]["enemy_prescript"]["skill_id"]
            b["hp"] = 1
            use_healing_potion(state, "b")
            self.assertIn("enemy_prescript", b["mechanics"])
            event = self.tap(state, marked, "b")
            self.assertIn("предписание противника исполнено", event["text"])
            self.assertNotIn("enemy_prescript", b["mechanics"])
            state = self.state("index_messenger", level)
            self.tap(state, "receive_prescript")
            b = state["sides"]["b"]
            before = b["resource"]
            skip_turn(state)
            self.assertEqual(b["resource"], before - penalty)
            self.assertNotIn("enemy_prescript", b["mechanics"])
            state = self.state("index_messenger", level)
            self.tap(state, "receive_prescript")
            b = state["sides"]["b"]
            before = b["resource"]
            event = self.tap(state, "go_to_store", "b")
            # Restoring energy happens after the bounded penalty.
            self.assertIn("нарушено", event["text"])
            self.assertGreaterEqual(b["resource"], before - penalty)

    def test_messenger_never_marks_unaffordable_evolved_skill(self):
        state = self.state("index_messenger")
        b = state["sides"]["b"]
        b["resource"] = 10
        b["loadout"] = ["smack"]
        b["effects"].append(
            dict(id="evolution_prepared", kind="prepared_attack", value=0, duration=2)
        )
        self.tap(state, "receive_prescript")
        self.assertEqual(b["mechanics"]["enemy_prescript"]["skill_id"], "bum_punch")

    def test_ragamuffin_native_transform_not_foreign(self):
        state = self.state("programmer")
        a = state["sides"]["a"]
        a.update(class_id="ragamuffin", archclass_id="", own_turns=4)
        skill = effective_skill(state, "a", "dust_in_eyes")
        self.assertEqual((skill.name, skill.cost), ("Уличные правила", 25))
        a["class_id"] = "nerd"
        self.assertIs(
            effective_skill(state, "a", "dust_in_eyes"), BUILTIN_SKILLS["dust_in_eyes"]
        )


class ArchStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        for chat in (1, 2):
            await self.db.upsert_chat(chat, "Чат")
            for user in (10, 20, 30):
                await self.db.upsert_user(chat, user, str(user), "Игрок")
                await self.db.arena_menu(chat, user)
        await self.db.force_enslave(1, 30, 10)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def profile(self, cls="jock", level=10, user=10, personal=True, chat=1):
        table = "personal_profiles" if personal else "slave_profiles"
        self.db.connection.execute(
            f"UPDATE {table} SET class_id=?,level=?,skills_pending_at=0 WHERE chat_id=? AND user_id=?",
            (cls, level, chat, user),
        )
        self.db.connection.commit()

    async def choose(self, key="mge_bro", actor=10, user=10, personal=True):
        return await self.db.arena_edit_profile(
            1, actor, user, personal, "archclass", key
        )

    async def test_choice_scope_persistence_and_level_twenty(self):
        self.profile()
        before = (await menu_view(self.db, 1, 10))["personal"]
        await self.choose()
        after = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(before["loadout"], after["loadout"])
        self.assertEqual(before["passive_loadout"], after["passive_loadout"])
        self.assertEqual(after["archclass"]["title"], "Мге-браток")
        self.assertEqual(
            (await menu_view(self.db, 2, 10))["personal"]["archclass_id"], ""
        )
        self.assertEqual((await self.db.get_slave_profile(1, 10))["archclass_id"], "")
        await self.db.close()
        await self.db.connect()
        self.assertEqual(
            (await menu_view(self.db, 1, 10))["personal"]["archclass_id"], "mge_bro"
        )
        self.profile("thumb", 20)
        self.db.connection.execute(
            "UPDATE personal_profiles SET archclass_id='thumb_execution' WHERE chat_id=1 AND user_id=10"
        )
        result = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(result["archclass"]["stage"], 20)
        self.assertEqual(result["class_name"], "Соттокапо: Расстрел")

    async def test_low_level_wrong_branch_repeat_and_foreign_profile(self):
        self.profile(level=9)
        with self.assertRaisesRegex(ValueError, "10 уровня"):
            await self.choose()
        self.profile()
        with self.assertRaisesRegex(ValueError, "недоступен"):
            await self.choose("princess")
        with self.assertRaises(ValueError):
            await self.choose(actor=20)
        results = await asyncio.gather(
            self.choose(), self.choose("gachi_actor"), return_exceptions=True
        )
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)

    async def test_owner_wait_is_separate_from_skill_changes(self):
        self.profile(user=30, personal=False)
        with patch("arena_store.utc_timestamp", return_value=100000):
            await self.db.arena_menu(1, 10)
            with self.assertRaisesRegex(ValueError, "48 часов"):
                await self.choose(actor=10, user=30, personal=False)
            await self.db.arena_edit_profile(1, 30, 30, False, "loadout", ["bum_punch"])
            self.assertEqual(
                (await self.db.get_slave_profile(1, 30))["archclass_pending_at"], 100000
            )
        with patch("arena_store.utc_timestamp", return_value=100000 + 48 * 3600):
            await self.choose(actor=10, user=30, personal=False)
        self.assertEqual(
            (await self.db.get_slave_profile(1, 30))["archclass_id"], "mge_bro"
        )

    async def test_reset_and_class_scroll_clear_branch(self):
        self.profile()
        await self.choose()
        await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
        profile = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(
            (profile["class_id"], profile["archclass_id"], profile["level"]),
            ("ragamuffin", "", 1),
        )
        self.profile()
        await self.choose()
        async with self.db._lock:
            self.db._arena_add_item_locked(1, 10, "class", "cutie", "uncommon")
            self.db.connection.commit()
        item = (await self.db.arena_market_view(1, 10))["inventory"][0]["id"]
        await self.db.arena_use_item(1, 10, item, 10, True, True)
        self.assertEqual(
            (await menu_view(self.db, 1, 10))["personal"]["archclass_id"], ""
        )

    async def test_saved_battle_branch_and_actual_ui_prices(self):
        self.profile()
        await self.choose()
        row = await self.db.arena_wasteland(1, 10)
        view = await battle_view(self.db, row, 10)
        a = view["state"]["sides"]["a"]
        self.assertEqual(a["archclass_id"], "mge_bro")
        self.assertEqual(a["class_name"], "Мге-браток")
        with self.assertRaisesRegex(ValueError, "во время боя"):
            await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
        await self.db.close()
        await self.db.connect()
        view = await battle_view(self.db, await self.db.arena_get(row["token"]), 10)
        self.assertEqual(view["state"]["sides"]["a"]["archclass_id"], "mge_bro")

    async def test_messenger_free_fallback_is_visible_even_with_other_usable_skills(
        self,
    ):
        row = await self.db.arena_wasteland(1, 10)
        state = create_battle_state(
            dict(
                slave_id=10, owner_id=10, class_id="jock", level=10, loadout=["smack"]
            ),
            dict(slave_id=0, owner_id=0, class_id="index", level=10),
        )
        state["sides"]["a"]["mechanics"] = dict(
            enemy_prescript=dict(skill_id="bum_punch", penalty=8)
        )
        row["state_json"] = json.dumps(state)
        view = await battle_view(self.db, row, 10)
        a = view["state"]["sides"]["a"]
        self.assertIn("bum_punch", [s["skill_id"] for s in a["skill_details"]])
        self.assertEqual(a["enemy_prescript_name"], "Удар бомжа")

    async def test_old_schema_migration_preserves_progress(self):
        self.profile()
        await self.db.close()
        import sqlite3

        con = sqlite3.connect(Path(self.temp.name) / "test.sqlite3")
        for table in ("personal_profiles", "slave_profiles"):
            con.execute(f"ALTER TABLE {table} DROP COLUMN archclass_id")
            con.execute(f"ALTER TABLE {table} DROP COLUMN archclass_pending_at")
        con.commit()
        con.close()
        await self.db.connect()
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(
            (p["level"], p["class_id"], p["archclass_id"]), (10, "jock", "")
        )
        self.assertEqual(len(p["archclass_options"]), 2)

    async def test_level_crossing_starts_wait_and_promotes_automatically(self):
        self.profile("thumb", 9)
        async with self.db._lock:
            before, after = self.db._grant_profile_xp_locked(
                "personal_profiles", 1, 10, fighter_xp_limit()
            )
            self.db.connection.commit()
        self.assertEqual((before, after), (9, 20))
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertIsNotNone(p["archclass_pending_at"])
        await self.choose("thumb_discipline")
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(p["class_name"], "Соттокапо: Дисциплина")
        self.assertEqual(p["archclass"]["stage"], 20)

    async def test_http_signed_choice_and_forged_profile_rejection(self):
        self.profile()
        bot = SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(
                    status="member", user=SimpleNamespace(is_bot=False)
                )
            )
        )
        client = TestClient(TestServer(create_arena_app(self.db, bot, TOKEN)))
        await client.start_server()
        try:
            response = await client.post(
                "/api/menu/1",
                json=dict(action="archclass", user=10, personal=True, value="mge_bro"),
            )
            self.assertEqual(response.status, 400)
            headers = {"X-Telegram-Init-Data": signed(now=int(time.time()))}
            response = await client.post(
                "/api/menu/1",
                headers=headers,
                json=dict(action="archclass", user=20, personal=True, value="mge_bro"),
            )
            self.assertEqual(response.status, 400)
            response = await client.post(
                "/api/menu/1",
                headers=headers,
                json=dict(action="archclass", user=10, personal=True, value="mge_bro"),
            )
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(payload["menu"]["personal"]["archclass_id"], "mge_bro")
            self.assertEqual(
                payload["menu"]["personal"]["archclass_options"][0]["class_id"], "jock"
            )
        finally:
            await client.close()


class ArchClientTests(unittest.TestCase):
    def test_branch_choices_lock_and_final_stage_render(self):
        runner = client_tests.ArenaMarketClientTests()
        data = runner.menu_data()
        p = data["personal"]
        p.update(
            class_id="jock",
            archclass_options=branch_options("jock"),
            archclass_can_choose=True,
        )
        body = runner.run_client(
            'page="personalProfile";profileId=10;menuScreen(input);', data
        )
        self.assertIn('data-do="archclass:mge_bro"', body)
        self.assertIn("Гачи-актёр", body)
        self.assertIn("Выбери архикласс", body)
        p["archclass_id"] = "mge_bro"
        p["archclass"] = archclass_view(p)
        body = runner.run_client(
            'page="personalProfile";profileId=10;menuScreen(input);', data
        )
        self.assertIn("ступень 20", body)
        self.assertNotIn('data-do="archclass:', body)

    def test_titles_ids_and_enemy_branches(self):
        self.assertEqual(FIGHTER_CLASSES["pinky"].name, "Звёздный клинок")
        for cls in (
            "cutie",
            "jock",
            "nerd",
            "thumb",
            "index",
            "middle",
            "ring",
            "pinky",
        ):
            self.assertEqual(len(branch_options(cls)), 2)
        self.assertEqual(VISIBLE_CLASS_ALIASES["капо"], "thumb")
        for level in (9, 10, 20):
            for seed in range(25):
                source = enemy_source(level, rng=random.Random(seed))
                if level < 10 or source["class_id"] == "ragamuffin":
                    self.assertEqual(source["archclass_id"], "")
                else:
                    self.assertEqual(
                        ARCHCLASSES[source["archclass_id"]]["class_id"],
                        source["class_id"],
                    )
