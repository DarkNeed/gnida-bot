import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_engine import (
    FIGHTER_CLASSES,
    BUILTIN_SKILLS,
    create_battle_state,
    fighter_xp_limit,
    unlocked_skill_ids,
)
from arena_wasteland import enemy_source, victory_xp
from arena_web import battle_view
from database import Database


class ForcedClass(random.Random):
    def __init__(self, cls):
        super().__init__(42)
        self.cls = cls

    def choice(self, choices):
        return self.cls if self.cls in choices else choices[0]


class EnemySourceTests(unittest.TestCase):
    def test_victory_xp_uses_capped_enemy_level(self):
        for level, expected in ((1, 7), (5, 15), (10, 25), (20, 45), (200, 45), (0, 7)):
            self.assertEqual(victory_xp(level), expected)

    def test_every_builtin_class_has_native_level_appropriate_build_and_passives(self):
        for cls in FIGHTER_CLASSES:
            for level in (5, 6, 9, 20):
                with self.subTest(cls=cls, level=level):
                    source = enemy_source(level, rng=ForcedClass(cls))
                    self.assertEqual(source["class_id"], cls)
                    self.assertGreaterEqual(len(source["loadout"]), 1)
                    self.assertLessEqual(len(source["loadout"]), 4)
                    self.assertEqual(
                        len(source["loadout"]), len(set(source["loadout"]))
                    )
                    self.assertTrue(
                        set(source["loadout"]).issubset(unlocked_skill_ids(cls, level))
                    )
                    self.assertTrue(
                        any(BUILTIN_SKILLS[k].damage_type for k in source["loadout"])
                    )
                    self.assertTrue(
                        any(
                            BUILTIN_SKILLS[k].class_id == cls for k in source["loadout"]
                        )
                    )
                    state = create_battle_state(
                        source, dict(source, slave_id=10, owner_id=10)
                    )
                    self.assertEqual(
                        len(state["sides"]["a"]["passive_details"]),
                        len(FIGHTER_CLASSES[cls].passives),
                    )

    def test_early_levels_only_ragamuffin_and_level_capped(self):
        for level in (-1, 1, 2, 3, 4):
            source = enemy_source(level, rng=random.Random(1))
            self.assertEqual(source["class_id"], "ragamuffin")
            self.assertEqual(source["level"], max(1, level))
            self.assertTrue(
                all(
                    BUILTIN_SKILLS[k].unlock_level <= source["level"]
                    for k in source["loadout"]
                )
            )
        self.assertEqual(enemy_source(1000)["level"], 20)

    def test_all_classes_can_appear_and_no_adjacent_repeat_when_available(self):
        rng = random.Random(100)
        seen, previous = set(), None
        for _ in range(200):
            source = enemy_source(20, previous, rng)
            self.assertNotEqual(source["class_id"], previous)
            previous = source["class_id"]
            seen.add(previous)
        self.assertEqual(seen, set(FIGHTER_CLASSES))
        self.assertEqual(enemy_source(1, "ragamuffin")["class_id"], "ragamuffin")

    def test_high_level_skills_not_lost_to_four_low_level_slots(self):
        for cls in FIGHTER_CLASSES:
            rng = ForcedClass(cls)
            seen = set()
            for _ in range(40):
                seen.update(enemy_source(20, rng=rng)["loadout"])
            native = {s.skill_id for s in BUILTIN_SKILLS.values() if s.class_id == cls}
            self.assertTrue(native.issubset(seen), cls)


class WastelandStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "bot.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        for user in (10, 30):
            await self.db.upsert_user(1, user, str(user), str(user))
        await self.db.arena_menu(1, 10)
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, fighter_xp_limit())
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def test_each_class_persisted_displayed_and_ai_can_move(self):
        for cls, catalog in FIGHTER_CLASSES.items():
            source = enemy_source(20, rng=ForcedClass(cls))
            with patch("arena_store.enemy_source", return_value=source):
                row = await self.db.arena_wasteland(1, 10)
            self.assertEqual(row["deadline"], 0)
            state = json.loads(row["state_json"])
            state["sides"]["a"]["hp"] = state["sides"]["b"]["hp"] = 10000
            self.db.connection.execute(
                "UPDATE arena_battles SET state_json=? WHERE token=?",
                (json.dumps(state), row["token"]),
            )
            self.db.connection.commit()
            view = await battle_view(self.db, row, 10)
            enemy = view["state"]["sides"]["b"]
            self.assertEqual(enemy["class_id"], cls)
            self.assertEqual(enemy["sprite"], cls)
            self.assertEqual(enemy["resource_name"], catalog.resource_name)
            self.assertIn(catalog.name, enemy["name"])
            with patch(
                "arena_store.random.choice", side_effect=lambda choices: choices[0]
            ):
                moved = await self.db.arena_action(
                    row["token"], 10, row["revision"], "bum_punch"
                )
            self.assertEqual(moved["status"], "active")
            self.assertEqual(json.loads(moved["state_json"])["active_side"], "a")
            self.assertTrue(
                any(e["side"] == "b" for e in json.loads(moved["state_json"])["log"])
            )
            await self.db.close()
            with patch(
                "arena_store.enemy_source",
                side_effect=AssertionError("Must not reroll existing fight"),
            ):
                await self.db.connect()
                resumed = await self.db.arena_get(row["token"])
            self.assertEqual(resumed["state_json"], moved["state_json"])
            done = await self.db.arena_action(
                row["token"], 10, resumed["revision"], "surrender"
            )
            self.assertEqual(json.loads(done["state_json"])["rewards"], {"a": 0})

    async def test_next_floor_new_class_same_level_cap_and_slave_profile(self):
        await self.db.force_enslave(1, 30, 10)
        await self.db.arena_equip_slave(1, 10, 30, True)
        await self.db.grant_slave_xp(1, 30, fighter_xp_limit())
        row = await self.db.arena_wasteland(1, 10, 30, personal=False)
        state = json.loads(row["state_json"])
        previous_class = state["sides"]["b"]["class_id"]
        state.update(finished=True, winner="a")
        self.db.connection.execute(
            "UPDATE arena_battles SET status='finished',state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        with patch("arena_store.enemy_source", wraps=enemy_source) as choose:
            next_row = await self.db.arena_wasteland(1, 10, previous=row["token"])
        choose.assert_called_once_with(21, previous_class)
        next_state = json.loads(next_row["state_json"])
        self.assertNotEqual(next_state["sides"]["b"]["class_id"], previous_class)
        self.assertEqual(next_state["sides"]["b"]["level"], 20)
        self.assertEqual(
            (next_row["floor"], next_row["a_fighter"], next_row["personal_solo"]),
            (2, 30, 0),
        )
        self.assertTrue(next_state["sides"]["a"]["controlled"])
        self.assertEqual(next_row["deadline"], 0)


class WastelandRewardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        for user in (10, 30):
            await self.db.upsert_user(1, user, str(user), str(user))
        await self.db.arena_menu(1, 10)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def win(self, level, floor=1, personal=True):
        source = enemy_source(level, rng=ForcedClass("ragamuffin"))
        with patch("arena_store.enemy_source", return_value=source):
            row = await self.db.arena_wasteland(
                1, 10, 10 if personal else 30, personal=personal
            )
        state = json.loads(row["state_json"])
        state["sides"]["b"]["hp"] = 1
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=?,floor=? WHERE token=?",
            (json.dumps(state), floor, row["token"]),
        )
        self.db.connection.commit()
        with patch("arena_engine.random.SystemRandom", return_value=random.Random(1)):
            return await self.db.arena_action(
                row["token"], 10, row["revision"], "bum_punch"
            )

    async def test_personal_win_rewards_saved_level_not_floor_or_player_level(self):
        for level, floor, expected in (
            (1, 10, 7),
            (10, 1, 25),
            (20, 1, 45),
            (20, 500, 45),
        ):
            with self.subTest(level=level, floor=floor):
                self.db.connection.execute(
                    "UPDATE personal_profiles SET xp=0,level=1 WHERE chat_id=1 AND user_id=10"
                )
                self.db.connection.commit()
                row = await self.win(level, floor)
                self.assertEqual(row["status"], "finished")
                state = json.loads(row["state_json"])
                self.assertEqual(state["sides"]["b"]["level"], level)
                self.assertEqual(state["rewards"], {"a": expected})
                self.assertEqual(
                    (await self.db.arena_menu(1, 10))["personal"]["xp"], expected
                )
                with self.assertRaises(ValueError):
                    await self.db.arena_action(
                        row["token"], 10, row["revision"], "bum_punch"
                    )
                self.assertEqual(
                    (await self.db.arena_menu(1, 10))["personal"]["xp"], expected
                )
                self.assertEqual(row["deadline"], 0)

    async def test_slave_win_same_formula_owner_reward_unchanged(self):
        await self.db.force_enslave(1, 30, 10)
        await self.db.arena_equip_slave(1, 10, 30, True)
        before = (await self.db.get_owner_profile(1, 10))["xp"]
        row = await self.win(10, personal=False)
        self.assertEqual(json.loads(row["state_json"])["rewards"], {"a": 25})
        self.assertEqual((await self.db.get_slave_profile(1, 30))["xp"], 25)
        self.assertEqual((await self.db.get_owner_profile(1, 10))["xp"], before + 6)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 0)

    async def test_level_twenty_player_does_not_accumulate_more_xp(self):
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, fighter_xp_limit())
        self.db.connection.commit()
        row = await self.win(20)
        self.assertEqual(json.loads(row["state_json"])["rewards"], {"a": 0})
        self.assertEqual(
            (await self.db.arena_menu(1, 10))["personal"]["xp"], fighter_xp_limit()
        )


if __name__ == "__main__":
    unittest.main()
