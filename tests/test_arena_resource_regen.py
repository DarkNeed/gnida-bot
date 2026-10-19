"""Native damage and turn-start resource regression tests; no live accounts."""

from copy import deepcopy
from dataclasses import replace
import random
import unittest

from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    create_battle_state,
    resolve_skill,
    restore_turn_resource,
    skip_turn,
    use_healing_potion,
)
from arena_raid_engine import create_raid_state, resolve_round
from arena_qte_patterns import attack_weights, profile
from arena_qte_unique import review_catalog


class TurnResourceTests(unittest.TestCase):
    def state(self, cls="ragamuffin", level=3):
        state = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id=cls, level=level),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=3),
        )
        for side in state["sides"].values():
            side["hp"] = side["stats"]["max_hp"] = 100000
            side["loadout"] = ["bum_punch", "dust_in_eyes"]
        state["active_side"] = "a"
        return state

    def test_every_class_regens_once_after_first_turn_and_ignores_legacy_stat(self):
        for cls in FIGHTER_CLASSES:
            with self.subTest(cls=cls):
                side = self.state(cls, 9)["sides"]["a"]
                side["resource"] = 0
                side["stats"]["resource_regen"] = 15
                self.assertEqual(restore_turn_resource(side), 0)
                side["own_turns"] = 1
                self.assertEqual(restore_turn_resource(side), 8)
                self.assertEqual(restore_turn_resource(side), 0)
                side = deepcopy(side)  # Saved/restored battle cannot claim it twice.
                self.assertEqual(restore_turn_resource(side), 0)
                side["own_turns"] += 1
                side["stats"]["resource_max"] = 200
                self.assertEqual(restore_turn_resource(side), 16)

    def test_cap_full_turn_marker_dead_and_boss_exclusions(self):
        side = self.state()["sides"]["a"]
        side["own_turns"] = 1
        self.assertEqual(restore_turn_resource(side), 0)
        side["resource"] = 50
        self.assertEqual(restore_turn_resource(side), 0)
        side["own_turns"] = 2
        side["resource"] = 98
        self.assertEqual(restore_turn_resource(side), 2)
        for field, value in (("hp", 0), ("is_boss", True)):
            excluded = deepcopy(side)
            excluded.update(own_turns=3, resource=0)
            excluded[field] = value
            self.assertEqual(restore_turn_resource(excluded), 0)

    def test_regen_happens_on_next_own_turn_not_after_skill_or_potion(self):
        state = self.state()
        a, b = state["sides"].values()
        a["resource"] = b["resource"] = 40
        resolve_skill(state, "a", "dust_in_eyes", rng=random.Random(2))
        self.assertEqual(a["resource"], 20)
        self.assertEqual(b["resource"], 40)  # Opponent's first turn.
        resolve_skill(state, "b", "dust_in_eyes", rng=random.Random(2))
        self.assertEqual(a["resource"], 28)
        self.assertEqual(b["resource"], 20)
        self.assertEqual(state["log"][-1]["after"]["a"]["resource"], 28)
        a["hp"] -= 20
        use_healing_potion(state, "a")
        self.assertEqual(a["resource"], 28)
        self.assertEqual(restore_turn_resource(a), 0)

    def test_timeout_and_stun_start_one_turn_without_free_refills(self):
        state = self.state()
        a, b = state["sides"].values()
        a.update(own_turns=1, resource=0)
        b.update(own_turns=1, resource=0)
        b["effects"].append(dict(id="stun", kind="stun", value=1, duration=1))
        skip_turn(state)
        self.assertEqual(a["resource"], 8)
        self.assertEqual(b["resource"], 8)
        self.assertEqual(state["active_side"], "a")
        self.assertEqual(restore_turn_resource(a), 0)
        resolve_skill(state, "a", "bum_punch", rng=random.Random(2))
        self.assertEqual(a["resource"], 8)
        self.assertEqual(b["resource"], 16)

    def test_raid_next_round_regen_defense_and_no_boss_or_withdrawn_refill(self):
        data = create_raid_state(
            [
                dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i)
                for i in (10, 20)
            ],
            [
                dict(owner_id=i, slave_id=i, class_id="ragamuffin", level=3)
                for i in (10, 20)
            ],
            FIGHTER_CLASSES,
            BUILTIN_SKILLS,
        )
        for fighter in [
            data["boss"],
            *(p["fighter"] for p in data["players"].values()),
        ]:
            fighter["hp"] = fighter["stats"]["max_hp"] = 100000
        player = data["players"]["10"]
        player["fighter"]["loadout"] = ["dust_in_eyes"]
        player["selected"] = "dust_in_eyes"
        data["boss"]["resource"] = 0
        withdrawn = data["players"]["20"]
        withdrawn.update(withdrawn=True)
        withdrawn["fighter"].update(resource=0, own_turns=1)
        data["intent"] = dict(kind="shield", phase=1, targets=[])
        resolve_round(data, BUILTIN_SKILLS, random.Random(2))
        self.assertEqual(player["fighter"]["resource"], 88)
        self.assertEqual(data["log"][-1]["after"]["10"]["resource"], 88)
        self.assertEqual(data["boss"]["resource"], 0)
        self.assertEqual(withdrawn["fighter"]["resource"], 0)
        player["selected"] = "defend"
        data["intent"] = dict(kind="shield", phase=1, targets=[])
        resolve_round(data, BUILTIN_SKILLS, random.Random(2))
        self.assertEqual(player["fighter"]["resource"], 96)

    def test_complete_and_partial_attack_marks_keep_native_integer_budget(self):
        for tags in (
            (),
            ("two_strike",),
            ("three_strike",),
            ("six_strike",),
            ("three_strike", "final_train"),
            ("three_strike", "final_execution"),
        ):
            n = (
                6
                if "six_strike" in tags
                else 3 if "three_strike" in tags else 2 if "two_strike" in tags else 1
            )
            skill = replace(BUILTIN_SKILLS["bum_punch"], power=40, tags=tags)
            skills = {**BUILTIN_SKILLS, "bum_punch": skill}
            for mask in ([True] * n, [i == n - 1 for i in range(n)], [False] * n):
                with self.subTest(tags=tags, mask=mask):
                    events = [
                        resolve_skill(
                            self.state(),
                            "a",
                            "bum_punch",
                            skills,
                            random.Random(2),
                            qte=dict(attack=mask, **extra),
                        )
                        for extra in ({}, dict(pattern_attack=dict(weights=[0.3] * n)))
                    ]
                    self.assertEqual(events[0]["damage"], events[1]["damage"])
                    self.assertEqual(events[0]["after"], events[1]["after"])

    def test_attack_shares_are_full_budget_and_native_finishers_not_projectile_weights(
        self,
    ):
        for skill in review_catalog():
            p = profile(skill)
            self.assertAlmostEqual(sum(attack_weights(p)), 1, msg=skill["name"])
        self.assertEqual(
            attack_weights(dict(strikes=3, skill=dict(tags=["final_train"]))),
            [0.2, 0.3, 0.5],
        )

    def test_reported_class_attacks_keep_full_damage_in_raid_adapter(self):
        from arena_qte_live import challenge
        from arena_qte_patterns import impact
        from arena_raid_engine import native_attack

        for cls, sid in (
            ("cutie", "uwu"),
            ("jock", "smack"),
            ("nerd", "humiliate"),
            ("thumb", "warning_shot"),
            ("mage", "mana_shot"),
        ):
            state = self.state(cls, 9)
            state["sides"]["a"]["loadout"] = [sid]
            skill = BUILTIN_SKILLS[sid]
            p = profile(
                challenge("attack", *state["sides"].values(), skill, 10)["profile"]
            )
            reference = resolve_skill(
                deepcopy(state), "a", sid, rng=random.Random(2), qte=dict(attack=[True])
            )
            a, b = deepcopy(state)["sides"].values()
            a["_qte_attack"] = [True]
            a["_qte_pattern_attack"] = dict(weights=[impact(p, 0)["weight"]])
            actual = native_attack(a, b, sid, BUILTIN_SKILLS, random.Random(2))
            self.assertEqual(actual["damage"], reference["damage"], sid)
            self.assertEqual(
                actual["after"]["a"]["resource"], reference["after"]["a"]["resource"]
            )


if __name__ == "__main__":
    unittest.main()
