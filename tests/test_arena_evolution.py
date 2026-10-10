import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_engine import (
    BUILTIN_SKILLS,
    create_battle_state,
    effective_skill,
    resolve_skill,
    skip_turn,
    use_healing_potion,
    class_modifiers,
)
from arena_mirror_effects import apply_gifts
from arena_web import battle_view, menu_view
from database import Database
from test_arena_rebalance import FixedRoll
import test_arena_market_client as client_tests


class EvolutionEngineTests(unittest.TestCase):
    def state(self, cls="cutie", level=10):
        state = create_battle_state(
            dict(slave_id=10, owner_id=10, class_id=cls, level=level),
            dict(slave_id=20, owner_id=20, class_id="jock", level=10),
        )
        for side in state["sides"].values():
            side["loadout"] = list(BUILTIN_SKILLS)
            side["hp"] = 10000
        return state

    def tap(self, state, skill, side="a", roll=0):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=FixedRoll(roll))

    def charm(self, state):
        state["sides"]["b"]["effects"].append(
            dict(id="adoration", kind="damage_pct", value=-0.4, duration=2)
        )

    def test_level_gate_and_foreign_skill_do_not_transform(self):
        for cls, level in (("cutie", 9), ("jock", 20)):
            state = self.state(cls, level)
            self.charm(state)
            self.assertIs(effective_skill(state, "a", "uwu"), BUILTIN_SKILLS["uwu"])
        state = self.state()
        self.charm(state)
        skill = effective_skill(state, "a", "uwu")
        self.assertEqual(
            (skill.skill_id, skill.name, skill.cost, skill.cooldown),
            ("uwu", "Ты уже мой", 15, BUILTIN_SKILLS["uwu"].cooldown),
        )

    def test_charm_hit_preserves_effect_and_uses_new_cost_no_charm_refund(self):
        state = self.state()
        self.tap(state, "uwu")
        self.assertEqual(state["sides"]["a"]["resource"], 95)
        event = self.tap(state, "uwu")
        self.assertTrue(event["evolved"])
        self.assertEqual(event["skill_name"], "Ты уже мой")
        self.assertEqual(state["sides"]["a"]["resource"], 80)
        self.assertTrue(
            any(e.get("id") == "adoration" for e in state["sides"]["b"]["effects"])
        )
        self.assertEqual(effective_skill(state, "a", "uwu").name, "Ты уже мой")

    def test_charm_miss_keeps_condition_and_mirror_refunds_real_cost(self):
        state = self.state()
        self.charm(state)
        apply_gifts(state["sides"]["a"], ["broken"])
        self.tap(state, "uwu", roll=0.99)
        self.assertEqual(state["sides"]["a"]["resource"], 100)
        self.assertEqual(effective_skill(state, "a", "uwu").name, "Ты уже мой")
        self.tap(state, "uwu", roll=0.99)
        self.assertEqual(state["sides"]["a"]["resource"], 85)

    def test_energy_validation_does_not_silently_fall_back_to_cheaper_base(self):
        state = self.state()
        self.charm(state)
        state["sides"]["a"]["resource"] = 14
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError, "выносливости"):
            resolve_skill(state, "a", "uwu")
        self.assertEqual(state, before)
        with self.assertRaises(ValueError):
            resolve_skill(state, "a", "uwu_evolved")
        self.assertEqual(state, before)

    def test_jock_preparation_consumed_by_hit_or_miss_without_double_passive(self):
        for roll in (0, 0.99):
            state = self.state("jock")
            self.tap(state, "flex_chest")
            skill = effective_skill(state, "a", "smack")
            self.assertEqual(
                (skill.name, skill.power, skill.cost), ("Последний подход", 12, 15)
            )
            a, b = state["sides"].values()
            self.assertAlmostEqual(class_modifiers(a, b, skill)[1], 0.15)
            before = a["resource"]
            self.tap(state, "smack", roll=roll)
            self.assertEqual(a["resource"], before - 15)
            self.assertIs(effective_skill(state, "a", "smack"), BUILTIN_SKILLS["smack"])
            self.assertEqual(class_modifiers(a, b, BUILTIN_SKILLS["smack"])[1], 0)

    def test_jock_charge_expires_refreshes_and_requires_success(self):
        state = self.state("jock")
        self.tap(state, "clench", roll=0.99)
        self.assertIs(effective_skill(state, "a", "smack"), BUILTIN_SKILLS["smack"])
        state["sides"]["a"]["cooldowns"].clear()
        self.tap(state, "clench")
        state["sides"]["a"]["cooldowns"].clear()
        self.tap(state, "clench")
        self.assertEqual(
            sum(
                e.get("id") == "evolution_prepared"
                for e in state["sides"]["a"]["effects"]
            ),
            1,
        )
        self.tap(state, "go_to_store")
        self.assertEqual(effective_skill(state, "a", "smack").name, "Последний подход")
        self.tap(state, "go_to_store")
        self.assertIs(effective_skill(state, "a", "smack"), BUILTIN_SKILLS["smack"])

    def test_jock_other_physical_attack_consumes_preparation(self):
        state = self.state("jock")
        self.tap(state, "flex_chest")
        self.tap(state, "bum_punch")
        self.assertIs(effective_skill(state, "a", "smack"), BUILTIN_SKILLS["smack"])

    def test_nerd_doxxing_changes_leech_but_does_not_remove_debuff(self):
        state = self.state("nerd")
        self.tap(state, "doxxing")
        skill = effective_skill(state, "a", "humiliate")
        self.assertEqual(
            (skill.name, skill.power, skill.cost), ("Полный деанон", 15, 25)
        )
        a, b = state["sides"].values()
        b["resource"] = 5
        self.tap(state, "humiliate")
        self.assertEqual((a["resource"], b["resource"]), (57, 0))
        self.assertTrue(any(e.get("id") == "doxxing_magic" for e in b["effects"]))
        # An unrelated magic-defense debuff must not impersonate Deanon.
        b["effects"] = [
            dict(id="other", kind="magic_defense_pct", value=-0.2, duration=2)
        ]
        self.assertIs(
            effective_skill(state, "a", "humiliate"), BUILTIN_SKILLS["humiliate"]
        )

    def test_four_own_turns_not_global_counter_and_shared_cooldown(self):
        state = self.state()
        for i in range(4):
            self.assertIs(effective_skill(state, "a", "meow"), BUILTIN_SKILLS["meow"])
            self.tap(state, "bum_punch")
            self.tap(state, "bum_punch", "b")
        self.assertEqual(state["turn"], 9)
        skill = effective_skill(state, "a", "meow")
        self.assertEqual(
            (skill.name, skill.cost, skill.cooldown), ("Кульминация: Мяу", 35, 2)
        )
        self.tap(state, "meow")
        self.assertEqual(state["sides"]["a"]["cooldowns"]["meow"], 2)
        state["active_side"] = "a"
        with self.assertRaisesRegex(ValueError, "восстанавливается"):
            resolve_skill(state, "a", "meow")

    def test_timeout_and_stun_count_own_turns_potion_does_not(self):
        state = self.state()
        state["sides"]["a"]["hp"] = 1
        use_healing_potion(state, "a")
        self.assertEqual(state["sides"]["a"]["own_turns"], 0)
        skip_turn(state)
        self.assertEqual(state["sides"]["a"]["own_turns"], 1)
        state["sides"]["a"]["effects"].append(
            dict(id="stun", kind="stun", value=1, duration=1)
        )
        self.tap(state, "go_to_store", "b")
        self.assertEqual(state["sides"]["a"]["own_turns"], 2)

    def test_legacy_log_initializes_separate_counters_and_roundtrip_preserves(self):
        state = self.state()
        for side in state["sides"].values():
            side.pop("own_turns")
        state["log"] = [dict(side="a", skill_id="bum_punch", seq=i) for i in range(4)]
        state["log"].append(dict(side="b", skill_id="bum_punch", seq=5))
        self.assertEqual(effective_skill(state, "a", "meow").name, "Кульминация: Мяу")
        self.tap(state, "meow")
        saved = json.loads(json.dumps(state))
        self.assertEqual(
            (saved["sides"]["a"]["own_turns"], saved["sides"]["b"]["own_turns"]), (5, 1)
        )
        self.assertEqual(effective_skill(saved, "a", "meow").name, "Кульминация: Мяу")

    def test_shared_cooldown_and_zero_energy_fallback_remain_available(self):
        state = self.state()
        self.charm(state)
        state["sides"]["a"]["cooldowns"]["uwu"] = 2
        with self.assertRaisesRegex(ValueError, "восстанавливается"):
            resolve_skill(state, "a", "uwu")
        state["sides"]["b"]["effects"].clear()
        with self.assertRaisesRegex(ValueError, "восстанавливается"):
            resolve_skill(state, "a", "uwu")
        state["sides"]["a"]["resource"] = 0
        self.tap(state, "bum_punch")
        self.assertEqual(state["sides"]["a"]["resource"], 0)


class EvolutionStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Чат")
        await self.db.upsert_user(1, 10, "user", "Игрок")
        await self.db.arena_menu(1, 10)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def test_battle_ui_cost_name_and_restart_match_server_resolution(self):
        row = await self.db.arena_wasteland(1, 10)
        state = create_battle_state(
            dict(slave_id=10, owner_id=10, class_id="cutie", level=10, loadout=["uwu"]),
            dict(slave_id=0, owner_id=0, class_id="jock", level=10),
        )
        state["sides"]["b"]["effects"].append(
            dict(id="adoration", kind="damage_pct", value=-0.4, duration=2)
        )
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        await self.db.close()
        await self.db.connect()
        row = await self.db.arena_get(row["token"])
        skill = (await battle_view(self.db, row, 10))["state"]["sides"]["a"][
            "skill_details"
        ][0]
        self.assertEqual(
            (
                skill["skill_id"],
                skill["name"],
                skill["cost"],
                skill["evolution"]["active"],
            ),
            ("uwu", "Ты уже мой", 15, True),
        )
        with patch("arena_engine.random.SystemRandom", return_value=FixedRoll()):
            row = await self.db.arena_action(row["token"], 10, row["revision"], "uwu")
        saved = json.loads(row["state_json"])
        self.assertEqual(saved["sides"]["a"]["resource"], 85)
        self.assertEqual(saved["log"][0]["skill_name"], "Ты уже мой")
        with self.assertRaises(ValueError):
            await self.db.arena_action(row["token"], 10, row["revision"] - 1, "uwu")

    async def test_ai_uses_transformed_cost_and_falls_back_instead_of_crashing(self):
        row = await self.db.arena_wasteland(1, 10)
        state = create_battle_state(
            dict(slave_id=10, owner_id=10, class_id="jock", level=10),
            dict(
                slave_id=0, owner_id=0, class_id="nerd", level=10, loadout=["humiliate"]
            ),
        )
        state["sides"]["a"]["effects"].append(
            dict(id="doxxing_magic", kind="magic_defense_pct", value=-0.2, duration=3)
        )
        state["sides"]["b"]["resource"] = 20  # Base cost 15; variant costs 25.
        state["sides"]["b"]["loadout"] = ["humiliate"]
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        with patch("arena_engine.random.SystemRandom", return_value=FixedRoll()):
            done = await self.db.arena_action(
                row["token"], 10, row["revision"], "bum_punch"
            )
        self.assertEqual(
            json.loads(done["state_json"])["log"][-1]["skill_id"], "bum_punch"
        )

    async def test_menu_explains_native_evolutions_without_extra_learned_slots(self):
        self.db.connection.execute(
            "UPDATE personal_profiles SET class_id='cutie',level=10 WHERE chat_id=1 AND user_id=10"
        )
        self.db.connection.commit()
        profile = (await menu_view(self.db, 1, 10))["personal"]
        uwu = next(s for s in profile["skills"] if s["skill_id"] == "uwu")
        self.assertEqual(uwu["evolution"]["min_level"], 10)
        self.assertEqual(uwu["evolution"]["name"], "Ты уже мой")
        self.assertFalse(
            any(s["skill_id"].endswith("evolved") for s in profile["skills"])
        )


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class EvolutionClientTests(unittest.TestCase):
    def test_button_uses_base_id_shows_upgrade_and_disables_at_real_cost(self):
        skill = dict(
            skill_id="uwu",
            name="Ты уже мой",
            cost=15,
            damage_type="magic",
            evolution=dict(active=True, condition="Умиление"),
        )
        side = dict(
            name="Игрок",
            controller_id=10,
            resource_name="Любовь",
            resource=14,
            cooldowns={},
            skill_details=[skill],
        )
        data = dict(
            actor_id=10,
            mode="wasteland",
            status="active",
            state=dict(turn=1, active_side="a", finished=False, sides=dict(a=side)),
        )
        body = client_tests.ArenaMarketClientTests.run_client(
            self, "current=input;renderActions();", data
        )
        self.assertIn('data-skill="uwu"', body)
        self.assertIn("skill evolved", body)
        self.assertIn("УСИЛЕНО", body)
        self.assertIn("Ты уже мой", body)
        self.assertIn("15 Любовь", body)
        self.assertIn("disabled", body)

    def test_skill_description_shows_condition_and_escapes_text(self):
        skill = dict(
            name="UWU",
            effects=[],
            evolution=dict(
                name="Ты уже мой",
                min_level=10,
                condition="<img src=x>",
                description="Усиленная атака",
                cost=15,
                power=12,
                active=False,
            ),
        )
        body = client_tests.ArenaMarketClientTests.run_client(
            self, "out=skillInfo(input);", skill
        )
        self.assertIn("Превращение с 10 уровня", body)
        self.assertIn("Энергия 15", body)
        self.assertNotIn("<img", body)
        self.assertIn("&lt;img", body)
