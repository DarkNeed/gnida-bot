"""Reachability is necessary, not a claim about real human completion rates."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import unittest

from arena_guild_patterns import FAMILIES, block_threats
from arena_qte_block import parameters
from arena_qte_patterns import profile, defense, prepare, attack
from arena_qte_rules import replay
from arena_qte_unique import review_catalog

ROOT=Path(__file__).resolve().parents[1]
HARD=dict(accuracy=100,enemyEvasion=0,enemyAccuracy=100,evasion=0)


def skills():
    # Highest native rank for every one of the thirty monster moves.
    return {s['base_id']:s for s in sorted(review_catalog(),key=lambda s:s.get('npc_tier',0))
            if s.get('monster_pattern')==3}


class MonsterDodgeTests(unittest.TestCase):
    def test_tells_and_wave_spacing_leave_reaction_time_at_worst_stats(self):
        self.assertEqual({sid[6:] for sid in skills()},set(FAMILIES))
        for skill in skills().values():
            for tier in range(5):
                s=defense(profile(dict(skill,npc_tier=tier)),HARD,17)
                with self.subTest(skill=skill['base_id'],tier=tier):
                    self.assertGreaterEqual(s['d']['warning'],.55)
                    self.assertLessEqual(s['d']['speed'],595)
                    self.assertLessEqual(s['d']['lead'],.061)
                    self.assertIn(len(s['events']),(4,5))
                    self.assertTrue(all(b['at']-a['at']>=.95 for a,b in zip(s['events'],s['events'][1:])))

    def test_stats_and_rank_still_matter_and_preparation_is_preserved(self):
        for skill in skills().values():
            hard=defense(profile(dict(skill,npc_tier=4)),HARD,17)
            easy=defense(profile(dict(skill,npc_tier=4)),dict(HARD,enemyAccuracy=60,evasion=70),17)
            low=defense(profile(dict(skill,npc_tier=0)),HARD,17)
            self.assertGreater(hard['d']['speed'],easy['d']['speed'])
            self.assertLess(hard['d']['warning'],easy['d']['warning'])
            self.assertGreater(hard['d']['speed'],low['d']['speed'])
            self.assertGreater(len(hard['events']),len(low['events']))
            self.assertEqual(hard['d']['moveSpeed'],easy['d']['moveSpeed'])
            self.assertEqual(hard['preparation'],1)

    def test_ice_opening_is_nearby_and_ring_exit_never_points_out_of_a_wall(self):
        for seed in range(20):
            for sid in ('guild_ice','guild_ice_tomb'):
                for x in (12,230,708):
                    s=defense(profile(skills()[sid]),HARD,seed);s['player'].update(x=x,y=160)
                    prepare(s,s['events'][0])
                    bullets=[h for h in s['hazards'] if h['type']=='bullet']
                    self.assertTrue(any(abs(x-h['x'])<=h['r']+6 for h in bullets),
                                    'Ice still requires movement, including at the arena edges')
                    # Some reachable horizontal position has room for the full
                    # hitbox, including a margin for imprecise touch movement.
                    reachable=192*(s['d']['warning']-.20)
                    self.assertTrue(any(all(abs(px-h['x'])>h['r']+16 for h in bullets)
                                        for px in range(max(12,math.ceil(x-reachable)),min(708,math.floor(x+reachable))+1)))
            for x,y in ((12,12),(708,12),(12,308),(708,308)):
                s=defense(profile(skills()['guild_smash']),HARD,seed);s['player'].update(x=x,y=y)
                prepare(s,s['events'][0]);ring=next(h for h in s['hazards'] if h['type']=='ring')
                self.assertGreater(math.cos(ring['gap'])*(360-x)+math.sin(ring['gap'])*(160-y),0)

    def test_saved_version_two_challenges_keep_their_parameters_and_geometry(self):
        new=skills()['guild_smash'];old=dict(new,monster_pattern=2,npc_tier=4)
        legacy=defense(profile(old),HARD,17);modern=defense(profile(dict(new,npc_tier=4)),HARD,17)
        self.assertAlmostEqual(legacy['d']['speed'],930)
        self.assertAlmostEqual(legacy['d']['warning'],.40)
        prepare(legacy,legacy['events'][0]);prepare(modern,modern['events'][0])
        self.assertEqual(next(h for h in legacy['hazards'] if h['type']=='ring')['speed'],200)
        self.assertEqual(next(h for h in modern['hazards'] if h['type']=='ring')['speed'],175)

    def test_block_and_attack_checks_are_not_rebalanced(self):
        for skill in skills().values():
            p=profile(skill);old=profile(dict(skill,monster_pattern=2))
            a,b=attack(p,HARD,17),attack(old,HARD,17);a.pop('p');b.pop('p')
            self.assertEqual(a,b)
            stats=dict(physicalDefense=20,magicDefense=20,enemyAttack=42,enemyAccuracy=98)
            self.assertEqual(block_threats(p,17,parameters(p,stats)),block_threats(old,17,parameters(old,stats)))

    def test_class_npcs_get_bounded_pressure_without_changing_player_patterns(self):
        for sid in ('warning_shot','first_line','falling_star','mana_shot','armor_split','hunter_shot'):
            skill=next(s for s in review_catalog() if s['base_id']==sid)
            old=defense(profile(dict(skill,npc_tier=4)),HARD,17)
            modern=defense(profile(dict(skill,npc_tier=4,npc_pattern=2)),HARD,17)
            self.assertGreaterEqual(modern['d']['warning'],.5)
            self.assertLess(modern['d']['speed'],old['d']['speed'])
            self.assertLess(modern['d']['lead'],old['d']['lead'])
            self.assertLessEqual(len(modern['events']),7)
            self.assertTrue(all(b['at']-a['at']>=.71 for a,b in zip(modern['events'],modern['events'][1:])))
            human=defense(profile(skill),HARD,17)
            unchanged=defense(profile(dict(skill,npc_tier=0,npc_pattern=2)),HARD,17)
            self.assertEqual(human['d'],unchanged['d'])
            self.assertEqual(human['events'],unchanged['events'])

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_class_npc_routes_and_server_replay(self):
        cases=[]
        for sid in ('warning_shot','first_line','falling_star','mana_shot','armor_split','hunter_shot'):
            skill=next(s for s in review_catalog() if s['base_id']==sid)
            cases.append(dict(version=2,kind='defense',profile=dict(skill,npc_tier=4,npc_pattern=2),
                stats=dict(HARD,controlScale=.8),seed=17,strikes=skill['strikes'],defense_preparation=1,perfect=True))
        traces=json.loads(subprocess.run(['node','tests/qte_patterns_trace.cjs'],cwd=ROOT,input=json.dumps(cases),
            capture_output=True,text=True,encoding='utf-8',check=True,timeout=120).stdout)
        for c,trace in zip(cases,traces,strict=True):
            self.assertEqual(trace['result']['contacts'],[])
            self.assertEqual(replay(c,trace['proof'],30),trace['result'])

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_every_monster_move_has_clean_paths_with_zero_evasion(self):
        cases=[dict(version=2,kind='defense',profile=s,stats=dict(HARD,controlScale=.8),seed=seed,
                    strikes=s['strikes'],defense_preparation=1,perfect=True)
               for s in skills().values() for seed in (17,89)]
        traces=json.loads(subprocess.run(['node','tests/qte_patterns_trace.cjs'],cwd=ROOT,input=json.dumps(cases),
            capture_output=True,text=True,encoding='utf-8',check=True,timeout=240).stdout)
        for c,trace in zip(cases,traces,strict=True):
            with self.subTest(skill=c['profile']['base_id'],seed=c['seed']):
                self.assertEqual(trace['result']['contacts'],[])
                self.assertEqual(replay(c,trace['proof'],30),trace['result'])

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_delayed_reaction_probe_is_viable_and_identical_on_server(self):
        cases=[dict(skill=s,stats=dict(HARD,controlScale=.8),seed=seed)
               for s in skills().values() for seed in (17,89,323)]
        traces=json.loads(subprocess.run(['node','tests/monster_dodge.cjs'],cwd=ROOT,input=json.dumps(cases),
            capture_output=True,text=True,encoding='utf-8',check=True,timeout=180).stdout)
        self.assertGreaterEqual(sum(not t['hits'] for t in traces),len(traces)*.8)
        self.assertLessEqual(max(t['weight'] for t in traces),1.2)
        for c,trace in zip(cases,traces,strict=True):
            config=dict(version=2,kind='defense',profile=c['skill'],seed=c['seed'],stats=c['stats'],
                        strikes=c['skill']['strikes'],defense_preparation=1)
            with self.subTest(skill=c['skill']['base_id'],seed=c['seed']):
                self.assertEqual(replay(config,trace['proof'],30)['contacts'],trace['contacts'])


if __name__=='__main__':unittest.main()
