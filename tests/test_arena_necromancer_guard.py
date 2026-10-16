"""Summon protection and equipped Elastic Mana share the normal damage hooks."""

import json
import unittest
from dataclasses import replace

from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES
from arena_raid_engine import create_raid_state, resolve_round
from arena_rpg import rpg_received_damage
from arena_rpg_combat import incoming
from test_arena_epic import FixedRoll
import test_arena_rpg as helpers


class NecromancerGuardTests(unittest.TestCase):
    state = helpers.RPGTests.state
    use = helpers.RPGTests.use

    def test_damage_absorption_keeps_its_threshold_and_never_spends_summon(self):
        for level in (10, 11, 12, 18, 20):
            for final in (False, True):
                with self.subTest(level=level, final=final):
                    actor = self.state('mage', 'mage_necromancer')['sides']['a']
                    actor.update(level=level, archclass_stage=20 if final else 10)
                    actor['rpg_state'] = dict(summon=3, death_servants=final)
                    for _ in range(8):
                        self.assertEqual(incoming(actor, 100, 'mage_necromancer'),
                                         75 if level >= 12 else 100)
                        self.assertEqual(actor['rpg_state']['summon'], 3)
                    self.assertEqual(incoming(actor, 0, 'mage_necromancer'), 0)
                    actor['rpg_state']['summon'] = 0
                    self.assertEqual(incoming(actor, 100, 'mage_necromancer'), 100)

    def test_elastic_mana_works_with_summon_from_ten_and_requires_equipped_passive(self):
        for level in (10, 12, 18, 20):
            for equipped in (False, True):
                with self.subTest(level=level, equipped=equipped):
                    state = self.state('mage', 'mage_necromancer')
                    actor = state['sides']['a']
                    actor['level'] = level
                    if not equipped:
                        actor['passive_details'] = [p for p in actor['passive_details']
                            if not any(e['kind'] == 'rpg_barrier_charge' for e in p['effects'])]
                    self.use(state, 'mana_barrier')
                    for _ in range(5):
                        self.use(state, 'bum_punch', 'b')
                    self.assertEqual(actor['rpg_state']['summon'], 3)
                    self.assertEqual(actor['rpg_state'].get('mana', 0), 3 if equipped else 0)

    def test_miss_expired_summon_and_unrelated_branch_give_no_charge(self):
        state = self.state('mage', 'mage_necromancer')
        actor = state['sides']['a']
        self.use(state, 'mana_barrier')
        self.use(state, 'bum_punch', 'b', hit=False)
        self.assertEqual(actor['rpg_state']['summon'], 3)
        self.assertNotIn('mana', actor['rpg_state'])
        actor['rpg_state']['summon'] = 0
        self.use(state, 'bum_punch', 'b')
        self.assertNotIn('mana', actor['rpg_state'])
        actor['rpg_state']['summon'] = 3
        actor['archclass_id'] = 'mage_elementalist'
        self.use(state, 'bum_punch', 'b')
        self.assertNotIn('mana', actor['rpg_state'])

    def test_one_charge_for_attack_and_followup_with_same_action_id(self):
        actor = self.state('mage', 'mage_necromancer')['sides']['a']
        actor['rpg_state'] = dict(summon=3)
        rpg_received_damage(actor, 0, actor['hp'], [20, 0])
        rpg_received_damage(actor, 15, actor['hp'], [20, 0])
        rpg_received_damage(actor, 6, actor['hp'], [20, 0])
        self.assertEqual(actor['rpg_state']['mana'], 1)
        rpg_received_damage(actor, 15, actor['hp'], [20, 1])
        self.assertEqual(actor['rpg_state']['mana'], 2)
        self.assertEqual(actor['rpg_state']['summon'], 3)

    def test_six_hit_attack_gives_one_charge_and_keeps_full_summon(self):
        state = self.state('mage', 'mage_necromancer')
        actor = state['sides']['a']
        self.use(state, 'mana_barrier')
        skills = dict(BUILTIN_SKILLS, bum_punch=replace(BUILTIN_SKILLS['bum_punch'],
                                                       tags=('six_strike',)))
        event = self.use(state, 'bum_punch', 'b', skills=skills)
        self.assertEqual(len(event['hit_results']), 6)
        self.assertTrue(all(part['hit'] for part in event['hit_results']))
        self.assertGreater(event['damage'], 0)
        self.assertEqual(actor['rpg_state']['mana'], 1)
        self.assertEqual(actor['rpg_state']['summon'], 3)

    def test_final_summon_passive_and_lifetime_survive_json_restart(self):
        state = self.state('mage', 'mage_necromancer')
        actor = state['sides']['a']
        actor.update(level=20, archclass_stage=20)
        actor['rpg_state'] = dict(souls=3)
        self.assertEqual(self.use(state, 'mana_barrier')['skill_name'], 'Мёртвые не знают усталости')
        state = json.loads(json.dumps(state))
        actor = state['sides']['a']
        self.use(state, 'bum_punch', 'b')
        self.assertEqual(actor['rpg_state']['summon'], 3)
        self.assertTrue(actor['rpg_state']['death_servants'])
        self.assertEqual(actor['rpg_state']['mana'], 1)
        for remaining in (2, 1, 0):
            self.use(state, 'mana_focus')
            self.assertEqual(actor['rpg_state']['summon'], remaining)
            self.use(state, 'bum_punch', 'b')
            self.assertEqual(actor['rpg_state']['summon'], remaining)
        self.assertEqual(actor['rpg_state']['souls'], 3)
        self.assertEqual(actor['rpg_state']['mana'], 3)

    def test_harvest_still_extends_living_summon_at_eighteen(self):
        state = self.state('mage', 'mage_necromancer')
        actor = state['sides']['a']
        self.use(state, 'mana_barrier')
        self.use(state, 'mana_focus')
        self.assertEqual(actor['rpg_state']['summon'], 2)
        self.use(state, 'bum_punch', 'b')
        self.assertEqual(actor['rpg_state']['summon'], 2)
        self.use(state, 'arch_mage_necromancer')
        self.assertEqual(actor['rpg_state']['summon'], 2)

    def test_raid_boss_hits_charge_mana_but_do_not_shorten_lifetime(self):
        members = [dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)]
        sources = [dict(slave_id=10, owner_id=10, class_id='mage', level=18,
                        archclass_id='mage_necromancer')]
        data = create_raid_state(members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, 'iron')
        player = data['players']['10']
        actor = player['fighter']
        actor['hp'] = actor['stats']['max_hp'] = 1000
        actor['loadout'] = ['mana_barrier', 'mana_focus']
        data['boss']['hp'] = data['boss']['stats']['max_hp'] = 10000
        for sid, remaining, charges in (('mana_barrier', 3, 1), ('mana_focus', 2, 2),
                                         ('mana_focus', 1, 3), ('mana_focus', 0, 0)):
            if remaining == 0:
                actor['rpg_state']['mana'] = 0  # Verify the last hit no longer grants mana.
            player['selected'] = sid
            data['intent'].update(kind='attack', phase=1, targets=['10'], skill='raid_sweep')
            resolve_round(data, BUILTIN_SKILLS, FixedRoll())
            self.assertEqual(actor['rpg_state']['summon'], remaining)
            self.assertEqual(actor['rpg_state']['mana'], charges)


if __name__ == '__main__':
    unittest.main()
