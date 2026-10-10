"""Regressions for the approved constellation, recoil and cutie rebalance."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_engine import (
    BUILTIN_SKILLS, create_battle_state, effective_skill, resolve_skill,
)
from arena_class_mechanics import has_adoration
from arena_fingers import has_trait
from arena_web import battle_view
from database import Database
from test_arena_rebalance import FixedRoll


class StarsRevengeTests(unittest.TestCase):
    def state(self, cls="pinky", branch="", level=10, stage=10):
        state = create_battle_state(
            dict(slave_id=10, owner_id=10, class_id=cls, level=level,
                 archclass_id=branch, archclass_stage=stage),
            dict(slave_id=20, owner_id=20, class_id="middle", level=level),
        )
        for side in state["sides"].values():
            side["loadout"] = list(BUILTIN_SKILLS)
            side["hp"] = 10000
            side["mechanics"] = {}
        state["active_side"] = "a"
        return state

    def tap(self, state, skill, roll=0, side="a"):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=FixedRoll(roll))

    def test_breath_and_one_native_attack_unlock_and_critical_never_resets(self):
        state = self.state(branch="pinky_tiansha")
        a = state["sides"]["a"]
        self.tap(state, "calm_breath")
        self.assertEqual(a["mechanics"]["focus"], 2)
        self.assertEqual(effective_skill(state, "a", "falling_star").name, "Падающая звезда")
        self.assertTrue(self.tap(state, "silent_cut")["critical"])
        self.assertEqual(a["mechanics"]["focus"], 3)
        self.assertEqual(effective_skill(state, "a", "falling_star").name, "Рассечь небеса")
        self.tap(state, "silent_cut")
        self.assertEqual(a["mechanics"]["focus"], 3)

    def test_ordinary_misses_foreign_attacks_and_unequipped_passive_do_not_charge(self):
        for skill, roll in (("silent_cut", .99), ("bum_punch", 0), ("uwu", 0)):
            state = self.state()
            self.tap(state, skill, roll)
            self.assertEqual(state["sides"]["a"]["mechanics"].get("focus", 0), 0)
        state = self.state()
        a = state["sides"]["a"]
        a["passive_details"] = []
        for skill in ("calm_breath", "silent_cut"):
            self.tap(state, skill)
            self.assertNotIn("focus", a["mechanics"])

    def test_level_fifteen_native_attack_gains_charge(self):
        state = self.state(branch="pinky_tiansha", level=15)
        self.tap(state, "arch_pinky_tiansha")
        self.assertEqual(state["sides"]["a"]["mechanics"]["focus"], 1)

    def test_empowered_hit_spends_two_miss_preserves_three_including_base_class(self):
        for branch, skill in (("", "moon_arc"), ("pinky_dihui", "moon_arc"),
                              ("pinky_tiansha", "falling_star")):
            for roll in (0, .99):
                with self.subTest(branch=branch, roll=roll):
                    state = self.state(branch=branch)
                    a = state["sides"]["a"]
                    a["mechanics"]["focus"] = 3
                    cost = effective_skill(state, "a", skill).cost
                    event = self.tap(state, skill, roll)
                    self.assertTrue(event["evolved"])
                    self.assertEqual(a["resource"], 100 - cost)
                    self.assertEqual(a["mechanics"]["focus"], 1 if event["hit"] else 3)
                    if skill == "moon_arc":
                        self.assertFalse(event["critical"])

    def test_star_prices_power_and_level_twelve_upgrade_at_both_stages(self):
        for level, stage, power in ((10, 10, 21), (11, 10, 21), (12, 10, 22),
                                    (20, 10, 22), (20, 20, 22)):
            state = self.state(branch="pinky_tiansha", level=level, stage=stage)
            state["sides"]["a"]["mechanics"]["focus"] = 3
            skill = effective_skill(state, "a", "falling_star")
            self.assertEqual((skill.power, skill.cost), (power, 45))
            state["sides"]["a"]["archclass_id"] = "pinky_dihui"
            skill = effective_skill(state, "a", "moon_arc")
            self.assertEqual((skill.power, skill.cost), (13, 20))
            self.assertAlmostEqual(skill.pierce, .55 if stage == 20 else .5 if level >= 12 else .45)

    def test_recoil_is_actual_damage_and_does_not_feed_own_grudges(self):
        state = self.state("middle", "middle_revenge")
        a, b = state["sides"].values()
        a["mechanics"]["grudge"] = 2
        event = self.tap(state, "recorded")
        recoil = (event["damage"] + 4) // 5
        self.assertEqual(event["self_damage"], recoil)
        self.assertEqual(a["hp"], 10000 - recoil)
        self.assertEqual(event["after"]["a"]["hp"], a["hp"])
        self.assertEqual(a["mechanics"]["grudge"], 2)
        self.assertEqual(b["mechanics"]["grudge"], 1)  # Real incoming attack still counts.
        self.assertIn(f"самоурон: −{recoil} HP", event["text"])

    def test_recoil_ignores_armor_tattoos_and_does_not_require_revenge_passive(self):
        state = self.state("middle", "middle_revenge")
        a = state["sides"]["a"]
        a["hp"] = 20  # Tattoos are active; still the same HP payment.
        self.assertTrue(has_trait(a, "tattoos"))
        a["effects"].append(dict(id="armor", kind="physical_defense_pct", value=10, duration=3))
        event = self.tap(state, "recorded")
        self.assertEqual(event["self_damage"], (event["damage"] + 4) // 5)
        state = self.state("middle", "middle_revenge")
        state["sides"]["a"]["passive_details"] = []
        self.assertGreater(self.tap(state, "recorded")["self_damage"], 0)

    def test_foreign_attacks_pay_but_bleed_utility_and_misses_do_not(self):
        state = self.state("middle", "middle_revenge")
        self.assertGreater(self.tap(state, "bum_punch")["self_damage"], 0)
        for skill, roll in (("recorded", .99), ("grit_teeth", 0), ("dust_in_eyes", 0)):
            state = self.state("middle", "middle_revenge")
            a, b = state["sides"].values()
            b["effects"].append(dict(id="bleed", kind="bleed", value=40, duration=3))
            event = self.tap(state, skill, roll)
            self.assertEqual(event["bleed_damage"], 40)
            self.assertEqual(event["self_damage"], 0)
            self.assertEqual(a["hp"], 10000)
        state = self.state("middle", "middle_revenge")
        state["sides"]["b"]["hp"] = 1
        event = self.tap(state, "whole_family")
        self.assertGreater(event["damage"], 1)
        self.assertEqual(event["self_damage"], 1)  # Overkill is not part of the payment.

    def test_base_middle_guardian_and_invalid_branch_do_not_pay(self):
        for cls, branch, level in (("middle", "", 10), ("middle", "middle_guardian", 10),
                                   ("middle", "middle_revenge", 9),
                                   ("pinky", "middle_revenge", 10)):
            state = self.state(cls, branch, level)
            event = self.tap(state, "bum_punch")
            self.assertEqual(event["self_damage"], 0)

    def test_self_knockout_and_mutual_knockout_end_for_either_side(self):
        for key in ("a", "b"):
            for mutual in (False, True):
                with self.subTest(key=key, mutual=mutual):
                    state = self.state("middle", "middle_revenge")
                    if key == "b":
                        state["sides"]["a"], state["sides"]["b"] = state["sides"]["b"], state["sides"]["a"]
                    other = "b" if key == "a" else "a"
                    state["sides"][key]["hp"] = 1
                    if mutual:
                        state["sides"][other]["hp"] = 1
                    self.tap(state, "recorded", side=key)
                    self.assertTrue(state["finished"])
                    self.assertEqual(state["winner"], None if mutual else other)
                    self.assertEqual(state["finish_reason"], "mutual_knockout" if mutual else "self_damage")
                    with self.assertRaises(ValueError):
                        resolve_skill(state, state["active_side"], "bum_punch")

    def test_uwu_preserves_but_never_refreshes_adoration_until_natural_expiry(self):
        state = self.state("cutie")
        a, b = state["sides"].values()
        self.tap(state, "uwu")
        original = copy.deepcopy(b["effects"])
        self.tap(state, "uwu")
        self.assertEqual(a["resource"], 80)  # No new charm refund.
        self.assertEqual(b["effects"], original)
        self.tap(state, "bum_punch", side="b")
        self.assertTrue(has_adoration(b))
        self.tap(state, "uwu")
        self.assertEqual(a["resource"], 65)
        self.assertEqual(next(e for e in b["effects"] if e["id"] == "adoration")["duration"], 1)
        self.tap(state, "bum_punch", side="b")
        self.assertFalse(has_adoration(b))
        self.assertIs(effective_skill(state, "a", "uwu"), BUILTIN_SKILLS["uwu"])

    def test_enhanced_meow_has_real_damage_gain_at_unchanged_cost(self):
        plain = self.state("cutie")
        evolved = copy.deepcopy(plain)
        evolved["sides"]["a"]["own_turns"] = 4
        a = evolved["sides"]["a"]
        skill = effective_skill(evolved, "a", "meow")
        self.assertEqual((skill.power, skill.cost, skill.cooldown), (22, 35, 2))
        first = self.tap(plain, "meow")["damage"]
        upgraded = self.tap(evolved, "meow")["damage"]
        self.assertAlmostEqual(upgraded / first, 22 / 17, delta=.08)
        self.assertEqual(a["resource"], 65)


class RecoilStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_mutual_knockout_refunds_both_stakes_once_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            await db.connect()
            try:
                await db.upsert_chat(1, "Test")
                for user in (10, 20):
                    await db.upsert_user(1, user, str(user), str(user))
                    db._add_francs_locked(1, user, 100)
                db.connection.commit()
                row = await db.arena_offer(1, 10, 20, "personal", 50)
                await db.arena_set_message(row["token"], 1)
                row = await db.arena_setup(row["token"], 20, "accept")
                state = StarsRevengeTests().state("middle", "middle_revenge")
                for side in state["sides"].values():
                    side["hp"] = 1
                db.connection.execute(
                    "UPDATE arena_battles SET state_json=? WHERE token=?",
                    (json.dumps(state), row["token"]),
                )
                db.connection.commit()
                await db.close()
                await db.connect()
                row = await db.arena_get(row["token"])
                with patch("arena_engine.random.SystemRandom", return_value=FixedRoll()):
                    row = await db.arena_action(row["token"], 10, row["revision"], "recorded")
                self.assertEqual(row["status"], "finished")
                saved = json.loads(row["state_json"])
                self.assertIsNone(saved["winner"])
                self.assertEqual(saved["payout"], 0)
                self.assertEqual(saved["log"][-1]["self_damage"], 1)
                self.assertEqual((row["escrow_a"], row["escrow_b"]), (0, 0))
                view = await battle_view(db, row, 10)
                self.assertIsNone(view["state"]["winner"])
                with self.assertRaises(ValueError):
                    await db.arena_action(row["token"], 10, row["revision"], "recorded")
                balances = db.connection.execute(
                    "SELECT balance FROM franc_balances WHERE chat_id=1 ORDER BY user_id"
                ).fetchall()
                self.assertEqual([r["balance"] for r in balances], [100, 100])
            finally:
                await db.close()
