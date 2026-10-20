"""Fixed nightmare encounter, fair intentions, saved loot and phase presentation."""

import json
import shutil
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from arena_engine import (BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state,
                          resolve_skill, validate_skill)
from arena_kit import KIT_STATS, KIT_LEVEL, kit_prepare_action, kit_finish_action
from arena_raid_engine import create_raid_state, resolve_round, set_intent, raid_boss_sprite
from arena_raid_web import raid_view
from handlers.raids import RAID_RE, raid_boss_id, RaidPublisher
from test_arena_epic import FixedRoll
import test_arena_lei_heng as store_helpers
import test_arena_market_client as client_helpers
from tools.preview_arena import raid_preview


def encounter(size=3, level=20):
    members = [dict(actor_id=i, fighter_id=i, personal=True, slave_owner=i)
               for i in (10, 20, 30)[:size]]
    sources = [dict(slave_id=m['actor_id'], owner_id=m['actor_id'], class_id='ragamuffin', level=level)
               for m in members]
    data = create_raid_state(members, sources, FIGHTER_CLASSES, BUILTIN_SKILLS, 'kit')
    for p in data['players'].values():
        p['fighter']['hp'] = p['fighter']['stats']['max_hp'] = 1000
        p['fighter']['loadout'] = list(BUILTIN_SKILLS)
        p['selected'] = 'defend'
    return data


class KitEngineTests(unittest.TestCase):
    def test_fixed_level_and_all_stats_ignore_party_size_level_and_hp(self):
        for size in (1, 2, 3):
            for level in (1, 5, 18, 20):
                with self.subTest(size=size, level=level):
                    data = encounter(size, level)
                    self.assertEqual(data['boss']['level'], KIT_LEVEL)
                    self.assertEqual(data['boss']['stats'], KIT_STATS)
                    self.assertEqual(data['phase_count'], 3)

    def test_three_phases_and_one_announced_eclipse(self):
        data = encounter()
        for ratio, expected in ((1, 1), (.70, 2), (.35, 3)):
            data['boss']['hp'] = round(KIT_STATS['max_hp'] * ratio)
            set_intent(data)
            self.assertEqual(data['phase'], expected)
        self.assertEqual(data['intent']['skill'], 'kit_eclipse')
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(len([e for e in data['log'] if e.get('skill') == 'kit_eclipse']), 3)
        for round_number in range(10, 20):
            data['round'] = round_number
            set_intent(data)
            self.assertNotEqual(data['intent']['skill'], 'kit_eclipse')

    def test_crossing_phase_threshold_cannot_add_unannounced_ultimate(self):
        data = encounter()
        data['boss']['hp'] = round(KIT_STATS['max_hp'] * .36)
        set_intent(data)
        self.assertEqual(data['phase'], 2)
        for p in data['players'].values():
            p['selected'] = 'bum_punch'
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(data['phase'], 3)
        self.assertEqual(data['intent']['skill'], 'kit_eclipse')
        self.assertFalse(any(e.get('skill') == 'kit_eclipse' for e in data['log']))
        self.assertTrue(all(e['after']['boss']['mechanics']['kit_phase'] == 2 for e in data['log']))

    def test_prediction_reads_last_public_action_not_secret_selections(self):
        data = encounter()
        data['round'] = 2
        for p in data['players'].values():
            p['kit_previous_action'] = 'magic'
        data['players']['20']['selected'] = 'mana_focus'
        set_intent(data)
        before = deepcopy(data['intent'])
        self.assertEqual(data['kit_prediction'], dict(target='20', action='magic'))
        data['players']['20']['selected'] = 'bum_punch'
        set_intent(data)
        self.assertEqual(data['intent'], before)

    def test_prediction_can_be_avoided_by_changing_category_or_guarding(self):
        for selected, count in (('mana_focus', 0), ('defend', 0), ('mana_shot', 1)):
            with self.subTest(selected=selected):
                data = encounter()
                data['round'] = 2
                data['players']['20']['kit_previous_action'] = 'magic'
                data['players']['20']['selected'] = selected
                set_intent(data)
                resolve_round(data, BUILTIN_SKILLS, FixedRoll())
                self.assertEqual(sum(e.get('skill') == 'kit_flash' for e in data['log']), count)

    def test_field_counter_is_one_per_round_not_one_per_player(self):
        data = encounter()
        data['boss']['hp'] = 700
        data['round'] = 4
        set_intent(data)
        self.assertEqual(data['intent']['skill'], 'kit_field')
        self.assertEqual(data['intent']['targets'], [])
        for p in data['players'].values():
            p['selected'] = 'bum_punch'
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(sum(e.get('skill') == 'kit_flash' for e in data['log']), 1)

    def test_accepted_stun_prevents_field_counter(self):
        data = encounter()
        data['boss']['hp'] = 700
        data['round'] = 4
        set_intent(data)
        skills = dict(BUILTIN_SKILLS, bum_punch=replace(BUILTIN_SKILLS['bum_punch'],
            effects=(dict(id='test_stun', kind='stun', value=1, turns=1, target='enemy', chance=1),)))
        data['players']['10']['selected'] = 'bum_punch'
        resolve_round(data, skills, FixedRoll())
        self.assertFalse(any(e.get('skill') == 'kit_flash' for e in data['log']))
        self.assertTrue(any('Босс ошеломлён' in e['text'] for e in data['log']))

    def test_shield_is_cleared_after_miss_and_only_one_successful_action_uses_it(self):
        data = encounter()
        skill = BUILTIN_SKILLS['mana_shot']
        prepared = kit_prepare_action(data, '10', skill)
        self.assertTrue(any(e['id'] == 'kit_action_shield' for e in data['boss']['effects']))
        kit_finish_action(data, '10', dict(damage=0), prepared)
        self.assertFalse(any(e['id'] == 'kit_action_shield' for e in data['boss']['effects']))
        self.assertNotIn('kit_shield_round', data['boss']['mechanics'])
        prepared = kit_prepare_action(data, '20', skill)
        kit_finish_action(data, '20', dict(damage=10), prepared)
        self.assertEqual(data['boss']['mechanics']['kit_shield_round'], 1)
        self.assertFalse(kit_prepare_action(data, '30', skill)['first'])

    def test_defend_removes_purification_before_it_can_burn(self):
        data = encounter()
        data['round'] = 2
        set_intent(data)
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        actor = data['players']['20']['fighter']
        self.assertTrue(any(e.get('id') == 'kit_mark' for e in actor['effects']))
        before = actor['hp']
        for p in data['players'].values():
            p['selected'] = 'defend'
        data['intent'].update(skill='kit_field', targets=[])
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertEqual(actor['hp'], before)
        self.assertFalse(any(e.get('id') == 'kit_mark' for e in actor['effects']))

    def test_reflection_has_two_damage_types_but_dot_ticks_once(self):
        data = encounter()
        data['boss']['effects'].extend([dict(id='burn', kind='burn', value=3, duration=3),
                                        dict(id='bleed', kind='bleed', value=2, duration=3)])
        before = data['boss']['hp']
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        attacks = [e for e in data['log'] if e.get('skill') in ('kit_reflection', 'kit_ash')]
        self.assertEqual([e['damage_type'] for e in attacks], ['physical', 'magic'])
        self.assertEqual(data['boss']['own_turns'], 1)
        self.assertEqual(data['boss']['hp'], before - 5)
        self.assertEqual([e['duration'] for e in data['boss']['effects']], [2, 2])

    def test_announced_departed_target_does_not_redirect_to_another_player(self):
        data = encounter()
        data['players']['10']['withdrawn'] = True
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertFalse(any(e.get('skill') in ('kit_reflection', 'kit_ash') for e in data['log']))

    def test_coins_interrupt_uses_actual_boss_hp_lost_and_still_ticks_burn(self):
        data = encounter()
        data['round'] = 5
        data['boss']['hp'] = 700
        set_intent(data)
        self.assertEqual(data['intent']['skill'], 'kit_coins')
        # Native attacks exceed the fixed 10% interrupt threshold without cheating HP.
        for p in data['players'].values():
            p['fighter']['stats']['physical_attack'] = 200
            p['selected'] = 'bum_punch'
        resolve_round(data, BUILTIN_SKILLS, FixedRoll())
        self.assertFalse(any(e.get('skill') in ('kit_coins', 'kit_coins_ash') for e in data['log']))
        self.assertTrue(any('подготовка сорвана' in e['text'] for e in data['log']))

    def test_defending_reduces_eclipse_beyond_normal_guard_stats(self):
        damages = []
        for guarded in (False, True):
            data = encounter(1)
            data['boss']['hp'] = 300
            set_intent(data)
            data['players']['10']['selected'] = 'defend' if guarded else 'mana_focus'
            resolve_round(data, BUILTIN_SKILLS, FixedRoll())
            damages.append(next(e['damage'] for e in data['log'] if e.get('skill') == 'kit_eclipse'))
        self.assertLess(damages[1], damages[0] * .45)

    def test_solar_tractate_min_level_fourth_action_hybrid_and_once_on_hit(self):
        source = dict(slave_id=1, owner_id=1, class_id='warrior', level=20,
                      loadout=['solar_eclipse'], granted_skills=['solar_eclipse'])
        state = create_battle_state(source, dict(source, slave_id=2, owner_id=2))
        actor = state['sides']['a']
        actor['stats']['physical_attack'] = 100
        actor['stats']['magic_attack'] = 0
        state['sides']['b']['hp'] = state['sides']['b']['stats']['max_hp'] = 1000
        for turn in range(3):
            actor['own_turns'] = turn
            with self.assertRaisesRegex(ValueError, 'четвёртого'):
                validate_skill(state, 'a', 'solar_eclipse')
        actor['own_turns'] = 3
        event = resolve_skill(state, 'a', 'solar_eclipse', rng=FixedRoll(.99), advance_turn=False)
        self.assertFalse(event['hit'])
        self.assertEqual(actor['resource'], 20)
        self.assertNotIn('solar_eclipse', actor.get('used_skills', []))
        state = json.loads(json.dumps(state))
        actor = state['sides']['a']
        actor['resource'] = 100
        event = resolve_skill(state, 'a', 'solar_eclipse', rng=FixedRoll(), advance_turn=False)
        self.assertGreater(event['damage'], 150)
        self.assertIn('solar_eclipse', actor['used_skills'])
        actor['resource'] = 100
        with self.assertRaisesRegex(ValueError, 'Уже использован'):
            validate_skill(state, 'a', 'solar_eclipse')
        actor['used_skills'] = []
        actor['level'] = 14
        with self.assertRaisesRegex(ValueError, '15'):
            validate_skill(state, 'a', 'solar_eclipse')

    def test_commands_and_transparent_asset(self):
        for command in ('/рейд кит', '/raid kit', '/РЕЙД МАЭЛЬ', '/рейд@TestBot Кит'):
            self.assertEqual(raid_boss_id(RAID_RE.fullmatch(command)), 'kit')
        with Image.open(Path(__file__).resolve().parents[1] / 'webapp/assets/kit.png') as img:
            self.assertEqual(img.mode, 'RGBA')
            self.assertGreaterEqual(min(img.size), 512)
            self.assertEqual(img.getchannel('A').getextrema(), (0, 255))

    def test_phase_assets_are_transparent_and_base_is_preserved(self):
        root = Path(__file__).resolve().parents[1]
        for phase, filename in ((1, 'kit.png'), (2, 'kit_phase_two.png'), (3, 'kit_phase_three.png')):
            self.assertEqual(raid_boss_sprite('kit', phase), '/static/assets/'+filename)
            with Image.open(root/'webapp/assets'/filename) as img:
                self.assertEqual(img.mode, 'RGBA')
                low, high = img.getchannel('A').getextrema()
                self.assertEqual(low, 0)
                self.assertGreaterEqual(high, 240)
        self.assertEqual(raid_boss_sprite('kit', 99), '/static/assets/kit.png')
        self.assertEqual(raid_boss_sprite('lei_heng', 2), '/static/assets/lei_heng.png')
        with Image.open(root/'webapp/assets/kit_eyes_background.png') as img:
            self.assertGreater(img.width, img.height)


class KitStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = store_helpers.LeiStoreTests.asyncSetUp
    asyncTearDown = store_helpers.LeiStoreTests.asyncTearDown
    start = store_helpers.LeiStoreTests.start
    win = store_helpers.LeiStoreTests.win

    async def test_phase_sprites_are_decorated_without_changing_saved_combat_data(self):
        row = await self.start('kit')
        for phase in (1, 2, 3):
            state = json.loads(row['data_json'])
            state['phase'] = phase
            record = dict(row, data_json=json.dumps(state))
            before = record['data_json']
            public = await raid_view(self.db, record, 10)
            self.assertEqual(public['data']['boss']['class_avatar_url'], raid_boss_sprite('kit', phase))
            self.assertEqual(public['boss_sprites'][str(phase)], raid_boss_sprite('kit', phase))
            self.assertEqual(record['data_json'], before)

    async def test_legendary_loot_public_fixed_level_and_account_cooldown(self):
        row = await self.start('kit')
        public = await raid_view(self.db, row, 10)
        self.assertEqual(public['fixed_level'], 25)
        self.assertEqual(public['phase_count'], 3)
        self.assertEqual(public['data']['boss']['level'], 25)
        self.assertEqual(public['data']['boss']['class_avatar_url'], '/static/assets/kit.png')
        body = await RaidPublisher(self.db, self.bot, 'TestBot').body(dict(row, status='lobby'))
        self.assertIn('фиксированный уровень 25', body.casefold())
        self.assertNotIn('Уровень босса подстраивается', body)
        with patch('arena_raid.random.SystemRandom', return_value=FixedRoll()):
            first = self.win(row)['rewards']['10']
        self.assertEqual(first['loot'], 'Солнечное затмение')
        inventory = self.db._arena_inventory_locked(1, 10)
        item = next(i for i in inventory if i['content_id'] == 'solar_eclipse')
        self.assertEqual(item['rarity_name'], 'Легендарный')
        self.assertNotIn(('skill', 'solar_eclipse'), self.db._arena_shop_catalog_locked())
        row = await self.start('kit')
        with patch('arena_raid.random.SystemRandom', return_value=FixedRoll()):
            second = self.win(row)['rewards']['10']
        self.assertFalse(second['full_reward'])
        self.assertEqual(second['loot'], '')
        self.assertEqual(second['francs'], first['francs'] // 5)
        self.assertEqual(next(i for i in self.db._arena_inventory_locked(1, 10)
                              if i['content_id'] == 'solar_eclipse')['quantity'], 1)


@unittest.skipUnless(shutil.which('node'), 'Node required')
class KitClientTests(unittest.TestCase):
    def test_soundtrack_follows_kit_phase_and_other_bosses_keep_their_themes(self):
        run = client_helpers.ArenaMarketClientTests().run_client
        for mode, expected in (('kit', 'raid'), ('kit_phase2', 'kit_menace'), ('kit_phase3', 'kit_abyss'), ('doof', 'doofenshmirtz'), ('lei_heng', 'lei_heng')):
            data = raid_preview(mode)
            self.assertEqual(run('out=raidSoundtrack(input);', data), expected)
            data['status'] = 'lobby'
            self.assertEqual(run('out=raidSoundtrack(input);', data), 'menu')
            data['status'] = 'finished'
            self.assertEqual(run('out=raidSoundtrack(input)||"silence";', data), 'silence')

    def test_music_switches_with_replayed_phase_not_unseen_final_phase(self):
        run = client_helpers.ArenaMarketClientTests().run_client
        data = raid_preview('kit_phase3')
        for phase, expected in ((1, 'raid'), (2, 'kit_menace'), (3, 'kit_abyss')):
            code = 'out=raidSoundtrack(raidVisual(input,{boss:{mechanics:{kit_phase:'+str(phase)+'}}}));'
            self.assertEqual(run(code, data), expected)

    def test_three_phase_views_show_sprite_background_controls_and_no_scaling_claim(self):
        run = client_helpers.ArenaMarketClientTests().run_client
        for mode, phase in (('kit', 1), ('kit_phase2', 2), ('kit_phase3', 3)):
            data = raid_preview(mode)
            body = run('document.getElementById=()=>null;raidScreen(input);', data)
            self.assertIn(raid_boss_sprite('kit', phase), body)
            self.assertIn('data-boss="kit" data-phase="'+str(phase)+'"', body)
            self.assertIn('ФАЗА '+str(phase)+' / 3', body)
            self.assertIn('data-raid="skill:defend"', body)
            self.assertEqual(body.count('class="raid-fighter'), 4)
        data.update(status='lobby', data=None)
        body = run('document.getElementById=()=>null;raidScreen(input);', data)
        self.assertIn('фиксированный уровень 25', body.casefold())
        self.assertNotIn('Уровень босса подстраивается', body)

    def test_replay_uses_the_event_phase_not_the_latest_server_sprite(self):
        run = client_helpers.ArenaMarketClientTests().run_client
        data = raid_preview('kit_phase3')
        result = json.loads(run("const view=raidVisual(input,{boss:{mechanics:{kit_phase:1}}});out=JSON.stringify({phase:view.data.phase,sprite:view.data.boss.class_avatar_url,original:input.data.boss.class_avatar_url});", data))
        self.assertEqual(result, dict(phase=1, sprite='/static/assets/kit.png', original='/static/assets/kit_phase_three.png'))
        result = json.loads(run("const view=raidVisual(input,{boss:{mechanics:{kit_phase:2}}});out=JSON.stringify({phase:view.data.phase,sprite:view.data.boss.class_avatar_url});", data))
        self.assertEqual(result, dict(phase=2, sprite='/static/assets/kit_phase_two.png'))

    def test_untrusted_sprite_metadata_cannot_be_used_as_an_image_url(self):
        data = raid_preview('kit')
        data['boss_sprites']['1'] = 'https://untrusted.example/spy.png'
        body = client_helpers.ArenaMarketClientTests().run_client('document.getElementById=()=>null;raidScreen(input);', data)
        self.assertNotIn('untrusted.example', body)
        self.assertIn('/static/assets/kit.png', body)

    def test_facing_is_independent_of_hit_cast_and_strike_transforms(self):
        css = (Path(__file__).resolve().parents[1]/'webapp/style.css').read_text(encoding='utf-8')
        self.assertIn('.kit-field .raid-enemy .raid-sprite{scale:-1 1;transform:none}', css)
        self.assertIn('kit_eyes_background.png', css)
        self.assertIn('.kit-field[data-phase="2"]:before', css)
