"""Whaler encounter and trophy against disposable data, including reaction resume."""

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
    _tick,
    fighter_xp_limit,
    restore_turn_resource,
)
from arena_plague import infect, clear, begin_turn
from arena_raid_engine import create_raid_state, resolve_round
from arena_whaler import set_intent
from test_arena_rebalance import FixedRoll
import test_arena


def encounter(size=1):
    members = [
        dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i)
        for i in (10, 20, 30)[:size]
    ]
    sources = [
        dict(
            owner_id=p["actor_id"],
            slave_id=p["actor_id"],
            class_id="mage",
            level=20,
            loadout=["mana_shot", "mana_focus"],
        )
        for p in members
    ]
    return create_raid_state(
        members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, "whaler"
    )


class WhalerTests(unittest.TestCase):
    def test_landed_miasma_advances_round_and_logs_each_plague_tick(self):
        for size in (1, 3):
            with self.subTest(size=size):
                d = encounter(size)
                d['round'] = 3
                set_intent(d)
                for player in d['players'].values():
                    player['fighter']['hp'] = player['fighter']['stats']['max_hp'] = 1000
                    player['fighter']['resource'] = 50
                    player['selected'] = 'defend'
                resolve_round(d, BUILTIN_SKILLS, FixedRoll())
                self.assertEqual(d['round'], 4)
                attacks = [e for e in d['log'] if e.get('skill') == 'whaler_miasma']
                ticks = [e for e in d['log'] if e['round'] == 4]
                self.assertEqual(len(attacks), size)
                self.assertTrue(all(e['hit'] for e in attacks))
                self.assertEqual(len(ticks), size)
                self.assertIn('before', ticks[0])
                for tick in ticks:
                    key = tick['target']
                    self.assertEqual(tick['damage'], 6)
                    self.assertEqual(tick['after'][key]['hp'],
                                     attacks[-1]['after'][key]['hp'] - 6)
                self.assertNotIn('round_before', d)
                # Saved/reloaded raids must continue rather than replay the
                # previous miasma or apply its start-of-turn damage twice.
                d = json.loads(json.dumps(d))
                for player in d['players'].values():
                    player['selected'] = 'defend'
                resolve_round(d, BUILTIN_SKILLS, FixedRoll())
                self.assertEqual(d['round'], 5)
                self.assertEqual(len([e for e in d['log'] if e['round'] == 5]), size)

    def test_fixed_hp_no_armor_and_party_gate(self):
        for size, hp in [(1, 600), (2, 900), (3, 1200)]:
            d = encounter(size)
            self.assertEqual(d["boss"]["hp"], hp)
            self.assertEqual(d["boss"]["stats"]["physical_defense"], 0)
            self.assertEqual(d["boss"]["stats"]["magic_defense"], 0)
            self.assertEqual(d["boss"]["stats"]["evasion"], 5)
        with self.assertRaises(ValueError):
            create_raid_state(
                [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
                [dict(owner_id=10, slave_id=10, class_id="mage", level=19)],
                FIGHTER_CLASSES,
                BUILTIN_SKILLS,
                "whaler",
            )

    def test_plague_ticks_once_at_start_refreshes_and_spores_cap(self):
        s = encounter()["players"]["10"]["fighter"]
        s["hp"] = s["stats"]["max_hp"] = 1000
        for _ in range(5):
            infect(s)
        self.assertEqual(
            next(e["value"] for e in s["effects"] if e["kind"] == "plague_spores"), 3
        )
        for _ in range(5):
            self.assertEqual(begin_turn(s), 8)
            self.assertEqual(begin_turn(s), 0)
            _tick(s, tick_dot=False)
        self.assertEqual(begin_turn(s), 3)
        self.assertFalse(any(e["kind"] == "plague_fever" for e in s["effects"]))

    def test_actual_restoration_clears_but_passive_regen_does_not(self):
        state = create_battle_state(
            dict(
                owner_id=10,
                slave_id=10,
                class_id="mage",
                level=20,
                loadout=["mana_focus"],
            ),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=20),
        )
        actor = state["sides"]["a"]
        actor.update(resource=97, own_turns=1)
        infect(actor)
        restore_turn_resource(actor)
        self.assertTrue(any(e["kind"] == "plague_fever" for e in actor["effects"]))
        actor["resource"] = 97
        event = resolve_skill(
            state, "a", "mana_focus", rng=FixedRoll(), advance_turn=False
        )
        self.assertEqual(event["deliberate_resource_restored"], 3)
        self.assertFalse(any(e["kind"].startswith("plague_") for e in actor["effects"]))

    def test_trophy_hybrid_damage_duration_cost_and_counterplay(self):
        skill = BUILTIN_SKILLS["swamp_miasma"]
        self.assertEqual((skill.cost, skill.cooldown, skill.unlock_level), (40, 3, 20))
        s = create_battle_state(
            dict(
                owner_id=10,
                slave_id=10,
                class_id="jock",
                level=20,
                loadout=[skill.skill_id],
                granted_skills=[skill.skill_id],
            ),
            dict(
                owner_id=20,
                slave_id=20,
                class_id="mage",
                level=20,
                loadout=["mana_focus"],
            ),
        )
        event = resolve_skill(
            s, "a", skill.skill_id, rng=FixedRoll(), qte=dict(attack=[True])
        )
        self.assertGreater(event["damage"], 0)
        self.assertEqual(s["sides"]["a"]["resource"], 60)
        fever = next(
            e for e in s["sides"]["b"]["effects"] if e["kind"] == "plague_fever"
        )
        self.assertEqual((fever["value"], fever["duration"]), (3, 3))
        s["sides"]["b"]["resource"] = 50
        resolve_skill(s, "b", "mana_focus", rng=FixedRoll())
        self.assertFalse(
            any(e["kind"].startswith("plague_") for e in s["sides"]["b"]["effects"])
        )

    def test_healing_removes_one_spore_and_cleanse_removes_both(self):
        from arena_epic import cleanse_one

        s = create_battle_state(
            dict(
                owner_id=10,
                slave_id=10,
                class_id="ragamuffin",
                level=20,
                loadout=["bum_punch"],
            ),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=20),
        )
        actor = s["sides"]["a"]
        actor["hp"] = 20
        for _ in range(3):
            infect(actor)
        skill = replace(
            BUILTIN_SKILLS["bum_punch"],
            damage_type=None,
            power=0,
            effects=(dict(id="heal", kind="heal_pct", value=0.1, target="self"),),
        )
        resolve_skill(
            s,
            "a",
            "bum_punch",
            {"bum_punch": skill},
            rng=FixedRoll(),
            advance_turn=False,
        )
        self.assertEqual(
            next(e["value"] for e in actor["effects"] if e["kind"] == "plague_spores"),
            2,
        )
        self.assertTrue(cleanse_one(actor, FixedRoll()))
        self.assertFalse(any(e["kind"].startswith("plague_") for e in actor["effects"]))

    def test_single_largest_restore_and_resume_never_repeats_actions(self):
        d = encounter(3)
        d["qte_modes"] = {"10": True, "20": True, "30": False}
        for key, p in d["players"].items():
            p["selected"] = "mana_focus"
            p["fighter"]["resource"] = {"10": 50, "20": 70, "30": 80}[key]
            p["fighter"]["hp"] = p["fighter"]["stats"]["max_hp"] = 1000
        resolve_round(d, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(d["whaler_restored"], {"10": 35, "20": 30, "30": 20})
        self.assertEqual(d["whaler_reaction"]["target"], "10")
        self.assertEqual(d["round"], 1)
        self.assertEqual(d["players"]["10"]["fighter"]["resource"], 85)
        d = json.loads(json.dumps(d))
        d["whaler_reaction"]["result"] = dict(dodge=[True, True])
        resolve_round(d, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(d["round"], 2)
        self.assertEqual(d["players"]["10"]["fighter"]["own_turns"], 1)
        self.assertEqual(d["players"]["10"]["fighter"]["resource"], 93)
        self.assertEqual(
            len([e for e in d["log"] if e.get("skill") == "mana_focus"]), 3
        )
        self.assertEqual(
            len(
                [
                    e
                    for e in d["log"]
                    if e.get("skill", "").startswith("whaler_punishment")
                ]
            ),
            2,
        )

    def test_ritual_once_actual_restoration_interrupts_and_never_triggers_kara(self):
        d = encounter()
        d["boss"]["hp"] = 150
        set_intent(d)
        self.assertEqual(d["intent"]["ritual_target"], 30)
        p = d["players"]["10"]
        p["selected"] = "mana_focus"
        p["fighter"]["resource"] = 70
        resolve_round(d, BUILTIN_SKILLS, FixedRoll())
        self.assertTrue(any("Ритуал гнили сорван" in e["text"] for e in d["log"]))
        self.assertFalse(
            any(e.get("skill", "").startswith("whaler_punishment") for e in d["log"])
        )
        self.assertNotEqual(d["intent"]["skill"], "whaler_rot")

    def test_zero_actual_gain_does_not_provoke_reaction(self):
        d = encounter()
        d["players"]["10"]["selected"] = "mana_focus"
        resolve_round(d, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(d["round"], 2)
        self.assertFalse(
            any(e.get("skill", "").startswith("whaler_punishment") for e in d["log"])
        )


class WhalerStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown

    async def ready(self):
        self.db._arena_profile_locked(1, 10, True)
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, fighter_xp_limit())
        self.db.connection.execute(
            "UPDATE personal_profiles SET class_id='mage',progression_level=20,loadout='[\"mana_focus\",\"mana_shot\"]' WHERE chat_id=0 AND user_id=10"
        )
        self.db.connection.commit()
        row = await self.db.arena_raid_create(1, 10, "whaler", silent=True)
        row = await self.db.arena_raid_setup(
            row["token"], 10, "start", expected_revision=row["revision"]
        )
        d = json.loads(row["data_json"])
        d["players"]["10"]["fighter"]["resource"] = 50
        self.db._raid_save_locked(row, d)
        self.db.connection.commit()
        return await self.db.arena_raid_get(row["token"])

    async def complete(self, row, mask):
        c = (await self.db.arena_qte_view("raid", row["token"], 10))["challenge"]
        with patch("arena_qte_live.replay", return_value=dict(mask=mask, contacts=[])):
            return await self.db.arena_interactive_raid(
                row["token"], 10, 1, proof={}, challenge_id=c["id"]
            )

    async def test_miasma_qte_completion_commits_next_round_and_survives_restart(self):
        row = await self.ready()
        d = json.loads(row['data_json'])
        d['round'] = 3
        d['players']['10']['fighter']['hp'] = 1000
        d['players']['10']['fighter']['stats']['max_hp'] = 1000
        set_intent(d)
        self.db._raid_save_locked(row, d)
        self.db.connection.commit()
        row = await self.db.arena_interactive_raid(row['token'], 10, 3, 'defend')
        c = (await self.db.arena_qte_view('raid', row['token'], 10))['challenge']
        with patch('arena_qte_live.replay', return_value=dict(mask=[False], contacts=[])):
            row = await self.db.arena_interactive_raid(
                row['token'], 10, 3, proof={}, challenge_id=c['id'])
        saved = json.loads(row['data_json'])
        self.assertEqual(row['round'], 4)
        self.assertEqual(saved['round'], 4)
        self.assertEqual(len([e for e in saved['log'] if e['round'] == 4]), 1)
        self.assertEqual(saved['log'][-1]['damage'], 6)
        self.assertIsNone(await self.db.arena_qte_view('raid', row['token'], 10))
        await self.db.close()
        await self.db.connect()
        loaded = await self.db.arena_raid_get(row['token'])
        self.assertEqual(loaded['round'], 4)
        self.assertEqual(json.loads(loaded['data_json']), saved)

    async def test_reaction_expiry_does_not_repeat_restoration(self):
        row = await self.ready()
        row = await self.db.arena_interactive_raid(row["token"], 10, 1, "mana_focus")
        row = await self.complete(row, [True])
        c = (await self.db.arena_qte_view("raid", row["token"], 10))["challenge"]
        with patch("arena_qte_live.time.time", return_value=c["expires"] + 1):
            await self.db.arena_qte_refresh("raid", row["token"])
        d = json.loads((await self.db.arena_raid_get(row["token"]))["data_json"])
        self.assertTrue(d["finished"] or d["round"] == 2)
        self.assertEqual(d["players"]["10"]["fighter"]["own_turns"], 1)
        self.assertEqual(
            len([e for e in d["log"] if e.get("skill") == "mana_focus"]), 1
        )
        self.assertIsNone(await self.db.arena_qte_view("raid", row["token"], 10))

    async def test_surrender_during_reaction_and_loot_definition(self):
        row = await self.ready()
        row = await self.db.arena_interactive_raid(row["token"], 10, 1, "mana_focus")
        row = await self.complete(row, [True])
        row = await self.db.arena_interactive_raid(row["token"], 10, 1, "surrender")
        d = json.loads(row["data_json"])
        self.assertTrue(d["finished"])
        self.assertFalse(d["won"])
        self.assertIsNone(await self.db.arena_qte_view("raid", row["token"], 10))
        row = await self.db.arena_raid_create(1, 10, "whaler", silent=True)
        row = await self.db.arena_raid_setup(
            row["token"], 10, "start", expected_revision=row["revision"]
        )
        d = json.loads(row["data_json"])
        d.update(finished=True, won=True, result="Победа")
        d["boss"]["hp"] = 0
        d["players"]["10"]["manual_turns"] = 2
        with patch("arena_raid.random.SystemRandom", return_value=FixedRoll()):
            self.db._raid_finish_locked(row, d)
        self.db.connection.commit()
        self.assertEqual(d["rewards"]["10"]["loot"], "Миазмы")
        self.assertTrue(
            self.db.connection.execute(
                "SELECT 1 FROM arena_inventory WHERE content_id='swamp_miasma'"
            ).fetchone()
        )


class WhalerControlTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown
    ready = WhalerStoreTests.ready
    complete = WhalerStoreTests.complete

    async def test_ally_leaving_cannot_skip_someone_elses_pending_defense(self):
        row = await self.ready()
        d = json.loads(row["data_json"])
        other = deepcopy(d["players"]["10"])
        other.update(actor_id=20, fighter_id=20, slave_owner=20, selected="defend")
        other["fighter"]["controller_id"] = 20
        d["players"]["20"] = other
        d["qte_modes"]["20"] = False
        self.db.connection.execute(
            "INSERT INTO arena_raid_players VALUES(?,?,?,?,?)",
            (row["token"], 20, 20, 1, 20),
        )
        self.db._raid_save_locked(row, d)
        self.db.connection.commit()
        row = await self.db.arena_interactive_raid(row["token"], 10, 1, "mana_focus")
        row = await self.complete(row, [True])
        c = (await self.db.arena_qte_view("raid", row["token"], 10))["challenge"]
        row = await self.db.arena_interactive_raid(row["token"], 20, 1, "surrender")
        d = json.loads(row["data_json"])
        self.assertIn("whaler_reaction", d)
        self.assertEqual(d["players"]["10"]["fighter"]["resource"], 85)
        self.assertEqual(
            (await self.db.arena_qte_view("raid", row["token"], 10))["challenge"]["id"],
            c["id"],
        )
        row = await self.complete(row, [True, True])
        self.assertEqual(json.loads(row["data_json"])["round"], 2)

    def test_trophy_does_not_slow_controls_boss_miasma_and_kara_do(self):
        from arena_qte_live import challenge
        from arena_whaler import WHALER_SKILLS
        from arena_qte_patterns import difficulty
        from arena_qte_block import parameters

        d = encounter()
        a = d["boss"]
        b = d["players"]["10"]["fighter"]
        infect(b, fever=3, turns=3)
        c = challenge("defense", a, b, WHALER_SKILLS["whaler_harpoon"], 10)
        self.assertNotIn("controlScale", c["stats"])
        infect(b, viscous=True)
        c = challenge("defense", a, b, WHALER_SKILLS["whaler_harpoon"], 10)
        self.assertEqual(c["stats"]["controlScale"], 0.8)
        self.assertEqual(difficulty(c["stats"])["moveSpeed"], 192)
        b["defense_mode"] = "block"
        c = challenge("defense", a, b, WHALER_SKILLS["whaler_punishment"], 10)
        import math

        self.assertAlmostEqual(
            parameters(dict(skill=c["profile"]), c["stats"])["rotation"],
            math.pi * 4 * 0.8,
        )

    def test_slowed_simulations_are_identical_on_server_and_browser(self):
        import subprocess, shutil
        from pathlib import Path
        from arena_qte_live import challenge
        from arena_qte_rules import replay
        from arena_whaler import WHALER_SKILLS

        d = encounter()
        a = d["boss"]
        b = d["players"]["10"]["fighter"]
        for mode, script in [
            ("dodge", "qte_patterns_trace.cjs"),
            ("block", "qte_block_trace.cjs"),
        ]:
            b["defense_mode"] = mode
            c = challenge("defense", a, b, WHALER_SKILLS["whaler_punishment"], 10)
            c["policy"] = "sweep"
            r = subprocess.run(
                [shutil.which("node"), str(Path(__file__).with_name(script))],
                input=json.dumps([c]),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            trace = json.loads(r.stdout)[0]
            result = replay(c, trace["proof"], 30)
            self.assertEqual(result["mask"], trace["result"]["mask"])
            self.assertEqual(len(result["contacts"]), len(trace["result"]["contacts"]))
            for x, y in zip(result["contacts"], trace["result"]["contacts"]):
                self.assertEqual(x["id"], y["id"])
                self.assertEqual(x["tick"], y["tick"])
                self.assertAlmostEqual(x["weight"], y["weight"], places=8)

    async def test_level_gate(self):
        with self.assertRaises(ValueError):
            await self.db.arena_raid_create(1, 10, "whaler", silent=True)

    async def test_dynamic_reaction_saved_after_actions_restart_and_one_time_completion(
        self,
    ):
        row = await self.ready()
        row = await self.db.arena_interactive_raid(row["token"], 10, 1, "mana_focus")
        row = await self.complete(row, [True])
        d = json.loads(row["data_json"])
        self.assertEqual(d["players"]["10"]["selected"], "mana_focus")
        self.assertEqual(d["players"]["10"]["fighter"]["resource"], 85)
        c = (await self.db.arena_qte_view("raid", row["token"], 10))["challenge"]
        self.assertEqual(c["name"], "Кара болот")
        self.assertEqual(c["strikes"], 2)
        await self.db.close()
        await self.db.connect()
        self.assertEqual(
            (await self.db.arena_qte_view("raid", row["token"], 10))["challenge"]["id"],
            c["id"],
        )
        row = await self.complete(row, [True, True])
        d = json.loads(row["data_json"])
        self.assertEqual(d["round"], 2)
        self.assertEqual(d["players"]["10"]["fighter"]["resource"], 93)
        self.assertEqual(d["players"]["10"]["fighter"]["own_turns"], 1)
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_raid(
                row["token"], 10, 1, proof={}, challenge_id=c["id"]
            )
