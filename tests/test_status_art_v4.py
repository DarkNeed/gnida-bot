import json
import unittest
from pathlib import Path

from PIL import Image

import test_arena_market_client as client_tests

ROOT = Path(__file__).resolve().parents[1]


class StatusArtV4Tests(unittest.TestCase):
    def client(self, code, data=None):
        return client_tests.ArenaMarketClientTests().run_client(code, data or {})

    def statuses(self, side):
        return json.loads(self.client('out=JSON.stringify(fighterStatuses(input));', side))

    def test_every_allowlisted_illustration_is_packaged_and_documented(self):
        names = json.loads(self.client('out=JSON.stringify(statusArtNames);'))
        manifest = json.loads((ROOT / 'art/status-effects-v4/generation.json').read_text(encoding='utf-8'))
        self.assertEqual(len(names), 36)
        self.assertEqual(set(names), {e['key'] for e in manifest['assets']})
        self.assertEqual(set(names), {p.stem for p in (ROOT / 'webapp/assets/status-effects-v4').glob('*.png')})
        for name in names:
            with self.subTest(name=name), Image.open(ROOT / f'webapp/assets/status-effects-v4/{name}.png') as icon:
                self.assertEqual(icon.mode, 'RGBA')
                self.assertEqual(icon.size, (144, 144))
                self.assertEqual(icon.getchannel('A').getextrema(), (0, 255))
                self.assertEqual(icon.getpixel((0, 0))[3], 0)
            markup = self.client('out=statusIcon(input,"down");', name)
            self.assertIn(f'/static/assets/status-effects-v4/{name}.png', markup)
            self.assertIn('status-illustrated', markup)
            self.assertIn('M26 20v8', markup)

    def test_only_allowlisted_names_can_form_paths(self):
        for name in ['constructor', '__proto__', '../burn', 'burn.png', '\"><script>']:
            markup = self.client('out=statusIcon(input);', name)
            self.assertIn('/status-effects-v3/15.png', markup)
            self.assertNotIn('<script>', markup)

    def test_persistent_effects_have_semantic_icons_without_changing_counters(self):
        effects = [
            ('rpg_burn', 'burn', 'burn'), ('rpg_frost', 'speed_pct', 'frost'),
            ('fever', 'plague_fever', 'fever'), ('spores', 'plague_spores', 'spores'),
            ('counter_lunge', 'rpg_counter', 'counter'), ('hunter_parry', 'rpg_parry', 'parry'),
            ('final_family_cover', 'family_cover', 'family_cover'),
            ('nz_contact_venom', 'burn', 'poison'), ('nz_contact_curse', 'damage_pct', 'curse'),
            ('nz_contact_shock', 'accuracy_flat', 'shock'), ('lei_prey', 'raid_prey', 'prey'),
            ('lei_overheat', 'damage_taken_pct', 'vulnerability'), ('sealed', 'skill_cost_flat', 'skill_cost'),
        ]
        items = self.statuses({'effects': [dict(id=ident, kind=kind, value=2, duration=3) for ident, kind, _ in effects]})
        self.assertEqual(len(items), len(effects))
        for item, (ident, kind, expected) in zip(items, effects):
            self.assertEqual(item['id'], f'effect:{ident}:{kind}')
            self.assertEqual(item['icon'], expected)
            self.assertEqual(item['count'], '2' if kind == 'plague_spores' else '3')

    def test_class_counters_and_distinct_summons(self):
        side = dict(class_id='mage', own_turns=0, rpg_state=dict(
            souls=2, summon=3, rally=12, weapon_open=True, visceral_ready=True,
            visceral_until=2, moon_mark=True, echo_ready=True, faith=1, retribution=2, beast=3))
        items = {e['id']: e for e in self.statuses(side)}
        for key, expected in [('souls','souls'),('skeleton','skeleton'),('rally','blood_rally'),('weapon','weapon_open'),('visceral','visceral'),('moon','moon_mark'),('echo','mana_echo'),('faith','faith'),('retribution','retribution'),('beast','beast')]:
            self.assertEqual(items['rpg:'+key]['icon'], expected)
        self.assertEqual(items['rpg:souls']['count'], '2/3')
        side['rpg_state']['death_servants'] = True
        items = {e['id']: e for e in self.statuses(side)}
        self.assertEqual(items['rpg:skeleton']['icon'], 'death_servants')
        self.assertEqual(items['rpg:skeleton']['count'], '3')

    def test_casino_counters_no_longer_share_a_scroll(self):
        side = dict(casino_state=dict(misfortune=1,chips=2,sevens=1,debt=5,table=2,ace=True,stored=6))
        items = self.statuses(side)
        self.assertEqual(len(items), 7)
        self.assertEqual(len({e['icon'] for e in items}), 7)
        self.assertTrue(all(e['icon'].startswith('casino_') for e in items))

    def test_boss_and_pet_art_and_old_standard_buffs(self):
        side = dict(effects=[dict(id='nz_plot_armor',kind='incoming_damage_multiplier',value=.5,duration=10000),
                             dict(id='attack',kind='physical_attack_pct',value=.2,duration=2)],
                    mechanics=dict(chaplain_incoming=.8), pet=dict(id='rat',name='Крыса',description='Бонус'), pet_state=dict(ready=True))
        items = {e['id']: e for e in self.statuses(side)}
        self.assertEqual(items['effect:nz_plot_armor:incoming_damage_multiplier']['icon'], 'plot_armor')
        self.assertEqual(items['effect:nz_plot_armor:incoming_damage_multiplier']['count'], '∞')
        self.assertEqual(items['mechanic:chaplain_revision']['icon'], 'revision')
        self.assertEqual(items['pet:rat']['icon'], 'pet_ready')
        self.assertEqual(items['effect:attack:physical_attack_pct']['icon'], 4)
        self.assertEqual(items['effect:attack:physical_attack_pct']['direction'], 'up')

    def test_new_coloured_art_is_excluded_from_legacy_red_filter(self):
        css = (ROOT / 'webapp/style.css').read_text(encoding='utf-8')
        self.assertIn('.status-down:not(.status-illustrated) .status-drawing', css)
