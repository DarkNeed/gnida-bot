import asyncio
import json
import logging
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer
from arena_engine import BUILTIN_SKILLS, BUILTIN_PASSIVES
from arena_forge import FORGE_RULES
from arena_web import create_arena_app
from database import Database
from test_arena import signed, TOKEN
import test_arena_market_client as client_tests


class ForgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "forge.sqlite3")
        await self.db.connect()
        for chat in (1, 2):
            await self.db.upsert_chat(chat, "Чат")
            for actor in (10, 20):
                await self.db.upsert_user(chat, actor, str(actor), "Игрок")
                self.db._add_francs_locked(chat, actor, 10000)
        self.db.connection.commit()
        self.bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member", user=SimpleNamespace(is_bot=False))))

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def add(self, content="dust_in_eyes", quantity=1, kind="skill", actor=10, chat=1):
        item = (BUILTIN_SKILLS if kind == "skill" else BUILTIN_PASSIVES)[content]
        self.db._arena_add_item_locked(chat, actor, kind, content, item.rarity, quantity)
        self.db.connection.commit()
        return self.db.connection.execute("SELECT id FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind=? AND content_id=?", (chat, actor, kind, content)).fetchone()[0]

    def qty(self, content="dust_in_eyes", kind="skill", actor=10, chat=1):
        row = self.db.connection.execute("SELECT quantity FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind=? AND content_id=?", (chat, actor, kind, content)).fetchone()
        return row[0] if row else 0

    def resources(self, pages=None, seals=None, actor=10, chat=1):
        wallet = self.db._forge_wallet_locked(chat, actor)
        wallet["pages"].update(pages or {})
        wallet["seals"].update(seals or {})
        self.db._forge_save_wallet_locked(chat, actor, wallet)
        self.db.connection.commit()

    async def request(self, operation, chat=1, actor=10, **fields):
        view = await self.db.arena_forge_view(chat, actor)
        return dict(operation=operation, nonce=uuid4().hex, confirm=True, revision=view["revision"], catalog_revision=view["catalog_revision"], **fields)

    async def perform(self, operation, **fields):
        return await self.db.arena_forge_action(1, 10, await self.request(operation, **fields))

    async def test_receipt_unlocks_recipe_not_class_learning_and_survives_restart(self):
        self.db._arena_profile_locked(1, 10, True)
        self.db._arena_known_skills_locked(1, 10, True)
        self.db.connection.commit()
        self.assertEqual((await self.db.arena_forge_view(1, 10))["recipes"], [])
        item = self.add(quantity=3)
        await self.perform("dismantle", items=[dict(id=item, quantity=3)])
        await self.db.close()
        await self.db.connect()
        view = await self.db.arena_forge_view(1, 10)
        self.assertEqual(view["pages"], {"common": 6})
        self.assertEqual([r["content_id"] for r in view["recipes"]], ["dust_in_eyes"])
        await self.perform("craft", kind="skill", content="dust_in_eyes")
        self.assertEqual(self.qty(), 1)
        self.assertEqual(await self.db.franc_balance(1, 10), 9960)
        self.assertEqual((await self.db.arena_forge_view(1, 10))["pages"]["common"], 0)

    async def test_passive_pages_craft_and_chat_owner_isolation(self):
        item = self.add("stone_skin", 3, "passive")
        await self.perform("dismantle", items=[dict(id=item, quantity=3)])
        await self.perform("craft", kind="passive", content="stone_skin")
        self.assertEqual(self.qty("stone_skin", "passive"), 1)
        self.assertEqual(await self.db.franc_balance(1, 10), 9930)
        for chat, actor in ((2, 10), (1, 20)):
            view = await self.db.arena_forge_view(chat, actor)
            self.assertFalse(view["pages"])
            self.assertFalse(view["recipes"])

    async def test_transfer_unlocks_recipe_for_recipient_without_transferring_pages(self):
        item = self.add(quantity=2)
        self.resources(pages={"common": 4})
        await self.db.arena_transfer_item(1, 10, item, 20)
        recipient = await self.db.arena_forge_view(1, 20)
        self.assertEqual(recipient["recipes"][0]["content_id"], "dust_in_eyes")
        self.assertFalse(recipient["pages"])
        self.assertEqual((await self.db.arena_forge_view(1, 10))["pages"], {"common": 4})

    async def test_same_request_and_concurrent_clicks_cannot_double_spend(self):
        item = self.add(quantity=6)
        request = await self.request("dismantle", items=[dict(id=item, quantity=3)])
        results = await asyncio.gather(*[self.db.arena_forge_action(1, 10, request) for _ in range(2)])
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.qty(), 3)
        self.assertEqual((await self.db.arena_forge_view(1, 10))["pages"], {"common": 6})
        with self.assertRaises(ValueError):
            await self.db.arena_forge_action(1, 10, dict(request, nonce=uuid4().hex))
        with self.assertRaises(ValueError):
            await self.db.arena_forge_action(1, 10, dict(request, items=[dict(id=item, quantity=1)]))
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.arena_forge_action(1, 10, request), results[0])
        self.assertEqual(self.qty(), 3)

    async def test_different_concurrent_requests_same_revision_one_succeeds(self):
        item = self.add(quantity=6)
        request = await self.request("dismantle", items=[dict(id=item, quantity=3)])
        results = await asyncio.gather(self.db.arena_forge_action(1, 10, request), self.db.arena_forge_action(1, 10, dict(request, nonce=uuid4().hex)), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(self.qty(), 3)

    async def test_rewrite_exactly_three_same_kind_rarity_and_opens_output_recipe(self):
        item = self.add("humiliate", quantity=3)
        with patch("arena_forge.random.SystemRandom") as rng:
            rng.return_value.choice.side_effect = lambda pool: next(p for p in pool if p["content_id"] != "humiliate")
            notice = await self.perform("rewrite", items=[dict(id=item, quantity=3)])
            output = rng.return_value.choice.call_args.args[0]
            self.assertTrue(all(p["kind"] == "skill" and p["rarity"] == "uncommon" and not p["boss_id"] for p in output))
        self.assertIn("Переписано", notice)
        self.assertEqual(self.qty("humiliate"), 0)
        self.assertEqual(await self.db.franc_balance(1, 10), 9965)
        self.assertEqual(self.db.connection.execute("SELECT SUM(quantity) FROM arena_inventory WHERE chat_id=1 AND owner_id=10").fetchone()[0], 1)
        self.assertEqual(len((await self.db.arena_forge_view(1, 10))["recipes"]), 2)

    async def test_rewrite_rejects_boss_hidden_mixed_type_rarity_and_duplicate_ids(self):
        active = self.add(quantity=3)
        passive = self.add("steady_hand", 3, "passive")
        higher = self.add("stone_skin", 3, "passive")
        boss = self.add("tigerslayer_flurry", 3)
        for ingredients in (
            [dict(id=boss, quantity=3)],
            [dict(id=active, quantity=2), dict(id=passive, quantity=1)],
            [dict(id=passive, quantity=2), dict(id=higher, quantity=1)],
            [dict(id=active, quantity=1), dict(id=active, quantity=2)],
            [dict(id=active, quantity=4)], [dict(id=active, quantity=2)],
        ):
            with self.subTest(ingredients=ingredients), self.assertRaises(ValueError):
                await self.perform("rewrite", items=ingredients)
        self.assertEqual(self.qty(), 3)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)

    async def test_catalog_excludes_class_branch_free_and_unknown_recipes(self):
        view = await self.db.arena_forge_view(1, 10)
        ids = {c["content_id"] for p in view["pools"] for c in p["choices"]}
        from arena_archprogress import skill_branch
        self.assertNotIn("bum_punch", ids)
        for key, skill in BUILTIN_SKILLS.items():
            if skill_branch(skill) or "raid_loot" in skill.tags:
                self.assertNotIn(key, ids)
        self.resources(pages={"common": 100, "epic": 100})
        for kind, content in (("class", "jock"), ("skill", "tigerslayer_flurry"), ("skill", "dust_in_eyes"), ("skill", "bum_punch")):
            with self.subTest(content=content), self.assertRaises(ValueError):
                await self.perform("craft", kind=kind, content=content)

    async def test_hidden_and_branch_scrolls_never_become_craftable_or_random(self):
        result = await self.db.create_custom_fighter_content('skill', 'private_forge_test',
            dict(name='Секретный навык', power=9, damage_type='magic', merchant_available=False), 1980056841)
        self.assertEqual(result, 'created')
        self.db._arena_add_item_locked(1, 10, 'skill', 'private_forge_test', 'common', 3)
        from arena_archprogress import skill_branch
        branch = next(k for k,s in BUILTIN_SKILLS.items() if skill_branch(s))
        self.add(branch, 3)
        self.db.connection.commit()
        self.resources(pages={k: 100 for k in FORGE_RULES})
        view = await self.db.arena_forge_view(1, 10)
        recipes = {r['content_id'] for r in view['recipes']}
        choices = {c['content_id'] for p in view['pools'] for c in p['choices']}
        for content in ('private_forge_test', branch):
            self.assertNotIn(content, recipes)
            self.assertNotIn(content, choices)
            with self.assertRaises(ValueError):
                await self.perform('craft', kind='skill', content=content)

    async def test_single_result_pool_does_not_charge_for_pointless_exchange(self):
        item = self.add(quantity=3)
        with self.assertRaisesRegex(ValueError, 'один результат'):
            await self.perform('rewrite', items=[dict(id=item, quantity=3)])
        self.assertEqual(self.qty(), 3)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)

    async def test_boss_recipe_requires_correct_seals_and_still_level_gated(self):
        self.add("tigerslayer_flurry")
        self.resources(pages={"epic": 6}, seals={"doofenshmirtz": 10})
        with self.assertRaisesRegex(ValueError, "печатей"):
            await self.perform("craft", kind="skill", content="tigerslayer_flurry")
        self.resources(seals={"lei_heng": 3})
        await self.perform("craft", kind="skill", content="tigerslayer_flurry")
        self.assertEqual(self.qty("tigerslayer_flurry"), 2)
        self.assertEqual(await self.db.franc_balance(1, 10), 9750)
        view = await self.db.arena_forge_view(1, 10)
        self.assertEqual(view["seals"], {"lei_heng": 0, "doofenshmirtz": 10})
        item = self.db.connection.execute("SELECT id FROM arena_inventory WHERE content_id='tigerslayer_flurry'").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "уровень"):
            await self.db.arena_use_item(1, 10, item, 10)
        self.assertEqual(self.qty("tigerslayer_flurry"), 2)

    async def test_insufficient_francs_pages_and_changed_quote_leave_inventory_unchanged(self):
        self.add()
        self.resources(pages={"common": 5})
        with self.assertRaisesRegex(ValueError, "страниц"):
            await self.perform("craft", kind="skill", content="dust_in_eyes")
        self.resources(pages={"common": 6})
        self.db.connection.execute("UPDATE franc_balances SET balance=0 WHERE chat_id=1 AND user_id=10")
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, "франков"):
            await self.perform("craft", kind="skill", content="dust_in_eyes")
        request = await self.request("craft", kind="skill", content="dust_in_eyes")
        with patch.dict(FORGE_RULES['common'], craft_price=50):
            with self.assertRaisesRegex(ValueError, "изменились"):
                await self.db.arena_forge_action(1, 10, request)
        self.assertEqual(self.qty(), 1)
        self.assertEqual((await self.db.arena_forge_view(1, 10))["pages"], {"common": 6})

    async def test_rollback_output_error_preserves_inputs_francs_and_wallet(self):
        item = self.add("humiliate", quantity=3)
        before = await self.db.arena_forge_view(1, 10)
        with patch.object(self.db, "_arena_add_item_locked", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                await self.perform("rewrite", items=[dict(id=item, quantity=3)])
        self.assertEqual(self.qty("humiliate"), 3)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)
        after = await self.db.arena_forge_view(1, 10)
        self.assertEqual((before["revision"], before["pages"]), (after["revision"], after["pages"]))
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_forge_actions").fetchone()[0], 0)

    async def test_migration_backfills_inventory_only_and_keeps_wallet(self):
        self.add()
        self.db.connection.execute("DELETE FROM arena_forge_recipes")
        self.resources(pages={"rare": 9})
        self.db.connection.commit()
        await self.db.close()
        await self.db.connect()
        view = await self.db.arena_forge_view(1, 10)
        self.assertEqual(view["pages"], {"rare": 9})
        self.assertEqual([r["content_id"] for r in view["recipes"]], ["dust_in_eyes"])

    async def test_invalid_inputs_and_foreign_inventory_cannot_spend(self):
        item = self.add(actor=20)
        request = await self.request("dismantle", items=[dict(id=item, quantity=1)])
        for changes in ({}, {'operation': []}, {'confirm': False}, {'revision': True}, {'nonce': 'bad'}, {'items': [dict(id=True, quantity=1)]}, {'items': [dict(id=item, quantity=-1)]}, {'items': [dict(id=item, quantity=True)]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await self.db.arena_forge_action(1, 10, dict(request, **changes))
        self.assertEqual(self.qty(actor=20), 1)

    async def test_http_signed_identity_fresh_membership_and_replay(self):
        item = self.add(quantity=3)
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        path = '/api/menu/1'
        headers = {'X-Telegram-Init-Data': signed(10, int(time.time()))}
        request = dict(action='forge', **await self.request("dismantle", items=[dict(id=item, quantity=3)]))
        try:
            self.assertEqual((await client.post(path, json=request)).status, 400)
            self.bot.get_chat_member.return_value.status = 'left'
            self.assertEqual((await client.post(path, headers=headers, json=request)).status, 400)
            self.bot.get_chat_member.return_value.status = 'member'
            response = await client.post(path, headers=headers, json=dict(request, actor=20, price=-100))
            self.assertEqual(response.status, 200, await response.text())
            data = await response.json()
            self.assertEqual(data['menu']['actor_id'], 10)
            self.assertEqual(data['menu']['forge']['pages'], {'common': 6})
            response = await client.post(path, headers=headers, json=request)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['menu']['forge']['pages'], {'common': 6})
        finally:
            await client.close()


class ForgeClientTests(unittest.TestCase):
    def data(self):
        data = client_tests.ArenaMarketClientTests().menu_data()
        data['forge'] = dict(revision=0, catalog_revision='f'*16, pages={'common': 6}, seals={}, bosses=[],
            rarities=[dict(id=k, name=k, **v) for k,v in FORGE_RULES.items()],
            inventory=[dict(id=3, kind='skill', content_id='dust_in_eyes', name='<Пыль>', quantity=3, rarity='common', salvage_pages=2, can_rewrite=True, details={})],
            recipes=[dict(kind='skill',content_id='dust_in_eyes',name='<Пыль>',rarity='common',pages=6,price=40,seals=0,boss_name='',can_craft=True,details={})],
            pools=[dict(kind='skill', rarity='common',price=20,choices=[dict(kind='skill',content_id='dust_in_eyes',name='<Пыль>',rarity='common',details={})])])
        return data

    def render(self, code):
        return client_tests.ArenaMarketClientTests().run_client(code, self.data())

    def test_forge_dismantle_recipes_pool_and_confirmation_are_readable(self):
        body = self.render("page='forge';menuScreen(input);")
        self.assertIn('Кузница трактатов', body)
        self.assertIn('forge-dismantle-3', body)
        self.assertIn('&lt;Пыль&gt;', body)
        body = self.render("page='forge';forgeMode='recipes';menuScreen(input);")
        self.assertIn('data-do="forgecraft:skill:dust_in_eyes"', body)
        self.assertIn('6 стр. · 40 ₣', body)
        body = self.render("page='forge';forgeMode='rewrite';menuScreen(input);")
        self.assertIn('Все возможные результаты', body)
        self.assertIn('forge-rewrite-3', body)
        self.assertIn('Шансы равные', body)
        body = self.render("page='forgeConfirm';forgePending={summary:'<p>Списать 40 ₣</p>'};menuScreen(input);")
        self.assertIn('data-do="forgeconfirm"', body)
        self.assertIn('Списать 40 ₣', body)
        self.assertIn('data-do="forgecancel"', body)
        detail = self.render("out=forgeInfo({kind:'skill',details:{unlock_level:5,cost:15,accuracy:88,power:13,cooldown:0,effects:[{kind:'resource_leech',value:15,target:'enemy'}]}});")
        self.assertIn('нужен уровень 5', detail)
        self.assertIn('-15 противнику', detail)


if __name__ == '__main__':
    unittest.main()
