import asyncio
import math
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from arena_qte_watch import Stream, WatchHub, HUB_KEY
from arena_web import create_arena_app
import test_arena


class StreamTests(unittest.TestCase):
    def stage(self, **changes):
        return dict(id='stage', kind='defense', version=3, strikes=1,
                    started=time.time()-20, expires=time.time()+20, **changes)

    def test_sanitizes_buffers_and_accepts_final_packet_without_rate_delay(self):
        stream = Stream(self.stage(), None)
        data = stream.accept(dict(type='data', id='stage', tick=24,
            inputs=[dict(t=0, angle=1, active=True, unrelated='drop')]))
        self.assertNotIn('unrelated', data['inputs'][0])
        with self.assertRaises(ValueError):
            stream.accept(dict(type='data', id='stage', tick=25))
        stream.accept(dict(type='data', id='stage', tick=25, ended=True))
        self.assertTrue(stream.ended)
        self.assertGreater(stream.retire_at, time.monotonic())
        with self.assertRaises(ValueError):
            stream.accept(dict(type='data', id='stage', tick=26, ended=True))

    def test_rejects_malformed_future_duplicate_and_unbounded_data(self):
        invalid = [
            dict(tick=True), dict(tick=1141), dict(tick=-1),
            dict(tick=1, reset=1), dict(tick=1, clicks=[0]),
            dict(tick=1, inputs=[dict(t=0, angle=math.nan, active=True)]),
            dict(tick=1, inputs=[dict(t=0, angle=0, active=1)]),
            dict(tick=1, inputs=[dict(t=2, angle=0, active=True)]),
            dict(tick=2, inputs=[dict(t=1, angle=0, active=True)]*2),
            dict(tick=1140, inputs=[dict(t=0, angle=0, active=True)]*2001),
        ]
        for packet in invalid:
            with self.subTest(packet=str(packet)[:90]), self.assertRaises(ValueError):
                Stream(self.stage(), None).accept(dict(type='data', id='stage', **packet))
        stage=self.stage();stage['started']=time.time()
        with self.assertRaises(ValueError):
            Stream(stage,None).accept(dict(type='data',id='stage',tick=120))

    def test_dodge_target_and_attack_clicks(self):
        stage=self.stage();stage.update(version=2,kind='defense',defense_preparation=1)
        stream=Stream(stage,None)
        stream.accept(dict(type='data',id='stage',tick=5,inputs=[dict(t=0,target=[720,320])]))
        self.assertEqual(stream.packet()['inputs'],[dict(t=0,target=[720,320])])
        for target in ([721,0], [0,float('inf')], [0]):
            with self.assertRaises(ValueError):
                Stream(stage,None).accept(dict(type='data',id='stage',tick=5,inputs=[dict(t=0,target=target)]))
        from arena_qte_live import challenge
        from arena_engine import create_battle_state, BUILTIN_SKILLS
        state=create_battle_state(dict(owner_id=10,slave_id=10,class_id='ragamuffin',level=1),
                                 dict(owner_id=20,slave_id=20,class_id='ragamuffin',level=1))
        attack=challenge('attack',state['sides']['a'],state['sides']['b'],BUILTIN_SKILLS['bum_punch'],10)
        attack.update(started=time.time()-20,expires=time.time()+20)
        stream=Stream(attack,None)
        stream.accept(dict(type='data',id=attack['id'],tick=30,clicks=[30],ended=True))
        self.assertEqual(stream.clicks,[30])

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_browser_replay_matches_live_simulations(self):
        for name in ('qte_watch.cjs','qte_watch_follow.cjs'):
            with self.subTest(script=name):
                result=subprocess.run([shutil.which('node'),str(Path(__file__).with_name(name))],
                                      capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class WatchTests(unittest.IsolatedAsyncioTestCase):
    duel=test_arena.ArenaStoreTests.duel

    async def asyncSetUp(self):
        await test_arena.ArenaStoreTests.asyncSetUp(self)
        self.client=TestClient(TestServer(create_arena_app(self.db,self.bot,test_arena.TOKEN)))
        await self.client.start_server()
        self.hub=self.client.server.app[HUB_KEY]

    async def asyncTearDown(self):
        await self.client.close()
        await test_arena.ArenaStoreTests.asyncTearDown(self)

    def auth(self, actor):
        return test_arena.signed(actor,int(time.time()))

    async def stage(self):
        row=await self.duel()
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','bum_punch')
        stage=(await self.db.arena_qte_view('battle',row['token'],10))['challenge']
        return row,stage

    async def socket(self, row, role, user, scope='battle', **extra):
        ws=await self.client.ws_connect(f'/qte-stream/{scope}/{row["token"]}')
        await ws.send_json(dict(role=role,auth=self.auth(user),**extra))
        return ws

    async def packet(self, ws, kind):
        for _ in range(12):
            data=await ws.receive_json(timeout=3)
            if data['type']==kind:
                return data
            self.assertNotEqual(data['type'],'error',data)
        self.fail('No '+kind)

    async def test_metadata_privacy_and_live_deltas_without_combat_writes(self):
        row,stage=await self.stage()
        before=[tuple(r) for r in self.db.connection.execute('SELECT * FROM arena_qte_flows')]
        response=await self.client.get('/api/battle/'+row['token'],headers={'X-Telegram-Init-Data':self.auth(40)})
        self.assertEqual(response.status,200)
        data=await response.json()
        self.assertIsNone(data['qte']['challenge'])
        self.assertEqual([s['actor'] for s in data['qte_watch']],[10])
        self.assertNotIn('seed',data['qte_watch'][0])
        self.assertFalse(await self.db.arena_qte_watchables('battle',row['token'],10))
        source=await self.socket(row,'source',10,challenge=stage['id'])
        self.assertFalse((await self.packet(source,'demand'))['active'])
        watch=await self.socket(row,'watch',40,actor=10)
        self.assertEqual((await self.packet(watch,'begin'))['stage']['id'],stage['id'])
        await self.packet(watch,'data')
        self.assertTrue((await self.packet(source,'demand'))['active'])
        await source.send_json(dict(type='data',id=stage['id'],tick=0,reset=True,clicks=[],inputs=[]))
        self.assertEqual((await self.packet(watch,'data'))['tick'],0)
        late=await self.socket(row,'watch',50,actor=10)
        await self.packet(late,'begin')
        self.assertTrue((await self.packet(late,'data'))['reset'])
        self.assertTrue((await self.packet(source,'demand'))['active'])
        await source.send_json(dict(type='data',id=stage['id'],tick=0,ended=True,aborted=True))
        self.assertTrue((await self.packet(watch,'data'))['ended'])
        self.assertEqual((await self.db.arena_get(row['token']))['state_json'],row['state_json'])
        after=[tuple(r) for r in self.db.connection.execute('SELECT * FROM arena_qte_flows')]
        self.assertEqual(before,after)
        await source.close();await watch.close();await late.close()
        for _ in range(10):
            if not self.hub.rooms:break
            await asyncio.sleep(.01)
        self.assertEqual(self.hub.rooms,{},[(k,[(s.closed,p) for s,p in r['peers'].items()]) for k,r in self.hub.rooms.items()])
        self.assertFalse(self.hub.connections)

    async def test_last_viewer_closing_stops_demand(self):
        row,stage=await self.stage()
        watch=await self.socket(row,'watch',40,actor=10)
        await self.packet(watch,'waiting')
        source=await self.socket(row,'source',10,challenge=stage['id'])
        await self.packet(watch,'begin')
        self.assertTrue((await self.packet(source,'demand'))['active'])
        await watch.close()
        self.assertFalse((await self.packet(source,'demand'))['active'])
        await source.close()

    async def test_follow_waits_before_first_stage_and_follows_next_actor(self):
        row=await self.duel()
        watch=await self.socket(row,'watch',40,follow=True,actor=0)
        await self.packet(watch,'waiting')
        for actor in (10,20):
            row=await self.db.arena_interactive_action(row['token'],actor,row['revision'],'skill','bum_punch')
            stage=(await self.db.arena_qte_view('battle',row['token'],actor))['challenge']
            source=await self.socket(row,'source',actor,challenge=stage['id'])
            self.assertEqual((await self.packet(watch,'begin'))['stage']['actor'],actor)
            self.assertTrue((await self.packet(source,'demand'))['active'])
            await source.send_json(dict(type='data',id=stage['id'],tick=0,ended=True,aborted=True))
            self.assertTrue((await self.packet(watch,'data'))['reset'])
            await self.packet(watch,'waiting')
            await source.close()
            row=await self.db.arena_interactive_action(row['token'],actor,row['revision'],'qte',
                proof=dict(abort=True),challenge_id=stage['id'])
        self.assertFalse(watch.closed)
        await watch.close()

    async def test_follow_never_subscribes_to_own_stage_and_rejects_bad_mode(self):
        row=await self.duel()
        watch=await self.socket(row,'watch',10,follow=True)
        await self.packet(watch,'waiting')
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','bum_punch')
        stage=(await self.db.arena_qte_view('battle',row['token'],10))['challenge']
        source=await self.socket(row,'source',10,challenge=stage['id'])
        self.assertFalse((await self.packet(source,'demand'))['active'])
        self.assertEqual((await self.packet(watch,'available'))['stages'],[])
        room=self.hub.rooms[('battle',row['token'])]
        self.assertEqual([p['selected'] for p in room['peers'].values() if p['role']=='watch'],[0])
        bad=await self.socket(row,'watch',40,follow=1,actor=0)
        self.assertEqual((await bad.receive_json(timeout=3))['type'],'error')
        await bad.close();await watch.close();await source.close()

    async def test_rejects_forged_auth_wrong_actor_outsiders_and_viewer_controls(self):
        row,stage=await self.stage()
        for role,user,extra in [('source',20,dict(challenge=stage['id'])),
                                ('watch',40,dict(actor=20)),('watch',10,dict(actor=10))]:
            ws=await self.socket(row,role,user,**extra)
            self.assertEqual((await ws.receive_json(timeout=3))['type'],'error')
            await ws.close()
        ws=await self.client.ws_connect('/qte-stream/battle/'+row['token'])
        await ws.send_json(dict(role='watch',auth=self.auth(40)+'tampered',actor=10))
        self.assertEqual((await ws.receive_json(timeout=3))['type'],'error');await ws.close()
        self.bot.get_chat_member.return_value.status='left'
        ws=await self.socket(row,'watch',50,actor=10)
        self.assertEqual((await ws.receive_json(timeout=3))['type'],'error');await ws.close()
        self.bot.get_chat_member.return_value.status='member'
        ws=await self.socket(row,'watch',30,actor=10)
        await self.packet(ws,'waiting')
        await ws.send_json(dict(type='data',id=stage['id'],tick=0,ended=True))
        self.assertIn('Зритель',(await ws.receive_json(timeout=3))['message']);await ws.close()
        qte=await self.db.arena_qte_view('battle',row['token'],10)
        self.assertEqual(qte['challenge']['id'],stage['id'])

    async def test_raid_independent_sources_and_switching(self):
        row=await self.db.arena_raid_create(1,10)
        row=await self.db.arena_raid_setup(row['token'],20,'join')
        row=await self.db.arena_raid_setup(row['token'],10,'start',expected_revision=row['revision'])
        for actor in (10,20):
            row=await self.db.arena_interactive_raid(row['token'],actor,1,'bum_punch')
        stages={a:(await self.db.arena_qte_view('raid',row['token'],a))['challenge'] for a in (10,20)}
        self.assertEqual({s['actor'] for s in await self.db.arena_qte_watchables('raid',row['token'],40)},{10,20})
        sources={}
        for actor in (10,20):
            sources[actor]=await self.socket(row,'source',actor,scope='raid',challenge=stages[actor]['id'])
            self.assertFalse((await self.packet(sources[actor],'demand'))['active'])
        watch=await self.socket(row,'watch',40,scope='raid',actor=10)
        self.assertEqual((await self.packet(watch,'begin'))['stage']['actor'],10)
        await self.packet(watch,'data');await self.packet(sources[10],'demand')
        await watch.send_json(dict(type='select',actor=20))
        self.assertEqual((await self.packet(watch,'begin'))['stage']['actor'],20)
        self.assertFalse((await self.packet(sources[10],'demand'))['active'])
        self.assertTrue((await self.packet(sources[20],'demand'))['active'])
        auto=await self.socket(row,'watch',50,scope='raid',follow=True)
        self.assertEqual((await self.packet(auto,'begin'))['stage']['actor'],10)
        await sources[10].close()
        self.assertEqual((await self.packet(auto,'begin'))['stage']['actor'],20)
        self.assertFalse(auto.closed)
        await auto.close()
        await watch.close()
        for ws in sources.values():await ws.close()

    async def test_ephemeral_room_capacity_and_expiry(self):
        class Socket:
            closed=False
            async def send_json(self,data):pass
            async def close(self):self.closed=True
        hub=WatchHub();key=('battle','x');source=Socket();watch=Socket()
        room=hub.join(key,source,10,'source',10)
        hub.join(key,watch,20,'watch',10)
        stage=dict(id='old',expires=time.time()-1)
        room['streams'][10]=Stream(stage,source)
        with patch('arena_qte_watch.MAX_ROOMS',1):
            with self.assertRaises(ValueError):hub.join(('raid','y'),Socket(),30,'watch',10)
        with patch('arena_qte_watch.MAX_ROOM_CONNECTIONS',2):
            with self.assertRaises(ValueError):hub.join(key,Socket(),30,'watch',10)
        worker=asyncio.create_task(hub.prune())
        await asyncio.sleep(1.05)
        worker.cancel();await asyncio.gather(worker,return_exceptions=True)
        self.assertFalse(room['streams'])
        await hub.leave(key,source);await hub.leave(key,watch)
        self.assertFalse(hub.rooms)

    async def test_script_served_with_correct_type(self):
        response=await self.client.get('/static/qte-watch.js')
        self.assertEqual(response.status,200)
        self.assertIn('javascript',response.content_type)
        self.assertIn('ArenaQTEWatch',await response.text())
        index=await self.client.get('/')
        self.assertIn('/static/qte-watch.js?v=',await index.text())

    async def test_demo_mutes_only_spectator_document(self):
        from tools.preview_qte_watch import application
        demo=TestClient(TestServer(await application()))
        await demo.start_server()
        try:
            page=await demo.get('/watch-demo?mode=attack')
            html=await page.text()
            self.assertEqual(page.status,200)
            self.assertEqual(html.count('silent=1'),1)
            self.assertIn('&player=30&silent=1',html)
            self.assertIn('&player=10"></iframe>',html)
            player=await demo.get('/watch-client?player=10')
            watcher=await demo.get('/watch-client?player=20&silent=1')
            self.assertNotIn('data-audio-silent',await player.text())
            self.assertIn('<script data-audio-silent="true" src="/static/audio.js?v=',await watcher.text())
        finally:
            await demo.close()
