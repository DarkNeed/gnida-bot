import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena_engine import create_battle_state, skip_turn
from arena_store import ARENA_TURN_SECONDS, ARENA_PREPARATION_SECONDS, utc_timestamp
from database import Database
import test_arena_market_client as client_tests


class SkipEngineTests(unittest.TestCase):
    def state(self):
        return create_battle_state(
            dict(slave_id=10, owner_id=10, class_id="nerd", level=20),
            dict(slave_id=20, owner_id=20, class_id="cutie", level=20),
        )

    def test_skip_ticks_buffs_and_cooldowns_not_energy_or_passives(self):
        state = self.state()
        actor = state["sides"]["a"]
        actor["resource"] = 20
        actor["mechanics"] = dict(paid_magic=2, last_magic="humiliate")
        actor["cooldowns"] = {"charging": 3, "mother_joke": 1}
        actor["effects"] = [
            dict(id="charge", kind="next_magic_damage", value=0.6, duration=2)
        ]
        skip_turn(state)
        self.assertEqual(actor["resource"], 20)
        self.assertEqual(actor["mechanics"]["paid_magic"], 2)
        self.assertEqual(actor["cooldowns"], {"charging": 2})
        self.assertEqual(actor["effects"][0]["duration"], 1)
        self.assertEqual(
            (state["turn"], state["active_side"], state["finished"]), (2, "b", False)
        )
        self.assertEqual(state["log"][-1]["action_kind"], "turn_timeout")
        self.assertFalse(state["had_player_action"])

    def test_next_side_stun_and_bleed_follow_normal_turn_rules(self):
        state = self.state()
        target = state["sides"]["b"]
        original = target["hp"]
        target["effects"] = [
            dict(id="stun", kind="stun", value=1, duration=1),
            dict(id="bleed", kind="bleed", value=3, duration=3),
        ]
        skip_turn(state)
        self.assertEqual(target["hp"], original - 3)
        self.assertEqual((state["turn"], state["active_side"]), (3, "a"))
        self.assertEqual(len(state["log"]), 2)

    def test_finished_rejects_and_cap_prevents_infinite_idle_battle(self):
        state = self.state()
        for _ in range(200):
            skip_turn(state)
        self.assertTrue(state["finished"])
        self.assertIsNone(state["winner"])
        self.assertEqual(state["finish_reason"], "turn_limit")
        with self.assertRaises(ValueError):
            skip_turn(state)


class ArenaTimerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bot.sqlite3"
        self.db = Database(self.path)
        await self.db.connect()
        await self.db.upsert_chat(1, "Test")
        for user in (10, 20, 30, 40):
            await self.db.upsert_user(1, user, str(user), str(user))
            self.db._add_francs_locked(1, user, 100)
        self.db.connection.commit()
        self.now = utc_timestamp()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def duel(self, mode="personal"):
        row = await self.db.arena_offer(1, 10, 20, mode, 50)
        self.assertEqual(row["deadline"] - row["created_at"], ARENA_PREPARATION_SECONDS)
        await self.db.arena_set_message(row["token"], 1)
        if mode == "slaves":
            await self.db.arena_setup(row["token"], 10, "select", 30)
            await self.db.arena_setup(row["token"], 20, "select", 40)
        with patch("arena_store.random.SystemRandom") as rng:
            rng.return_value.choice.return_value = "a"
            return await self.db.arena_setup(row["token"], 20, "accept")

    async def expire(self, row, at=None):
        with patch("arena_store.utc_timestamp", return_value=at or row["deadline"]):
            changed = await self.db.arena_expire()
        self.assertEqual(len(changed), 1)
        return changed[0]

    async def test_pvp_exact_deadline_skip_keeps_escrow_and_no_rewards(self):
        with patch("arena_store.utc_timestamp", return_value=self.now):
            row = await self.duel()
        self.assertEqual(row["deadline"] - self.now, ARENA_TURN_SECONDS)
        with patch("arena_store.utc_timestamp", return_value=row["deadline"] - 1):
            self.assertEqual(await self.db.arena_expire(), [])
        changed = await self.expire(row)
        state = json.loads(changed["state_json"])
        self.assertEqual((changed["status"], state["active_side"]), ("active", "b"))
        self.assertEqual(changed["revision"], row["revision"] + 1)
        self.assertEqual(changed["deadline"], row["deadline"] + 180)
        self.assertEqual((changed["escrow_a"], changed["escrow_b"]), (50, 50))
        self.assertNotIn("rewards", state)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 0)
        with patch("arena_store.utc_timestamp", return_value=row["deadline"]):
            self.assertEqual(await self.db.arena_expire(), [])

    async def test_expired_action_cannot_play_and_opponent_can_use_fresh_revision(self):
        row = await self.duel()
        with patch("arena_store.utc_timestamp", return_value=row["deadline"]):
            with self.assertRaises(ValueError):
                await self.db.arena_action(
                    row["token"], 10, row["revision"], "bum_punch"
                )
            changed = await self.db.arena_get(row["token"])
            self.assertEqual(json.loads(changed["state_json"])["turn"], 2)
            played = await self.db.arena_action(
                changed["token"], 20, changed["revision"], "bum_punch"
            )
            self.assertEqual(json.loads(played["state_json"])["turn"], 3)
            self.assertEqual(played["deadline"], row["deadline"] + 180)

    async def test_get_and_sweep_race_skip_only_once(self):
        row = await self.duel()
        with patch("arena_store.utc_timestamp", return_value=row["deadline"]):
            await asyncio.gather(
                self.db.arena_get(row["token"]),
                self.db.arena_expire(),
                self.db.arena_expire(),
            )
            changed = await self.db.arena_get(row["token"])
        self.assertEqual(changed["revision"], row["revision"] + 1)
        self.assertEqual(len(json.loads(changed["state_json"])["log"]), 1)

    async def test_potion_does_not_extend_deadline(self):
        row = await self.duel()
        state = json.loads(row["state_json"])
        state["sides"]["a"]["hp"] -= 5
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db._arena_add_item_locked(1, 10, "potion", "healing", "common", 1)
        self.db.connection.commit()
        with patch("arena_store.utc_timestamp", return_value=row["deadline"] - 10):
            changed = await self.db.arena_action(
                row["token"], 10, row["revision"], "potion"
            )
        self.assertEqual(changed["deadline"], row["deadline"])
        self.assertEqual(json.loads(changed["state_json"])["active_side"], "a")

    async def test_slave_battle_same_timer(self):
        await self.db.force_enslave(1, 30, 10)
        await self.db.force_enslave(1, 40, 20)
        await self.db.arena_equip_slave(1, 10, 30, True)
        await self.db.arena_equip_slave(1, 20, 40, True)
        row = await self.duel("slaves")
        changed = await self.expire(row)
        self.assertEqual(changed["status"], "active")
        self.assertEqual(json.loads(changed["state_json"])["active_side"], "b")

    async def test_pve_no_timeout_even_with_legacy_deadline_can_resume(self):
        row = await self.db.arena_wasteland(1, 10)
        self.assertEqual(row["deadline"], 0)
        self.db.connection.execute(
            "UPDATE arena_battles SET deadline=? WHERE token=?",
            (self.now - 1, row["token"]),
        )
        self.db.connection.commit()
        with patch("arena_store.utc_timestamp", return_value=self.now + 30 * 86400):
            self.assertEqual(await self.db.arena_expire(), [])
            changed = await self.db.arena_get(row["token"])
            self.assertEqual(changed["revision"], row["revision"])
            changed = await self.db.arena_action(
                changed["token"], 10, changed["revision"], "bum_punch"
            )
            self.assertEqual(changed["deadline"], 0)

    async def test_restart_preserves_timer_and_long_offline_skips_once(self):
        row = await self.duel()
        await self.db.close()
        with patch("arena_store.utc_timestamp", return_value=self.now + 60):
            await self.db.connect()
            resumed = await self.db.arena_get(row["token"])
        self.assertEqual(resumed["deadline"], row["deadline"])
        self.assertEqual(resumed["revision"], row["revision"])
        resumed = await self.expire(row, self.now + 86400)
        self.assertEqual(json.loads(resumed["state_json"])["turn"], 2)
        self.assertEqual(resumed["deadline"], self.now + 86400 + 180)

    async def test_legacy_live_battle_upgrade_only_once(self):
        row = await self.duel()
        state = json.loads(row["state_json"])
        del state["turn_timer_seconds"]
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=?,deadline=? WHERE token=?",
            (json.dumps(state), self.now + 10800, row["token"]),
        )
        self.db.connection.commit()
        await self.db.close()
        with patch("arena_store.utc_timestamp", return_value=self.now + 60):
            await self.db.connect()
            upgraded = await self.db.arena_get(row["token"])
        self.assertEqual(upgraded["deadline"], self.now + 240)
        self.assertEqual(upgraded["revision"], row["revision"] + 1)
        await self.db.close()
        with patch("arena_store.utc_timestamp", return_value=self.now + 90):
            await self.db.connect()
            same = await self.db.arena_get(row["token"])
        self.assertEqual(same["deadline"], upgraded["deadline"])

    async def test_idle_draw_refunds_stakes_but_gives_no_xp(self):
        row = await self.duel()
        state = json.loads(row["state_json"])
        state["turn"] = 200
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        changed = await self.expire(row)
        self.assertEqual(changed["status"], "finished")
        self.assertEqual(json.loads(changed["state_json"])["rewards"], {"a": 0, "b": 0})
        self.assertEqual(await self.db.franc_balance(1, 10), 100)
        self.assertEqual(await self.db.franc_balance(1, 20), 100)


@unittest.skipUnless(shutil.which("node"), "Node needed")
class TimerClientTests(unittest.TestCase):
    def timer(self, mode="personal", status="active", remaining=180):
        return json.loads(
            client_tests.ArenaMarketClientTests.run_client(
                self,
                "const el={classList:{toggle(){}}};document.getElementById=()=>el;Date.now=()=>1000000;current=input;updateTurnTimer();out=JSON.stringify(el);",
                dict(
                    mode=mode,
                    status=status,
                    deadline=1000 + remaining,
                    state=dict(finished=status == "finished"),
                ),
            )
        )

    def test_countdown_visible_in_pvp_hidden_for_pve_finished_and_pending(self):
        self.assertIn("03:00", self.timer()["textContent"])
        self.assertIn("00:01", self.timer(remaining=1)["textContent"])
        self.assertIn("Время вышло", self.timer(remaining=0)["textContent"])
        for mode, status in (
            ("wasteland", "active"),
            ("personal", "finished"),
            ("slaves", "pending"),
        ):
            self.assertTrue(self.timer(mode, status)["hidden"])

    def test_server_clock_offset_applied(self):
        body = client_tests.ArenaMarketClientTests.run_client(
            self,
            "const el={classList:{toggle(){}}};document.getElementById=()=>el;Date.now=()=>500000;serverClockOffset=500000;current=input;updateTurnTimer();out=el.textContent;",
            dict(
                mode="personal",
                status="active",
                deadline=1180,
                state=dict(finished=False),
            ),
        )
        self.assertIn("03:00", body)


if __name__ == "__main__":
    unittest.main()
