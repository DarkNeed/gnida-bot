"""Finite combat revisions, anchor accounting, trophy and real temporary DB flows."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from arena_engine import (BUILTIN_SKILLS, FIGHTER_CLASSES, resolve_skill, effective_skill,
                          validate_skill, fighter_xp_limit, _tick)
from arena_raid_engine import create_raid_state, resolve_round, pair_state, finish_if_needed
from arena_chaplain import set_intent, anchor, rewind, action_before, record_action
from arena_raid_web import raid_view
from handlers.raids import RAID_RE, raid_boss_id, RaidPublisher
from test_arena_rebalance import FixedRoll
import test_arena


def encounter(size=1):
    members = [dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i) for i in (10, 20, 30)[:size]]
    sources = [dict(owner_id=p['actor_id'], slave_id=p['actor_id'], class_id='mage', level=20,
                    granted_skills=['last_amendment'],
                    loadout=['mana_shot', 'mana_focus', 'last_amendment']) for p in members]
    return create_raid_state(members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, 'chaplain')


def choose(data, skill='defend'):
    for p in data['players'].values():
        if not p.get('withdrawn') and p['fighter']['hp'] > 0:
            p['selected'] = skill
    return resolve_round(data, BUILTIN_SKILLS, FixedRoll())


class ChaplainEngineTests(unittest.TestCase):
    def test_command_aliases(self):
        for command in ('/рейд капеллан', '/РЕЙД КАПЕЛЛАН', '/raid chaplain',
                        '/рейд@TestBot Капеллан', ' /рейд каппеллан  '):
            match = RAID_RE.fullmatch(command)
            self.assertIsNotNone(match, command)
            self.assertEqual(raid_boss_id(match), 'chaplain', command)
        self.assertIsNone(RAID_RE.fullmatch('/рейд капеллан лишнее'))

    def test_fixed_level_hp_and_no_entry_gate(self):
        for size in (1, 2, 3):
            d = encounter(size)
            self.assertEqual(d['boss']['level'], 25)
            self.assertEqual(d['boss']['hp'], 720 + 360 * (size - 1))
            self.assertEqual(d['chaplain']['recoveries'], 0)
        for level in (1, 5, 19):
            d = create_raid_state([dict(actor_id=10, fighter_id=10, personal=True, slave_owner=10)],
                [dict(owner_id=10, slave_id=10, class_id='mage', level=level)], FIGHTER_CLASSES, BUILTIN_SKILLS, 'chaplain')
            self.assertEqual(d['boss']['level'], 25)
            self.assertEqual(d['boss']['stats']['max_hp'], 720)

    def test_three_full_heals_touch_only_boss_and_armor_decreases(self):
        from arena_chaplain import transition, INCOMING
        d = encounter(3)
        for phase in range(1, 5):
            self.assertEqual(d['boss']['stats']['max_hp'], 1440)
            self.assertEqual(d['boss']['chaplain_damage_taken'], INCOMING[phase-1])
            d['boss']['hp'] = 100
            before = deepcopy(d['players'])
            changed = transition(d)
            self.assertEqual(changed, phase < 4)
            self.assertEqual(d['players'], before)
            if phase < 4:
                self.assertEqual(d['boss']['hp'], 1440)
                self.assertEqual(d['phase'], phase+1)
            else:
                self.assertEqual(d['boss']['hp'], 100)
        self.assertEqual(d['chaplain']['recoveries'], 3)

    def test_burst_cannot_skip_phase_or_settle_early_victory(self):
        d = encounter()
        for phase in (1, 2, 3):
            d['boss']['hp'] = 1
            set_intent(d)
            choose(d, 'mana_shot')
            self.assertFalse(d['finished'])
            self.assertFalse(d['won'])
            self.assertEqual(d['phase'], phase+1)
            self.assertEqual(d['boss']['hp'], d['boss']['stats']['max_hp'])
            self.assertEqual(d['rewards'], {})
        d['boss']['hp'] = 1
        choose(d, 'mana_shot')
        self.assertTrue(d['finished'])
        self.assertTrue(d['won'])

    def test_ordinary_rewind_is_action_every_5_to_7_rounds_not_three_charges(self):
        d = encounter()
        f = d['players']['10']['fighter']
        f['hp'] = f['stats']['max_hp'] = 10000
        set_intent(d)
        for _ in range(31):
            choose(d)
        events = [e for e in d['log'] if e.get('chaplain_event') == 'rewind']
        # Logs are bounded; the persistent counter still records every action.
        self.assertGreaterEqual(d['chaplain']['rewinds'], 4)
        self.assertEqual(d['chaplain']['recoveries'], 0)
        rounds = [e['round'] for e in events]
        for first, second in zip(rounds, rounds[1:]):
            self.assertTrue(5 <= second-first <= 7)
        for event in events:
            self.assertFalse(any(e['actor']=='boss' and e.get('damage') for e in d['log'] if e['round']==event['round']))
        self.assertEqual(d['round'], 32)

    def test_rewind_restores_previous_combat_not_real_round_afk_or_used_skills(self):
        d = encounter()
        f = d['players']['10']['fighter']
        f['hp'] = f['stats']['max_hp'] = 1000
        set_intent(d)
        choose(d, 'mana_shot')
        d['chaplain']['next_rewind'] = 2
        set_intent(d)
        # Identical set_intent calls should be avoided by real flow; explicit
        # checkpoint below isolates the bounded restore semantics.
        checkpoint = deepcopy(d['_chaplain_snapshot'])
        checkpoint['round'] = 1
        d['_chaplain_previous'] = checkpoint
        f['resource'] = 7
        f['hp'] = 40
        f['used_skills'] = ['last_amendment', 'solar_eclipse']
        f['potion_used'] = True
        f.setdefault('rpg_state', {})['phoenix_revived'] = True
        d['players']['10']['manual_turns'] = 4
        rewind(d)
        self.assertEqual(f['resource'], checkpoint['players']['10']['fighter']['resource'])
        self.assertEqual(f['hp'], checkpoint['players']['10']['fighter']['hp'])
        self.assertTrue(f['potion_used'])
        self.assertIn('solar_eclipse', f['used_skills'])
        self.assertTrue(f['rpg_state']['phoenix_revived'])
        self.assertEqual(d['players']['10']['manual_turns'], 4)
        self.assertEqual(d['round'], 2)
        self.assertTrue(7 <= d['chaplain']['next_rewind'] <= 9)

    def test_anchor_last_three_rounds_and_preserves_damage(self):
        d = encounter()
        anchor(d, '10', 'chaplain_anchor:damage')
        self.assertEqual(d['chaplain']['anchors']['10']['until'], 3)
        before = d['boss']['hp']
        d['boss']['hp'] -= 30
        rewind(d)
        self.assertEqual(d['boss']['hp'], before-30)
        self.assertEqual(d['chaplain']['recoveries'], 0)

    def test_healing_and_cleanse_anchors_preserve_results_not_withdrawn_players(self):
        d = encounter(3)
        f = d['players']['20']['fighter']
        f['hp'] = 30
        f['effects'].append(dict(id='test_bleed',kind='bleed',value=3,duration=5))
        set_intent(d)
        anchor(d, '10', 'chaplain_anchor:healing')
        anchor(d, '20', 'chaplain_anchor:cleanse')
        before = action_before(d)
        f['hp'] += 20
        f['effects'] = []
        record_action(d, before)
        f['hp'] = 5
        d['players']['30'].update(withdrawn=True,reward_blocked=True)
        d['players']['30']['fighter']['hp'] = 0
        rewind(d)
        self.assertEqual(f['hp'], 50)
        self.assertFalse(any(e['id']=='test_bleed' for e in f['effects']))
        self.assertTrue(d['players']['30']['withdrawn'])
        self.assertEqual(d['players']['30']['fighter']['hp'], 0)

    def test_team_wipe_is_not_rescued_by_phase_healing(self):
        d = encounter()
        d['boss']['hp'] = 10
        d['players']['10']['fighter']['hp'] = 0
        self.assertTrue(finish_if_needed(d))
        self.assertFalse(d['won'])
        self.assertEqual(d['chaplain']['recoveries'], 0)

    def test_same_art_first_two_phases_and_no_cross_phase_history(self):
        from arena_raid_engine import raid_boss_sprite
        from arena_chaplain import transition
        d = encounter()
        self.assertEqual(raid_boss_sprite('chaplain',1),raid_boss_sprite('chaplain',2))
        self.assertNotEqual(raid_boss_sprite('chaplain',2),raid_boss_sprite('chaplain',3))
        self.assertNotEqual(raid_boss_sprite('chaplain',3),raid_boss_sprite('chaplain',4))
        d['boss']['hp'] = 1
        transition(d)
        self.assertNotIn('_chaplain_previous', d)
        set_intent(d)
        self.assertNotIn('_chaplain_previous', d)

    def test_no_qte_fields_in_checkpoint_real_limit_and_phase_ui_state(self):
        d = encounter()
        d['players']['10']['fighter']['_qte_guard'] = {'dodge':[True]}
        d['chaplain']['phase'] = 4
        d['round'] = 3
        set_intent(d)
        self.assertNotIn('_qte_guard', json.dumps(d['_chaplain_snapshot']))
        self.assertTrue(d['chaplain']['ui_scramble'])
        self.assertEqual(d['chaplain']['swap_target'], '')
        self.assertEqual(set(d['chaplain']['ui_order']['10']),set(d['players']['10']['fighter']['loadout']))
        d['round'] = 4
        set_intent(d)
        self.assertEqual(d['chaplain']['swap_target'], '10')
        d['round'] = 100
        d['chaplain']['next_rewind'] = 1000
        set_intent(d)
        choose(d)
        self.assertTrue(d['finished'])
        self.assertFalse(d['won'])

    def test_marked_skill_is_not_disabled_and_surcharge_cannot_kill(self):
        from arena_chaplain import marked_cost
        d = encounter()
        d['chaplain']['phase'] = 2
        set_intent(d)
        f = d['players']['10']['fighter']
        d['chaplain']['banned']['10'] = 'mana_shot'
        f['hp'] = 2
        marked_cost(d,'10','mana_shot')
        self.assertEqual(f['hp'],1)
        self.assertTrue(any('Нарушение предписания' in e['text'] for e in d['log']))

    def test_amendment_only_restores_hp_debuffs_not_energy_cooldowns_or_uses(self):
        d = encounter()
        f = d['players']['10']['fighter']
        pair = pair_state(f, d['boss'])
        saved = f['hp']
        resolve_skill(pair,'a','last_amendment',BUILTIN_SKILLS,FixedRoll(),advance_turn=False)
        self.assertEqual(f['resource'],50)
        f['hp'] -= 40
        f['resource'] = 0
        f['cooldowns']['mana_shot'] = 5
        f['potion_used'] = True
        f.setdefault('used_skills', []).append('solar_eclipse')
        f['effects'].append(dict(id='bleed',kind='bleed',value=2,duration=4))
        self.assertEqual(effective_skill(pair,'a','last_amendment').cost,0)
        resolve_skill(pair,'a','last_amendment',BUILTIN_SKILLS,FixedRoll(),advance_turn=False)
        self.assertEqual(f['hp'],saved)
        self.assertEqual(f['resource'],0)
        self.assertEqual(f['cooldowns']['mana_shot'],4)
        self.assertTrue(f['potion_used'])
        self.assertIn('solar_eclipse',f['used_skills'])
        self.assertFalse(any(e['kind']=='bleed' for e in f['effects']))
        self.assertEqual(f['cooldowns']['last_amendment'], 5)
        f['resource'] = 100
        with self.assertRaisesRegex(ValueError,'восстанавливается'):
            validate_skill(pair,'a','last_amendment')

    def test_amendment_expires_after_two_following_actions(self):
        d = encounter()
        f = d['players']['10']['fighter']
        pair = pair_state(f,d['boss'])
        resolve_skill(pair,'a','last_amendment',rng=FixedRoll(),advance_turn=False)
        _tick(f)
        self.assertEqual(validate_skill(pair,'a','last_amendment').cost,0)
        _tick(f)
        with self.assertRaises(ValueError):
            validate_skill(pair,'a','last_amendment')
        self.assertNotIn('last_amendment', f['mechanics'])
        self.assertEqual(f['cooldowns']['last_amendment'], 5)

    def test_amendment_repeats_after_exactly_five_own_turns(self):
        d = encounter()
        f = d['players']['10']['fighter']
        pair = pair_state(f, d['boss'])
        # Old saved once-per-battle markers must not lock the updated skill.
        f['used_skills'] = ['last_amendment', 'solar_eclipse']
        for cycle in range(3):
            f['resource'] = 100
            resolve_skill(pair, 'a', 'last_amendment', rng=FixedRoll(), advance_turn=False)
            self.assertNotIn('last_amendment', f['cooldowns'])
            self.assertEqual(f['resource'], 50)
            f['hp'] = max(1, f['hp']-10)
            resolve_skill(pair, 'a', 'last_amendment', rng=FixedRoll(), advance_turn=False)
            self.assertEqual(f['resource'], 50)
            self.assertEqual(f['cooldowns']['last_amendment'], 5)
            for left in (4, 3, 2, 1):
                _tick(f)
                self.assertEqual(f['cooldowns']['last_amendment'], left)
                with self.assertRaisesRegex(ValueError, 'восстанавливается'):
                    validate_skill(pair, 'a', 'last_amendment')
            _tick(f)
            self.assertEqual(validate_skill(pair, 'a', 'last_amendment').cost, 50)
        self.assertIn('solar_eclipse', f['used_skills'])

    def test_amendment_expiration_also_allows_a_new_paid_record_after_five_turns(self):
        d = encounter()
        f = d['players']['10']['fighter']
        pair = pair_state(f, d['boss'])
        resolve_skill(pair, 'a', 'last_amendment', rng=FixedRoll(), advance_turn=False)
        saved_hp = f['hp']
        f['hp'] = max(1, f['hp']-20)
        _tick(f)
        _tick(f)
        self.assertEqual(f['cooldowns']['last_amendment'], 5)
        for _ in range(5):
            _tick(f)
        self.assertEqual(f['hp'], max(1, saved_hp-20))
        self.assertEqual(validate_skill(pair, 'a', 'last_amendment').cost, 50)
        resolve_skill(pair, 'a', 'last_amendment', rng=FixedRoll(), advance_turn=False)
        self.assertEqual(f['resource'], 0)
        self.assertEqual(effective_skill(pair, 'a', 'last_amendment').cost, 0)

    def test_rewind_preserves_current_amendment_window_and_cooldown_not_saved_ones(self):
        from arena_chaplain import _restore_fighter, amendment_active
        d = encounter()
        f = d['players']['10']['fighter']
        pair = pair_state(f, d['boss'])
        saved_before = deepcopy(f)
        resolve_skill(pair, 'a', 'last_amendment', rng=FixedRoll(), advance_turn=False)
        _restore_fighter(f, saved_before)
        self.assertIsNotNone(amendment_active(f))
        saved_active = deepcopy(f)
        resolve_skill(pair, 'a', 'last_amendment', rng=FixedRoll(), advance_turn=False)
        _tick(f)
        self.assertEqual(f['cooldowns']['last_amendment'], 4)
        saved_cooling = deepcopy(f)
        _restore_fighter(f, saved_active)
        self.assertIsNone(amendment_active(f))
        self.assertEqual(f['cooldowns']['last_amendment'], 4)
        for _ in range(4):
            _tick(f)
        _restore_fighter(f, saved_cooling)
        self.assertNotIn('last_amendment', f['cooldowns'])
        self.assertIsNone(amendment_active(f))
        self.assertEqual(validate_skill(pair, 'a', 'last_amendment').cost, 50)


class ChaplainStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown

    async def test_low_level_players_can_create_join_and_start(self):
        for actor in (10, 20):
            self.assertLess(self.db._arena_profile_locked(1, actor, True)['level'], 20)
        row = await self.db.arena_raid_create(1, 10, boss_id='chaplain')
        body = await RaidPublisher(self.db, self.bot, 'TestBot').body(row)
        self.assertIn('Капеллан', body)
        self.assertIn('Последняя поправка', body)
        self.assertNotIn('поступи тигробоя', body)
        self.assertIn('Вход без ограничения уровня', body)
        row = await self.db.arena_raid_setup(row['token'], 20, 'join')
        row = await self.db.arena_raid_setup(row['token'], 10, 'start')
        self.assertEqual(row['status'], 'active')
        view = await raid_view(self.db, row, 10)
        self.assertEqual(view['min_level'], 1)
        self.assertEqual(view['recommended_level'], 20)
        self.assertEqual(view['data']['boss']['level'], 25)
        self.assertNotIn('С 20 уровня.', view['encounter_rules'])

    async def start(self):
        self.db._arena_profile_locked(1, 10, True)
        self.db._grant_profile_xp_locked('personal_profiles', 1, 10, fighter_xp_limit())
        self.db.connection.execute("UPDATE personal_profiles SET class_id='mage',archclass_id='mage_archmage',archclass_stage=20,progression_level=20,progression_pending_level=0 WHERE user_id=10 AND chat_id=0")
        self.db.connection.commit()
        row = await self.db.arena_raid_create(1, 10, boss_id='chaplain')
        return await self.db.arena_raid_setup(row['token'], 10, 'start')

    async def test_private_checkpoint_hidden_and_invalid_anchor_rejected(self):
        row = await self.start()
        view = await raid_view(self.db, row, 10)
        self.assertNotIn('_chaplain_snapshot', view['data'])
        self.assertNotIn('_chaplain_results', view['data'])
        self.assertEqual(view['loot_name'], 'Последняя поправка')
        with self.assertRaises(ValueError):
            await self.db.arena_raid_action(row['token'], 10, 1, 'chaplain_anchor:cheat')
        row = await self.db.arena_raid_action(row['token'], 10, 1, 'chaplain_anchor:damage')
        self.assertEqual(row['round'], 2)
        self.assertGreater(row['revision'], 1)
        with self.assertRaises(ValueError):
            await self.db.arena_raid_action(row['token'], 10, 1, 'defend')

    async def test_anchor_still_gets_defense_qte_and_stale_flow_is_invalid_after_rewind(self):
        row = await self.start()
        data = json.loads(row['data_json'])
        data['players']['10']['fighter']['hp'] = data['players']['10']['fighter']['stats']['max_hp'] = 1000
        set_intent(data)
        self.db._raid_save_locked(row, data)
        self.db.connection.commit()
        await self.db.arena_interactive_raid(row['token'], 10, 1, 'chaplain_anchor:damage')
        flow = self.db._qte_load_locked('raid', row['token'], 10)
        self.assertIsNotNone(flow)
        self.assertEqual(len(flow['stages']), 1)
        self.assertEqual(flow['stages'][0]['kind'], 'defense')
        self.db._qte_complete_locked(flow, expired=True)
        self.assertFalse(self.db._qte_valid_locked(flow))
        row = self.db._raid_row_locked(row['token'])
        data = json.loads(row['data_json'])
        data['chaplain']['next_rewind'] = 2
        set_intent(data)
        self.db._raid_save_locked(row, data)
        self.db.connection.commit()
        await self.db.arena_interactive_raid(row['token'], 10, 2, 'chaplain_anchor:damage')
        current = json.loads(self.db._raid_row_locked(row['token'])['data_json'])
        self.assertEqual(current['round'], 3)
        self.assertEqual(current['chaplain']['rewinds'], 1)
        self.assertFalse(self.db._qte_valid_locked(flow))

    async def test_false_victory_does_not_settle_database_rewards(self):
        row = await self.start()
        data = json.loads(row['data_json'])
        data['boss']['hp'] = 0
        self.assertFalse(finish_if_needed(data))
        self.db._raid_save_locked(row, data)
        self.db.connection.commit()
        self.assertEqual(self.db._raid_row_locked(row['token'])['status'], 'active')
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_raid_reward_cooldowns').fetchone()[0], 0)
        self.assertEqual(data['rewards'], {})

    async def test_real_victory_settles_trophy_once_after_charges_exhausted(self):
        row = await self.start()
        data = json.loads(row['data_json'])
        data['players']['10']['manual_turns'] = 2
        data['chaplain'].update(phase=4, recoveries=3)
        data['boss']['hp'] = 0
        self.assertTrue(finish_if_needed(data))
        self.assertTrue(data['won'])
        with patch('arena_raid.random.SystemRandom', return_value=FixedRoll()):
            self.db._raid_finish_locked(row, data)
        self.db.connection.commit()
        self.assertEqual(data['rewards']['10']['loot'], 'Последняя поправка')
        self.assertEqual(self.db._raid_row_locked(row['token'])['status'], 'finished')
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_raid_reward_cooldowns').fetchone()[0], 1)
