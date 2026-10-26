"""RP templates and free combat are isolated from ordinary progression."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from arena_engine import BUILTIN_SKILLS, validate_skill, resolve_skill
from arena_rp import rp_skills, template_fighter
from arena_raid_engine import pair_state, finish_if_needed
from arena_raid_web import raid_view
from arena_web import create_arena_app
from database import Database
from handlers.rp import RP_RE, create_rp_router
from test_arena import signed, TOKEN
from test_arena_rebalance import FixedRoll


def definition(**changes):
    return dict(name='RP-боец', class_id='warrior', level=20, archclass_id='',
                skills=['bum_punch', 'mana_shot', 'armor_split', 'dust_in_eyes', 'chaplain_p3_1', 'lei_perfected_flurry'],
                passives=['steady_hand', 'stone_skin', 'inherent:mage:0', 'inherent:warrior:0'], **changes)


class RPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / 'rp.sqlite3')
        await self.db.connect()
        for chat in (-100, -200):
            await self.db.upsert_chat(chat, 'RP-чат')
        for actor in (10, 20, 30):
            await self.db.upsert_user(-100, actor, str(actor), 'Игрок ' + str(actor))
        self.bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member', user=SimpleNamespace(is_bot=False))))

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    async def character(self, actor=20, **changes):
        v = definition()
        v.update(changes)
        return await self.db.arena_rp_save(actor, 'character', v)

    async def lobby(self, mob=None):
        return await self.db.arena_rp_encounter_create(-100, 10,
            [dict(kind='mob', id=mob['id'])] if mob else [dict(kind='builtin', id='goblin')], 'a'*32)

    async def start(self, *, mob=None, normal=False):
        template = await self.character()
        row = await self.lobby(mob)
        await self.db.arena_raid_setup(row['token'], 20, 'join', rp_template=template['id'])
        if normal:
            self.db._arena_profile_locked(-100, 30, True)
            self.db.connection.commit()
            await self.db.arena_raid_setup(row['token'], 30, 'join')
        row = await self.db.arena_raid_setup(row['token'], 10, 'start', expected_revision=(await self.db.arena_raid_get(row['token']))['revision'])
        return row, template

    async def test_private_templates_unlimited_loadout_and_no_paid_slots(self):
        baseline = {table: list(self.db.connection.execute('SELECT * FROM ' + table))
                    for table in ('personal_profiles', 'arena_character_slots', 'arena_character_accounts')}
        t = await self.character()
        self.assertGreater(len(t['definition']['skills']), 4)
        self.assertEqual(await self.db.arena_rp_templates(10), [])
        with self.assertRaises(ValueError):
            await self.db.arena_rp_save(10, 'character', t['definition'], ident=t['id'], revision=1)
        with self.assertRaises(ValueError):
            await self.db.arena_rp_delete(10, t['id'], 1)
        edited = await self.db.arena_rp_save(20, 'character', dict(t['definition'], name='Изменён'), ident=t['id'], revision=1)
        self.assertEqual(edited['revision'], 2)
        with self.assertRaises(ValueError):
            await self.db.arena_rp_save(20, 'character', t['definition'], ident=t['id'], revision=1)
        await self.db.close(); await self.db.connect()
        self.assertEqual((await self.db.arena_rp_templates(20))[0]['definition']['name'], 'Изменён')
        for table, rows in baseline.items():
            self.assertEqual(list(self.db.connection.execute('SELECT * FROM ' + table)), rows, table)

    async def test_catalog_combinations_never_raise_context_exceptions(self):
        classes, ordinary = self.db._fighter_catalog_locked()
        skills = rp_skills(ordinary)
        errors=[]
        for cid in classes:
            v=definition();v.update(class_id=cid,skills=list(skills))
            t=await self.db.arena_rp_save(20,'character',v)
            base=template_fighter(t,20,classes,skills)
            base['hp']=base['stats']['max_hp']=10000
            base['resource']=base['stats']['resource_max']=1000
            for sid in skills:
                pair=pair_state(deepcopy(base),deepcopy(base))
                try:
                    resolve_skill(pair,'a',sid,skills,FixedRoll(.5),advance_turn=False,qte=dict(attack=[True]*6,luck_evasion=False))
                except ValueError:
                    pass  # Explicit gameplay requirements are intentionally kept.
                except Exception as error:
                    errors.append((cid,sid,type(error).__name__,str(error)))
        self.assertEqual(errors[:20],[])

    async def test_invalid_input_and_image_ownership(self):
        for changes in (dict(level=0), dict(level=21), dict(level=True), dict(skills=['bum_punch']*2),
                        dict(skills=['unknown']), dict(name=''), dict(archclass_id='mage_necromancer'),
                        dict(sprite_key='a'*64), dict(scale=float('nan'))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await self.character(**changes)
        with self.assertRaises(ValueError):
            await self.db.arena_rp_save(20, 'mob', dict(definition(), stats=dict(evasion=101)))
        key = await self.db.arena_rp_image(20, b'fixture')
        t = await self.character(sprite_key=key, flip=True)
        self.assertTrue(t['definition']['flip'])
        with self.assertRaises(ValueError):
            await self.character(10, sprite_key=key)

    async def test_builtin_mob_presets_can_be_saved_without_unknown_stats(self):
        catalog=await self.db.arena_rp_catalog()
        for preset in catalog['mobs']:
            saved=await self.db.arena_rp_save(10,'mob',preset['definition'])
            self.assertEqual(saved['definition']['skills'],[preset['skill']])

    async def test_mixed_lobby_master_and_snapshot_independence(self):
        mob = await self.db.arena_rp_save(10, 'mob', dict(definition(), name='Своя тень', stats=dict(max_hp=777), ai='sequence'))
        row, t = await self.start(mob=mob, normal=True)
        data = json.loads(row['data_json'])
        self.assertEqual(set(data['players']), {'20', '30'})
        self.assertTrue(data['players']['20']['fighter']['rp_sandbox'])
        self.assertNotIn('rp_sandbox', data['players']['30']['fighter'])
        self.assertEqual(len(data['players']['20']['fighter']['loadout']), 6)
        self.assertEqual(len(data['players']['20']['fighter']['passive_details']), 4)
        self.assertEqual(data['enemies']['e1']['hp'], 777)
        await self.db.arena_rp_delete(10, mob['id'], mob['revision'])
        await self.db.arena_rp_delete(20, t['id'], t['revision'])
        self.assertEqual(json.loads((await self.db.arena_raid_get(row['token']))['data_json']), data)
        view = await raid_view(self.db, row, 20)
        self.assertEqual(view['data']['players']['20']['fighter']['name'], 'RP-боец')
        self.assertEqual(view['data']['enemies']['e1']['name'], 'Своя тень')
        self.assertEqual(len(view['data']['players']['20']['fighter']['skill_details']), 6)
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM personal_profiles WHERE user_id=20').fetchone())
        self.assertNotIn(row['token'], [r['token'] for r in await self.db.arena_raid_list(-100,20)])
        self.assertNotIn(row['token'], [r['token'] for r in await self.db.arena_raid_list(-100,10)])

    async def test_idempotent_create_master_not_a_fighter_and_cross_mode_denial(self):
        t = await self.character(actor=10)
        row = await self.lobby()
        self.assertEqual((await self.lobby())['token'], row['token'])
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row['token'], 10, 'join', rp_template=t['id'])
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row['token'], 20, 'join', rp_template=t['id'])
        normal = await self.db.arena_raid_create(-100, 30)
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(normal['token'], 20, 'join', rp_template=t['id'])
        with self.assertRaises(ValueError):
            await self.db.arena_rp_encounter_create(-100, 10, [dict(kind='builtin', id='brute')], 'a'*32)

    async def test_free_skills_still_pay_energy_and_respect_conditions_and_qte(self):
        row, _ = await self.start()
        data = json.loads(row['data_json'])
        f = data['players']['20']['fighter']
        f['loadout'].append('chaplain_rewind')
        with self.assertRaises(ValueError):
            validate_skill(pair_state(f, data['boss']), 'a', 'chaplain_rewind', rp_skills(BUILTIN_SKILLS))
        f['resource'] = 0
        with self.assertRaises(ValueError):
            validate_skill(pair_state(f, data['boss']), 'a', 'mana_shot', rp_skills(BUILTIN_SKILLS))
        await self.db.arena_interactive_raid(row['token'], 20, 1, 'chaplain_p3_1', target='e1')
        flow = self.db._qte_load_locked('raid', row['token'], 20)
        self.assertEqual(flow['stages'][0]['profile']['base_id'], 'chaplain_p3_1')
        self.assertEqual(flow['stages'][-1]['encounter_enemy'], 'e1')
        await self.db.arena_raid_setup(row['token'], 10, 'finish')
        self.assertIsNone(self.db._qte_load_locked('raid', row['token'], 20))

    async def test_custom_enemy_intents_have_native_qte_and_ai_skip_unavailable(self):
        mob = await self.db.arena_rp_save(10, 'mob', dict(definition(), skills=['chaplain_rewind', 'mana_shot'], ai='priority'))
        row, _ = await self.start(mob=mob)
        data = json.loads(row['data_json'])
        self.assertEqual(data['enemy_intents']['e1']['skill'], 'mana_shot')
        await self.db.arena_interactive_raid(row['token'], 20, 1, 'defend', target='e1')
        flow = self.db._qte_load_locked('raid', row['token'], 20)
        self.assertEqual(len(flow['stages']), 1)
        self.assertEqual(flow['stages'][0]['profile']['base_id'], 'mana_shot')

    async def test_victory_never_changes_progress_or_rewards(self):
        row, _ = await self.start(normal=True)
        tables = ('personal_profiles', 'arena_inventory', 'arena_raid_reward_cooldowns', 'arena_raid_global_pity', 'arena_raid_daily_claims')
        before = {table: [tuple(r) for r in self.db.connection.execute('SELECT * FROM ' + table)] for table in tables}
        data = json.loads(row['data_json'])
        for f in data['enemies'].values(): f['hp'] = 0
        self.assertTrue(finish_if_needed(data))
        with self.db.connection: self.db._raid_finish_locked(row, data)
        for table in tables:
            self.assertEqual([tuple(r) for r in self.db.connection.execute('SELECT * FROM ' + table)], before[table], table)
        self.assertEqual(data['rewards'], {})

    async def test_http_authorization_catalog_crud_and_asset_types(self):
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, TOKEN)))
        await client.start_server()
        try:
            headers={'X-Telegram-Init-Data': signed(now=int(time.time()), user=20)}
            self.assertEqual((await client.get('/api/rp/templates')).status, 400)
            chats = await (await client.get('/api/rp/chats', headers=headers)).json()
            self.assertEqual([c['chat_id'] for c in chats['chats']], [-100])
            catalog = await (await client.get('/api/rp/catalog', headers=headers)).json()
            self.assertIn('chaplain_p4_2', [s['skill_id'] for s in catalog['skills']])
            r=await client.post('/api/rp/settings',json=dict(enabled=False),headers=headers)
            self.assertEqual(r.status,200)
            self.assertFalse((await r.json())['combat_settings']['minigames'])
            self.assertFalse(self.db.connection.execute('SELECT 1 FROM personal_profiles WHERE user_id=20').fetchone())
            result = await (await client.post('/api/rp/templates', json=dict(kind='character', definition=definition()), headers=headers)).json()
            self.assertIn('template', result)
            r = await client.post('/api/rp/encounters', headers=headers, json=dict(chat=-200, roster=[dict(kind='builtin', id='goblin')], nonce='c'*32))
            self.assertEqual(r.status, 400)
            r = await client.get('/rp/client.js');self.assertEqual(r.status, 200);self.assertIn('javascript', r.headers['Content-Type'])
            out=BytesIO();Image.new('RGBA',(32,32),(10,20,30,255)).save(out,format='PNG')
            r=await client.post('/api/rp/images?kind=avatar',data=out.getvalue(),headers={**headers,'Content-Type':'image/png'})
            self.assertEqual(r.status,200)
            image=await r.json();self.assertEqual((await client.get(image['url'])).status,200)
            r=await client.post('/api/rp/images?kind=sprite',data=out.getvalue(),headers={**headers,'Content-Type':'image/png'})
            self.assertEqual(r.status,400)
        finally:
            await client.close()

    async def test_command_is_separate_and_private_does_not_require_menu(self):
        router=create_rp_router(self.db,self.bot,'GnidoBot',True)
        handler=router.message.handlers[0].callback
        message=SimpleNamespace(from_user=SimpleNamespace(id=20,is_bot=False),chat=SimpleNamespace(id=20,type='private'),answer=AsyncMock())
        await handler(message)
        markup=message.answer.call_args.kwargs['reply_markup']
        self.assertTrue(markup.inline_keyboard[0][0].url.endswith('startapp=rp'))
        for command in ('/рп','/rp','/рп@GnidoBot'):
            self.assertTrue(RP_RE.fullmatch(command))
        self.assertFalse(RP_RE.fullmatch('/рпп'))
        first=SimpleNamespace(from_user=SimpleNamespace(id=999,is_bot=False,full_name='Новый участник'),
                              chat=SimpleNamespace(id=-300,type='supergroup',title='Первое RP'),answer=AsyncMock())
        await handler(first)
        self.assertTrue(await self.db.user_knows_chat(999,-300))
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM personal_profiles WHERE user_id=999').fetchone())

    async def test_ai_sequence_priority_and_random_preserve_gameplay_requirements(self):
        from arena_encounters import set_intents
        for mode in ('sequence','priority','random'):
            mob=await self.db.arena_rp_save(10,'mob',dict(definition(),skills=['mana_shot','armor_split','chaplain_rewind'],ai=mode))
            classes,skills=self.db._fighter_catalog_locked()
            fighter=template_fighter(mob,-1,classes,rp_skills(skills))
            fighter.update(mob_id='custom',controller_id=0,is_boss=True)
            data=dict(players={'20':dict(fighter=deepcopy(fighter))},enemies={'e1':fighter},round=1)
            set_intents(data,rp_skills(skills))
            first=data['enemy_intents']['e1']['skill']
            self.assertIn(first,('mana_shot','armor_split'))
            fighter['cooldowns'][first]=3
            set_intents(data,rp_skills(skills))
            self.assertNotEqual(first,data['enemy_intents']['e1']['skill'])
            fighter['resource']=0
            set_intents(data,rp_skills(skills))
            self.assertEqual(data['enemy_intents']['e1']['skill'],'bum_punch')

    async def test_deleted_lobby_template_does_not_fall_back_to_real_character(self):
        t=await self.character()
        row=await self.lobby()
        await self.db.arena_raid_setup(row['token'],20,'join',rp_template=t['id'])
        await self.db.arena_rp_delete(20,t['id'],t['revision'])
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row['token'],10,'start')
        self.assertEqual((await self.db.arena_raid_get(row['token']))['status'],'lobby')
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM personal_profiles WHERE user_id=20').fetchone())


if __name__ == '__main__':unittest.main()
