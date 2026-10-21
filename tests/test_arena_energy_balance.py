"""Energy economy with turn-start 8% regen; no live players or database."""
from copy import deepcopy
from dataclasses import replace
import unittest

from arena_engine import (BUILTIN_SKILLS, create_battle_state, effective_skill,
                          resolve_skill, restore_turn_resource, validate_skill)
from arena_class_mechanics import class_after_action
from arena_mirror_effects import gift_cost
from arena_plague import infect
from test_arena_rebalance import FixedRoll


class EnergyBalanceTests(unittest.TestCase):
    def state(self, arch='', stage=20, mastery=False, passives=None):
        source = dict(owner_id=10, slave_id=10, class_id='nerd', level=20,
                      archclass_id=arch, archclass_stage=stage,
                      progression_level=20 if mastery or arch else 0,
                      loadout=['humiliate', 'mother_joke', 'charging', 'go_to_store'])
        if passives is not None:
            source['passive_details'] = passives
        state = create_battle_state(source,
            dict(owner_id=20, slave_id=20, class_id='ragamuffin', level=20))
        for side in state['sides'].values():
            side['hp'] = side['stats']['max_hp'] = 10000
        state['sides']['b']['resource'] = 0
        return state

    def test_economy_refund_is_five_after_third_paid_magic(self):
        s = self.state()
        a = s['sides']['a']
        a['mechanics'] = dict(paid_magic=0)
        for i in range(3):
            event = resolve_skill(s, 'a', 'humiliate', rng=FixedRoll(), advance_turn=False)
            self.assertEqual(a['resource'], 100 - 15 * (i + 1) + (5 if i == 2 else 0))
            self.assertEqual(event['before']['a']['resource'] - event['after']['a']['resource'], 10 if i == 2 else 15)
            self.assertEqual(event['deliberate_resource_restored'], 0)
        self.assertEqual(a['mechanics']['paid_magic'], 0)

    def test_full_cost_paid_on_miss_and_regen_only_at_next_own_turn(self):
        s = self.state()
        a = s['sides']['a']
        event = resolve_skill(s, 'a', 'humiliate', rng=FixedRoll(.99),
                              qte=dict(attack=[False]))
        self.assertFalse(event['hit'])
        self.assertEqual(a['resource'], 85)
        resolve_skill(s, 'b', 'bum_punch', rng=FixedRoll())
        self.assertEqual(a['resource'], 93)
        self.assertEqual(restore_turn_resource(a), 0)

    def test_no_generic_economy_discount_on_native_or_foreign_skills(self):
        skill = BUILTIN_SKILLS['humiliate']
        a = self.state()['sides']['a']
        self.assertEqual(gift_cost(a, skill), 15)
        a['class_id'] = 'jock'
        self.assertEqual(gift_cost(a, skill), 15)
        a['class_id'] = 'nerd'
        a['passive_details'] = []
        self.assertEqual(gift_cost(a, skill), 15)
        a = self.state()['sides']['a']
        for sid in ('tigerslayer_flurry', 'deportator_inator', 'solar_eclipse',
                    'swamp_miasma', 'mana_blob', 'charging', 'go_to_store'):
            self.assertEqual(gift_cost(a, BUILTIN_SKILLS[sid]), BUILTIN_SKILLS[sid].cost)

    def test_prices_are_pure_and_keep_existing_mirror_and_tax(self):
        s = self.state()
        a = s['sides']['a']
        a['hp'] = 1
        a['mirror_gifts'] = ['nerve']
        a['effects'].append(dict(id='tax', kind='skill_cost_flat', value=15, duration=3))
        before = deepcopy(s)
        skill = effective_skill(s, 'a', 'mother_joke')
        for _ in range(3):
            self.assertEqual(skill.cost, 40)
            self.assertEqual(gift_cost(a, skill), 47)  # ceil(40*.8) +15
            self.assertEqual(s, before)
        a['effects'] = []
        self.assertEqual(gift_cost(a, replace(skill, cost=2)), 2)
        self.assertEqual(gift_cost(a, replace(skill, cost=0)), 0)

    def test_validation_requires_full_price_even_when_refund_is_due(self):
        s = self.state()
        a = s['sides']['a']
        a['resource'] = 15
        a['mechanics'] = dict(paid_magic=2)
        validate_skill(s, 'a', 'humiliate')
        resolve_skill(s, 'a', 'humiliate', rng=FixedRoll(), advance_turn=False)
        self.assertEqual(a['resource'], 5)
        s = self.state()
        s['sides']['a']['resource'] = 14
        s['sides']['a']['mechanics'] = dict(paid_magic=2)
        before = deepcopy(s)
        with self.assertRaises(ValueError):
            resolve_skill(s, 'a', 'humiliate', rng=FixedRoll(), advance_turn=False)
        self.assertEqual(s, before)

    def test_branches_and_mastery_keep_only_preexisting_combo_discounts(self):
        for arch, stage in (('', 20), ('programmer', 10), ('programmer', 20),
                            ('hacker', 10), ('hacker', 20)):
            with self.subTest(arch=arch, stage=stage):
                s = self.state(arch, stage)
                a, b = s['sides'].values()
                a['effects'].append(dict(id='charging_damage', kind='next_magic_damage',
                                         value=.6, duration=2))
                b['effects'].append(dict(id='doxxing_magic', kind='magic_defense_pct',
                                         value=-.2, duration=2))
                skill = effective_skill(s, 'a', 'humiliate')
                self.assertEqual(gift_cost(a, skill), skill.cost)
                if arch:
                    sid = 'arch_' + arch
                    a['loadout'].append(sid)
                    variant = effective_skill(s, 'a', sid)
                    expected = variant.cost
                    self.assertEqual(gift_cost(a, variant), expected)
        s = self.state(mastery=True)
        a = s['sides']['a']
        a['mastery_state'] = dict(theory_ready=True)
        skill = effective_skill(s, 'a', 'humiliate')
        self.assertEqual((skill.cost, gift_cost(a, skill)), (5, 5))

    def test_shop_restores_45_and_plague_still_requires_actual_gain(self):
        for initial, cleared in ((50, True), (100, False)):
            s = self.state()
            a = s['sides']['a']
            a['resource'] = initial
            infect(a)
            event = resolve_skill(s, 'a', 'go_to_store', rng=FixedRoll(), advance_turn=False)
            self.assertEqual(a['resource'], min(100, initial + 45))
            self.assertEqual(event['deliberate_resource_restored'], min(100 - initial, 45))
            self.assertEqual(not any(e['kind'].startswith('plague_') for e in a['effects']), cleared)

    def test_defensive_and_setup_prices(self):
        for sid, cost in dict(charging=15, doxxing=20, mother_joke=40,
                              unfinished_portrait=15, armor_split=15, counter_lunge=20,
                              priest_ward=20, priest_cleanse=15).items():
            self.assertEqual(BUILTIN_SKILLS[sid].cost, cost, sid)

    def test_saved_counter_refunds_five_even_on_miss(self):
        a, b = self.state()['sides'].values()
        a['resource'] = 30
        a['mechanics'] = dict(paid_magic=2)
        class_after_action(a, b, BUILTIN_SKILLS['mother_joke'], False, False, False, False)
        self.assertEqual(a['resource'], 35)
        self.assertEqual(a['mechanics']['paid_magic'], 0)
