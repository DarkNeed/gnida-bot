import json
import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from aiohttp.test_utils import TestClient, TestServer

from arena_encounters import parse_roster, create_encounter, alive_enemies
from arena_engine import FIGHTER_CLASSES, BUILTIN_SKILLS
from arena_raid_engine import resolve_round, finish_if_needed, raid_snapshot
from arena_raid_web import raid_view
from handlers.raids import RaidPublisher, ENCOUNTER_RE, create_raid_router
from arena_web import create_arena_app
import test_arena
from test_arena_raids import Roll
import test_arena_market_client as client_tests


def encounter(roster=None, actors=(20,)):
    participants = [dict(actor_id=k, fighter_id=k, personal=True, slave_owner=k) for k in actors]
    sources = [dict(slave_id=k, owner_id=k, class_id='ragamuffin', level=1) for k in actors]
    return create_encounter(participants, sources, FIGHTER_CLASSES, BUILTIN_SKILLS,
                            roster or ['goblin', 'goblin', 'shaman'], 10)


class EncounterEngineTests(unittest.TestCase):
    def test_parser_limits_and_mixed_roster(self):
        self.assertEqual(parse_roster('гоблин 2, шаман'), ['goblin', 'goblin', 'shaman'])
        self.assertEqual(parse_roster('громила'), ['brute'])
        self.assertTrue(ENCOUNTER_RE.fullmatch('/встреча@GnidoBot гоблин 2, шаман'))
        for text in ('', 'гоблин 4', 'гоблин 3, шаман', 'кит', 'гоблин -1', 'гоблин 1.5', 'гоблин,'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_roster(text)

    def test_enemy_targets_independent_hp_effects_and_snapshots(self):
        data = encounter()
        data['players']['20']['fighter']['hp'] = 10000
        data['players']['20'].update(selected='bum_punch', selected_target='e2')
        before = raid_snapshot(data)
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertEqual(data['round'], 2)
        self.assertEqual(data['enemies']['e1']['hp'], before['e1']['hp'])
        self.assertLess(data['enemies']['e2']['hp'], before['e2']['hp'])
        self.assertTrue(any(e['actor'] == '20' and e['target'] == 'e2' for e in data['log']))
        self.assertEqual(before['e2']['hp'], before['e1']['hp'])
        self.assertNotIn('selected', json.dumps(before))
        self.assertNotIn(10, [p['actor_id'] for p in data['players'].values()])

    def test_killing_first_enemy_does_not_end_encounter_or_attack(self):
        data = encounter()
        data['players']['20']['fighter']['hp'] = 10000
        data['enemies']['e1']['hp'] = 1
        data['players']['20'].update(selected='bum_punch', selected_target='e1')
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertFalse(data['finished'])
        self.assertEqual(data['enemies']['e1']['hp'], 0)
        self.assertFalse(any(e['actor'] == 'e1' and e.get('skill') for e in data['log']))
        for f in data['enemies'].values():
            f['hp'] = 0
        self.assertTrue(finish_if_needed(data))
        self.assertTrue(data['won'])
        self.assertEqual(data['rewards'], {})

    def test_already_dead_selected_target_does_not_retarget_or_charge(self):
        data = encounter(actors=(20, 30))
        data['enemies']['e2']['hp'] = 0
        for p in data['players'].values():
            p.update(selected='bum_punch', selected_target='e2')
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertFalse(any(e['actor'] in ('20', '30') and e.get('skill') for e in data['log']))
        self.assertTrue(all(p['fighter']['resource'] == 100 for p in data['players'].values()))

    def test_self_support_still_works_when_selected_enemy_has_died(self):
        data = encounter()
        player = data['players']['20']
        player['fighter']['level'] = 20
        player['fighter']['loadout'].append('last_amendment')
        player['fighter']['hp'] = 10000
        player.update(selected='last_amendment', selected_target='e2')
        data['enemies']['e2']['hp'] = 0
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertIn('last_amendment', player['fighter']['mechanics'])
        self.assertEqual(player['fighter']['resource'], 58)

    def test_shaman_heals_brute_guards_and_stun_interrupts_one_enemy(self):
        data = encounter(['brute', 'shaman'])
        data['enemies']['e1']['hp'] -= 30
        data['players']['20']['fighter']['hp'] = 10000
        for _ in range(3):
            data['players']['20']['selected'] = 'defend'
            resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertTrue(any(e.get('healing', 0) > 0 for e in data['log']))
        self.assertTrue(any('Прикрытие' in e['text'] for e in data['log']))
        data['enemies']['e1']['effects'].append(dict(id='test', kind='stun', value=1, duration=1))
        data['players']['20']['selected'] = 'defend'
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertTrue(any(e['actor'] == 'e1' and 'намерение сорвано' in e['text'] for e in data['log']))


class EncounterStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown

    async def lobby(self, roster=None):
        row = await self.db.arena_encounter_create(1, 10, roster or ['goblin', 'goblin', 'shaman'])
        await self.db.arena_raid_set_message(row['token'], 5)
        return await self.db.arena_raid_get(row['token'])

    async def start(self):
        row = await self.lobby()
        await self.db.arena_raid_setup(row['token'], 20, 'join')
        return await self.db.arena_raid_setup(row['token'], 10, 'start')

    async def test_master_not_reserved_not_joined_and_only_master_can_control(self):
        row = await self.lobby()
        self.assertEqual(row['participants'], [])
        self.assertFalse(self.db._arena_busy_locked(1, 10))
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row['token'], 10, 'start')
        with self.assertRaises(ValueError):
            await self.db.arena_encounter_create(1, 10, ['goblin'])
        row = await self.db.arena_raid_setup(row['token'], 20, 'join')
        for action in ('start', 'cancel'):
            with self.assertRaises(ValueError):
                await self.db.arena_raid_setup(row['token'], 20, action)
        row = await self.db.arena_raid_setup(row['token'], 10, 'start')
        with self.assertRaises(ValueError):
            await self.db.arena_raid_setup(row['token'], 20, 'finish')
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_raid(row['token'], 10, 1, 'bum_punch', target='e1')
        self.assertFalse(self.db._arena_busy_locked(1, 10))
        self.assertTrue(self.db._arena_busy_locked(1, 20))
        row = await self.db.arena_raid_setup(row['token'], 10, 'finish')
        self.assertEqual(row['status'], 'finished')
        self.assertFalse(self.db._arena_busy_locked(1, 20))

    async def test_master_can_opt_in_and_leave_without_cancelling(self):
        row = await self.lobby(['goblin'])
        await self.db.arena_raid_setup(row['token'], 10, 'join')
        row = await self.db.arena_raid_setup(row['token'], 10, 'leave')
        self.assertEqual(row['status'], 'lobby')
        self.assertEqual(row['participants'], [])

    async def test_rewards_and_claims_unchanged_even_on_win_and_repeated_reads(self):
        row = await self.start()
        balance = test_arena.ArenaStoreTests.balance(self, 20)
        before = dict(self.db._arena_profile_locked(1, 20, True))
        tables = ('arena_raid_reward_cooldowns', 'arena_raid_global_pity', 'arena_raid_daily_claims', 'arena_inventory')
        def counts():
            return [self.db.connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in tables]
        old = counts()
        data = json.loads(row['data_json'])
        data['players']['20']['manual_turns'] = 10
        for f in data['enemies'].values():
            f['hp'] = 0
        finish_if_needed(data)
        with self.db.connection:
            self.db._raid_finish_locked(row, data)
        for _ in range(2):
            row = await self.db.arena_raid_get(row['token'])
            view = await raid_view(self.db, row, 20)
            self.assertEqual(view['data']['rewards'], {})
            self.assertFalse(view['rewards_enabled'])
        self.assertEqual(test_arena.ArenaStoreTests.balance(self, 20), balance)
        self.assertEqual(self.db._arena_profile_locked(1, 20, True)['xp'], before['xp'])
        self.assertEqual(counts(), old)
        with self.assertRaises(ValueError):
            self.db._raid_finish_locked(row, data)

    async def test_target_validation_persisted_flow_each_enemy_gets_own_defense(self):
        row = await self.start()
        data = json.loads(row['data_json'])
        data['players']['20']['fighter']['hp'] = 10000
        with self.db.connection:
            self.db._raid_save_locked(row, data)
        for target in ('boss', '20', 'e99', 1, {'bad': 1}):
            with self.assertRaises(ValueError):
                await self.db.arena_interactive_raid(row['token'], 20, 1, 'bum_punch', target=target)
        await self.db.arena_interactive_raid(row['token'], 20, 1, 'bum_punch', target='e2')
        flow = self.db._qte_load_locked('raid', row['token'], 20)
        self.assertEqual(flow['target'], 'e2')
        self.assertEqual([s.get('encounter_enemy') for s in flow['stages'][1:]], ['e1', 'e2', 'e3'])
        await self.db.close()
        await self.db.connect()
        for _ in range(4):
            flow = self.db._qte_load_locked('raid', row['token'], 20)
            self.assertIsNotNone(flow)
            await self.db.arena_interactive_raid(row['token'], 20, 1, proof=dict(abort=True),
                challenge_id=flow['stages'][0]['id'], target='e3')
        row = await self.db.arena_raid_get(row['token'])
        data = json.loads(row['data_json'])
        self.assertEqual(data['round'], 2)
        self.assertTrue(any(e['actor'] == '20' and e['target'] == 'e2' for e in data['log']))
        self.assertFalse(any('_qte_guard' in f for f in data['enemies'].values()))
        self.assertIsNone(self.db._qte_load_locked('raid', row['token'], 20))

    async def test_finish_removes_live_minigames_and_lobby_survives_restart(self):
        row = await self.start()
        await self.db.arena_interactive_raid(row['token'], 20, 1, 'defend')
        self.assertIsNotNone(self.db._qte_load_locked('raid', row['token'], 20))
        await self.db.arena_raid_setup(row['token'], 10, 'finish')
        self.assertIsNone(self.db._qte_load_locked('raid', row['token'], 20))
        row = await self.lobby(['goblin'])
        await self.db.close()
        await self.db.connect()
        row = await self.db.arena_raid_get(row['token'])
        self.assertEqual(json.loads(row['encounter_json'])['roster'], ['goblin'])
        self.assertTrue(any(r['token'] == row['token'] for r in await self.db.arena_raid_list(1, 10)))
        with patch('arena_raid.time.time', return_value=row['deadline']):
            await self.db.arena_raid_expire()
        self.assertEqual((await self.db.arena_raid_get(row['token']))['status'], 'cancelled')

    async def test_defenses_are_not_reused_between_three_enemies(self):
        row = await self.start()
        data = json.loads(row['data_json'])
        data['players']['20']['fighter']['hp'] = 10000
        with self.db.connection:
            self.db._raid_save_locked(row, data)
        await self.db.arena_interactive_raid(row['token'], 20, 1, 'defend')
        with patch('arena_qte_live.replay', side_effect=[[False], [True], [False]]), patch('arena_encounters.random.SystemRandom', return_value=Roll()):
            for _ in range(3):
                flow = self.db._qte_load_locked('raid', row['token'], 20)
                await self.db.arena_interactive_raid(row['token'], 20, 1, proof={}, challenge_id=flow['stages'][0]['id'])
        data = json.loads((await self.db.arena_raid_get(row['token']))['data_json'])
        damage = {e['actor']: e['damage'] for e in data['log'] if e.get('skill')}
        self.assertGreater(damage['e1'], 0)
        self.assertEqual(damage['e2'], 0)
        self.assertGreater(damage['e3'], 0)

    async def test_command_publication_and_failed_publication_are_safe(self):
        pub = RaidPublisher(self.db, self.bot, 'TestBot')
        router = create_raid_router(self.db, self.bot, True, pub)
        handler = next(h.callback for h in router.message.handlers if h.callback.__name__ == 'encounter_command')
        message = SimpleNamespace(text='/встреча гоблин 2, шаман', caption=None,
            from_user=SimpleNamespace(id=10, is_bot=False), chat=SimpleNamespace(id=1, type='supergroup'),
            answer=AsyncMock(return_value=SimpleNamespace(message_id=5)))
        await handler(message)
        message.answer.assert_awaited_once()
        row = (await self.db.arena_raid_list(1, 10))[0]
        self.assertEqual((await self.db.arena_raid_get(row['token']))['participants'], [])
        await self.db.arena_raid_setup(row['token'], 10, 'cancel')
        message.answer = AsyncMock(side_effect=RuntimeError('publication failed'))
        with self.assertRaises(RuntimeError):
            await handler(message)
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_raids WHERE boss_id='encounter' AND status IN ('lobby','active')").fetchone()[0], 0)

    async def test_http_auth_target_and_master_end_permissions(self):
        row = await self.start()
        client = TestClient(TestServer(create_arena_app(self.db, self.bot, test_arena.TOKEN)))
        await client.start_server()
        path = '/api/raid/' + row['token']
        def headers(actor):
            return {'X-Telegram-Init-Data': test_arena.signed(actor, int(time.time()))}
        try:
            self.assertEqual((await client.post(path, json=dict(action='finish'))).status, 400)
            response = await client.get(path, headers=headers(10))
            self.assertTrue((await response.json())['is_master'])
            self.assertEqual((await client.post(path, headers=headers(20), json=dict(action='finish'))).status, 400)
            self.assertEqual((await client.post(path, headers=headers(10), json=dict(action='skill', round=1, skill='bum_punch', target='e1'))).status, 400)
            response = await client.post(path, headers=headers(20), json=dict(action='skill', round=1, skill='bum_punch', target='e2'))
            self.assertEqual(response.status, 200, await response.text())
            self.assertEqual(self.db._qte_load_locked('raid', row['token'], 20)['target'], 'e2')
            response = await client.post(path, headers=headers(10), json=dict(action='finish'))
            self.assertEqual(response.status, 200, await response.text())
            self.assertEqual((await response.json())['status'], 'finished')
        finally:
            await client.close()

    async def test_view_chat_and_mobile_client_render_three_enemies_master_and_targets(self):
        row = await self.start()
        view = await raid_view(self.db, row, 10)
        self.assertTrue(view['is_master'])
        self.assertEqual(len(view['data']['enemies']), 3)
        text = await RaidPublisher(self.db, self.bot, 'TestBot').body(row)
        self.assertIn('Награды отключены', text)
        renderer = client_tests.ArenaMarketClientTests()
        render = 'document.querySelector=()=>null;document.getElementById=()=>null;raidScreen(input);'
        html = renderer.run_client(render, view)
        self.assertIn('Управление мастера', html)
        self.assertEqual(html.count('class="raid-fighter raid-enemy encounter-enemy'), 3)
        self.assertNotIn('Выбери действие', html)
        self.assertNotIn('data-raid="target:', html)
        view = await raid_view(self.db, row, 20)
        html = renderer.run_client(render, view)
        self.assertIn('Нажми на спрайт врага', html)
        self.assertNotIn('encounter-targets', html)
        self.assertNotIn('<h3>Цель навыка</h3>', html)
        self.assertEqual(html.count('class="raid-art encounter-target"'), 3)
        self.assertIn('aria-label="Выбрать цель: Гоблин №2"', html)
        self.assertIn('data-raid="target:e2"', html)
        self.assertNotIn('Управление мастера', html)

    async def test_sprite_target_selection_is_local_and_rejects_dead_or_locked_targets(self):
        row = await self.start()
        view = await raid_view(self.db, row, 20)
        result = client_tests.ArenaMarketClientTests().run_client('''
raidCurrent=input;
const marks={},pressed={},label={textContent:''};
app.querySelectorAll=()=>Object.keys(input.data.enemies).map(key=>({
  id:'raid-fighter-'+key,
  classList:{toggle(name,value){marks[key]=value;}},
  querySelector(){return {setAttribute(name,value){pressed[key]=value;}};}
}));
document.getElementById=()=>label;
selectEncounterTarget('e3');
const valid=encounterTarget,selectedName=label.textContent;
input.data.enemies.e2.hp=0;
selectEncounterTarget('e2');const afterDead=encounterTarget;
selectEncounterTarget('not-an-enemy');const afterUnknown=encounterTarget;
const deadMarkup=encounterPortrait(input.data.enemies.e2,'e2',1);
input.data.players['20'].ready=true;
selectEncounterTarget('e1');const afterReady=encounterTarget;
input.data.players['20'].ready=false;input.qte={waiting:true};
selectEncounterTarget('e1');const afterQte=encounterTarget;
input.qte=null;input.actor_id=10;
selectEncounterTarget('e1');
out=JSON.stringify({valid,selectedName,afterDead,afterUnknown,afterReady,afterQte,
  afterViewer:encounterTarget,marks,pressed,deadDisabled:deadMarkup.includes(' disabled')});
''', view)
        result = json.loads(result)
        for key in ('valid', 'afterDead', 'afterUnknown', 'afterReady', 'afterQte', 'afterViewer'):
            self.assertEqual(result[key], 'e3')
        self.assertEqual(result['selectedName'], 'Шаман №3')
        self.assertEqual(result['marks'], dict(e1=False, e2=False, e3=True))
        self.assertEqual(result['pressed'], dict(e1='false', e2='false', e3='true'))
        self.assertTrue(result['deadDisabled'])


if __name__ == '__main__':
    unittest.main()
