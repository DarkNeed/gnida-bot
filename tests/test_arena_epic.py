import json
import unittest
from dataclasses import asdict

from arena_engine import BUILTIN_SKILLS, BUILTIN_PASSIVES, FIGHTER_CLASSES, create_battle_state, resolve_skill, skip_turn, effective_skill, skill_restriction
from arena_epic import epic_modifiers, temporary_buff, temporary_debuff, cleanse_one
from arena_raid_engine import native_attack


class FixedRoll:
    def __init__(self, value=.01):
        self.value = value

    def random(self):
        return self.value

    def uniform(self, low, high):
        return 1

    def choice(self, pool):
        return pool[0]


class EpicTests(unittest.TestCase):
    def state(self, passives=(), cls="ragamuffin"):
        source = dict(slave_id=10, owner_id=10, controlled=False, class_id=cls, level=15,
                      passive_details=[asdict(BUILTIN_PASSIVES[p]) for p in passives])
        state = create_battle_state(source, dict(source, slave_id=20, owner_id=20, passive_details=[]))
        for side in state["sides"].values():
            side["loadout"] = [k for k, v in BUILTIN_SKILLS.items() if v.class_id == "universal"] + ["bum_punch"]
            side["stats"]["max_hp"] = 1000
            side["hp"] = 1000
        return state

    def use(self, state, skill, value=.01, side="a"):
        state["active_side"] = side
        return resolve_skill(state, side, skill, rng=FixedRoll(value), advance_turn=False)

    def test_desperation_exact_threshold_50_percent_and_no_defense_penalty(self):
        normal = self.state()
        buffed = self.state(["nothing_to_lose"])
        actor = buffed["sides"]["a"]
        actor["hp"] = 350
        original = dict(actor["stats"])
        baseline = self.use(normal, "bum_punch")["damage"]
        damage = self.use(buffed, "bum_punch")["damage"]
        self.assertLessEqual(abs(damage - baseline * 1.5), 1)
        self.assertEqual(actor["stats"], original)
        actor["hp"] = 351
        self.assertEqual(self.use(buffed, "bum_punch")["damage"], baseline)
        actor["hp"] = 1
        self.assertEqual(epic_modifiers(actor, buffed['sides']['b'], BUILTIN_SKILLS['bum_punch'])[1], 1.5)

    def test_desperation_multiplies_other_buffs_instead_of_diluting_bonus(self):
        state = self.state(["nothing_to_lose"])
        actor = state['sides']['a']
        actor['effects'].append(dict(id='boost', kind='damage_pct', value=1, duration=8))
        actor['hp'] = 500
        normal = self.use(state, 'bum_punch')['damage']
        actor['hp'] = 300
        buffed = self.use(state, 'bum_punch')['damage']
        self.assertLessEqual(abs(buffed - normal * 1.5), 1)

    def test_plan_b_persists_consumes_on_attack_not_support_and_rearms_on_miss(self):
        state = self.state(['plan_b'])
        self.assertFalse(self.use(state, 'bum_punch', .99)['hit'])
        state = json.loads(json.dumps(state))
        actor = state['sides']['a']
        self.assertTrue(actor['epic_state']['plan_b_ready'])
        self.use(state, 'safe_house')
        self.assertTrue(actor['epic_state']['plan_b_ready'])
        self.assertEqual(epic_modifiers(actor, state['sides']['b'], BUILTIN_SKILLS['bum_punch']), (25, 1.3))
        self.use(state, 'bum_punch')
        self.assertFalse(actor['epic_state']['plan_b_ready'])
        self.use(state, 'bum_punch', .99)
        self.use(state, 'bum_punch', .99)
        self.assertEqual(epic_modifiers(actor, state['sides']['b'], BUILTIN_SKILLS['bum_punch']), (25, 1.3))

    def test_second_wind_for_attacker_and_defender_once_and_not_lethal(self):
        state = self.state(['second_wind'])
        actor = state['sides']['a']
        actor.update(hp=310, resource=10)
        self.use(state, 'bum_punch', side='b')
        self.assertLessEqual(actor['hp'], 300)
        self.assertEqual(actor['resource'], 50)
        state = json.loads(json.dumps(state))
        actor = state['sides']['a']
        self.use(state, 'bum_punch', side='b')
        self.assertEqual(actor['resource'], 50)
        fresh = self.state(['second_wind'])
        fresh['sides']['a'].update(hp=1, resource=10)
        self.use(fresh, 'bum_punch', side='b')
        self.assertEqual(fresh['sides']['a']['resource'], 10)
        fresh = self.state(['second_wind'])
        fresh['sides']['a'].update(hp=250, resource=90)
        self.use(fresh, 'safe_house')
        self.assertEqual(fresh['sides']['a']['resource'], 100)

    def test_fine_print_counts_real_actions_waits_for_debuff_and_only_once(self):
        state = self.state(['fine_print'])
        actor = state['sides']['a']
        for _ in range(4):
            self.use(state, 'bum_punch')
        self.assertFalse(actor['epic_state'].get('fine_print_used'))
        actor['effects'].append(dict(id='bleed', kind='bleed', value=1, duration=5))
        self.use(state, 'bum_punch')
        self.assertFalse(actor['effects'])
        actor['effects'].append(dict(id='bleed', kind='bleed', value=1, duration=5))
        self.use(state, 'bum_punch')
        self.assertTrue(actor['effects'])
        fresh = self.state(['fine_print'])
        for _ in range(4):
            fresh['active_side'] = 'a'
            skip_turn(fresh)
        self.assertNotIn('epic_state', fresh['sides']['a'])

    def test_last_argument_gated_dynamic_type_and_cost(self):
        state = self.state(cls='nerd')
        actor = state['sides']['a']
        with self.assertRaisesRegex(ValueError, 'четвёртого'):
            self.use(state, 'last_argument')
        actor['own_turns'] = 3
        self.assertEqual(effective_skill(state, 'a', 'last_argument').damage_type, 'magic')
        event = self.use(state, 'last_argument')
        self.assertEqual(event['damage_type'], 'magic')
        self.assertFalse(event['evolved'])
        self.assertEqual(actor['resource'], 50)
        self.assertEqual(actor['cooldowns']['last_argument'], 4)
        actor['stats']['physical_attack'] = 100
        self.assertEqual(effective_skill(state, 'a', 'last_argument').damage_type, 'physical')

    def test_stress_test_unique_negative_types_capped_and_not_consumed(self):
        normal, combo = self.state(), self.state()
        enemy = combo['sides']['b']
        enemy['effects'] = [dict(id=str(i), kind=k, value=-1, duration=5) for i,k in enumerate(
            ('accuracy_flat', 'evasion_flat', 'speed_pct', 'physical_defense_pct', 'magic_defense_pct', 'damage_pct'))]
        enemy['effects'] += [dict(id='extra', kind='accuracy_flat', value=-1, duration=5)]
        enemy['effects'] += [dict(id='vulnerability', kind='damage_taken_pct', value=.25, duration=3, consume_on_hit=True)]
        self.assertEqual(epic_modifiers(combo['sides']['a'], enemy, BUILTIN_SKILLS['stress_test'])[1], 2)
        effects = list(enemy['effects'])
        self.use(combo, 'stress_test')
        self.assertEqual(enemy['effects'], effects)
        self.assertEqual(normal['sides']['a']['resource'], 100)

    def test_unsubscribe_removes_buffs_not_debuffs_inherent_or_boss_mechanics(self):
        state = self.state()
        enemy = state['sides']['b']
        enemy['is_boss'] = True
        buffs = [dict(id='shield', kind='incoming_damage_multiplier', value=.65, duration=2),
                 dict(id='atk', kind='damage_pct', value=.3, duration=2)]
        keep = [dict(id='bleed', kind='bleed', value=2, duration=3),
                dict(id='inherent', kind='damage_pct', value=.3, duration=1000000),
                dict(id='mechanic', kind='boss_phase', value=1, duration=2)]
        enemy['effects'] = buffs + keep
        self.use(state, 'unsubscribe', .99)
        self.assertEqual(enemy['effects'], buffs + keep)
        state['sides']['a']['cooldowns'] = {}
        self.use(state, 'unsubscribe')
        self.assertEqual(enemy['effects'], keep)
        self.assertTrue(all(temporary_buff(e) for e in buffs))
        self.assertTrue(temporary_buff(dict(id='prepared', kind='prepared_attack', value=0, duration=2)))

    def test_safe_house_multiplicative_with_enemy_damage_debuff_and_expires(self):
        state = self.state()
        normal = self.use(state, 'bum_punch', side='b')['damage']
        state = self.state()
        self.use(state, 'safe_house')
        state['sides']['b']['effects'].append(dict(id='adoration', kind='damage_pct', value=-.4, duration=2))
        guarded = self.use(state, 'bum_punch', side='b')['damage']
        self.assertLessEqual(abs(guarded - normal * .65 * .6), 1)
        self.use(state, 'bum_punch')
        self.assertFalse(any(e['kind']=='incoming_damage_multiplier' for e in state['sides']['a']['effects']))

    def test_not_today_heals_cleanses_twice_limit_survives_save(self):
        state = self.state()
        actor = state['sides']['a']
        for _ in range(2):
            actor.update(hp=600, resource=100, cooldowns={})
            actor['effects'] = [dict(id='bleed', kind='bleed', value=3, duration=4)]
            self.use(state, 'not_today')
            self.assertEqual(actor['hp'], 800)
            self.assertFalse(actor['effects'])
            self.assertEqual(actor['resource'], 65)
            state = json.loads(json.dumps(state))
            actor = state['sides']['a']
        self.assertTrue(skill_restriction(actor, BUILTIN_SKILLS['not_today']))
        actor.update(resource=100, cooldowns={})
        with self.assertRaisesRegex(ValueError, 'Два применения'):
            self.use(state, 'not_today')

    def test_hands_off_updates_without_stacking_and_native_raid_passives(self):
        state = self.state(['nothing_to_lose', 'plan_b'])
        actor, target = state['sides'].values()
        self.use(state, 'hands_off')
        actor.update(resource=100, cooldowns={})
        self.use(state, 'hands_off')
        self.assertEqual(len(target['effects']), 2)
        actor.update(hp=300, resource=100)
        first = native_attack(actor, target, 'bum_punch', BUILTIN_SKILLS, FixedRoll(.99))
        self.assertFalse(first['hit'])
        self.assertTrue(actor['epic_state']['plan_b_ready'])
        saved = json.loads(json.dumps(actor))
        event = native_attack(saved, target, 'bum_punch', BUILTIN_SKILLS, FixedRoll())
        self.assertTrue(event['hit'])
        self.assertFalse(saved['epic_state']['plan_b_ready'])
        self.assertIn('epic_state', event['status_after']['a'])

    def test_combined_epics_form_a_real_damage_build(self):
        state = self.state(['nothing_to_lose', 'plan_b'])
        actor, enemy = state['sides'].values()
        actor['hp'] = 300
        actor['epic_state'] = {'plan_b_ready': True}
        enemy['effects'] = [dict(id=k, kind=k, value=-1, duration=3) for k in
                            ('accuracy_flat', 'evasion_flat', 'speed_pct', 'physical_defense_pct', 'damage_pct')]
        accuracy, multiplier = epic_modifiers(actor, enemy, BUILTIN_SKILLS['stress_test'])
        self.assertEqual(accuracy, 25)
        self.assertAlmostEqual(multiplier, 3.9)

    def test_cleanse_handles_vulnerability_but_preserves_damage_reduction(self):
        state = self.state()
        actor = state['sides']['a']
        vulnerability = dict(id='vulnerable', kind='damage_taken_pct', value=.25, duration=3)
        guard = dict(id='guard', kind='damage_taken_pct', value=-.25, duration=3)
        self.assertTrue(temporary_debuff(vulnerability))
        self.assertFalse(temporary_debuff(guard))
        self.assertTrue(temporary_buff(guard))
        actor['effects'] = [guard, vulnerability]
        self.assertTrue(cleanse_one(actor, FixedRoll()))
        self.assertEqual(actor['effects'], [guard])

    def test_universal_attacks_work_for_every_base_class(self):
        for cls in FIGHTER_CLASSES:
            with self.subTest(cls=cls):
                state = self.state(cls=cls)
                actor = state['sides']['a']
                expected = 'magic' if actor['stats']['magic_attack'] > actor['stats']['physical_attack'] else 'physical'
                self.assertEqual(self.use(state, 'stress_test')['damage_type'], expected)
                actor['own_turns'] = 3
                self.assertEqual(self.use(state, 'last_argument')['damage_type'], expected)

    def test_new_battle_resets_epic_uses_and_low_level_cannot_attack(self):
        old = self.state(['second_wind'])
        old['sides']['a'].update(hp=250, resource=0)
        self.use(old, 'bum_punch')
        self.assertTrue(old['sides']['a']['epic_state']['second_wind_used'])
        fresh = self.state(['second_wind'])
        self.assertNotIn('epic_state', fresh['sides']['a'])
        fresh['sides']['a']['level'] = 9
        with self.assertRaisesRegex(ValueError, '10 уровень'):
            self.use(fresh, 'stress_test')


if __name__ == '__main__':
    unittest.main()
