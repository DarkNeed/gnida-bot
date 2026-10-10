"""Lei Heng's telegraphed mechanics, native tractate and persistent personal loot."""

import json
import random
import unittest
import subprocess
import shutil
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

import test_arena
import test_arena_market_client as client_tests
from arena_engine import (
    BUILTIN_SKILLS,
    FIGHTER_CLASSES,
    create_battle_state,
    resolve_skill,
    skill_restriction,
    unlocked_skill_ids,
    validate_skill,
)
from arena_raid_engine import (
    create_raid_state,
    resolve_round,
    set_intent,
    native_attack,
    BOSS_SKILLS,
)
from arena_raid_web import raid_view
from handlers.raids import RAID_RE, RaidPublisher, create_raid_router
from tools.preview_arena import raid_preview


class Hit(random.Random):
    def random(self):
        return 0

    def uniform(self, a, b):
        return 1


class NoLoot(random.Random):
    def random(self):
        return 1


def state():
    participants = [
        dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i) for i in (1, 2, 3)
    ]
    sources = [
        dict(slave_id=i, owner_id=i, class_id="ragamuffin", level=10) for i in (1, 2, 3)
    ]
    data = create_raid_state(
        participants, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, "lei_heng"
    )
    for fighter in [data["boss"]] + [p["fighter"] for p in data["players"].values()]:
        fighter["hp"] = fighter["stats"]["max_hp"] = 10000
    return data


class LeiEngineTests(unittest.TestCase):
    def test_distinct_boss_and_command_aliases(self):
        data = state()
        self.assertIn("Лей Хенг", data["boss"]["name"])
        self.assertEqual(
            set(data["boss"]["loadout"]),
            {"lei_double_slash", "lei_explosive_slash", "lei_perfected_flurry"},
        )
        for text in (
            "/рейд лейхенг",
            "/рейд Лей Хенг",
            "/raid lei_heng",
            "/рейд@GnidoBot лейхенг",
        ):
            self.assertIsNotNone(RAID_RE.fullmatch(text))
        self.assertIsNone(RAID_RE.fullmatch("/рейд 20"))
        self.assertIsNone(RAID_RE.fullmatch("/рейд лейхенг что-то"))

    def test_prey_every_third_round_and_no_stale_marker(self):
        data = state()
        for round_number in range(1, 10):
            data["round"] = round_number
            set_intent(data)
            marked = [
                k
                for k, p in data["players"].items()
                if any(e.get("id") == "lei_prey" for e in p["fighter"]["effects"])
            ]
            if round_number % 3 == 0:
                self.assertEqual(marked, data["intent"]["targets"])
                self.assertEqual(data["intent"]["skill"], "lei_perfected_flurry")
            else:
                self.assertEqual(marked, [])

    def signature(self, defend=False):
        data = state()
        data["round"] = 3
        set_intent(data)
        for key, player in data["players"].items():
            player["selected"] = "defend" if defend and key == "1" else "bum_punch"
        resolve_round(data, BUILTIN_SKILLS, Hit())
        event = next(e for e in data["log"] if e.get("skill") == "lei_perfected_flurry")
        return data, event

    def test_guard_signature_triple_visuals_and_overheat(self):
        attacking, attack_event = self.signature()
        guarded, guard_event = self.signature(True)
        self.assertLessEqual(guard_event["damage"], round(attack_event["damage"] * 0.4))
        self.assertGreater(guard_event["damage"], 0)
        self.assertEqual(sum(guard_event["hits"]), guard_event["damage"])
        self.assertEqual(len(guard_event["hits"]), 3)
        self.assertEqual(guarded["boss"]["own_turns"], 1)
        self.assertTrue(
            any(e.get("id") == "lei_overheat" for e in guarded["boss"]["effects"])
        )
        normal = deepcopy(attacking)
        normal["boss"]["effects"] = []
        for data in (attacking, normal):
            for p in data["players"].values():
                p["selected"] = "bum_punch"
            resolve_round(data, BUILTIN_SKILLS, Hit())

        def hit(data):
            return next(
                e["damage"]
                for e in data["log"]
                if e["round"] == 4 and e["actor"] == "1"
            )

        self.assertAlmostEqual(hit(attacking) / hit(normal), 1.25, delta=0.08)
        self.assertFalse(
            any(e.get("id") == "lei_overheat" for e in attacking["boss"]["effects"])
        )

    def test_phase_frozen_before_choices_and_dead_prey_redirect(self):
        data = state()
        data["round"] = 3
        set_intent(data)
        data["boss"]["hp"] = 4999
        data["players"]["1"]["withdrawn"] = True
        for p in data["players"].values():
            p["selected"] = "defend"
        resolve_round(data, BUILTIN_SKILLS, Hit())
        event = next(e for e in data["log"] if e.get("skill") == "lei_perfected_flurry")
        self.assertEqual(event["target"], "2")
        self.assertEqual(data["intent"]["phase"], 2)

    def test_signature_guard_multiplies_existing_damage_debuffs(self):
        data = state()
        boss, player = data["boss"], data["players"]["1"]["fighter"]
        boss["effects"] = [
            dict(id="adoration", kind="damage_pct", value=-0.4, duration=2)
        ]
        baseline = native_attack(
            deepcopy(boss), deepcopy(player), "lei_perfected_flurry", BOSS_SKILLS, Hit()
        )["damage"]
        boss["effects"].append(
            dict(id="guard", kind="final_damage_multiplier", value=0.4, duration=1)
        )
        guarded = native_attack(
            boss, player, "lei_perfected_flurry", BOSS_SKILLS, Hit()
        )["damage"]
        self.assertAlmostEqual(guarded, baseline * 0.4, delta=1)

    def test_stun_cancels_signature_without_overheat(self):
        from arena_engine import Skill

        data = state()
        data["round"] = 3
        set_intent(data)
        skill = Skill(
            "test_stun",
            "Контроль",
            "raid",
            1,
            None,
            0,
            100,
            0,
            0,
            effects=(
                {
                    "id": "control",
                    "kind": "stun",
                    "value": 1,
                    "turns": 1,
                    "target": "enemy",
                },
            ),
        )
        for p in data["players"].values():
            p["selected"] = "defend"
        data["players"]["1"]["fighter"]["loadout"].append("test_stun")
        data["players"]["1"]["selected"] = "test_stun"
        resolve_round(data, BUILTIN_SKILLS | {"test_stun": skill}, Hit())
        self.assertTrue(any("намерение сорвано" in e["text"] for e in data["log"]))
        self.assertFalse(
            any(e.get("id") == "lei_overheat" for e in data["boss"]["effects"])
        )

    def test_native_tractate_level_action_cost_cooldown_and_single_resolution(self):
        source = dict(
            slave_id=1,
            owner_id=1,
            class_id="ragamuffin",
            level=10,
            loadout=["tigerslayer_flurry"],
            granted_skills=["tigerslayer_flurry"],
        )
        battle = create_battle_state(source, dict(source, slave_id=2, owner_id=2))
        actor, target = battle["sides"].values()
        target["hp"] = target["stats"]["max_hp"] = 10000
        for turns in (0, 1):
            actor["own_turns"] = turns
            with self.assertRaisesRegex(ValueError, "третьего"):
                validate_skill(battle, "a", "tigerslayer_flurry")
        actor["own_turns"] = 2
        before = target["hp"]
        event = resolve_skill(
            battle, "a", "tigerslayer_flurry", rng=Hit(), advance_turn=False
        )
        self.assertEqual(actor["resource"], 55)
        self.assertEqual(actor["cooldowns"]["tigerslayer_flurry"], 4)
        self.assertEqual(actor["own_turns"], 3)
        self.assertEqual(sum(event["hits"]), before - target["hp"])
        self.assertEqual(len(battle["log"]), 1)
        actor["level"] = 9
        self.assertIn(
            "10", skill_restriction(actor, BUILTIN_SKILLS["tigerslayer_flurry"])
        )
        self.assertNotIn("tigerslayer_flurry", unlocked_skill_ids("ragamuffin", 20))

    def test_raid_client_sprite_marker_and_triple_replay(self):
        run = client_tests.ArenaMarketClientTests().run_client
        preview = raid_preview("lei_heng")
        rendered = run("updateRaidTimer=()=>{};raidScreen(input)", preview)
        self.assertIn("/static/assets/lei_heng.png", rendered)
        self.assertIn("Добыча", rendered)
        self.assertEqual(rendered.count('class="raid-fighter'), 4)
        animation = raid_preview("lei_heng_animation")
        event = next(e for e in animation["data"]["log"] if e.get("hits"))
        source = (
            (Path(__file__).resolve().parents[1] / "webapp" / "battle-client")
            .read_text(encoding="utf-8")
            .rsplit("boot();", 1)[0]
        )
        script = """
const vm=require('node:vm'),payload=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const c={window:{Telegram:undefined,matchMedia:()=>({matches:true})},document:{getElementById:()=>({addEventListener(){},querySelector:()=>({classList:{add(){},remove(){}}})}),querySelector:()=>null,addEventListener(){}},location:{search:'',hostname:'example.test'},URLSearchParams,URL,setInterval(){},setTimeout(cb){cb()},clearTimeout(){},input:payload.event};
vm.runInNewContext(payload.source+`
let impacts=0,numbers=[];slashImpact=async()=>{impacts++};raidPopup=(k,n)=>numbers.push(n);
raidAnimate(input).then(()=>({impacts,numbers}));`,c).then(result=>process.stdout.write(JSON.stringify(result))).catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script],
            input=json.dumps(dict(source=source, event=event)),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), {"impacts": 3, "numbers": event["hits"]}
        )


class LeiStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown
    balance = test_arena.ArenaStoreTests.balance

    async def start(self, boss_id="lei_heng", chat=1):
        row = await self.db.arena_raid_create(chat, 10, boss_id)
        await self.db.arena_raid_set_message(row["token"], 99)
        for actor in (20, 50):
            row = await self.db.arena_raid_setup(row["token"], actor, "join")
        return await self.db.arena_raid_setup(row["token"], 10, "start")

    def win(self, row, eligible=("10",)):
        data = json.loads(row["data_json"])
        data.update(finished=True, won=True, result="Босс повержен!")
        data["boss"]["hp"] = 0
        for key, p in data["players"].items():
            p["manual_turns"] = 2 if key in eligible else 0
        self.db._raid_finish_locked(row, data)
        self.db.connection.commit()
        return data

    def misses(self, actor=10, chat=1):
        row = self.db.connection.execute(
            "SELECT misses FROM arena_raid_loot_pity WHERE chat_id=? AND actor_id=? AND boss_id='lei_heng'",
            (chat, actor),
        ).fetchone()
        return row["misses"] if row else None

    async def test_pity_fifth_win_reset_eligibility_restart_and_chat_scope(self):
        with patch("arena_raid.random.SystemRandom", return_value=NoLoot()):
            for attempt in range(1, 6):
                row = await self.start()
                data = self.win(row)
                self.assertEqual(self.misses(), attempt if attempt < 5 else 0)
                self.assertEqual(self.misses(20), None)
                self.assertEqual(bool(data["rewards"]["10"]["loot"]), attempt == 5)
                self.assertEqual(await self.db.arena_raid_expire(), [])
                if attempt == 3:
                    await self.db.close()
                    await self.db.connect()
            items = self.db.connection.execute(
                "SELECT * FROM arena_inventory WHERE owner_id=10 AND content_id='tigerslayer_flurry'"
            ).fetchall()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["quantity"], 1)
            await self.db.upsert_chat(2, "Другой чат")
            self.win(await self.start(chat=2))
            self.assertEqual(self.misses(chat=2), 1)
            self.assertEqual(self.misses(), 0)

    async def test_twenty_percent_drop_and_transaction_rollback(self):
        with patch("arena_raid.random.SystemRandom", return_value=Hit()):
            data = self.win(await self.start())
        self.assertIn("поступь", data["rewards"]["10"]["loot"])
        self.assertEqual(self.misses(), 0)
        self.db.connection.execute("UPDATE arena_raid_loot_pity SET misses=4")
        self.db.connection.commit()
        row = await self.start()
        before = self.balance(10)
        with patch.object(
            self.db, "_arena_add_item_locked", side_effect=RuntimeError("write failed")
        ):
            with self.assertRaises(RuntimeError):
                self.win(row)
            self.db.connection.rollback()
        self.assertEqual(self.misses(), 4)
        self.assertEqual(self.balance(10), before)
        self.assertEqual(
            (await self.db.arena_raid_get(row["token"]))["status"], "active"
        )

    async def test_legacy_migration_and_public_boss_decoration(self):
        row = await self.start()
        public = await raid_view(self.db, row, 10)
        self.assertEqual(
            public["data"]["boss"]["class_avatar_url"], "/static/assets/lei_heng.png"
        )
        self.assertEqual(public["boss_id"], "lei_heng")
        self.assertEqual(public["recommended_level"], 10)
        self.db.connection.execute("ALTER TABLE arena_raids DROP COLUMN boss_id")
        self.db._connect_raids()
        row = await self.db.arena_raid_get(row["token"])
        self.assertEqual(row["boss_id"], "iron")
        with self.assertRaisesRegex(ValueError, "Неизвестный"):
            await self.db.arena_raid_create(1, 50, "unknown")

    async def test_merchant_excludes_raid_tractate(self):
        catalog = self.db._arena_shop_catalog_locked()
        self.assertNotIn("tigerslayer_flurry", str(catalog))

    async def test_drop_threshold_and_native_inventory_transfer_replacement(self):
        with patch(
            "arena_raid.random.SystemRandom",
            return_value=SimpleNamespace(random=lambda: 0.2),
        ):
            data = self.win(await self.start())
        self.assertFalse(data["rewards"]["10"]["loot"])
        with patch(
            "arena_raid.random.SystemRandom",
            return_value=SimpleNamespace(random=lambda: 0.1999),
        ):
            self.win(await self.start())
        item = self.db.connection.execute(
            "SELECT id FROM arena_inventory WHERE owner_id=10 AND content_id='tigerslayer_flurry'"
        ).fetchone()["id"]
        with self.assertRaisesRegex(ValueError, "10"):
            await self.db.arena_use_item(1, 10, item, 10)
        await self.db.arena_transfer_item(1, 10, item, 20)
        item = self.db.connection.execute(
            "SELECT id FROM arena_inventory WHERE owner_id=20 AND content_id='tigerslayer_flurry'"
        ).fetchone()["id"]
        await self.db.arena_menu(1, 20)
        self.db._grant_profile_xp_locked("personal_profiles", 1, 20, 10**6)
        self.db.connection.commit()
        await self.db.arena_edit_profile(1, 20, 20, True, "progression", "stay")
        for content in ("smack", "humiliate", "uwu", "posing"):
            self.db._arena_add_item_locked(1, 20, "skill", content, "common")
            self.db.connection.commit()
            scroll = self.db.connection.execute(
                "SELECT id FROM arena_inventory WHERE owner_id=20 AND content_id=?",
                (content,),
            ).fetchone()["id"]
            await self.db.arena_use_item(1, 20, scroll, 20)
        await self.db.arena_edit_profile(
            1, 20, 20, True, "loadout", ["bum_punch", "smack", "humiliate", "uwu"]
        )
        with self.assertRaisesRegex(ValueError, "Максимум 6"):
            await self.db.arena_use_item(1, 20, item, 20)
        await self.db.arena_use_item(1, 20, item, 20, replace_skill="smack")
        source = self.db._arena_source_locked(1, 20, 20, False, True)
        battle = create_battle_state(
            source, dict(slave_id=30, owner_id=30, class_id="ragamuffin", level=20)
        )
        self.assertEqual(
            battle["sides"]["a"]["loadout"],
            ["bum_punch", "tigerslayer_flurry", "humiliate", "uwu"],
        )
        with self.assertRaisesRegex(ValueError, "третьего"):
            validate_skill(battle, "a", "tigerslayer_flurry")
        self.assertIsNone(
            self.db.connection.execute(
                "SELECT id FROM arena_inventory WHERE id=?", (item,)
            ).fetchone()
        )

    async def test_named_command_publishes_named_boss(self):
        message = SimpleNamespace(
            text="/рейд лейхенг",
            caption=None,
            chat=SimpleNamespace(id=1, type="supergroup"),
            from_user=SimpleNamespace(id=10, is_bot=False),
            answer=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        )
        publisher = RaidPublisher(self.db, self.bot, "GnidoBot")
        router = create_raid_router(self.db, self.bot, True, publisher)
        await router.message.handlers[0].callback(message)
        row = self.db.connection.execute(
            "SELECT * FROM arena_raids WHERE creator_id=10"
        ).fetchone()
        self.assertEqual(row["boss_id"], "lei_heng")
        self.assertEqual(row["message_id"], 99)
        self.assertIn("Лей Хенг", message.answer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
