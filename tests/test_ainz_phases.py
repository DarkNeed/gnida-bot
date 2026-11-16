from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess
import unittest

from arena_engine import BUILTIN_SKILLS,FIGHTER_CLASSES
from arena_raid_engine import create_raid_state
from arena_nazarick import load_stage,set_intent,progress,resolve,summon,presentation,contact_afflictions,SKILLS
from arena_ainz_phases import configure,PHASES,MOVES
from arena_nazarick_patterns import shapes,block_threats,active_duration,block_duration,schedule,time_stopped
from arena_qte_patterns import profile,difficulty
from arena_qte_block import parameters


def encounter(phase=1,size=1):
    members=[dict(actor_id=n,fighter_id=n,personal=True,slave_owner=n) for n in (10,20,30)[:size]]
    sources=[dict(owner_id=p['actor_id'],slave_id=p['actor_id'],class_id='mage',level=20,
        loadout=['mana_shot','mana_focus']) for p in members]
    d=create_raid_state(members,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,'nazarick')
    d['nazarick'].update(stage=4,phase=phase);load_stage(d)
    d['boss']['hp']=round(d['boss']['stats']['max_hp']*(7-phase)/6)
    return d


class AinzPhaseTests(unittest.TestCase):
    def test_six_real_health_barriers_and_final_victory(self):
        d=encounter();saved=deepcopy(d['players'])
        hp=d['boss']['stats']['max_hp']
        for phase in range(2,7):
            d['boss']['hp']=0
            self.assertTrue(progress(d))
            self.assertEqual(d['nazarick']['phase'],phase)
            self.assertEqual(d['boss']['hp'],round(hp*(7-phase)/6))
            self.assertFalse(d['finished'])
            self.assertFalse(progress(d))
            self.assertEqual(d['players'],saved)
        d['boss']['hp']=0;progress(d)
        self.assertTrue(d['finished']);self.assertTrue(d['won'])

    def test_legacy_snapshot_still_has_two_phases(self):
        d=encounter();d['nazarick'].pop('ainz_version');load_stage(d)
        self.assertEqual(d['boss']['stats']['max_hp'],1100)
        self.assertTrue(d['intent']['skill'].startswith('nz_ainz_p1'))
        d['boss']['hp']=0;progress(d)
        self.assertEqual(d['nazarick']['phase'],2)
        d['boss']['hp']=0;progress(d)
        self.assertTrue(d['finished'])

    def test_forms_summons_stats_casts_and_assets(self):
        d=encounter();d['round']=5;summon(d)
        self.assertEqual(len(d['enemies']),3)
        set_intent(d)
        self.assertIn('nz_boss_knight',{e['id'] for e in d['boss']['effects']})
        self.assertIn('nz_boss_lich',{e['id'] for e in d['boss']['effects']})
        d['enemies']['boss_lich']['hp']=0;set_intent(d)
        self.assertNotIn('nz_boss_lich',{e['id'] for e in d['boss']['effects']})
        d['nazarick']['phase']=2;configure(d);set_intent(d)
        self.assertEqual(list(d['enemies']),['boss'])
        self.assertEqual(d['boss']['resource'],0)
        self.assertTrue(all(SKILLS[s].damage_type=='physical' for s in d['boss']['loadout']))
        root=Path(__file__).resolve().parents[1]/'webapp'
        for phase in range(1,7):
            d=encounter(phase);v=presentation(d)
            self.assertEqual(v['phase_count'],6)
            self.assertTrue((root/v['sprite'].replace('/static/','')).is_file())
            self.assertEqual(bool(v['floating_staff']),phase==6)
            self.assertEqual(len(d['boss']['loadout']),4)
            self.assertEqual(len(d['boss']['passive_details']),2)
            self.assertTrue(all(k not in v for k in ('strength','weakness','advice')))
        self.assertGreater(encounter(4)['boss']['stats']['physical_attack'],encounter(2)['boss']['stats']['physical_attack'])
        self.assertGreater(SKILLS['nz_ainz6_p4_0'].cast_base,SKILLS['nz_ainz6_p2_0'].cast_base*2)

    def test_every_attack_really_executes_and_ritual_does_not_skip_staff(self):
        for phase in range(1,7):
            d=encounter(phase)
            for p in d['players'].values():p['fighter']['hp']=p['fighter']['stats']['max_hp']=100000
            for _ in range(10):
                set_intent(d)
                resolve(d,BUILTIN_SKILLS,random.Random(42),actor_keys=[],enemy_keys=['boss'],complete=False)
                d['round']+=1
            played={e.get('skill') for e in d['log']}
            expected={f'nz_ainz6_p{phase}_{move}' for move in range(4) if (phase,move)!=(1,2)}
            self.assertTrue(expected<=played,(phase,expected-played))
            self.assertFalse(d['finished'])

    def test_status_requires_actual_nonperfect_contact(self):
        f=encounter()['players']['10']['fighter'];hit=dict(hit=True,damage=10)
        guard=dict(pattern_dodge=dict(contacts=[dict(status='bleed',weight=.3,reduction=1)]))
        self.assertEqual(contact_afflictions(f,'nz_ainz6_p2_0',hit,guard),[])
        guard['pattern_dodge']['contacts'][0]['reduction']=0
        self.assertTrue(contact_afflictions(f,'nz_ainz6_p2_0',hit,guard))
        self.assertEqual(next(e for e in f['effects'] if e['kind']=='bleed')['value'],3)
        self.assertEqual(contact_afflictions(f,'nz_ainz6_p2_0',dict(hit=False,damage=0),guard),[])

    def test_ritual_has_prep_and_can_be_weakened(self):
        d=encounter(6);d['boss']['own_turns']=1;set_intent(d)
        self.assertEqual(d['enemy_intents']['boss']['kind'],'ritual')
        resolve(d,BUILTIN_SKILLS,random.Random(2),actor_keys=[],enemy_keys=['boss'],complete=False)
        set_intent(d)
        self.assertEqual(d['enemy_intents']['boss']['skill'],'nz_ainz6_p6_1')
        self.assertIn('ritual',d['nazarick'])

    def test_all_profiles_shapes_and_blocks_match_javascript(self):
        fixtures=[]
        for sid,skill in SKILLS.items():
            if not sid.startswith('nz_ainz6_'):continue
            desc=dict(id=sid,base_id=sid,name=skill.name,class_id='raid',strikes=1,damage_type=skill.damage_type)
            p=profile(desc);stats=dict(accuracy=100,enemyEvasion=0,enemyAccuracy=100,evasion=0)
            for index in (0,1,3,6):
                fixtures.append(dict(p=p,d=difficulty(stats),player=dict(x=335,y=173),
                    event=dict(index=index,jitter=.35,at=.1),preparation=1,
                    params=parameters(p,dict(physicalDefense=20,magicDefense=15,enemyAttack=20,enemyAccuracy=100))))
        script="const N=require('./webapp/nazarick-qte.js'),E=require('./webapp/qte-unique/engine');let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(f=>({shapes:N.shapes(f,f.event),blocks:N.blockThreats(f.p,42,f.params,E.rng),family:E.family(f.p.skill),duration:N.activeDuration(f.p),blockDuration:N.blockDuration(f.p),schedule:N.schedule(f.p,4,4.5)})))));"
        actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        def compare(a,b):
            if isinstance(a,(int,float)) and not isinstance(a,bool):self.assertAlmostEqual(a,b,places=8)
            elif isinstance(a,(list,tuple)):
                self.assertEqual(len(a),len(b))
                for v,w in zip(a,b):compare(v,w)
            elif isinstance(a,dict):
                self.assertEqual(set(a),set(b))
                for k,v in a.items():compare(v,b[k])
            else:self.assertEqual(a,b)
        for f,a in zip(fixtures,actual):
            compare(shapes(f,f['event']),a['shapes']);compare(block_threats(f['p'],42,f['params']),a['blocks'])
            self.assertEqual(f['p']['kind'],a['family'])
            self.assertEqual(active_duration(f['p']),a['duration']);self.assertEqual(block_duration(f['p']),a['blockDuration'])
            compare(schedule(f['p'],4,4.5),a['schedule'])

    def test_time_stop_only_final_phase_and_two_cycles(self):
        for phase in range(1,7):
            p=profile(dict(id='test',base_id=f'nz_ainz6_p{phase}_0',name='test',class_id='raid',damage_type='magic'))
            for t in (2.0,7.2):self.assertEqual(time_stopped(dict(p=p,time=t,preparation=1)),phase==6)

    def test_unified_queue_transition_cancels_old_cast_and_resumes(self):
        import arena_unified_queue as queue
        from arena_raid_engine import BOSS_SKILLS
        skills={**BUILTIN_SKILLS,**BOSS_SKILLS}
        d=encounter();d['qte_modes']={}
        queue.initialize(d,skills)
        self.assertTrue(any(e['skill'].startswith('nz_ainz6_p1_') for e in queue.clock(d)['pending']))
        # A completing player action crosses the threshold before the old cast.
        d['boss']['hp']=2501
        queue.submit(d,'10','mana_shot','boss',skills,ident=queue.choice(d,'10'))
        for _ in range(8):
            queue.advance(d,skills,random.Random(1))
            if d['nazarick']['phase']==2:break
            for key in queue.ready(d):queue.submit(d,key,'mana_shot','boss',skills,ident=queue.choice(d,key))
        self.assertEqual(d['nazarick']['phase'],2)
        self.assertTrue(any(e['skill'].startswith('nz_ainz6_p2_') for e in queue.clock(d)['pending']))
        self.assertFalse(any(e['skill'].startswith('nz_ainz6_p1_') for e in queue.clock(d)['pending']))
