"""Guild transactions, native combat, party snapshots and API isolation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from aiohttp.test_utils import TestClient,TestServer
from database import Database
from arena_guild_rules import CONTRACTS,MONSTERS,SKILLS,EVENTS,CONTRACT_FLAVOUR,art,make_map,mob_templates
from arena_raid_web import raid_view
from arena_web import create_arena_app
from arena_raid_engine import finish_if_needed
from test_arena import signed,TOKEN


class GuildTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.folder.name)/'guild.sqlite3');await self.db.connect()
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Охотники')
            for actor in (10,20,30):await self.db.upsert_user(chat,actor,str(actor),'Охотник '+str(actor))
        for actor in (10,20,30):
            self.db._arena_profile_locked(-100,actor,True)
            self.db.connection.execute("UPDATE personal_profiles SET class_id='warrior',level=20,progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?",
                (json.dumps(['bum_punch','armor_split','steel_charge']),actor))
            self.db._guild_hunter_locked(actor)
            self.db.connection.execute('UPDATE guild_hunters SET rank=3,peak_rank=3 WHERE actor_id=?',(actor,))
            self.db._add_francs_locked(-100,actor,1000)
        self.db.connection.commit()

    async def asyncTearDown(self):await self.db.close();self.folder.cleanup()

    async def create(self,key='c_dungeon',actor=10,chat=-100):
        return await self.db.guild_create(chat,actor,key,'nonce-'+str(actor)+'-'+key)

    async def start(self,key='c_dungeon',party=False):
        run=await self.create(key)
        if party:run=await self.db.guild_action(run['id'],20,'join',run['revision'])
        return await self.db.guild_action(run['id'],10,'start',run['revision'])

    async def win_room(self,run):
        async with self.db._lock:
            with self.db.connection:
                row=self.db._raid_row_locked(run['battle']);d=json.loads(row['data_json'])
                for e in d['enemies'].values():e['hp']=0
                self.assertTrue(finish_if_needed(d));self.db._raid_finish_locked(row,d)
        return await self.db.guild_get(run['id'],10)

    async def test_start_snapshot_quota_and_replay(self):
        run=await self.start(party=True)
        self.assertEqual(run['status'],'active')
        self.assertEqual(self.db._guild_used_locked(10),1)
        self.assertEqual(self.db._guild_used_locked(20),1)
        again=await self.db.guild_action(run['id'],10,'start',0)
        self.assertEqual(again['id'],run['id']);self.assertEqual(self.db._guild_used_locked(10),1)
        created=await self.db.guild_create(-100,10,'c_dungeon','nonce-10-c_dungeon')
        self.assertEqual(created['id'],run['id'])
        self.db.connection.execute("UPDATE personal_profiles SET level=1,class_id='ragamuffin' WHERE chat_id=0 AND user_id=10");self.db.connection.commit()
        fresh=await self.db.guild_get(run['id'],10)
        self.assertEqual(fresh['members'][0]['max_hp'],run['members'][0]['max_hp'])
        with self.assertRaises(ValueError):await self.db.guild_create(-200,10,'c_hunt','other-nonce')

    async def test_rank_limit_each_member_and_lobby_free(self):
        self.db.connection.execute('UPDATE guild_hunters SET rank=0 WHERE actor_id=20');self.db.connection.commit()
        run=await self.create()
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],20,'join',run['revision'])
        with self.assertRaises(ValueError):await self.db.guild_create(-100,10,'s_hunt','illegal-rank')
        self.assertEqual(self.db._guild_used_locked(10),0)
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],20,'start',run['revision'])
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],20,'vote',run['revision'],choice='a1')

    async def test_party_votes_hidden_map_and_native_qte_snapshot(self):
        run=await self.start(party=True)
        self.assertTrue(any(n['kind']=='unknown' for n in run['nodes']))
        self.assertFalse(any('roll' in n for n in run['nodes']))
        run=await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='a1')
        self.assertEqual(run['position'],'start');self.assertEqual(run['votes'],{'10':'a1'})
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='b1')
        run=await self.db.guild_action(run['id'],20,'vote',run['revision'],choice='b1')
        self.assertEqual(run['position'],'a1') # tied: leader decides
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],30,'vote',run['revision'],choice='boss')

    async def test_room_battle_preserves_hp_resource_and_no_generic_rewards(self):
        run=await self.start('c_hunt')
        row=await self.db.arena_raid_get(run['battle']);d=json.loads(row['data_json'])
        self.assertFalse(d['players']['10']['fighter'].get('rp_sandbox',False))
        self.assertFalse(d['rp_mode'])
        self.assertIn('guild_monster',next(iter(d['enemies'].values())))
        public=await raid_view(self.db,row,10)
        self.assertEqual(public['guild_run_id'],run['id']);self.assertFalse(public['is_master'])
        self.assertEqual(public['data']['enemies']['e1']['sprite_url'],art('troll'))
        import test_arena_market_client as client_tests
        renderer=client_tests.ArenaMarketClientTests()
        image=renderer.run_client('out=fighterImage(input.data.enemies.e1,"raid-sprite");',public)
        self.assertIn('src="'+art('troll')+'"',image)
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(run['battle'],10,'finish')
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(run['battle'],10,'join',rp_template='forged')
        before=await self.db.franc_balance(-100,10)
        finished=await self.win_room(run)
        self.assertEqual(finished['status'],'completed')
        self.assertEqual(await self.db.franc_balance(-100,10),before+CONTRACTS['c_hunt']['reward']+23)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_raid_reward_cooldowns').fetchone()[0],0)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM guild_settlements').fetchone()[0],1)
        again=await self.db.guild_get(run['id'],10);self.assertEqual(again['results'],finished['results'])

    async def test_remaining_fighter_state_between_rooms(self):
        run=await self.start()
        async with self.db._lock:
            with self.db.connection:
                row=self.db._guild_row_locked(run['id']);node=next(n for n in row['data']['nodes'] if n['id']=='a1');node['kind']='battle'
                row['data']['players']['10']['fighter'].update(hp=33,resource=17)
                self.db._guild_save_locked(row)
        run=await self.db.guild_get(run['id'],10)
        run=await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='a1')
        native=json.loads((await self.db.arena_raid_get(run['battle']))['data_json'])
        self.assertEqual(native['players']['10']['fighter']['hp'],33)
        self.assertEqual(native['players']['10']['fighter']['resource'],17)
        run=await self.win_room(run)
        self.assertEqual(run['members'][0]['hp'],33);self.assertEqual(run['members'][0]['resource'],17)
        self.assertEqual(run['status'],'active');self.assertIsNone(run['battle'])
        self.assertEqual(await self.db.franc_balance(-100,10),1000)

    async def test_board_exposes_a_unique_sprite_for_every_monster(self):
        board=await self.db.guild_view(-100,10)
        self.assertEqual({m['id']:m['sprite'] for m in board['monsters']},
                         {key:art(key) for key in MONSTERS})

    async def test_supplies_purchase_idempotent_rank_and_use_atomic(self):
        await self.db.guild_buy(-100,10,'bandage','purchase-one')
        await self.db.guild_buy(-100,10,'bandage','purchase-one')
        self.assertEqual(await self.db.franc_balance(-100,10),965)
        with self.assertRaises(ValueError):await self.db.guild_buy(-100,10,'revive','purchase-two')
        with self.assertRaises(ValueError):await self.db.guild_buy(-100,10,'ration','purchase-one')
        run=await self.start();run=await self.db.guild_action(run['id'],10,'supply',run['revision'],item='bandage')
        self.assertEqual(run['bag']['bandage'],0)
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'supply',run['revision'],item='bandage')

    async def test_daily_account_limit_reset_and_safe_retreat(self):
        for i in range(3):
            run=await self.db.guild_create(-100,10,'c_dungeon','daily-nonce-'+str(i))
            run=await self.db.guild_action(run['id'],10,'start',run['revision'])
            run=await self.db.guild_action(run['id'],10,'retreat',run['revision'])
        self.assertEqual(self.db._guild_used_locked(10),3)
        with self.assertRaises(ValueError):await self.db.guild_create(-200,10,'c_hunt','fourth-one')
        with patch('arena_guild.raid_day',return_value='2099-01-01'):
            self.assertEqual(self.db._guild_used_locked(10),0)
        profile=self.db._guild_hunter_locked(10)
        self.assertEqual(profile['rank'],2);self.assertEqual(profile['losses'],3)

    async def test_saved_restart_and_expiry_once(self):
        run=await self.start()
        await self.db.close();await self.db.connect()
        fresh=await self.db.guild_get(run['id'],10);self.assertEqual(fresh['nodes'],run['nodes'])
        self.db.connection.execute('UPDATE guild_runs SET expires=0 WHERE id=?',(run['id'],));self.db.connection.commit()
        fresh=await self.db.guild_get(run['id'],10);self.assertEqual(fresh['status'],'failed')
        await self.db.guild_get(run['id'],10)
        self.assertEqual(self.db._guild_hunter_locked(10)['losses'],1)

    async def test_api_membership_forged_actor_and_inputs(self):
        app=create_arena_app(self.db,self.bot,TOKEN)
        async with TestClient(TestServer(app)) as client:
            res=await client.get('/api/guild/board?chat=-100');self.assertEqual(res.status,400)
            headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
            res=await client.get('/api/guild/board?chat=-999',headers=headers);self.assertEqual(res.status,400)
            res=await client.get('/api/guild/board?chat=-100',headers=headers);self.assertEqual(res.status,200)
            res=await client.post('/api/guild/runs',headers=headers,json=dict(chat=-100,contract='c_hunt',nonce='api-create-one',actor=30))
            self.assertEqual(res.status,200);run=await res.json();self.assertEqual(run['leader'],10)
            res=await client.post('/api/guild/runs/'+run['id'],headers={'X-Telegram-Init-Data':signed(20,int(time.time()))},json=dict(action='start',revision=run['revision']))
            self.assertEqual(res.status,400)

    async def test_full_dungeon_personal_payouts_and_real_tractate_once(self):
        run=await self.start(party=True)
        # Choose one valid route; replace only RNG room selection in this test.
        async with self.db._lock:
            with self.db.connection:
                row=self.db._guild_row_locked(run['id'])
                for n in row['data']['nodes']:
                    if n['id'] in ('a1','a2'):n.update(kind='event',event='well')
                self.db._guild_save_locked(row)
        run=await self.db.guild_get(run['id'],10)
        async def vote(choice):
            nonlocal run
            run=await self.db.guild_action(run['id'],10,'vote',run['revision'],choice=choice)
            run=await self.db.guild_action(run['id'],20,'vote',run['revision'],choice=choice)
        for ident in ('a1','a2','a3','a4','boss'):
            await vote(ident)
            if run['pending']:await vote('heal' if run['pending']['kind']=='rest' else 'leave')
        self.assertTrue(run['battle'])
        run=await self.win_room(run)
        self.assertEqual(run['status'],'completed')
        self.assertEqual(set(run['results']),{'10','20'})
        for actor in (10,20):
            reward=run['results'][str(actor)]
            self.assertIn('трактат',reward['loot'])
            self.assertEqual(await self.db.franc_balance(-100,actor),1000+reward['francs'])
            self.assertEqual(await self.db.franc_balance(-200,actor),0)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM guild_settlements').fetchone()[0],2)
        self.assertEqual(self.db.connection.execute("SELECT SUM(quantity) FROM arena_inventory WHERE kind='skill'").fetchone()[0],2)
        await self.db.guild_get(run['id'],20)
        self.assertEqual(self.db.connection.execute("SELECT SUM(quantity) FROM arena_inventory WHERE kind='skill'").fetchone()[0],2)

    async def test_promotion_requires_qualification_and_cannot_farm_easy_rank(self):
        self.db.connection.execute('UPDATE guild_hunters SET reputation=84,rank_wins=3,clearance=0 WHERE actor_id=10');self.db.connection.commit()
        run=await self.start('c_elite');await self.win_room(run)
        hunter=self.db._guild_hunter_locked(10)
        self.assertEqual(hunter['rank'],4);self.assertEqual(hunter['reputation'],0)
        run=await self.db.guild_create(-100,10,'f_hunt','easy-no-rank')
        run=await self.db.guild_action(run['id'],10,'start',run['revision']);await self.win_room(run)
        self.assertEqual(self.db._guild_hunter_locked(10)['reputation'],0)

    async def test_calibration_is_solo_once_uses_daily_ticket(self):
        self.db.connection.execute('UPDATE guild_hunters SET rank=0,peak_rank=0 WHERE actor_id=10');self.db.connection.commit()
        run=await self.db.guild_create(-100,10,'calibration','calibrate-me')
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],20,'join',run['revision'])
        run=await self.db.guild_action(run['id'],10,'start',run['revision'])
        self.assertEqual(self.db._guild_used_locked(10),1)
        finished=await self.win_room(run)
        self.assertEqual(finished['results']['10']['rank'],'C')
        self.assertEqual(finished['results']['10']['reputation'],0)
        with self.assertRaises(ValueError):await self.db.guild_create(-100,10,'calibration','calibrate-again')

    async def test_event_effects_are_real_and_duplicate_click_cannot_reapply(self):
        run=await self.start()
        async with self.db._lock:
            with self.db.connection:
                row=self.db._guild_row_locked(run['id']);node=next(n for n in row['data']['nodes'] if n['id']=='a1');node.update(kind='event',event='shrine')
                row['data']['players']['10']['fighter']['hp']=1;self.db._guild_save_locked(row)
        run=await self.db.guild_get(run['id'],10)
        run=await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='a1')
        rev=run['revision'];run=await self.db.guild_action(run['id'],10,'vote',rev,choice='blessing')
        self.assertGreater(run['members'][0]['hp'],1)
        saved=self.db._guild_row_locked(run['id'])['data']['players']['10']['fighter']
        self.assertTrue(any(e['kind']=='damage_taken_pct' for e in saved['effects']))
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'vote',rev,choice='blessing')
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='blessing')

    async def test_vote_timeout_uses_cast_vote_and_no_off_route_teleport(self):
        run=await self.start(party=True)
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='boss')
        run=await self.db.guild_action(run['id'],20,'vote',run['revision'],choice='b1')
        async with self.db._lock:
            with self.db.connection:
                row=self.db._guild_row_locked(run['id']);row['data']['vote_deadline']=1;self.db._guild_save_locked(row)
        run=await self.db.guild_get(run['id'],10)
        self.assertEqual(run['position'],'b1')

    async def test_active_battle_expiry_cancels_qte_and_releases_reservations(self):
        run=await self.start('c_hunt')
        await self.db.arena_interactive_raid(run['battle'],10,1,'bum_punch',target='e1')
        self.assertIsNotNone(self.db._qte_load_locked('raid',run['battle'],10))
        self.db.connection.execute('UPDATE guild_runs SET expires=0 WHERE id=?',(run['id'],));self.db.connection.commit()
        ended=await self.db.guild_get(run['id'],10)
        self.assertEqual(ended['status'],'failed')
        self.assertEqual((await self.db.arena_raid_get(run['battle']))['status'],'cancelled')
        self.assertIsNone(self.db._qte_load_locked('raid',run['battle'],10))
        self.assertFalse(self.db._arena_busy_locked(-100,10))

    async def test_interactive_action_and_defense_proofs_work_in_guild(self):
        run=await self.start('c_hunt')
        async with self.db._lock:
            with self.db.connection:
                raid=self.db._raid_row_locked(run['battle']);data=json.loads(raid['data_json'])
                data['players']['10']['fighter']['hp']=10000
                data['players']['10']['fighter']['stats']['max_hp']=10000
                self.db._raid_save_locked(raid,data)
        await self.db.arena_interactive_raid(run['battle'],10,1,'armor_split',target='e1')
        while flow:=self.db._qte_load_locked('raid',run['battle'],10):
            await self.db.arena_interactive_raid(run['battle'],10,1,proof=dict(abort=True),challenge_id=flow['stages'][0]['id'])
        native=json.loads((await self.db.arena_raid_get(run['battle']))['data_json'])
        self.assertEqual(native['round'],2)
        self.assertEqual(native['players']['10']['fighter']['resource'],93) # 100−15+8 next-turn regen
        self.assertTrue(any(e.get('skill','').startswith('guild_') for e in native['log']))

    async def test_no_double_payout_after_native_finish_retry(self):
        run=await self.start('c_hunt')
        raid=await self.db.arena_raid_get(run['battle']);old=json.loads(raid['data_json'])
        done=await self.win_room(run)
        money=await self.db.franc_balance(-100,10)
        with self.assertRaises(ValueError):
            async with self.db._lock:
                with self.db.connection:self.db._raid_finish_locked(raid,dict(old,finished=True,won=True))
        self.assertEqual(await self.db.franc_balance(-100,10),money)
        self.assertEqual((await self.db.guild_get(run['id'],10))['results'],done['results'])

    async def test_concurrent_lobby_join_is_capped_at_three(self):
        await self.db.upsert_user(-100,40,'40','Четвёртый')
        self.db._guild_hunter_locked(40);self.db.connection.execute('UPDATE guild_hunters SET rank=3 WHERE actor_id=40');self.db.connection.commit()
        run=await self.create();run=await self.db.guild_action(run['id'],20,'join',run['revision'])
        results=await asyncio.gather(*(self.db.guild_action(run['id'],a,'join',run['revision']) for a in (30,40)),return_exceptions=True)
        self.assertEqual(sum(not isinstance(r,Exception) for r in results),1)
        self.assertEqual(len((await self.db.guild_get(run['id'],10))['members']),3)

    async def test_guild_command_in_group_and_private(self):
        from handlers.guild import create_guild_router,GUILD_RE
        self.assertTrue(GUILD_RE.fullmatch('/гильдия@GnidoBot'))
        router=create_guild_router(self.db,self.bot,'GnidoBot',True)
        handler=router.message.handlers[0].callback
        for kind,chat in (('private',10),('supergroup',-100)):
            message=SimpleNamespace(text='/гильдия',chat=SimpleNamespace(id=chat,type=kind,title='Охотники'),
                from_user=SimpleNamespace(id=10,is_bot=False,username='10',full_name='Охотник'),answer=AsyncMock())
            await handler(message)
            keyboard=message.answer.call_args.kwargs['reply_markup']
            self.assertIn('startapp=guild',keyboard.inline_keyboard[0][0].url)


class GuildContentTests(unittest.TestCase):
    def test_individual_raster_sprites_exist_and_catalog_uses_them(self):
        root=Path(__file__).resolve().parents[1]/'webapp'
        urls=[art(key) for key in MONSTERS]
        self.assertEqual(len(set(urls)),14)
        for url in urls:
            path=root/url.removeprefix('/static/')
            self.assertTrue(path.is_file(),url)
            self.assertEqual(path.read_bytes()[:8],b'\x89PNG\r\n\x1a\n',url)
        source=(root/'guild.js').read_text(encoding='utf-8')
        self.assertIn('const monsterArt=m=>m.sprite;',source)

    def test_authorized_alpha_cleanup_preserves_art_and_never_adds_opacity(self):
        from PIL import Image,ImageChops
        from tools.prepare_guild_sprites import clean_alpha
        source=Image.new('RGBA',(20,20),(40,80,120,0))
        source.putpixel((10,10),(10,30,50,252))
        source.putpixel((9,10),(20,40,60,80))
        source.putpixel((1,1),(60,80,100,80))
        result=clean_alpha(source)
        self.assertIsNone(ImageChops.difference(source.convert('RGB'),result.convert('RGB')).getbbox())
        self.assertEqual(result.getpixel((10,10)),source.getpixel((10,10)))
        self.assertEqual(result.getpixel((9,10)),source.getpixel((9,10)))
        self.assertEqual(result.getpixel((1,1))[3],0)
        self.assertIsNone(ImageChops.subtract(result.getchannel('A'),source.getchannel('A')).getbbox())

    def test_flavour_preserves_objectives_and_explicit_event_costs(self):
        self.assertLess(len(CONTRACT_FLAVOUR),len(CONTRACTS))
        for key,line in CONTRACT_FLAVOUR.items():
            self.assertTrue(CONTRACTS[key]['description'].endswith(line))
            self.assertGreater(len(CONTRACTS[key]['description']),len(line))
        self.assertIn('+40% HP',EVENTS['shrine']['choices'][0]['hint'])
        self.assertIn('+15%',EVENTS['shrine']['choices'][0]['hint'])
        self.assertIn('50/50',EVENTS['cocoon']['choices'][0]['hint'])

    def test_enemy_formation_starts_center_and_steps_diagonally_right(self):
        import re
        css=(Path(__file__).resolve().parents[1]/'webapp/style.css').read_text(encoding='utf-8')
        positions=[]
        for index in range(3):
            match=re.search(r'(?m)^\.encounter-field \.enemy-'+str(index)+r'\{right:(\d+)%?;top:(\d+)%?\}',css)
            self.assertIsNotNone(match)
            positions.append(tuple(map(int,match.groups())))
        self.assertEqual(positions[0],(40,2))
        self.assertTrue(all(a[0]>b[0] and a[1]<b[1] for a,b in zip(positions,positions[1:])))
        self.assertIn('.encounter-field.nazarick-field .enemy-0{right:6%;top:1%;width:37%}',css)

    def test_content_fixed_rank_maps_and_assets(self):
        self.assertEqual(len(CONTRACTS),21);self.assertEqual(len(MONSTERS),14)
        for c in CONTRACTS.values():
            nodes=make_map(c,42)
            self.assertEqual(nodes,make_map(c,42))
            for n in nodes:
                for key in n['links']:self.assertTrue(any(x['id']==key and x['layer']>n['layer'] for x in nodes))
            mobs=mob_templates(c,nodes[-1],3)
            self.assertLessEqual(len(mobs),3)
            if c['kind']=='hunt':
                self.assertEqual(mobs[0]['guild_monster'],c['monsters'][0])
                self.assertEqual(mobs[0]['definition']['stats']['max_hp'],round(MONSTERS[c['monsters'][0]]['hp']*2.2))
            self.assertTrue(all(s in SKILLS for m in mobs for s in m['definition']['skills']))


if __name__=='__main__':unittest.main()
