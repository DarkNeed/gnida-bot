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
from arena_forge import FORGE_RULES, FORGE_PAGE_ODDS, FORGE_FUSION_ODDS, forge_distribution
from arena_web import create_arena_app
from database import Database
from test_arena import signed, TOKEN
import test_arena_market_client as client_tests


class ForgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'forge.sqlite3')
        await self.db.connect()
        for chat in (1, 2):
            await self.db.upsert_chat(chat, 'Чат')
            for actor in (10, 20):
                await self.db.upsert_user(chat, actor, str(actor), 'Игрок')
                self.db._add_francs_locked(chat, actor, 10000)
        self.db.connection.commit()
        self.bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member', user=SimpleNamespace(is_bot=False))))

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    def add(self, content='dust_in_eyes', quantity=1, kind='skill', actor=10, chat=1):
        item = (BUILTIN_SKILLS if kind == 'skill' else BUILTIN_PASSIVES)[content]
        self.db._arena_add_item_locked(chat, actor, kind, content, item.rarity, quantity)
        self.db.connection.commit()
        return self.db.connection.execute('SELECT id FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind=? AND content_id=?', (chat, actor, kind, content)).fetchone()[0]

    def qty(self, content='dust_in_eyes', kind='skill', actor=10, chat=1):
        row = self.db.connection.execute('SELECT quantity FROM arena_inventory WHERE chat_id=? AND owner_id=? AND kind=? AND content_id=?', (chat, actor, kind, content)).fetchone()
        return row[0] if row else 0

    def resources(self, pages=None, seals=None, actor=10, chat=1):
        wallet = self.db._forge_wallet_locked(chat, actor)
        wallet['pages'].update(pages or {})
        wallet['seals'].update(seals or {})
        self.db._forge_save_wallet_locked(chat, actor, wallet)
        self.db.connection.commit()

    async def request(self, operation, chat=1, actor=10, **fields):
        view = await self.db.arena_forge_view(chat, actor)
        return dict(operation=operation, nonce=uuid4().hex, confirm=True, revision=view['revision'], catalog_revision=view['catalog_revision'], **fields)

    async def perform(self, operation, **fields):
        return await self.db.arena_forge_action(1, 10, await self.request(operation, **fields))

    def fixed(self, roll):
        rng = patch('arena_forge.random.SystemRandom')
        mock = rng.start()
        self.addCleanup(rng.stop)
        mock.return_value.random.return_value = roll
        mock.return_value.choice.side_effect = lambda pool: pool[0]
        return mock

    async def test_no_recipe_required_pages_and_restart(self):
        item = self.add(quantity=3)
        await self.perform('dismantle', items=[dict(id=item, quantity=3)])
        await self.db.close()
        await self.db.connect()
        view = await self.db.arena_forge_view(1, 10)
        self.assertNotIn('recipes', view)
        self.assertEqual(view['pages'], {'common': 6})
        self.fixed(.01)
        await self.perform('craft', kind='skill', rarity='common')
        self.assertEqual(self.qty(), 1)
        self.assertEqual(await self.db.franc_balance(1, 10), 9960)
        self.assertEqual((await self.db.arena_forge_view(1, 10))['pages']['common'], 0)

    async def test_passive_pages_chat_owner_isolation(self):
        item = self.add('stone_skin', 3, 'passive')
        await self.perform('dismantle', items=[dict(id=item, quantity=3)])
        self.fixed(.30)
        await self.perform('craft', kind='passive', rarity='uncommon')
        self.assertEqual(await self.db.franc_balance(1, 10), 9930)
        row = self.db.connection.execute('SELECT * FROM arena_inventory WHERE chat_id=1 AND owner_id=10').fetchone()
        self.assertEqual((row['kind'], row['rarity'], row['quantity']), ('passive', 'uncommon', 1))
        for chat, actor in ((2, 10), (1, 20)):
            self.assertFalse((await self.db.arena_forge_view(chat, actor))['pages'])

    async def test_transfer_does_not_transfer_pages_or_require_recipe(self):
        item = self.add(quantity=2)
        self.resources(pages={'common': 4})
        await self.db.arena_transfer_item(1, 10, item, 20)
        self.assertFalse((await self.db.arena_forge_view(1, 20))['pages'])
        self.assertEqual((await self.db.arena_forge_view(1, 10))['pages'], {'common': 4})
        self.assertEqual(self.qty(actor=20), 1)

    async def test_replay_and_concurrent_clicks_restart_cannot_double_spend(self):
        item = self.add(quantity=6)
        request = await self.request('dismantle', items=[dict(id=item, quantity=3)])
        results = await asyncio.gather(*[self.db.arena_forge_action(1, 10, request) for _ in range(2)])
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.qty(), 3)
        self.assertEqual((await self.db.arena_forge_view(1, 10))['pages'], {'common': 6})
        for changes in (dict(nonce=uuid4().hex), dict(items=[dict(id=item, quantity=1)])):
            with self.assertRaises(ValueError):
                await self.db.arena_forge_action(1, 10, dict(request, **changes))
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.arena_forge_action(1, 10, request), results[0])
        self.assertEqual(self.qty(), 3)

    async def test_different_concurrent_requests_one_succeeds(self):
        item = self.add(quantity=6)
        request = await self.request('rewrite', items=[dict(id=item, quantity=3)])
        results = await asyncio.gather(self.db.arena_forge_action(1, 10, request), self.db.arena_forge_action(1, 10, dict(request, nonce=uuid4().hex)), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        self.assertEqual(await self.db.franc_balance(1, 10), 9980)

    async def test_fusion_all_epic_can_downgrade_but_never_roll_boss(self):
        item = self.add('last_argument', 3)
        self.fixed(.12)
        notice = await self.perform('rewrite', items=[dict(id=item, quantity=3)])
        self.assertIn('Редкий', notice)
        self.assertEqual(self.qty('last_argument'), 0)
        self.assertEqual(await self.db.franc_balance(1, 10), 9875)
        row = self.db.connection.execute('SELECT * FROM arena_inventory WHERE chat_id=1 AND owner_id=10').fetchone()
        self.assertEqual((row['rarity'], row['quantity']), ('rare', 1))

    async def test_mixed_rarity_fusion_weighted_average_price_and_epic_result(self):
        ids = [self.add(c) for c in ('dust_in_eyes', 'last_argument', 'whole_family')]
        self.fixed(.95)
        await self.perform('rewrite', items=[dict(id=i, quantity=1) for i in ids])
        self.assertEqual(await self.db.franc_balance(1, 10), 9930)
        row = self.db.connection.execute('SELECT * FROM arena_inventory WHERE chat_id=1 AND owner_id=10').fetchone()
        self.assertEqual((row['rarity'], row['quantity']), ('epic', 1))
        self.assertNotIn('raid_loot', BUILTIN_SKILLS[row['content_id']].tags)

    async def test_passive_fusion_rolls_passive_and_can_upgrade(self):
        item = self.add('steady_hand', 3, 'passive')
        self.fixed(.995)
        await self.perform('rewrite', items=[dict(id=item, quantity=3)])
        self.assertEqual(self.qty('battle_rhythm', 'passive'), 1)
        self.assertEqual(self.qty('steady_hand', 'passive'), 0)

    async def test_rewrite_rejects_boss_mixed_type_duplicate_foreign_and_quantity(self):
        active = self.add(quantity=3)
        passive = self.add('steady_hand', 3, 'passive')
        boss = self.add('tigerslayer_flurry', 3)
        foreign = self.add(actor=20)
        for ingredients in ([dict(id=boss, quantity=3)], [dict(id=active, quantity=2), dict(id=passive, quantity=1)],
                            [dict(id=active, quantity=1), dict(id=active, quantity=2)], [dict(id=active, quantity=4)],
                            [dict(id=active, quantity=2)], [dict(id=foreign, quantity=3)]):
            with self.subTest(ingredients=ingredients), self.assertRaises(ValueError):
                await self.perform('rewrite', items=ingredients)
        self.assertEqual(self.qty(), 3)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)

    async def test_public_epic_pool_excludes_boss_branch_free_hidden_class(self):
        view = await self.db.arena_forge_view(1, 10)
        ids = {c['content_id'] for p in view['pools'] for c in p['choices']}
        from arena_archprogress import skill_branch
        self.assertNotIn('bum_punch', ids)
        for key, skill in BUILTIN_SKILLS.items():
            if skill_branch(skill) or 'raid_loot' in skill.tags:
                self.assertNotIn(key, ids)
        epics = [p for p in view['pools'] if p['rarity']=='epic']
        self.assertEqual([len(p['choices']) for p in epics], [6, 4])
        await self.db.create_custom_fighter_content('skill', 'private_forge_test',
            dict(name='Секретный навык', power=9, damage_type='magic', merchant_available=False), 1980056841)
        self.db._arena_add_item_locked(1, 10, 'skill', 'private_forge_test', 'common', 3)
        self.db.connection.commit()
        branch = next(k for k,s in BUILTIN_SKILLS.items() if skill_branch(s))
        branch_id = self.add(branch, 3)
        secret_id = self.db.connection.execute("SELECT id FROM arena_inventory WHERE content_id='private_forge_test'").fetchone()[0]
        for i in (branch_id, secret_id):
            with self.assertRaises(ValueError):
                await self.perform('rewrite', items=[dict(id=i, quantity=3)])

    async def test_page_odds_and_mixed_distribution_exact(self):
        catalog = self.db._forge_catalog_locked()
        for kind in ('skill', 'passive'):
            for r in FORGE_RULES:
                self.assertEqual(forge_distribution(catalog, kind, [(r, 3)]), FORGE_FUSION_ODDS[r])
                self.assertEqual(forge_distribution(catalog, kind, [(r, 1)], pages=True), FORGE_PAGE_ODDS[r])
        mix = forge_distribution(catalog, 'skill', [('common', 2), ('epic', 1)])
        for r in FORGE_RULES:
            self.assertAlmostEqual(mix[r], (FORGE_FUSION_ODDS['common'][r]*2+FORGE_FUSION_ODDS['epic'][r])/3)
        self.assertAlmostEqual(sum(mix.values()), 100)
        limited = {k:v for k,v in catalog.items() if v['rarity'] != 'epic'}
        self.assertEqual(forge_distribution(limited, 'skill', [('epic', 1)])['epic'], 0)
        self.assertAlmostEqual(sum(forge_distribution(limited, 'skill', [('epic', 1)]).values()), 100)

    async def test_roll_boundaries_have_exact_tier_weights(self):
        catalog = self.db._forge_catalog_locked()
        rng = self.fixed(0)
        for table in (FORGE_PAGE_ODDS, FORGE_FUSION_ODDS):
            for input_rarity, odds in table.items():
                cumulative = 0
                for rarity, weight in odds.items():
                    if not weight:
                        continue
                    for roll in (cumulative + .0001, cumulative + weight - .0001):
                        rng.return_value.random.return_value = roll/100
                        result = self.db._forge_roll(catalog, 'skill', odds)
                        self.assertEqual(result['rarity'], rarity, (input_rarity, roll))
                    cumulative += weight
                self.assertEqual(cumulative, 100)

    async def test_pages_epic_can_roll_epic_without_recipe_or_seals(self):
        self.resources(pages={'epic': 6})
        self.fixed(.99)
        await self.perform('craft', kind='passive', rarity='epic')
        self.assertEqual(await self.db.franc_balance(1, 10), 9750)
        row = self.db.connection.execute('SELECT * FROM arena_inventory').fetchone()
        self.assertEqual((row['kind'], row['rarity']), ('passive', 'epic'))
        self.assertFalse((await self.db.arena_forge_view(1, 10))['seals'])

    async def test_old_recipe_request_and_class_rejected(self):
        self.resources(pages={r: 100 for r in FORGE_RULES})
        for fields in (dict(kind='skill', content='dust_in_eyes'), dict(kind='class', rarity='rare'),
                       dict(kind='skill', rarity='epic', content='tigerslayer_flurry'), dict(kind='skill', rarity='legendary')):
            with self.assertRaises(ValueError):
                await self.perform('craft', **fields)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)

    async def test_epic_scroll_study_is_level_gated_and_cross_class_replacement_works(self):
        item = self.add('last_argument')
        with self.assertRaisesRegex(ValueError, 'уровень 10'):
            await self.db.arena_use_item(1, 10, item, 10)
        self.assertEqual(self.qty('last_argument'), 1)
        self.db._grant_profile_xp_locked('personal_profiles',1,10,72)
        self.db._arena_reset_profile_locked(1, 10, True, 'nerd')
        self.db._grant_profile_xp_locked('personal_profiles', 1, 10, 10**6)
        self.db.connection.commit()
        await self.db.arena_edit_profile(1, 10, 10, True, 'progression', 'stay')
        known = self.db._arena_known_skills_locked(1, 10, True)
        replace = next(k for k in known if k != 'bum_punch')
        await self.db.arena_use_item(1, 10, item, 10, replace_skill=replace)
        self.assertEqual(self.qty('last_argument'), 0)
        self.assertIn('last_argument', self.db._arena_known_skills_locked(1, 10, True))
        self.assertNotIn(replace, self.db._arena_known_skills_locked(1, 10, True))
        passive = self.add('nothing_to_lose', kind='passive')
        await self.db.arena_use_item(1, 10, passive, 10)
        self.assertEqual(self.qty('nothing_to_lose', 'passive'), 0)
        await self.db.close()
        await self.db.connect()
        view = await self.db.arena_passive_view(1, 10, True)
        self.assertIn('last_argument', view['known_skills'])
        self.assertIn('nothing_to_lose', {p['skill_id'] for p in view['passives']})

    async def test_insufficient_pages_francs_changed_catalog_or_odds_leave_inputs(self):
        self.resources(pages={'common': 5})
        with self.assertRaisesRegex(ValueError, 'страниц'):
            await self.perform('craft', kind='skill', rarity='common')
        self.resources(pages={'common': 6})
        request = await self.request('craft', kind='skill', rarity='common')
        with patch.dict(FORGE_PAGE_ODDS['common'], common=84, uncommon=15):
            with self.assertRaisesRegex(ValueError, 'изменились'):
                await self.db.arena_forge_action(1, 10, request)
        self.db.connection.execute('UPDATE franc_balances SET balance=0 WHERE chat_id=1 AND user_id=10')
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, 'франков'):
            await self.perform('craft', kind='skill', rarity='common')
        self.assertEqual((await self.db.arena_forge_view(1, 10))['pages'], {'common': 6})

    async def test_rollback_preserves_inputs_francs_revision_and_no_receipt(self):
        item = self.add('humiliate', 3)
        before = await self.db.arena_forge_view(1, 10)
        with patch.object(self.db, '_arena_add_item_locked', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                await self.perform('rewrite', items=[dict(id=item, quantity=3)])
        self.assertEqual(self.qty('humiliate'), 3)
        self.assertEqual(await self.db.franc_balance(1, 10), 10000)
        after = await self.db.arena_forge_view(1, 10)
        self.assertEqual(before['revision'], after['revision'])
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_forge_actions').fetchone()[0], 0)

    async def test_upgrade_preserves_old_pages_seals_and_unused_recipe_table(self):
        self.db.connection.execute('CREATE TABLE arena_forge_recipes (chat_id INTEGER, owner_id INTEGER, kind TEXT, content_id TEXT)')
        self.db.connection.execute("INSERT INTO arena_forge_recipes VALUES(1,10,'skill','dust_in_eyes')")
        self.resources(pages={'rare': 9}, seals={'lei_heng': 3})
        await self.db.close()
        await self.db.connect()
        view = await self.db.arena_forge_view(1, 10)
        self.assertEqual(view['pages'], {'rare': 9})
        self.assertEqual(view['seals'], {'lei_heng': 3})
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_forge_recipes').fetchone()[0], 1)

    async def test_invalid_inputs_cannot_spend(self):
        item = self.add(actor=20)
        request = await self.request('dismantle', items=[dict(id=item, quantity=1)])
        for changes in ({}, {'operation': []}, {'confirm': False}, {'revision': True}, {'nonce': 'bad'}, {'items': [dict(id=True, quantity=1)]}, {'items': [dict(id=item, quantity=-1)]}, {'items': [dict(id=item, quantity=True)]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await self.db.arena_forge_action(1, 10, dict(request, **changes))
        self.assertEqual(self.qty(actor=20), 1)

    async def test_http_signed_identity_membership_ignores_forged_price_and_odds(self):
        self.resources(pages={'epic': 6})
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        path, headers = '/api/menu/1', {'X-Telegram-Init-Data': signed(10, int(time.time()))}
        request = dict(action='forge', **await self.request('craft', kind='skill', rarity='epic'))
        try:
            self.assertEqual((await client.post(path, json=request)).status, 400)
            self.bot.get_chat_member.return_value.status = 'left'
            self.assertEqual((await client.post(path, headers=headers, json=request)).status, 400)
            self.bot.get_chat_member.return_value.status = 'member'
            response = await client.post(path, headers=headers, json=dict(request, actor=20, price=-100, odds={'epic':100}))
            self.assertEqual(response.status, 200, await response.text())
            data = await response.json()
            self.assertEqual(data['menu']['actor_id'], 10)
            self.assertEqual(data['menu']['balance'], 9750)
            self.assertEqual((await client.post(path, headers=headers, json=request)).status, 200)
            self.assertEqual(await self.db.franc_balance(1, 10), 9750)
        finally:
            await client.close()


class ForgeClientTests(unittest.TestCase):
    def data(self):
        data = client_tests.ArenaMarketClientTests().menu_data()
        data['forge'] = dict(revision=0, catalog_revision='f'*16, pages={'common':6}, seals={},
            rarities=[dict(id=k,name=k,**v) for k,v in FORGE_RULES.items()],
            inventory=[dict(id=3,kind='skill',content_id='dust_in_eyes',name='<Пыль>',quantity=3,rarity='common',salvage_pages=2,can_rewrite=True,details={}),
                       dict(id=4,kind='skill',content_id='last_argument',name='Последний аргумент',quantity=3,rarity='epic',salvage_pages=2,can_rewrite=True,details={})],
            crafts=[dict(kind='skill',rarity='common',pages=6,price=40,odds=FORGE_PAGE_ODDS['common'])],
            fusion_odds={'skill':FORGE_FUSION_ODDS},
            pools=[dict(kind='skill',rarity=r,choices=[dict(kind='skill',content_id=r,name='<'+r+'>',rarity=r,details={})]) for r in FORGE_RULES])
        return data

    def render(self, code):
        return client_tests.ArenaMarketClientTests().run_client(code, self.data())

    def test_forge_views_confirmation_and_escaped_details(self):
        body = self.render("page='forge';menuScreen(input);")
        self.assertIn('forge-dismantle-3', body)
        self.assertIn('&lt;Пыль&gt;', body)
        self.assertNotIn('Рецепты</button>', body)
        body = self.render("page='forge';forgeMode='craft';menuScreen(input);")
        self.assertIn('data-do="forgecraft:skill:common"', body)
        self.assertIn('6 стр. · 40 ₣', body)
        self.assertIn('85%', body)
        self.assertNotIn('100%', body)
        body = self.render("page='forge';forgeMode='rewrite';menuScreen(input);")
        self.assertIn('forge-rewrite-3', body)
        self.assertIn('forge-rewrite-4', body)
        self.assertIn('Редкости можно смешивать', body)
        self.assertIn('Внутри неё шансы навыков равные', body)
        self.assertNotIn('100%', body)
        body = self.render("page='forgeConfirm';forgePending={summary:'<p>Списать 40 ₣</p>'};menuScreen(input);")
        self.assertIn('data-do="forgeconfirm"', body)
        self.assertIn('data-do="forgecancel"', body)

    def test_client_fusion_odds_price_match_server(self):
        result = json.loads(self.render("out=JSON.stringify(forgeFusion(input.forge,input.forge.inventory,[{id:3,quantity:2},{id:4,quantity:1}]));"))
        self.assertEqual(result['price'], 55)
        for r in FORGE_RULES:
            self.assertAlmostEqual(result['odds'][r], (FORGE_FUSION_ODDS['common'][r]*2+FORGE_FUSION_ODDS['epic'][r])/3)
        detail = self.render("out=forgeInfo({kind:'skill',details:{unlock_level:10,cost:15,accuracy:95,power:32,cooldown:4,effects:[{kind:'resource_leech',value:15,target:'enemy'}]}});")
        self.assertIn('нужен уровень 10', detail)
        self.assertIn('-15 противнику', detail)


if __name__ == '__main__':
    unittest.main()
