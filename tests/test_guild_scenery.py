"""Biome/room assignments, saved scenes, legacy battles and approved assets."""
import hashlib
import json
from pathlib import Path
import unittest

import test_chest_mimic as fixtures
from arena_guild_rules import CONTRACTS, RANKS, art, make_map
from arena_guild_scenery import BACKGROUNDS, room_background, assign_background, background_view
from arena_raid_web import raid_view

ROOT=Path(__file__).resolve().parents[1]


class SceneryContentTests(unittest.TestCase):
    def test_room_rules_keep_locations_distinct_and_ignore_rank(self):
        for biome in ('mines','forest','crypt','caldera'):
            for rank in RANKS:
                c=dict(kind='dungeon',biome=biome,rank=rank)
                for kind in ('entry','battle','event','rest','treasure','elite','boss'):
                    node=dict(kind=kind,event='well' if kind=='event' else '')
                    key=room_background(c,node)
                    if biome=='caldera':self.assertEqual(key,'biome')
                    elif biome=='forest':self.assertEqual(key,'cavern' if kind in ('treasure','elite','boss') else 'biome')
                    elif kind in ('treasure','elite','boss'):self.assertEqual(key,'hall')
                    else:self.assertEqual(key,'catacombs' if biome=='crypt' else 'cavern')
                for event in ('shrine','chest'):
                    expected='hall' if biome in ('mines','crypt') else 'cavern' if biome=='forest' and event=='chest' else 'biome'
                    self.assertEqual(room_background(c,dict(kind='event',event=event)),expected)
        self.assertEqual(room_background(dict(kind='hunt',biome='crypt'),dict(kind='boss')),'biome')
        self.assertEqual(room_background(dict(kind='elite',biome='mines'),dict(kind='boss')),'biome')

    def test_generated_rooms_have_stable_assignments_and_no_arbitrary_urls(self):
        for c in CONTRACTS.values():
            one=make_map(c,42);self.assertEqual(one,make_map(c,42))
            if c['kind']=='dungeon':
                for n in one:self.assertEqual(n['scenery'],room_background(c,n))
        c=CONTRACTS['c_dungeon'];node=dict(kind='battle',scenery='hall')
        self.assertEqual(assign_background(c,node),'hall')
        node['scenery']='https://attacker.invalid/image.png'
        self.assertEqual(assign_background(c,node),'catacombs')
        self.assertEqual(background_view('https://attacker.invalid/image.png')['url'],'')

    def test_runtime_art_is_exact_approved_art_and_v1_is_preserved(self):
        pairs=[('art/dungeon-gray-anime-v1/01-vaulted-hall.png',BACKGROUNDS['hall'][1]),
               ('art/dungeon-gray-anime-v1/02-catacombs.png',BACKGROUNDS['catacombs'][1]),
               ('art/dungeon-gray-anime-v1/03-cavern.png',BACKGROUNDS['cavern'][1]),
               ('art/chest-mimic-anime-v1/03-brush.png',art('chest_mimic'))]
        for source,url in pairs:
            a=(ROOT/source).read_bytes();b=(ROOT/'webapp'/url.removeprefix('/static/')).read_bytes()
            self.assertEqual(hashlib.sha256(a).digest(),hashlib.sha256(b).digest())
        self.assertTrue(art('chest_mimic').endswith('-v2.png'))
        self.assertTrue((ROOT/'webapp/assets/guild/chest_mimic-v1.png').is_file())


class SceneryStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ChestStoreTests.asyncSetUp
    asyncTearDown=fixtures.ChestStoreTests.asyncTearDown

    async def room(self,kind='treasure',legacy=False):
        run=await self.db.guild_create(-100,10,'c_dungeon','scenery-create-request')
        run=await self.db.guild_action(run['id'],10,'start',run['revision'])
        with self.db.connection:
            row=self.db._guild_row_locked(run['id']);node=next(n for n in row['data']['nodes'] if n['id']=='a1')
            node.update(kind=kind,roll=.25);node.pop('event',None);node.pop('scenery',None)
            if not legacy:assign_background(row['data']['contract'],node)
            self.db._guild_save_locked(row)
        run=await self.db.guild_get(run['id'],10)
        return await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='a1')

    async def test_chest_scene_survives_restart_and_battle_is_frozen(self):
        run=await self.room()
        self.assertEqual(run['room_scenery'],background_view('hall'))
        await self.db.close();await self.db.connect()
        run=await self.db.guild_get(run['id'],10)
        self.assertEqual(run['room_scenery'],background_view('hall'))
        run=await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='open')
        raw=await self.db.arena_raid_get(run['battle']);view=await raid_view(self.db,raw,10)
        self.assertEqual(view['guild_scenery'],background_view('hall'))
        self.assertEqual(view['data']['enemies']['e1']['sprite_url'],art('chest_mimic'))
        with self.db.connection:
            row=self.db._guild_row_locked(run['id'])
            next(n for n in row['data']['nodes'] if n['id']=='a1')['scenery']='cavern'
            self.db._guild_save_locked(row)
        raw=await self.db.arena_raid_get(run['battle'])
        self.assertEqual((await raid_view(self.db,raw,10))['guild_scenery'],background_view('hall'))

    async def test_legacy_room_assigns_once_but_old_active_battle_keeps_old_look(self):
        run=await self.room('battle',legacy=True)
        self.assertEqual(run['room_scenery']['key'],'catacombs')
        raw=await self.db.arena_raid_get(run['battle'])
        self.assertEqual(json.loads(raw['data_json'])['guild_scenery'],'catacombs')
        with self.db.connection:
            data=json.loads(raw['data_json']);data.pop('guild_scenery')
            self.db._raid_save_locked(raw,data)
        raw=await self.db.arena_raid_get(run['battle'])
        view=await raid_view(self.db,raw,10)
        self.assertEqual(view['guild_scenery'],background_view(None))

    async def test_non_dungeon_order_keeps_old_biome_background(self):
        run=await self.db.guild_create(-100,10,'c_hunt','ordinary-hunt-request')
        run=await self.db.guild_action(run['id'],10,'start',run['revision'])
        raw=await self.db.arena_raid_get(run['battle'])
        self.assertEqual((await raid_view(self.db,raw,10))['guild_scenery']['url'],'')

    async def test_regular_mob_has_compact_health_but_keeps_details_and_target(self):
        from test_arena_market_client import ArenaMarketClientTests
        run=await self.room('battle');raw=await self.db.arena_raid_get(run['battle'])
        view=await raid_view(self.db,raw,10)
        self.assertFalse(view['guild_boss_encounter'])
        # This historical combat flag must not turn a normal encounter into a
        # full raid-boss presentation.
        view['data']['enemies']['e1']['is_boss']=True
        html=ArenaMarketClientTests().run_client('raidCurrent=input;out=encounterPortrait(input.data.enemies.e1,"e1",0);',view)
        self.assertIn('encounter-compact-hud',html)
        self.assertIn('data-raid="inspect:e1"',html)
        self.assertIn('data-raid="target:e1"',html)
        self.assertNotIn('<strong',html)
        self.assertNotIn(' · Lv.',html)
        self.assertIn('encounter-hp-value',html)

    async def test_dungeon_boss_and_nazarick_keep_full_cards(self):
        from test_arena_market_client import ArenaMarketClientTests
        run=await self.room('boss');raw=await self.db.arena_raid_get(run['battle'])
        view=await raid_view(self.db,raw,10)
        self.assertTrue(view['guild_boss_encounter'])
        render=ArenaMarketClientTests().run_client
        code='raidCurrent=input;out=encounterPortrait(input.data.enemies.e1,"e1",0);'
        html=render(code,view)
        self.assertNotIn('encounter-compact-hud',html);self.assertIn('<strong',html);self.assertIn(' · Lv.',html)
        # Legacy guild saves derive the room role without a conversion.
        with self.db.connection:
            data=json.loads(raw['data_json']);data.pop('guild_boss_room')
            self.db._raid_save_locked(raw,data)
        self.assertTrue((await raid_view(self.db,await self.db.arena_raid_get(run['battle']),10))['guild_boss_encounter'])
        view['guild_boss_encounter']=False;view['nazarick_run_id']='guardian-run'
        self.assertNotIn('encounter-compact-hud',render(code,view))


if __name__=='__main__':unittest.main()
