"""Reliable revenge attacks without larger HP/attack stats or free resources."""

import unittest

from arena_engine import BUILTIN_SKILLS, create_battle_state, effective_skill, resolve_skill
from arena_fingers import combat_modifiers
from test_arena_rebalance import FixedRoll


class MiddleBalanceTests(unittest.TestCase):
    def state(self, branch="", grudge=3, passives=True, level=17, stage=10):
        source = dict(slave_id=1, owner_id=1, class_id="middle", level=level,
                      archclass_id=branch, archclass_stage=stage)
        if not passives:
            source["passive_details"] = []
        state = create_battle_state(source, dict(slave_id=2, owner_id=2,
                                                class_id="cutie", level=level))
        a, b = state["sides"].values()
        a["loadout"] = list(BUILTIN_SKILLS)
        a["mechanics"] = dict(grudge=grudge)
        a["own_turns"] = 2
        a["hp"] = b["hp"] = 10000
        return state

    def tap(self, state, skill, roll):
        return resolve_skill(state, "a", skill, rng=FixedRoll(roll), advance_turn=False)

    def test_bounded_accuracy_and_compensating_damage_per_grudge(self):
        for key, bonus in (("answer_for_it", .10), ("whole_family", .12)):
            for stacks in (-1, 0, 1, 2, 3, 8):
                with self.subTest(skill=key, stacks=stacks):
                    state = self.state(grudge=stacks)
                    a, b = state["sides"].values()
                    accuracy, boost, *_ = combat_modifiers(a, b, BUILTIN_SKILLS[key], FixedRoll())
                    bounded = max(0, min(3, stacks))
                    self.assertEqual(accuracy, 3 * bounded)
                    self.assertAlmostEqual(boost, bonus * bounded)

    def test_misses_keep_only_one_existing_grudge_cost_and_cooldown_unchanged(self):
        for branch in ("", "middle_guardian", "middle_revenge"):
            for key in ("answer_for_it", "whole_family"):
                for stacks in (0, 1, 2, 3):
                    with self.subTest(branch=branch, skill=key, stacks=stacks):
                        state = self.state(branch, stacks)
                        a = state["sides"]["a"]
                        skill = effective_skill(state, "a", key)
                        event = self.tap(state, key, .99)
                        self.assertFalse(event["hit"])
                        self.assertEqual(a["mechanics"]["grudge"], min(1, stacks))
                        self.assertEqual(a["resource"], 100 - skill.cost)
                        self.assertEqual(a["cooldowns"][key], skill.cooldown)
                        self.assertEqual(a["own_turns"], 3)
                        self.assertEqual(event["self_damage"], 0)

    def test_success_consumes_all_and_recoil_is_still_twenty_percent(self):
        for branch in ("", "middle_guardian", "middle_revenge"):
            for level, stage in ((9, 10), (10, 10), (17, 10), (20, 20)):
                for key in ("answer_for_it", "whole_family"):
                    state = self.state(branch, level=level, stage=stage)
                    event = self.tap(state, key, 0)
                    self.assertTrue(event["hit"])
                    self.assertEqual(state["sides"]["a"]["mechanics"]["grudge"], 0)
                    expected = (event["damage"] + 4) // 5 if branch == "middle_revenge" and level >= 10 else 0
                    self.assertEqual(event["self_damage"], expected)

    def test_bonus_changes_actual_hit_threshold_for_base_and_both_branches(self):
        for branch in ("", "middle_guardian", "middle_revenge"):
            state = self.state(branch)
            # Base/guardian: 86 + 9 - 20 = 75%; revenge with its level-12
            # improvement: 91 + 9 - 20 = 80%. Previously 66% / 71%.
            threshold = .80 if branch == "middle_revenge" else .75
            self.assertTrue(self.tap(state, "whole_family", threshold - .001)["hit"])
            self.assertFalse(self.tap(self.state(branch), "whole_family", threshold)["hit"])

    def test_missing_passive_does_not_grant_bonus_or_preserve_stale_grudge(self):
        state = self.state(passives=False)
        a, b = state["sides"].values()
        self.assertEqual(combat_modifiers(a, b, BUILTIN_SKILLS["whole_family"], FixedRoll())[:2], (0, 0))
        self.tap(state, "whole_family", .99)
        self.assertEqual(a["mechanics"]["grudge"], 0)

    def test_missed_evolved_skill_reports_one_grudge_and_loses_three_stack_variant(self):
        for branch in ("", "middle_guardian", "middle_revenge"):
            state = self.state(branch)
            self.assertEqual(effective_skill(state, "a", "whole_family").name, "Долг крови")
            event = self.tap(state, "whole_family", .99)
            self.assertEqual(event["status_after"]["a"]["mechanics"]["grudge"], 1)
            self.assertEqual(effective_skill(state, "a", "whole_family").name, "За всю семью")

    def test_non_reply_skills_do_not_spend_grudges_or_receive_accuracy(self):
        for key in ("recorded", "bum_punch", "grit_teeth", "tigerslayer_flurry"):
            state = self.state()
            a, b = state["sides"].values()
            self.assertEqual(combat_modifiers(a, b, BUILTIN_SKILLS[key], FixedRoll())[:2], (0, 0))
            self.tap(state, key, 0)
            self.assertEqual(a["mechanics"]["grudge"], 3)


if __name__ == "__main__":
    unittest.main()
