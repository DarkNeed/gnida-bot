"""Small moon-hunter buff without extra parry duration or repeated hit procs."""
import unittest

from arena_engine import BUILTIN_SKILLS, effective_skill, resolve_skill
from test_arena_rpg import RPGTests
from test_arena_epic import FixedRoll


class MoonHunterBuffTests(unittest.TestCase):
    def state(self, level=18, final=False):
        s = RPGTests().state('hunter', 'hunter_moon')
        a = s['sides']['a']
        a.update(level=level, archclass_stage=20 if final else 10)
        a['cooldowns'] = dict(hunter_shot=3)
        a['rpg_state'] = dict(visceral_ready=True, visceral_until=10, moon_mark=True)
        return s

    def test_base_judgment_power_and_price_and_existing_milestone(self):
        skill = BUILTIN_SKILLS['arch_hunter_moon']
        self.assertEqual((skill.power, skill.cost, skill.pierce, skill.cooldown), (36, 45, .50, 3))
        self.assertEqual(effective_skill(self.state(15), 'a', skill.skill_id).power, 36)
        self.assertEqual(effective_skill(self.state(18), 'a', skill.skill_id).power, 38)

    def test_hit_reduces_shot_cooldown_by_one_in_addition_to_normal_tick(self):
        for hit, expected in ((True, 1), (False, 2)):
            s = self.state()
            a = s['sides']['a']
            event = resolve_skill(s, 'a', 'arch_hunter_moon', rng=FixedRoll(.01 if hit else .99), advance_turn=False)
            self.assertEqual(event['hit'], hit)
            self.assertEqual(a['cooldowns']['hunter_shot'], expected)
            self.assertEqual(a['resource'], 55)
            self.assertEqual(a['cooldowns']['arch_hunter_moon'], 3)

    def test_final_partial_hit_only_shortens_once_and_final_power_is_unchanged(self):
        s = self.state(20, True)
        a = s['sides']['a']
        skill = effective_skill(s, 'a', 'arch_hunter_moon')
        self.assertEqual((skill.name, skill.power, skill.cost), ('Луна не прощает', 48, 50))
        event = resolve_skill(s, 'a', skill.skill_id, rng=FixedRoll(),
                              advance_turn=False, qte=dict(attack=[True, False]))
        self.assertEqual(len(event['hit_results']), 2)
        self.assertEqual(a['cooldowns']['hunter_shot'], 1)
        self.assertTrue(a['rpg_state']['moon_used'])

    def test_ready_shot_never_gets_negative_cooldown_and_other_visceral_does_not_shorten(self):
        s = self.state()
        a = s['sides']['a']
        a['cooldowns'] = {}
        resolve_skill(s, 'a', 'arch_hunter_moon', rng=FixedRoll(), advance_turn=False)
        self.assertEqual(a['cooldowns'].get('hunter_shot', 0), 0)
        s = self.state()
        resolve_skill(s, 'a', 'hunter_visceral', rng=FixedRoll(), advance_turn=False)
        self.assertEqual(s['sides']['a']['cooldowns']['hunter_shot'], 2)

    def test_parry_window_stays_two_own_actions(self):
        s = RPGTests().state('hunter', 'hunter_moon')
        resolve_skill(s, 'a', 'hunter_shot', rng=FixedRoll(), advance_turn=False)
        s['active_side'] = 'b'
        resolve_skill(s, 'b', 'bum_punch', rng=FixedRoll(), advance_turn=False)
        a = s['sides']['a']
        self.assertEqual(a['rpg_state']['visceral_until'] - a['own_turns'], 2)
