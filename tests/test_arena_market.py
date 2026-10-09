import asyncio
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
from arena_engine import (
    MAX_FIGHTER_LEVEL,
    BUILTIN_PASSIVES,
    create_battle_state,
    effective_stat,
    fighter_xp_limit,
    level_from_total_xp,
    level_progress,
    stats_for,
)
from arena_web import menu_view, battle_view, create_arena_app
from database import Database
from handlers.arena import ITEM_TRANSFER_RE, create_arena_router, ArenaPublisher
from test_arena import signed, TOKEN


class FighterCapTests(unittest.TestCase):
    def test_cap_and_progress(self):
        limit = fighter_xp_limit()
        self.assertEqual(level_from_total_xp(limit - 1), 19)
        self.assertEqual(level_from_total_xp(limit), 20)
        self.assertEqual(level_from_total_xp(10**30), 20)
        self.assertEqual(level_progress(10**30), (20, 0, 0))
        self.assertGreater(level_from_total_xp(limit + 10000, None), 20)

    def test_stats_cap_and_low_level_class_reset(self):
        for class_id in ("ragamuffin", "cutie", "jock", "nerd"):
            self.assertEqual(stats_for(class_id, 100), stats_for(class_id, 20))
            self.assertLess(
                stats_for(class_id, 1)["max_hp"], stats_for(class_id, 5)["max_hp"]
            )

    def test_engine_has_only_two_passives_and_applies_effects(self):
        from dataclasses import asdict

        source = dict(
            slave_id=10,
            owner_id=10,
            class_id="ragamuffin",
            level=1,
            controlled=False,
            passive_details=[
                asdict(BUILTIN_PASSIVES[k])
                for k in ("stone_skin", "light_step", "battle_rhythm")
            ],
        )
        state = create_battle_state(
            source, dict(source, slave_id=20, passive_details=[])
        )
        side = state["sides"]["a"]
        self.assertEqual(len(side["passive_details"]), 2)
        self.assertEqual(effective_stat(side, "physical_defense"), 3 * 1.15)
        self.assertEqual(effective_stat(side, "evasion"), 9)
        self.assertFalse(any(e["kind"] == "damage_pct" for e in side["effects"]))


class ArenaMarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "bot.sqlite3")
        await self.db.connect()
        for chat in (1, 2):
            await self.db.upsert_chat(chat, "Чат")
            for user in (10, 20, 30):
                await self.db.upsert_user(chat, user, str(user), f"User {user}")
        await self.db.force_enslave(1, 30, 10)
        await self.db.arena_equip_slave(1, 10, 30, True)
        self.db._add_francs_locked(1, 10, 10000)
        self.db.connection.commit()
        self.bot = SimpleNamespace(
            get_chat_member=AsyncMock(
                return_value=SimpleNamespace(
                    status="member",
                    user=SimpleNamespace(
                        is_bot=False, full_name="User 20", username="20"
                    ),
                )
            )
        )

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def add(self, kind, content, owner=10, chat=1, quantity=1, rarity="common"):
        self.db._arena_add_item_locked(chat, owner, kind, content, rarity, quantity)
        self.db.connection.commit()
        return self.db.connection.execute(
            "SELECT id FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind=? AND content_id=?",
            (chat, owner, kind, content),
        ).fetchone()["id"]

    def qty(self, item):
        row = self.db.connection.execute(
            "SELECT quantity FROM arena_inventory WHERE id=?", (item,)
        ).fetchone()
        return row["quantity"] if row else 0

    async def open_shop(self):
        with patch("arena_market.CLASS_SCROLL_CHANCE", 1):
            await self.db.arena_market_view(1, 10)
        visit = self.db.connection.execute(
            "SELECT * FROM arena_merchant_visits WHERE chat_id=1 ORDER BY starts LIMIT 1"
        ).fetchone()
        now = int(time.time())
        self.db.connection.execute(
            "UPDATE arena_merchant_visits SET starts=?,ends=? WHERE id=?",
            (now - 1, now + 7200, visit["id"]),
        )
        self.db.connection.commit()
        return (await self.db.arena_market_view(1, 10))["merchant"]

    async def test_cap_fighters_not_owner_and_candy_preserved_at_cap(self):
        await self.db.grant_slave_xp(1, 30, 10**6)
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, 10**6)
        await self.db.grant_owner_xp(1, 10, 10**6)
        personal = (await menu_view(self.db, 1, 10))["personal"]
        self.assertEqual(personal["level"], 20)
        self.assertEqual(personal["xp"], fighter_xp_limit())
        self.assertEqual((await self.db.get_slave_profile(1, 30))["level"], 20)
        self.assertGreater((await self.db.get_owner_profile(1, 10))["level"], 20)
        item = self.add("candy", "experience")
        with self.assertRaises(ValueError):
            await self.db.arena_use_item(1, 10, item, 10)
        self.assertEqual(self.qty(item), 1)

    async def test_surrender_before_and_after_moves_gives_no_xp(self):
        for personal, user in ((True, 10), (False, 30)):
            for moved in (False, True):
                row = await self.db.arena_wasteland(1, 10, user, personal=personal)
                if moved:
                    state = json.loads(row["state_json"])
                    state["sides"]["a"]["hp"] = state["sides"]["a"]["stats"][
                        "max_hp"
                    ] = 1000
                    state["sides"]["b"]["hp"] = 1000
                    self.db.connection.execute(
                        "UPDATE arena_battles SET state_json=? WHERE token=?",
                        (json.dumps(state), row["token"]),
                    )
                    self.db.connection.commit()
                    row = await self.db.arena_action(
                        row["token"], 10, row["revision"], "bum_punch"
                    )
                row = await self.db.arena_action(
                    row["token"], 10, row["revision"], "surrender"
                )
                self.assertEqual(json.loads(row["state_json"])["rewards"], {"a": 0})
        self.assertEqual((await self.db.get_slave_profile(1, 30))["xp"], 0)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 0)

    async def test_timeout_no_xp_and_natural_loss_still_rewards(self):
        row = await self.db.arena_wasteland(1, 10)
        with patch("arena_store.utc_timestamp", return_value=row["deadline"] + 1):
            await self.db.arena_expire()
        self.assertEqual(
            json.loads((await self.db.arena_get(row["token"]))["state_json"])[
                "rewards"
            ]["a"],
            0,
        )
        row = await self.db.arena_wasteland(1, 10)
        state = json.loads(row["state_json"])
        state["sides"]["a"]["hp"] = 1
        state["sides"]["b"]["hp"] = 1000
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        import random

        with patch(
            "arena_engine.random.SystemRandom", return_value=random.Random(1)
        ), patch("arena_store.random.choice", return_value="bum_punch"):
            row = await self.db.arena_action(
                row["token"], 10, row["revision"], "bum_punch"
            )
        self.assertEqual(row["status"], "finished")
        self.assertEqual(json.loads(row["state_json"])["rewards"], {"a": 3})

    async def test_shop_contains_consumables_passives_actives_and_rare_class_scroll(
        self,
    ):
        shop = await self.open_shop()
        self.assertEqual(
            {o["kind"] for o in shop["offers"]},
            {"skill", "passive", "potion", "candy", "class"},
        )
        self.assertEqual(len(shop["offers"]), 6)
        again = (await self.db.arena_market_view(1, 20))["merchant"]
        self.assertEqual(shop["offers"], again["offers"])
        await self.db.close()
        await self.db.connect()
        self.assertEqual(
            (await self.db.arena_market_view(1, 10))["merchant"]["offers"],
            shop["offers"],
        )

    async def test_atomic_purchase_limit_and_no_foreign_chat_purchase(self):
        offer = next(
            o for o in (await self.open_shop())["offers"] if o["kind"] == "passive"
        )
        results = await asyncio.gather(
            *(self.db.arena_buy_item(1, 10, offer["id"]) for _ in range(2)),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000 - offer["price"])
        items = (await self.db.arena_market_view(1, 10))["inventory"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quantity"], 1)
        with self.assertRaises(ValueError):
            await self.db.arena_buy_item(2, 10, offer["id"])
        with self.assertRaises(ValueError):
            await self.db.arena_buy_item(1, 20, offer["id"])
        self.assertEqual((await self.db.arena_market_view(1, 20))["inventory"], [])

    async def test_expired_offer_does_not_spend(self):
        shop = await self.open_shop()
        with patch("arena_market.market_now", return_value=shop["ends"]):
            with self.assertRaises(ValueError):
                await self.db.arena_buy_item(1, 10, shop["offers"][0]["id"])
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)

    async def test_transfer_merges_stacks_preserves_total_and_ownership(self):
        item = self.add("candy", "experience", quantity=2)
        other = self.add("candy", "experience", owner=20, quantity=3)
        await self.db.arena_transfer_item(1, 10, item, 20)
        self.assertEqual(self.qty(item), 1)
        self.assertEqual(self.qty(other), 4)
        for args in ((1, 20, item, 30), (2, 10, item, 20), (1, 10, item, 10)):
            with self.assertRaises(ValueError):
                await self.db.arena_transfer_item(*args)
        self.assertEqual(self.qty(item), 1)

    async def test_same_item_cannot_be_used_and_transferred_twice(self):
        item = self.add("passive", "light_step")
        results = await asyncio.gather(
            self.db.arena_use_item(1, 10, item, 10),
            self.db.arena_transfer_item(1, 10, item, 20),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(self.qty(item), 0)

    async def test_learn_cross_class_active_and_two_passive_slots(self):
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, 100)
        self.db.connection.commit()
        item = self.add("skill", "smack")
        await self.db.arena_use_item(1, 10, item, 10)
        view = await menu_view(self.db, 1, 10)
        self.assertIn("smack", [s["skill_id"] for s in view["personal"]["skills"]])
        for content in ("light_step", "stone_skin", "battle_rhythm"):
            await self.db.arena_use_item(1, 10, self.add("passive", content), 10)
        view = await menu_view(self.db, 1, 10)
        self.assertEqual(len(view["personal"]["passives"]), 3)
        self.assertEqual(len(view["personal"]["passive_loadout"]), 2)
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(
                1,
                10,
                10,
                True,
                "passives",
                ["light_step", "stone_skin", "battle_rhythm"],
            )
        with self.assertRaises(ValueError):
            await self.db.arena_edit_profile(1, 10, 10, True, "passives", ["unknown"])
        await self.db.arena_edit_profile(
            1, 10, 10, True, "passives", ["stone_skin", "battle_rhythm"]
        )
        row = await self.db.arena_wasteland(1, 10)
        state = json.loads(row["state_json"])
        self.assertEqual(
            [s["skill_id"] for s in state["sides"]["a"]["passive_details"]],
            ["stone_skin", "battle_rhythm"],
        )

    async def test_duplicate_and_level_requirement_do_not_consume(self):
        item = self.add("skill", "meow")
        with self.assertRaises(ValueError):
            await self.db.arena_use_item(1, 10, item, 10)
        self.assertEqual(self.qty(item), 1)
        passive = self.add("passive", "light_step", quantity=2)
        await self.db.arena_use_item(1, 10, passive, 10)
        with self.assertRaises(ValueError):
            await self.db.arena_use_item(1, 10, passive, 10)
        self.assertEqual(self.qty(passive), 1)

    async def test_class_change_resets_only_target_profile_and_preserves_inventory_and_sprite(
        self,
    ):
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, 100)
        await self.db.grant_slave_xp(1, 10, 100)
        await self.db.arena_use_item(1, 10, self.add("skill", "smack"), 10)
        await self.db.arena_use_item(1, 10, self.add("passive", "light_step"), 10)
        await self.db.arena_set_sprite(1, 10, b"test-image", True)
        item = self.add("class", "nerd", rarity="uncommon")
        candy = self.add("candy", "experience", quantity=3)
        with self.assertRaises(ValueError):
            await self.db.arena_use_item(1, 10, item, 10)
        self.assertEqual(self.qty(item), 1)
        await self.db.arena_use_item(1, 10, item, 10, confirm=True)
        view = await menu_view(self.db, 1, 10)
        p = view["personal"]
        self.assertEqual((p["class_id"], p["level"], p["xp"]), ("nerd", 1, 0))
        self.assertEqual([s["skill_id"] for s in p["skills"]], ["bum_punch"])
        self.assertEqual(p["passive_loadout"], [])
        self.assertEqual(p["passives"], [])
        self.assertTrue(p["sprite_url"])
        self.assertGreater((await self.db.get_slave_profile(1, 10))["level"], 1)
        self.assertEqual(self.qty(candy), 3)
        self.assertEqual(self.qty(item), 0)

    async def test_reset_does_not_reenable_old_author_grants_after_leveling(self):
        admin = 1980056841
        await self.db.create_custom_fighter_content(
            "skill",
            "exclusive",
            {"name": "Свет", "class_id": "ragamuffin", "power": 10},
            admin,
        )
        await self.db.arena_admin_grant(1, 10, "skill", "exclusive", admin, True)
        item = self.add("class", "nerd")
        await self.db.arena_use_item(1, 10, item, 10, confirm=True)
        self.db._grant_profile_xp_locked("personal_profiles", 1, 10, 1000)
        self.db.connection.commit()
        self.assertNotIn(
            "exclusive",
            [
                s["skill_id"]
                for s in (await menu_view(self.db, 1, 10))["personal"]["skills"]
            ],
        )
        await self.db.arena_admin_grant(1, 10, "skill", "exclusive", admin, True)
        self.assertIn(
            "exclusive",
            [
                s["skill_id"]
                for s in (await menu_view(self.db, 1, 10))["personal"]["skills"]
            ],
        )

    async def test_cannot_use_on_other_personal_or_non_owned_slave_or_in_battle(self):
        item = self.add("candy", "experience", quantity=2)
        for user, personal in ((20, True), (20, False)):
            with self.assertRaises(ValueError):
                await self.db.arena_use_item(1, 10, item, user, personal)
        await self.db.arena_wasteland(1, 10)
        with self.assertRaises(ValueError):
            await self.db.arena_use_item(1, 10, item, 10)
        self.assertEqual(self.qty(item), 2)

    async def test_candy_can_train_slave_and_personal_separately_and_craft_is_disabled(
        self,
    ):
        item = self.add("candy", "experience", quantity=2)
        await self.db.arena_use_item(1, 10, item, 30, False)
        await self.db.arena_use_item(1, 10, item, 10, True)
        self.assertEqual((await self.db.get_slave_profile(1, 30))["xp"], 30)
        self.assertEqual((await self.db.arena_menu(1, 10))["personal"]["xp"], 30)
        self.assertIn("Крафт убран", await self.db.craft_owner_item(1, 10, "potion"))

    async def test_personal_potion_atomic_and_only_once(self):
        item = self.add("potion", "healing", quantity=2)
        row = await self.db.arena_wasteland(1, 10)
        with self.assertRaises(ValueError):
            await self.db.arena_action(row["token"], 10, row["revision"], "potion")
        self.assertEqual(self.qty(item), 2)
        state = json.loads(row["state_json"])
        state["sides"]["a"]["hp"] = 1
        self.db.connection.execute(
            "UPDATE arena_battles SET state_json=? WHERE token=?",
            (json.dumps(state), row["token"]),
        )
        self.db.connection.commit()
        row = await self.db.arena_action(row["token"], 10, row["revision"], "potion")
        self.assertEqual(self.qty(item), 1)
        self.assertEqual(json.loads(row["state_json"])["sides"]["a"]["hp"], 7)
        with self.assertRaises(ValueError):
            await self.db.arena_action(row["token"], 10, row["revision"], "potion")
        self.assertEqual(self.qty(item), 1)

    async def test_legacy_items_migrate_once_and_backup_contains_inventory(self):
        self.db._ensure_owner_profile_locked(1, 10)
        self.db.connection.execute(
            "UPDATE owner_profiles SET healing_potions=4,candies=2 WHERE chat_id=1 AND user_id=10"
        )
        self.db.connection.execute("DELETE FROM arena_market_migrations")
        self.db.connection.commit()
        await self.db.close()
        await self.db.connect()
        items = (await self.db.arena_market_view(1, 10))["inventory"]
        self.assertEqual(
            {i["kind"]: i["quantity"] for i in items}, {"potion": 4, "candy": 2}
        )
        await self.db.close()
        await self.db.connect()
        self.assertEqual((await self.db.arena_market_view(1, 10))["inventory"], items)
        await self.db.backup_to(Path(self.temp.name) / "backup.db")

    async def test_hidden_classes_and_exclusive_skills_not_sold_without_opt_in(self):
        from dataclasses import asdict
        from arena_engine import FIGHTER_CLASSES

        payload = asdict(FIGHTER_CLASSES["cutie"])
        payload.update(name="Скрытый", rarity="epic")
        await self.db.create_custom_fighter_content(
            "class", "secret", payload, 1980056841
        )
        await self.db.create_custom_fighter_content(
            "skill", "exclusive", {"name": "Свет", "class_id": "ragamuffin"}, 1980056841
        )
        catalog = self.db._arena_shop_catalog_locked()
        self.assertNotIn(("class", "secret"), catalog)
        self.assertNotIn(("skill", "exclusive"), catalog)

    async def test_battle_card_includes_effective_stats_passives_and_custom_avatar(
        self,
    ):
        await self.db.arena_use_item(1, 10, self.add("passive", "stone_skin"), 10)
        await self.db.arena_set_sprite(1, 10, b"image", True)
        row = await self.db.arena_wasteland(1, 10)
        view = await battle_view(self.db, row, 20)
        a = view["state"]["sides"]["a"]
        self.assertTrue(a["sprite_url"])
        self.assertEqual(
            a["effective_stats"]["physical_defense"],
            a["stats"]["physical_defense"] * 1.15,
        )
        self.assertEqual(a["passive_details"][0]["skill_id"], "stone_skin")
        self.assertIn("rarity", a["skill_details"][0])

    async def test_merchant_notification_claims_are_persistent_and_once_only(self):
        await self.db.arena_menu(-100, 10)
        await self.db.arena_market_view(-100, 10)
        now = int(time.time())
        self.db.connection.execute("UPDATE arena_merchant_visits SET notified=1")
        self.db.connection.execute(
            "UPDATE arena_merchant_visits SET starts=?,ends=?,notified=0 WHERE chat_id=-100 AND visit=1",
            (now - 1, now + 100),
        )
        self.db.connection.commit()
        due = await self.db.arena_due_merchants()
        self.assertEqual(len(due), 2)  # Today's and tomorrow's test rows forced active.
        self.assertEqual(await self.db.arena_due_merchants(), [])

    async def test_transfer_command_reply_tag_and_private_selected_chat(self):
        router = create_arena_router(
            self.db,
            self.bot,
            "GnidoBot",
            True,
            ArenaPublisher(self.db, self.bot, "GnidoBot"),
        )
        handler = next(
            h.callback
            for h in router.message.handlers
            if h.callback.__name__ == "transfer_arena_item"
        )
        item = self.add("candy", "experience", quantity=3)
        message = SimpleNamespace(
            text=f"/передать предмет {item} @20",
            caption=None,
            chat=SimpleNamespace(id=1, type="supergroup"),
            from_user=SimpleNamespace(id=10),
            reply_to_message=None,
            entities=[],
            caption_entities=[],
            answer=AsyncMock(),
        )
        await handler(message)
        self.assertEqual(self.qty(item), 2)
        message.text = f"/передать трактат {item}"
        message.reply_to_message = SimpleNamespace(
            sender_chat=None,
            from_user=SimpleNamespace(
                id=20, username="20", is_bot=False, full_name="User 20"
            ),
        )
        await handler(message)
        self.assertEqual(self.qty(item), 1)
        await self.db.select_menu_chat(10, 1)
        message.chat = SimpleNamespace(id=10, type="private")
        message.text = f"/передать предмет {item} @20"
        message.reply_to_message = None
        await handler(message)
        self.assertEqual(self.qty(item), 0)
        for text in (
            f"/передать предмет {item} @20",
            f"!передать трактат {item}",
            f"Передать предмет {item}",
        ):
            self.assertIsNotNone(ITEM_TRANSFER_RE.match(text))

    async def test_http_actions_authorization_and_wrong_target(self):
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        try:
            headers = {"X-Telegram-Init-Data": signed(now=int(time.time()))}
            offer = (await self.open_shop())["offers"][0]
            response = await client.post(
                "/api/menu/1",
                json={"action": "buy_item", "offer": offer["id"]},
                headers=headers,
            )
            self.assertEqual(response.status, 200, await response.text())
            data = await response.json()
            self.assertEqual(len(data["menu"]["inventory"]), 1)
            item = self.add("candy", "experience")
            response = await client.post(
                "/api/menu/1",
                json={"action": "use_item", "item": item, "user": 20, "personal": True},
                headers=headers,
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(self.qty(item), 1)
            response = await client.post(
                "/api/menu/1",
                json={
                    "action": "use_item",
                    "item": item,
                    "user": 10,
                    "personal": "false",
                },
                headers=headers,
            )
            self.assertEqual(response.status, 400)
            response = await client.post(
                "/api/menu/1",
                json={"action": "craft", "item": "potion"},
                headers=headers,
            )
            self.assertEqual(response.status, 400)
            self.bot.get_chat_member.return_value = SimpleNamespace(status="left")
            response = await client.post(
                "/api/menu/1",
                json={"action": "use_item", "item": item, "user": 10, "personal": True},
                headers=headers,
            )
            self.assertEqual(response.status, 400)
        finally:
            await client.close()
