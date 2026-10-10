import json
import shutil
import unittest
from pathlib import Path

from arena_engine import (
    battle_status_snapshot,
    create_battle_state,
    resolve_skill,
    skip_turn,
)
import test_arena_market_client as client_tests


class StatusSnapshotTests(unittest.TestCase):
    def state(self):
        source = dict(
            slave_id=1,
            owner_id=1,
            class_id="ragamuffin",
            level=10,
            loadout=["bum_punch", "dust_in_eyes"],
        )
        state = create_battle_state(source, dict(source, slave_id=2, owner_id=2))
        state["active_side"] = "a"
        return state

    def test_snapshot_is_detached_and_omits_passives_and_instant_effects(self):
        state = self.state()
        a = state["sides"]["a"]
        a["effects"] = [
            dict(id="dust", kind="accuracy_flat", value=-20, duration=3),
            dict(id="passive", kind="damage_pct", value=0.1, duration=1_000_000),
            dict(id="expired", kind="stun", value=1, duration=0),
            dict(id="instant", kind="resource", value=10, duration=1),
        ]
        a["mechanics"] = dict(
            order=2,
            last_skill="dust_in_eyes",
            enemy_prescript=dict(skill_id="bum_punch", penalty=8),
        )
        snapshot = battle_status_snapshot(state)
        self.assertEqual([e["id"] for e in snapshot["a"]["effects"]], ["dust"])
        self.assertNotIn("last_skill", snapshot["a"]["mechanics"])
        a["effects"][0]["duration"] = 1
        a["mechanics"]["enemy_prescript"]["penalty"] = 12
        self.assertEqual(snapshot["a"]["effects"][0]["duration"], 3)
        self.assertEqual(snapshot["a"]["mechanics"]["enemy_prescript"]["penalty"], 8)

    def test_action_and_timeout_have_separate_status_snapshots(self):
        state = self.state()
        rng = type(
            "AlwaysHit", (), {"random": lambda _: 0.0, "uniform": lambda _, a, b: 1.0}
        )()
        event = resolve_skill(state, "a", "dust_in_eyes", rng=rng)
        effect = event["status_after"]["b"]["effects"][0]
        self.assertEqual(effect["duration"], 3)
        skip_turn(state)
        self.assertEqual(event["status_after"]["b"]["effects"][0]["duration"], 3)
        self.assertEqual(
            state["log"][-1]["status_after"]["b"]["effects"][0]["duration"], 2
        )

    def test_stun_skip_removes_icon_in_its_own_event(self):
        state = self.state()
        state["sides"]["b"]["effects"] = [
            dict(id="stun", kind="stun", value=1, duration=1)
        ]
        rng = type(
            "AlwaysHit", (), {"random": lambda _: 0.0, "uniform": lambda _, a, b: 1.0}
        )()
        event = resolve_skill(state, "a", "bum_punch", rng=rng)
        self.assertEqual(event["status_after"]["b"]["effects"][0]["kind"], "stun")
        self.assertEqual(state["log"][-1]["status_after"]["b"]["effects"], [])


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class StatusClientTests(unittest.TestCase):
    def run_client(self, code, data):
        return client_tests.ArenaMarketClientTests().run_client(code, data)

    def statuses(self, side):
        return json.loads(
            self.run_client("out=JSON.stringify(fighterStatuses(input));", side)
        )

    def test_empty_legacy_side_has_no_icons(self):
        self.assertEqual(self.statuses({}), [])

    def test_only_active_temporary_effects_appear(self):
        effects = [
            dict(id="x", kind="damage_pct", value=-0.4, duration=d)
            for d in (0, -1, 10_000, 999_900)
        ]
        effects += [
            dict(id="instant", kind="resource", value=20, duration=2),
            dict(
                id="adoration",
                kind="damage_pct",
                value=-0.4,
                duration=2,
                turns=3,
                target="enemy",
                chance=0.5,
            ),
        ]
        items = self.statuses(dict(effects=effects))
        self.assertEqual(len(items), 1)
        self.assertEqual(
            (items[0]["name"], items[0]["icon"], items[0]["count"]),
            ("Умиление", 0, "2"),
        )
        self.assertIn("-40%", items[0]["detail"])
        self.assertNotIn("противнику", items[0]["detail"])
        self.assertNotIn("шанс", items[0]["detail"])

    def test_custom_effect_falls_back_and_escapes_description(self):
        item = self.statuses(
            dict(
                effects=[
                    dict(
                        id='"x',
                        kind="unknown",
                        duration=2,
                        description="<script>bad</script>",
                    )
                ]
            )
        )[0]
        self.assertEqual(item["icon"], 15)
        self.assertIn("&lt;script&gt;", item["detail"])
        self.assertNotIn("<script>", item["detail"])
        buttons = self.run_client(
            "out=statusButtons(input,'b');",
            dict(effects=[dict(id='"x', kind="unknown", duration=2)]),
        )
        self.assertIn("effect:&quot;x:unknown", buttons)
        self.assertNotIn('data-status-id="effect:"x', buttons)

    def test_flat_effects_are_percentage_points(self):
        item = self.statuses(
            dict(effects=[dict(id="dust", kind="accuracy_flat", value=-20, duration=3)])
        )[0]
        self.assertEqual(item["icon"], 3)
        self.assertIn("процентных пунктах", item["detail"])

    def test_preparation_and_magic_attack_have_icons(self):
        items = self.statuses(
            dict(
                effects=[
                    dict(id=k, kind=k, value=0.2, duration=2)
                    for k in (
                        "prepared_attack",
                        "next_physical_damage",
                        "next_magic_damage",
                        "magic_attack_pct",
                    )
                ]
            )
        )
        self.assertEqual([e["icon"] for e in items], [10, 10, 5, 5])

    def test_mechanics_show_stacks_and_both_prescriptions(self):
        items = self.statuses(
            dict(
                mechanics=dict(
                    order=2,
                    grudge=3,
                    focus=1,
                    prescript="first_line",
                    enemy_prescript=dict(skill_id="bum_punch", penalty=10),
                ),
                skill_details=[
                    dict(skill_id="first_line", name="Первая строка"),
                    dict(skill_id="bum_punch", name="Удар бомжа"),
                ],
            )
        )
        self.assertEqual([e["count"] for e in items], ["2/3", "3/3", "1/3", "1", "1"])
        self.assertIn("не длительность", items[0]["detail"])
        self.assertIn("Первая строка", items[3]["detail"])
        self.assertIn("Удар бомжа", items[4]["detail"])
        self.assertIn("10", items[4]["detail"])

    def test_duplicate_kind_effects_are_not_merged(self):
        items = self.statuses(
            dict(
                effects=[
                    dict(id=k, kind="physical_defense_pct", value=0.2, duration=2)
                    for k in ("barrier", "pose")
                ]
            )
        )
        self.assertEqual(len({e["id"] for e in items}), 2)

    def test_animation_uses_snapshot_not_final_state(self):
        out = self.run_client(
            """
current={state:{sides:{a:input,b:{}}}};
renderBattleStatuses({a:{effects:[{id:'bleed',kind:'bleed',value:4,duration:3}],mechanics:{grudge:2}},b:{effects:[],mechanics:{}}});
out=JSON.stringify(fighterStatuses(statusSide('a')));
""",
            dict(effects=[], mechanics=dict(grudge=0)),
        )
        self.assertEqual([e["count"] for e in json.loads(out)], ["3", "2/3"])

    def test_approved_atlas_is_present(self):
        from PIL import Image

        asset = (
            Path(__file__).resolve().parents[1] / "webapp/assets/status-effects-v1.png"
        )
        with Image.open(asset) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.width, image.height)
            self.assertEqual(image.getchannel("A").getextrema(), (0, 255))
