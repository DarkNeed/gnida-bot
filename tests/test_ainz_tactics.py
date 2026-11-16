"""Real phase openings and authoritative analytic-path parity."""
from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess
import unittest

from test_ainz_phases import encounter
from arena_ainz_phases import configure
from arena_ainz_tactics import before_player, after_player, after_boss, clean_guard
from arena_engine import BUILTIN_SKILLS
from arena_nazarick import SKILLS, set_intent, summon, contact_afflictions
from arena_qte_patterns import profile, difficulty, geometry
from arena_ainz_patterns import shapes
from arena_raid_engine import native_attack


class AinzTacticsTests(unittest.TestCase):
    def test_combined_defense_keeps_each_source_separate(self):
        sid='nz_ainz6_p2_0';f=encounter()['players']['10']['fighter']
        guard=dict(subskills=[sid,'nz_knight_p1_0'],pattern_dodge=dict(contacts=[
            dict(strike=1,status='curse',weight=.4,reduction=0),
            dict(strike=0,status='bleed',weight=.4,reduction=1)]))
        self.assertTrue(clean_guard(guard,sid))
        self.assertFalse(clean_guard(guard,'missing'))
        self.assertEqual(contact_afflictions(f,sid,dict(hit=True,damage=1),guard),[])
        guard['pattern_dodge']['contacts'][1]['reduction']=0
        self.assertFalse(clean_guard(guard,sid))
        contact_afflictions(f,sid,dict(hit=True,damage=1),guard)
        self.assertEqual({e['kind'] for e in f['effects']},{'bleed'})

    def test_summon_link_only_opens_after_both_helpers_die(self):
        d=encounter();set_intent(d)
        self.assertNotIn('ainz_link_broken',{e['id'] for e in d['boss']['effects']})
        d['round']=d['nazarick']['next_summon'];summon(d);set_intent(d)
        d['enemies']['boss_lich']['hp']=0;set_intent(d)
        self.assertNotIn('ainz_link_broken',{e['id'] for e in d['boss']['effects']})
        d['enemies']['boss_knight']['hp']=0;set_intent(d)
        self.assertEqual(next(e['value'] for e in d['boss']['effects'] if e['id']=='ainz_link_broken'),.25)
        d['round']=d['nazarick']['next_summon'];summon(d);set_intent(d)
        self.assertIn('ainz_link_broken',{e['id'] for e in d['boss']['effects']})
        d['boss']['own_turns']=d['nazarick']['ainz_summon_ready'];summon(d);set_intent(d)
        self.assertNotIn('ainz_link_broken',{e['id'] for e in d['boss']['effects']})

    def test_clean_defense_and_heavy_recovery_have_limited_openings(self):
        for phase,hits,value,clean in [(2,1,.30,True),(3,2,.20,True),(4,2,.40,False),(6,2,.20,False)]:
            d=encounter(phase);intent=dict(skill=f'nz_ainz6_p{phase}_3')
            if phase in (2,3):
                after_boss(d,intent,False)
                self.assertFalse(d['nazarick'].get('ainz_opening_hits'))
            after_boss(d,intent,clean)
            self.assertEqual(d['nazarick']['ainz_opening_hits'],hits)
            self.assertEqual(next(e['value'] for e in d['boss']['effects'] if e['id']=='ainz_form_opening'),value)
            after_player(d,BUILTIN_SKILLS['mana_shot'],dict(damage=0))
            self.assertEqual(d['nazarick']['ainz_opening_hits'],hits)
            for _ in range(hits):after_player(d,BUILTIN_SKILLS['mana_shot'],dict(damage=1))
            self.assertNotIn('ainz_form_opening',{e['id'] for e in d['boss']['effects']})

    def test_opening_modifies_real_damage(self):
        d=encounter(4);a=deepcopy(d['players']['10']['fighter']);boss=deepcopy(d['boss'])
        baseline=native_attack(deepcopy(a),boss,'mana_shot',BUILTIN_SKILLS,random.Random(5))['damage']
        after_boss(d,dict(skill='nz_ainz6_p4_0'))
        damage=native_attack(deepcopy(a),d['boss'],'mana_shot',BUILTIN_SKILLS,random.Random(5))['damage']
        self.assertGreater(damage,baseline)

    def test_white_armor_adapts_and_support_or_new_damage_type_breaks_it(self):
        for support in (True,False):
            d=encounter(5);magic=BUILTIN_SKILLS['mana_shot']
            physical=next(s for s in BUILTIN_SKILLS.values() if s.damage_type=='physical')
            after_player(d,magic,dict(damage=10));after_player(d,magic,dict(damage=10))
            effect=next(e for e in d['boss']['effects'] if e['id']=='ainz_form_adaptation')
            self.assertEqual((effect['kind'],effect['value']),('magic_defense_pct',.25))
            if support:before_player(d,'defend',BUILTIN_SKILLS)
            else:after_player(d,physical,dict(damage=10))
            self.assertNotIn('ainz_form_adaptation',{e['id'] for e in d['boss']['effects']})
            self.assertEqual(d['nazarick']['ainz_opening_hits'],1)
            self.assertEqual(d['nazarick']['ainz_damage_streak'],0 if support else 1)

    def test_weakened_ritual_opens_boss_and_transition_clears_form_state(self):
        d=encounter(6);after_boss(d,dict(skill='nz_ainz6_p6_1'),ritual_weakened=False)
        self.assertFalse(d['nazarick'].get('ainz_opening_hits'))
        after_boss(d,dict(skill='nz_ainz6_p6_1'),ritual_weakened=True)
        self.assertEqual(d['nazarick']['ainz_opening_hits'],2)
        d['nazarick'].update(ainz_damage_streak=2,ainz_last_damage_type='magic',ainz_summoned=True)
        configure(d)
        self.assertFalse(any(k in d['nazarick'] for k in ('ainz_opening_hits','ainz_damage_streak','ainz_last_damage_type','ainz_summoned')))
        self.assertNotIn('ainz_form_opening',{e['id'] for e in d['boss']['effects']})

    def test_curved_and_frozen_geometry_matches_browser_at_all_sample_times(self):
        fixtures=[];paths=set()
        for sid,skill in SKILLS.items():
            if not sid.startswith('nz_ainz6_'):continue
            p=profile(dict(id=sid,base_id=sid,name=skill.name,class_id='raid',damage_type=skill.damage_type))
            state=dict(p=p,d=difficulty(dict(accuracy=100,enemyEvasion=0,enemyAccuracy=100,evasion=0)),
                       player=dict(x=335,y=173),preparation=1)
            for index in (0,1,3,6):
                for h in shapes(state,dict(index=index,jitter=.35,at=1.18)):
                    if not h.get('ainzPath'):continue
                    paths.add(h['ainzPath']);h['start']=1.18+h['delay']+state['d']['warning']
                    for age in (0,.1,.5,1,1.4,2,3,4.5):fixtures.append(dict(h=h,t=h['start']+age))
        self.assertEqual(paths,{'bezier','wave','orbitLaunch','sealDrift','driftRect','sweepLine','ricochet','slidePolyline'})
        script="const E=require('./webapp/qte-unique/engine');let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(f=>{const g=E.geometry(f.h,f.t);return[g.x,g.y,g.vx??null,g.vy??null]}))));"
        actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        for f,a in zip(fixtures,actual):
            g=geometry(f['h'],f['t'])
            for value,want in zip((g.get(k) for k in ('x','y','vx','vy')),a):
                if value is None:self.assertIsNone(want)
                else:self.assertAlmostEqual(value,want,places=7)

    def test_all_damaging_actions_replay_dodge_and_block_with_server_contacts(self):
        from arena_qte_patterns import replay
        from arena_qte_block import replay as block_replay
        fixtures=[]
        for sid,skill in SKILLS.items():
            if not sid.startswith('nz_ainz6_') or not skill.damage_type:continue
            fixtures.append(dict(profile=dict(id=sid,base_id=sid,name=skill.name,class_id='raid',strikes=1,damage_type=skill.damage_type),
                kind='defense',seed=81,defense_preparation=1,
                stats=dict(accuracy=100,enemyEvasion=0,enemyAccuracy=100,evasion=0,physicalDefense=20,magicDefense=20,enemyAttack=30),
                policy='sweep'))
        root=Path(__file__).resolve().parents[1]
        for script,check in [('qte_patterns_trace.cjs',replay),('qte_block_trace.cjs',block_replay)]:
            for c in fixtures:c['defense_mode']='block' if script=='qte_block_trace.cjs' else 'dodge'
            traces=json.loads(subprocess.check_output(['node','tests/'+script],input=json.dumps(fixtures).encode(),cwd=root))
            for c,trace in zip(fixtures,traces):
                with self.subTest(skill=c['profile']['base_id'],mode=script):
                    self.assertEqual(check(c,trace['proof'],30),trace['result'])
