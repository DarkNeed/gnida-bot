import json
import math
from pathlib import Path
import shutil
import subprocess
import unittest
from copy import deepcopy

from arena_qte_patterns import (
    profile,
    family,
    defense,
    prepare,
    duration,
    difficulty,
    defense_step,
)
from arena_qte_rules import replay
from arena_qte_unique import review_catalog
from arena_engine import create_battle_state, resolve_skill


class PatternReplayTests(unittest.TestCase):
    def test_defense_preparation_has_no_hazards_damage_or_early_movement(self):
        skill = next(s for s in review_catalog() if s["base_id"] == "warning_shot")
        c = self.config(skill)
        for command in (dict(x=1, y=1), dict(target=[700, 300])):
            s = defense(profile(skill), c["stats"], 23)
            start = deepcopy(s["player"])
            for _ in range(120):
                defense_step(s, command)
            self.assertEqual(s["player"], start)
            self.assertFalse(s["hazards"])
            self.assertFalse(s["contacts"])
            self.assertTrue(all(not e["ready"] for e in s["events"]))
            defense_step(s, command)
            self.assertNotEqual(s["player"]["x"], start["x"])
        self.assertAlmostEqual(duration(c), 7.8)
        with self.assertRaises(ValueError):
            replay(c, dict(ticks=816, inputs=[]), 30)

    def test_accuracy_evasion_have_strong_defense_contrast_without_slowing_player(self):
        high = difficulty(
            dict(accuracy=75, enemyEvasion=25, enemyAccuracy=100, evasion=0)
        )
        low = difficulty(
            dict(accuracy=75, enemyEvasion=25, enemyAccuracy=50, evasion=75)
        )
        self.assertAlmostEqual(high["warning"], 0.32)
        self.assertAlmostEqual(low["warning"], 0.90)
        self.assertAlmostEqual(high["speed"], 750)
        self.assertAlmostEqual(low["speed"], 400)
        self.assertLess(high["gap"], low["gap"])
        self.assertGreater(high["lead"], low["lead"])
        self.assertEqual(high["moveSpeed"], low["moveSpeed"])
        self.assertEqual(
            high["zone"], low["zone"], "defense tuning must not alter attack timing"
        )

    def test_bum_basic_has_three_small_windups_without_shockwaves(self):
        skill = next(s for s in review_catalog() if s["name"] == "Удар бомжа")
        c = self.config(skill)
        s = defense(profile(skill), dict(c["stats"], enemyAccuracy=100, evasion=0), 23)
        self.assertEqual(len(s["events"]), 3)
        self.assertGreaterEqual(s["d"]["warning"], 0.66)
        for event in s["events"]:
            prepare(s, event)
        self.assertTrue(
            all(h["type"] == "circle" and h["r"] <= 32 for h in s["hazards"])
        )
        mastery = next(s for s in review_catalog() if s["name"] == "Уличный ответ")
        advanced = defense(profile(mastery), c["stats"], 23)
        prepare(advanced, advanced["events"][0])
        self.assertTrue(any(h["type"] == "ring" for h in advanced["hazards"]))

    def test_requested_classes_have_crossfire_and_alternating_patterns(self):
        stats = dict(accuracy=75, enemyEvasion=25, enemyAccuracy=100, evasion=0)
        catalog = review_catalog()

        def trial(ident):
            skill = next(
                s
                for s in catalog
                if s["base_id"] == ident and s["origin"] == "Базовый навык"
            )
            return defense(profile(skill), stats, 23)

        soldier = trial("warning_shot")
        prepare(soldier, soldier["events"][0])
        bullets = [h for h in soldier["hazards"] if h["type"] == "bullet"]
        self.assertEqual(len(bullets), 12)
        self.assertTrue(
            any(h["vx"] > 0 for h in bullets) and any(h["vx"] < 0 for h in bullets)
        )
        self.assertGreater(len({h["start"] for h in bullets}), 1)
        edict = trial("first_line")
        prepare(edict, edict["events"][0])
        prepare(edict, edict["events"][1])
        first = [
            h for h in edict["hazards"] if h["index"] == 0 and h["tier"] == "heavy"
        ]
        second = [
            h for h in edict["hazards"] if h["index"] == 1 and h["tier"] == "heavy"
        ]
        self.assertTrue(all(h["ay"] == h["by"] for h in first))
        self.assertTrue(all(h["ax"] == h["bx"] for h in second))
        stars = trial("moon_arc")
        prepare(stars, stars["events"][0])
        self.assertTrue(any(h.get("turn") for h in stars["hazards"]))
        self.assertTrue(
            any(h["type"] == "bullet" and not h.get("turn") for h in stars["hazards"])
        )

    def config(self, skill, kind="defense", **changes):
        return dict(
            version=2,
            defense_preparation=1,
            profile=skill,
            kind=kind,
            seed=23,
            strikes=skill["strikes"],
            stats=dict(accuracy=75, enemyEvasion=25, enemyAccuracy=95, evasion=10),
            **changes
        )

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_actual_js_traces_match_python_for_entire_catalog_and_kit(self):
        catalog = review_catalog()
        configs = []
        families = {}
        for skill in catalog:
            families[family(skill)] = skill
            configs.append(self.config(skill))
            configs.append(self.config(skill, "attack", retry=True))
        for skill in families.values():
            for evasion in (0, 100):
                c = self.config(skill)
                c["seed"] = 29
                c["stats"].update(evasion=evasion, accuracy=45, enemyEvasion=70)
                configs.extend((c, dict(c, kind="attack")))
        multi = next(s for s in catalog if s["strikes"] == 6)
        configs.append(
            dict(
                self.config(multi),
                enabled_strikes=[True, False, True, False, True, False],
            )
        )
        legacy = self.config(multi)
        legacy.pop("defense_preparation")
        self.assertAlmostEqual(duration(legacy), 6.8)
        configs.append(legacy)
        result = subprocess.run(
            [
                shutil.which("node"),
                str(Path(__file__).with_name("qte_patterns_trace.cjs")),
            ],
            input=json.dumps(configs),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for c, trace in zip(configs, json.loads(result.stdout), strict=True):
            self.assertEqual(
                replay(c, trace["proof"], 30),
                trace["result"],
                (c["profile"]["name"], c["kind"], c["stats"]),
            )

    def test_kit_is_only_slightly_faster_with_same_projectile_weights(self):
        s = next(s for s in review_catalog() if s["base_id"] == "kit_eclipse")
        p = profile(s)
        c = self.config(s)
        hard = defense(p, c["stats"], 23)
        easy = defense(dict(p, kit=False), c["stats"], 23)
        self.assertAlmostEqual(hard["d"]["warning"] / easy["d"]["warning"], 0.92)
        self.assertAlmostEqual(hard["d"]["speed"] / easy["d"]["speed"], 1.08)
        self.assertLess(hard["events"][-1]["at"], easy["events"][-1]["at"])
        prepare(hard, hard["events"][0])
        prepare(easy, easy["events"][0])
        self.assertEqual(
            [h["weight"] for h in hard["hazards"]],
            [h["weight"] for h in easy["hazards"]],
        )

    def test_untrusted_results_fast_forward_spam_and_aborts(self):
        s = next(s for s in review_catalog() if s["base_id"] == "bum_punch")
        c = self.config(s, "attack")
        for proof, elapsed in (
            (dict(ticks=200, clicks=[]), 0),
            (dict(ticks=1, clicks=[1]), 30),
            (dict(ticks=300, clicks=[160, 160]), 30),
            (dict(ticks=300, clicks=[160, 161]), 30),
            (dict(ticks=0, clicks=[], result=True), 30),
        ):
            with self.assertRaises(ValueError):
                replay(c, proof, elapsed)
        self.assertEqual(replay(c, dict(abort=True), 0)["mask"], [False])
        c["kind"] = "defense"
        for events in (
            [dict(t=0, x=float("nan"))],
            [dict(t=0, target=[721, 0])],
            [dict(t=1), dict(t=1)],
        ):
            with self.assertRaises(ValueError):
                replay(c, dict(ticks=936, inputs=events), 30)
        with self.assertRaises(ValueError):
            replay(c, dict(ticks=815, inputs=[]), 30)
        worst = replay(c, dict(abort=True), 0)
        actual = replay(c, dict(ticks=936, inputs=[]), 30)
        self.assertGreaterEqual(
            sum(h["weight"] for h in worst["contacts"]),
            sum(h["weight"] for h in actual["contacts"]),
        )
        self.assertEqual(
            len(worst["contacts"]), len({h["id"] for h in worst["contacts"]})
        )

    def test_weighted_contacts_not_normalized_and_effects_still_once(self):
        state = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=3),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=3),
        )
        state["sides"]["b"]["hp"] = 10000
        import random

        normal = resolve_skill(
            deepcopy(state),
            "a",
            "bum_punch",
            rng=random.Random(2),
            qte=dict(attack=[True]),
        )
        c = [
            dict(id=str(i), strike=0, weight=w)
            for i, w in enumerate((0.1, 0.3, 0.6, 1))
        ]
        event = resolve_skill(
            deepcopy(state),
            "a",
            "bum_punch",
            rng=random.Random(2),
            qte=dict(attack=[True], dodge=[False], pattern_dodge=dict(contacts=c)),
        )
        self.assertGreater(event["damage"], normal["damage"])
        self.assertEqual(len(event["qte_projectiles"]), 4)
        self.assertEqual(
            sum(h["damage"] for h in event["qte_projectiles"]), event["damage"]
        )
        self.assertEqual(
            event["after"]["a"]["resource"], normal["after"]["a"]["resource"]
        )
        clean = resolve_skill(
            deepcopy(state),
            "a",
            "dust_in_eyes",
            qte=dict(attack=[True], dodge=[True], pattern_dodge=dict(contacts=[])),
        )
        self.assertFalse(clean["hit"])
        self.assertTrue(clean["dodged"])
        self.assertEqual(clean["damage"], 0)

    def test_kit_composite_guard_does_not_repeat_contacts_for_second_action(self):
        from arena_raid_engine import create_raid_state, resolve_round
        from arena_engine import FIGHTER_CLASSES, BUILTIN_SKILLS
        import random

        for group in (0, 1):
            data = create_raid_state(
                [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
                [dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=20)],
                FIGHTER_CLASSES,
                BUILTIN_SKILLS,
                "kit",
            )
            player = data["players"]["10"]
            player["fighter"]["hp"] = 10000
            player["selected"] = "defend"
            data["intent"] = dict(
                kind="kit", skill="kit_reflection", phase=1, targets=["10"]
            )
            player["qte_result"] = dict(
                dodge=[group != 0, group != 1],
                guard_skill="kit_reflection",
                guard_subskills=["kit_reflection", "kit_ash"],
                pattern_dodge=dict(
                    contacts=[
                        dict(id="only-contact", strike=group, weight=0.6, tier="heavy")
                    ]
                ),
            )
            resolve_round(data, BUILTIN_SKILLS, random.Random(2))
            events = [
                e
                for e in data["log"]
                if e.get("skill") in ("kit_reflection", "kit_ash")
            ]
            self.assertEqual(len(events), 2)
            self.assertGreater(events[group]["damage"], 0, (group, events))
            self.assertEqual(events[1 - group]["damage"], 0)

    def test_attack_only_weights_are_used_but_disabled_combat_is_unchanged(self):
        import random

        state = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=3),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=3),
        )
        normal = resolve_skill(
            deepcopy(state),
            "a",
            "bum_punch",
            rng=random.Random(2),
            qte=dict(attack=[True]),
        )
        active = resolve_skill(
            deepcopy(state),
            "a",
            "bum_punch",
            rng=random.Random(2),
            qte=dict(attack=[True], pattern_attack=dict(weights=[0.6])),
        )
        self.assertEqual(
            active["damage"], max(1, math.floor(normal["damage"] * 0.6 + 0.5))
        )
        self.assertEqual(len(active["qte_projectiles"]), 1)
        self.assertNotIn("qte_projectiles", normal)

    def test_weighted_finisher_keeps_native_armor_piercing(self):
        from dataclasses import replace
        from arena_engine import BUILTIN_SKILLS
        import random

        state = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=3),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=3),
        )
        state["sides"]["b"]["hp"] = 10000
        state["sides"]["b"]["stats"]["physical_defense"] = 80
        qte = dict(attack=[False, False, True], pattern_attack=dict(weights=[0, 0, 1]))
        damage = []
        for tags in (("three_strike",), ("three_strike", "final_train")):
            skill = replace(BUILTIN_SKILLS["bum_punch"], power=40, tags=tags)
            event = resolve_skill(
                deepcopy(state),
                "a",
                "bum_punch",
                skills={**BUILTIN_SKILLS, "bum_punch": skill},
                rng=random.Random(2),
                qte=qte,
            )
            damage.append(event["damage"])
        self.assertGreater(damage[1], damage[0])


if __name__ == "__main__":
    unittest.main()
