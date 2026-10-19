import json
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from arena_web import create_arena_app

import test_arena
from arena_engine import create_battle_state, resolve_skill, BUILTIN_SKILLS
from arena_qte_rules import replay


def recording(challenge, perfect=False):
    result = subprocess.run(
        [
            shutil.which("node"),
            str(Path(__file__).with_name("qte_live_trace.cjs")),
            json.dumps(dict(challenge, perfect=perfect)),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


class ReplayTests(unittest.TestCase):
    def test_python_replays_actual_browser_engine_for_all_patterns_and_extremes(self):
        for kind in ("attack", "defense"):
            for n, pattern in ((1, "cross"), (3, "rain"), (6, "slashes")):
                for evasion in (0, 100):
                    c = dict(
                        kind=kind,
                        strikes=n,
                        pattern=pattern,
                        seed=23,
                        stats=dict(
                            accuracy=75,
                            enemyEvasion=25,
                            enemyAccuracy=95,
                            evasion=evasion,
                        ),
                    )
                    data = recording(c)
                    self.assertEqual(
                        replay(c, data["proof"], 10), data["result"], (kind, n, evasion)
                    )

    def test_rejects_fast_forward_nan_out_of_bounds_and_unfinished_trials(self):
        c = dict(
            kind="defense",
            strikes=1,
            pattern="rain",
            seed=23,
            stats=dict(accuracy=75, enemyEvasion=25, enemyAccuracy=95, evasion=0),
        )
        for proof, elapsed in (
            (dict(ticks=720, inputs=[]), 0.1),
            (dict(ticks=719, inputs=[]), 10),
            (dict(ticks=720, inputs=[dict(t=0, target=[999, 0])]), 10),
            (dict(ticks=720, inputs=[dict(t=0, x=float("nan"))]), 10),
        ):
            with self.assertRaises(ValueError):
                replay(c, proof, elapsed)
        self.assertEqual(replay(c, dict(abort=True), 0), [False])

    def test_dodge_has_priority_and_blocks_hostile_effects(self):
        s = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id="ragamuffin", level=3),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=3),
        )
        event = resolve_skill(
            s, "a", "dust_in_eyes", qte=dict(attack=[True], dodge=[True])
        )
        self.assertFalse(event["hit"])
        self.assertTrue(event["dodged"])
        self.assertEqual(event["damage"], 0)
        self.assertFalse(s["sides"]["b"]["effects"])
        self.assertEqual(s["sides"]["a"]["resource"], 80)


class InteractiveStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown
    duel = test_arena.ArenaStoreTests.duel

    async def complete(self, row, actor, perfect=False, abort=False, scope="battle"):
        qte = await self.db.arena_qte_view(scope, row["token"], actor)
        c = qte["challenge"]
        self.assertIsNotNone(c)
        proof = dict(abort=True) if abort else recording(c, perfect)["proof"]
        with patch("arena_qte_live.time.time", return_value=c["started"] + 6.2):
            if scope == "battle":
                return await self.db.arena_interactive_action(
                    row["token"],
                    actor,
                    row["revision"],
                    "qte",
                    proof=proof,
                    challenge_id=c["id"],
                )
            return await self.db.arena_interactive_raid(
                row["token"], actor, 0, proof=proof, challenge_id=c["id"]
            )

    async def test_default_on_and_account_preference_persists(self):
        self.assertEqual(await self.db.arena_combat_settings(10), dict(minigames=True))
        await self.db.arena_combat_settings(10, False)
        self.assertEqual(await self.db.arena_combat_settings(10), dict(minigames=False))
        with self.assertRaises(ValueError):
            await self.db.arena_combat_settings(10, 1)

    async def test_pvp_stages_hide_challenge_from_other_player_and_prevent_replay(self):
        row = await self.duel()
        before = json.loads(row["state_json"])
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        q = await self.db.arena_qte_view("battle", row["token"], 20)
        self.assertIsNone(q["challenge"])
        self.assertEqual(q["actor"], 10)
        self.assertEqual(json.loads(row["state_json"])["turn"], before["turn"])
        row = await self.complete(row, 10)
        q = await self.db.arena_qte_view("battle", row["token"], 20)
        self.assertEqual(q["kind"], "defense")
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(
                row["token"],
                10,
                row["revision"],
                "qte",
                proof=dict(abort=True),
                challenge_id=q["challenge"]["id"],
            )
        row = await self.complete(row, 20, abort=True)
        state = json.loads(row["state_json"])
        self.assertEqual(state["turn"], before["turn"] + 1)
        self.assertLess(state["sides"]["b"]["hp"], before["sides"]["b"]["hp"])
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(
                row["token"],
                20,
                row["revision"],
                "qte",
                proof=dict(abort=True),
                challenge_id=q["challenge"]["id"],
            )

    async def test_disabled_players_keep_one_click_and_switching_cannot_change_current_battle(
        self,
    ):
        await self.db.arena_combat_settings(10, False)
        await self.db.arena_combat_settings(20, False)
        row = await self.duel()
        await self.db.arena_combat_settings(10, True)
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        self.assertIsNone(await self.db.arena_qte_view("battle", row["token"], 10))
        self.assertEqual(json.loads(row["state_json"])["turn"], 2)

    async def test_mixed_mode_off_attacker_still_waits_for_defenders_game(self):
        await self.db.arena_combat_settings(10, False)
        row = await self.duel()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        q = await self.db.arena_qte_view("battle", row["token"], 20)
        self.assertEqual(q["kind"], "defense")
        self.assertIsNone(
            (await self.db.arena_qte_view("battle", row["token"], 10))["challenge"]
        )
        with patch("arena_qte_live.replay", return_value=[True]):
            row = await self.complete(row, 20, abort=False)
        self.assertFalse(json.loads(row["state_json"])["log"][-1]["hit"])

    async def test_real_pvp_perfect_defense_cancels_successful_mana_shot(self):
        row = await self.duel()
        state = json.loads(row["state_json"])
        state["sides"]["a"] = create_battle_state(
            dict(
                owner_id=10,
                slave_id=10,
                class_id="mage",
                level=7,
                loadout=["mana_shot"],
            ),
            dict(owner_id=20, slave_id=20, class_id="ragamuffin", level=3),
        )["sides"]["a"]
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "mana_shot"
        )
        row = await self.complete(row, 10)
        before = json.loads(row["state_json"])["sides"]["b"]["hp"]
        row = await self.complete(row, 20, perfect=True)
        after = json.loads(row["state_json"])
        self.assertEqual(after["sides"]["b"]["hp"], before)
        self.assertTrue(after["log"][-1]["dodged"])
        self.assertFalse(after["log"][-1]["hit"])

    async def test_multiple_raid_flows_preserve_other_players_readiness(self):
        await self.db.arena_combat_settings(20, False)
        row = await self.db.arena_raid_create(1, 10, silent=True)
        row = await self.db.arena_raid_setup(row["token"], 20, "join")
        row = await self.db.arena_raid_setup(row["token"], 50, "join")
        row = await self.db.arena_raid_setup(
            row["token"], 10, "start", expected_revision=row["revision"]
        )
        data = json.loads(row["data_json"])
        data["boss"]["hp"] = data["boss"]["stats"]["max_hp"] = 10000
        for p in data["players"].values():
            p["fighter"]["hp"] = p["fighter"]["stats"]["max_hp"] = 1000
        self.db.connection.execute(
            "UPDATE arena_raids SET data_json=? WHERE token=?",
            (json.dumps(data), row["token"]),
        )
        self.db.connection.commit()
        for actor in (10, 50):
            row = await self.db.arena_interactive_raid(
                row["token"], actor, 1, "bum_punch"
            )
        row = await self.db.arena_interactive_raid(row["token"], 20, 1, "bum_punch")
        self.assertTrue(json.loads(row["data_json"])["players"]["20"]["selected"])
        for actor in (10, 50):
            for _ in range(2):
                if await self.db.arena_qte_view("raid", row["token"], actor):
                    row = await self.complete(row, actor, abort=True, scope="raid")
        after = json.loads(row["data_json"])
        self.assertEqual(after["round"], 2)
        self.assertTrue(all(p["selected"] is None for p in after["players"].values()))

    async def test_http_cannot_forge_results_or_control_someone_elses_settings(self):
        client = TestClient(
            TestServer(create_arena_app(self.db, self.bot, test_arena.TOKEN))
        )
        await client.start_server()
        try:
            headers = {
                "X-Telegram-Init-Data": test_arena.signed(10, now=int(time.time()))
            }
            response = await client.post(
                "/api/menu/1",
                headers=headers,
                json=dict(action="combat_settings", enabled=False, actor_id=20),
            )
            self.assertEqual(response.status, 200)
            self.assertFalse((await self.db.arena_combat_settings(10))["minigames"])
            self.assertTrue((await self.db.arena_combat_settings(20))["minigames"])
            await self.db.arena_combat_settings(10, True)
            row = await self.duel()
            response = await client.post(
                "/api/battle/" + row["token"],
                headers=headers,
                json=dict(
                    action="skill",
                    revision=row["revision"],
                    skill="bum_punch",
                    qte=dict(attack=[True], dodge=[False]),
                ),
            )
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["qte"]["challenge"]["kind"], "attack")
            self.assertEqual(body["state"]["turn"], 1)
            response = await client.post(
                "/api/battle/" + row["token"],
                headers=headers,
                json=dict(
                    action="qte",
                    revision=body["revision"],
                    challenge_id=body["qte"]["challenge"]["id"],
                    proof=dict(ticks=0, clicks=[], result=True),
                ),
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(
                json.loads((await self.db.arena_get(row["token"]))["state_json"])[
                    "turn"
                ],
                1,
            )
        finally:
            await client.close()

    async def test_attack_abort_costs_turn_without_free_reroll(self):
        row = await self.duel()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        row = await self.complete(row, 10, abort=True)
        self.assertEqual(json.loads(row["state_json"])["active_side"], "b")
        self.assertFalse(json.loads(row["state_json"])["log"][-1]["hit"])
        self.assertIsNone(await self.db.arena_qte_view("battle", row["token"], 20))

    async def test_expiry_and_reconnect_survive_database_reopen(self):
        row = await self.duel()
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        c = (await self.db.arena_qte_view("battle", row["token"], 10))["challenge"]
        await self.db.close()
        await self.db.connect()
        self.assertEqual(
            (await self.db.arena_qte_view("battle", row["token"], 10))["challenge"][
                "id"
            ],
            c["id"],
        )
        with patch("arena_qte_live.time.time", return_value=c["expires"] + 1):
            await self.db.arena_qte_refresh("battle", row["token"])
        row = await self.db.arena_get(row["token"])
        self.assertEqual(json.loads(row["state_json"])["active_side"], "b")

    async def test_wasteland_defense_after_real_bot_attack(self):
        row = await self.db.arena_wasteland(1, 10, 10, personal=True)
        row = await self.db.arena_interactive_action(
            row["token"], 10, row["revision"], "skill", "bum_punch"
        )
        row = await self.complete(row, 10, abort=True)
        q = await self.db.arena_qte_view("battle", row["token"], 10)
        if q:
            self.assertEqual(q["kind"], "defense")
            row = await self.complete(row, 10, abort=True)
        self.assertTrue(
            json.loads(row["state_json"])["finished"]
            or json.loads(row["state_json"])["active_side"] == "a"
        )

    async def test_solo_raid_failed_attack_still_requires_boss_defense(self):
        row = await self.db.arena_raid_create(1, 10, boss_id="lei_heng", silent=True)
        row = await self.db.arena_raid_setup(
            row["token"], 10, "start", expected_revision=row["revision"]
        )
        data = json.loads(row["data_json"])
        data["intent"]["targets"] = ["10"]
        data["intent"]["skill"] = "lei_perfected_flurry"
        data["intent"]["kind"] = "attack"
        self.db.connection.execute(
            "UPDATE arena_raids SET data_json=? WHERE token=?",
            (json.dumps(data), row["token"]),
        )
        self.db.connection.commit()
        row = await self.db.arena_interactive_raid(
            row["token"], 10, data["round"], "bum_punch"
        )
        row = await self.complete(row, 10, abort=True, scope="raid")
        q = await self.db.arena_qte_view("raid", row["token"], 10)
        self.assertEqual(q["kind"], "defense")
        hp = json.loads(row["data_json"])["players"]["10"]["fighter"]["hp"]
        row = await self.complete(row, 10, perfect=True, scope="raid")
        after = json.loads(row["data_json"])
        self.assertEqual(after["players"]["10"]["fighter"]["hp"], hp)
