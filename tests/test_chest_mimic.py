"""Chest opening, persistent outcomes, native attacks and authoritative QTEs."""
from copy import deepcopy
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from database import Database
from arena_chest_mimic import SKILLS, PHASE_ONE, PHASE_TWO, prepare as phase
from arena_guild_rules import CONTRACTS, MONSTERS, RANKS, art, mob_templates
from arena_raid_engine import BOSS_SKILLS, finish_if_needed, pair_state
from arena_encounters import set_intents
from arena_engine import validate_skill, resolve_skill
from arena_qte_live import challenge
from arena_qte_patterns import defense, profile, prepare, geometry
from arena_qte_rules import replay
from arena_raid_web import raid_view

ROOT=Path(__file__).resolve().parents[1]


class ChestStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'chest.sqlite3');await self.db.connect()
        await self.db.upsert_chat(-100,'Данж')
        for actor in (10,20):
            await self.db.upsert_user(-100,actor,str(actor),'Охотник '+str(actor))
            self.db._arena_profile_locked(-100,actor,True)
            self.db.connection.execute("UPDATE personal_profiles SET class_id='warrior',level=20,progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?",(json.dumps(['bum_punch','armor_split']),actor))
            self.db._guild_hunter_locked(actor)
            self.db.connection.execute('UPDATE guild_hunters SET rank=6 WHERE actor_id=?',(actor,))
        self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close();self.tmp.cleanup()

    async def enter(self,roll=.25,party=False):
        run=await self.db.guild_create(-100,10,'c_dungeon','chest-test-request')
        if party:run=await self.db.guild_action(run['id'],20,'join',run['revision'])
        run=await self.db.guild_action(run['id'],10,'start',run['revision'])
        with self.db.connection:
            row=self.db._guild_row_locked(run['id'])
            node=next(n for n in row['data']['nodes'] if n['id']=='a1')
            node.update(kind='treasure',roll=roll)
            self.db._guild_save_locked(row)
        run=await self.db.guild_get(run['id'],10)
        for actor in ((10,20) if party else (10,)):
            run=await self.db.guild_action(run['id'],actor,'vote',run['revision'],choice='a1')
        return run

    async def open(self,run,party=False,choice='open'):
        for actor in ((10,20) if party else (10,)):
            run=await self.db.guild_action(run['id'],actor,'vote',run['revision'],choice=choice)
        return run

    async def victory(self,run):
        with self.db.connection:
            raid=self.db._raid_row_locked(run['battle']);data=json.loads(raid['data_json'])
            for enemy in data['enemies'].values():enemy['hp']=0
            self.assertTrue(finish_if_needed(data));self.db._raid_finish_locked(raid,data)
        return await self.db.guild_get(run['id'],10)

    async def test_opening_is_optional_and_boundary_half_is_normal(self):
        run=await self.enter(.5)
        self.assertEqual(run['pending']['event'],'chest');self.assertFalse(run['battle'])
        self.assertEqual(run['finds'],0)
        self.assertFalse(any('roll' in n for n in run['nodes']))
        run=await self.open(run)
        self.assertFalse(run['battle']);self.assertEqual(run['finds'],51)
        self.assertTrue(next(n for n in run['nodes'] if n['id']=='a1')['cleared'])
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='open')
        self.assertEqual((await self.db.guild_get(run['id'],10))['finds'],51)

    async def test_skip_has_no_treasure_equipment_or_material_reward(self):
        run=await self.open(await self.enter(),choice='leave')
        self.assertFalse(run['battle']);self.assertEqual(run['finds'],0)
        with self.db.connection:
            row=self.db._guild_row_locked(run['id'])
            self.db._guild_settle_locked(row,True,'Тест: возврат')
        run=await self.db.guild_get(run['id'],10)
        self.assertEqual(len(run['results']['10']['equipment_loot']),1)
        self.assertEqual(run['results']['10']['equipment_loot'][0]['materials'],3)

    async def test_saved_roll_party_vote_combat_and_one_reward(self):
        run=await self.enter(.499999,party=True)
        await self.db.close();await self.db.connect()
        run=await self.db.guild_get(run['id'],10)
        run=await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='open')
        self.assertFalse(run['battle'])
        run=await self.db.guild_action(run['id'],20,'vote',run['revision'],choice='open')
        token=run['battle'];self.assertTrue(token)
        raid=await self.db.arena_raid_get(token);battle=json.loads(raid['data_json'])
        enemy=battle['enemies']['e1']
        self.assertEqual(enemy['guild_monster'],'chest_mimic')
        self.assertFalse(enemy.get('is_mimic'));self.assertFalse(battle['rewards_enabled'])
        self.assertEqual(battle['unified_version'],3)
        self.assertTrue(all(p['fighter']['hp']==p['fighter']['stats']['max_hp'] for p in battle['players'].values()))
        view=await raid_view(self.db,raid,10)
        self.assertEqual(view['data']['enemies']['e1']['sprite_url'],art('chest_mimic'))
        from test_arena_market_client import ArenaMarketClientTests
        image=ArenaMarketClientTests().run_client('out=fighterImage(input.data.enemies.e1,"raid-sprite");',view)
        self.assertIn('src="'+art('chest_mimic')+'"',image)
        with self.assertRaises(ValueError):await self.db.guild_action(run['id'],10,'vote',run['revision'],choice='open')
        self.assertEqual(self.db.connection.execute("SELECT COUNT(*) FROM arena_raids WHERE status='active'").fetchone()[0],1)
        run=await self.victory(run)
        self.assertEqual(run['finds'],95)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM gear_loot').fetchone()[0],0)
        self.assertEqual(await self.db.franc_balance(-100,10),0)
        with self.db.connection:
            row=self.db._guild_row_locked(run['id']);self.db._guild_settle_locked(row,True,'Тест: возврат')
        run=await self.db.guild_get(run['id'],10)
        for actor in (10,20):
            rewards=run['results'][str(actor)]
            self.assertEqual([x['materials'] for x in rewards['equipment_loot']],[3,2])
            self.assertEqual(rewards['francs'],CONTRACTS['c_dungeon']['reward']+95)
        before=await self.db.franc_balance(-100,10)
        with self.db.connection:self.db._guild_settle_locked(self.db._guild_row_locked(run['id']),True,'Повтор')
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM gear_loot').fetchone()[0],4)

    async def test_phases_native_skills_mass_targets_no_canceled_old_cast(self):
        run=await self.open(await self.enter(party=True),party=True)
        data=json.loads((await self.db.arena_raid_get(run['battle']))['data_json'])
        enemy=data['enemies']['e1'];player=data['players']['10']['fighter']
        for index,sid in enumerate(PHASE_ONE):
            enemy['rp_ai_index']=index;set_intents(data,BOSS_SKILLS)
            self.assertEqual(data['enemy_intents']['e1']['skill'],sid)
            self.assertEqual(len(data['enemy_intents']['e1']['targets']),2 if sid.endswith('coins') else 1)
            pair=pair_state(deepcopy(enemy),deepcopy(player))
            self.assertEqual(validate_skill(pair,'a',sid,BOSS_SKILLS).skill_id,sid)
            event=resolve_skill(pair,'a',sid,skills=BOSS_SKILLS,rng=random.Random(3))
            self.assertGreater(event['damage'],0)
            if sid.endswith('tongue') or sid.endswith('devour'):
                kind='speed_pct' if sid.endswith('tongue') else 'physical_defense_pct'
                self.assertTrue(any(e['kind']==kind and e['value']==-.15 for e in pair['sides']['b']['effects']))
                guarded=pair_state(deepcopy(enemy),deepcopy(player))
                hp=guarded['sides']['b']['hp']
                event=resolve_skill(guarded,'a',sid,skills=BOSS_SKILLS,rng=random.Random(3),
                    qte=dict(dodge=[True],pattern_dodge=dict(mask=[True],contacts=[])))
                self.assertEqual(event['damage'],0);self.assertEqual(guarded['sides']['b']['hp'],hp)
                self.assertFalse(any(e['kind']==kind for e in guarded['sides']['b']['effects']))
        enemy['hp']=int(enemy['stats']['max_hp']*.35);hp=enemy['hp']
        phase(enemy)
        self.assertEqual(enemy['chest_phase'],2);self.assertEqual(enemy['hp'],hp)
        # Already-announced phase-one casts remain executable.
        validate_skill(pair_state(enemy,player),'a',PHASE_ONE[0],BOSS_SKILLS)
        for index,sid in enumerate(PHASE_TWO):
            enemy['rp_ai_index']=index;set_intents(data,BOSS_SKILLS)
            self.assertEqual(data['enemy_intents']['e1']['skill'],sid)
            validate_skill(pair_state(enemy,player),'a',sid,BOSS_SKILLS)
        enemy['hp']=enemy['stats']['max_hp'];phase(enemy)
        self.assertEqual(enemy['chest_phase'],2)


class ChestPatternsTests(unittest.TestCase):
    def configs(self,perfect=False):
        return [dict(version=2,kind='defense',profile=dict(id=s.skill_id+':'+s.name+':1:physical',base_id=s.skill_id,
            name=s.name,class_id=s.class_id,damage_type=s.damage_type,strikes=1,description=s.description,
            monster_pattern=3,npc_tier=tier),stats=dict(accuracy=95,enemyEvasion=0,enemyAccuracy=95,evasion=5),
            seed=23,defense_preparation=1,perfect=perfect) for tier in (0,4) for s in SKILLS.values()]

    def test_rank_not_hero_scaling_and_sprite(self):
        self.assertTrue((ROOT/'webapp'/art('chest_mimic').removeprefix('/static/')).is_file())
        for rank in RANKS:
            c=CONTRACTS[rank.lower()+'_dungeon'];node=dict(kind='treasure',ambush='chest_mimic')
            one=mob_templates(c,node,1)[0];three=mob_templates(c,node,3)[0]
            self.assertGreater(three['definition']['stats']['max_hp'],one['definition']['stats']['max_hp'])
            self.assertLess(one['definition']['stats']['max_hp'],MONSTERS[c['monsters'][-1]]['hp']*1.45)

    def test_distinct_shapes_and_real_return_jaws(self):
        for c in self.configs():
            s=defense(profile(c['profile']),c['stats'],23,preparation=1)
            prepare(s,s['events'][0]);hazards=s['hazards'];sid=c['profile']['base_id']
            self.assertTrue(hazards,sid);self.assertGreaterEqual(s['d']['warning'],.5)
            self.assertTrue(all(h.get('motif','').startswith('chest_') for h in hazards))
            if 'ravenous' in sid:self.assertGreater(len({h['type'] for h in hazards}),1)
            if 'coins' in sid:
                coin=next(h for h in hazards if h.get('returnAt'))
                a=geometry(coin,coin['start']+.4);b=geometry(coin,coin['start']+1.56)
                self.assertAlmostEqual(a['x'],b['x']);self.assertAlmostEqual(a['y'],b['y'])
                self.assertAlmostEqual(a['vx'],-b['vx'])
            if sid.endswith('bite'):
                jaw=next(h for h in hazards if h['type']=='line');at=jaw['start']
                self.assertNotEqual(geometry(jaw,at)['ay'],geometry(jaw,at+.2)['ay'])

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_browser_server_dodge_and_block_parity_and_safe_routes(self):
        configs=self.configs(perfect=True)
        proc=subprocess.run([shutil.which('node'),str(ROOT/'tests/qte_patterns_trace.cjs')],
                            input=json.dumps(configs),capture_output=True,text=True,encoding='utf-8',timeout=180)
        self.assertEqual(proc.returncode,0,proc.stderr)
        for c,trace in zip(configs,json.loads(proc.stdout),strict=True):
            self.assertFalse(trace['result']['contacts'],c['profile']['name'])
            self.assertEqual(replay(c,trace['proof'],30),trace['result'])
        from arena_qte_block import profile as block_profile, threats, parameters
        script="const E=require('./webapp/qte-unique/engine'),B=require('./webapp/qte-block/engine');let t='';process.stdin.on('data',x=>t+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(t).map(c=>{const p=E.profile(c.profile),params=B.parameters(p,c.stats);return E.guildBlockThreats(p,c.seed,params)}))));"
        proc=subprocess.run([shutil.which('node'),'-e',script],cwd=ROOT,input=json.dumps(configs),capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr)
        for c,events in zip(configs,json.loads(proc.stdout),strict=True):
            p=block_profile(c['profile']);expected=threats(p,c['seed'],parameters(p,c['stats']))
            self.assertEqual(len(events),len(expected))
            for a,b in zip(events,expected,strict=True):
                for k in a:
                    if isinstance(a[k],float):self.assertAlmostEqual(a[k],b[k])
                    else:self.assertEqual(a[k],b[k])


if __name__=='__main__':unittest.main()
