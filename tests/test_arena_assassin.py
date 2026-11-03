import unittest

from arena_archclasses import ARCHCLASSES, branch_options
from arena_engine import VISIBLE_CLASS_ALIASES, create_battle_state, effective_skill, resolve_skill


class AlwaysHit:
    def random(self):
        return 0

    def uniform(self, low, high):
        return 1


class AssassinBleedTests(unittest.TestCase):
    def state(self):
        state = create_battle_state(
            dict(slave_id=1, owner_id=1, class_id="assassin", level=8),
            dict(slave_id=2, owner_id=2, class_id="ragamuffin", level=8),
        )
        state["sides"]["a"]["loadout"] = [
            "assassin_cut", "assassin_needle", "assassin_expose", "assassin_execution",
        ]
        return state

    def test_each_damaging_assassin_skill_applies_bleeding_after_a_hit(self):
        for skill_id in self.state()["sides"]["a"]["loadout"]:
            state = self.state()
            event = resolve_skill(state, "a", skill_id, rng=AlwaysHit())
            self.assertTrue(event["hit"], skill_id)
            self.assertTrue(
                any(effect["kind"] == "bleed" for effect in state["sides"]["b"]["effects"]),
                skill_id,
            )

    def test_bleeding_ticks_when_the_wounded_target_uses_an_attack(self):
        state = self.state()
        resolve_skill(state, "a", "assassin_cut", rng=AlwaysHit())
        event = resolve_skill(state, "b", "bum_punch", rng=AlwaysHit())
        self.assertEqual(event["bleed_damage"], 2)

    def test_assassin_is_selectable_and_both_archclasses_transform_native_skills(self):
        self.assertEqual(VISIBLE_CLASS_ALIASES["ассасин"], "assassin")
        self.assertEqual({branch["id"] for branch in branch_options("assassin")}, {
            "assassin_shadow", "assassin_blood",
        })
        for branch_id, skill_id in (
            ("assassin_shadow", "assassin_smoke"),
            ("assassin_blood", "assassin_execution"),
        ):
            state = create_battle_state(
                dict(slave_id=1, owner_id=1, class_id="assassin", level=20,
                     archclass_id=branch_id),
                dict(slave_id=2, owner_id=2, class_id="ragamuffin", level=20),
            )
            variant = effective_skill(state, "a", skill_id)
            self.assertNotEqual(variant.name, {"assassin_smoke": "Дымовой уход", "assassin_execution": "Перерезать нить"}[skill_id])
            self.assertEqual(ARCHCLASSES[branch_id]["class_id"], "assassin")
