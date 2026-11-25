from copy import deepcopy
import json
import unittest

import arena_cultist as cult
import arena_summons as summons
import arena_unified_queue as queue
from arena_encounters import create_encounter
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state
from arena_raid_engine import BOSS_SKILLS, create_raid_state

SKILLS = {**BUILTIN_SKILLS, **BOSS_SKILLS}


class Hits:
    def random(self):
        return .4

    def uniform(self, *_):
        return 1


def source(uid, klass='cultist'):
    branch = 'cultist_shub' if klass == 'cultist' else ''
    return dict(slave_id=uid, owner_id=uid, class_id=klass, level=20,
                archclass_id=branch, archclass_stage=20,
                loadout=cult.branch_loadout(branch) if branch else ['bum_punch'])


def summon(owner, target, *, predator=False, hp=None):
    cult.after_action(owner, target, SKILLS['cult_brood'], True)
    unit = owner['rpg_state']['cult_brood']
    unit['predator'] = predator
    if hp is not None:
        unit['hp'] = hp
    return unit


def action(data, actor, skill, target, end=None):
    event = queue.submit(data, actor, skill, target, SKILLS, ident=queue.choice(data, actor))
    if end is not None:
        event['end'] = end
    return event


def encounter(count=1):
    data = create_encounter([dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
                            [source(10)], FIGHTER_CLASSES, SKILLS, ['goblin']*count, 30)
    data.update(unified_version=3, qte_modes={})
    for fighter in [data['players']['10']['fighter'], *data['enemies'].values()]:
        fighter['hp'] = fighter['stats']['max_hp'] = 1000
    return data


class SummonTests(unittest.TestCase):
    def test_pvp_can_target_enemy_brood_no_qte_or_player_slot(self):
        data = create_battle_state(source(10), source(20, 'warrior'), action_queue_version=True)
        data['qte_modes'] = {'10': True, '20': True}
        owner, rival = data['sides'].values()
        summon(owner, rival, hp=1)
        target, = summons.units(data)
        self.assertEqual(queue.ready(data), ['a', 'b'])
        with self.assertRaisesRegex(ValueError, 'живого противника'):
            action(data, 'a', 'bum_punch', target)
        health = owner['hp']
        action(data, 'b', 'bum_punch', target, .5)
        action(data, 'a', 'defend', 'b', 1.5)
        queue.advance(data, SKILLS, Hits())
        self.assertEqual(owner['hp'], health)
        self.assertFalse(summons.units(data))
        self.assertNotIn('_queue_wait', data)
        self.assertGreaterEqual(owner['cooldowns']['cult_brood'], 3)
        self.assertTrue(any(e.get('source') == 'b' and e.get('target') == target for e in data['log']))
        summon(owner, rival)
        self.assertNotIn(target, summons.units(data))

    def test_predator_has_a_persisted_autocast_and_dies_with_owner(self):
        data = encounter()
        owner, enemy = data['players']['10']['fighter'], data['enemies']['e1']
        summon(owner, enemy, predator=True)
        queue.initialize(data, SKILLS)
        data = json.loads(json.dumps(data))
        ident, = summons.units(data)
        pending = [e for e in queue.public(data, 10)['entries'] if e['actor'] == ident]
        self.assertEqual([e['skill'] for e in pending], [summons.BITE])
        action(data, '10', 'defend', 'e1', 4.)
        queue.advance(data, SKILLS, Hits())
        strikes = [e for e in data['log'] if e['actor'] == ident and e.get('skill') == summons.BITE]
        self.assertTrue(strikes)
        self.assertGreater(strikes[0]['damage'], 0)
        self.assertEqual(queue.ready(data), ['10'])
        data['players']['10']['fighter']['hp'] = 0
        queue.advance(data, SKILLS, Hits())
        self.assertTrue(data['finished'])
        self.assertNotIn(ident, summons.troop(data))
        self.assertEqual(queue.clock(data)['pending'], [])

    def test_wounded_or_exposed_brood_gets_native_enemy_cast(self):
        data = encounter()
        enemy, owner = data['enemies']['e1'], data['players']['10']['fighter']
        unit = summon(owner, enemy, hp=1)
        before = owner['hp']
        queue.initialize(data, SKILLS)
        key, = summons.units(data)
        self.assertEqual(data['enemy_intents']['e1']['targets'], [key])
        action(data, '10', 'defend', 'e1', queue.clock(data)['pending'][0]['end'] + .2)
        queue.advance(data, SKILLS, Hits())
        self.assertEqual(unit['hp'], 0)
        self.assertEqual(owner['hp'], before)
        self.assertTrue(any(e['target'] == key and e.get('damage',0) > 0 for e in data['log']))

    def test_solo_can_intercept_brood_cast_and_cancel_before_committing(self):
        data = encounter()
        enemy, owner = data['enemies']['e1'], data['players']['10']['fighter']
        enemy['own_turns'] = 1
        unit = summon(owner, enemy)
        queue.initialize(data, SKILLS)
        key, = summons.units(data)
        event, = queue.clock(data)['pending']
        self.assertEqual(event['target'], key)
        queue.intercept(data, 10, 'e1', SKILLS)
        self.assertEqual(event['target'], '10')
        self.assertEqual(data['enemy_intents']['e1']['original_target'], key)
        queue.intercept(data, 10, 'e1', SKILLS)
        self.assertEqual(event['target'], key)
        self.assertNotIn('interceptor', data['enemy_intents']['e1'])
        queue.intercept(data, 10, 'e1', SKILLS)
        resource = owner['resource']
        action(data, '10', 'defend', 'e1', event['end'] + .2)
        self.assertEqual(owner['resource'], resource - 8)
        queue.advance(data, SKILLS, Hits())
        self.assertLess(owner['hp'], 1000)
        self.assertEqual(unit['hp'], 30)

    def test_pve_redirects_to_player_without_cover_in_defense_forecast(self):
        data = create_battle_state(source(10), source(0, 'warrior'), action_queue_version=True)
        data['qte_modes'] = {'10': True}
        owner, rival = data['sides'].values()
        rival['own_turns'] = 1
        summon(owner, rival)
        queue.initialize(data, SKILLS)
        npc, = queue.clock(data)['pending']
        self.assertTrue(npc['target'].startswith('brood:a:'))
        queue.intercept(data, 10, 'b', SKILLS)
        resource = owner['resource']
        action(data, 'a', 'defend', 'b', npc['end'] + .2)
        self.assertEqual(owner['resource'], resource - 8)
        queue.advance(data, SKILLS, Hits())
        stage, = queue.stages(data, 'a', SKILLS)
        self.assertNotIn('cult_cover', stage['members'][0])

    def test_raid_snapshot_marks_real_removal_instead_of_missing_data(self):
        from arena_raid_engine import raid_snapshot
        data = encounter()
        owner = data['players']['10']['fighter']
        self.assertEqual(raid_snapshot(data)['_summons'], {})
        unit = summon(owner, data['enemies']['e1'])
        previous = raid_snapshot(data)['_summons']
        unit['hp'] = 0
        self.assertEqual(raid_snapshot(data)['_summons'], {})
        self.assertEqual(next(iter(previous.values()))['hp'], 30)

    def test_area_hits_both_even_solo_without_using_protector_twice(self):
        base = encounter()
        base['enemy_intents']['e1']['area'] = True
        with_brood = deepcopy(base)
        owner = with_brood['players']['10']['fighter']
        summon(owner, with_brood['enemies']['e1'])
        key, = summons.units(with_brood)
        for state in [base, with_brood]:
            queue.initialize(state, SKILLS)
            action(state, '10', 'defend', 'e1', queue.clock(state)['pending'][0]['end'] + .2)
            queue.advance(state, SKILLS, Hits())
        self.assertEqual(owner['hp'], base['players']['10']['fighter']['hp'])
        self.assertTrue(any(e['target'] == key and e.get('damage',0) > 0 for e in with_brood['log']))
        self.assertEqual(base['enemies']['e1']['own_turns'], with_brood['enemies']['e1']['own_turns'])

    def test_shared_defense_forecast_disables_cover_for_area_only(self):
        data = encounter(2)
        data['qte_modes']['10'] = True
        data['enemy_intents']['e1']['area'] = True
        summon(data['players']['10']['fighter'], data['enemies']['e1'])
        queue.initialize(data, SKILLS)
        for event in queue.clock(data)['pending']:
            event['end'] = 1.
        action(data, '10', 'defend', 'e1', 4.)
        queue.advance(data, SKILLS, Hits())
        stage, = queue.stages(data, '10', SKILLS)
        exposures = {m['encounter_enemy']: 'cult_cover' in m for m in stage['members']}
        self.assertEqual(exposures, {'e1': False, 'e2': True})
        self.assertEqual(stage['cult_cover']['percent'], 30)

    def test_scripted_raid_sweep_also_hits_the_brood(self):
        data = create_raid_state([dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
                                 [source(10)], FIGHTER_CLASSES, BUILTIN_SKILLS, 'iron', unified=True)
        data['qte_modes'] = {}
        owner, boss = data['players']['10']['fighter'], data['boss']
        owner['hp'] = owner['stats']['max_hp'] = 1000
        self.assertTrue(data['intent']['area'])
        summon(owner, boss)
        key, = summons.units(data)
        action(data, '10', 'defend', 'boss', 4.)
        queue.advance(data, SKILLS, Hits())
        self.assertTrue(any(e['actor'] == 'boss' and e['target'] == key and e.get('damage',0) > 0 for e in data['log']))
