from copy import deepcopy
import math
from pathlib import Path
import shutil
import subprocess
import unittest
import json

from arena_qte_block import create, step, replay
from arena_qte_unique import review_catalog
from arena_chaplain_block import identity


class ChaplainBlockTests(unittest.TestCase):
    def skills(self):
        return [s for s in review_catalog() if identity({'skill': s}) is not None]

    def config(self, skill, **changes):
        return dict(version=3, kind='defense', defense_mode='block', profile=skill, seed=23,
            stats=dict(physicalDefense=35, magicDefense=35, enemyAttack=30, enemyAccuracy=100), **changes)

    def test_all_twelve_attacks_have_distinct_timed_scores_and_tells(self):
        skills = self.skills()
        self.assertEqual(len(skills), 12)
        signatures = set()
        for skill in skills:
            s = create(self.config(skill))
            events = s['events']
            signatures.add(json.dumps(events, sort_keys=True))
            self.assertGreaterEqual(len(events), 8, skill['name'])
            for e in events:
                self.assertGreaterEqual(e['at']-e['warning'], 1)
                self.assertGreaterEqual(e['warning'], .68)
                self.assertLess(e['at'], 9.5)
                self.assertIn(e['motif'], ('hand','bell','cut','window','denied','stamp','echo','delete','clock','light','admin'))
            for first, second in zip(events, events[1:]):
                self.assertGreaterEqual(second['at']-first['at'], .39)
            damaging = [e for e in events if e['weight'] > 0]
            for first, second in zip(damaging, damaging[1:]):
                self.assertGreaterEqual(second['at']-first['at'], .47)
        self.assertEqual(len(signatures), 12)

    def test_light_final_has_only_four_major_flashes_and_four_small_echoes(self):
        skill = next(s for s in self.skills() if s['base_id'] == 'chaplain_p4_1')
        events = create(self.config(skill))['events']
        self.assertEqual(sum(e['kind'] == 'wave' for e in events), 4)
        self.assertEqual(sum(e['weight'] == .1 for e in events), 4)
        self.assertFalse(any(e['kind'] == 'feint' for e in events))

    def test_low_accuracy_and_extra_warning_do_not_overlap_preparation_or_end(self):
        for skill in self.skills():
            c = self.config(skill)
            c['stats'].update(enemyAccuracy=0, extraWarning=.15)
            for event in create(c)['events']:
                self.assertGreaterEqual(event['at']-event['warning'], 1, skill['name'])
                self.assertLess(event['at'], 9.5, skill['name'])

    def test_denied_request_only_consumes_guard_never_hp_or_block_credit(self):
        skill = next(s for s in self.skills() if s['base_id'] == 'chaplain_p2_1')
        initial = create(self.config(skill))
        feint = next(e for e in initial['events'] if e['kind'] == 'feint')
        initial['events'] = [deepcopy(feint)]
        held, lowered = deepcopy(initial), deepcopy(initial)
        for _ in range(math.ceil(feint['at']*120)+1):
            step(held, dict(active=True, angle=feint['angle']))
            step(lowered, dict(active=False, angle=feint['angle']))
        for s in (held, lowered):
            self.assertEqual(len(s['contacts']), 1)
            contact = s['contacts'][0]
            self.assertEqual(contact['weight'], 0)
            self.assertFalse(contact['blocked'])
            self.assertEqual(contact['outcome'], 'feint')
        self.assertGreater(lowered['stamina']-held['stamina'], 10)
        aborted = replay(self.config(skill), {'abort': True}, 0)
        fake_ids = {e['id'] for e in create(self.config(skill))['events'] if e['kind'] == 'feint'}
        self.assertTrue(all(c['weight'] == 0 for c in aborted['contacts'] if c['id'] in fake_ids))

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_every_pattern_renders_at_phone_width(self):
        rendered = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('chaplain_block_view.cjs'))],
            input=json.dumps(self.skills()), text=True, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(rendered.returncode, 0, rendered.stdout+rendered.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_all_scores_have_clean_routes_and_js_matches_authoritative_replay(self):
        configs = []
        for skill in self.skills():
            for seed in (17, 29):
                for armor in (0, 60):
                    for policy in ('careful', 'hold'):
                        c = self.config(skill, policy=policy)
                        c['seed'] = seed
                        c['stats'].update(physicalDefense=armor, magicDefense=armor)
                        configs.append(c)
        traces = subprocess.run([shutil.which('node'), str(Path(__file__).with_name('qte_block_trace.cjs'))],
            input=json.dumps(configs), text=True, capture_output=True, encoding='utf-8', timeout=90)
        self.assertEqual(traces.returncode, 0, traces.stderr)
        for c, trace in zip(configs, json.loads(traces.stdout), strict=True):
            result = replay(c, trace['proof'], 20)
            self.assertEqual(result['mask'], trace['result']['mask'], c['profile']['name'])
            for actual, expected in zip(result['contacts'], trace['result']['contacts'], strict=True):
                for key in ('id', 'strike', 'tier', 'outcome', 'blocked', 'tick'):
                    self.assertEqual(actual[key], expected[key], (c['profile']['name'], c['policy']))
                self.assertAlmostEqual(actual['weight'], expected['weight'], places=9)
            if c['policy'] == 'careful':
                self.assertTrue(all(e['weight'] == 0 for e in result['contacts']), c['profile']['name'])


if __name__ == '__main__':
    unittest.main()
