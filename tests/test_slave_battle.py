import json
import random
import tempfile
import unittest
from pathlib import Path

from database import Database
from slave_battle import (
    BUILTIN_SKILLS,
    create_battle_state,
    level_progress,
    resolve_turn,
    stats_for,
    xp_for_next_level,
)
from webapp_server import validate_telegram_init_data


class SlaveBattleEngineTests(unittest.TestCase):
    def test_xp_curve_starts_at_ten_and_grows_by_forty_percent(self):
        self.assertEqual([xp_for_next_level(level) for level in range(1, 5)], [10, 14, 20, 28])
        self.assertEqual(level_progress(72), (5, 0, 39))

    def test_control_reduces_every_combat_stat(self):
        ordinary = stats_for("jock", 7)
        controlled = stats_for("jock", 7, controlled=True)
        for name in ordinary:
            self.assertEqual(controlled[name], round(ordinary[name] * 0.8, 2))

    def test_matching_dodge_direction_reduces_hit_chance(self):
        state = create_battle_state(
            {"slave_id": 1, "owner_id": 11, "class_id": "ragamuffin", "level": 1},
            {"slave_id": 2, "owner_id": 22, "class_id": "ragamuffin", "level": 1},
        )
        # Seed 31 rolls below the wrong-direction chance but above the matching one.
        actions = {
            "a": {"skill_id": "bum_punch", "attack_direction": "left", "dodge_direction": "left"},
            "b": {"skill_id": "bum_punch", "attack_direction": "right", "dodge_direction": "left"},
        }
        before = state["sides"]["b"]["hp"]
        resolve_turn(state, actions, random.Random(31))
        self.assertLessEqual(state["sides"]["b"]["hp"], before)
        self.assertIn("bum_punch", BUILTIN_SKILLS)


class SlaveBattleDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "battle.sqlite3")
        await self.database.connect()
        await self.database.upsert_chat(1, "Арена")
        for user_id in (10, 20, 30, 40):
            await self.database.upsert_user(1, user_id, f"u{user_id}", f"U{user_id}")
        await self.database.force_enslave(1, 20, 10)
        await self.database.force_enslave(1, 30, 40)

    async def asyncTearDown(self):
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_battle_requires_consents_then_accepts_actions(self):
        status, battle_id = await self.database.create_slave_battle(1, 10, 20, 30)
        self.assertEqual(status, "created")
        self.assertIsNotNone(battle_id)
        self.assertEqual(await self.database.accept_slave_battle_slave(battle_id, 20), "pending")
        self.assertEqual(await self.database.accept_slave_battle_owner(battle_id, 40), "pending")
        self.assertEqual(await self.database.accept_slave_battle_slave(battle_id, 30), "active")
        waiting = await self.database.submit_slave_battle_action(
            battle_id, 20, {"skill_id": "bum_punch", "attack_direction": "left", "dodge_direction": "left"}
        )
        self.assertEqual(waiting["status"], "waiting")
        completed = await self.database.submit_slave_battle_action(
            battle_id, 30, {"skill_id": "bum_punch", "attack_direction": "right", "dodge_direction": "right"}
        )
        self.assertIn(completed["status"], {"resolved", "finished"})

    async def test_owner_control_unblocks_slave_consent_from_level_one(self):
        status, battle_id = await self.database.create_slave_battle(1, 10, 20, 30)
        self.assertEqual(status, "created")
        self.assertEqual(await self.database.set_slave_battle_control(battle_id, 10, side="a"), "pending")
        await self.database.accept_slave_battle_owner(battle_id, 40)
        self.assertEqual(await self.database.accept_slave_battle_slave(battle_id, 30), "active")
        battle = await self.database.get_slave_battle(battle_id)
        state = json.loads(battle["state_json"])
        self.assertEqual(state["sides"]["a"]["controller_id"], 10)
        self.assertTrue(state["sides"]["a"]["controlled"])

    async def test_one_owner_can_control_both_sides(self):
        await self.database.force_enslave(1, 30, 10)
        await self.database.grant_owner_xp(1, 10, 10)
        status, battle_id = await self.database.create_slave_battle(1, 10, 20, 30)
        self.assertEqual(status, "created")
        await self.database.set_slave_battle_control(battle_id, 10, side="a")
        self.assertEqual(
            await self.database.set_slave_battle_control(battle_id, 10, side="b"), "active"
        )
        first = await self.database.submit_slave_battle_action(
            battle_id, 10, {"side": "a", "skill_id": "bum_punch", "attack_direction": "left", "dodge_direction": "left"}
        )
        self.assertEqual(first["status"], "waiting")
        second = await self.database.submit_slave_battle_action(
            battle_id, 10, {"side": "b", "skill_id": "bum_punch", "attack_direction": "right", "dodge_direction": "right"}
        )
        self.assertIn(second["status"], {"resolved", "finished"})

    async def test_custom_class_can_be_granted_and_selected(self):
        definition = {
            "name": "Фембой",
            "resource_name": "Кавай",
            "base_level": 5,
            "base_stats": {
                "max_hp": 38,
                "physical_attack": 4,
                "magic_attack": 14,
                "physical_defense": 5,
                "magic_defense": 11,
                "speed": 12,
                "evasion": 12,
            },
            "growth": {"max_hp": 4, "magic_attack": 1.7, "speed": 1},
        }
        self.assertEqual(
            await self.database.create_custom_fighter_content("class", "femboy", definition, 999),
            "created",
        )
        self.assertEqual(
            await self.database.grant_custom_fighter_content(1, 20, "class", "femboy", 999),
            "granted",
        )
        await self.database.grant_slave_xp(1, 20, 72)
        self.assertEqual(await self.database.choose_slave_class(1, 20, "фембой"), "femboy")

    async def test_wasteland_starts_without_control_penalty_and_scales_by_floor(self):
        status, run = await self.database.start_wasteland_run(1, 10, 20)
        self.assertEqual(status, "created")
        self.assertIsNotNone(run)
        state = json.loads(run["state_json"])
        self.assertEqual(state["sides"]["a"]["controller_id"], 10)
        self.assertFalse(state["sides"]["a"]["controlled"])
        self.assertEqual(state["wasteland"]["enemy_level"], 1)

        self.database.connection.execute(
            "UPDATE wasteland_runs SET status='victory' WHERE id=?", (run["id"],)
        )
        self.database.connection.commit()
        advanced = await self.database.advance_wasteland_run(int(run["id"]), 10)
        self.assertEqual(advanced["status"], "active")
        self.assertEqual(advanced["floor"], 2)
        self.assertEqual(advanced["state"]["wasteland"]["enemy_level"], 2)

    async def test_wasteland_victory_grants_floor_experience(self):
        _status, run = await self.database.start_wasteland_run(1, 10, 20)
        state = json.loads(run["state_json"])
        state["sides"]["b"]["hp"] = 0
        self.database.connection.execute(
            "UPDATE wasteland_runs SET state_json=? WHERE id=?", (json.dumps(state), run["id"])
        )
        self.database.connection.commit()
        result = await self.database.submit_wasteland_action(
            int(run["id"]), 10,
            {"skill_id": "bum_punch", "attack_direction": "left", "dodge_direction": "left"},
        )
        self.assertEqual(result["status"], "victory")
        self.assertEqual(result["reward_xp"], 7)
        profile = await self.database.get_slave_profile(1, 20)
        self.assertEqual(profile["xp"], 7)


class WebAppAuthTests(unittest.TestCase):
    def test_invalid_init_data_is_rejected(self):
        self.assertIsNone(validate_telegram_init_data("auth_date=1&hash=nope", "token", now=2))
