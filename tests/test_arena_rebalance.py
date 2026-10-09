import copy
import json
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_engine import (
    BUILTIN_SKILLS,
    create_battle_state,
    effective_stat,
    resolve_skill,
)
from arena_class_mechanics import class_modifiers, has_adoration
from arena_web import battle_view
from database import Database
import test_arena_market_client as client_tests


class FixedRoll:
    def __init__(self, roll=0):
        self.roll = roll

    def random(self):
        return self.roll

    def uniform(self, lo, hi):
        return 1

    def choice(self, choices):
        return choices[0]


class RebalanceEngineTests(unittest.TestCase):
    def state(self, cls="nerd", other="jock", passives=None):
        first = dict(slave_id=10, owner_id=10, class_id=cls, level=20)
        if passives is not None:
            first["passive_details"] = passives
        state = create_battle_state(
            first, dict(slave_id=20, owner_id=20, class_id=other, level=20)
        )
        for side in state["sides"].values():
            side["loadout"] = list(BUILTIN_SKILLS)
            side["hp"] = 10000  # Isolate mechanics from fight termination.
        return state

    def tap(self, state, skill, side="a", roll=0):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=FixedRoll(roll))

    def test_adoration_reduces_buffed_damage_by_forty_percent(self):
        state = self.state("jock", "cutie")
        actor = state["sides"]["a"]
        actor["effects"] = [dict(id="buff", kind="damage_pct", value=0.6, duration=3)]
        plain = copy.deepcopy(state)
        actor["effects"].append(
            dict(id="adoration", kind="damage_pct", value=-0.4, duration=2)
        )
        full = self.tap(plain, "smack")["damage"]
        reduced = self.tap(state, "smack")["damage"]
        self.assertAlmostEqual(reduced, full * 0.6, delta=1)

    def test_charm_refresh_not_stack_and_refund_once(self):
        state = self.state("cutie")
        actor, target = state["sides"].values()
        self.tap(state, "uwu")
        self.assertEqual(actor["resource"], 95)
        self.tap(state, "uwu")
        self.assertEqual(actor["resource"], 90)
        charms = [e for e in target["effects"] if e.get("id") == "adoration"]
        self.assertEqual(len(charms), 1)
        self.assertEqual((charms[0]["value"], charms[0]["duration"]), (-0.4, 2))
        self.assertNotIn("uwu", actor["cooldowns"])

    def test_refunds_require_equipped_passives(self):
        state = self.state("cutie", passives=[])
        self.tap(state, "uwu")
        self.assertEqual(state["sides"]["a"]["resource"], 90)

    def test_meow_bonus_consumes_charm_only_on_hit(self):
        state = self.state("cutie")
        self.tap(state, "uwu")
        a, b = state["sides"].values()
        self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["air_kiss"])[1], 0.2)
        self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["meow"])[1], 0.25)
        miss = copy.deepcopy(state)
        self.tap(miss, "meow", roll=0.99)
        self.assertTrue(has_adoration(miss["sides"]["b"]))
        self.tap(state, "meow")
        self.assertFalse(has_adoration(b))

    def test_dodge_not_ordinary_miss_refunds_love(self):
        for roll, dodged, resource in (
            (0.80, True, 58),
            (0.99, False, 50),
            (0, False, 50),
        ):
            with self.subTest(roll=roll):
                state = self.state("jock", "cutie")
                state["sides"]["b"]["resource"] = 50
                event = self.tap(state, "smack", roll=roll)
                self.assertEqual(event["dodged"], dodged)
                self.assertEqual(state["sides"]["b"]["resource"], resource)

    def test_non_damage_miss_has_no_dodge_refund(self):
        state = self.state("jock", "cutie")
        state["sides"]["b"]["resource"] = 50
        event = self.tap(state, "clench", roll=0.8)
        self.assertFalse(event["hit"])
        self.assertFalse(event["dodged"])
        self.assertEqual(state["sides"]["b"]["resource"], 50)

    def test_charging_spent_by_magic_even_on_miss(self):
        for roll in (0, 0.99):
            state = self.state()
            self.tap(state, "charging")
            a, b = state["sides"].values()
            self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["humiliate"])[1], 0.6)
            self.tap(state, "humiliate", roll=roll)
            self.assertFalse(
                any(e["kind"] == "next_magic_damage" for e in a["effects"])
            )

    def test_charging_expires_after_three_actions_and_no_stacking(self):
        state = self.state()
        a = state["sides"]["a"]
        self.tap(state, "charging")
        a["cooldowns"].clear()
        self.tap(state, "charging")
        self.assertEqual(
            sum(e["value"] for e in a["effects"] if e["kind"] == "next_magic_damage"),
            0.6,
        )
        for _ in range(2):
            self.tap(state, "bum_punch")
        self.assertTrue(any(e["kind"] == "next_magic_damage" for e in a["effects"]))
        self.tap(state, "bum_punch")
        self.assertFalse(any(e["kind"] == "next_magic_damage" for e in a["effects"]))

    def test_leech_returns_half_actual_energy_not_nominal(self):
        for available, returned in ((0, 0), (5, 2), (100, 7)):
            state = self.state(passives=[])
            a, b = state["sides"].values()
            b["resource"] = available
            self.tap(state, "humiliate")
            self.assertEqual(a["resource"], 85 + returned)
            self.assertEqual(b["resource"], max(0, available - 15))
            self.assertNotIn("humiliate", a["cooldowns"])

    def test_analysis_different_magic_and_economy_every_third_paid_attack(self):
        state = self.state()
        a, b = state["sides"].values()
        b["resource"] = 0
        for i in range(3):
            self.tap(state, "humiliate")
            self.assertEqual(a["resource"], 100 - (i + 1) * 15 + (10 if i == 2 else 0))
        self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["humiliate"])[0], 0)
        self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["mother_joke"])[0], 10)
        self.assertEqual(a["mechanics"]["paid_magic"], 0)
        self.tap(state, "go_to_store")
        self.assertEqual(a["mechanics"]["paid_magic"], 0)
        self.assertNotIn("mechanics", self.state()["sides"]["a"])

    def test_foreign_magic_does_not_grant_nerd_passives(self):
        state = self.state("jock")
        a, b = state["sides"].values()
        b["resource"] = 0
        for _ in range(3):
            self.tap(state, "humiliate")
        self.assertEqual(a["resource"], 55)
        self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["mother_joke"])[0], 0)

    def test_doxxing_lowers_both_defenses_and_evasion_not_energy(self):
        state = self.state(other="cutie")
        a, b = state["sides"].values()
        self.tap(state, "doxxing")
        for stat in ("physical_defense", "magic_defense"):
            self.assertAlmostEqual(effective_stat(b, stat), b["stats"][stat] * 0.8)
        self.assertEqual(
            effective_stat(b, "evasion"), max(0, b["stats"]["evasion"] - 15)
        )
        self.assertEqual(b["resource"], 100)
        self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["mother_joke"])[1], 0.2)
        self.assertEqual(a["cooldowns"]["doxxing"], 3)

    def test_store_repeatable_but_costs_a_turn_and_caps_energy(self):
        state = self.state()
        a = state["sides"]["a"]
        a["resource"] = 0
        self.tap(state, "go_to_store")
        self.assertEqual((a["resource"], state["active_side"]), (55, "b"))
        self.assertNotIn("go_to_store", a["cooldowns"])
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "go_to_store")
        self.tap(state, "bum_punch", "b")
        resolve_skill(state, "a", "go_to_store", rng=FixedRoll())
        self.assertEqual(a["resource"], 100)


class RebalanceStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "bot.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        for user in (10, 20, 30):
            await self.db.upsert_user(1, user, str(user), str(user))
            self.db._add_francs_locked(1, user, 100)
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def duel(self):
        row = await self.db.arena_offer(1, 10, 20, "personal", 50)
        await self.db.arena_set_message(row["token"], 1)
        with patch("arena_store.random.SystemRandom") as rng:
            rng.return_value.choice.return_value = "a"
            return await self.db.arena_setup(row["token"], 20, "accept")

    async def test_surrender_off_turn_settles_correct_winner_and_rejects_spectator(
        self,
    ):
        row = await self.duel()
        state = json.loads(row["state_json"])
        loser = "b" if state["active_side"] == "a" else "a"
        actor = state["sides"][loser]["controller_id"]
        with self.assertRaises(ValueError):
            await self.db.arena_action(row["token"], 30, row["revision"], "surrender")
        row = await self.db.arena_action(
            row["token"], actor, row["revision"], "surrender"
        )
        result = json.loads(row["state_json"])
        self.assertEqual(result["winner"], state["active_side"])
        self.assertEqual(result["finish_reason"], "surrender")
        self.assertEqual(row["status"], "finished")
        self.assertEqual((row["escrow_a"], row["escrow_b"]), (0, 0))
        self.assertEqual((await self.db.franc_balance(1, actor)), 50)
        with self.assertRaises(ValueError):
            await self.db.arena_action(
                row["token"], actor, row["revision"], "surrender"
            )

    async def test_new_class_passives_fill_free_slots_once_without_overwriting_choice(
        self,
    ):
        await self.db.arena_passive_view(1, 10, True)
        self.db.connection.execute(
            "UPDATE personal_profiles SET class_id='cutie',passive_loadout='[]' WHERE chat_id=1 AND user_id=10"
        )
        view = await self.db.arena_passive_view(1, 10, True)
        self.assertEqual(
            view["passive_loadout"], ["inherent:cutie:0", "inherent:cutie:1"]
        )
        self.db.connection.execute(
            "UPDATE personal_profiles SET passive_loadout='[]' WHERE chat_id=1 AND user_id=10"
        )
        again = await self.db.arena_passive_view(1, 10, True)
        self.assertEqual(again["passive_loadout"], [])
        self.assertEqual(
            (await self.db.get_slave_profile(1, 10))["class_id"], "ragamuffin"
        )

    async def test_existing_manual_passive_not_replaced_and_memory_capped(self):
        self.db._arena_add_item_locked(1, 10, "passive", "stone_skin", "common", 1)
        item = self.db.connection.execute("SELECT id FROM arena_inventory").fetchone()[
            "id"
        ]
        self.db.connection.commit()
        await self.db.arena_use_item(1, 10, item, 10)
        await self.db.arena_edit_profile(1, 10, 10, True, "passives", ["stone_skin"])
        self.db.connection.execute(
            "UPDATE personal_profiles SET class_id='nerd' WHERE chat_id=1 AND user_id=10"
        )
        view = await self.db.arena_passive_view(1, 10, True)
        self.assertEqual(view["passive_loadout"], ["stone_skin", "inherent:nerd:0"])
        self.assertEqual(len(view["passives"]), 3)
        again = await self.db.arena_passive_view(1, 10, True)
        self.assertEqual(again["passive_loadout"], view["passive_loadout"])

    async def test_damage_bonus_view_matches_multiplicative_reduction(self):
        row = await self.duel()
        state = json.loads(row["state_json"])
        state["sides"]["a"]["effects"] = [
            dict(id="buff", kind="damage_pct", value=0.6, duration=3),
            dict(id="adoration", kind="damage_pct", value=-0.4, duration=2),
        ]
        row["state_json"] = json.dumps(state)
        view = await battle_view(self.db, row, 10)
        self.assertAlmostEqual(view["state"]["sides"]["a"]["damage_bonus"], -0.04)


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class RebalanceClientTests(unittest.TestCase):
    def render(self, actor, active="a", finished=False):
        sides = {
            k: dict(controller_id=user, name=k, skill_details=[], mechanics={}, hp=10)
            for k, user in (("a", 10), ("b", 20))
        }
        return client_tests.ArenaMarketClientTests.run_client(
            self,
            "const nodes={};document.getElementById=id=>nodes[id]||(nodes[id]={innerHTML:'',classList:{toggle(){}}});"
            "current=input;renderActions();out=nodes.panel.innerHTML;",
            dict(
                actor_id=actor,
                own_side="a" if actor == 10 else None,
                state=dict(
                    sides=sides,
                    active_side=active,
                    turn=1,
                    finished=finished,
                    winner="b",
                    log=[],
                ),
            ),
        )

    def test_surrender_one_button_both_turns_not_for_spectator_or_finished(self):
        for active in ("a", "b"):
            self.assertEqual(self.render(10, active).count('data-do="surrender"'), 1)
        self.assertNotIn('data-do="surrender"', self.render(30))
        self.assertNotIn('data-do="surrender"', self.render(10, finished=True))

    def test_charging_description_uses_percentage(self):
        body = client_tests.ArenaMarketClientTests.run_client(
            self,
            "out=describeEffect(input);",
            dict(kind="next_magic_damage", value=0.6, target="self", turns=3),
        )
        self.assertIn("60%", body)


if __name__ == "__main__":
    unittest.main()
