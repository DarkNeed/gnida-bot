"""Tractate counterplay is explicit; Whaler and unmarked saves keep old rules."""

from copy import deepcopy
from dataclasses import replace
import json
import random
import unittest

from arena_engine import (BUILTIN_SKILLS, create_battle_state, resolve_skill,
                          restore_turn_resource, _tick)
from arena_plague import infect, begin_turn, clear, healed, actively_healed, actively_restored
from arena_pets import pet_snapshot
from arena_rpg import rpg_effect


class FixedRoll(random.Random):
    def random(self):
        return .5

    def uniform(self, low, high):
        return 1


def state():
    battle = create_battle_state(
        dict(slave_id=10, owner_id=10, class_id='mage', level=20, passive_details=[]),
        dict(slave_id=20, owner_id=20, class_id='mage', level=20, passive_details=[]))
    for side in battle['sides'].values():
        side.update(hp=1000, resource=100, effects=[], loadout=['swamp_miasma', 'mana_focus', 'priest_heal', 'bum_punch'])
        side['stats'].update(max_hp=1000, evasion=0)
    return battle


def trophy(side, stacks=1):
    for _ in range(stacks):
        infect(side, fever=4, turns=3, variant='trophy')


def spores(side, variant='trophy'):
    return next((e['value'] for e in side['effects'] if e['kind'] == 'plague_spores'
                 and e.get('plague_variant', 'boss') == variant), 0)


class MiasmaRebalanceTests(unittest.TestCase):
    def test_direct_damage_halved_with_stats_buffs_armor_crit_and_qte(self):
        skill = BUILTIN_SKILLS['swamp_miasma']
        old = replace(skill, power=10, effects=())
        for physical, magic, armor, critical in ((10, 80, 5, 0), (100, 1, 40, 0), (65, 85, 20, 100)):
            for qte in (None, dict(attack=[True], luck_evasion=False),
                        dict(dodge=[False], pattern_dodge=dict(contacts=[dict(strike=0, weight=1)]))):
                with self.subTest(stats=(physical, magic, armor, critical), qte=qte):
                    battle = state()
                    a, b = battle['sides'].values()
                    a['stats'].update(physical_attack=physical, magic_attack=magic)
                    if critical:
                        a['passive_details'] = [dict(effects=[dict(kind='constellation', value=1)])]
                        a.setdefault('mechanics', {})['focus'] = 5
                    a['effects'] = [dict(id='test', kind='damage_pct', value=.5, duration=4)]
                    b['stats']['magic_defense'] = armor
                    before = deepcopy(battle)
                    old_hit = resolve_skill(before, 'a', skill.skill_id,
                        {**BUILTIN_SKILLS, skill.skill_id: old}, FixedRoll(), advance_turn=False, qte=qte)
                    new_hit = resolve_skill(battle, 'a', skill.skill_id,
                        rng=FixedRoll(), advance_turn=False, qte=qte)
                    self.assertLessEqual(abs(new_hit['damage'] * 2 - old_hit['damage']), 1)
                    self.assertEqual(new_hit['critical'], bool(critical))
                    self.assertEqual(a['resource'], 60)
                    self.assertEqual(a['cooldowns'][skill.skill_id], 3)

    def test_three_turn_fever_refresh_and_spore_cap_six_after_json_reload(self):
        side = state()['sides']['a']
        trophy(side, 5)
        side = json.loads(json.dumps(side))
        self.assertEqual(spores(side), 3)
        self.assertEqual(begin_turn(side), 10)
        self.assertEqual(begin_turn(side), 0)
        _tick(side, tick_dot=False)
        trophy(side)
        self.assertEqual(next(e['duration'] for e in side['effects'] if e['kind'] == 'plague_fever'), 3)
        for _ in range(3):
            self.assertEqual(begin_turn(side), 10)
            _tick(side, tick_dot=False)
        self.assertEqual(begin_turn(side), 6)
        self.assertEqual(spores(side), 3)

    def test_active_restore_removes_exactly_one_spore_not_fever(self):
        for count in (1, 3):
            battle = state()
            actor = battle['sides']['a']
            actor['resource'] = 40
            trophy(actor, count)
            event = resolve_skill(battle, 'a', 'mana_focus', rng=FixedRoll(), advance_turn=False)
            self.assertGreater(event['deliberate_resource_restored'], 0)
            self.assertEqual(spores(actor), count - 1)
            self.assertTrue(any(e['kind'] == 'plague_fever' for e in actor['effects']))
        actor = state()['sides']['a']
        trophy(actor, 3)
        for count in (2, 1, 0):
            actively_restored(actor)
            self.assertEqual(spores(actor), count)
            self.assertTrue(any(e['kind'] == 'plague_fever' for e in actor['effects']))

    def test_no_actual_restore_at_full_energy_and_passive_regen_do_not_cleanse(self):
        battle = state()
        actor = battle['sides']['a']
        trophy(actor, 3)
        resolve_skill(battle, 'a', 'mana_focus', rng=FixedRoll(), advance_turn=False)
        self.assertEqual(spores(actor), 3)
        actor.update(resource=30, own_turns=2)
        restore_turn_resource(actor)
        self.assertGreater(actor['resource'], 30)
        self.assertEqual(spores(actor), 3)

    def test_damaging_resource_refund_is_not_dedicated_restoration(self):
        battle = state()
        actor = battle['sides']['a']
        actor['resource'] = 20
        trophy(actor, 3)
        skill = replace(BUILTIN_SKILLS['bum_punch'], effects=(dict(kind='resource', target='self', value=10),))
        event = resolve_skill(battle, 'a', 'bum_punch', {**BUILTIN_SKILLS, 'bum_punch': skill}, FixedRoll(), advance_turn=False)
        self.assertEqual(event['deliberate_resource_restored'], 0)
        self.assertEqual(spores(actor), 3)

    def test_active_heal_pct_cleanses_at_full_hp_but_failed_heal_does_not(self):
        for amount, chance in ((0, 1), (.1, 1), (.1, 0)):
            battle = state()
            actor = battle['sides']['a']
            trophy(actor, 3)
            skill = replace(BUILTIN_SKILLS['bum_punch'], damage_type=None, power=0,
                effects=(dict(kind='heal_pct', target='self', value=amount, chance=chance),))
            resolve_skill(battle, 'a', 'bum_punch', {**BUILTIN_SKILLS, 'bum_punch': skill}, FixedRoll(), advance_turn=False)
            self.assertEqual(spores(actor), 0 if amount and chance else 3)
            self.assertEqual(any(e['kind'] == 'plague_fever' for e in actor['effects']), not bool(amount and chance))

    def test_miss_and_successful_dodge_do_not_apply_plague_but_charge_full_cost(self):
        for qte in (dict(attack=[False]), dict(attack=[True], dodge=[True])):
            battle = state()
            event = resolve_skill(battle, 'a', 'swamp_miasma', rng=FixedRoll(), advance_turn=False, qte=qte)
            self.assertFalse(event['hit'])
            self.assertEqual(battle['sides']['a']['resource'], 60)
            self.assertFalse(any(e['kind'].startswith('plague_') for e in battle['sides']['b']['effects']))

    def test_cleanse_skill_clears_the_whole_trophy_plague(self):
        battle = state()
        actor = battle['sides']['a']
        trophy(actor, 3)
        skill = replace(BUILTIN_SKILLS['bum_punch'], damage_type=None, power=0,
                        effects=(dict(kind='cleanse_one', target='self', value=1),))
        resolve_skill(battle, 'a', 'bum_punch', {**BUILTIN_SKILLS, 'bum_punch': skill}, FixedRoll(), advance_turn=False)
        self.assertFalse(any(e['kind'].startswith('plague_') for e in actor['effects']))

    def test_priest_cleanses_only_actual_heal_recipient_not_other_passive_healing(self):
        battle = state()
        priest = battle['sides']['a']
        ally = deepcopy(battle['sides']['b'])
        ally.update(hp=100, controller_id=30)
        priest['hp'] = 250
        priest['pet'] = pet_snapshot(dict(id='sandwich', level=1))
        trophy(priest, 3)
        trophy(ally, 3)
        resolve_skill(battle, 'a', 'priest_heal', rng=FixedRoll(), advance_turn=False,
                      allies=[priest, ally])
        self.assertGreater(ally['hp'], 100)
        self.assertFalse(any(e['kind'].startswith('plague_') for e in ally['effects']))
        self.assertGreater(priest['hp'], 250)  # Simultaneous passive sandwich heal.
        self.assertEqual(spores(priest), 3)

    def test_necromancer_life_drain_and_pet_healing_leave_plague(self):
        battle = state()
        actor = battle['sides']['a']
        actor.update(hp=50, archclass_id='mage_necromancer', archclass_stage=10)
        actor['loadout'].append('mana_blob')
        trophy(actor, 3)
        resolve_skill(battle, 'a', 'mana_blob', rng=FixedRoll(), advance_turn=False, qte=dict(attack=[True]))
        self.assertGreater(actor['hp'], 50)
        self.assertEqual(spores(actor), 3)
        actor['hp'] += 1
        healed(actor)
        self.assertEqual(spores(actor), 3)

    def test_dawn_healing_cleanses_all_living_recipients(self):
        battle = state()
        actor = battle['sides']['a']
        ally = deepcopy(battle['sides']['b'])
        for who in (actor, ally):
            trophy(who, 3)
        rpg_effect(actor, battle['sides']['b'], dict(kind='rpg_dawn', value=1), FixedRoll(), allies=[actor, ally])
        self.assertFalse(any(e['kind'].startswith('plague_') for who in (actor, ally) for e in who['effects']))

    def test_cleanse_removes_fever_and_spores_and_boss_rules_remain_unchanged(self):
        side = state()['sides']['a']
        infect(side, spores=3)
        trophy(side, 3)
        self.assertEqual(begin_turn(side), 18)  # Distinct 5+3 and 4+6 diseases.
        actively_healed(side)
        self.assertEqual(spores(side), 0)
        self.assertEqual(spores(side, 'boss'), 3)
        healed(side)
        self.assertEqual(spores(side, 'boss'), 2)
        trophy(side, 3)
        actively_restored(side)
        self.assertEqual(spores(side, 'boss'), 0)
        self.assertEqual(spores(side), 2)
        self.assertTrue(clear(side))
        self.assertFalse(any(e['kind'].startswith('plague_') for e in side['effects']))

    def test_legacy_unmarked_saved_effects_keep_old_counterplay(self):
        side = state()['sides']['a']
        infect(side, spores=3)
        for effect in side['effects']:
            effect.pop('plague_variant')
            effect.pop('damage_per_stack', None)
        self.assertEqual(begin_turn(side), 8)
        healed(side)
        self.assertEqual(spores(side, 'boss'), 2)
        actively_restored(side)
        self.assertFalse(any(e['kind'].startswith('plague_') for e in side['effects']))


if __name__ == '__main__':
    unittest.main()
