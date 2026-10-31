import math
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from arena_qte_patterns import defense, geometry, prepare, profile, touches, replay
from arena_qte_unique import review_catalog


class ChaplainPatternTests(unittest.TestCase):
    def model(self, ident, **stats):
        skill = next(s for s in review_catalog() if s['base_id'] == ident)
        return defense(profile(deepcopy(skill)), dict(accuracy=75, enemyEvasion=25, enemyAccuracy=100, evasion=0, **stats), 23)

    def test_last_phase_light_has_four_spaced_waves_and_wider_safe_corridor(self):
        s = self.model('chaplain_p4_1')
        self.assertEqual(len(s['events']), 4)
        self.assertGreaterEqual(s['d']['warning'], .65)
        self.assertGreater(s['events'][1]['at']-s['events'][0]['at'], 1)
        for i, event in enumerate(s['events']):
            before = len(s['hazards'])
            prepare(s, event)
            hazards = s['hazards'][before:]
            upper, lower = hazards[:2]
            self.assertGreaterEqual(lower['y']-upper['h'], 120)
            # A normal horizontal position is already in the safe corridor;
            # moving vertically is no longer mandatory before every flash.
            self.assertLess(upper['h'], s['player']['y']-s['player']['r'])
            self.assertGreater(lower['y'], s['player']['y']+s['player']['r'])
            self.assertEqual(len(hazards), 3 if i % 2 else 2)
            if i % 2:
                self.assertAlmostEqual(hazards[2]['start']-upper['start'], .58)

    def test_clock_hands_rotate_about_visible_dial_and_collision_follows(self):
        s = self.model('chaplain_p2_0')
        prepare(s, s['events'][0])
        self.assertEqual(len(s['hazards']), 2)
        for h in s['hazards']:
            self.assertEqual(h['motif'], 'clock_hand')
            self.assertEqual((h['ax'], h['ay']), (600, 155))
            start, end = geometry(h, h['start']), geometry(h, h['end'])
            self.assertNotEqual((start['bx'], start['by']), (end['bx'], end['by']))
            self.assertAlmostEqual(math.hypot(start['bx']-600, start['by']-155),
                                   math.hypot(end['bx']-600, end['by']-155))
            point = dict(x=600+(end['bx']-600)*.5, y=155+(end['by']-155)*.5, r=1)
            self.assertTrue(touches(h, point, point, h['end'], 0))
            self.assertFalse(touches(h, point, point, h['start'], 0))

    def test_final_clock_hand_still_matches_dial(self):
        s = self.model('chaplain_p4_0')
        prepare(s, s['events'][0])
        hand = next(h for h in s['hazards'] if h.get('clockTurn'))
        self.assertEqual((hand['ax'], hand['ay']), (600, 155))
        self.assertAlmostEqual(hand['end']-hand['start'], .30)

    def test_first_phase_vertical_beam_reaches_both_edges_only_for_chaplain(self):
        for x,index,expected in ((12,0,0),(708,1,720)):
            s=self.model('chaplain_hand');s['player'].update(x=x,y=210)
            event=dict(s['events'][0],index=index)
            prepare(s,event)
            beam=s['hazards'][0]
            self.assertEqual(beam['ax'],expected)
            self.assertTrue(touches(beam,s['player'],s['player'],beam['start']+.01,0))
            s=self.model('chaplain_hand');s['p']['skill']['base_id']='unrelated_coin_attack'
            s['player'].update(x=x,y=210);prepare(s,event)
            self.assertEqual(s['hazards'][0]['ax'],80 if x==12 else 640)

    @unittest.skipUnless(shutil.which('node'),'Node required for server/client parity')
    def test_first_phase_beam_server_replays_browser_inputs_identically(self):
        skill=next(deepcopy(s) for s in review_catalog() if s['base_id']=='chaplain_hand')
        case=dict(version=2,kind='defense',profile=skill,seed=23,strikes=skill['strikes'],defense_preparation=1,
                  stats=dict(accuracy=75,enemyEvasion=25,enemyAccuracy=100,evasion=0))
        result=subprocess.run(['node','tests/qte_patterns_trace.cjs'],cwd=Path(__file__).resolve().parents[1],
                              input=json.dumps([case]),text=True,encoding='utf-8',capture_output=True,check=True)
        trace=json.loads(result.stdout)[0]
        self.assertEqual(replay(case,trace['proof'],20),trace['result'])


if __name__ == '__main__':
    unittest.main()
