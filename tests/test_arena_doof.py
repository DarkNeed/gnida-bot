import json
import random
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import test_arena
import test_arena_market_client
from test_arena_lei_heng import Hit, NoLoot
import test_arena_lei_heng as lei_tests
from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    create_battle_state,
    validate_skill,
    resolve_skill,
)
from arena_raid_engine import (
    create_raid_state,
    resolve_round,
    set_intent,
    pair_state,
    native_attack,
)
from arena_raid_web import raid_view
from handlers.raids import RAID_RE, raid_boss_id, RaidPublisher
from tools.preview_arena import raid_preview


def state(size=3):
    members = [
        dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i)
        for i in range(1, size + 1)
    ]
    sources = [
        dict(slave_id=i, owner_id=i, class_id="ragamuffin", level=18)
        for i in range(1, size + 1)
    ]
    data = create_raid_state(
        members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, "doofenshmirtz"
    )
    for f in [data["boss"]] + [p["fighter"] for p in data["players"].values()]:
        f["hp"] = f["stats"]["max_hp"] = 10000
    return data


def advance(data, round_number):
    data["round"] = round_number
    set_intent(data)
    for p in data["players"].values():
        p["selected"] = "defend"
    return resolve_round(data, BUILTIN_SKILLS, Hit())


class DoofEngineTests(unittest.TestCase):
    def test_aliases_level_and_telegraphs(self):
        for text in ("/рейд Фуфелшмерц", "/raid doof", "/рейд@GnidoBot фуфел"):
            self.assertEqual(raid_boss_id(RAID_RE.fullmatch(text)), "doofenshmirtz")
        self.assertEqual(raid_boss_id(RAID_RE.fullmatch("/рейд")), "iron")
        for size in (1, 2, 3):
            data = state(size)
            self.assertEqual(data["boss"]["level"], 20)
            self.assertTrue(data["boss"]["is_boss"])
            for round_number, skill in enumerate(
                (
                    "doof_shot",
                    "doof_hangover",
                    "doof_deport",
                    "monologue",
                    "doof_blast",
                ),
                1,
            ):
                data["round"] = round_number
                set_intent(data)
                self.assertEqual(data["intent"]["skill"], skill)
                self.assertTrue(data["dialogue"]["persistent"])

    def test_perry_cover_only_reduces_one_successful_hit(self):
        data = state()
        actor, boss = data["players"]["1"]["fighter"], data["boss"]
        uncovered = deepcopy(boss)
        uncovered["effects"] = []
        normal = native_attack(
            deepcopy(actor), uncovered, "bum_punch", BUILTIN_SKILLS, Hit()
        )["damage"]
        covered = native_attack(
            deepcopy(actor), boss, "bum_punch", BUILTIN_SKILLS, Hit()
        )["damage"]
        self.assertLess(covered, normal)
        self.assertFalse(any(e.get("id") == "perry_cover" for e in boss["effects"]))
        second = native_attack(
            deepcopy(actor), boss, "bum_punch", BUILTIN_SKILLS, Hit()
        )["damage"]
        self.assertEqual(second, normal)

    def test_deport_one_round_no_afk_penalty_and_no_solo_lock(self):
        data = state()
        advance(data, 3)
        p = data["players"]["1"]
        self.assertEqual(p["deported_round"], 4)
        self.assertEqual(p["selected"], "defend")
        manual = p["manual_turns"]
        resolve_round(data, BUILTIN_SKILLS, Hit())
        self.assertEqual(p["manual_turns"], manual)
        self.assertEqual(p["missed"], 0)
        self.assertEqual(data["round"], 5)
        self.assertIsNone(p["selected"])
        solo = state(1)
        advance(solo, 3)
        self.assertNotIn("deported_round", solo["players"]["1"])
        self.assertTrue(
            any(
                e.get("id") == "doof_deport_accuracy"
                for e in solo["players"]["1"]["fighter"]["effects"]
            )
        )

    def test_blast_interrupt_and_monologue(self):
        data = state()
        advance(data, 4)
        self.assertTrue(
            any(e.get("id") == "doof_story_magic" for e in data["boss"]["effects"])
        )
        # A native test attack inflicts enough damage to break the telegraph.
        from arena_engine import Skill

        skill = Skill("test_break", "Срыв", "raid", 1, "magic", 2500, 95, 0, 0)
        p = data["players"]["1"]
        p["fighter"]["loadout"].append("test_break")
        for x in data["players"].values():
            x["selected"] = "defend"
        p["selected"] = "test_break"
        resolve_round(data, BUILTIN_SKILLS | {"test_break": skill}, Hit())
        self.assertTrue(
            any("заряд инатора сорван" in e["text"].casefold() for e in data["log"])
        )
        self.assertFalse(any(e.get("skill") == "doof_blast" for e in data["log"]))

    def test_self_destruct_once_and_phase_after_announcement(self):
        data = state()
        data["boss"]["hp"] = 4900
        advance(data, 2)
        self.assertEqual(data["boss"]["hp"], 4400)
        self.assertEqual(data["phase"], 2)
        advance(data, 4)
        self.assertEqual(data["boss"]["hp"], 4400)
        self.assertEqual(
            sum("Кнопка самоуничтожения" in e["text"] for e in data["log"]), 1
        )

    def test_aoe_bleed_ticks_only_once(self):
        data = state()
        data["boss"]["effects"].append(
            dict(id="bleed", kind="bleed", value=7, duration=3)
        )
        advance(data, 2)
        self.assertEqual(data["boss"]["hp"], 9993)

    def test_tractate_cost_once_persistence_new_battle_and_boss_immunity(self):
        source = dict(
            slave_id=1,
            owner_id=1,
            class_id="nerd",
            level=18,
            loadout=["deportator_inator"],
            granted_skills=["deportator_inator"],
        )
        for boss in (False, True):
            battle = create_battle_state(source, dict(source, slave_id=2, owner_id=2))
            actor, target = battle["sides"].values()
            target["hp"] = 10000
            target["is_boss"] = boss
            event = resolve_skill(
                battle, "a", "deportator_inator", rng=Hit(), advance_turn=False
            )
            self.assertGreater(event["damage"], 0)
            self.assertEqual(actor["resource"], 20)
            self.assertEqual(
                any(e["kind"] == "stun" for e in target["effects"]), not boss
            )
            actor["resource"] = 100
            # Saved JSON and many turns must not renew this skill.
            battle = json.loads(json.dumps(battle))
            for _ in range(10):
                from arena_engine import _tick

                _tick(battle["sides"]["a"])
            with self.assertRaisesRegex(ValueError, "Уже использован"):
                validate_skill(battle, "a", "deportator_inator")
            fresh = create_battle_state(source, dict(source, slave_id=2, owner_id=2))
            validate_skill(fresh, "a", "deportator_inator")

    def test_client_support_dialogue_and_assets(self):
        data = raid_preview("doof")
        rendered = test_arena_market_client.ArenaMarketClientTests().run_client(
            "updateRaidTimer=()=>{};raidScreen(input)", data
        )
        self.assertIn('class="raid-support"', rendered)
        self.assertIn('class="raid-dialogue"', rendered)
        self.assertIn("/static/assets/perry.png", rendered)
        self.assertIn("/static/assets/doofenshmirtz.png", rendered)
        self.assertEqual(rendered.count('class="raid-fighter'), 4)
        for name in ("perry", "doofenshmirtz"):
            self.assertTrue(
                (
                    Path(__file__).resolve().parents[1]
                    / "webapp"
                    / "assets"
                    / (name + ".png")
                ).is_file()
            )

    def test_miss_consumes_once_but_failed_validation_does_not(self):
        source = dict(
            slave_id=1,
            owner_id=1,
            class_id="nerd",
            level=18,
            loadout=["deportator_inator"],
            granted_skills=["deportator_inator"],
        )
        battle = create_battle_state(source, dict(source, slave_id=2, owner_id=2))
        actor = battle["sides"]["a"]
        actor["resource"] = 79
        with self.assertRaisesRegex(ValueError, "Недостаточно"):
            resolve_skill(
                battle, "a", "deportator_inator", rng=Hit(), advance_turn=False
            )
        self.assertFalse(actor.get("used_skills"))
        actor["resource"] = 100
        event = resolve_skill(
            battle, "a", "deportator_inator", rng=NoLoot(), advance_turn=False
        )
        self.assertEqual(event["damage"], 0)
        self.assertEqual(actor["resource"], 20)
        actor["resource"] = 100
        with self.assertRaisesRegex(ValueError, "Уже использован"):
            validate_skill(battle, "a", "deportator_inator")


class DoofStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown
    win = lei_tests.LeiStoreTests.win

    async def start(self):
        return await lei_tests.LeiStoreTests.start(self, "doofenshmirtz")

    async def test_drop_pity_restart_atomic_and_public_view(self):
        with patch("arena_raid.random.SystemRandom", return_value=NoLoot()):
            for attempt in range(1, 6):
                row = await self.start()
                view = await raid_view(self.db, row, 10)
                self.assertEqual(view["loot_name"], "Депортатор-инатор")
                self.assertEqual(view["ally_sprite"], "/static/assets/perry.png")
                data = self.win(row)
                self.assertEqual(bool(data["rewards"]["10"]["loot"]), attempt == 5)
                if attempt == 3:
                    await self.db.close()
                    await self.db.connect()
            item = self.db.connection.execute(
                "SELECT * FROM arena_inventory WHERE owner_id=10 AND content_id='deportator_inator'"
            ).fetchone()
            self.assertEqual(item["quantity"], 1)
            self.assertNotIn(
                "deportator_inator", str(self.db._arena_shop_catalog_locked())
            )
            with self.assertRaises(ValueError):
                self.win(row)
            self.assertEqual(
                self.db.connection.execute(
                    "SELECT quantity FROM arena_inventory WHERE id=?", (item["id"],)
                ).fetchone()["quantity"],
                1,
            )

    async def test_rewards_rollback_and_distinct_pity(self):
        row = await self.start()
        with patch("arena_raid.random.SystemRandom", return_value=Hit()), patch.object(
            self.db, "_arena_add_item_locked", side_effect=RuntimeError("failed")
        ):
            with self.assertRaises(RuntimeError):
                self.win(row)
            self.db.connection.rollback()
        self.assertEqual(
            (await self.db.arena_raid_get(row["token"]))["status"], "active"
        )
        self.assertIsNone(
            self.db.connection.execute(
                "SELECT * FROM arena_raid_loot_pity WHERE boss_id='doofenshmirtz'"
            ).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
