import unittest
from copy import deepcopy
import random

from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state, Skill
from arena_raid_engine import native_attack, BOSS_SKILLS
from arena_encounters import create_encounter
from arena_nazarick_dungeon_rules import GUARDIANS,MOVES,build_skills,configure_enemy,intents,phases,ROOMS
from arena_nazarick_guardians import effect,prepare,allows_effect

CATALOG={**BUILTIN_SKILLS,**BOSS_SKILLS,**build_skills(Skill)}

def state(who='cocytus',phase=1):
    data=create_encounter([dict(actor_id=10,fighter_id=10,personal=True,slave_owner=10)],
        [dict(slave_id=10,owner_id=10,class_id='warrior',level=20)],FIGHTER_CLASSES,BUILTIN_SKILLS,['goblin'],30)
    f=data['enemies']['e1'];configure_enemy(f,who,1)
    f.update(nzd_phase=phase,loadout=[f'nz_{who}_p{phase}_{i}' for i in range(5)])
    data.update(nazarick_run_id='unit-test',nazarick_room=next(r['index'] for r in ROOMS if who in r['enemies']),qte_modes={})
    return data,f,data['players']['10']['fighter']

class GuardianTests(unittest.TestCase):
    def test_all_guardians_have_ten_legendary_skills_and_real_passives(self):
        self.assertEqual(len(build_skills(Skill)),120)
        for who in GUARDIANS:
            data,f,target=state(who)
            self.assertEqual([len(p) for p in MOVES[who]],[5,5])
            self.assertGreaterEqual(len(f['passive_details']),2)
            self.assertTrue(all(CATALOG[f'nz_{who}_p{p}_{i}'].rarity=='legendary' for p in (1,2) for i in range(5)))

    def test_every_new_skill_can_be_cast_with_native_conditions(self):
        for who in GUARDIANS:
            for phase in (1,2):
                for move in range(5):
                    with self.subTest(who=who,phase=phase,move=move):
                        data,f,target=state(who,phase)
                        target['hp']=target['stats']['max_hp']=10000
                        f['hp']=round(f['stats']['max_hp']*.60)
                        sid=f'nz_{who}_p{phase}_{move}'
                        native_attack(f,target,sid,CATALOG,random.Random(1),allies=[f],raid_context=data)
                        self.assertEqual(f['own_turns'],1)
                        self.assertEqual(f['resource'],200-CATALOG[sid].cost)

    def test_cold_caps_without_removing_control(self):
        data,f,target=state()
        for _ in range(5):effect(f,target,dict(kind='nzd_frost',value=1),[],data)
        frost=next(e for e in target['effects'] if e['id']=='nzd_frost')
        self.assertEqual(frost['stacks'],3)
        self.assertEqual(frost['value'],-.24)
        self.assertEqual(next(e['value'] for e in target['effects'] if e['id']=='nzd_frost_evasion'),-6)
        self.assertFalse(any(e['kind']=='stun' for e in target['effects']))

    def test_lupus_heals_her_real_ally_and_not_the_opponent(self):
        data,f,target=state('lupusregina')
        ally=deepcopy(f);ally['hp']=1
        hp=target['hp']
        native_attack(f,target,'nz_lupusregina_p1_3',CATALOG,random.Random(1),allies=[f,ally],raid_context=data)
        self.assertEqual(ally['hp'],1+round(ally['stats']['max_hp']*.16))
        self.assertEqual(target['hp'],hp)

    def test_mare_shelter_and_sibling_bonus_are_not_only_descriptions(self):
        data,f,target=state('mare',2)
        aura=deepcopy(f);configure_enemy(aura,'aura',1);data['enemies']['e2']=aura
        prepare(data)
        self.assertTrue(any(e['id']=='nzd_sibling' and e['value']==.12 for e in f['effects']))
        native_attack(f,target,'nz_mare_p2_3',CATALOG,random.Random(1),allies=[f,aura],raid_context=data)
        self.assertTrue(any(e['id']=='nzd_nature_shelter' and e['value']==.75 for e in aura['effects']))
        aura['hp']=0;prepare(data)
        self.assertFalse(any(e['id']=='nzd_sibling' for e in f['effects']))

    def test_construct_immunities_do_not_protect_normal_characters(self):
        _,garg,target=state('gargantua')
        for kind in ('stun','bleed','plague_infect'):
            self.assertFalse(allows_effect(garg,dict(kind=kind)))
            self.assertTrue(allows_effect(target,dict(kind=kind)))

    def test_cocytus_combo_is_really_five_strikes(self):
        from arena_qte_live import strike_count
        _,f,target=state('cocytus',2)
        skill=CATALOG['nz_cocytus_p2_4']
        self.assertEqual(strike_count(skill),5)
        event=native_attack(f,target,skill.skill_id,CATALOG,random.Random(1))
        self.assertEqual(len(event['hit_results']),5)

    def test_ai_rotates_by_own_actions_and_uses_only_available_skills(self):
        data,f,target=state('cocytus')
        selected=set()
        for turn in range(10):
            f['own_turns']=turn;intents(data);sid=data['enemy_intents']['e1']['skill']
            selected.add(sid)
            self.assertIn(sid,f['loadout'])
        self.assertEqual(len(selected),5)
        f['cooldowns']['nz_cocytus_p1_0']=2;f['own_turns']=0;intents(data)
        self.assertNotEqual(data['enemy_intents']['e1']['skill'],'nz_cocytus_p1_0')

    def test_signature_choreography_preserves_individual_strikes(self):
        from arena_qte_patterns import profile,defense,prepare
        from arena_nazarick_patterns import schedule,active_duration
        import subprocess,json
        fixtures=[]
        for who,strikes in (('cocytus',5),('sebas',3),('cz',3),('mare',1)):
            sid=f'nz_{who}_p2_4';skill=CATALOG[sid]
            desc=dict(id=sid,base_id=sid,name=skill.name,class_id='raid',strikes=strikes,damage_type=skill.damage_type)
            p=profile(desc)
            count={'cocytus':5,'sebas':4,'cz':1,'mare':2}[who]
            self.assertEqual(schedule(p,9,4)[0],count)
            self.assertEqual(active_duration(p),5.2 if who=='cz' else 8.4 if who=='sebas' else 6.8)
            stats=dict(accuracy=95,enemyEvasion=5,enemyAccuracy=100,evasion=0)
            s=defense(p,stats,42)
            self.assertEqual(len(s['events']),count)
            for event in s['events']:prepare(s,event)
            self.assertEqual(set(h['strike'] for h in s['hazards']),set(range(strikes)))
            fixtures.append(dict(p=p,stats=stats,strikes=strikes,count=count))
        script="const E=require('./webapp/qte-unique/engine');let b='';process.stdin.on('data',v=>b+=v);process.stdin.on('end',()=>{const out=JSON.parse(b).map(f=>{const s=E.defense(f.p,f.stats,42),seen=new Set();while(!s.ended){E.defenseStep(s,1/120,{x:0,y:0});s.hazards.forEach(h=>seen.add(h.strike));}return {count:s.events.length,strikes:[...seen].sort()};});process.stdout.write(JSON.stringify(out));});"
        result=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(fixtures).encode()))
        for f,r in zip(fixtures,result):
            self.assertEqual(r['count'],f['count'])
            self.assertEqual(r['strikes'],list(range(f['strikes'])))

    def test_two_phase_gate_survives_lethal_hit(self):
        for who in GUARDIANS:
            data,f,_=state(who);f['hp']=0;phases(data)
            self.assertEqual(f['nzd_phase'],2)
            self.assertGreater(f['hp'],0)
            self.assertEqual(len(f['loadout']),1 if who=='victim' else 10)

    def test_victim_is_a_finite_postmortem_trial_not_another_health_bar(self):
        from arena_encounters import finish
        data,f,target=state('victim');f['hp']=0;phases(data)
        self.assertTrue(f['nzd_ritual']);self.assertEqual(f['stats']['max_hp'],1)
        f['hp']=0;self.assertFalse(finish(data));self.assertEqual(f['hp'],1)
        self.assertFalse(allows_effect(f,dict(kind='stun')))
        native_attack(f,target,'nz_victim_p2_4',CATALOG,random.Random(1),raid_context=data)
        self.assertTrue(f['nzd_ritual_complete']);self.assertEqual(f['hp'],0)
        self.assertTrue(finish(data));self.assertTrue(data['won'])

    def test_phase_transition_replaces_stale_cast_and_gargantua_keeps_attacking(self):
        import arena_unified_queue as q
        for who in ('gargantua','victim'):
            data,f,target=state(who);data['unified_version']=3
            target['hp']=target['stats']['max_hp']=100000
            intents(data)
            q.initialize(data,CATALOG)
            self.assertIn('_p1_',q.clock(data)['pending'][0]['skill'])
            f['hp']=0;q._finish(data);q.initialize(data,CATALOG)
            self.assertIn('_p2_',q.clock(data)['pending'][0]['skill'])
            for _ in range(14):
                if data.get('finished'):break
                for key in q.ready(data):q.submit(data,key,'defend','e1',CATALOG,ident=q.choice(data,key))
                q.advance(data,CATALOG)
            if who=='victim':self.assertTrue(data.get('won'))
            else:self.assertGreaterEqual(f.get('own_turns',0),3)

    def test_twins_and_pleiades_open_with_real_joint_casts(self):
        import arena_unified_queue as q
        for team in (('aura','mare'),('yuri','narberal','lupusregina'),('solution','entoma','cz')):
            data,first,target=state(team[0]);data['unified_version']=3
            for i,who in enumerate(team[1:],2):
                f=deepcopy(first);configure_enemy(f,who,1);f['enemy_id']=f'e{i}';data['enemies'][f'e{i}']=f
            data['qte_modes']={'10':True};intents(data);q.initialize(data,CATALOG)
            self.assertTrue(q._release_group(data,CATALOG,random.Random(1)))
            self.assertEqual(len(data['_queue_wait']['released']),len(team))
            incoming=q.stages(data,'10',CATALOG)[0]
            self.assertEqual(len(incoming['members']),len(team))

    def test_resource_recovers_once_per_turn_for_guardians_only(self):
        from arena_engine import restore_turn_resource
        _,f,_=state('gargantua');f.update(resource=0,own_turns=16)
        self.assertEqual(restore_turn_resource(f),16)
        self.assertEqual(restore_turn_resource(f),0)
        other=deepcopy(f);other.pop('nzd_guardian');other.update(resource=0,own_turns=17)
        self.assertEqual(restore_turn_resource(other),0)

    def test_victim_long_trial_has_six_distinct_sections_and_streams_to_the_end(self):
        from arena_qte_patterns import profile,defense,prepare
        from arena_nazarick_patterns import block_duration
        from arena_qte_watch import Stream
        import time
        skill=CATALOG['nz_victim_p2_4'];desc=dict(id=skill.skill_id,base_id=skill.skill_id,name=skill.name,class_id='raid',damage_type='magic',strikes=1)
        p=profile(desc);s=defense(p,dict(accuracy=95,enemyEvasion=0,enemyAccuracy=100,evasion=0),42)
        self.assertEqual(len(s['events']),12);self.assertEqual(block_duration(p),45)
        variants=[]
        for event in s['events'][::2]:
            sample=deepcopy(s);sample['hazards']=[];prepare(sample,event)
            variants.append(tuple((h['type'],h.get('motif')) for h in sample['hazards']))
        self.assertEqual(len(set(variants)),6)
        from arena_qte_block import create
        challenge=dict(id='long',kind='defense',version=3,profile=desc,seed=42,strikes=1,started=time.time()-46,expires=time.time()+30,stats=dict(physicalDefense=30,magicDefense=30,enemyAttack=20,enemyAccuracy=100))
        self.assertGreaterEqual(len(create(challenge)['events']),40)
        stream=Stream(challenge,None);stream.accept(dict(type='data',id='long',tick=5400,inputs=[],ended=True))
        self.assertTrue(stream.ended)

    def test_long_depleted_guardian_fights_and_one_failed_cast_do_not_lock_ai(self):
        import arena_unified_queue as q
        for who in ('gargantua','sebas'):
            data,f,target=state(who,2);data['unified_version']=3
            target['hp']=target['stats']['max_hp']=1000000
            f['resource']=0;intents(data);self.assertEqual(data['enemy_intents']['e1']['kind'],'recover')
            q.initialize(data,CATALOG)
            injected=False
            for _ in range(250):
                if f.get('own_turns',0)>=60:break
                if not injected and f.get('own_turns',0)>=3:
                    pending=next((e for e in q.clock(data)['pending'] if e['actor']=='e1' and e['skill']),None)
                    if pending:f['cooldowns'][pending['skill']]=2;injected=True
                for key in q.ready(data):q.submit(data,key,'defend','e1',CATALOG,ident=q.choice(data,key))
                q.advance(data,CATALOG,random.Random(1))
            self.assertTrue(injected);self.assertGreaterEqual(f['own_turns'],60)
            attacks=[e for e in data['log'] if e.get('skill','').startswith('nz_'+who)]
            self.assertGreater(len(attacks),5)
            self.assertFalse(any('Каст сорван' in e['text'] for e in data['log'][-15:]))

    def test_ritual_cannot_be_restarted_by_spamming_attacks(self):
        import arena_unified_queue as q
        from arena_engine import validate_skill
        data,f,target=state('victim');data['unified_version']=3
        target['hp']=target['stats']['max_hp']=1000000
        f.update(hp=0,resource=0);phases(data)
        attack=next(sid for sid in target['loadout'] if CATALOG[sid].hostile)
        for _ in range(10):
            with self.assertRaisesRegex(ValueError,'печать нельзя атаковать'):
                validate_skill(q.pair(target,f),'a',attack,CATALOG)
            self.assertEqual(f['hp'],1)
        intents(data);q.initialize(data,CATALOG)
        end=q.clock(data)['pending'][0]['end']
        for _ in range(20):
            if data.get('finished'):break
            for key in q.ready(data):q.submit(data,key,'defend','e1',CATALOG,ident=q.choice(data,key))
            q.advance(data,CATALOG)
        self.assertTrue(data.get('won'));self.assertTrue(f.get('nzd_ritual_complete'))
        self.assertGreaterEqual(q.clock(data)['time'],end)
