"""Resource-only balance for every native class, branches and retained mastery."""
import unittest

from arena_engine import (BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state,
                          effective_skill, resolve_skill, restore_turn_resource)
from test_arena_rebalance import FixedRoll


class EnergyRegenRebalanceTests(unittest.TestCase):
    def state(self, cid, arch='', stage=20, mastery=False, level=20):
        source = dict(owner_id=10, slave_id=10, class_id=cid, level=level,
                      archclass_id=arch, archclass_stage=stage,
                      progression_level=level if mastery or arch else 0)
        state = create_battle_state(source,
            dict(owner_id=20, slave_id=20, class_id='ragamuffin', level=level))
        for side in state['sides'].values():
            side['hp'] = side['stats']['max_hp'] = 10000
            side['stats']['evasion'] = 0
            side['loadout'] = list(BUILTIN_SKILLS)
        return state

    def test_approved_heavy_prices(self):
        for sid, cost in dict(meow=40, butt_peak=50, whole_family=45,
                last_stroke=40, falling_star=45, steel_charge=25,
                warrior_execute=40, mana_overload=40, holy_judgment=40).items():
            self.assertEqual(BUILTIN_SKILLS[sid].cost, cost, sid)

    def test_basic_attacks_heal_and_hunter_prices_are_preserved(self):
        for sid, cost in dict(bum_punch=0, uwu=10, smack=10, bayonet=0,
                first_line=0, recorded=0, first_stroke=0, silent_cut=0,
                mana_shot=10, light_word=10, priest_heal=25, hunter_cut=15,
                hunter_shot=20, hunter_visceral=40, mana_blob=25).items():
            self.assertEqual(BUILTIN_SKILLS[sid].cost, cost, sid)

    def test_deliberate_restore_values_and_unchanged_cooldowns(self):
        for cid, sid, gain, cd in (
            ('nerd', 'go_to_store', 45, 0), ('thumb', 'reload', 30, 3),
            ('index', 'receive_prescript', 35, 3), ('middle', 'grit_teeth', 30, 2),
            ('pinky', 'calm_breath', 30, 3), ('mage', 'mana_focus', 35, 0),
            ('hunter', 'blood_bullets', 30, 2)):
            with self.subTest(sid=sid):
                s = self.state(cid)
                a = s['sides']['a']
                a['resource'] = 0
                resolve_skill(s, 'a', sid, rng=FixedRoll(), advance_turn=False)
                self.assertEqual(a['resource'], gain)
                self.assertEqual(a['cooldowns'].get(sid, 0), cd)
                self.assertEqual(a['hp'], 9000 if cid == 'hunter' else 10000)

    def test_guardian_restore_at_both_stages(self):
        for stage in (10, 20):
            s = self.state('middle', 'middle_guardian', stage)
            a = s['sides']['a']
            a['resource'] = 0
            resolve_skill(s, 'a', 'grit_teeth', rng=FixedRoll(), advance_turn=False)
            self.assertEqual(a['resource'], 30)

    def test_all_classes_keep_eight_percent_once_per_own_turn(self):
        for cid in FIGHTER_CLASSES:
            a = self.state(cid)['sides']['a']
            a.update(resource=0, own_turns=1)
            self.assertEqual(restore_turn_resource(a), 8, cid)
            self.assertEqual(restore_turn_resource(a), 0, cid)

    def test_native_heavy_variants_inherit_one_price_increase(self):
        cases = [
            ('cutie', '', 'meow', 40), ('jock', 'mge_bro', 'butt_peak', 55),
            ('middle', '', 'whole_family', 50), ('middle', 'middle_revenge', 'whole_family', 50),
            ('ring', '', 'last_stroke', 45), ('ring', 'ring_fauvist', 'last_stroke', 45),
            ('pinky', 'pinky_tiansha', 'falling_star', 50),
            ('warrior', 'warrior_knight', 'warrior_execute', 40),
            ('mage', 'mage_elementalist', 'mana_overload', 40),
            ('priest', 'priest_paladin', 'holy_judgment', 40)]
        for cid, arch, sid, cost in cases:
            with self.subTest(sid=sid, arch=arch):
                s = self.state(cid, arch, stage=10)
                a, b = s['sides'].values()
                a['own_turns'] = 5
                a['mechanics'] = dict(grudge=3, focus=3)
                b['effects'] = [dict(id='n'+str(i), kind=k, value=-.1, duration=3)
                    for i, k in enumerate(('speed_pct', 'accuracy_flat', 'magic_defense_pct'))]
                b['hp'] = 100
                self.assertEqual(effective_skill(s, 'a', sid).cost, cost)

    def test_mastery_final_heavies_do_not_revert_to_old_cost(self):
        for cid, sid, cost in (('cutie', 'meow', 40), ('middle', 'whole_family', 45),
                ('ring', 'last_stroke', 45), ('pinky', 'falling_star', 50),
                ('mage', 'mana_overload', 40), ('priest', 'holy_judgment', 45)):
            with self.subTest(cid=cid):
                s = self.state(cid, mastery=True)
                a, b = s['sides'].values()
                a['mechanics'] = dict(grudge=3, focus=3)
                a['mastery_state'] = dict(last_cute='uwu', flow=3, prayers=3)
                b['effects'] = [dict(id='adoration', kind='damage_pct', value=-.4, duration=3),
                                dict(id='slow', kind='speed_pct', value=-.1, duration=3),
                                dict(id='weak', kind='magic_defense_pct', value=-.1, duration=3)]
                self.assertEqual(effective_skill(s, 'a', sid).cost, cost)

    def test_index_mastery_refund_is_six_then_eight(self):
        for level, extra in ((10, 6), (12, 8), (20, 8)):
            s = self.state('index', mastery=True, level=level)
            a = s['sides']['a']
            a.update(resource=40, mechanics=dict(prescript='literal'))
            resolve_skill(s, 'a', 'literal', rng=FixedRoll(), advance_turn=False)
            self.assertEqual(a['resource'], 40 - 20 + 8 + extra)

    def test_final_archclass_price_and_tooltip_inherit_exactly_five(self):
        from arena_evolution import evolution_info
        for cid, arch, sid, memory, cost in (
            ('jock', 'mge_bro', 'butt_peak', dict(dominance=3), 50),
            ('middle', 'middle_guardian', 'whole_family', dict(steadfast=3), 50),
            ('middle', 'middle_revenge', 'whole_family', dict(blood_debt=2500), 55),
            ('ring', 'ring_fauvist', 'last_stroke', dict(beast=1), 50),
            ('pinky', 'pinky_tiansha', 'falling_star', {}, 55)):
            with self.subTest(arch=arch):
                s = self.state(cid, arch)
                a, b = s['sides'].values()
                a['final_state'] = memory
                a['mechanics'] = dict(focus=3, grudge=3)
                b['effects'] = [dict(id='n'+str(i), kind=k, value=-.1, duration=3)
                    for i, k in enumerate(('speed_pct', 'accuracy_flat', 'magic_defense_pct'))]
                self.assertEqual(effective_skill(s, 'a', sid).cost, cost)
                self.assertEqual(evolution_info(BUILTIN_SKILLS[sid], cid, a, b)['cost'], cost)
