"""Mage balance regressions, including real alternating turns and paid casts."""

import json
import unittest

from arena_engine import (BUILTIN_SKILLS, FIGHTER_CLASSES, battle_status_snapshot,
                          effective_skill, resolve_skill, skip_turn)
from arena_raid_engine import create_raid_state, resolve_round
from arena_rpg import rpg_modifiers
from arena_rpg_descriptions import skill_description
from test_arena_epic import FixedRoll
import test_arena_rpg as helpers


class MageReviewTests(unittest.TestCase):
    state = helpers.RPGTests.state
    use = helpers.RPGTests.use

    def test_echo_two_distinct_casts_count_even_when_both_miss(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        self.use(state, 'mana_shot', hit=False)
        self.assertEqual(actor['rpg_state']['echo_steps'], ['mana_shot'])
        self.assertFalse(actor['rpg_state'].get('echo_ready'))
        self.use(state, 'mana_blob', hit=False)
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.assertNotIn('mana', actor['rpg_state'])

    def test_echo_repeats_preserve_progress_and_support_alone_cannot_ready(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        for sid in ('mana_focus', 'mana_focus', 'mana_barrier', 'mana_focus'):
            self.use(state, sid)
        self.assertEqual(actor['rpg_state']['echo_steps'], ['mana_focus', 'mana_barrier'])
        self.assertFalse(actor['rpg_state'].get('echo_ready'))
        self.use(state, 'mana_shot', hit=False)
        self.assertTrue(actor['rpg_state']['echo_ready'])

    def test_echo_repeating_attack_keeps_one_step_and_triggering_cast_is_not_boosted(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        self.use(state, 'mana_shot')
        self.use(state, 'mana_shot', hit=False)
        self.assertEqual(actor['rpg_state']['echo_steps'], ['mana_shot'])
        self.assertFalse(actor['rpg_state'].get('echo_ready'))
        expected = self.use(self.state('mage', 'mage_archmage'), 'mana_blob')['damage']
        event = self.use(state, 'mana_blob')
        self.assertEqual(event['damage'], expected)
        self.assertTrue(actor['rpg_state']['echo_ready'])

    def test_echo_foreign_moves_and_timeout_neither_advance_nor_reset(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        self.use(state, 'mana_shot', hit=False)
        self.use(state, 'bum_punch')
        state['active_side'] = 'a'
        skip_turn(state)
        self.assertEqual(actor['rpg_state']['echo_steps'], ['mana_shot'])
        self.assertFalse(actor['rpg_state'].get('echo_ready'))
        actor['resource'] = 0
        state['active_side'] = 'a'
        with self.assertRaises(ValueError):
            resolve_skill(state, 'a', 'mana_blob', rng=FixedRoll())
        self.assertEqual(actor['rpg_state']['echo_steps'], ['mana_shot'])

    def test_echo_only_archmage_can_prepare_it(self):
        for key in ('', 'mage_necromancer', 'mage_elementalist', 'mage_archmage'):
            with self.subTest(branch=key):
                state = self.state('mage', key)
                if key == 'mage_archmage':
                    state['sides']['a']['level'] = 9
                self.use(state, 'mana_shot')
                self.use(state, 'mana_focus')
                self.assertNotIn('echo_ready', state['sides']['a']['rpg_state'])

    def test_echo_damage_is_sixty_percent_and_multiplies_overload_charges(self):
        for level in (10, 12, 18, 20):
            for sid in ('mana_shot', 'mana_blob', 'mana_overload', 'arch_mage_archmage'):
                if sid.startswith('arch_') and level < 15:
                    continue
                with self.subTest(level=level, skill=sid):
                    damages = []
                    for ready in (False, True):
                        state = self.state('mage', 'mage_archmage')
                        actor, target = state['sides']['a'], state['sides']['b']
                        actor.update(level=level, archclass_stage=10)
                        actor['rpg_state'] = dict(mana=3, echo_ready=ready)
                        spell = effective_skill(state, 'a', sid)
                        multiplier = rpg_modifiers(actor, target, spell)[1]
                        expected = (2.05 if sid == 'mana_overload' else 1) * (1.6 if ready else 1)
                        self.assertAlmostEqual(multiplier, expected)
                        damages.append(self.use(state, sid)['damage'])
                    self.assertAlmostEqual(damages[1], damages[0] * 1.6, delta=1.3)

    def test_echo_discount_starts_at_twelve_and_payment_is_real_on_miss(self):
        for level in (10, 11, 12, 18):
            for sid, price in (('mana_shot', 10), ('mana_blob', 25), ('mana_overload', 35)):
                with self.subTest(level=level, skill=sid):
                    state = self.state('mage', 'mage_archmage')
                    actor = state['sides']['a']
                    actor['level'] = level
                    actor['rpg_state'] = dict(echo_ready=True)
                    expected = max(1, price - 10) if level >= 12 else price
                    self.assertEqual(effective_skill(state, 'a', sid).cost, expected)
                    event = self.use(state, sid, hit=False)
                    self.assertFalse(event['hit'])
                    self.assertEqual(actor['resource'], 100 - expected)
                    self.assertTrue(actor['rpg_state']['echo_ready'])

    def test_ready_echo_survives_support_foreign_move_and_miss_until_native_hit(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        self.use(state, 'mana_shot')
        self.use(state, 'mana_focus')
        for sid in ('mana_barrier', 'mana_focus', 'bum_punch'):
            self.use(state, sid)
            self.assertTrue(actor['rpg_state']['echo_ready'])
        self.use(state, 'mana_overload', hit=False)
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.use(state, 'mana_overload')
        self.assertFalse(actor['rpg_state']['echo_ready'])
        self.assertEqual(actor['rpg_state']['echo_steps'], [])

    def test_eighteen_erasure_seeds_next_chain_and_restart_keeps_progress(self):
        for level in (15, 18):
            with self.subTest(level=level):
                state = self.state('mage', 'mage_archmage')
                actor = state['sides']['a']
                actor['level'] = level
                actor['rpg_state'] = dict(echo_ready=True)
                self.use(state, 'arch_mage_archmage')
                steps = ['arch_mage_archmage'] if level >= 18 else []
                self.assertEqual(actor['rpg_state']['echo_steps'], steps)
                snapshot = battle_status_snapshot(state)
                state = json.loads(json.dumps(state))
                self.use(state, 'mana_focus')
                self.assertEqual(bool(state['sides']['a']['rpg_state'].get('echo_ready')), level >= 18)
                self.assertEqual(snapshot['a']['rpg_state']['echo_steps'], steps)

    def test_saved_old_three_step_chain_can_finish_without_resetting(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        actor['rpg_state'] = dict(echo_steps=['mana_shot', 'mana_blob'])
        self.use(state, 'mana_shot', hit=False)
        self.assertTrue(actor['rpg_state']['echo_ready'])

    def test_mana_passive_all_branches_cap_and_preserve_on_missed_overload(self):
        for key in ('', 'mage_archmage', 'mage_elementalist', 'mage_necromancer'):
            with self.subTest(branch=key):
                state = self.state('mage', key)
                actor = state['sides']['a']
                for _ in range(4):
                    self.use(state, 'mana_shot')
                self.assertEqual(actor['rpg_state']['mana'], 3)
                self.use(state, 'mana_overload', hit=False)
                self.assertEqual(actor['rpg_state']['mana'], 3)
                self.use(state, 'mana_overload')
                self.assertEqual(actor['rpg_state']['mana'], 0)

    def test_necromancer_leech_uses_actual_hp_and_cannot_heal_on_miss(self):
        for sid in ('mana_blob', 'arch_mage_necromancer'):
            with self.subTest(skill=sid):
                state = self.state('mage', 'mage_necromancer')
                actor, target = state['sides']['a'], state['sides']['b']
                actor['hp'] = 100
                actor['rpg_state'] = dict(souls=3)
                self.use(state, sid, hit=False)
                self.assertEqual(actor['hp'], 100)
                self.assertEqual(actor['rpg_state']['souls'], 3)
                target['hp'] = 10
                self.use(state, sid)
                self.assertEqual(actor['hp'], 103)
                self.assertEqual(actor['rpg_state']['souls'], 0 if sid.startswith('arch_') else 3)

    def alternate(self, state, sid, rng=None):
        """No free resource/cooldown resets: let the target really take its turn."""
        event = resolve_skill(state, 'a', sid, rng=rng or FixedRoll())
        resolve_skill(state, 'b', 'bum_punch', rng=FixedRoll())
        return event

    def test_real_echo_rotation_without_refills_or_cooldown_resets(self):
        state = self.state('mage', 'mage_archmage')
        actor = state['sides']['a']
        actor['loadout'] = ['mana_shot', 'mana_blob', 'mana_focus', 'mana_overload']
        self.alternate(state, 'mana_shot', FixedRoll(.99))
        self.alternate(state, 'mana_focus')
        self.assertTrue(actor['rpg_state']['echo_ready'])
        self.assertEqual(actor['resource'], 100)
        self.alternate(state, 'mana_overload')
        self.assertEqual(actor['resource'], 75)
        self.assertEqual(actor['cooldowns']['mana_overload'], 3)
        self.assertFalse(actor['rpg_state']['echo_ready'])

    def test_real_barrier_lasts_two_enemy_attacks_and_grants_passive_charges(self):
        for key in ('', 'mage_archmage', 'mage_elementalist'):
            with self.subTest(branch=key):
                state = self.state('mage', key)
                actor = state['sides']['a']
                self.alternate(state, 'mana_barrier')
                self.assertEqual(actor['rpg_state']['mana'], 1)
                self.alternate(state, 'mana_focus')
                self.assertEqual(actor['rpg_state']['mana'], 2)
                self.alternate(state, 'mana_focus')
                self.assertEqual(actor['rpg_state']['mana'], 2)
                self.assertFalse(any(e.get('id') == 'mana_barrier' for e in actor['effects']))

    def test_real_elementalist_rotation_readies_final_without_extra_slots(self):
        state = self.state('mage', 'mage_elementalist')
        actor = state['sides']['a']
        actor.update(level=20, archclass_stage=20)
        actor['loadout'] = ['mana_overload', 'mana_shot', 'mana_blob', 'arch_mage_elementalist']
        for sid in ('mana_overload', 'mana_shot', 'mana_blob'):
            self.alternate(state, sid)
        self.assertEqual(actor['resource'], 50)  # 100 - 35 - 10 - 25 + 20
        self.assertEqual(actor['rpg_state']['elements'], [])
        self.assertEqual(effective_skill(state, 'a', 'arch_mage_elementalist').name, 'Катаклизм')
        event = resolve_skill(state, 'a', 'arch_mage_elementalist', rng=FixedRoll())
        self.assertEqual(len(event['hit_results']), 3)
        self.assertEqual(actor['resource'], 0)
        self.assertFalse(any(e.get('id') in ('rpg_burn', 'rpg_frost', 'rpg_conductivity')
                             for e in state['sides']['b']['effects']))

    def test_real_necromancer_support_ticks_summon_without_creating_new_one(self):
        state = self.state('mage', 'mage_necromancer')
        actor = state['sides']['a']
        actor['loadout'] = ['mana_barrier', 'mana_focus', 'mana_blob', 'arch_mage_necromancer']
        self.alternate(state, 'mana_barrier')
        # An enemy hit consumes one action of the skeleton's lifetime at 12+.
        self.assertEqual(actor['rpg_state']['summon'], 2)
        self.assertNotIn('mana', actor['rpg_state'])  # A summon is not a mana barrier.
        self.alternate(state, 'mana_focus')
        self.assertEqual(actor['rpg_state']['souls'], 1)
        self.assertEqual(actor['rpg_state']['summon'], 0)
        self.alternate(state, 'mana_focus')
        self.assertEqual(actor['rpg_state']['souls'], 1)
        self.assertEqual(actor['rpg_state']['summon'], 0)

    def test_raid_missed_attack_and_support_prepare_echo_and_pay_once(self):
        members = [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)]
        sources = [dict(slave_id=10, owner_id=10, class_id='mage', level=18,
                        archclass_id='mage_archmage')]
        data = create_raid_state(members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, 'iron')
        player = data['players']['10']
        actor = player['fighter']
        actor['hp'] = actor['stats']['max_hp'] = 1000
        actor['loadout'] = ['mana_shot', 'mana_focus', 'mana_blob', 'mana_overload']
        data['boss']['hp'] = data['boss']['stats']['max_hp'] = 10000
        player['selected'] = 'mana_shot'
        resolve_round(data, BUILTIN_SKILLS, FixedRoll(.99))
        self.assertEqual(actor['rpg_state']['echo_steps'], ['mana_shot'])
        player['selected'] = 'mana_focus'
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertTrue(actor['rpg_state']['echo_ready'])
        player['selected'] = 'mana_overload'
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(actor['resource'], 75)
        self.assertFalse(actor['rpg_state']['echo_ready'])

    def test_mage_descriptions_are_specific_and_echo_bonus_is_current(self):
        for key in ('', 'mage_archmage', 'mage_necromancer', 'mage_elementalist'):
            source = dict(class_id='mage', archclass_id=key)
            for sid in ('mana_shot', 'mana_blob', 'mana_focus', 'mana_barrier', 'mana_overload'):
                with self.subTest(branch=key, skill=sid):
                    description = skill_description(BUILTIN_SKILLS[sid], source)
                    self.assertTrue(description)
                    self.assertNotIn('условия финальной атаки указаны', description)
            if key == 'mage_archmage':
                description = skill_description(BUILTIN_SKILLS['arch_mage_archmage'], source)
                self.assertIn('60%', description)
                self.assertNotIn('35%', description)


if __name__ == '__main__':
    unittest.main()
