import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from arena_engine import BUILTIN_SKILLS, create_battle_state, resolve_skill, skip_turn
from arena_class_mechanics import class_modifiers
from database import Database
import test_arena_market_client as client_tests


class Roll:
    def __init__(self, value=0):
        self.value = value

    def random(self):
        return self.value

    def uniform(self, low, high):
        return 1

    def choice(self, choices):
        return choices[0]


class JockEngineTests(unittest.TestCase):
    def state(self, passives=None, controlled=False):
        source = dict(
            slave_id=10, owner_id=30, class_id="jock", level=20, controlled=controlled
        )
        if passives is not None:
            source["passive_details"] = passives
        state = create_battle_state(
            source, dict(slave_id=20, owner_id=20, class_id="nerd", level=20)
        )
        for side in state["sides"].values():
            side["loadout"] = list(BUILTIN_SKILLS)
            side["hp"] = 10000
        return state

    def tap(self, state, skill, roll=0, side="a"):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=Roll(roll))

    def boost(self, state, skill="smack"):
        a, b = state["sides"].values()
        return class_modifiers(a, b, BUILTIN_SKILLS[skill])[1]

    def test_both_preparations_charge_bonus_refund_and_keep_turn_and_cooldown(self):
        for skill, cost, cooldown in (("flex_chest", 25, 3), ("clench", 20, 2)):
            with self.subTest(skill=skill):
                state = self.state()
                event = self.tap(state, skill)
                a = state["sides"]["a"]
                self.assertEqual(a["resource"], 100 - cost + 8)
                self.assertEqual(a["cooldowns"][skill], cooldown)
                self.assertEqual(state["active_side"], "b")
                self.assertEqual(event["after"]["a"]["resource"], a["resource"])
                self.assertEqual(self.boost(state), 0.15)

    def test_failing_clench_costs_full_price_no_bonus_or_refund(self):
        state = self.state()
        self.assertFalse(self.tap(state, "clench", 0.99)["hit"])
        self.assertEqual(state["sides"]["a"]["resource"], 80)
        self.assertEqual(self.boost(state), 0)

    def test_exact_bonus_only_next_physical_attack_even_when_it_misses(self):
        for roll in (0, 0.99):
            state = self.state()
            self.tap(state, "flex_chest")
            plain = copy.deepcopy(state)
            plain["sides"]["a"]["effects"] = [
                e
                for e in plain["sides"]["a"]["effects"]
                if e["kind"] != "next_physical_damage"
            ]
            full = self.tap(plain, "smack", roll)["damage"]
            boosted = self.tap(state, "smack", roll)["damage"]
            self.assertAlmostEqual(boosted, full * 1.15, delta=1)
            self.assertEqual(self.boost(state), 0)
            self.assertEqual(
                state["sides"]["a"]["resource"], 68
            )  # Prepared version costs 15 from level 10.

    def test_bonus_refreshes_without_stacking(self):
        state = self.state()
        self.tap(state, "flex_chest")
        self.tap(state, "clench")
        effects = [
            e
            for e in state["sides"]["a"]["effects"]
            if e["kind"] == "next_physical_damage"
        ]
        self.assertEqual(len(effects), 1)
        self.assertEqual((effects[0]["value"], effects[0]["duration"]), (0.15, 2))

    def test_magic_not_boosted_or_consumed_but_counts_toward_two_own_actions(self):
        state = self.state()
        self.tap(state, "flex_chest")
        self.tap(state, "bum_punch", side="b")
        self.assertEqual(self.boost(state), 0.15)  # Enemy actions do not tick it.
        self.assertEqual(self.boost(state, "humiliate"), 0)
        self.tap(state, "humiliate")
        self.assertEqual(self.boost(state), 0.15)
        self.tap(state, "go_to_store")
        self.assertEqual(self.boost(state), 0)

    def test_second_action_physical_still_gets_bonus(self):
        state = self.state()
        self.tap(state, "flex_chest")
        self.tap(state, "go_to_store")
        self.assertEqual(self.boost(state), 0.15)
        self.tap(state, "bum_punch")
        self.assertEqual(self.boost(state), 0)

    def test_timeout_ticks_without_proc_or_refund(self):
        state = self.state()
        self.tap(state, "flex_chest")
        for _ in range(2):
            state["active_side"] = "a"
            skip_turn(state)
        self.assertEqual(state["sides"]["a"]["resource"], 83)
        self.assertEqual(self.boost(state), 0)

    def test_validation_uses_full_cost_before_refund(self):
        state = self.state()
        state["sides"]["a"]["resource"] = 24
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            self.tap(state, "flex_chest")
        self.assertEqual(state, before)

    def test_each_trait_only_works_when_equipped_not_merely_class_or_skill(self):
        for selected, refund, boost in (([], 0, 0), ([0], 0, 0.15), ([1], 8, 0)):
            state = self.state()
            a = state["sides"]["a"]
            a["passive_details"] = [a["passive_details"][i] for i in selected]
            self.tap(state, "flex_chest")
            self.assertEqual(a["resource"], 75 + refund)
            self.assertEqual(self.boost(state), boost)
        state = self.state()
        self.tap(state, "flex_chest", side="b")  # Nerd with foreign jock skill.
        self.assertEqual(state["sides"]["b"]["resource"], 75)
        self.assertFalse(
            any(
                e["kind"] == "next_physical_damage"
                for e in state["sides"]["b"]["effects"]
            )
        )

    def test_normal_attacks_do_not_proc_passives(self):
        state = self.state()
        self.tap(state, "smack")
        self.assertEqual(state["sides"]["a"]["resource"], 90)
        self.assertEqual(self.boost(state), 0)

    def test_controlled_bonus_persists_json_and_new_battle_starts_without_charge(self):
        state = self.state(controlled=True)
        self.tap(state, "flex_chest")
        state = json.loads(json.dumps(state))
        self.assertEqual(state["sides"]["a"]["resource"], 63)
        self.assertEqual(self.boost(state), 0.15)
        self.tap(state, "smack")
        self.assertEqual(self.boost(state), 0)
        self.assertEqual(self.boost(self.state()), 0)


class JockStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        await self.db.upsert_user(1, 10, "ten", "Ten")

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def test_existing_personal_and_slave_profiles_discover_once(self):
        for personal, table in ((True, "personal_profiles"), (False, "slave_profiles")):
            await self.db.arena_passive_view(1, 10, personal)
            self.db.connection.execute(
                f"UPDATE {table} SET class_id='jock' WHERE chat_id=1 AND user_id=10"
            )
            view = await self.db.arena_passive_view(1, 10, personal)
            ids = ["inherent:jock:0", "inherent:jock:1"]
            self.assertEqual(view["passive_loadout"], ids)
            self.assertEqual(len(view["passives"]), 2)
            self.db.connection.execute(
                f"UPDATE {table} SET passive_loadout='[]' WHERE chat_id=1 AND user_id=10"
            )
            self.assertEqual(
                (await self.db.arena_passive_view(1, 10, personal))["passive_loadout"],
                [],
            )

    async def test_new_passives_leave_existing_two_equipped_and_learned_cap_intact(
        self,
    ):
        await self.db.arena_passive_view(1, 10, True)
        for skill in ("steady_hand", "stone_skin"):
            self.db._arena_add_item_locked(1, 10, "passive", skill, "common")
            item = self.db.connection.execute(
                "SELECT id FROM arena_inventory WHERE content_id=?", (skill,)
            ).fetchone()["id"]
            self.db.connection.commit()
            await self.db.arena_use_item(1, 10, item, 10)
        await self.db.arena_edit_profile(
            1, 10, 10, True, "passives", ["steady_hand", "stone_skin"]
        )
        self.db.connection.execute(
            "UPDATE personal_profiles SET class_id='jock' WHERE chat_id=1 AND user_id=10"
        )
        view = await self.db.arena_passive_view(1, 10, True)
        self.assertEqual(view["passive_loadout"], ["steady_hand", "stone_skin"])
        self.assertEqual(len(view["passives"]), 3)


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class JockClientTests(unittest.TestCase):
    def test_ready_effect_has_readable_percentage(self):
        body = client_tests.ArenaMarketClientTests.run_client(
            self,
            "out=describeEffect(input);",
            dict(kind="next_physical_damage", value=0.15, target="self", turns=2),
        )
        self.assertIn("15%", body)
        self.assertIn("Следующая физическая атака", body)


if __name__ == "__main__":
    unittest.main()
