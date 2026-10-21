"""Approved Oct 18 balance: actual resolver, no live data or battle AI."""
import copy
import json
import unittest
from unittest.mock import patch

from arena_engine import (BUILTIN_SKILLS, create_battle_state, effective_skill,
                          resolve_skill, validate_skill)
from arena_rpg import rpg_modifiers, rpg_received_damage
from arena_mastery import modifiers as mastery_modifiers
from arena_archclasses import obey_enemy_prescript
from arena_raid_engine import native_attack
from test_arena_rebalance import FixedRoll


class ApprovedBalanceTests(unittest.TestCase):
    def state(self, cls='mage', arch='', stage=20, level=20):
        state=create_battle_state(dict(slave_id=10,owner_id=10,class_id=cls,
            archclass_id=arch,archclass_stage=stage,level=level,progression_level=20),
            dict(slave_id=20,owner_id=20,class_id='jock',level=20))
        for side in state['sides'].values():
            side['hp']=side['stats']['max_hp']=1000
            side['loadout']=list(BUILTIN_SKILLS)
            side.setdefault('mechanics',{})
        return state

    def tap(self, state, sid, side='a', miss=False, **kwargs):
        state['active_side']=side
        state['sides'][side]['cooldowns'].pop(sid,None)
        return resolve_skill(state,side,sid,rng=FixedRoll(.99 if miss else 0),
                             advance_turn=False,**kwargs)

    def test_ragamuffin_free_fallback_is_pure_and_preserves_preparation(self):
        state=self.state('ragamuffin');actor=state['sides']['a']
        for combo in ([],['a','b','c']):
            actor['mastery_state']=dict(street_ready=True,combo=combo)
            actor['resource']=0
            before=copy.deepcopy(state)
            skill=effective_skill(state,'a','bum_punch')
            self.assertEqual(skill.cost,0)
            self.assertEqual(state,before)
            validate_skill(state,'a','bum_punch')
            self.assertEqual(state,before)
        self.tap(state,'bum_punch')
        self.assertGreaterEqual(actor['resource'],0)

    def test_street_finisher_cost_refund_and_level_fifteen_skill(self):
        state=self.state('ragamuffin');actor=state['sides']['a']
        actor['mastery_state']=dict(combo=['a','b','c'])
        self.tap(state,'bum_punch')
        self.assertEqual(actor['resource'],90)
        for level,power in ((15,16),(18,20),(20,20)):
            actor['level']=level
            self.assertEqual(effective_skill(state,'a','mastery_ragamuffin').power,power)

    def test_street_fallback_checks_actual_discount_and_tax_without_consuming_them(self):
        state=self.state('ragamuffin');a=state['sides']['a']
        a['mastery_state']=dict(combo=['a','b','c']);a['hp']=100;a['resource']=16
        a['mirror_gifts']=['nerve']
        before=copy.deepcopy(state)
        self.assertEqual(effective_skill(state,'a','bum_punch').name,'Последний из подворотни')
        self.assertEqual(state,before)
        a['effects'].append(dict(id='tax',kind='skill_cost_flat',value=15,duration=3))
        before=copy.deepcopy(state)
        self.assertEqual(effective_skill(state,'a','bum_punch').cost,0)
        self.assertEqual(state,before)

    def test_base_mastery_economy(self):
        state=self.state('jock');a=state['sides']['a']
        a['effects']=[dict(id='evolution_prepared',kind='prepared_attack',value=1,duration=2)]
        self.assertEqual(effective_skill(state,'a','smack').power,27)
        event=self.tap(state,'smack');self.assertEqual(len(event['hit_results']),3)
        state=self.state('thumb');a=state['sides']['a'];a['mechanics']['order']=3
        self.assertEqual(effective_skill(state,'a','warning_shot').accuracy,
                         min(100,BUILTIN_SKILLS['warning_shot'].accuracy+5))
        self.tap(state,'warning_shot');self.assertEqual(a['mechanics']['order'],1)
        state=self.state('middle');a=state['sides']['a'];a['mechanics']['grudge']=3
        self.tap(state,'whole_family');self.assertEqual(a['mechanics']['grudge'],1)
        a['mechanics']['grudge']=3
        self.tap(state,'answer_for_it');self.assertEqual(a['mechanics']['grudge'],2)

    def test_mage_resource_bonuses_add_but_other_multipliers_are_unchanged(self):
        state=self.state();a,b=state['sides'].values()
        a['rpg_state']=dict(mana=3);a['mastery_state']=dict(flow=3)
        skill=effective_skill(state,'a','mana_overload')
        self.assertAlmostEqual(rpg_modifiers(a,b,skill)[1],2.8)
        self.assertEqual(mastery_modifiers(a,b,skill)[1],1)
        self.tap(state,'mana_overload');self.assertEqual(a['resource'],70)
        state=self.state('mage','mage_archmage');a,b=state['sides'].values()
        a['rpg_state']=dict(mana=3,echo_ready=True)
        self.assertAlmostEqual(rpg_modifiers(a,b,effective_skill(state,'a','mana_overload'))[1],2.05*1.6)

    def test_retained_and_final_star_prices(self):
        for arch,power,cost,defense in (('pinky_dihui',26,30,.25),('pinky_tiansha',30,40,None)):
            with self.subTest(arch=arch):
                state=self.state('pinky',arch,10);a=state['sides']['a'];a['mechanics']['focus']=3
                skill=effective_skill(state,'a','arch_'+arch)
                self.assertEqual((skill.power,skill.cost),(power,cost))
                if defense is not None:
                    self.assertTrue(all(e['value']==defense for e in skill.effects if e['kind'].endswith('_defense_pct')))
                self.tap(state,'arch_'+arch);self.assertEqual(a['mechanics']['focus'],2)
        state=self.state('pinky','pinky_tiansha');state['sides']['a']['mechanics']['focus']=3
        self.assertEqual(effective_skill(state,'a','falling_star').cost,55)

    def test_final_variant_buffs_keep_single_action_and_hit_budgets(self):
        cases=[('cutie','femboy','air_kiss',dict(shame=3),28,30,.25),
               ('jock','gachi_actor','smack',dict(grip=2),32,35,None),
               ('jock','mge_bro','butt_peak',dict(dominance=3),40,50,0),
               ('index','index_proxy','last_line',dict(execution=2),34,40,.55)]
        for cls,arch,sid,memory,power,cost,pierce in cases:
            with self.subTest(arch=arch):
                state=self.state(cls,arch);a=state['sides']['a'];a['final_state']=memory
                skill=effective_skill(state,'a',sid)
                self.assertEqual((skill.power,skill.cost),(power,cost))
                if pierce is not None:self.assertEqual(skill.pierce,pierce)
                with patch('arena_engine.pet_after_action',return_value=[]) as pet:
                    event=self.tap(state,sid)
                pet.assert_called_once();self.assertEqual(a['own_turns'],1)
                if arch=='mge_bro':self.assertEqual(len(event['hit_results']),3)

    def test_princess_pose_refund_retained_and_final_evasion(self):
        for stage in (10,20):
            state=self.state('cutie','princess',stage);a=state['sides']['a']
            a['final_state']=dict(whim=2)
            if stage==20:
                skill=effective_skill(state,'a','posing')
                self.assertIn((20,3),[(e['value'],e['turns']) for e in skill.effects if e['kind']=='evasion_flat'])
                self.assertEqual([e['value'] for e in skill.effects if e['kind']=='incoming_damage_multiplier'],[.75])
            self.tap(state,'posing');self.assertEqual(a['resource'],85)
        state=self.state('cutie');a=state['sides']['a'];self.tap(state,'posing')
        self.assertEqual(a['resource'],100-BUILTIN_SKILLS['posing'].cost)

    def test_program_requires_two_distinct_actions_and_an_attack_misses_count(self):
        state=self.state('nerd','programmer');a=state['sides']['a']
        self.tap(state,'go_to_store');self.tap(state,'charging')
        self.assertFalse(a['final_state']['compiled'])
        self.tap(state,'humiliate',miss=True);self.assertTrue(a['final_state']['compiled'])
        self.tap(state,'charging');self.assertFalse(a['final_state']['compiled'])
        self.assertFalse(a['final_state']['compile_attack'])
        state=self.state('nerd','programmer');a=state['sides']['a']
        self.tap(state,'humiliate',miss=True);self.tap(state,'humiliate',miss=True)
        self.assertFalse(a['final_state']['compiled'])
        self.tap(state,'go_to_store');self.assertTrue(a['final_state']['compiled'])
        state=self.state('nerd','programmer');a=state['sides']['a']
        a['final_state']=dict(compile_steps=['humiliate'],compiled=False)
        self.tap(state,'go_to_store');self.assertTrue(a['final_state']['compiled'])

    def test_discipline_suppresses_both_damage_types(self):
        for level in (10,12,18,20):
            state=self.state('thumb','thumb_discipline',level=level)
            self.tap(state,'warning_shot')
            kind='damage_pct' if level>=12 else 'physical_attack_pct'
            self.assertTrue(any(e['kind']==kind and e['value']==-.25 for e in state['sides']['b']['effects']))

    def test_messenger_charge_outcomes_are_deduplicated_for_aoe(self):
        for obeyed,expected in ((True,1),(False,2)):
            state=self.state('index','index_messenger');a,b=state['sides'].values()
            b['is_boss']=True
            b['mechanics']['enemy_prescript']=dict(skill_id='smack',allowed=['smack'],source=10,penalty=12)
            for _ in range(3):obey_enemy_prescript(copy.deepcopy(b),'smack' if obeyed else 'wallop',a)
            self.assertEqual(a['final_state']['guilt'],expected)

    def test_ring_windows_and_stronger_bleed_survive_refresh(self):
        state=self.state('ring');a,b=state['sides'].values()
        self.tap(state,'unfinished_portrait')
        self.assertTrue(all(e['duration']==3 for e in b['effects'] if e.get('id','').startswith('portrait_')))
        b['effects'].append(dict(id='bleed',kind='bleed',value=7,duration=2,mastery_owner=999))
        self.tap(state,'first_stroke')
        bleed=next(e for e in b['effects'] if e.get('id')=='bleed')
        self.assertEqual((bleed['value'],bleed['duration']),(7,3))
        self.assertEqual(bleed['mastery_owner'],999)
        state=self.state('ring','ring_pointillist');a,b=state['sides'].values()
        b['effects']=[dict(id=k,kind=k,value=-.1,duration=3) for k in ('speed_pct','accuracy_flat','magic_defense_pct')]
        skill=effective_skill(state,'a','red_etude');self.assertEqual((skill.power,skill.cost),(28,35))
        event=self.tap(state,'red_etude');self.assertEqual(len(event['hit_results']),6)
        self.assertEqual(next(e['value'] for e in b['effects'] if e.get('id')=='bleed'),8)

    def test_skeleton_respects_shields_without_spending_extra_lifetime(self):
        damage=[]
        for guarded in (False,True):
            state=self.state('mage','mage_necromancer');a,b=state['sides'].values()
            a['rpg_state']=dict(summon=3,summon_power=30)
            if guarded:b['effects']=[dict(id='shield',kind='incoming_damage_multiplier',value=.5,duration=3)]
            before=b['hp'];self.tap(state,'mana_focus');damage.append(before-b['hp'])
            self.assertEqual(a['rpg_state']['summon'],2)
        self.assertAlmostEqual(damage[1],damage[0]/2,delta=1)

    def test_bastion_has_one_guard_and_unrelated_guards_still_stack(self):
        state=self.state('warrior','warrior_knight');a=state['sides']['a']
        a['rpg_state']=dict(steadfast=3)
        a['effects']=[dict(id='other_guard',kind='incoming_damage_multiplier',value=.8,duration=3)]
        self.tap(state,'arch_warrior_knight')
        guards={e['id']:e['value'] for e in a['effects'] if e['kind']=='incoming_damage_multiplier'}
        self.assertNotIn('knight_guard',guards)
        self.assertEqual(guards,dict(other_guard=.8,bastion_guard=.55))

    def test_element_cycle_counts_failed_attempts_but_not_repetitions_or_support(self):
        state=self.state('mage','mage_elementalist');a=state['sides']['a']
        self.tap(state,'mana_shot',miss=True);self.tap(state,'mana_shot',miss=True)
        self.tap(state,'mana_focus');self.assertEqual(a['rpg_state']['elements'],['fire'])
        self.tap(state,'mana_blob',miss=True);a['resource']=60
        self.tap(state,'mana_overload',miss=True)
        self.assertEqual(a['resource'],50)
        self.assertEqual(a['rpg_state']['elements'],[])

    def test_final_rpg_costs_and_required_resources(self):
        state=self.state('mage','mage_necromancer');a=state['sides']['a'];a['rpg_state']=dict(souls=3)
        self.assertEqual(effective_skill(state,'a','mana_barrier').cost,40)
        self.tap(state,'mana_barrier')
        from arena_rpg_combat import incoming
        self.assertEqual(incoming(a,100,'mage_necromancer'),65)
        state=self.state('priest','priest_paladin');a=state['sides']['a'];a['rpg_state']=dict(faith=3,retribution=2)
        skill=effective_skill(state,'a','arch_priest_paladin')
        self.assertEqual((skill.name,skill.cost),('Последний приговор',45))
        state=self.state('hunter','hunter_moon');a=state['sides']['a']
        a['rpg_state']=dict(moon_mark=True,visceral_ready=True,visceral_until=3)
        self.assertEqual((effective_skill(state,'a','arch_hunter_moon').power,effective_skill(state,'a','arch_hunter_moon').cost),(48,50))

    def test_primal_fury_finisher_available_after_real_cooldown(self):
        state=self.state('hunter','hunter_beast');a=state['sides']['a'];a['rpg_state']=dict(beast=3)
        self.tap(state,'arch_hunter_beast')
        for _ in range(3):self.tap(state,'mana_focus')
        self.assertEqual(a['cooldowns'].get('arch_hunter_beast',0),0)
        skill=effective_skill(state,'a','arch_hunter_beast')
        self.assertEqual(skill.name,'Первобытный разрыв')
        state['active_side']='a'
        event=resolve_skill(state,'a','arch_hunter_beast',rng=FixedRoll(),advance_turn=False)
        self.assertEqual(len(event['hit_results']),3)

    def test_paladin_ally_guard_credits_source_once_per_enemy_action(self):
        state=self.state('priest','priest_paladin');a,b=state['sides'].values()
        ally=copy.deepcopy(b);ally.update(controller_id=30,hp=100,effects=[],rpg_state={})
        a['rpg_state']=dict(faith=1)
        self.tap(state,'priest_ward',allies=[a,ally])
        shield=next(e for e in ally['effects'] if e['id']=='paladin_ward')
        self.assertEqual(shield['source_controller'],10)
        raid=dict(players={'10':dict(fighter=a),'30':dict(fighter=ally)})
        for target in (ally,a,copy.deepcopy(ally)):
            rpg_received_damage(target,20,target['hp'],[99,0],raid)
        self.assertEqual(a['rpg_state']['retribution'],1)
        rpg_received_damage(ally,0,ally['hp'],[99,1],raid)
        self.assertEqual(a['rpg_state']['retribution'],1)
        rpg_received_damage(ally,20,ally['hp'],[99,1],raid)
        self.assertEqual(a['rpg_state']['retribution'],2)
        restored=json.loads(json.dumps(raid))
        rpg_received_damage(restored['players']['30']['fighter'],20,100,[99,1],restored)
        self.assertEqual(restored['players']['10']['fighter']['rpg_state']['retribution'],2)
        raid['players']['10']['withdrawn']=True
        rpg_received_damage(ally,20,100,[99,2],raid)
        self.assertEqual(a['rpg_state']['retribution'],2)

    def test_native_raid_damage_credits_shield_owner_for_one_aoe(self):
        state=self.state('priest','priest_paladin');a,b=state['sides'].values()
        ally=copy.deepcopy(b);ally.update(controller_id=30,hp=100,effects=[],rpg_state={})
        a['rpg_state']=dict(faith=1)
        self.tap(state,'priest_ward',allies=[a,ally])
        raid=dict(players={'10':dict(fighter=a),'30':dict(fighter=ally)})
        boss=copy.deepcopy(b);boss['is_boss']=True
        for target in (ally,a):
            event=native_attack(copy.deepcopy(boss),target,'bum_punch',BUILTIN_SKILLS,
                                FixedRoll(),raid_context=raid)
            self.assertGreater(event['damage'],0)
        self.assertEqual(a['rpg_state']['retribution'],1)
        self.assertEqual(ally['rpg_state'].get('retribution',0),0)


if __name__=='__main__':unittest.main()
