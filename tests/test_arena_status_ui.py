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

    def test_accuracy_penalty_has_direction_and_percent(self):
        item = self.statuses(
            dict(effects=[dict(id="dust", kind="accuracy_flat", value=-20, duration=3)])
        )[0]
        self.assertEqual(item["icon"], 3)
        self.assertEqual(item["name"], "Понижение точности")
        self.assertEqual(item["direction"], "down")
        self.assertIn("Точность: -20%", item["detail"])
        self.assertNotIn("процент", item["detail"])

    def test_stat_buffs_and_debuffs_have_distinct_names_and_icon_marks(self):
        for kind, label in (
            ("evasion_flat", "уклонения"),
            ("damage_pct", "урона"),
            ("speed_pct", "скорости"),
            ("physical_defense_pct", "физ. защиты"),
            ("magic_attack_pct", "маг. атаки"),
        ):
            with self.subTest(kind=kind):
                side = dict(
                    effects=[
                        dict(id="negative", kind=kind, value=-0.2, duration=2),
                        dict(id="positive", kind=kind, value=0.2, duration=2),
                    ]
                )
                items = self.statuses(side)
                self.assertEqual(
                    [e["name"] for e in items],
                    ["Понижение " + label, "Повышение " + label],
                )
                self.assertEqual([e["direction"] for e in items], ["down", "up"])
                buttons = self.run_client("out=statusButtons(input,'a');", side)
                self.assertIn("status-down", buttons)
                self.assertIn("status-up", buttons)

    def test_percent_units_do_not_affect_energy_or_custom_names(self):
        out = self.run_client(
            "out=describeEffect(input);", dict(kind="resource", value=20)
        )
        self.assertEqual(out, "Энергия: +20")
        out = self.run_client(
            "out=describeEffect(input);", dict(kind="evasion_flat", value=20)
        )
        self.assertEqual(out, "Уклонение: +20%")
        item = self.statuses(
            dict(
                effects=[
                    dict(
                        id="custom",
                        name="Пыль в глаза",
                        kind="accuracy_flat",
                        value=-20,
                        duration=3,
                    )
                ]
            )
        )[0]
        self.assertEqual(item["name"], "Пыль в глаза")
        self.assertEqual(item["direction"], "down")

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

    def test_all_vector_icons_are_present_without_raster_or_external_content(self):
        from xml.etree import ElementTree as ET

        asset = (
            Path(__file__).resolve().parents[1] / "webapp/assets/status-effects-v2.svg"
        )
        root = ET.parse(asset).getroot()
        symbols = root.findall("{http://www.w3.org/2000/svg}symbol")
        self.assertEqual(
            [s.attrib["id"] for s in symbols], [f"status-{i}" for i in range(16)]
        )
        for symbol in symbols:
            self.assertEqual(symbol.attrib["viewBox"], "0 0 32 32")
            self.assertGreater(len(list(symbol)), 0)
        for element in root.iter():
            self.assertIn(
                element.tag.rsplit("}", 1)[-1], {"svg", "symbol", "g", "path", "circle"}
            )
            self.assertFalse(
                any(
                    key.lower().startswith("on") or "href" in key
                    for key in element.attrib
                )
            )
        self.assertLess(asset.stat().st_size, 10_000)

    def test_status_markup_uses_original_drawings_and_vector_direction_arrows(self):
        for index in range(16):
            with self.subTest(index=index):
                markup = self.run_client("out=statusIcon(input);", index)
                self.assertIn('<svg class="status-icon"', markup)
                self.assertIn(f"/static/assets/status-effects-v3/{index}.png", markup)
                self.assertIn('<image class="status-drawing"', markup)
                self.assertNotIn("<use", markup)
        markup = self.run_client("out=statusIcon(3,'down');", {})
        self.assertIn("status-down", markup)
        self.assertIn("#ef5366", markup)
        self.assertIn('<path d="M26 20v8', markup)
        markup = self.run_client("out=statusIcon(3,'up');", {})
        self.assertIn("status-up", markup)
        self.assertIn('<path d="M26 28v-8', markup)

    def test_invalid_vector_icon_indexes_use_safe_fallback(self):
        for index in (-1, 16, None, '"/><script>'):
            with self.subTest(index=index):
                markup = self.run_client("out=statusIcon(input);", index)
                self.assertIn("/15.png", markup)
                self.assertNotIn("<script>", markup)


class OriginalStatusArtworkTests(unittest.TestCase):
    def test_short_windows_scroll_without_shrinking_skill_controls(self):
        css = (Path(__file__).resolve().parents[1] / "webapp/style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".battle{height:auto;min-height:100dvh;overflow:visible}", css)
        self.assertIn(".battle .field{flex:0 0 auto;", css)
        self.assertIn(".battle>.panel,.battle>.foot,.panel>*{flex-shrink:0}", css)

    def test_prepared_original_icons_have_transparency_and_retina_resolution(self):
        from PIL import Image

        folder = Path(__file__).resolve().parents[1] / "webapp/assets/status-effects-v3"
        self.assertEqual(len(list(folder.glob("*.png"))), 16)
        for index in range(16):
            with self.subTest(index=index), Image.open(folder / f"{index}.png") as icon:
                self.assertEqual(icon.mode, "RGBA")
                self.assertEqual(icon.size, (144, 144))
                alpha = icon.getchannel("A")
                self.assertEqual(alpha.getextrema(), (0, 255))
                self.assertIsNotNone(alpha.getbbox())
                self.assertEqual(alpha.getpixel((0, 0)), 0)

    def test_cleanup_preserves_artwork_colour_and_removes_faint_noise(self):
        from PIL import Image, ImageDraw
        from tools.prepare_status_icons import clean_icon

        original = Image.new("RGBA", (64, 64))
        draw = ImageDraw.Draw(original)
        draw.rectangle((12, 12, 40, 40), fill=(100, 160, 200, 255))
        draw.rectangle((45, 45, 54, 54), fill=(100, 160, 200, 255))
        draw.rectangle((2, 2, 6, 6), fill=(255, 0, 0, 30))
        original.putpixel((58, 2), (255, 255, 0, 255))
        cleaned = clean_icon(original)
        self.assertLess(cleaned.width, 50)
        self.assertLess(cleaned.height, 50)
        self.assertEqual(cleaned.getpixel((10, 10)), (100, 160, 200, 255))
        self.assertGreater(cleaned.getchannel("A").getpixel((38, 38)), 0)
        self.assertEqual(original.getpixel((58, 2)), (255, 255, 0, 255))

    def test_empty_icon_fails_instead_of_producing_an_invisible_asset(self):
        from PIL import Image
        from tools.prepare_status_icons import clean_icon

        with self.assertRaisesRegex(ValueError, "empty"):
            clean_icon(Image.new("RGBA", (32, 32)))
