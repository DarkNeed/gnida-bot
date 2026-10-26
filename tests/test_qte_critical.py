"""Server-verified timing crits, independent native strikes and intact defenses."""
from dataclasses import replace
import json
import math
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from arena_engine import BUILTIN_SKILLS, create_battle_state, resolve_skill
from arena_qte_patterns import attack, attack_frame, duration, profile
from arena_qte_rules import replay
from arena_qte_unique import review_catalog
from test_arena_rebalance import FixedRoll


class TimingCriticalTests(unittest.TestCase):
    def challenge(self, skill=None):
        skill = skill or next(s for s in review_catalog() if s['base_id'] == 'bum_punch')
        return dict(version=2, kind='attack', profile=skill, seed=17,
                    stats=dict(accuracy=75, enemyEvasion=25, enemyAccuracy=75, evasion=25))

    def proof(self, c, critical=True):
        s = attack(profile(c['profile']), c['stats'], c['seed'])
        ticks = math.ceil(duration(c) * 120 - 1e-7)
        clicks = []
        seen = set()
        for tick in range(ticks):
            s['time'] = tick / 120
            f = attack_frame(s)
            distance = abs(f['cursor'] - f['center'])
            good = (distance < f['criticalWidth'] / 3 if critical else
                    f['width'] * .2 < distance < f['width'] * .4)
            if f['canHit'] and good and f['index'] not in seen:
                clicks.append(tick)
                seen.add(f['index'])
        self.assertEqual(len(clicks), s['p']['strikes'])
        return dict(ticks=ticks, clicks=clicks)

    def state(self):
        s = create_battle_state(
            dict(owner_id=10, slave_id=10, class_id='ragamuffin', level=3),
            dict(owner_id=20, slave_id=20, class_id='ragamuffin', level=3),
        )
        s['active_side'] = 'a'
        for side in s['sides'].values():
            side['hp'] = side['stats']['max_hp'] = 100000
        return s

    def event(self, criticals, *, state=None, skill=None, **guard):
        return resolve_skill(state or self.state(), 'a', 'bum_punch',
                             {**BUILTIN_SKILLS, 'bum_punch': skill or BUILTIN_SKILLS['bum_punch']},
                             FixedRoll(.5), qte=dict(attack=[True] * len(criticals),
                                                    pattern_attack=dict(criticals=criticals), **guard))

    def test_server_distinguishes_hit_and_crit_without_accepting_client_flags(self):
        c = self.challenge()
        for desired in (False, True):
            proof = self.proof(c, desired)
            proof['criticals'] = [not desired]  # Deliberately forged, ignored.
            result = replay(c, proof, 60)
            self.assertEqual(result['mask'], [True])
            self.assertEqual(result['criticals'], [desired])
            self.assertEqual(result['weights'], [1])
        self.assertEqual(replay(c, dict(abort=True, criticals=[True]), 60)['criticals'], [False])

    def test_one_attempt_still_applies_to_critical_mark(self):
        c = self.challenge()
        first = self.proof(c, False)['clicks'][0]
        second = self.proof(c, True)['clicks'][0]
        self.assertLess(first, second)
        with self.assertRaises(ValueError):
            replay(c, dict(ticks=math.ceil(duration(c)*120), clicks=[first, second]), 60)

    def test_damage_gets_existing_critical_multiplier(self):
        normal, critical = self.event([False]), self.event([True])
        self.assertFalse(normal['critical'])
        self.assertTrue(critical['critical'])
        self.assertEqual(critical['damage'], round(normal['damage'] * 1.5))
        self.assertIn('критический удар', critical['text'])

    def test_independent_criticals_do_not_boost_other_native_strikes(self):
        skill = replace(BUILTIN_SKILLS['bum_punch'], power=100, tags=('six_strike',))
        normal = self.event([False]*6, skill=skill)
        critical = self.event([False, True, False, False, False, True], skill=skill)
        self.assertEqual(critical['hits'], [round(v * (1.5 if i in (1, 5) else 1))
                                          for i, v in enumerate(normal['hits'])])
        self.assertEqual([p['critical'] for p in critical['hit_results']],
                         [False, True, False, False, False, True])

    def test_critical_does_not_stack_or_override_skill_restrictions(self):
        with patch('arena_engine.combat_modifiers', return_value=(0, 0, 0, True, False)):
            self.assertEqual(self.event([False])['damage'], self.event([True])['damage'])
        skill = replace(BUILTIN_SKILLS['bum_punch'], tags=('no_critical',))
        normal, critical = self.event([False], skill=skill), self.event([True], skill=skill)
        self.assertEqual(normal['damage'], critical['damage'])
        self.assertFalse(critical['critical'])

    def test_successful_dodge_and_perfect_block_cancel_crit(self):
        for block in (False, True):
            guard = dict(dodge=[True])
            if block:
                guard['pattern_dodge'] = dict(mode='block', contacts=[])
            e = self.event([True], **guard)
            self.assertEqual(e['damage'], 0)
            self.assertFalse(e['critical'])
        npc = self.state()
        npc['sides']['b'].update(controller_id=0)
        npc['sides']['b']['stats']['evasion'] = 95
        e = self.event([True], state=npc)
        self.assertTrue(e['dodged'])
        self.assertEqual(e['damage'], 0)

    def test_partial_block_and_weighted_contacts_still_work(self):
        for mode in ('block', 'dodge'):
            guard = dict(dodge=[False], pattern_dodge=dict(mode=mode, contacts=[
                dict(strike=0, weight=.25, id='test', tick=120, tier='normal')]))
            normal, critical = self.event([False], **guard), self.event([True], **guard)
            self.assertAlmostEqual(critical['damage'], normal['damage']*1.5, delta=1)
            self.assertTrue(critical['critical'])

    def test_casino_non_damage_and_no_critical_have_no_small_zone(self):
        catalog = review_catalog()
        for skill in catalog:
            p = profile(skill)
            frame = attack_frame(attack(p, self.challenge()['stats'], 17))
            if p['kind'].startswith('casino_') or not skill['damage_type'] or 'no_critical' in skill['tags']:
                self.assertEqual(frame['criticalWidth'], 0, skill['name'])
            else:
                self.assertAlmostEqual(frame['criticalWidth'], frame['width']*.2)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_browser_damage_feedback_and_spectator_forecasts(self):
        result = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('qte_critical.cjs'))],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_javascript_matches_authoritative_criticals_for_every_timing_style(self):
        chosen = {}
        for skill in review_catalog():
            p = profile(skill)
            if not p['kind'].startswith('casino_') and skill['damage_type'] and 'no_critical' not in skill['tags']:
                chosen.setdefault(p['style'], skill)
        configs = [dict(self.challenge(skill), critical_aim=True) for skill in chosen.values()]
        result = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('qte_patterns_trace.cjs'))],
                                input=json.dumps(configs), capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for c, trace in zip(configs, json.loads(result.stdout), strict=True):
            verified = replay(c, trace['proof'], 60)
            self.assertTrue(all(verified['criticals']), c['profile']['name'])
            self.assertEqual(verified, trace['result'])


if __name__ == '__main__':
    unittest.main()
