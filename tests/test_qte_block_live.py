from copy import deepcopy
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from arena_engine import create_battle_state, resolve_skill, BUILTIN_SKILLS
from arena_qte_live import challenge
from arena_qte_rules import replay
from arena_qte_unique import review_catalog
from arena_qte_block import create, step
from database import Database
import test_arena


def traces(configs):
    result = subprocess.run(
        [shutil.which("node"), str(Path(__file__).with_name("qte_block_trace.cjs"))],
        input=json.dumps(configs),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return json.loads(result.stdout)


class BlockReplayTests(unittest.TestCase):
    def config(self, skill, **changes):
        return dict(
            version=3,
            kind="defense",
            defense_mode="block",
            profile=skill,
            seed=23,
            stats=dict(
                physicalDefense=35, magicDefense=20, enemyAttack=30, enemyAccuracy=85
            ),
            **changes
        )

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_js_python_replay_all_profiles_policies_and_disabled_strikes(self):
        configs = [
            self.config(skill, policy=policy)
            for skill in review_catalog()
            for policy in ("hold", "react", "sweep")
        ]
        multi = next(s for s in review_catalog() if s["strikes"] == 6)
        configs.append(
            self.config(
                multi,
                policy="react",
                enabled_strikes=[True, False, True, False, True, False],
            )
        )
        for c, trace in zip(configs, traces(configs), strict=True):
            actual = replay(c, trace["proof"], 20)
            self.assertEqual(
                actual["mask"],
                trace["result"]["mask"],
                (c["profile"]["name"], c["policy"]),
            )
            self.assertEqual(len(actual["contacts"]), len(trace["result"]["contacts"]))
            for a, b in zip(
                actual["contacts"], trace["result"]["contacts"], strict=True
            ):
                for field in ("id", "strike", "tier", "outcome", "blocked", "tick"):
                    self.assertEqual(
                        a[field], b[field], (c["profile"]["name"], c["policy"], a, b)
                    )
                self.assertAlmostEqual(a["weight"], b["weight"], places=9)
                self.assertAlmostEqual(a["reduction"], b["reduction"], places=9)

    def test_preparation_abort_and_invalid_input(self):
        c = self.config(review_catalog()[0])
        s = create(c)
        before = deepcopy(s)
        for _ in range(120):
            step(s, dict(active=True, angle=math.pi))
        self.assertEqual(s["angle"], before["angle"])
        self.assertEqual(s["stamina"], before["stamina"])
        self.assertEqual(s["contacts"], [])
        bad = [
            dict(ticks=1139, inputs=[]),
            dict(ticks=True, inputs=[]),
            dict(ticks=1140, inputs=[dict(t=0, active=True, angle=float("nan"))]),
            dict(ticks=1140, inputs=[dict(t=0, active=1, angle=0)]),
            dict(ticks=1140, inputs=[dict(t=0, active=True, angle=99)]),
            dict(ticks=1140, inputs=[dict(t=0, active=False, angle=0)] * 2),
        ]
        for proof in bad:
            with self.assertRaises(ValueError):
                replay(c, proof, 20)
        with self.assertRaises(ValueError):
            replay(c, dict(ticks=1140, inputs=[]), 0.1)
        abort = replay(c, dict(abort=True), 0)
        self.assertTrue(all(not contact["blocked"] for contact in abort["contacts"]))
        self.assertEqual(abort["mask"], [False] * c["profile"]["strikes"])

    def state(self, cls="middle", arch=""):
        s = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=3),
            dict(owner_id=20, slave_id=20, class_id=cls, archclass_id=arch, level=15),
        )
        for side in s["sides"].values():
            side["hp"] = side["stats"]["max_hp"] = 10000
        return s

    def test_perfect_block_is_not_dodge_and_keeps_defensive_charges_once(self):
        for cls, arch, counter, key in [
            ("middle", "middle_guardian", "mechanics", "grudge"),
            ("warrior", "warrior_knight", "rpg_state", "steadfast"),
            ("priest", "priest_paladin", "rpg_state", "retribution"),
        ]:
            s = self.state(cls, arch)
            contacts = [
                dict(id=str(i), strike=0, weight=0, blocked=True, outcome="perfect")
                for i in range(12)
            ]
            event = resolve_skill(
                s,
                "a",
                "bum_punch",
                rng=random.Random(2),
                qte=dict(
                    attack=[True],
                    dodge=[True],
                    pattern_dodge=dict(mode="block", contacts=contacts),
                ),
            )
            self.assertEqual(event["damage"], 0)
            self.assertFalse(event["hit"])
            self.assertFalse(event["dodged"])
            self.assertTrue(event["blocked"])
            self.assertEqual(s["sides"]["b"][counter][key], 1, (cls, s["sides"]["b"]))
            self.assertEqual(event["after"]["a"]["resource"], 100)
        s = self.state()
        event = resolve_skill(
            s,
            "a",
            "dust_in_eyes",
            qte=dict(
                attack=[True],
                dodge=[True],
                pattern_dodge=dict(mode="block", contacts=contacts),
            ),
        )
        self.assertFalse(any(e.get("id") == "dust" for e in s["sides"]["b"]["effects"]))

    def test_native_armor_applies_once_and_tiny_blocked_pellets_aggregate(self):
        s = self.state("ragamuffin")
        native = resolve_skill(
            deepcopy(s), "a", "bum_punch", rng=random.Random(2), qte=dict(attack=[True])
        )["damage"]
        contacts = [
            dict(id=str(i), strike=0, weight=0.025, blocked=True) for i in range(10)
        ]
        event = resolve_skill(
            deepcopy(s),
            "a",
            "bum_punch",
            rng=random.Random(2),
            qte=dict(
                attack=[True],
                dodge=[False],
                pattern_dodge=dict(mode="block", contacts=contacts),
            ),
        )
        self.assertEqual(event["damage"], math.floor(native * 0.25 + 0.5))
        self.assertLess(event["damage"], 10)
        miss = resolve_skill(
            deepcopy(s),
            "a",
            "bum_punch",
            rng=random.Random(2),
            qte=dict(
                attack=[False],
                dodge=[False],
                pattern_dodge=dict(mode="block", contacts=contacts),
            ),
        )
        self.assertEqual(miss["damage"], 0)
        self.assertFalse(miss["blocked"])


class BlockSettingsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown
    duel = test_arena.ArenaStoreTests.duel

    async def test_invalid_settings_are_atomic_and_disabled_minigames_skip_block(self):
        with self.assertRaises(ValueError):
            await self.db.arena_combat_settings(10, "false", defense_mode="block")
        self.assertEqual(
            await self.db.arena_combat_settings(10),
            dict(minigames=True, defense_mode="dodge", character_slot=1),
        )
        with self.assertRaises(ValueError):
            await self.db.arena_combat_settings(10, False, defense_mode="invalid")
        self.assertTrue((await self.db.arena_combat_settings(10))["minigames"])
        await self.db.arena_combat_settings(20, False, defense_mode="block")
        await self.db.arena_combat_settings(10, False)
        row = await self.duel()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", skill="bum_punch"
        )
        self.assertIsNone(await self.db.arena_qte_view("battle", row["token"], 20))
        state = json.loads(row["state_json"])
        self.assertEqual(state["sides"]["b"]["defense_mode"], "block")
        self.assertEqual(state["turn"], 2)

    async def test_per_slot_persistence_legacy_default_and_stale_slot_guard(self):
        self.assertEqual(
            (await self.db.arena_combat_settings(10))["defense_mode"], "dodge"
        )
        await self.db.arena_combat_settings(10, defense_mode="block", expected_slot=1)
        await self.db.arena_grant_character_slots(10, 1980056841)
        view = await self.db.arena_characters(10)
        await self.db.arena_select_character(1, 10, 2, view["revision"])
        self.assertEqual(
            (await self.db.arena_combat_settings(10))["defense_mode"], "dodge"
        )
        with self.assertRaises(ValueError):
            await self.db.arena_combat_settings(
                10, defense_mode="block", expected_slot=1
            )
        view = await self.db.arena_characters(10)
        await self.db.arena_select_character(1, 10, 1, view["revision"])
        await self.db.close()
        await self.db.connect()
        self.assertEqual(
            (await self.db.arena_combat_settings(10))["defense_mode"], "block"
        )

    async def test_mode_is_snapshotted_at_duel_start_and_not_changed_midfight(self):
        await self.db.arena_combat_settings(20, defense_mode="block", expected_slot=1)
        row = await self.duel()
        state = json.loads(row["state_json"])
        self.assertEqual(state["sides"]["b"]["defense_mode"], "block")
        await self.db.arena_combat_settings(20, defense_mode="dodge", expected_slot=1)
        row = await self.db.arena_get(row["token"])
        state = json.loads(row["state_json"])
        self.assertEqual(state["sides"]["b"]["defense_mode"], "block")
        c = challenge(
            "defense",
            state["sides"]["a"],
            state["sides"]["b"],
            BUILTIN_SKILLS["bum_punch"],
            20,
        )
        self.assertEqual(c["version"], 3)
        self.assertEqual(c["defense_mode"], "block")
        old = deepcopy(state["sides"]["b"])
        old.pop("defense_mode")
        self.assertEqual(
            challenge(
                "defense", state["sides"]["a"], old, BUILTIN_SKILLS["bum_punch"], 20
            )["version"],
            2,
        )

    async def test_real_pvp_guard_survives_restart_and_successful_block_has_priority(
        self,
    ):
        from test_arena_rebalance import FixedRoll

        await self.db.arena_combat_settings(10, False)
        await self.db.arena_combat_settings(20, defense_mode="block", expected_slot=1)
        row = await self.duel()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", skill="bum_punch"
        )
        c = (await self.db.arena_qte_view("battle", row["token"], 20))["challenge"]
        self.assertEqual(c["version"], 3)
        trace = traces([dict(c, policy="react")])[0]
        self.assertTrue(
            all(v["outcome"] == "perfect" for v in trace["result"]["contacts"])
        )
        await self.db.close()
        await self.db.connect()
        saved = (await self.db.arena_qte_view("battle", row["token"], 20))["challenge"]
        self.assertEqual(c["id"], saved["id"])
        self.assertEqual(c["seed"], saved["seed"])
        await self.db.arena_combat_settings(20, defense_mode="dodge", expected_slot=1)
        hp = json.loads(row["state_json"])["sides"]["b"]["hp"]
        with patch("arena_qte_live.time.time", return_value=c["expires"] - 0.5), patch(
            "arena_engine.random.SystemRandom", return_value=FixedRoll()
        ):
            row = await self.db.arena_interactive_action(
                row["token"],
                20,
                row["revision"],
                "qte",
                proof=trace["proof"],
                challenge_id=c["id"],
            )
        state = json.loads(row["state_json"])
        self.assertEqual(state["sides"]["b"]["hp"], hp)
        self.assertEqual(state["sides"]["b"]["defense_mode"], "block")
        self.assertTrue(state["log"][-1]["blocked"])
        self.assertFalse(state["log"][-1]["dodged"])
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(
                row["token"],
                20,
                row["revision"],
                "qte",
                proof=trace["proof"],
                challenge_id=c["id"],
            )

    async def test_raid_guard_for_lei_heng_and_kit_composite_uses_correct_groups(self):
        for boss, skill in [
            ("lei_heng", "lei_perfected_flurry"),
            ("kit", "kit_reflection"),
        ]:
            with self.subTest(boss=boss):
                await self.db.arena_combat_settings(
                    10, defense_mode="block", expected_slot=1
                )
                row = await self.db.arena_raid_create(1, 10, boss_id=boss, silent=True)
                row = await self.db.arena_raid_setup(
                    row["token"], 10, "start", expected_revision=row["revision"]
                )
                data = json.loads(row["data_json"])
                data["players"]["10"]["fighter"]["hp"] = 10000
                data["intent"].update(
                    skill=skill,
                    targets=["10"],
                    phase=1,
                    kind="kit" if boss == "kit" else "attack",
                )
                self.db.connection.execute(
                    "UPDATE arena_raids SET data_json=? WHERE token=?",
                    (json.dumps(data), row["token"]),
                )
                self.db.connection.commit()
                row = await self.db.arena_interactive_raid(
                    row["token"], 10, data["round"], "defend"
                )
                c = (await self.db.arena_qte_view("raid", row["token"], 10))[
                    "challenge"
                ]
                self.assertEqual(c["version"], 3)
                trace = traces([dict(c, policy="react")])[0]
                with patch("arena_qte_live.time.time", return_value=c["expires"] - 0.5):
                    row = await self.db.arena_interactive_raid(
                        row["token"],
                        10,
                        data["round"],
                        proof=trace["proof"],
                        challenge_id=c["id"],
                    )
                after = json.loads(row["data_json"])
                self.assertEqual(after["players"]["10"]["fighter"]["hp"], 10000)
                self.assertEqual(after["round"], 2)
                # End this disposable raid before creating the next one.
                await self.db.arena_interactive_raid(row["token"], 10, 2, "surrender")
