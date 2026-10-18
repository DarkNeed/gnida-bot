import copy
import json
import random
import shutil
import unittest
from unittest.mock import patch

from arena_archclasses import ARCHCLASSES, archclass_view
from arena_engine import (BUILTIN_SKILLS,FIGHTER_CLASSES,create_battle_state,
    effective_skill,resolve_skill,battle_status_snapshot,skip_turn,effective_stat)
from arena_evolution import evolution_info
from arena_finals import FINALS, branch, buff, incoming
from arena_mirror_effects import gift_cost
from arena_epic import temporary_debuff, cleanse_one
from arena_raid_engine import native_attack, defend, create_raid_state, resolve_round
from test_arena_rebalance import FixedRoll
import test_arena_status_ui as status_tests


PRIMARY=dict(femboy='air_kiss',princess='air_kiss',gachi_actor='smack',mge_bro='butt_peak',
    programmer='charging',hacker='arch_hacker',thumb_discipline='warning_shot',
    thumb_execution='senior_verdict',index_proxy='last_line',index_messenger='arch_index_messenger',
    middle_guardian='arch_middle_guardian',middle_revenge='whole_family',
    ring_pointillist='red_etude',ring_fauvist='last_stroke',pinky_dihui='moon_arc',pinky_tiansha='falling_star')


class FinalsEngineTests(unittest.TestCase):
    def state(self,key='mge_bro',level=20,stage=20):
        a=dict(slave_id=10,owner_id=10,class_id=FINALS[key][0],level=level,
               archclass_id=key,archclass_stage=stage)
        b=dict(slave_id=20,owner_id=20,class_id='jock',level=20)
        state=create_battle_state(a,b)
        for s in state['sides'].values():
            s['hp']=s['stats']['max_hp']=1000
            s['loadout']=list(BUILTIN_SKILLS)
        return state

    def tap(self,state,sid,side='a',roll=0,**kwargs):
        state['active_side']=side
        state['sides'][side]['cooldowns'].pop(sid,None)
        return resolve_skill(state,side,sid,rng=FixedRoll(roll),advance_turn=False,**kwargs)

    def prepare(self,state):
        a,b=state['sides'].values()
        a['final_state']=dict(shame=3,whim=3,grip=3,dominance=3,compiled=True,access=3,
            command=1,zones=['a','b','c'],execution=2,guilt=3,steadfast=3,blood_debt=1000,beast=3,counter_until=2)
        a['mechanics']=dict(focus=3)
        for kind in ('accuracy_flat','speed_pct','magic_defense_pct'):
            buff(b,kind,kind,-.1,3)

    def test_all_sixteen_titles_variants_and_one_click_no_extra_slots(self):
        self.assertEqual(len(FINALS),16)
        for key,(cls,title,_) in FINALS.items():
            with self.subTest(key=key):
                state=self.state(key);self.prepare(state)
                a,b=state['sides'].values();sid=PRIMARY[key]
                self.assertEqual(archclass_view(a)['title'],title)
                v=effective_skill(state,'a',sid)
                self.assertTrue(any(t.startswith('final_') for t in v.tags))
                self.assertEqual(v.skill_id,sid)
                self.assertEqual(v.cooldown,BUILTIN_SKILLS[sid].cooldown)
                self.assertEqual(evolution_info(BUILTIN_SKILLS[sid],cls,a,b)['min_level'],20)
                count=len(a['loadout']);passives=copy.deepcopy(a['passive_details'])
                event=self.tap(state,sid)
                self.assertGreaterEqual(a['resource'],0)
                self.assertEqual(len(a['loadout']),count)
                self.assertEqual(a['passive_details'],passives)
                self.assertIn('final_state',event['status_after']['a'])
                self.assertEqual(json.loads(json.dumps(state)),state)

    def test_no_final_mechanics_before_twenty_or_when_staying_at_ten(self):
        for key in FINALS:
            for level,stage in ((19,20),(20,10)):
                state=self.state(key,level,stage);self.prepare(state)
                self.assertFalse(branch(state['sides']['a']))
                v=effective_skill(state,'a',PRIMARY[key])
                self.assertFalse(any(t.startswith('final_') for t in v.tags))
            state=self.state(key);state['sides']['a']['class_id']='ragamuffin'
            self.assertFalse(branch(state['sides']['a']))

    def test_failed_validation_and_preview_are_read_only(self):
        for key in FINALS:
            state=self.state(key);self.prepare(state)
            a=state['sides']['a'];sid=PRIMARY[key];a['resource']=0
            before=copy.deepcopy(state)
            for _ in range(3):effective_skill(state,'a',sid)
            self.assertEqual(state,before)
            with self.assertRaises(ValueError):resolve_skill(state,'a',sid,rng=FixedRoll())
            self.assertEqual(state,before)

    def test_final_tooltip_does_not_claim_ready_from_an_old_stage_variant(self):
        state=self.state('femboy');a,b=state['sides'].values()
        buff(b,'adoration','damage_pct',-.4,3)
        info=evolution_info(BUILTIN_SKILLS['air_kiss'],'cutie',a,b)
        self.assertFalse(info['final_ready'])
        self.assertEqual(effective_skill(state,'a','air_kiss').name,'Попался, натурал')

    def test_train_three_independent_rolls_one_cost_one_proc(self):
        class Rolls(FixedRoll):
            def __init__(self):self.values=iter([0,.99,0])
            def random(self):return next(self.values,0)
        state=self.state();a,b=state['sides'].values()
        a['final_state']=dict(dominance=3)
        with patch('arena_engine.pet_after_action',return_value=[]) as pet:
            event=resolve_skill(state,'a','butt_peak',rng=Rolls(),advance_turn=False)
        self.assertEqual(event['skill_name'],'Билет в паровозик')
        self.assertEqual([p['hit'] for p in event['hit_results']],[True,False,True])
        self.assertEqual(sum(event['hits']),event['damage'])
        self.assertEqual((a['resource'],a['own_turns']),(55,1))
        self.assertEqual(a['final_state']['dominance'],0)
        self.assertAlmostEqual(effective_stat(a,'physical_defense'),a['stats']['physical_defense']*.8)
        pet.assert_called_once()

    def test_train_weights_and_miss_retention(self):
        state=self.state();a,b=state['sides'].values()
        a['stats']['physical_attack']=0;b['stats']['physical_defense']=0
        a['final_state']=dict(dominance=3)
        event=self.tap(state,'butt_peak')
        self.assertEqual(event['hits'],[8,12,20])
        state=self.state();a=state['sides']['a'];a['final_state']=dict(dominance=3)
        event=self.tap(state,'butt_peak',roll=.99)
        self.assertEqual(event['hits'],[0,0,0])
        self.assertEqual(a['final_state']['dominance'],3)
        self.assertEqual(a['resource'],55)

    def test_train_native_preparation_is_affordable_without_specific_pet_or_tractat(self):
        state=self.state();a=state['sides']['a']
        for sid in ('smack','wallop','smack'):
            self.tap(state,sid)
        self.assertEqual(a['resource'],50)
        self.assertEqual(a['final_state']['dominance'],3)
        self.assertEqual(self.tap(state,'butt_peak')['skill_name'],'Билет в паровозик')
        self.assertEqual(a['resource'],5)

    def test_dominance_misses_count_repetition_does_not(self):
        state=self.state();a=state['sides']['a']
        for sid in ('smack','smack','wallop','butt_peak'):
            a['resource']=100;self.tap(state,sid,roll=.99)
        self.assertEqual(a['final_state']['dominance'],3)

    def test_train_last_hit_adds_pet_pierce_without_double_counting(self):
        state=self.state();a,b=state['sides'].values()
        a['stats']['physical_attack']=0;b['stats']['physical_defense']=50
        a['final_state']=dict(dominance=3)
        with patch('arena_engine.pet_modifiers',return_value=(0,0,.20)):
            event=self.tap(state,'butt_peak')
        self.assertEqual(event['hits'],[4,4,11])

    def test_femboy_different_hits_prepare_and_hit_spends(self):
        state=self.state('femboy');a,b=state['sides'].values()
        for sid in ('air_kiss','air_kiss','uwu','meow'):
            a['resource']=100;self.tap(state,sid)
        self.assertEqual(a['final_state']['shame'],3)
        a['resource']=100;self.tap(state,'air_kiss',roll=.99)
        self.assertEqual(a['final_state']['shame'],3)
        a['resource']=100;self.tap(state,'air_kiss')
        self.assertEqual(a['final_state']['shame'],0)
        self.assertTrue(any(e['id']=='final_charm_weakness' for e in b['effects']))

    def test_princess_multihit_one_charge_and_two_different_spenders(self):
        state=self.state('princess');a,b=state['sides'].values()
        b['loadout']=['lei_perfected_flurry']
        native_attack(b,a,'lei_perfected_flurry',__import__('arena_raid_engine').BOSS_SKILLS,FixedRoll())
        self.assertEqual(a['final_state']['whim'],1)
        a['final_state']['whim']=3
        self.tap(state,'posing')
        self.assertEqual(a['final_state']['whim'],1)
        self.assertEqual(next(e['value'] for e in a['effects'] if e['id']=='final_royal_guard'),.75)
        self.assertTrue(any(e['kind']=='evasion_flat' and e['value']==20 for e in a['effects']))
        a['final_state']['whim']=2;a['resource']=100
        self.assertEqual(self.tap(state,'air_kiss')['skill_name'],'Казнить нельзя помиловать')

    def test_wrestler_grip_can_be_broken_and_boss_is_not_stunned(self):
        state=self.state('gachi_actor');a,b=state['sides'].values()
        self.tap(state,'clench');self.tap(state,'flex_chest')
        self.assertEqual(a['final_state']['grip'],3)
        defend(b,a)
        self.assertEqual(a['final_state']['grip'],2)
        a['final_state']['grip']=3;a['resource']=100;b['is_boss']=True
        self.tap(state,'smack')
        self.assertEqual(a['final_state']['grip'],0)
        self.assertFalse(any(e['kind']=='stun' for e in b['effects']))

    def test_program_compilation_and_exactly_one_mode(self):
        for mode in ('humiliate','doxxing','go_to_store'):
            state=self.state('programmer');a=state['sides']['a']
            for sid in ('humiliate','doxxing'):
                a['resource']=100;self.tap(state,sid)
            self.assertTrue(a['final_state']['compiled'])
            a['resource']=100
            self.assertEqual(self.tap(state,'charging')['skill_name'],'В продакшене разберёмся')
            self.assertTrue(any(e['id']=='charging_damage' and e['value']==.6 for e in a['effects']))
            a['resource']=0 if mode=='go_to_store' else 100
            a['cooldowns']['mother_joke']=5
            event=self.tap(state,mode)
            self.assertEqual(a['final_state']['program_until'],0)
            self.assertFalse(a['final_state']['compiled'])
            self.assertEqual(a['cooldowns'].get('mother_joke'),2 if mode=='doxxing' else 4)
            if mode=='go_to_store':self.assertEqual(a['resource'],75)

    def test_hacker_tax_is_actual_cost_once_free_fallback_and_cleanse(self):
        state=self.state('hacker');a,b=state['sides'].values()
        a['final_state']=dict(access=3)
        self.tap(state,'arch_hacker')
        self.assertEqual(a['final_state']['access'],0)
        self.assertEqual(gift_cost(b,BUILTIN_SKILLS['smack']),25)
        self.assertEqual(gift_cost(b,BUILTIN_SKILLS['bum_punch']),0)
        tax=next(e for e in b['effects'] if e['kind']=='skill_cost_flat')
        self.assertTrue(temporary_debuff(tax))
        self.tap(state,'bum_punch',side='b')
        self.assertEqual(gift_cost(b,BUILTIN_SKILLS['smack']),25)
        self.tap(state,'smack',side='b')
        self.assertEqual(b['resource'],75)
        self.assertEqual(gift_cost(b,BUILTIN_SKILLS['smack']),10)

    def test_thumb_preparation_and_execution_budget(self):
        for key,sid in (('thumb_discipline','warning_shot'),('thumb_execution','senior_verdict')):
            state=self.state(key);a=state['sides']['a']
            for move in ('bayonet','reload','arch_'+key):
                a['resource']=100;self.tap(state,move)
            a['resource']=100
            self.assertTrue(any(t.startswith('final_') for t in effective_skill(state,'a',sid).tags))
            event=self.tap(state,sid)
            self.assertEqual(a['final_state']['zones'],[])
            if key=='thumb_execution':self.assertEqual(len(event['hit_results']),3)
            else:self.assertTrue(any(e['id']=='final_code_guard' for e in a['effects']))

    def test_proxy_refund_and_single_reroll(self):
        state=self.state('index_proxy');a=state['sides']['a']
        for _ in range(2):
            a.setdefault('mechanics',{})['prescript']='first_line';self.tap(state,'first_line')
        self.assertEqual(a['final_state']['execution'],2)
        a['resource']=100;self.tap(state,'last_line',roll=.99)
        self.assertEqual(a['resource'],75)
        self.assertEqual(a['final_state']['execution'],2)
        a['resource']=100;self.tap(state,'last_line')
        self.assertEqual(a['final_state']['execution'],0)
        a['mechanics']['prescript']='first_line';a['resource']=100
        self.tap(state,'receive_prescript')
        order=a['mechanics']['prescript'];self.assertNotEqual(order,'first_line')
        self.tap(state,'receive_prescript')
        self.assertEqual(a['mechanics']['prescript'],order)

    def test_messenger_two_achievable_choices_and_outcomes(self):
        state=self.state('index_messenger');a,b=state['sides'].values()
        b['loadout']=['smack','wallop'];b['resource']=0
        self.tap(state,'receive_prescript')
        self.assertEqual(b['mechanics']['enemy_prescript']['allowed'],['bum_punch'])
        a['resource']=50;self.tap(state,'bum_punch',side='b')
        self.assertEqual(a['resource'],55)
        a['resource']=100;b['resource']=100
        self.tap(state,'receive_prescript')
        self.assertEqual(len(b['mechanics']['enemy_prescript']['allowed']),2)
        state['active_side']='b';skip_turn(state)
        self.assertEqual(a['final_state']['guilt'],3)  # One obedience + one violation.

    def test_messenger_aoe_clones_do_not_multiply_guilt_or_refunds(self):
        from arena_archclasses import obey_enemy_prescript
        state=self.state('index_messenger');a,b=state['sides'].values()
        a['resource']=50
        for skill,expected in ((None,2),('smack',1)):
            a['final_state']={}
            b.setdefault('mechanics',{})['enemy_prescript']=dict(skill_id='smack',allowed=['smack'],source=10,penalty=12)
            for _ in range(3):obey_enemy_prescript(copy.deepcopy(b),skill,a)
            self.assertEqual(a['final_state'].get('guilt',0),expected)
        self.assertEqual(a['resource'],55)

    def test_guardian_redirect_deduplicates_and_dead_guardian_cannot_protect(self):
        state=self.state('middle_guardian');a,b=state['sides'].values()
        friend=copy.deepcopy(b);friend['controller_id']=30;friend['hp']=500
        raid=dict(players={'10':dict(fighter=a),'30':dict(fighter=friend)})
        self.tap(state,'arch_middle_guardian',allies=[a,friend],raid_context=raid)
        hp=a['hp'];left=incoming(friend,100,b,raid)
        self.assertEqual((left,a['hp']),(70,hp-30))
        self.assertEqual(a['final_state']['steadfast'],1)
        incoming(friend,100,b,raid)
        self.assertEqual(a['final_state']['steadfast'],1)
        a['hp']=0
        self.assertEqual(incoming(friend,100,b,raid),100)

    def test_revenge_only_direct_real_damage_not_recoil(self):
        state=self.state('middle_revenge');a,b=state['sides'].values()
        self.tap(state,'smack',side='b')
        debt=a['final_state']['blood_debt'];self.assertGreater(debt,0)
        self.tap(state,'bum_punch')
        self.assertEqual(a['final_state']['blood_debt'],debt)
        a['final_state']['blood_debt']=1000;a['resource']=100
        event=self.tap(state,'whole_family')
        self.assertEqual(a['final_state']['blood_debt'],0)
        self.assertEqual(event['self_damage'],(event['damage']+4)//5)

    def test_pointillist_six_rolls_one_bleed_and_one_pet_proc(self):
        state=self.state('ring_pointillist');self.prepare(state)
        with patch('arena_engine.pet_after_action',return_value=[]) as pet:
            event=self.tap(state,'red_etude')
        self.assertEqual(len(event['hit_results']),6)
        self.assertEqual(sum(e['id']=='bleed' for e in state['sides']['b']['effects']),1)
        pet.assert_called_once()

    def test_fauvist_one_summon_lifetime_and_no_recursive_procs(self):
        state=self.state('ring_fauvist');a,b=state['sides'].values()
        self.tap(state,'arch_ring_fauvist')
        self.assertEqual(a['final_state']['beast'],3)
        a['resource']=100
        with patch('arena_engine.pet_after_action',return_value=[]) as pet:
            event=self.tap(state,'first_stroke')
        self.assertGreater(event['follower_damage'],0);pet.assert_called_once()
        self.assertEqual(a['final_state']['beast'],2)
        for _ in range(2):self.tap(state,'bum_punch')
        self.assertEqual(a['final_state']['beast'],0)
        a['resource']=100;self.tap(state,'arch_ring_fauvist')
        self.prepare(state);a['resource']=100
        event=self.tap(state,'last_stroke')
        self.assertEqual(len(event['hit_results']),2)
        self.assertEqual(event['follower_damage'],0)

    def test_dihui_guard_opens_counter_and_full_miss_keeps_it(self):
        state=self.state('pinky_dihui');a,b=state['sides'].values()
        self.tap(state,'arch_pinky_dihui')
        self.tap(state,'smack',side='b')
        self.assertGreater(a['final_state']['counter_until'],a['own_turns'])
        a['resource']=100;self.tap(state,'moon_arc',roll=.99)
        self.assertGreater(a['final_state']['counter_until'],a['own_turns'])
        a['resource']=100;event=self.tap(state,'moon_arc')
        self.assertFalse(event['critical'])
        self.assertEqual(a['final_state']['counter_until'],0)

    def test_tiangang_focus_spent_on_hit_only_and_vulnerability(self):
        state=self.state('pinky_tiansha');a=state['sides']['a']
        a['mechanics']=dict(focus=3)
        self.tap(state,'falling_star',roll=.99)
        self.assertEqual(a['mechanics']['focus'],3)
        a['resource']=100;event=self.tap(state,'falling_star')
        self.assertEqual(event['skill_name'],'Небо не выдержало')
        self.assertEqual(a['mechanics']['focus'],1)
        self.assertTrue(any(e['id']=='final_heaven_open' for e in a['effects']))

    def test_saved_counters_and_snapshots_are_detached(self):
        state=self.state('mge_bro');self.prepare(state)
        snap=battle_status_snapshot(state)
        state['sides']['a']['final_state']['dominance']=0
        self.assertEqual(snap['a']['final_state']['dominance'],3)
        state=json.loads(json.dumps(state))
        self.assertEqual(branch(state['sides']['a']),'mge_bro')

    def test_all_paths_in_native_raid_rounds(self):
        from arena_engine import skill_restriction
        from arena_raid_engine import pair_state
        for key,(cls,_,_) in FINALS.items():
            for boss in ('lei_heng','doofenshmirtz','kit'):
                with self.subTest(key=key,boss=boss):
                    sid=PRIMARY[key]
                    natives=[k for k,s in BUILTIN_SKILLS.items() if s.class_id==cls and not k.startswith('arch_')]
                    loadout=list(dict.fromkeys([sid,'arch_'+key]+natives))[:4]
                    source=dict(slave_id=10,owner_id=10,class_id=cls,level=20,archclass_id=key,archclass_stage=20,loadout=loadout)
                    party=[dict(actor_id=10,fighter_id=10,personal=True,slave_owner=None)]
                    raid=create_raid_state(party,[source],FIGHTER_CLASSES,BUILTIN_SKILLS,boss)
                    for turn in range(5):
                        if raid['finished']:break
                        player=raid['players']['10'];a=player['fighter']
                        choices=[]
                        for move in a['loadout']+['bum_punch']:
                            v=effective_skill(pair_state(a,raid['boss']),'a',move)
                            if not a['cooldowns'].get(move) and gift_cost(a,v)<=a['resource'] and not skill_restriction(a,v):choices.append(move)
                        player['selected']=choices[turn%len(choices)] if choices else 'defend'
                        resolve_round(raid,BUILTIN_SKILLS,random.Random(turn))
                        self.assertGreaterEqual(a['resource'],0)
                        self.assertLessEqual(a['resource'],a['stats']['resource_max'])
                        self.assertLessEqual(len(a['loadout']),4)
                    self.assertEqual(json.loads(json.dumps(raid)),raid)


@unittest.skipUnless(shutil.which('node'),'Node needed')
class FinalStatusTests(unittest.TestCase):
    run_client=status_tests.StatusClientTests.run_client
    statuses=status_tests.StatusClientTests.statuses

    def test_final_counters_and_two_choice_order_are_readable(self):
        side=dict(own_turns=4,final_state=dict(dominance=3,beast=2,counter_until=6),
                  mechanics=dict(enemy_prescript=dict(skill_id='a',allowed=['a','b'],penalty=12)),
                  skill_details=[dict(skill_id='a',name='Первый'),dict(skill_id='b',name='Второй')])
        items=self.statuses(side)
        self.assertTrue(any(i['name']=='Доминирование' and i['count']=='3/3' for i in items))
        order=next(i for i in items if i['name']=='Предписание противника')
        self.assertIn('Первый',order['detail']);self.assertIn('Второй',order['detail'])


if __name__=='__main__':unittest.main()
