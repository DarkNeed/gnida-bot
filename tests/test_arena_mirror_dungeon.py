import asyncio
import json
import random
import unittest
from unittest.mock import patch

import test_arena_mirror as fixtures
from arena_engine import FIGHTER_CLASSES, MAX_FIGHTER_LEVEL, create_battle_state, fighter_xp_limit
from arena_mirror_dungeon import DEPTH, MIRROR_TITLE, elite_shard_rank, enemy_card, floor_enemy_level, make_route, make_floor, scale_enemy


class RouteTests(unittest.TestCase):
    def test_only_late_elites_can_grant_gear_shards(self):
        rng=random.Random(1)  # first roll < 15%
        self.assertIsNone(elite_shard_rank(6,rng))
        self.assertEqual(elite_shard_rank(7,rng),'A')
        self.assertEqual(elite_shard_rank(9,random.Random(1)),'S')
        self.assertIsNone(elite_shard_rank(10,random.Random(2)))

    def test_floor_lengths_and_single_shop_and_boss(self):
        lengths=set()
        for seed in range(100):
            route,boss=make_floor(seed%10+1,FIGHTER_CLASSES,random.Random(seed))
            lengths.add(len(route)+1)
            self.assertEqual([n['lane'] for n in route[-1]['nodes'] if n['kind']=='shop'],[1])
            self.assertEqual(sum(n['kind']=='shop' for row in route for n in row['nodes']),1)
            self.assertTrue(any(len(row['nodes'])==2 for row in route[:-1]))
            self.assertEqual(enemy_card(boss)['level'],floor_enemy_level(seed%10+1,'boss'))
            for prev,row in zip(route,route[1:]):
                self.assertEqual({x for x,_ in row['links']},{n['lane'] for n in prev['nodes']})
                self.assertEqual({y for _,y in row['links']},{n['lane'] for n in row['nodes']})
        self.assertEqual(lengths,{5,6,7,8})

    def test_levels_increase_and_late_floors_raise_combat_stats_above_cap(self):
        for kind, last_level in [('fight',25),('elite',28),('boss',30)]:
            levels=[floor_enemy_level(floor,kind) for floor in range(1,DEPTH+1)]
            self.assertEqual((levels[0],levels[-1]),(15,last_level))
            self.assertEqual(levels,sorted(set(levels)))
        route,boss=make_floor(DEPTH,{'warrior'},random.Random(0))
        for kind,last_level in [('fight',25),('elite',28),('boss',30)]:
            enemy=boss if kind=='boss' else next(n['enemy'] for row in route for n in row['nodes'] if n['kind']==kind)
            self.assertEqual(enemy_card(enemy)['level'],last_level)
            state=create_battle_state(dict(enemy,slave_id=1,owner_id=1),enemy)
            player,fighter=state['sides'].values()
            baseline=create_battle_state(enemy,enemy)['sides']['b']
            scale_enemy(baseline,DEPTH,kind,chapter=True)
            scale_enemy(fighter,DEPTH,kind,chapter=True,mirror_level=enemy['mirror_level'])
            self.assertEqual(player['level'],MAX_FIGHTER_LEVEL)
            self.assertEqual(fighter['level'],last_level)
            self.assertEqual(fighter['loadout'],baseline['loadout'])
            for key in ('max_hp','physical_attack','physical_defense','magic_defense'):
                self.assertGreater(fighter['stats'][key],baseline['stats'][key])
            self.assertEqual(fighter['hp'],fighter['stats']['max_hp'])

    def test_every_lane_remains_connected_and_layout_varies_across_runs(self):
        signatures=set()
        for seed in range(100):
            route,boss=make_route(10,FIGHTER_CLASSES,random.Random(seed))
            self.assertEqual(len(route),DEPTH)
            self.assertEqual(boss['level'],14)
            self.assertEqual(sum(len(row['nodes'])==2 for row in route[1:-1]),5)
            self.assertEqual(route[-1]['nodes'],[dict(id='f10-1',kind='shop',lane=1)])
            previous=None
            for row in route:
                lanes={n['lane'] for n in row['nodes']}
                self.assertEqual(len(lanes),len(row['nodes']))
                if previous is not None:
                    self.assertEqual({a for a,_ in row['links']},previous)
                    self.assertEqual({b for _,b in row['links']},lanes)
                    self.assertTrue(all(abs(a-b)<=1 for a,b in row['links']))
                previous=lanes
            signatures.add(str(route[1]['links']))
        self.assertGreater(len(signatures),8)


class DungeonTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.MirrorStoreTests.asyncSetUp
    asyncTearDown=fixtures.MirrorStoreTests.asyncTearDown
    move=fixtures.MirrorStoreTests.move
    win=fixtures.MirrorStoreTests.win

    async def settle(self, run, *, won=True, wounded=False):
        row=await self.db.arena_get(run['battle_token'])
        state=json.loads(row['state_json'])
        if wounded:state['sides']['a'].update(hp=2 if won else 0,resource=0)
        state.update(finished=True,winner='a' if won else 'b',finish_reason='knockout')
        with self.db.connection:
            self.db._arena_finish_locked(row,state)
            self.db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',(json.dumps(state),row['token']))
        return await self.db.arena_mirror_get(run['token'],10)

    async def test_normal_battle_awards_dust_via_the_live_queue(self):
        run=await self.db.arena_mirror_start(1,10)
        run=await self.move(run,'visit',run['available'][0])
        run=await self.win(run)
        self.assertEqual((run['phase'],run['floor'],run['step'],run['dust'],run['francs']),('map',1,2,18,0))

    async def test_boss_won_in_live_queue_restores_and_unlocks_next_floor(self):
        run=await self.shop(await self.db.arena_mirror_start(1,10))
        run=await self.move(run,'next')
        run=await self.win(run,hp=2,resource=0)
        self.assertEqual((run['phase'],run['hp'],run['resource']),('landing',run['max_hp'],run['resource_max']))
        await self.db.close();await self.db.connect()
        self.assertEqual(await self.db.arena_mirror_get(run['token'],10),run)
        next_floor=await self.move(run,'next')
        self.assertEqual((next_floor['floor'],next_floor['step'],next_floor['dust'],next_floor['path']),
                         (2,1,run['dust'],[]))

    async def test_losing_boss_does_not_heal_or_mark_floor_cleared(self):
        run=await self.shop(await self.db.arena_mirror_start(1,10))
        run=await self.settle(await self.move(run,'next'),won=False,wounded=True)
        self.assertEqual((run['status'],run['cleared'],run['hp'],run['resource']),('lost',0,0,0))

    async def test_route_is_saved_enemy_preview_matches_and_shortcuts_refused(self):
        run=await self.db.arena_mirror_start(1,10)
        self.assertEqual((run['phase'],run['total_floors'],len(run['available'])),('map',10,3))
        self.assertEqual(run['dust'],0)
        self.assertEqual(run['battle_token'],'')
        self.assertNotIn('route',(await self.db.arena_mirror_list(1,10))[0])
        with self.assertRaises(ValueError):await self.move(run,'visit','f2-0')
        await self.db.close();await self.db.connect()
        self.assertEqual(await self.db.arena_mirror_get(run['token'],10),run)
        node=next(n for n in run['route'][0]['nodes'] if n.get('mob'))
        self.assertEqual(node['mob']['level'],15)
        run=await self.move(run,'visit',node['id'])
        row=await self.db.arena_get(run['battle_token'])
        state=json.loads(row['state_json'])
        self.assertEqual(state['sides']['b']['level'],node['mob']['level'])
        self.assertFalse(state['mirror_boss'])
        run=await self.settle(run)
        self.assertEqual(run['phase'],'map')
        self.assertEqual(run['dust'],18)
        self.assertFalse(run['offers'])
        with self.assertRaises(ValueError):await self.move(run,'buy','edge')
        with self.assertRaises(ValueError):await self.move(run,'next')
        lane=node['lane']
        expected={f'f2-{b}' for a,b in run['route'][1]['links'] if a==lane}
        self.assertEqual(set(run['available']),expected)
        if rejected:=({'f2-0','f2-1','f2-2'}-expected):
            with self.assertRaises(ValueError):await self.move(run,'visit',rejected.pop())
        run=await self.shop(run)
        item=next(o for o in run['offers'] if o['kind']=='artifact')
        before=run['dust'];run=await self.move(run,'buy',item['id'])
        self.assertEqual(run['dust'],before-item['price'])
        with self.assertRaises(ValueError):await self.move(run,'buy',item['id'])
        run=await self.move(run,'next')
        row=await self.db.arena_get(run['battle_token'])
        self.assertIn(item['id'],json.loads(row['state_json'])['sides']['a']['mirror_gifts'])

    async def shop(self, run):
        floor=run['floor']
        for step in range(run['step'],len(run['route'])):
            self.assertEqual((run['floor'],run['step'],run['phase']),(floor,step,'map'))
            before=run['dust']
            run=await self.move(run,'visit',run['available'][0])
            if run['phase']=='combat':run=await self.settle(run)
            else:self.assertEqual(run['dust'],before)
        self.assertEqual(run['available'],[f'f{run["step"]}-1'])
        with self.assertRaises(ValueError):await self.move(run,'next')
        with self.assertRaises(ValueError):await self.move(run,'visit',f'f{run["step"]}-0')
        dust=run['dust']
        run=await self.move(run,'visit',run['available'][0])
        self.assertEqual((run['phase'],run['cleared'],run['dust']),('merchant',floor-1,dust))
        return run

    async def reach(self, floor):
        run=await self.db.arena_mirror_start(1,10)
        for stage in range(1,floor+1):
            self.assertEqual((run['floor'],run['step']),(stage,1))
            run=await self.shop(run)
            run=await self.move(run,'next')
            self.assertTrue(run['boss_active'])
            if stage==DEPTH:
                row=await self.db.arena_get(run['battle_token'])
                self.assertEqual(json.loads(row['state_json'])['sides']['b']['level'],30)
            run=await self.settle(run,wounded=True)
            self.assertEqual((run['cleared'],run['hp'],run['resource']),(stage,run['max_hp'],run['resource_max']))
            if stage!=floor:
                self.assertEqual(run['phase'],'landing')
                run=await self.move(run,'next')
        return run

    async def test_finishing_all_ten_shops_and_selecting_treasure_exactly_once(self):
        run=await self.reach(DEPTH)
        self.assertEqual(run['francs'],240)
        self.assertEqual(run['pages'],{'common':4,'uncommon':4,'rare':4})
        self.assertGreaterEqual(run['gear_shards']['S'],3)
        self.assertEqual(await self.db.franc_balance(1,10),240)
        self.assertEqual((run['status'],run['phase']),('finished','reward'))
        self.assertEqual(run['francs'],240)
        with self.assertRaisesRegex(ValueError,'трофей'):await self.db.arena_mirror_start(1,10)
        # Even two taps from stale browser screens must never grant a second set.
        receipts=await asyncio.gather(self.move(run,'claim','pages'),self.move(run,'claim','pages'),return_exceptions=True)
        self.assertEqual(sum(isinstance(x,dict) for x in receipts),1)
        result=await self.db.arena_mirror_get(run['token'],10)
        self.assertEqual(result['phase'],'ended')
        self.assertEqual(result['pages'],{'common':4,'uncommon':4,'rare':10})
        self.assertEqual(self.db._forge_wallet_locked(1,10)['pages'],result['pages'])

    async def test_weekly_epic_choice_is_saved_and_reward_can_only_be_salvaged(self):
        with self.db.connection:
            self.db._grant_profile_xp_locked('personal_profiles',1,10,fighter_xp_limit())
            self.db.connection.execute(
                "UPDATE personal_profiles SET class_id='warrior',progression_level=20,progression_pending_level=0 WHERE chat_id=0 AND user_id=10")
        with patch('arena_mirror.message_week',return_value=100):
            run=await self.reach(DEPTH)
            self.assertTrue(run['weekly_bonus'])
            self.assertEqual(await self.db.arena_mirror_title(10),MIRROR_TITLE)
            choices=[i for i in run['rewards'] if i['kind']=='gear']
            self.assertEqual({i['id'] for i in choices},{'gear-weapon','gear-armor','gear-accessory','gear-relic'})
            self.assertTrue(all(i['rarity']=='epic' for i in choices))
            picked=choices[0]
            await self.db.close();await self.db.connect()
            self.assertEqual((await self.db.arena_mirror_get(run['token'],10))['rewards'],run['rewards'])
            claimed=await self.move(run,'claim',picked['id'])
            reward=claimed['item_rewards'][0]
            self.assertEqual(reward['stats'],picked['stats'])
            self.assertEqual(reward['rank'],'S')
            self.assertFalse(reward['sellable'])
            gear=await self.db.gear_view(1,10)
            with self.assertRaisesRegex(ValueError,'нельзя продать'):
                await self.db.gear_action(1,10,dict(action='sell',item=reward['id'],price=0,confirm=True,
                                                    revision=gear['revision'],nonce='mirror-sell-test'))
            self.assertFalse(any(i['id']==reward['id'] for i in self.db._gear_market_locked(1,10)['items']))
            shards=gear['materials']['S']
            gear=await self.db.gear_action(1,10,dict(action='salvage',item=reward['id'],revision=gear['revision'],
                                                    nonce='mirror-salvage-test'))
            self.assertEqual(gear['materials']['S'],shards+8)
            repeat=await self.reach(DEPTH)
            self.assertFalse(repeat['weekly_bonus'])
            self.assertTrue(all(i['rarity']=='rare' for i in repeat['rewards'] if i['kind']=='gear'))
            await self.move(repeat,'claim','pages')
        with patch('arena_mirror.message_week',return_value=200):
            next_week=await self.reach(DEPTH)
            self.assertTrue(next_week['weekly_bonus'])

    async def test_treatises_omit_learned_and_already_owned_options(self):
        with self.db.connection:
            self.db._arena_add_item_locked(1,10,'passive','battle_rhythm','rare')
            self.db.connection.execute("INSERT INTO arena_learned VALUES(0,10,1,'passive','magic_ward')")
            offers=self.db._mirror_scroll_choices_locked(1,10,random.Random(0))
            self.assertEqual(len(offers),3)
            self.assertTrue({'battle_rhythm','magic_ward'}.isdisjoint(i['content_id'] for i in offers))

    async def test_checkpoint_rewards_survive_abandonment(self):
        run=await self.reach(3)
        run=await self.move(run,'abandon')
        self.assertEqual((run['status'],run['francs'],run['pages']),('cancelled',25,{'common':4}))
        self.assertEqual(await self.db.franc_balance(1,10),25)

    async def test_stored_single_map_run_can_still_continue(self):
        run=await self.db.arena_mirror_start(1,10,_route_version=1)
        self.assertEqual(len(run['route']),10)
        run=await self.settle(await self.move(run,'visit',run['available'][0]))
        self.assertEqual((run['phase'],run['cleared']),('merchant',1))
        run=await self.move(run,'next')
        self.assertEqual((run['phase'],run['step'],run['floor']),('map',2,2))
