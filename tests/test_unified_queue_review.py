import asyncio
from copy import deepcopy
import math
import unittest

from aiohttp.test_utils import TestClient, TestServer

from arena_skill_timing import base_duration, duration, forecast, schedule, release
from tools.preview_unified_queue import (SKILLS, app, new_session, view, pair,
                                         idle_heroes, drive, complete_group, SESSIONS)


class TimingRulesTests(unittest.TestCase):
    def test_native_review_uses_unmodified_class_stats_and_four_slots(self):
        from arena_engine import stats_for
        state = new_session(dict(native=True, class_id='assassin', arch='assassin_shadow', scenario='mixed'))
        for key in state['fighters']:
            fighter = state['fighters'][key]
            expected = stats_for(fighter['class_id'], 20)
            self.assertEqual(fighter['hp'], expected['max_hp'])
            self.assertEqual(fighter['stats']['speed'], expected['speed'])
        self.assertEqual(len(state['fighters']['h1']['loadout']), 4)
        self.assertFalse(state['fighters']['h1']['rp_sandbox'])
        public = view(state, 'demo')['fighters']['h1']['arena']
        self.assertEqual(len(public['skill_details']), 4)
        self.assertIn('passive_details', public)

    def test_native_view_works_for_all_classes_and_scenarios(self):
        from arena_engine import FIGHTER_CLASSES
        for cls in FIGHTER_CLASSES:
            for scenario in ('solo', 'mixed', 'party', 'sync'):
                with self.subTest(class_id=cls, scenario=scenario):
                    public = view(new_session(dict(native=True, class_id=cls, scenario=scenario)), 'demo')
                    self.assertIn('arena', public['fighters']['h1'])

    def test_every_catalog_skill_has_finite_positive_duration(self):
        state = new_session({})
        hero = state['fighters']['h1']
        self.assertGreater(len(SKILLS), 300)
        for sid, skill in SKILLS.items():
            self.assertTrue(math.isfinite(base_duration(skill)), sid)
            self.assertGreaterEqual(duration(hero, skill), .75, sid)

    def test_forecast_before_together_after_and_no_incoming(self):
        self.assertEqual(forecast(1, 1, 3)['outcome'], 'before')
        self.assertEqual(forecast(1, 2, 3)['outcome'], 'together')
        self.assertEqual(forecast(1, 3, 3)['outcome'], 'after')
        self.assertEqual(forecast(1, 1, None)['outcome'], 'none')

    def test_schedule_does_not_release_until_completion_and_cannot_repeat(self):
        queue = dict(time=0., pending=[])
        schedule(queue, 'hero', 'cut', 'enemy', .8)
        with self.assertRaises(ValueError):
            schedule(queue, 'hero', 'cut', 'enemy', .8)
        self.assertEqual(queue['time'], 0)
        events = release(queue)
        self.assertEqual(queue['time'], .8)
        self.assertEqual(len(events), 1)
        self.assertEqual(release(queue), [])

    def test_two_different_actions_fit_before_enemy_no_auto_followup(self):
        state = new_session(dict(scenario='sync'))
        for sid in ('assassin_cut', 'assassin_needle'):
            hero = state['fighters']['h1']
            schedule(state, 'h1', sid, 'e1', duration(hero, SKILLS[sid]))
            drive(state)
            self.assertEqual(state['stages'][0]['kind'], 'attack')
            state['stages'] = []
            state['results']['h1'] = dict(attack=[True])
            drive(state)
            self.assertEqual(idle_heroes(state), ['h1'])
            self.assertFalse(any(e['actor'] == 'h1' for e in state['pending']))
        self.assertLess(state['time'], 3)
        self.assertEqual(len(state['log']), 2)
        self.assertTrue(any(e['kind'] == 'bleed' for e in state['fighters']['e1']['effects']))

    def test_enemy_hits_before_long_cast_and_player_cast_continues(self):
        state = new_session(dict(scenario='solo'))
        state['fighters']['h1']['hp'] = state['fighters']['h1']['stats']['max_hp'] = 1000
        schedule(state, 'h1', 'assassin_execution', 'e1', 4.)
        hp = state['fighters']['h1']['hp']
        drive(state)
        self.assertEqual(state['stages'][0]['kind'], 'defense')
        self.assertLess(state['time'], 4)
        while state['time'] < 4:
            state['stages'] = []
            state['results']['e1'] = dict(dodge=[False])
            drive(state)
        self.assertLess(state['fighters']['h1']['hp'], hp)
        self.assertEqual(state['time'], 4)
        self.assertEqual(state['stages'][0]['kind'], 'attack')

    def test_same_time_incoming_attacks_use_existing_combined_qte(self):
        state = new_session(dict(scenario='sync'))
        schedule(state, 'h1', 'assassin_execution', 'e1', 4.)
        drive(state)
        self.assertEqual(len(state['stages']), 1)
        self.assertEqual(state['stages'][0]['version'], 4)
        self.assertEqual(len(state['stages'][0]['members']), 2)

    def test_dead_enemy_loses_unfinished_cast(self):
        state = new_session(dict(scenario='sync'))
        schedule(state, 'h1', 'assassin_cut', 'e2', .8)
        drive(state)
        state['fighters']['e2']['hp'] = 0
        state['stages'] = []
        drive(state)
        self.assertFalse(any(e['actor'] == 'e2' for e in state['pending']))

    def test_party_waits_for_other_hero_without_repeating_first_action(self):
        state = new_session(dict(scenario='party'))
        schedule(state, 'h1', 'assassin_cut', 'e1', .85)
        drive(state)
        self.assertEqual(state['time'], 0)
        self.assertEqual(idle_heroes(state), ['h2'])
        schedule(state, 'h2', 'armor_split', 'e1', 2.)
        drive(state)
        self.assertEqual(state['time'], .85)
        state['stages'] = []
        drive(state)
        self.assertEqual(idle_heroes(state), ['h1'])
        self.assertEqual([e['actor'] for e in state['pending']].count('h1'), 0)

    def test_stun_interrupts_pending_cast_without_starting_attack_qte(self):
        state = new_session(dict(scenario='solo'))
        hp = state['fighters']['e1']['hp']
        schedule(state, 'h1', 'assassin_cut', 'e1', .85)
        state['fighters']['h1']['effects'].append(dict(kind='stun', value=1, duration=1))
        drive(state)
        self.assertFalse(state['stages'])
        self.assertEqual(state['fighters']['e1']['hp'], hp)
        self.assertIn('ошеломление', state['log'][0]['text'])
        self.assertEqual(idle_heroes(state), ['h1'])


class ReviewApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_local_session_cost_reservation_qte_and_duplicate_rejection(self):
        response = await self.client.post('/queue-review/session', json=dict(scenario='sync', class_id='assassin'))
        self.assertEqual(response.status, 200)
        state = await response.json()
        token = state['token']
        hp = state['fighters']['e1']['hp']
        payload = dict(action='skill', actor='h1', skill='assassin_cut', target='e1', revision=0)
        response = await self.client.post('/queue-review/session/' + token, json=payload)
        self.assertEqual(response.status, 200)
        state = await response.json()
        self.assertEqual(state['fighters']['h1']['resource'], 92)
        self.assertEqual(state['fighters']['e1']['hp'], hp)
        self.assertEqual(state['stage']['kind'], 'attack')
        duplicate = await self.client.post('/queue-review/session/' + token, json=payload)
        self.assertEqual(duplicate.status, 400)
        response = await self.client.post('/queue-review/session/' + token, json=dict(
            action='qte', revision=1, challenge_id=state['stage']['id'], proof=dict(abort=True)))
        self.assertEqual(response.status, 200)
        state = await response.json()
        self.assertEqual(state['idle'], ['h1'])
        self.assertEqual(state['fighters']['e1']['hp'], hp)
        self.assertFalse(any(e['actor'] == 'h1' for e in state['pending']))


if __name__ == '__main__':
    unittest.main()
