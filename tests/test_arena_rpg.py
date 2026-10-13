import json
import re
import unittest

from arena_engine import (BUILTIN_SKILLS, create_battle_state, resolve_skill,
                          effective_skill, skip_turn, validate_skill)
from arena_rpg import RPG_BRANCHES
from arena_engine import FIGHTER_CLASSES
from arena_raid_engine import create_raid_state, resolve_round
from test_arena_epic import FixedRoll


class RPGTests(unittest.TestCase):
    def state(self, cls='mage', arch=''):
        source = dict(slave_id=10, owner_id=10, controlled=False, class_id=cls,
                      level=18, archclass_id=arch)
        state = create_battle_state(source, dict(source, slave_id=20, owner_id=20,
                                                 class_id='ragamuffin', archclass_id=''))
        for side in state['sides'].values():
            side['stats']['max_hp'] = 1000
            side['hp'] = 1000
            side['stats']['evasion'] = 0
            side['loadout'] = list(BUILTIN_SKILLS)
        return state

    def use(self, state, skill, side='a', hit=True, **kw):
        state['active_side'] = side
        state['sides'][side]['cooldowns'] = {}
        state['sides'][side]['resource'] = 100
        return resolve_skill(state, side, skill, rng=FixedRoll(.01 if hit else .99),
                             advance_turn=False, **kw)

    def test_native_mage_has_no_elements_and_spends_mana_only_on_hit(self):
        state = self.state()
        for sid in ('mana_shot','mana_blob','mana_focus','mana_barrier','mana_overload'):
            self.assertFalse(any(e['kind']=='burn' for e in effective_skill(state,'a',sid).effects))
        for _ in range(3):
            self.use(state,'mana_shot')
        actor=state['sides']['a']
        self.assertEqual(actor['rpg_state']['mana'],3)
        self.use(state,'mana_overload',hit=False)
        self.assertEqual(actor['rpg_state']['mana'],3)
        baseline=self.use(self.state(),'mana_overload')['damage']
        event=self.use(state,'mana_overload')
        self.assertGreater(event['damage'],baseline*1.9)
        self.assertEqual(actor['rpg_state']['mana'],0)

    def test_branch_guard_and_all_nine_unique_attacks(self):
        for key,(cls,_,_) in RPG_BRANCHES.items():
            with self.subTest(key=key):
                state=self.state(cls,key)
                actor=state['sides']['a']
                actor['rpg_state']={'visceral_ready':True,'visceral_until':2}
                event=self.use(state,'arch_'+key)
                self.assertGreater(event['damage'],0)
                actor['archclass_id']='mage_necromancer' if cls!='mage' else 'hunter_moon'
                with self.assertRaises(ValueError):
                    validate_skill(state,'a','arch_'+key)

    def test_armor_stacks_and_charge_rolls_both_strikes(self):
        state=self.state('warrior')
        for _ in range(4): self.use(state,'armor_split')
        effect=next(e for e in state['sides']['b']['effects'] if e['id']=='armor_split')
        self.assertEqual(effect['value'],-.45)
        event=self.use(state,'steel_charge')
        self.assertEqual(len(event['hit_results']),2)
        self.assertTrue(all(r['hit'] for r in event['hit_results']))

    def test_parry_visceral_consumption_and_two_action_window(self):
        state=self.state('hunter')
        with self.assertRaises(ValueError): validate_skill(state,'a','hunter_visceral')
        self.use(state,'hunter_shot')
        before=state['sides']['a']['hp']
        event=self.use(state,'bum_punch','b')
        self.assertEqual(state['sides']['a']['hp'],before)
        self.assertFalse(event['hit'])
        self.assertTrue(state['sides']['a']['rpg_state']['visceral_ready'])
        self.use(state,'hunter_visceral',hit=False)
        self.assertFalse(state['sides']['a']['rpg_state']['visceral_ready'])
        self.use(state,'hunter_shot')
        self.use(state,'bum_punch','b')
        for _ in range(2):
            state['active_side']='a';skip_turn(state)
        with self.assertRaises(ValueError): validate_skill(state,'a','hunter_visceral')

    def test_boss_parry_reduces_damage_without_losing_attack(self):
        state=self.state('hunter')
        state['sides']['b']['is_boss']=True
        baseline=self.use(self.state('hunter'),'bum_punch','b')['damage']
        self.use(state,'hunter_shot')
        event=self.use(state,'bum_punch','b')
        self.assertTrue(event['hit'])
        self.assertLessEqual(abs(event['damage']-baseline*.65),1)
        self.assertTrue(state['sides']['a']['rpg_state']['visceral_ready'])

    def test_rally_caps_enemy_loss_self_cost_and_skip(self):
        state=self.state('hunter')
        actor=state['sides']['a']
        self.use(state,'bum_punch','b')
        damaged=actor['hp']
        event=self.use(state,'hunter_cut')
        self.assertGreater(actor['hp'],damaged)
        self.assertLessEqual(actor['hp'],1000)
        self.assertLessEqual(actor['hp']-damaged,round(event['damage']*.75))
        self.use(state,'blood_bullets')
        self.assertNotIn('rally',actor['rpg_state'])
        self.use(state,'bum_punch','b')
        state['active_side']='a';skip_turn(state)
        self.assertNotIn('rally',actor['rpg_state'])
        actor['hp']=100
        state['active_side']='a'
        with self.assertRaises(ValueError):validate_skill(state,'a','blood_bullets')

    def test_raid_heal_alive_lowest_ratio_and_no_full_hp_faith(self):
        state=self.state('priest','priest_bishop')
        actor=state['sides']['a']
        ally=dict(actor,hp=100,effects=[],rpg_state={})
        dead=dict(actor,hp=0,effects=[],rpg_state={})
        self.use(state,'priest_heal',allies=[actor,ally,dead])
        self.assertEqual(actor['hp'],1000)
        self.assertEqual(ally['hp'],475)
        self.assertEqual(dead['hp'],0)
        self.assertEqual(actor['rpg_state']['faith'],1)
        self.assertTrue(any(e['id']=='bishop_guard' for e in ally['effects']))
        self.use(state,'priest_heal',allies=[actor])
        self.assertEqual(actor['rpg_state']['faith'],1)

    def test_necromancer_summon_json_restart_three_attacks_then_stops(self):
        state=self.state('mage','mage_necromancer')
        self.use(state,'mana_barrier')
        self.assertEqual(state['sides']['b']['hp'],1000)
        state=json.loads(json.dumps(state))
        for _ in range(3):self.use(state,'mana_focus')
        actor=state['sides']['a']
        self.assertEqual(actor['rpg_state']['summon'],0)
        self.assertEqual(actor['rpg_state']['souls'],3)
        before=state['sides']['b']['hp']
        self.use(state,'mana_focus')
        self.assertEqual(state['sides']['b']['hp'],before)

    def test_elementalist_burn_ticks_support_and_is_consumed_on_meteor_hit(self):
        state=self.state('mage','mage_elementalist')
        self.use(state,'mana_shot')
        enemy=state['sides']['b'];before=enemy['hp']
        self.use(state,'mana_focus','b')
        self.assertEqual(enemy['hp'],before-3)
        self.use(state,'arch_mage_elementalist',hit=False)
        self.assertTrue(any(e['kind']=='burn' for e in enemy['effects']))
        self.use(state,'arch_mage_elementalist')
        self.assertFalse(any(e['kind']=='burn' for e in enemy['effects']))

    def test_archmage_echo_requires_alternating_attacks(self):
        state=self.state('mage','mage_archmage')
        for sid in ('mana_shot','mana_blob','mana_shot'):self.use(state,sid)
        actor=state['sides']['a']
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.use(state,'mana_focus')
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.use(state,'mana_shot',hit=False)
        self.assertFalse(actor['rpg_state']['echo_ready'])

    def test_raid_area_attack_keeps_all_three_warrior_counters_and_one_burn_tick(self):
        for boss in ('iron','doofenshmirtz'):
            with self.subTest(boss=boss):
                members=[dict(actor_id=i,fighter_id=i,personal=True,slave_owner=i) for i in (10,20,30)]
                sources=[dict(slave_id=i,owner_id=i,class_id='warrior',level=18) for i in (10,20,30)]
                data=create_raid_state(members,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,boss)
                data['boss']['hp']=data['boss']['stats']['max_hp']=10000
                data['boss']['effects'].append(dict(id='test_burn',kind='burn',value=3,duration=3))
                data['intent'].update(kind='attack',phase=1,targets=list(data['players']),
                                      skill='raid_sweep' if boss=='iron' else 'doof_shot')
                for p in data['players'].values():
                    p['fighter']['loadout']=['counter_lunge']
                    p['selected']='counter_lunge'
                resolve_round(data,BUILTIN_SKILLS,FixedRoll())
                counters=[int(m.group(1)) for e in data['log']
                          for m in [re.search(r'Контрудар врага: −(\d+) HP',e['text'])] if m]
                self.assertEqual(len(counters),3)
                self.assertEqual(data['boss']['hp'],10000-sum(counters)-3)


if __name__=='__main__':unittest.main()
