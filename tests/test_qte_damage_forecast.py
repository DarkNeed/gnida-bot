from copy import deepcopy
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import unittest

from arena_qte_combined import combine, replay
from arena_qte_live import challenge
from arena_raid_engine import BOSS_SKILLS, native_attack
from test_unified_live import SKILLS, raid


class DamageForecastTests(unittest.TestCase):
    def test_mixed_damage_forecasts_use_separate_defenses_and_native_weights(self):
        data = raid('kit')
        boss, target = data['boss'], data['players']['10']['fighter']
        target['hp'] = target['stats']['max_hp'] = 1000
        target['stats'].update(physical_defense=500, magic_defense=0)
        original = deepcopy(data)
        skill = BOSS_SKILLS['kit_reflection']
        stage = challenge('defense', boss, target, skill, 10, skills=SKILLS)
        self.assertEqual(data, original)
        self.assertEqual(stage['subskills'], ['kit_reflection', 'kit_ash'])
        physical, magic = stage['strike_damage_bases']
        self.assertGreater(magic, physical * 4)
        data.update(_qte_boss_phase=True, intent={'skill': skill.skill_id})
        target['_qte_guard'] = dict(skill=skill.skill_id, dodge=[False, False],
                                    subskills=stage['subskills'], pattern_dodge=dict(
                                        contacts=[dict(strike=i, weight=1) for i in range(2)]))
        for sid, expected in zip(stage['subskills'], (physical, magic)):
            with self.subTest(skill=sid):
                event = native_attack(deepcopy(boss), target, sid, BOSS_SKILLS,
                                      random.Random(0), tick_actor_bleed=False, raid_context=data)
                self.assertEqual(event['damage'], expected)

    @staticmethod
    def block_members(*sources):
        data = raid('kit')
        boss, target = data['boss'], data['players']['10']['fighter']
        target['defense_mode'] = 'block'
        return [dict(challenge('defense', boss, target, BOSS_SKILLS['kit_reflection'], 10, skills=SKILLS),
                     encounter_enemy=source, seed=42 + i)
                for i, source in enumerate(sources)]

    @staticmethod
    def trace(stage, proof):
        return json.loads(subprocess.check_output(
            ['node', 'tests/qte_combined_trace.cjs'], cwd=Path(__file__).resolve().parents[1],
            input=json.dumps(dict(stage=stage, proof=proof, withDamage=True)).encode()))

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_browser_block_uses_the_damage_for_each_individual_component(self):
        member, = self.block_members('boss')
        member.update(damage_base=7, strike_damage_bases=[7, 80])
        stage = combine([member], 10, 1000)
        proof = dict(ticks=math.ceil(stage['duration'] * 120 - 1e-7), inputs=[])
        totals = [0, 0]
        for contact in self.trace(stage, proof)['boss']:
            totals[contact['strike']] += contact['damage']
        expected = [0., 0.]
        for contact in replay(stage, proof, 99)['sources']['boss']['pattern_dodge']['contacts']:
            strike = contact['strike']
            expected[strike] += contact['weight'] * member['strike_damage_bases'][strike]
        self.assertGreater(min(totals), 0)
        self.assertEqual(totals, [math.floor(n + .5) for n in expected])

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_joint_block_filters_failed_strikes_per_attacker_not_per_shield(self):
        first, second = self.block_members('one', 'two')
        first['enabled_strikes'] = [False, True]
        second['enabled_strikes'] = [True, False]
        stage = combine([first, second], 10, 1000)
        proof = dict(ticks=math.ceil(stage['duration'] * 120 - 1e-7), inputs=[])
        client = self.trace(stage, proof)
        server = replay(stage, proof, 99)['sources']
        for source, active_strike in [('one', 1), ('two', 0)]:
            self.assertEqual({c['strike'] for c in client[source]}, {active_strike})
            self.assertEqual({c['strike'] for c in server[source]['pattern_dodge']['contacts']}, {active_strike})
