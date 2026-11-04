import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import subprocess
import tempfile
import unittest

from database import Database
from arena_nazarick_dungeon_rules import ROOMS, GUARDIANS, build_skills
from arena_engine import Skill,BUILTIN_SKILLS
from arena_raid_engine import resolve_round


class DungeonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'nz.sqlite';self.db=Database(self.path)
        await self.db.connect()
        for chat in(-100,-200):
            await self.db.upsert_chat(chat,'Тест')
            for actor in(10,20,30,40):await self.db.upsert_user(chat,actor,str(actor),f'Игрок {actor}')
        for actor in(10,20,30,40):
            self.db._arena_profile_locked(-100,actor,True)
            self.db.connection.execute("UPDATE personal_profiles SET class_id='mage',level=20,progression_level=20,progression_pending_level=0,loadout='[\"mana_shot\",\"mana_focus\"]' WHERE user_id=?",(actor,))
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close();self.folder.cleanup()

    async def create(self,checkpoint=0,party=False):
        with self.db.connection:
            for actor in(10,20,30):
                self.db._nzd_progress_locked(actor)
                self.db.connection.execute('UPDATE nazarick_progress SET checkpoint=? WHERE actor=?',(checkpoint,actor))
        run=await self.db.nazarick_create(-100,10)
        if party:
            for actor in(20,30):run=await self.db.nazarick_action(run['id'],actor,'join',run['revision'])
        return run

    async def start(self,run):return await self.db.nazarick_action(run['id'],10,'start',run['revision'])

    async def finish(self,run,won):
        with self.db.connection:
            raid=self.db._raid_row_locked(run['battle']);data=json.loads(raid['data_json']);data.update(finished=True,won=won)
            self.db._raid_finish_locked(raid,data)
        return await self.db.nazarick_get(run['id'],10)

    async def test_checkpoint_restart_retry_and_restore(self):
        run=await self.start(await self.create(3,True));token=run['battle']
        self.assertEqual(token,(await self.start(run))['battle'])
        run=await self.finish(run,True)
        self.assertEqual(run['checkpoint'],4);self.assertEqual(run['status'],'ready')
        await self.db.close();self.db=Database(self.path);await self.db.connect()
        run=await self.db.nazarick_get(run['id'],10);self.assertEqual(run['checkpoint'],4)
        run=await self.start(run);failed=await self.finish(run,False)
        self.assertEqual(failed['checkpoint'],4);self.assertTrue(failed['blessing_available'])
        again=await self.start(failed)
        raid=self.db._raid_row_locked(again['battle']);data=json.loads(raid['data_json'])
        self.assertTrue(all(p['fighter']['hp']==p['fighter']['stats']['max_hp'] for p in data['players'].values()))

    async def test_first_two_floors_have_valid_non_guardian_attacks(self):
        from arena_unified_store import catalog
        import arena_unified_queue as q
        for index, count in ((0,2),(1,3)):
            run=await self.start(await self.create(index))
            data=json.loads(self.db._raid_row_locked(run['battle'])['data_json'])
            skills=catalog(self.db)
            self.assertEqual(len(data['enemies']),count)
            self.assertTrue(all(not f.get('nzd_guardian') for f in data['enemies'].values()))
            self.assertTrue(all(sid in skills for f in data['enemies'].values() for sid in f['loadout']))
            for f in data['enemies'].values():
                self.assertTrue((Path(__file__).resolve().parents[1]/'webapp'/f['guild_sprite'].removeprefix('/static/')).is_file())
            from arena_raid_web import raid_view
            public=await raid_view(self.db,dict(self.db._raid_row_locked(run['battle'])),10)
            self.assertEqual(public['status'],'active')
            for p in data['players'].values():p['fighter']['hp']=p['fighter']['stats']['max_hp']=100000
            data['qte_modes']={}
            for _ in range(6):
                for key in q.ready(data):q.submit(data,key,'defend',next(iter(data['enemies'])),skills,ident=q.choice(data,key))
                q.advance(data,skills)
            used={e.get('skill') for e in data['log']}
            self.assertTrue({'nz_knight_p1_0','nz_lich_p1_0'} <= used)
            self.assertFalse(any('каст сорван' in e.get('text','').lower() for e in data['log']))
            run=await self.finish(run,True)
            self.assertEqual(run['checkpoint'],index+1)
            await self.db.nazarick_action(run['id'],10,'leave',run['revision'])

    async def test_guardian_attacks_and_two_phase_gate(self):
        for index in (3,4,5,7,9,10,11):
            run=await self.start(await self.create(index))
            raid=self.db._raid_row_locked(run['battle']);data=json.loads(raid['data_json'])
            for p in data['players'].values():p['fighter']['hp']=p['fighter']['stats']['max_hp']=100000
            for _ in range(3):
                import arena_unified_queue as q
                from arena_raid_engine import BOSS_SKILLS
                data['qte_modes']={}
                for key in q.ready(data):q.submit(data,key,'defend',next(iter(data['enemies'])),{**BOSS_SKILLS,**BUILTIN_SKILLS},ident=q.choice(data,key))
                q.advance(data,{**BOSS_SKILLS,**BUILTIN_SKILLS})
            self.assertTrue(any(e.get('skill','').startswith('nz_') for e in data['log']))
            self.assertFalse(any('стало недоступно' in e['text'] for e in data['log']))
            for f in data['enemies'].values():f['hp']=0
            from arena_encounters import finish
            self.assertFalse(finish(data));self.assertTrue(all(f['nzd_phase']==2 and f['hp']>0 for f in data['enemies'].values()))
            run=await self.finish(run,True)
            await self.db.nazarick_action(run['id'],10,'leave',run['revision'])

    async def test_final_rewards_guaranteed_atomic_and_fixed(self):
        run=await self.start(await self.create(len(ROOMS)-1,True));run=await self.finish(run,False)
        for actor in(10,20,30):run=await self.db.nazarick_action(run['id'],actor,'blessing',run['revision'])
        self.assertTrue(run['blessed']);run=await self.start(run);run=await self.finish(run,True)
        self.assertTrue(run['can_claim'])
        with self.assertRaises(ValueError):await self.db.nazarick_claim(run['id'],40,'nz_pandora_mask','nz_frost')
        with self.assertRaises(ValueError):await self.db.nazarick_claim(run['id'],10,'bogus','nz_frost')
        a=await self.db.nazarick_claim(run['id'],10,'nz_cocytus_oath','nz_frost')
        b=await self.db.nazarick_claim(run['id'],10,'nz_pandora_mask','nz_throne')
        self.assertEqual(a,b);self.assertTrue(a['ticket']);self.assertEqual(a['francs'],1000)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM gear_items WHERE actor=10').fetchone()[0],1)
        self.assertEqual(self.db._nzd_progress_locked(10)['checkpoint'],0)

    async def test_join_access_guard_and_ordinary_raid_no_rp(self):
        run=await self.create(4)
        self.db.connection.execute('UPDATE nazarick_progress SET checkpoint=0 WHERE actor=20');self.db.connection.commit()
        with self.assertRaises(ValueError):await self.db.nazarick_action(run['id'],20,'join',run['revision'])
        run=await self.start(run)
        with self.assertRaises(ValueError):await self.db.arena_raid_setup(run['battle'],10,'finish')
        with self.assertRaises(ValueError):await self.db.nazarick_get(run['id'],999)
        data=json.loads(self.db._raid_row_locked(run['battle'])['data_json'])
        self.assertFalse(data['rp_mode']);self.assertTrue(all(not p['fighter'].get('rp_sandbox') for p in data['players'].values()))

    async def test_treasury_not_extra_floor_and_floor10_checkpoints(self):
        run=await self.create(8);run=await self.db.nazarick_action(run['id'],10,'treasury',run['revision']);run=await self.finish(run,True)
        self.assertEqual(run['checkpoint'],8);self.assertEqual(run['treasury'],'cleared')
        run=await self.start(run);self.assertEqual(run['checkpoint'],9);self.assertEqual(run['status'],'ready')
        run=await self.start(run);run=await self.finish(run,True);self.assertEqual(run['checkpoint'],10)

    async def test_replacement_and_deserter_do_not_skip_or_respawn(self):
        run=await self.start(await self.create(3,True))
        with self.db.connection:
            raid=self.db._raid_row_locked(run['battle']);data=json.loads(raid['data_json'])
            data['players']['20']['withdrawn']=True;data.update(finished=True,won=True)
            self.db._raid_finish_locked(raid,data)
        run=await self.db.nazarick_get(run['id'],10)
        self.assertNotIn(20,[p['actor'] for p in run['members']]);self.assertEqual(self.db._nzd_progress_locked(20)['checkpoint'],3)
        with self.assertRaises(ValueError):await self.db.nazarick_action(run['id'],40,'join',run['revision'])
        with self.db.connection:
            self.db._nzd_progress_locked(40);self.db.connection.execute('UPDATE nazarick_progress SET checkpoint=4 WHERE actor=40')
        run=await self.db.nazarick_action(run['id'],40,'join',run['revision']);run=await self.start(run)
        data=json.loads(self.db._raid_row_locked(run['battle'])['data_json'])
        self.assertEqual(set(data['players']),{'10','30','40'})
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_inventory').fetchone()[0],0)

    async def test_claim_preserves_active_slot_and_cannot_craft_exclusives(self):
        run=await self.start(await self.create(len(ROOMS)-1));run=await self.finish(run,True)
        from arena_characters import CHARACTER_OWNER_ID
        await self.db.arena_grant_character_slots(10,CHARACTER_OWNER_ID)
        with self.db.connection:self.db._character_switch_locked(10,2)
        before=dict(self.db._arena_profile_locked(-100,10,True))
        await self.db.nazarick_claim(run['id'],10,'nz_twins_bond','nz_forest')
        self.assertEqual(self.db._character_active_locked(10),2)
        self.assertEqual(dict(self.db._arena_profile_locked(-100,10,True)),before)
        with self.assertRaises(ValueError):await self.db.gear_action(-100,10,dict(action='craft',key='nz_frost',rank='F',nonce='nazarick-only',revision=self.db._gear_revision_locked(10),character_slot=2))


class DungeonPatternTests(unittest.TestCase):
    def test_all_new_sprites_survive_browser_whitelist(self):
        import test_arena_market_client as client_tests
        from arena_nazarick_dungeon_rules import sprite
        runner=client_tests.ArenaMarketClientTests()
        for who in GUARDIANS:
            path=sprite(who)
            self.assertEqual(runner.run_client('out=sprite(input);',dict(sprite='ragamuffin',class_avatar_url=path)),path)
        self.assertEqual(runner.run_client('out=sprite(input);',dict(sprite='ragamuffin',class_avatar_url='/static/assets/nazarick-dungeon-v2/../bad.png')),'/static/assets/ragamuffin.png')

    def test_all_patterns_match_server(self):
        from arena_nazarick_patterns import shapes,block_threats
        from arena_qte_patterns import profile,difficulty
        from arena_qte_block import parameters
        fixtures=[]
        for sid,s in build_skills(Skill).items():
            desc=dict(id=sid+':'+s.name+':1:'+str(s.damage_type),base_id=sid,name=s.name,class_id=s.class_id,strikes=1,damage_type=s.damage_type,description=s.description)
            p=profile(desc)
            for i in(0,1):fixtures.append(dict(p=p,player=dict(x=335,y=173),d=difficulty(dict(accuracy=95,enemyEvasion=5,enemyAccuracy=100,evasion=0)),event=dict(index=i,jitter=.35),params=parameters(p,dict(physicalDefense=20,magicDefense=15,enemyAttack=20,enemyAccuracy=100))))
        script="const N=require('./webapp/nazarick-qte.js'),E=require('./webapp/qte-unique/engine');let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(f=>({shapes:N.shapes(f,f.event),blocks:N.blockThreats(f.p,42,f.params,E.rng)})))));"
        output=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        def compare(a,b):
            if isinstance(a,(float,int)) and not isinstance(a,bool):self.assertAlmostEqual(a,b,places=8)
            elif isinstance(a,list):
                self.assertEqual(len(a),len(b))
                for v,w in zip(a,b):compare(v,w)
            elif isinstance(a,dict):
                self.assertEqual(set(a),set(b))
                for k,v in a.items():compare(v,b[k])
            else:self.assertEqual(a,b)
        for f,o in zip(fixtures,output):
            with self.subTest(skill=f['p']['skill']['base_id']):compare(shapes(f,f['event']),o['shapes']);compare(block_threats(f['p'],42,f['params']),o['blocks'])
