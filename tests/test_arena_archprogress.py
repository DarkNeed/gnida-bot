import copy
import logging
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_archclasses import ARCHCLASSES, arch_rule, archclass_view
from arena_archprogress import UPGRADES_12, branch_skill_allowed
from arena_engine import (
    BUILTIN_SKILLS,
    create_battle_state,
    effective_skill,
    resolve_skill,
    unlocked_skill_ids,
    xp_for_next_level,
)
from arena_web import menu_view, battle_view
from arena_wasteland import enemy_source
from database import Database
from test_arena_rebalance import FixedRoll
import test_arena_market_client as client_tests

PRIMARY = dict(
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


def state_for(branch, level, skill_id=None):
    return create_battle_state(
        dict(
            slave_id=10,
            owner_id=10,
            class_id=ARCHCLASSES[branch]["class_id"],
            level=level,
            archclass_id=branch,
            archclass_stage=10,
            loadout=[skill_id or PRIMARY[branch]],
        ),
        dict(slave_id=20, owner_id=20, class_id="jock", level=level),
    )


class ArchProgressEngineTests(unittest.TestCase):
    def test_all_branches_have_one_unique_and_three_milestones(self):
        self.assertEqual(set(UPGRADES_12), set(ARCHCLASSES))
        for branch, entry in ARCHCLASSES.items():
            sid = "arch_" + branch
            unique = BUILTIN_SKILLS[sid]
            self.assertEqual(
                (unique.class_id, unique.unlock_level), (entry["class_id"], 15)
            )
            for level in (14, 15, 18):
                allowed = unlocked_skill_ids(
                    entry["class_id"], level, archclass_id=branch
                )
                self.assertEqual(sid in allowed, level >= 15)
                self.assertEqual(
                    [k for k in allowed if k.startswith("arch_")],
                    [sid] if level >= 15 else [],
                )
            self.assertNotIn(sid, unlocked_skill_ids(entry["class_id"], 20))
            view = archclass_view(state_for(branch, 15)["sides"]["a"])
            self.assertEqual([m["level"] for m in view["progression"]], [12, 15, 18])
            self.assertEqual(
                [m["unlocked"] for m in view["progression"]], [True, True, False]
            )

    def test_all_uniques_resolve_one_tap_and_upgrade_at_eighteen(self):
        for branch in ARCHCLASSES:
            sid = "arch_" + branch
            for level in (15, 17, 18, 20):
                with self.subTest(branch=branch, level=level):
                    state = state_for(branch, level, sid)
                    a = state["sides"]["a"]
                    skill = effective_skill(state, "a", sid)
                    self.assertEqual(skill.cost, BUILTIN_SKILLS[sid].cost)
                    self.assertEqual(skill.cooldown, BUILTIN_SKILLS[sid].cooldown)
                    if level >= 18:
                        self.assertNotEqual(skill, BUILTIN_SKILLS[sid])
                    else:
                        self.assertIs(skill, BUILTIN_SKILLS[sid])
                    before = a["resource"]
                    event = resolve_skill(state, "a", sid, rng=FixedRoll(0))
                    self.assertTrue(event["hit"])
                    self.assertEqual(event["skill_id"], sid)
                    self.assertLessEqual(a["resource"], before)
                    self.assertGreaterEqual(a["resource"], 0)
                    self.assertLessEqual(len(a["loadout"]), 4)
                    self.assertLessEqual(len(a["passive_details"]), 2)

    def test_forged_wrong_branch_or_low_level_cannot_execute_unique(self):
        for branch in ARCHCLASSES:
            sid = "arch_" + branch
            state = state_for(branch, 14)
            state["sides"]["a"]["loadout"] = [sid]
            before = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                resolve_skill(state, "a", sid)
            self.assertEqual(state, before)
            state = state_for(branch, 18, sid)
            state["sides"]["a"]["archclass_id"] = ""
            with self.assertRaises(ValueError):
                resolve_skill(state, "a", sid)
            state["sides"]["a"].update(archclass_id=branch, class_id="ragamuffin")
            with self.assertRaises(ValueError):
                resolve_skill(state, "a", sid)

    def test_unique_cost_cooldown_and_miss_never_refund_or_apply_effects(self):
        state = state_for("hacker", 18, "arch_hacker")
        state["sides"]["a"]["resource"] = 34
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "arch_hacker")
        self.assertEqual(state, before)
        state["sides"]["a"]["resource"] = 100
        b = state["sides"]["b"]
        before_effects = copy.deepcopy(b["effects"])
        resolve_skill(state, "a", "arch_hacker", rng=FixedRoll(0.99))
        self.assertEqual(state["sides"]["a"]["resource"], 65)
        self.assertEqual(b["resource"], 100)
        self.assertEqual(b["effects"], before_effects)
        state["active_side"] = "a"
        with self.assertRaisesRegex(ValueError, "восстанавливается"):
            resolve_skill(state, "a", "arch_hacker")

    def test_level_twelve_rules_really_change_and_are_not_lost_at_twenty(self):
        for branch, sid in PRIMARY.items():
            skill = BUILTIN_SKILLS[sid]
            a11 = state_for(branch, 11)["sides"]["a"]
            a12 = state_for(branch, 12)["sides"]["a"]
            rule11, rule12 = arch_rule(skill, a11), arch_rule(skill, a12)
            if branch not in {"programmer", "index_messenger"}:
                self.assertNotEqual(rule11["changes"], rule12["changes"], branch)
            self.assertIn("12 уровня", rule12["description"])
            a20 = dict(a12, level=20, archclass_stage=20)
            rule20 = arch_rule(skill, a20)
            for attribute in ("power", "accuracy", "pierce"):
                if attribute in rule12["changes"]:
                    self.assertGreaterEqual(
                        rule20["changes"][attribute], rule12["changes"][attribute]
                    )
        state = state_for("index_messenger", 12)
        resolve_skill(state, "a", "receive_prescript", rng=FixedRoll(0))
        self.assertEqual(
            state["sides"]["b"]["mechanics"]["enemy_prescript"]["penalty"], 10
        )
        state = state_for("programmer", 12)
        resolve_skill(state, "a", "charging", rng=FixedRoll(0))
        self.assertEqual(effective_skill(state, "a", "humiliate").cost, 9)

    def test_pve_pool_never_contains_sibling_branch_skills(self):
        rng = random.Random(44)
        for level in (14, 15, 18, 20):
            for _ in range(120):
                source = enemy_source(level, rng=rng)
                state = create_battle_state(
                    source, dict(slave_id=1, owner_id=1, class_id="jock", level=level)
                )
                for sid in state["sides"]["a"]["loadout"]:
                    self.assertTrue(
                        branch_skill_allowed(
                            BUILTIN_SKILLS[sid], source["archclass_id"], level
                        )
                    )


class ArchProgressStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        for user in (10, 20, 30):
            await self.db.upsert_user(1, user, str(user), str(user))
            await self.db.arena_menu(1, user)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def level(self, branch, level, user=10, personal=True):
        table = "personal_profiles" if personal else "slave_profiles"
        self.db.connection.execute(
            f"UPDATE {table} SET class_id=?,level=?,xp=?,archclass_id=?,progression_level=10,archclass_stage=10 WHERE chat_id=1 AND user_id=?",
            (
                ARCHCLASSES[branch]["class_id"],
                level,
                sum(xp_for_next_level(n) for n in range(1, level)),
                branch,
                user,
            ),
        )
        self.db.connection.commit()

    async def test_full_memory_preserved_new_skill_available_and_can_relearn(self):
        self.level("hacker", 14)
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(len(p["known_skills"]), 6)
        old = p["known_skills"]
        self.level("hacker", 15)
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(p["known_skills"], old)
        self.assertIn("arch_hacker", [s["skill_id"] for s in p["available_skills"]])
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(
                1, 10, 10, True, "learn_skill", "arch_hacker"
            )
        await self.db.arena_edit_profile(
            1, 10, 10, True, "forget_skill", "dust_in_eyes"
        )
        await self.db.arena_edit_profile(1, 10, 10, True, "learn_skill", "arch_hacker")
        await self.db.arena_edit_profile(1, 10, 10, True, "loadout", ["arch_hacker"])
        await self.db.close()
        await self.db.connect()
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertIn("arch_hacker", p["known_skills"])
        row = await self.db.arena_wasteland(1, 10)
        view = await battle_view(self.db, row, 10)
        self.assertIn("arch_hacker", view["state"]["sides"]["a"]["loadout"])
        await self.db.arena_action(row["token"], 10, row["revision"], "surrender")
        await self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True)
        self.assertNotIn(
            "arch_hacker", (await menu_view(self.db, 1, 10))["personal"]["known_skills"]
        )

    async def test_unique_fills_free_memory_not_extra_slots_and_branch_isolation(self):
        self.level("pinky_dihui", 14)
        await menu_view(self.db, 1, 10)
        await self.db.arena_edit_profile(
            1, 10, 10, True, "forget_skill", "dust_in_eyes"
        )
        p = (await menu_view(self.db, 1, 10))["personal"]
        old = p["known_skills"]
        self.level("pinky_dihui", 15)
        p = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(p["known_skills"], old + ["arch_pinky_dihui"])
        self.assertLessEqual(len(p["loadout"]), 4)
        for sid in ("arch_pinky_tiansha", "arch_hacker"):
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(1, 10, 10, True, "learn_skill", sid)
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(1, 10, 10, True, "loadout", [sid])
        self.assertFalse((await menu_view(self.db, 1, 20))["personal"]["archclass"])

    async def test_slave_menu_and_combat_keep_unique_and_scope(self):
        await self.db.force_enslave(1, 30, 10)
        await self.db.arena_equip_slave(1, 10, 30, True)
        self.level("ring_fauvist", 18, user=30, personal=False)
        p = (await menu_view(self.db, 1, 10))["slaves"][0]
        self.assertIn(
            "arch_ring_fauvist", [s["skill_id"] for s in p["available_skills"]]
        )
        await self.db.arena_edit_profile(
            1, 30, 30, False, "forget_skill", "dust_in_eyes"
        )
        await self.db.arena_edit_profile(
            1, 30, 30, False, "learn_skill", "arch_ring_fauvist"
        )
        p = (await menu_view(self.db, 1, 10))["slaves"][0]
        self.assertIn("arch_ring_fauvist", p["known_skills"])
        await self.db.arena_edit_profile(
            1, 30, 30, False, "loadout", ["arch_ring_fauvist"]
        )
        row = await self.db.arena_wasteland(1, 10, 30, personal=False)
        view = await battle_view(self.db, row, 10)
        detail = next(
            s
            for s in view["state"]["sides"]["a"]["skill_details"]
            if s["skill_id"] == "arch_ring_fauvist"
        )
        self.assertEqual(detail["power"], 15)
        self.assertEqual(detail["evolution"]["min_level"], 18)
        self.assertNotIn(
            "arch_ring_fauvist",
            (await menu_view(self.db, 1, 30))["personal"]["known_skills"],
        )

    async def test_uniques_not_sold_and_wrong_branch_scroll_not_consumed(self):
        self.level("hacker", 15)
        async with self.db._lock:
            self.assertNotIn(
                ("skill", "arch_hacker"), self.db._arena_shop_catalog_locked()
            )
            self.db._arena_add_item_locked(1, 10, "skill", "arch_princess", "rare")
            self.db.connection.commit()
        item = (await self.db.arena_market_view(1, 10))["inventory"][0]["id"]
        with self.assertRaises(ValueError):
            await self.db.arena_use_item(1, 10, item, 10, True)
        self.assertEqual(
            (await self.db.arena_market_view(1, 10))["inventory"][0]["quantity"], 1
        )

    async def test_update_starts_delegation_once_even_for_full_level_18_memory(self):
        await self.db.force_enslave(1, 30, 10)
        self.level("hacker", 14, user=30, personal=False)
        await menu_view(self.db, 1, 10)
        self.db.connection.execute(
            "UPDATE slave_profiles SET skills_pending_at=NULL WHERE user_id=30"
        )
        self.db.connection.commit()
        self.level("hacker", 18, user=30, personal=False)
        with patch("arena_market.market_now", return_value=100000):
            await menu_view(self.db, 1, 10)
        with patch("arena_market.market_now", return_value=200000):
            await menu_view(self.db, 1, 10)
        profile = self.db.connection.execute(
            "SELECT * FROM slave_profiles WHERE user_id=30"
        ).fetchone()
        self.assertEqual(profile["skills_pending_at"], 100000)
        with patch("arena_store.utc_timestamp", return_value=100001):
            with self.assertRaises(ValueError):
                await self.db.arena_edit_profile(
                    1, 10, 30, False, "forget_skill", "dust_in_eyes"
                )
        with patch("arena_store.utc_timestamp", return_value=100000 + 48 * 3600):
            await self.db.arena_edit_profile(
                1, 10, 30, False, "forget_skill", "dust_in_eyes"
            )
            await self.db.arena_edit_profile(
                1, 10, 30, False, "learn_skill", "arch_hacker"
            )
        self.assertIn(
            "arch_hacker",
            (await menu_view(self.db, 1, 10))["slaves"][0]["known_skills"],
        )


class ArchProgressClientTests(unittest.TestCase):
    def test_menu_lists_all_milestones_and_available_skill_effects(self):
        runner = client_tests.ArenaMarketClientTests()
        data = runner.menu_data()
        data["personal"].update(
            archclass=archclass_view(state_for("hacker", 15)["sides"]["a"]),
            available_skills=[
                dict(
                    skill_id="arch_hacker",
                    name="Отказ в обслуживании",
                    cost=35,
                    accuracy=90,
                    power=10,
                    cooldown=3,
                    effects=[],
                    description="Уникальный навык",
                )
            ],
        )
        body = runner.run_client(
            "page='personalProfile';profileId=10;menuScreen(input);", data
        )
        for level in (12, 15, 18):
            self.assertIn(str(level) + " уровень", body)
        self.assertIn("Энергия 35", body)
        self.assertIn("learn_skill:arch_hacker", body)
