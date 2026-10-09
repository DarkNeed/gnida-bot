import asyncio
import copy
import json
import random
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from arena_engine import (
    create_battle_state,
    resolve_skill,
    BUILTIN_SKILLS,
    effective_stat,
)
from arena_mirror_effects import apply_gifts, gift_cost
from arena_web import create_arena_app, battle_view, menu_view
from database import Database
from test_arena import signed, TOKEN
import test_arena_market_client as client_tests


class Roll(random.Random):
    def random(self):
        return 0

    def uniform(self, low, high):
        return 1


class Miss(Roll):
    def random(self):
        return 0.99


class MirrorEngineTests(unittest.TestCase):
    def state(self, gifts):
        state = create_battle_state(
            dict(slave_id=10, owner_id=10, class_id="cutie", level=20),
            dict(slave_id=20, owner_id=20, class_id="jock", level=20),
        )
        for side in state["sides"].values():
            side["loadout"] = list(BUILTIN_SKILLS)
        apply_gifts(state["sides"]["a"], gifts)
        return state

    def tap(self, state, skill, side="a", miss=False):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=Miss() if miss else Roll())

    def test_broken_refunds_first_miss_only_and_actual_discounted_cost(self):
        state = self.state(["broken", "nerve"])
        a = state["sides"]["a"]
        a["hp"] = 10
        self.tap(state, "uwu", miss=True)
        self.assertEqual(a["resource"], 100)
        self.tap(state, "uwu", miss=True)
        self.assertEqual(a["resource"], 92)

    def test_nerve_cost_and_validation_use_same_low_hp_threshold(self):
        state = self.state(["nerve"])
        a = state["sides"]["a"]
        a["hp"] = 10
        a["resource"] = 16
        self.assertEqual(gift_cost(a, BUILTIN_SKILLS["air_kiss"]), 16)
        self.tap(state, "air_kiss", miss=True)
        self.assertEqual(a["resource"], 0)
        self.assertEqual(gift_cost(a, BUILTIN_SKILLS["bum_punch"]), 0)
        a["hp"] = a["stats"]["max_hp"]
        self.assertEqual(gift_cost(a, BUILTIN_SKILLS["air_kiss"]), 20)

    def test_curtain_first_direct_attack_only_not_utility(self):
        state = self.state(["curtain"])
        self.tap(state, "clench", "b")
        plain = copy.deepcopy(state)
        plain["sides"]["a"]["mirror_gifts"] = []
        full = self.tap(plain, "smack", "b")["damage"]
        reduced = self.tap(state, "smack", "b")["damage"]
        self.assertAlmostEqual(reduced, full * 0.75, delta=1)
        self.assertEqual(
            self.tap(state, "smack", "b")["damage"],
            self.tap(plain, "smack", "b")["damage"],
        )

    def test_blood_heals_only_hit_bleeding_target_and_caps_hp(self):
        state = self.state(["blood"])
        a, b = state["sides"].values()
        a["hp"] = 20
        self.tap(state, "bum_punch")
        self.assertEqual(a["hp"], 20)
        b["effects"].append(dict(id="bleed", kind="bleed", value=1, duration=3))
        self.tap(state, "bum_punch", miss=True)
        self.assertEqual(a["hp"], 20)
        self.tap(state, "bum_punch")
        self.assertEqual(a["hp"], 20 + round(a["stats"]["max_hp"] * 0.05))

    def test_smile_refresh_not_stack_and_requires_successful_charm(self):
        state = self.state(["smile"])
        b = state["sides"]["b"]
        for _ in range(2):
            self.tap(state, "uwu")
        effects = [e for e in b["effects"] if e.get("id") == "mirror_smile"]
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["duration"], 2)
        self.assertAlmostEqual(
            effective_stat(b, "physical_defense"), b["stats"]["physical_defense"] * 0.9
        )

    def test_edge_risk_shell_and_focus_temporary_not_permanent_passives(self):
        state = self.state(["edge", "risk", "shell", "focus"])
        plain = self.state([])
        a = state["sides"]["a"]
        self.assertEqual(len(a["passive_details"]), 2)
        self.assertAlmostEqual(
            effective_stat(a, "physical_defense"), a["stats"]["physical_defense"] * 0.97
        )
        damage = self.tap(plain, "bum_punch")["damage"]
        self.assertAlmostEqual(
            self.tap(state, "bum_punch")["damage"], damage * 1.3, delta=1
        )
        self.assertNotIn(
            "mirror_gifts",
            create_battle_state(
                dict(slave_id=1, owner_id=1, class_id="jock", level=5),
                dict(slave_id=2, owner_id=2, class_id="jock", level=5),
            )["sides"]["a"],
        )


class MirrorStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        await self.db.upsert_chat(2, "Other")
        for user in (10, 20, 30):
            await self.db.upsert_user(1, user, str(user), str(user))
        await self.db.arena_menu(1, 10)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def move(self, run, action, value=""):
        return await self.db.arena_mirror_action(
            run["token"], 10, run["revision"], action, value
        )

    async def win(self, run, hp=10, resource=20):
        row = await self.db.arena_get(run["battle_token"])
        state = json.loads(row["state_json"])
        state["sides"]["b"]["hp"] = 1
        state["sides"]["a"]["hp"] = hp
        state["sides"]["a"]["resource"] = resource
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        with patch("arena_engine.random.SystemRandom", return_value=Roll()):
            done = await self.db.arena_action(
                row["token"], 10, row["revision"], "bum_punch"
            )
        self.assertEqual(done["status"], "finished")
        return await self.db.arena_mirror_get(run["token"], 10)

    async def gift(self, run):
        return await self.move(run, "gift", run["choices"][0]["id"])

    async def test_start_full_resources_no_timer_and_restart_preserves_choices(self):
        run = await self.db.arena_mirror_start(1, 10)
        self.assertEqual((run["floor"], run["hp"], run["resource"]), (1, 20, 100))
        self.assertEqual((await self.db.arena_get(run["battle_token"]))["deadline"], 0)
        run = await self.win(run)
        self.assertEqual((run["phase"], run["hp"], run["resource"]), ("gift", 10, 50))
        self.assertEqual(len(run["choices"]), 3)
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.arena_mirror_get(run["token"], 10), run)
        self.assertEqual((await menu_view(self.db, 1, 10))["mirror_runs"][0], run)

    async def test_five_floors_rewards_once_inventory_and_permanent_class_unchanged(
        self,
    ):
        original = (await self.db.arena_menu(1, 10))["personal"]
        run = await self.db.arena_mirror_start(1, 10)
        for floor in range(1, 6):
            self.assertEqual(run["floor"], floor)
            row = await self.db.arena_get(run["battle_token"])
            state = json.loads(row["state_json"])
            self.assertEqual(state["sides"]["a"]["level"], 1)  # Frozen run build.
            if floor == 5:
                self.assertGreater(state["sides"]["b"]["hp"], 20)
            run = await self.win(run)
            if floor < 5:
                self.assertEqual(run["francs"], 0)
                run = await self.gift(run)
                run = await self.move(run, "route", "rest")
                run = await self.move(run, "next")
        self.assertEqual((run["status"], run["phase"]), ("finished", "ended"))
        self.assertEqual(run["xp"], sum(5 + 2 * level for level in range(1, 6)))
        self.assertEqual(await self.db.franc_balance(1, 10), 55)
        self.assertTrue(run["loot"])
        self.assertEqual(len((await self.db.arena_market_view(1, 10))["inventory"]), 1)
        for action in ("next", "abandon", "gift"):
            with self.assertRaises(ValueError):
                await self.move(run, action, "edge")
        self.assertEqual(await self.db.franc_balance(1, 10), 55)
        profile = (await self.db.arena_menu(1, 10))["personal"]
        self.assertEqual(profile["class_id"], original["class_id"])
        self.assertEqual(profile["loadout"], original["loadout"])
        self.assertFalse(self.db._arena_busy_locked(1, 10))

    async def test_busy_between_fights_blocks_duel_reset_and_parallel_start(self):
        results = await asyncio.gather(
            self.db.arena_mirror_start(1, 10),
            self.db.arena_mirror_start(1, 10),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        run = next(r for r in results if isinstance(r, dict))
        run = await self.win(run)
        for call in (
            self.db.arena_wasteland(1, 10),
            self.db.arena_offer(1, 10, 20, "personal"),
            self.db.arena_edit_profile(1, 10, 10, True, "reset_class", True),
        ):
            with self.assertRaises(ValueError):
                await call
        ended = await self.move(run, "abandon")
        self.assertEqual(ended["status"], "cancelled")
        self.assertFalse(self.db._arena_busy_locked(1, 10))
        await self.db.arena_wasteland(1, 10)

    async def test_surrender_no_current_rewards_no_francs(self):
        run = await self.db.arena_mirror_start(1, 10)
        row = await self.db.arena_get(run["battle_token"])
        done = await self.db.arena_action(
            row["token"], 10, row["revision"], "surrender"
        )
        self.assertEqual(json.loads(done["state_json"])["rewards"], {"a": 0})
        run = await self.db.arena_mirror_get(run["token"], 10)
        self.assertEqual(run["status"], "lost")
        self.assertEqual((run["xp"], run["francs"]), (0, 0))
        self.assertEqual(await self.db.franc_balance(1, 10), 0)
        self.assertFalse(self.db._arena_busy_locked(1, 10))

    async def test_rest_resource_carry_and_temporary_gifts_next_floor(self):
        run = await self.win(await self.db.arena_mirror_start(1, 10))
        run = await self.gift(run)
        gift = run["gifts"][0]["id"]
        run = await self.move(run, "route", "rest")
        self.assertEqual((run["hp"], run["resource"]), (17, 85))
        run = await self.move(run, "next")
        state = json.loads((await self.db.arena_get(run["battle_token"]))["state_json"])
        self.assertEqual(
            (state["sides"]["a"]["hp"], state["sides"]["a"]["resource"]), (17, 85)
        )
        self.assertEqual(state["sides"]["a"]["mirror_gifts"], [gift])
        self.assertEqual(len(state["sides"]["a"]["passive_details"]), 0)

    async def test_invalid_and_concurrent_gift_do_not_duplicate(self):
        run = await self.win(await self.db.arena_mirror_start(1, 10))
        with self.assertRaises(ValueError):
            await self.move(run, "gift", "made_up")
        self.assertEqual(await self.db.arena_mirror_get(run["token"], 10), run)
        results = await asyncio.gather(
            self.gift(run), self.gift(run), return_exceptions=True
        )
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(
            len((await self.db.arena_mirror_get(run["token"], 10))["gifts"]), 1
        )

    async def test_merchant_local_currency_only_and_one_purchase(self):
        run = await self.gift(await self.win(await self.db.arena_mirror_start(1, 10)))
        run = await self.move(run, "route", "merchant")
        bought = await self.move(run, "shop", "heal")
        self.assertEqual((bought["hp"], bought["shards"]), (20, 15))
        self.assertEqual(await self.db.franc_balance(1, 10), 0)
        with self.assertRaises(ValueError):
            await self.move(bought, "shop", "gift")
        self.assertEqual((await self.db.arena_market_view(1, 10))["inventory"], [])

    async def test_event_risk_has_bounded_hp_cost_and_temporary_curse(self):
        run = await self.gift(await self.win(await self.db.arena_mirror_start(1, 10)))
        with patch("arena_mirror.random.SystemRandom") as rng:
            rng.return_value.choice.return_value = "altar"
            run = await self.move(run, "route", "event")
        run = await self.move(run, "event", "risk")
        self.assertEqual(run["hp"], 6)
        self.assertIn("risk", [g["id"] for g in run["gifts"]])
        with self.assertRaises(ValueError):
            await self.move(run, "event", "risk")
        run = await self.move(run, "next")
        state = json.loads((await self.db.arena_get(run["battle_token"]))["state_json"])
        a = state["sides"]["a"]
        expected = 0.97 if "shell" in a["mirror_gifts"] else 0.85
        self.assertAlmostEqual(
            effective_stat(a, "magic_defense"), a["stats"]["magic_defense"] * expected
        )

    async def test_outsider_and_chat_scope_and_no_normal_wasteland_continuation(self):
        run = await self.db.arena_mirror_start(1, 10)
        with self.assertRaises(ValueError):
            await self.db.arena_mirror_get(run["token"], 20)
        with self.assertRaises(ValueError):
            await self.db.arena_mirror_action(
                run["token"], 20, run["revision"], "abandon"
            )
        self.assertEqual(await self.db.arena_mirror_list(2, 10), [])
        run = await self.win(run)
        with self.assertRaises(ValueError):
            await self.db.arena_wasteland(1, 10, previous=run["battle_token"])

    async def test_slave_requires_equipment_and_transfer_ends_run_between_floors(self):
        await self.db.force_enslave(1, 30, 10)
        with self.assertRaises(ValueError):
            await self.db.arena_mirror_start(1, 10, 30, False)
        await self.db.arena_equip_slave(1, 10, 30, True)
        run = await self.win(await self.db.arena_mirror_start(1, 10, 30, False))
        self.assertEqual((await self.db.get_slave_profile(1, 30))["xp"], 7)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 0)
        with self.assertRaises(ValueError):
            await self.db.arena_equip_slave(1, 10, 30, False)
        await self.db.force_enslave(1, 30, 20)
        ended = await self.db.arena_mirror_get(run["token"], 10)
        self.assertEqual(ended["status"], "cancelled")
        self.assertFalse(self.db._arena_busy_locked(1, 10))
        self.assertEqual(await self.db.franc_balance(1, 10), 0)

    async def test_failed_payout_rolls_back_entire_boss_completion(self):
        run = await self.db.arena_mirror_start(1, 10)
        row = self.db._mirror_row_locked(run["token"])
        data = json.loads(row["data_json"])
        data["floor"] = 5
        self.db.connection.execute(
            "UPDATE arena_mirror_runs SET data_json=? WHERE token=?",
            (json.dumps(data), run["token"]),
        )
        self.db.connection.commit()
        with patch.object(
            self.db, "_add_francs_locked", side_effect=RuntimeError("test failure")
        ):
            with self.assertRaises(RuntimeError):
                await self.win(run)
        after = await self.db.arena_mirror_get(run["token"], 10)
        self.assertEqual(after["status"], "active")
        self.assertEqual(after["xp"], 0)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 0)

    async def test_slave_transfer_during_combat_cancels_for_owner_and_self(self):
        for self_control in (False, True):
            await self.db.force_enslave(1, 30, 10)
            await self.db.arena_equip_slave(1, 10, 30, True)
            actor = 30 if self_control else 10
            run = await self.db.arena_mirror_start(1, actor, 30, False)
            battle = await self.db.arena_get(run["battle_token"])
            await self.db.force_enslave(1, 30, 20)
            with self.assertRaises(ValueError):
                await self.db.arena_action(
                    battle["token"], actor, battle["revision"], "bum_punch"
                )
            self.assertEqual(
                (await self.db.arena_get(battle["token"]))["status"], "cancelled"
            )
            self.assertEqual(
                (await self.db.arena_mirror_get(run["token"], actor))["status"],
                "cancelled",
            )
            self.assertEqual((await self.db.get_slave_profile(1, 30))["xp"], 0)
            self.assertFalse(self.db._arena_busy_locked(1, actor))

    async def test_chest_success_trap_and_safe_outcomes_are_saved_once(self):
        for choice, roll, hp, shards in (
            ("risk", 0, 10, 65),
            ("risk", 0.99, 7, 35),
            ("safe", 0, 10, 35),
        ):
            run = await self.gift(
                await self.win(await self.db.arena_mirror_start(1, 10))
            )
            with patch("arena_mirror.random.SystemRandom") as rng:
                rng.return_value.choice.return_value = "chest"
                run = await self.move(run, "route", "event")
                rng.return_value.random.return_value = roll
                after = await self.move(run, "event", choice)
            self.assertEqual(
                (after["hp"], after["shards"], after["phase"]), (hp, shards, "ready")
            )
            with self.assertRaises(ValueError):
                await self.move(run, "event", choice)
            self.assertEqual(await self.db.arena_mirror_get(run["token"], 10), after)
            await self.move(after, "abandon")

    async def test_insufficient_shards_and_empty_gift_pool_do_not_corrupt_run(self):
        run = await self.gift(await self.win(await self.db.arena_mirror_start(1, 10)))
        run = await self.move(run, "route", "merchant")
        row = self.db._mirror_row_locked(run["token"])
        data = json.loads(row["data_json"])
        data["shards"] = 0
        self.db._mirror_save_locked(row, data)
        self.db.connection.commit()
        run = await self.db.arena_mirror_get(run["token"], 10)
        with self.assertRaises(ValueError):
            await self.move(run, "shop", "gift")
        self.assertEqual(await self.db.arena_mirror_get(run["token"], 10), run)
        run = await self.move(run, "shop", "leave")
        run = await self.move(run, "next")
        row = self.db._mirror_row_locked(run["token"])
        data = json.loads(row["data_json"])
        from arena_mirror_effects import NORMAL_GIFTS

        data["gifts"] = list(NORMAL_GIFTS)
        self.db._mirror_save_locked(row, data)
        self.db.connection.commit()
        run = await self.win(run)
        self.assertEqual((run["phase"], run["choices"]), ("route", []))

    async def test_battle_view_shows_actual_gift_cost_and_bonuses(self):
        run = await self.db.arena_mirror_start(1, 10)
        row = await self.db.arena_get(run["battle_token"])
        state = json.loads(row["state_json"])
        a = state["sides"]["a"]
        a.update(hp=1, loadout=["air_kiss"])
        apply_gifts(a, ["focus", "edge", "risk", "nerve"])
        row["state_json"] = json.dumps(state)
        side = (await battle_view(self.db, row, 10))["state"]["sides"]["a"]
        self.assertEqual(side["skill_details"][0]["cost"], 16)
        self.assertEqual(side["accuracy_bonus"], 8)
        self.assertAlmostEqual(side["damage_bonus"], 0.3)

    async def test_concurrent_boss_completion_awards_once(self):
        run = await self.db.arena_mirror_start(1, 10)
        mirror = self.db._mirror_row_locked(run["token"])
        data = json.loads(mirror["data_json"])
        data["floor"] = 5
        self.db._mirror_save_locked(mirror, data)
        battle = await self.db.arena_get(run["battle_token"])
        state = json.loads(battle["state_json"])
        state["sides"]["b"]["hp"] = 1
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), battle["token"]),
        )
        self.db.connection.commit()
        with patch("arena_engine.random.SystemRandom", return_value=Roll()):
            results = await asyncio.gather(
                *[
                    self.db.arena_action(
                        battle["token"], 10, battle["revision"], "bum_punch"
                    )
                    for _ in range(2)
                ],
                return_exceptions=True
            )
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(await self.db.franc_balance(1, 10), 55)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 7)


class MirrorHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await MirrorStoreTests.asyncSetUp(self)
        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member"))
        )
        self.client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await self.client.start_server()
        self.headers = {"X-Telegram-Init-Data": signed(10, int(time.time()))}

    async def asyncTearDown(self):
        await self.client.close()
        await MirrorStoreTests.asyncTearDown(self)

    async def test_signed_start_resume_and_authorization(self):
        response = await self.client.post(
            "/api/menu/1",
            headers=self.headers,
            json={"action": "mirror_start", "fighter": 10, "personal": True},
        )
        self.assertEqual(response.status, 200, await response.text())
        run = (await response.json())["mirror"]
        response = await self.client.get(
            "/api/mirror/" + run["token"], headers=self.headers
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["battle_token"], run["battle_token"])
        response = await self.client.get(
            "/api/mirror/" + run["token"],
            headers={"X-Telegram-Init-Data": signed(20, int(time.time()))},
        )
        self.assertEqual(response.status, 400)
        response = await self.client.post(
            "/api/mirror/" + run["token"],
            headers=self.headers,
            json={"action": "abandon", "revision": run["revision"], "value": ""},
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await response.json())["status"], "cancelled")

    async def test_membership_and_types_and_no_unsigned_access(self):
        response = await self.client.post(
            "/api/menu/1", json={"action": "mirror_start"}
        )
        self.assertEqual(response.status, 400)
        response = await self.client.post(
            "/api/menu/1",
            headers=self.headers,
            json={"action": "mirror_start", "personal": "true"},
        )
        self.assertEqual(response.status, 400)
        self.bot.get_chat_member.return_value = SimpleNamespace(status="left")
        response = await self.client.post(
            "/api/menu/1", headers=self.headers, json={"action": "mirror_start"}
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(await self.db.arena_mirror_list(1, 10), [])


@unittest.skipUnless(shutil.which("node"), "Node is needed for client tests")
class MirrorClientTests(unittest.TestCase):
    def run_data(self, phase):
        return dict(
            token="test",
            chat_id=1,
            status="active",
            phase=phase,
            floor=2,
            total_floors=5,
            hp=10,
            max_hp=20,
            resource=50,
            resource_max=100,
            shards=35,
            xp=7,
            francs=0,
            loot="",
            result="",
            event="altar",
            battle_token="battle",
            gifts=[],
            choices=[dict(id="edge", name="Острый отблеск", description="Урон +10%")],
        )

    def test_each_run_phase_renders_choices_and_escape_text(self):
        for phase, text in (
            ("combat", "Открыть бой"),
            ("gift", "Выбери дар"),
            ("route", "Куда пойдёшь"),
            ("event", "Принести жертву"),
            ("merchant", "Торговец отражениями"),
            ("ready", "На этаж 3"),
        ):
            data = self.run_data(phase)
            data["result"] = "<script>bad</script>"
            body = client_tests.ArenaMarketClientTests.run_client(
                self, "closeStats=()=>{};mirrorScreen(input);", data
            )
            self.assertIn(text, body)
            self.assertNotIn("<script>", body)


if __name__ == "__main__":
    unittest.main()
