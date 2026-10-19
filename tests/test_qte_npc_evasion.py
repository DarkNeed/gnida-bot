"""Post-QTE NPC evasion, independent native strikes, and unchanged energy."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    create_battle_state,
    resolve_skill,
)
from arena_qte_live import damage_preview
from arena_raid_engine import AVAILABLE_BOSSES, create_raid_state, native_attack
from test_arena_rebalance import FixedRoll
import test_arena


class NpcEvasionTests(unittest.TestCase):
    def state(self, npc=True, evasion=50):
        state = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=3),
            dict(
                owner_id=0 if npc else 20,
                slave_id=0 if npc else 20,
                class_id="ragamuffin",
                level=3,
            ),
        )
        state["active_side"] = "a"
        for side in state["sides"].values():
            side["hp"] = side["stats"]["max_hp"] = 100000
            side["loadout"] = ["bum_punch", "dust_in_eyes"]
        state["sides"]["b"]["stats"]["evasion"] = evasion
        return state

    def test_chance_uses_effective_evasion_and_zero_has_no_free_dodge(self):
        for evasion, roll, avoided in [
            (0, 0, False),
            (50, 0.49, True),
            (50, 0.50, False),
            (100, 0.96, False),
        ]:
            with self.subTest(evasion=evasion, roll=roll):
                s = self.state(evasion=evasion)
                e = resolve_skill(
                    s, "a", "bum_punch", rng=FixedRoll(roll), qte=dict(attack=[True])
                )
                self.assertEqual(e["dodged"], avoided)
                self.assertEqual(e["hit"], not avoided)
        s = self.state(evasion=0)
        s["sides"]["b"]["effects"].append(
            dict(id="evade", kind="evasion_flat", value=50, duration=3)
        )
        self.assertTrue(
            resolve_skill(
                s, "a", "bum_punch", rng=FixedRoll(0.25), qte=dict(attack=[True])
            )["dodged"]
        )

    def test_npc_dodge_cancels_hostile_effect_but_pays_full_cost(self):
        s = self.state()
        e = resolve_skill(
            s, "a", "dust_in_eyes", rng=FixedRoll(0.1), qte=dict(attack=[True])
        )
        self.assertTrue(e["dodged"])
        self.assertEqual(e["damage"], 0)
        self.assertEqual(s["sides"]["b"]["effects"], [])
        self.assertEqual(s["sides"]["a"]["resource"], 80)
        resolve_skill(s, "b", "bum_punch", rng=FixedRoll(0.9))
        self.assertEqual(s["sides"]["a"]["resource"], 88)

    def test_each_successful_strike_rolls_independently_and_misses_do_not(self):
        s = self.state()
        skill = replace(BUILTIN_SKILLS["bum_punch"], tags=("six_strike",), cost=30)
        rolls = iter([0.99] * 6 + [0.1, 0.9, 0.1])
        rng = FixedRoll()
        rng.random = lambda: next(rolls)
        e = resolve_skill(
            s,
            "a",
            "bum_punch",
            {**BUILTIN_SKILLS, "bum_punch": skill},
            rng,
            qte=dict(attack=[True, True, False, True, False, False]),
        )
        self.assertEqual(
            [p["dodged"] for p in e["hit_results"]],
            [True, False, False, True, False, False],
        )
        self.assertEqual(
            [p["hit"] for p in e["hit_results"]],
            [False, True, False, False, False, False],
        )
        self.assertEqual(s["sides"]["a"]["resource"], 70)
        self.assertEqual(list(rolls), [])

    def test_pvp_qte_and_disabled_player_mode_are_unchanged(self):
        s = self.state(npc=False)
        self.assertTrue(
            resolve_skill(
                deepcopy(s),
                "a",
                "bum_punch",
                rng=FixedRoll(0.1),
                qte=dict(attack=[True]),
            )["hit"]
        )
        self.assertTrue(
            resolve_skill(
                deepcopy(s),
                "a",
                "bum_punch",
                rng=FixedRoll(0.1),
                qte=dict(attack=[True], luck_evasion=True),
            )["dodged"]
        )
        self.assertTrue(
            resolve_skill(
                deepcopy(s),
                "a",
                "bum_punch",
                rng=FixedRoll(0.1),
                qte=dict(attack=[True], dodge=[True]),
            )["dodged"]
        )

    def test_raid_adapter_and_preview_damage_do_not_confuse_dodge_with_zero_power(self):
        s = self.state()
        a, b = s["sides"].values()
        b["is_boss"] = True
        a["_qte_attack"] = [True]
        self.assertTrue(
            native_attack(a, b, "bum_punch", BUILTIN_SKILLS, FixedRoll(0.1))["dodged"]
        )
        a, b = self.state()["sides"].values()
        b["stats"]["evasion"] = 100
        preview = damage_preview(a, b, BUILTIN_SKILLS["bum_punch"])
        b["stats"]["evasion"] = 0
        self.assertGreater(preview, 0)
        self.assertEqual(preview, damage_preview(a, b, BUILTIN_SKILLS["bum_punch"]))

    def test_new_raid_bosses_have_nonzero_evasion(self):
        for boss in AVAILABLE_BOSSES:
            d = create_raid_state(
                [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
                [dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=20)],
                FIGHTER_CLASSES,
                BUILTIN_SKILLS,
                boss,
            )
            self.assertGreater(d["boss"]["stats"]["evasion"], 0, boss)


class NpcFlowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown

    async def test_real_wasteland_flow_preserves_npc_dodge_after_success(self):
        row = await self.db.arena_wasteland(1, 10, 10, personal=True)
        s = json.loads(row["state_json"])
        s["active_side"] = "a"
        s["sides"]["b"]["stats"]["evasion"] = 50
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(s), row["token"]),
        )
        self.db.connection.commit()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        c = (await self.db.arena_qte_view("battle", row["token"], 10))["challenge"]
        with patch(
            "arena_qte_live.replay", return_value=dict(mask=[True], weights=[1])
        ), patch("arena_engine.random.SystemRandom", return_value=FixedRoll(0.1)):
            row = await self.db.arena_interactive_action(
                row["token"], 10, row["revision"], "qte", proof={}, challenge_id=c["id"]
            )
        log = json.loads(row["state_json"])["log"]
        self.assertTrue(
            next(
                e
                for e in log
                if e.get("skill_id") == "bum_punch" and e.get("side") == "a"
            )["dodged"]
        )
