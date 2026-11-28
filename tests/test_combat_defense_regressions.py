import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import unittest
from copy import deepcopy
from dataclasses import replace

from arena_combined_damage import incoming_group, target_counts
from arena_engine import BUILTIN_SKILLS, create_battle_state
from arena_qte_combined import combine, replay
from arena_qte_live import challenge, strike_count
from arena_action_queue import _land
from test_action_queue_live import state
from test_nazarick_guardians import CATALOG, state as guardian_state

ROOT = Path(__file__).resolve().parents[1]


class DefenseRegressions(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_guild_dragon_replay_damage_matches_the_visible_contacts(self):
        import arena_unified_queue as queue
        from arena_encounters import create_encounter
        from arena_engine import FIGHTER_CLASSES
        from arena_guild_rules import mob_templates,MONSTERS
        from arena_raid_engine import BOSS_SKILLS
        skills={**BUILTIN_SKILLS,**BOSS_SKILLS}
        for mid in ('dragon','ancient'):
            for mode in ('dodge','block'):
                for sid in MONSTERS[mid]['skills']:
                    with self.subTest(monster=mid,mode=mode,skill=sid):
                        templates=mob_templates(dict(rank=MONSTERS[mid]['rank'],kind='hunt',monsters=[mid]),dict(kind='boss'),1)
                        data=create_encounter([dict(actor_id=10,fighter_id=10,personal=True,slave_owner=10)],
                            [dict(slave_id=10,owner_id=10,class_id='warrior',level=20)],FIGHTER_CLASSES,skills,templates,10)
                        data.update(unified_version=3,_cast_queue=dict(time=1,round=1))
                        enemy=data['enemies']['e1'];enemy['guild_monster']=mid
                        player=data['players']['10']['fighter'];player.update(hp=10000,defense_mode=mode)
                        player['stats']['max_hp']=10000
                        cast=dict(source='e1',fighter=deepcopy(enemy),intent=dict(skill=sid,targets=['10']))
                        data['_queue_wait']=dict(attacks={},released=[cast],guards={})
                        stage,=queue.stages(data,'10',skills)
                        stage['members'][0]['seed']=17
                        self.assertTrue(stage['members'][0]['fixed_contact_reference'])
                        proof=dict(ticks=math.ceil(stage['duration']*120-1e-7),inputs=[])
                        expected=json.loads(subprocess.check_output(['node','tests/qte_combined_trace.cjs'],cwd=ROOT,
                            input=json.dumps(dict(stage=stage,proof=proof,withDamage=True)).encode()))
                        result=replay(stage,proof,stage['duration'])
                        queue.record_result(data,stage,result)
                        _land(data,[cast],data['_queue_wait']['guards'],skills,random.Random(8))
                        self.assertEqual(10000-player['hp'],sum(c['damage'] for c in expected['e1']))
                        # A clean defense never receives damage or an on-hit status.
                        player.update(hp=10000,effects=[])
                        result=dict(sources={'e1':dict(dodge=[True]*stage['strikes'],pattern_dodge=dict(contacts=[],mode=mode))})
                        queue.record_result(data,stage,result)
                        _land(data,[cast],data['_queue_wait']['guards'],skills,random.Random(18))
                        self.assertEqual(player['hp'],10000)
                        self.assertFalse(player['effects'])

    def test_encounter_defend_explains_burn_separately(self):
        from arena_action_queue import _player
        data=state();data['_cast_queue']=dict(time=1,round=1)
        p=data['players']['20'];p['selected']='defend';before=p['fighter']['hp']
        p['fighter']['effects'].append(dict(id='guild_dragon_burn',kind='burn',value=3,duration=2))
        _player(data,'20',BUILTIN_SKILLS,random.Random(3))
        self.assertEqual(p['fighter']['hp'],before-3)
        self.assertIn('горение: −3 HP',data['log'][-1]['text'])

    def test_fast_collision_checks_keep_tangencies_and_swept_hits(self):
        from arena_qte_patterns import _segments_within, touches
        # A beam five pixels above a horizontal movement is exactly tangent.
        self.assertTrue(_segments_within(0, 0, 10, 0, 2, 5, 8, 5, 5))
        self.assertFalse(_segments_within(0, 0, 10, 0, 2, 5.0000000001, 8, 5.0000000001, 5))
        # Both projectile samples are outside the player, but the projectile
        # crosses them between ticks. Checking endpoints alone would miss it.
        player = dict(x=12, y=30, r=2)
        h = dict(type='bullet', x=0, y=30, vx=16, vy=0, r=1, start=0)
        self.assertFalse(touches(h, player, player, .5, .5))
        self.assertTrue(touches(h, player, player, 1.5, 1))
        self.assertFalse(touches(h, player, player, 2.5, 1))

    def test_companions_cannot_hit_outside_a_perfect_defense(self):
        from arena_engine import resolve_skill
        cases=(('mage','mage_necromancer','mana_blob'),('ring','ring_fauvist','red_etude'))
        for cls,arch,sid in cases:
            for mode in ('dodge','block'):
                with self.subTest(cls=cls,mode=mode):
                    battle=create_battle_state(dict(slave_id=10,owner_id=10,class_id=cls,level=20,archclass_id=arch),
                        dict(slave_id=20,owner_id=20,class_id='ragamuffin',level=20))
                    a,b=battle['sides'].values()
                    for f in (a,b):f['hp']=f['stats']['max_hp']=10000;f['loadout']=list(BUILTIN_SKILLS)
                    a['rpg_state']=dict(summon=3,souls=0)
                    a['final_state']=dict(beast=3)
                    guard=dict(dodge=[True]*strike_count(BUILTIN_SKILLS[sid]),pattern_dodge=dict(contacts=[],mode=mode))
                    event=resolve_skill(battle,'a',sid,BUILTIN_SKILLS,random.Random(2),qte=guard)
                    self.assertEqual(b['hp'],10000,event)
                    self.assertEqual(event['damage'],0)
                    self.assertEqual(event['follower_damage'],0)
                    remaining=a['rpg_state']['summon'] if cls=='mage' else a['final_state']['beast']
                    self.assertEqual(remaining,2)

    def test_clean_guard_is_respected_for_every_guardian_attack(self):
        # Includes maids, multi-strikes, class effects and both guardian phases.
        for who in ('gargantua','cocytus','aura','mare','victim','sebas','yuri','lupusregina','narberal','cz','solution','entoma'):
            for phase in (1,2):
                for index in range(5):
                    with self.subTest(who=who,phase=phase,index=index):
                        data, enemy, player=guardian_state(who,phase)
                        data['_cast_queue']=dict(time=1,round=data['round'])
                        sid=f'nz_{who}_p{phase}_{index}'
                        if not CATALOG[sid].hostile:continue
                        player['hp']=player['stats']['max_hp']=10000
                        cast=dict(source='e1',fighter=deepcopy(enemy),intent=dict(skill=sid,targets=['10']))
                        guard=dict(dodge=[True]*strike_count(CATALOG[sid]),pattern_dodge=dict(contacts=[]))
                        _land(data,[cast],{'10':{'e1':guard}},CATALOG,random.Random(2))
                        self.assertEqual(player['hp'],10000,data['log'])
                        self.assertTrue(all(e.get('damage',0)==0 for e in data['log']))

    def test_simultaneous_discount_is_per_target_and_once_per_skill(self):
        from arena_engine import resolve_skill
        for count,factor in ((1,1),(2,.9),(3,.8),(5,.8)):
            for mode in ('normal','projectiles','multistrike'):
                with self.subTest(count=count,mode=mode):
                    battle=create_battle_state(dict(slave_id=10,owner_id=10,class_id='ragamuffin',level=20),
                        dict(slave_id=20,owner_id=20,class_id='ragamuffin',level=20))
                    for f in battle['sides'].values():f['hp']=f['stats']['max_hp']=10000
                    skill=replace(BUILTIN_SKILLS['bum_punch'],power=100,effects=(),tags=('three_strike',) if mode=='multistrike' else ())
                    skills={**BUILTIN_SKILLS,skill.skill_id:skill}
                    proof=dict(attack=[True]*(3 if mode=='multistrike' else 1),luck_evasion=False)
                    if mode=='projectiles':
                        proof.update(dodge=[False],pattern_dodge=dict(contacts=[dict(id=str(i),strike=0,weight=.3,tier='minor') for i in range(6)]))
                    baseline=resolve_skill(deepcopy(battle),'a',skill.skill_id,skills,random.Random(2),qte=proof)
                    released=[dict(source=str(i),intent=dict(skill=skill.skill_id,targets=['b'])) for i in range(count)]
                    with incoming_group(battle,released,skills):
                        actual=resolve_skill(battle,'a',skill.skill_id,skills,random.Random(2),qte=proof)
                    self.assertEqual(actual['damage'],math.floor(baseline['damage']*factor+.5))
                    self.assertNotIn('_simultaneous_incoming',battle['sides']['b'])
                    if mode!='normal':self.assertEqual(sum(actual['hits']),actual['damage'])

    def test_count_excludes_support_duplicates_and_other_targets(self):
        released=[dict(source='one',intent=dict(skill='bum_punch',targets=['a','a'])),
            dict(source='two',intent=dict(skill='bum_punch',targets=['b'])),
            dict(source='three',intent=dict(skill='charging',targets=['a']))]
        self.assertIn('charging',BUILTIN_SKILLS)
        self.assertEqual(target_counts(released,BUILTIN_SKILLS),{'a':1,'b':1})
        data=state();fighter=data['players']['20']['fighter']
        released=[dict(source='one',intent=dict(skill='bum_punch',targets=['20']))]
        with self.assertRaises(RuntimeError):
            with incoming_group(data,released,BUILTIN_SKILLS):raise RuntimeError('failed cast')
        self.assertNotIn('_simultaneous_incoming',fighter)

    def test_party_attacks_use_the_same_rule_for_an_enemy_target(self):
        from arena_unified_queue import _damage_group
        data=state(actors=(20,30))
        data['_queue_wait']=dict(released=[],attacks={str(k):dict(skill='bum_punch',target='e1') for k in (20,30)})
        casts=_damage_group(data)
        with incoming_group(data,casts,BUILTIN_SKILLS):
            self.assertEqual(data['enemies']['e1']['_simultaneous_incoming'],.9)
            self.assertNotIn('_simultaneous_incoming',data['players']['20']['fighter'])
        self.assertNotIn('_simultaneous_incoming',data['enemies']['e1'])

    def test_raid_header_is_not_removed_by_intent_lines(self):
        source=(ROOT/'webapp/battle-client').read_text(encoding='utf-8')
        self.assertNotIn("document.querySelector?.('.raid-intent')?.remove()",source)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_solo_header_includes_the_next_npc_skill_and_time(self):
        subprocess.run(['node','tests/battle_intent_header.cjs'],cwd=ROOT,check=True,capture_output=True)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_shared_motion_uses_the_position_that_is_drawn(self):
        subprocess.run(['node','tests/qte_shared_motion.cjs'],cwd=ROOT,check=True,capture_output=True)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_guardian_combined_browser_and_server_contacts_match(self):
        cases=[(('mare',2,2),('narberal',1,0)),(('cocytus',2,4),('aura',1,0)),
               (('yuri',2,1),('lupusregina',1,1),('narberal',2,2))]
        for case in cases:
            for mode in ('dodge','block'):
                with self.subTest(case=case,mode=mode):
                    members=[]
                    for i,(who,phase,index) in enumerate(case):
                        _,enemy,player=guardian_state(who,phase)
                        player['defense_mode']=mode
                        m=challenge('defense',enemy,player,CATALOG[f'nz_{who}_p{phase}_{index}'],10)
                        m.update(seed=99+i,encounter_enemy=f'e{i}')
                        members.append(m)
                    stage=combine(members,10,10000)
                    self.assertEqual(stage['incoming_factor'],.9 if len(members)==2 else .8)
                    ticks=math.ceil(stage['duration']*120-1e-7)
                    proof=dict(ticks=ticks,inputs=[dict(t=t,**(dict(angle=math.sin(t/40)*3,active=t%100<70) if mode=='block'
                        else dict(target=[360+200*math.sin(t/80),160+130*math.cos(t/95)]))) for t in range(0,ticks,20)])
                    actual=json.loads(subprocess.check_output(['node','tests/qte_combined_trace.cjs'],cwd=ROOT,input=json.dumps(dict(stage=stage,proof=proof)).encode()))
                    expected=replay(stage,proof,99)['sources']
                    for source,value in expected.items():
                        contacts=value['pattern_dodge']['contacts']
                        self.assertEqual(len(contacts),len(actual[source]))
                        for a,b in zip(contacts,actual[source]):
                            self.assertEqual({k:v for k,v in a.items() if k!='weight'},{k:v for k,v in b.items() if k!='weight'})
                            self.assertAlmostEqual(a['weight'],b['weight'],places=7)

    def test_existing_periodic_damage_is_not_reduced_or_cleansed(self):
        from arena_engine import _tick
        data=state();fighter=data['players']['20']['fighter']
        fighter['hp']=1000
        fighter['effects'].append(dict(id='test_burn',kind='burn',value=10,duration=3))
        casts=[dict(source=str(i),intent=dict(skill='bum_punch',targets=['20'])) for i in range(3)]
        with incoming_group(data,casts,BUILTIN_SKILLS):_tick(fighter)
        self.assertEqual(fighter['hp'],990)
        self.assertTrue(any(e['id']=='test_burn' for e in fighter['effects']))


if __name__=='__main__':unittest.main()
