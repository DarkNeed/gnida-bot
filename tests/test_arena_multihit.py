"""Six real hit checks, with action-level costs, effects and passive bookkeeping."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from dataclasses import replace

from arena_engine import BUILTIN_SKILLS, create_battle_state, resolve_skill


class Rolls:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def random(self):
        self.calls += 1
        return next(self.values)

    def uniform(self, low, high):
        return 1


class MultiHitTests(unittest.TestCase):
    def battle(self):
        state = create_battle_state(
            dict(slave_id=1, owner_id=1, class_id="middle", level=17,
                 loadout=["tigerslayer_flurry"], granted_skills=["tigerslayer_flurry"]),
            dict(slave_id=2, owner_id=2, class_id="cutie", level=17),
        )
        a, b = state["sides"].values()
        a["own_turns"] = 2
        b["hp"] = b["stats"]["max_hp"] = 10000
        return state

    def tap(self, state, rolls, catalog=None):
        return resolve_skill(state, "a", "tigerslayer_flurry", skills=catalog,
                             rng=rolls, advance_turn=False)

    def test_independent_hits_dodges_misses_and_sum(self):
        state = self.battle()
        rng = Rolls([0, .8, .99, 0, .8, .99])
        event = self.tap(state, rng)
        self.assertEqual(rng.calls, 6)
        self.assertEqual([p["hit"] for p in event["hit_results"]],
                         [True, False, False, True, False, False])
        self.assertEqual([p["dodged"] for p in event["hit_results"]],
                         [False, True, False, False, True, False])
        self.assertEqual(event["damage"], sum(event["hits"]))
        self.assertEqual(state["sides"]["b"]["hp"], 10000 - event["damage"])
        self.assertIn("попаданий 2/6, уклонений 2, промахов 2", event["text"])

    def test_full_hit_budget_is_not_six_times_the_original_damage(self):
        state = self.battle()
        reference = copy.deepcopy(state)
        catalog = BUILTIN_SKILLS | {"tigerslayer_flurry": replace(
            BUILTIN_SKILLS["tigerslayer_flurry"], tags=("raid_loot", "third_action"))}
        original = self.tap(reference, Rolls([0]), catalog)
        series = self.tap(state, Rolls([0] * 6))
        self.assertEqual(series["damage"], original["damage"])
        self.assertLessEqual(max(series["hits"]) - min(series["hits"]), 1)

    def test_all_misses_still_cost_one_action_and_do_not_feed_revenge(self):
        state = self.battle()
        b = state["sides"]["b"]
        b["passive_details"] = state["sides"]["a"]["passive_details"]
        event = self.tap(state, Rolls([.99] * 6))
        self.assertFalse(event["hit"])
        self.assertEqual(event["hits"], [0] * 6)
        self.assertEqual(event["damage"], 0)
        self.assertEqual(b.get("mechanics", {}).get("grudge", 0), 0)
        self.assertEqual(state["sides"]["a"]["resource"], 55)
        self.assertEqual(state["sides"]["a"]["own_turns"], 3)
        self.assertEqual(state["sides"]["a"]["cooldowns"]["tigerslayer_flurry"], 4)

    def test_successful_series_grudge_bleed_and_buff_tick_only_once(self):
        state = self.battle()
        a, b = state["sides"].values()
        b["passive_details"] = a["passive_details"]
        a["effects"].extend([
            dict(id="bleed", kind="bleed", value=3, duration=2),
            dict(id="aim", kind="accuracy_flat", value=5, duration=2),
        ])
        event = self.tap(state, Rolls([0] * 6))
        self.assertEqual(b["mechanics"]["grudge"], 1)
        self.assertEqual(event["bleed_damage"], 3)
        self.assertEqual(a["effects"][0]["duration"], 1)
        self.assertEqual(a["resource"], 55)
        self.assertEqual(len(state["log"]), 1)

    def test_partial_hit_recoil_uses_actual_damage_once(self):
        state = self.battle()
        a = state["sides"]["a"]
        a["archclass_id"] = "middle_revenge"
        a["archclass_stage"] = 10
        event = self.tap(state, Rolls([0, .99, .99, 0, .99, .99]))
        self.assertEqual(event["self_damage"], (event["damage"] + 4) // 5)

    def test_damage_stops_at_remaining_hp(self):
        state = self.battle()
        state["sides"]["b"]["hp"] = 1
        event = self.tap(state, Rolls([0] * 6))
        self.assertEqual(event["damage"], 1)
        self.assertEqual(event["hits"], [1, 0, 0, 0, 0, 0])

    @unittest.skipUnless(shutil.which("node"), "Node.js required for client replay")
    def test_normal_battle_replays_partial_series_and_all_misses(self):
        source = (Path(__file__).resolve().parents[1] / "webapp" / "battle-client").read_text(
            encoding="utf-8").rsplit("boot();", 1)[0]
        script = """
const vm=require('node:vm'),p=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let numbers=[],impacts=0;
const el=()=>({style:{},classList:{add(){},remove(){}},remove(){},addEventListener(){}});
const field={append(n){numbers.push(n.textContent)}};
const c={window:{Telegram:undefined,matchMedia:()=>({matches:true})},document:{getElementById:()=>el(),
querySelector:()=>field,createElement:()=>el(),addEventListener(){}},
location:{search:'',hostname:'example.test'},URLSearchParams,URL,
setInterval(){},setTimeout(cb){cb()},clearTimeout(){},input:p.event,counter:()=>{impacts++}};
vm.runInNewContext(p.source+`
current={actor_id:1,state:{sides:{a:{controller_id:1,name:'A'},b:{controller_id:2,name:'B'}}}};
slashImpact=async()=>{counter()};
animateEvent(input);`,c).then(()=>process.stdout.write(JSON.stringify({numbers,impacts})))
.catch(e=>{console.error(e);process.exit(1)});
"""
        for rolls, expected, impacts in (
            ([0, .8, .99, 0, .8, .99], None, 2),
            ([.99] * 6, ["Промах"] * 6, 0),
        ):
            event = self.tap(self.battle(), Rolls(rolls))
            event.pop("after")
            event.pop("status_after")
            if expected is None:
                expected = [f"−{event['hits'][0]}", "Уклонение", "Промах",
                            f"−{event['hits'][3]}", "Уклонение", "Промах"]
            result = subprocess.run(
                [shutil.which("node"), "-e", script],
                input=json.dumps(dict(source=source, event=event)),
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(numbers=expected, impacts=impacts))


if __name__ == "__main__":
    unittest.main()
