import asyncio
import json
import random
import shutil
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from arena_engine import FIGHTER_CLASSES, BUILTIN_SKILLS, Skill
from arena_raid_engine import create_raid_state, resolve_round, set_intent
from arena_raid_web import raid_view
from arena_web import create_arena_app
from database import Database
from handlers.raids import RAID_RE, RaidPublisher, create_raid_router
from tools.preview_arena import raid_preview
import test_arena
import test_arena_market_client as client_tests


class Roll(random.Random):
    def random(self):
        return 0

    def uniform(self, low, high):
        return 1


class RaidEngineTests(unittest.TestCase):
    def state(self, classes=("ragamuffin",) * 3, level=1):
        participants = [
            dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i)
            for i in (10, 20, 30)
        ]
        sources = [
            dict(slave_id=i, owner_id=i, class_id=cls, level=level)
            for i, cls in zip((10, 20, 30), classes)
        ]
        data = create_raid_state(participants, sources, FIGHTER_CLASSES, BUILTIN_SKILLS)
        return data

    def sturdy(self, data):
        data["boss"]["hp"] = data["boss"]["stats"]["max_hp"] = 10000
        for p in data["players"].values():
            p["fighter"]["hp"] = p["fighter"]["stats"]["max_hp"] = 10000

    def test_snapshot_independent_fighters_and_scaling(self):
        data = self.state()
        self.assertEqual(
            data["boss"]["hp"],
            round(sum(p["fighter"]["hp"] for p in data["players"].values()) * 1.4),
        )
        data["players"]["10"]["fighter"]["hp"] = 1
        self.assertGreater(data["players"]["20"]["fighter"]["hp"], 1)
        self.assertEqual(data["boss"]["level"], 1)

    def test_speed_order_ticks_cooldowns_once_and_area_attack_once(self):
        data = self.state()
        self.sturdy(data)
        for key, p in data["players"].items():
            p["selected"] = "bum_punch"
            p["fighter"]["stats"]["speed"] = int(key)
            p["fighter"]["cooldowns"]["dust_in_eyes"] = 3
        data["boss"]["effects"] = [
            dict(id="buff", kind="damage_pct", value=0.2, duration=4)
        ]
        resolve_round(data, BUILTIN_SKILLS, Roll())
        hits = [e for e in data["log"] if e.get("skill")]
        self.assertEqual([e["actor"] for e in hits], ["30", "20", "10"])
        self.assertEqual(len([e for e in data["log"] if e["actor"] == "boss"]), 3)
        self.assertEqual(data["boss"]["own_turns"], 1)
        self.assertEqual(data["boss"]["effects"][0]["duration"], 3)
        for p in data["players"].values():
            self.assertEqual(p["fighter"]["own_turns"], 1)
            self.assertEqual(p["fighter"]["cooldowns"]["dust_in_eyes"], 2)
            self.assertIsNone(p["selected"])
        self.assertEqual(data["round"], 2)

    def test_bleeding_ticks_once_not_per_attacker(self):
        data = self.state()
        self.sturdy(data)
        for f in [data["boss"], data["players"]["10"]["fighter"]]:
            f["effects"] = [dict(id="blood", kind="bleed", value=7, duration=3)]
        for p in data["players"].values():
            p["selected"] = "bum_punch"
        resolve_round(data, BUILTIN_SKILLS, Roll())
        for key in ("10", "boss"):
            events = [
                e
                for e in data["log"]
                if e["actor"] == key and "Кровотечение" in e["text"]
            ]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["damage"], 7)
        damage = sum(e.get("damage", 0) for e in data["log"] if e["target"] == "boss")
        self.assertEqual(data["boss"]["hp"], 10000 - damage)

    def test_stunned_players_skip_once_and_boss_has_control_immunity_window(self):
        data = self.state()
        self.sturdy(data)
        stun = Skill(
            "test_stun",
            "Контроль",
            "ragamuffin",
            1,
            None,
            0,
            100,
            0,
            0,
            effects=(
                {
                    "id": "stun",
                    "kind": "stun",
                    "value": 1,
                    "turns": 2,
                    "target": "enemy",
                    "chance": 1,
                },
            ),
        )
        skills = {**BUILTIN_SKILLS, stun.skill_id: stun}
        for p in data["players"].values():
            p["fighter"]["loadout"].append(stun.skill_id)
        for n in range(3):
            for p in data["players"].values():
                p["selected"] = stun.skill_id
            resolve_round(data, skills, Roll())
            self.assertEqual(data["control_lock"], (2, 1, 0)[n])
        self.assertEqual(sum("намерение сорвано" in e["text"] for e in data["log"]), 1)
        p = data["players"]["10"]
        p["fighter"]["effects"].append(
            dict(id="stun", kind="stun", value=1, duration=1)
        )
        for other in data["players"].values():
            other["selected"] = "defend"
        resolve_round(data, skills, Roll())
        self.assertFalse(any(e["kind"] == "stun" for e in p["fighter"]["effects"]))
        self.assertEqual(p["fighter"]["own_turns"], 4)

    def test_phase_change_is_announced_before_next_round(self):
        data = self.state()
        data["boss"]["hp"] = data["boss"]["stats"]["max_hp"] // 2 + 1
        for p in data["players"].values():
            p["selected"] = "bum_punch"
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertEqual(data["intent"]["phase"], 2)
        self.assertEqual(data["phase"], 2)
        self.assertTrue(
            all(
                "Размах цепью" in e["text"] for e in data["log"] if e["actor"] == "boss"
            )
        )

    def test_defense_is_refreshed_not_stacked_and_shield_expires(self):
        data = self.state()
        self.sturdy(data)
        for _ in range(5):
            for p in data["players"].values():
                p["selected"] = "defend"
            resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertFalse(
            any(e["id"].startswith("raid_shield") for e in data["boss"]["effects"])
        )
        for p in data["players"].values():
            self.assertEqual(
                len(
                    [
                        e
                        for e in p["fighter"]["effects"]
                        if e["id"].startswith("raid_guard")
                    ]
                ),
                2,
            )

    def test_energy_cost_is_native_and_timeout_defends(self):
        data = self.state(level=3)
        self.sturdy(data)
        data["players"]["10"]["selected"] = "dust_in_eyes"
        for _ in range(3):
            resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertEqual(data["players"]["10"]["fighter"]["resource"], 80)
        self.assertTrue(data["players"]["20"]["reward_blocked"])
        self.assertFalse(data["players"]["10"]["reward_blocked"])
        self.assertEqual(data["players"]["10"]["manual_turns"], 1)

    def test_invalidated_choice_falls_back_without_crashing_team(self):
        data = self.state(level=3)
        data["players"]["10"]["selected"] = "dust_in_eyes"
        data["players"]["10"]["fighter"]["resource"] = 0
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertEqual(data["round"], 2)
        self.assertTrue(any("Навык недоступен" in e["text"] for e in data["log"]))

    def test_round_cap_and_no_mutual_death_victory(self):
        data = self.state()
        self.sturdy(data)
        data["round"] = 40
        set_intent(data)
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertTrue(data["finished"])
        self.assertFalse(data["won"])
        data = self.state()
        data["boss"]["hp"] = 0
        for p in data["players"].values():
            p["fighter"]["hp"] = 0
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertFalse(data["won"])
        self.assertIn("Ничья", data["result"])


class RaidStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown
    balance = test_arena.ArenaStoreTests.balance

    async def lobby(self):
        row = await self.db.arena_raid_create(1, 10)
        await self.db.arena_raid_set_message(row["token"], 99)
        return await self.db.arena_raid_get(row["token"])

    async def start(self, slave=False):
        row = await self.lobby()
        if slave:
            await self.db.arena_raid_setup(row["token"], 10, "join", 30, False)
        for actor in (20, 50):
            row = await self.db.arena_raid_setup(row["token"], actor, "join")
        return await self.db.arena_raid_setup(
            row["token"], 10, "start", expected_revision=row["revision"]
        )

    def save(self, row, data, deadline=None):
        self.db.connection.execute(
            "UPDATE arena_raids SET data_json=?,deadline=? WHERE token=?",
            (json.dumps(data), deadline or row["deadline"], row["token"]),
        )
        self.db.connection.commit()

    async def test_lobby_limits_permissions_and_revision(self):
        row = await self.lobby()
        with self.assertRaisesRegex(ValueError, "три участника"):
            await self.db.arena_raid_setup(row["token"], 10, "start")
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row["token"], 20, "cancel")
        await self.db.arena_raid_setup(row["token"], 20, "join")
        await self.db.arena_raid_setup(row["token"], 50, "join")
        with self.assertRaisesRegex(ValueError, "изменился"):
            await self.db.arena_raid_setup(
                row["token"], 10, "start", expected_revision=row["revision"]
            )
        with self.assertRaisesRegex(ValueError, "заняты"):
            await self.db.arena_raid_setup(row["token"], 40, "join")
        await self.db.arena_raid_setup(row["token"], 20, "leave")
        self.assertEqual(
            len((await self.db.arena_raid_get(row["token"]))["participants"]), 2
        )
        await self.db.arena_raid_setup(row["token"], 10, "cancel")
        self.assertFalse(self.db._arena_busy_locked(1, 10))

    async def test_lobby_allows_mandatory_choice_but_active_raid_locks_profile(self):
        row = await self.lobby()
        for actor in (20, 50):
            await self.db.arena_raid_setup(row["token"], actor, "join")
        self.db.connection.execute(
            "UPDATE personal_profiles SET level=5 WHERE chat_id=1 AND user_id=10"
        )
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, "выбор класса"):
            await self.db.arena_raid_setup(row["token"], 10, "start")
        await self.db.arena_edit_profile(1, 10, 10, True, "progression", "stay")
        row = await self.db.arena_raid_setup(row["token"], 10, "start")
        self.assertEqual(row["status"], "active")
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 10, 10, True, "loadout", ["bum_punch"])

    async def test_reward_transaction_rolls_back_if_grant_fails(self):
        row = await self.start()
        data = json.loads(row["data_json"])
        for p in data["players"].values():
            p["manual_turns"] = 2
        data["boss"]["hp"] = 1
        self.save(row, data)
        for actor in (10, 20):
            await self.db.arena_raid_action(row["token"], actor, 1, "bum_punch")
        original = await self.db.arena_raid_get(row["token"])
        with patch.object(
            self.db, "_add_francs_locked", side_effect=RuntimeError("storage failed")
        ), patch("arena_raid_engine.random.SystemRandom", return_value=Roll()):
            with self.assertRaises(RuntimeError):
                await self.db.arena_raid_action(row["token"], 50, 1, "bum_punch")
        fresh = await self.db.arena_raid_get(row["token"])
        self.assertEqual(fresh["data_json"], original["data_json"])
        self.assertEqual(fresh["revision"], original["revision"])
        self.assertEqual(self.balance(10), 0)
        self.assertEqual(self.db._arena_profile_locked(1, 10, True)["xp"], 0)

    async def test_slave_equipment_ownership_and_duplicate(self):
        row = await self.lobby()
        await self.db.arena_equip_slave(1, 20, 40, False)
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row["token"], 10, "join", 40, False)
        with self.assertRaisesRegex(ValueError, "экипируйте"):
            await self.db.arena_raid_setup(row["token"], 20, "join", 40, False)
        await self.db.arena_raid_setup(row["token"], 10, "join", 30, False)
        with self.assertRaisesRegex(ValueError, "уже занимает"):
            await self.db.arena_raid_setup(row["token"], 30, "join", 30, False)
        with self.assertRaises(ValueError):
            await self.db.arena_equip_slave(1, 10, 30, False)
        await self.db.arena_raid_setup(row["token"], 10, "join", 10, True)
        await self.db.arena_raid_setup(row["token"], 30, "join", 30, False)
        row = await self.db.arena_raid_get(row["token"])
        self.assertFalse(row["participants"][1]["personal"])

    async def test_reservations_block_other_modes_and_are_chat_scoped(self):
        row = await self.lobby()
        for operation in (
            self.db.arena_offer(1, 10, 20, "personal"),
            self.db.arena_wasteland(1, 10, 10, personal=True),
            self.db.arena_mirror_start(1, 10, 10, True),
        ):
            with self.assertRaises(ValueError):
                await operation
        await self.db.upsert_chat(2, "Другой")
        other = await self.db.arena_raid_create(2, 10)
        self.assertNotEqual(other["token"], row["token"])
        await self.db.arena_raid_setup(row["token"], 10, "cancel")
        duel = await self.db.arena_offer(1, 10, 20, "personal")
        with self.assertRaises(ValueError):
            await self.db.arena_raid_create(1, 10)
        await self.db.arena_setup(duel["token"], 10, "cancel")

    async def test_concurrent_selection_resolves_one_round_and_cannot_replay(self):
        row = await self.start()
        deadline = row["deadline"]
        first = await self.db.arena_raid_action(row["token"], 10, 1, "bum_punch")
        self.assertEqual(first["deadline"], deadline)
        with self.assertRaisesRegex(ValueError, "уже выбрано"):
            await self.db.arena_raid_action(row["token"], 10, 1, "defend")
        await asyncio.gather(
            *(
                self.db.arena_raid_action(row["token"], i, 1, "bum_punch")
                for i in (20, 50)
            )
        )
        row = await self.db.arena_raid_get(row["token"])
        data = json.loads(row["data_json"])
        self.assertEqual(data["round"], 2)
        self.assertEqual(len([e for e in data["log"] if e.get("skill")]), 3)
        self.assertTrue(all(p["manual_turns"] == 1 for p in data["players"].values()))
        with self.assertRaisesRegex(ValueError, "Раунд"):
            await self.db.arena_raid_action(row["token"], 20, 1, "bum_punch")

    async def test_timeout_survives_restart_no_offline_round_cascade(self):
        row = await self.start()
        self.save(row, json.loads(row["data_json"]), int(time.time()) - 10000)
        path = self.db.path
        await self.db.close()
        self.db = Database(path)
        await self.db.connect()
        changed = await self.db.arena_raid_expire()
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["round"], 2)
        self.assertGreater(changed[0]["deadline"], time.time())
        self.assertEqual(await self.db.arena_raid_expire(), [])

    async def test_empty_lobby_expiration_and_failed_publication_free_slots(self):
        row = await self.lobby()
        self.db.connection.execute(
            "UPDATE arena_raids SET deadline=1 WHERE token=?", (row["token"],)
        )
        self.db.connection.commit()
        self.assertEqual((await self.db.arena_raid_expire())[0]["status"], "cancelled")
        pub = RaidPublisher(self.db, self.bot, "TestBot")
        router = create_raid_router(self.db, self.bot, True, pub)
        handler = router.message.handlers[0].callback
        msg = SimpleNamespace(
            from_user=SimpleNamespace(id=10, is_bot=False),
            chat=SimpleNamespace(id=1, type="supergroup"),
            answer=AsyncMock(side_effect=RuntimeError("publish failed")),
        )
        with self.assertRaises(RuntimeError):
            await handler(msg)
        self.assertFalse(self.db._arena_busy_locked(1, 10))

    async def test_ownership_change_withdraws_slave_not_whole_team(self):
        row = await self.start(slave=True)
        data = json.loads(row["data_json"])
        personal_stats = self.db._arena_source_locked(1, 30, 30, False, False)
        from arena_engine import create_battle_state

        original = create_battle_state(personal_stats, personal_stats)["sides"]["a"]
        self.assertLess(
            data["players"]["10"]["fighter"]["stats"]["max_hp"],
            original["stats"]["max_hp"],
        )
        await self.db.force_enslave(1, 30, 20)
        await self.db.arena_raid_expire()
        data = json.loads((await self.db.arena_raid_get(row["token"]))["data_json"])
        self.assertTrue(data["players"]["10"]["withdrawn"])
        self.assertFalse(data["finished"])
        with self.assertRaises(ValueError):
            await self.db.arena_raid_action(row["token"], 10, 1, "bum_punch")

    async def test_forged_skills_and_viewer_cannot_act(self):
        row = await self.start()
        for actor, skill, turn in (
            (40, "bum_punch", 1),
            (10, "raid_crush", 1),
            (10, "blah", 1),
            (10, "defend", True),
        ):
            with self.assertRaises(ValueError):
                await self.db.arena_raid_action(row["token"], actor, turn, skill)
        self.assertEqual(
            (await self.db.arena_raid_get(row["token"]))["revision"], row["revision"]
        )

    async def test_victory_rewards_atomic_and_inactive_or_surrender_no_reward(self):
        row = await self.start()
        data = json.loads(row["data_json"])
        for p in data["players"].values():
            p["manual_turns"] = 2
        data["players"]["20"]["reward_blocked"] = True
        data["players"]["50"]["withdrawn"] = True
        data["boss"]["hp"] = 1
        self.save(row, data)
        with patch("arena_raid.random.SystemRandom", return_value=Roll()), patch(
            "arena_raid_engine.random.SystemRandom", return_value=Roll()
        ):
            row = await self.db.arena_raid_action(row["token"], 10, 1, "bum_punch")
        data = json.loads(row["data_json"])
        self.assertEqual(row["status"], "active")  # waits for the second living player
        with patch("arena_raid.random.SystemRandom", return_value=Roll()), patch(
            "arena_raid_engine.random.SystemRandom", return_value=Roll()
        ):
            row = await self.db.arena_raid_action(row["token"], 20, 1, "defend")
        data = json.loads(row["data_json"])
        self.assertEqual(row["status"], "finished")
        self.assertEqual(set(data["rewards"]), {"10"})
        self.assertEqual(self.balance(10), 43)
        self.assertEqual(self.balance(20), 0)
        self.assertEqual(self.balance(50), 0)
        self.assertTrue(data["rewards"]["10"]["loot"])
        for _ in range(2):
            self.assertEqual(await self.db.arena_raid_expire(), [])
            with self.assertRaises(ValueError):
                await self.db.arena_raid_action(row["token"], 10, 1, "bum_punch")
        self.assertEqual(self.balance(10), 43)

    async def test_surrender_finishes_without_money(self):
        row = await self.start()
        for actor in (10, 20, 50):
            row = await self.db.arena_raid_action(row["token"], actor, 1, "surrender")
        self.assertEqual(row["status"], "finished")
        self.assertEqual(json.loads(row["data_json"])["rewards"], {})

    async def test_can_surrender_after_selecting_action(self):
        row = await self.start()
        await self.db.arena_raid_action(row["token"], 10, 1, "defend")
        row = await self.db.arena_raid_action(row["token"], 10, 1, "surrender")
        p = json.loads(row["data_json"])["players"]["10"]
        self.assertTrue(p["withdrawn"])
        self.assertTrue(p["reward_blocked"])
        self.assertIsNone(p["selected"])

    async def test_basic_attack_appears_only_as_resource_fallback(self):
        row = await self.start()
        data = json.loads(row["data_json"])
        p = data["players"]["10"]["fighter"]
        p["loadout"] = ["dust_in_eyes"]
        p["resource"] = 0
        self.save(row, data)
        view = await raid_view(self.db, await self.db.arena_raid_get(row["token"]), 10)
        self.assertEqual(
            [
                s["skill_id"]
                for s in view["data"]["players"]["10"]["fighter"]["skill_details"]
            ],
            ["dust_in_eyes", "bum_punch"],
        )
        p["resource"] = 100
        self.save(row, data)
        view = await raid_view(self.db, await self.db.arena_raid_get(row["token"]), 10)
        self.assertEqual(
            len(view["data"]["players"]["10"]["fighter"]["skill_details"]), 1
        )

    async def test_publisher_retries_telegram_rate_limit(self):
        from aiogram.exceptions import TelegramRetryAfter
        from aiogram.methods import EditMessageText

        row = await self.start()
        error = TelegramRetryAfter(EditMessageText(text="test"), "flood", retry_after=2)
        self.bot.edit_message_text = AsyncMock(side_effect=[error, None])
        pub = RaidPublisher(self.db, self.bot, "TestBot")
        await pub.changed(row["token"])
        self.assertIn(row["token"], pub.retry_at)
        await pub.changed(row["token"])
        self.assertEqual(self.bot.edit_message_text.call_count, 1)
        pub.retry_at[row["token"]] = 0
        pub.last_edit = 0
        await pub.retry_pending()
        self.assertEqual(self.bot.edit_message_text.call_count, 2)
        self.assertEqual(pub.retry_at, {})

    async def test_public_view_hides_other_choices_and_uses_custom_sprites(self):
        row = await self.start()
        row = await self.db.arena_raid_action(row["token"], 10, 1, "bum_punch")
        self.db.connection.execute(
            "INSERT INTO arena_sprites VALUES(?,?,?,?,?)",
            (1, 10, "test-key", b"test", 0),
        )
        self.db.connection.commit()
        spectator = await raid_view(self.db, row, 40)
        own = await raid_view(self.db, row, 10)
        self.assertTrue(spectator["data"]["players"]["10"]["ready"])
        self.assertIsNone(spectator["data"]["players"]["10"]["selected"])
        self.assertEqual(own["data"]["players"]["10"]["selected"], "bum_punch")
        self.assertIn("test-key", own["data"]["players"]["10"]["fighter"]["sprite_url"])
        self.assertEqual(len(spectator["data"]["boss"]["skill_details"]), 3)

    async def test_chat_join_does_not_reset_chosen_slave(self):
        row = await self.lobby()
        await self.db.arena_raid_setup(row["token"], 10, "join", 30, False)
        pub = RaidPublisher(self.db, self.bot, "TestBot")
        self.bot.edit_message_text = AsyncMock()
        router = create_raid_router(self.db, self.bot, True, pub)
        callback = SimpleNamespace(
            data="rr:join:" + row["token"],
            from_user=SimpleNamespace(id=10),
            message=SimpleNamespace(chat=SimpleNamespace(id=1)),
            answer=AsyncMock(),
        )
        await router.callback_query.handlers[0].callback(callback)
        self.assertEqual(
            (await self.db.arena_raid_get(row["token"]))["participants"][0][
                "fighter_id"
            ],
            30,
        )

    async def test_publisher_escapes_names_and_skips_readiness_spam(self):
        await self.db.upsert_user(1, 10, "10", "<b>fake</b>")
        row = await self.start()
        self.bot.edit_message_text = AsyncMock()
        pub = RaidPublisher(self.db, self.bot, "TestBot")
        await pub.changed(row["token"])
        await self.db.arena_raid_action(row["token"], 10, 1, "defend")
        await pub.changed(row["token"])
        self.assertEqual(self.bot.edit_message_text.call_count, 1)
        self.assertIn(
            "&lt;b&gt;fake&lt;/b&gt;", self.bot.edit_message_text.call_args.args[0]
        )
        self.assertIn("?startapp=r_", pub.keyboard(row).inline_keyboard[0][0].url)
        await self.db.arena_raid_action(row["token"], 10, 1, "surrender")
        await pub.changed(row["token"])
        self.assertEqual(self.bot.edit_message_text.call_count, 2)
        self.assertIn("🚪", self.bot.edit_message_text.call_args.args[0])

    async def test_http_auth_membership_join_start_and_observation_without_dm(self):
        row = await self.lobby()
        client = TestClient(
            TestServer(create_arena_app(self.db, self.bot, test_arena.TOKEN))
        )
        await client.start_server()
        path = "/api/raid/" + row["token"]

        def headers(actor):
            return {"X-Telegram-Init-Data": test_arena.signed(actor, int(time.time()))}

        try:
            self.assertEqual((await client.get(path)).status, 400)
            for actor in (20, 50):
                self.assertEqual(
                    (
                        await client.post(
                            path, headers=headers(actor), json={"action": "join"}
                        )
                    ).status,
                    200,
                )
            response = await client.post(
                path, headers=headers(10), json={"action": "start"}
            )
            self.assertEqual(response.status, 200, await response.text())
            response = await client.get(path, headers=headers(40))
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["actor_id"], 40)
            response = await client.post(
                path,
                headers=headers(40),
                json={"action": "skill", "round": 1, "skill": "defend"},
            )
            self.assertEqual(response.status, 400)
            self.bot.get_chat_member.return_value.status = "left"
            response = await client.post(
                path,
                headers=headers(10),
                json={"action": "skill", "round": 1, "skill": "defend"},
            )
            self.assertEqual(response.status, 400)
            self.assertFalse(self.bot.__dict__.get("send_message"))
        finally:
            await client.close()


@unittest.skipUnless(shutil.which("node"), "Node required")
class RaidClientTests(unittest.TestCase):
    def render(self, data):
        return client_tests.ArenaMarketClientTests().run_client(
            "document.getElementById=()=>null;raidScreen(input);", data
        )

    def test_active_one_click_skills_3_players_and_boss(self):
        body = self.render(raid_preview())
        self.assertEqual(body.count('class="raid-fighter'), 4)
        self.assertIn('data-raid="skill:', body)
        self.assertIn('data-raid="skill:defend"', body)
        self.assertNotIn("подтвердить", body.lower())
        self.assertNotIn('data-do="skill', body)
        self.assertIn('data-raid="inspect:boss"', body)

    def test_spectator_has_no_action_buttons(self):
        body = self.render(raid_preview("spectator"))
        self.assertIn("Ты зритель", body)
        self.assertNotIn('data-raid="skill:', body)

    def test_lobby_finished_and_escaped_names(self):
        body = self.render(raid_preview("lobby"))
        self.assertIn('data-raid="start" class="primary" disabled', body)
        self.assertIn('data-raid="join:p:1"', body)
        data = raid_preview("finished")
        data["data"]["players"]["1"]["fighter"]["name"] = "<script>x</script>"
        body = self.render(data)
        self.assertIn("Босс повержен", body)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", body)
        self.assertNotIn('data-raid="skill:', body)

    def test_command_matching(self):
        for text in ("/рейд", "/raid", "/рейд@GnidoBot", " /RAID  "):
            self.assertIsNotNone(RAID_RE.fullmatch(text))
        for text in ("рейд", "/рейдовый", "/рейд 20"):
            self.assertIsNone(RAID_RE.fullmatch(text))
