import json
import math
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import random
import shutil
import subprocess
import unittest

from arena_engine import BUILTIN_SKILLS,BUILTIN_PASSIVES,FIGHTER_CLASSES,create_battle_state,effective_skill,resolve_skill
from arena_raid_engine import BOSS_SKILLS,AVAILABLE_BOSSES,create_raid_state,pair_state
from arena_qte_live import challenge
from arena_qte_combined import combine,replay
import arena_mimic as m
import arena_unified_queue as q

CATALOG={**BOSS_SKILLS,**BUILTIN_SKILLS}


def state():
    data=create_raid_state([dict(actor_id=10,fighter_id=10,personal=True,slave_owner=10)],
        [dict(slave_id=10,owner_id=10,class_id='mage',level=20,
            loadout=['mana_shot','mana_overload','mana_focus','plagiarism'])],
        FIGHTER_CLASSES,BUILTIN_SKILLS,'mimic',unified=True)
    data['_cast_queue']=dict(time=0,round=1)
    return data,data['players']['10']['fighter'],data['boss']


def learn(data,player,boss,sid):
    skill=effective_skill(pair_state(player,boss),'a',sid,CATALOG)
    before=deepcopy(player),deepcopy(boss)
    m.observe(data,before,player,boss,skill,dict(hit=True,damage=10),sid)


class MimicTests(unittest.TestCase):
    def test_registry_command_and_three_phases(self):
        from handlers.raids import RAID_RE,raid_boss_id
        self.assertIn('mimic',AVAILABLE_BOSSES)
        self.assertEqual(raid_boss_id(RAID_RE.match('/рейд мимик')),'mimic')
        data,p,b=state();hp=b['stats']['max_hp']
        b['hp']=round(hp*.69);m.phase(data);self.assertEqual(data['phase'],2)
        b['hp']=round(hp*.34);m.phase(data);self.assertEqual(data['phase'],3)
        self.assertEqual(b['hp'],round(hp*.34),'phase change must not heal the boss')

    def test_miss_still_teaches_but_repeats_do_not_reset_cooldowns(self):
        data,p,b=state();p['loadout'].append('mana_shot')
        resolve_skill(pair_state(p,b),'a','mana_shot',CATALOG,random.Random(2),qte=dict(attack=[False]),raid_context=data)
        self.assertEqual(len(data['mimic']['attacks']),1)
        b['cooldowns']['mimic_echo_0']=3
        for _ in range(5):learn(data,p,b,'mana_shot')
        self.assertEqual(data['mimic']['attacks'][0]['seen'],3)
        self.assertEqual(b['cooldowns']['mimic_echo_0'],3)

    def test_raid_durability_scales_and_resistance_increases_without_healing(self):
        for size in (1,2,3):
            participants=[dict(actor_id=i,fighter_id=i,personal=True,slave_owner=i) for i in range(10,10+size)]
            sources=[dict(slave_id=i,owner_id=i,class_id='mage',level=20) for i in range(10,10+size)]
            data=create_raid_state(participants,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,'mimic',unified=True)
            b=data['boss'];self.assertEqual(b['hp'],1800+1000*(size-1))
            self.assertEqual(b['stats']['physical_defense'],24);self.assertEqual(b['resource'],220)
            for fraction,resistance in ((1,.9),(.69,.8),(.34,.7)):
                b['hp']=round(b['stats']['max_hp']*fraction);hp=b['hp'];m.phase(data);m.apply_passives(data)
                effects=[e for e in b['effects'] if e['id']=='mimic_resistance']
                self.assertEqual(len(effects),1);self.assertEqual(effects[0]['value'],resistance)
                self.assertEqual(b['hp'],hp)

    def test_first_phase_stitches_one_observed_attack_with_a_native_partner(self):
        data,p,b=state();learn(data,p,b,'mana_shot');b['own_turns']=1;m.set_intent(data)
        self.assertEqual(data['phase'],1);self.assertEqual(data['intent']['skill'],'mimic_stitch')
        casts=m.release(data,data['intent'],CATALOG);self.assertEqual(len(casts),2)
        self.assertTrue(any(c['intent']['copies'][0].get('native_skill') for c in casts))
        guards={'10':{c['source']:dict(dodge=[True],pattern_dodge=dict(contacts=[])) for c in casts}}
        hp=p['hp'];m.resolve_group(data,casts,guards,CATALOG,random.Random(4))
        self.assertEqual(p['hp'],hp);self.assertEqual(data['mimic']['stitched_count'],1)
        m.set_intent(data);self.assertNotEqual(data['intent']['skill'],'mimic_stitch')
        b['own_turns']=4;m.set_intent(data);self.assertEqual(data['intent']['skill'],'mimic_stitch')

    def test_copy_uses_source_offense_without_permanently_inflating_boss_stats(self):
        data,p,b=state();p['stats']['magic_attack']=80;learn(data,p,b,'mana_shot');m.set_intent(data)
        casts=m.release(data,data['intent'],CATALOG)
        self.assertGreaterEqual(casts[0]['fighter']['stats']['magic_attack'],76)
        copied=effective_skill(pair_state(casts[0]['fighter'],p),'a',casts[0]['intent']['skill'],CATALOG)
        self.assertGreater(copied.power,data['mimic']['attacks'][0]['skill']['power'])
        m.resolve_group(data,casts,{},CATALOG,random.Random(3))
        self.assertEqual(b['stats']['magic_attack'],32)

    def test_natural_fight_displays_stitching_before_second_phase(self):
        data,p,b=state();p['hp']=p['stats']['max_hp']=5000
        for _ in range(16):
            if data['mimic']['stitched_count']:break
            q.submit(data,'10','mana_shot','boss',CATALOG,ident=q.choice(data,'10'))
            q.advance(data,CATALOG,random.Random(5))
        self.assertGreater(data['mimic']['stitched_count'],0)
        self.assertEqual(data['phase'],1)

    def test_fifo_and_lock_preserve_only_one_dangerous_record(self):
        data,p,b=state()
        for sid in ('mana_shot','mana_overload','mana_focus'):learn(data,p,b,sid)
        strongest=max(data['mimic']['attacks'],key=lambda r:r['threat'])
        b['hp']=round(b['stats']['max_hp']*.34);m.phase(data)
        for sid in ('hunter_shot','light_word','bum_punch'):
            learn(data,p,b,sid)
        self.assertEqual(len(data['mimic']['attacks']),3)
        self.assertIn(strongest['uid'],[r['uid'] for r in data['mimic']['attacks']])
        json.dumps(data)

    def test_full_overload_is_flattened_once_not_recomputed_from_empty_boss_mana(self):
        data,p,b=state();p.update(archclass_id='mage_archmage',rpg_state=dict(mana=3,echo_ready=True))
        learn(data,p,b,'mana_overload');record=data['mimic']['attacks'][0]
        self.assertTrue(record['prepared']);self.assertGreater(record['skill']['power'],BUILTIN_SKILLS['mana_overload'].power*2)
        m.set_intent(data);casts=m.release(data,data['intent'],CATALOG)
        copied=effective_skill(pair_state(casts[0]['fighter'],p),'a',casts[0]['intent']['skill'],CATALOG)
        self.assertGreater(copied.power,BUILTIN_SKILLS['mana_overload'].power*2)
        self.assertEqual(copied.skill_id,'mimic_echo_0')
        guard={'10':{'boss':dict(dodge=[True],pattern_dodge=dict(contacts=[]))}}
        hp=p['hp'];m.resolve_group(data,casts,guard,CATALOG,random.Random(2))
        self.assertEqual(p['hp'],hp)
        self.assertEqual(data['mimic']['attacks'][0]['charges'],0)
        self.assertEqual(b.get('rpg_state',{}).get('mana',0),0)

    def test_declared_copy_is_immutable_when_its_slot_is_overwritten(self):
        data,p,b=state();learn(data,p,b,'mana_shot');m.set_intent(data);declared=deepcopy(data['intent'])
        for sid in ('mana_focus','hunter_shot','light_word'):learn(data,p,b,sid)
        cast=m.release(data,declared,CATALOG)[0]
        stage=challenge('defense',cast['fighter'],p,effective_skill(pair_state(cast['fighter'],p),'a',cast['intent']['skill'],CATALOG),10)
        self.assertEqual(stage['profile']['base_id'],'mana_shot')
        self.assertEqual(json.loads(json.dumps(declared))['copies'][0]['descriptor']['base_id'],'mana_shot')

    def test_passive_must_manifest_and_lives_three_own_actions(self):
        data,p,b=state();p['passive_details']=[asdict(BUILTIN_PASSIVES['battle_rhythm'])]
        before=deepcopy(p),deepcopy(b)
        skill=BUILTIN_SKILLS['mana_shot']
        m.observe(data,before,p,b,skill,dict(hit=False,damage=0),skill.skill_id)
        self.assertFalse(data['mimic']['passives'])
        m.observe(data,before,p,b,skill,dict(hit=True,damage=10),skill.skill_id)
        self.assertEqual(len(data['mimic']['passives']),1)
        self.assertEqual(p['passive_details'],[asdict(BUILTIN_PASSIVES['battle_rhythm'])])
        self.assertTrue(any(e['kind']=='damage_pct' for e in b['effects']))
        b['own_turns']=2;m.apply_passives(data);self.assertEqual(len(b['passive_details']),1)
        b['own_turns']=3;m.apply_passives(data);self.assertFalse(b['passive_details'])

    def test_healing_copy_uses_donor_hp_not_raid_boss_hp(self):
        data,p,b=state();heal=BUILTIN_SKILLS['priest_heal']
        copy=m.compile_copy(heal,p,b)
        self.assertIsNotNone(copy)
        effects=[e for e in copy['skill']['effects'] if e['kind']=='heal_pct']
        self.assertTrue(effects)
        expected=heal.effects[0]['value']*p['stats']['max_hp']
        self.assertAlmostEqual(effects[0]['value']*b['stats']['max_hp'],expected)
        self.assertIsNone(m.compile_copy(BUILTIN_SKILLS['last_amendment'],p,b))
        self.assertIsNone(m.compile_copy(BUILTIN_SKILLS['plagiarism'],p,b))

    def test_casino_copy_keeps_the_observed_result_not_another_roulette(self):
        data,p,b=state();skill=BUILTIN_SKILLS['casino_all_in']
        copy=m.compile_copy(skill,p,b)
        copy.update(strength=1,seen=1,slot=0,uid='1',charges=1)
        b['_mimic_skills']={'mimic_echo_0':copy}
        copied=effective_skill(pair_state(b,p),'a','mimic_echo_0',CATALOG)
        self.assertTrue(copy['prepared']);self.assertEqual(copied.power,copy['skill']['power'])
        stage=challenge('attack',b,p,copied,10)
        self.assertNotIn('casino_mode',stage)
        self.assertTrue(stage['profile']['mimic_outcome'])

    def test_stitched_cast_has_two_native_patterns_one_action_and_full_guard(self):
        data,p,b=state();learn(data,p,b,'mana_shot');learn(data,p,b,'hunter_shot')
        b.update(hp=int(b['stats']['max_hp']*.6),own_turns=2);m.set_intent(data)
        self.assertEqual(data['intent']['skill'],'mimic_stitch')
        casts=m.release(data,data['intent'],CATALOG);self.assertEqual(len(casts),2)
        guards={'10':{r['source']:dict(dodge=[True],pattern_dodge=dict(contacts=[])) for r in casts}}
        hp=p['hp'];resource=b['resource'];m.resolve_group(data,casts,guards,CATALOG,random.Random(3))
        self.assertEqual(p['hp'],hp);self.assertEqual(b['own_turns'],3)
        self.assertEqual(b['resource'],resource-sum(r['intent']['copies'][0]['skill']['cost'] for r in casts))

    def test_scroll_is_one_use_per_observation_and_keeps_its_equipped_id(self):
        battle=create_battle_state(dict(slave_id=10,owner_id=10,class_id='mage',level=20,loadout=['plagiarism']),
            dict(slave_id=20,owner_id=20,class_id='mage',level=20,loadout=['mana_shot']))
        a,b=battle['sides'].values()
        a['loadout']=['plagiarism'];b['loadout']=['mana_shot']
        resolve_skill(pair_state(b,a),'a','mana_shot',CATALOG,random.Random(2),qte=dict(attack=[True]))
        self.assertIn('plagiarism_memory',a)
        skill=effective_skill(pair_state(a,b),'a','plagiarism',CATALOG)
        self.assertEqual(skill.skill_id,'plagiarism');self.assertGreaterEqual(skill.cost,45)
        self.assertEqual(challenge('attack',a,b,skill,10)['profile']['base_id'],'mana_shot')
        resolve_skill(pair_state(a,b),'a','plagiarism',CATALOG,random.Random(3),qte=dict(attack=[True]))
        self.assertNotIn('plagiarism_memory',a)
        self.assertGreaterEqual(a['cooldowns']['plagiarism'],4)

    def test_shared_queue_runs_many_actions_without_replaying_or_stalling(self):
        data,p,b=state();p['hp']=p['stats']['max_hp']=5000
        for _ in range(24):
            if data['finished']:break
            q.submit(data,'10','mana_shot','boss',CATALOG,ident=q.choice(data,'10'))
            q.advance(data,CATALOG,random.Random(5))
            self.assertIn('10',q.ready(data))
        self.assertGreater(b['own_turns'],0)
        self.assertTrue(any(e.get('actor')=='boss' and e.get('damage',0)>0 for e in data['log']))

    def test_counter_is_applied_once_and_a_cancelled_copy_does_not_crash(self):
        from arena_raid_engine import native_attack
        data,p,b=state();m.set_intent(data)
        p['effects'].append(dict(id='counter',kind='rpg_counter',value=12,duration=3))
        casts=m.release(data,data['intent'],CATALOG)
        expected=deepcopy(b);defender=deepcopy(p)
        native_attack(expected,defender,casts[0]['intent']['skill'],CATALOG,random.Random(0),tick_actor_bleed=False)
        self.assertLess(expected['hp'],b['hp'])
        m.resolve_group(data,casts,{},CATALOG,random.Random(0))
        self.assertEqual(b['hp'],expected['hp'])
        self.assertEqual(p['hp'],defender['hp'])
        learn(data,p,b,'mana_shot');m.set_intent(data)
        casts=m.release(data,data['intent'],CATALOG)
        b['resource']=0
        m.resolve_group(data,casts,{},CATALOG,random.Random(0))
        self.assertTrue(any('каст сорван' in e.get('text','') for e in data['log']))

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_copied_shared_patterns_match_browser_in_both_defense_modes(self):
        data,p,b=state()
        for sid in ('mana_shot','hunter_shot'):learn(data,p,b,sid)
        b.update(hp=350,own_turns=2);m.set_intent(data)
        for mode in ('dodge','block'):
            p['defense_mode']=mode
            members=[]
            for i,cast in enumerate(m.release(data,data['intent'],CATALOG)):
                sk=effective_skill(pair_state(cast['fighter'],p),'a',cast['intent']['skill'],CATALOG)
                stage=challenge('defense',cast['fighter'],p,sk,10)
                stage.update(seed=99+i,encounter_enemy=cast['source']);members.append(stage)
                self.assertTrue(stage['profile']['mimic'])
            combined=combine(members,10,p['hp'])
            ticks=math.ceil(combined['duration']*120-1e-7)
            proof=dict(ticks=ticks,inputs=[dict(t=t,**(dict(active=t%90<65,angle=math.sin(t/40)*3)
                if mode=='block' else dict(target=[360+180*math.sin(t/80),160+110*math.cos(t/95)])))
                for t in range(0,ticks,20)])
            expected=replay(combined,proof,99)['sources']
            actual=json.loads(subprocess.check_output(['node','tests/qte_combined_trace.cjs'],
                input=json.dumps(dict(stage=combined,proof=proof)).encode(),cwd=Path(__file__).resolve().parents[1]))
            for source,result in expected.items():
                contacts=result['pattern_dodge']['contacts']
                self.assertEqual(len(contacts),len(actual[source]),mode)
                for a,c in zip(contacts,actual[source]):
                    self.assertEqual({k:v for k,v in a.items() if k!='weight'},
                                     {k:v for k,v in c.items() if k!='weight'},mode)
                    self.assertAlmostEqual(a['weight'],c['weight'],places=7)


class MimicStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_music_review_loads_assets_without_creating_a_battle(self):
        import re
        from aiohttp.test_utils import TestClient,TestServer
        from tools.preview_mimic import application
        app=await application();client=TestClient(TestServer(app));await client.start_server()
        try:
            response=await client.get('/mimic-music');self.assertEqual(response.status,200)
            html=await response.text();self.assertNotIn('__AUDIO_REV__',html)
            for key in ('mimic_stitched','mimic_original'):self.assertIn(key,html)
            self.assertNotIn('telegram-web-app',html)
            for url in re.findall(r'(?:src|href)="(/static/[^\"]+)"',html):
                self.assertEqual((await client.get(url)).status,200,url)
            self.assertEqual((await client.get('/static/assets/mimic_hall.png')).status,200)
            self.assertIsNone(app['mimic_review_db'].connection.execute('SELECT 1 FROM arena_raids LIMIT 1').fetchone())
            self.assertIn('/mimic-music',await (await client.get('/mimic-review')).text())
        finally:await client.close()

    async def test_memory_and_declaration_survive_database_reconnect_and_are_not_public_payloads(self):
        from aiohttp.test_utils import TestClient,TestServer
        from tools.preview_mimic import application
        from arena_raid_web import raid_view
        app=await application();client=TestClient(TestServer(app));await client.start_server()
        try:
            response=await client.get('/mimic-demo?mode=phase2&qte=0&sturdy=1')
            self.assertEqual(response.status,200)
            token=response.url.query['tgWebAppStartParam'][2:];db=app['mimic_review_db']
            row=await db.arena_raid_get(token);saved=json.loads(row['data_json'])
            self.assertEqual(saved['unified_version'],3)
            self.assertEqual(len(saved['mimic']['attacks']),2)
            await db.close();await db.connect()
            row=await db.arena_raid_get(token)
            self.assertEqual(json.loads(row['data_json'])['mimic'],saved['mimic'])
            public=(await raid_view(db,row,10))['data']
            self.assertEqual(len(public['mimic_view']['attacks']),2)
            self.assertNotIn('mimic',public)
            self.assertNotIn('_mimic_skills',public['boss'])
            self.assertNotIn('copies',public['intent'])
            self.assertEqual(json.loads((await db.arena_raid_get(token))['data_json'])['mimic'],saved['mimic'])
            row=await db.arena_raid_action(token,10,row['round'],'defend')
            self.assertGreater(json.loads(row['data_json'])['players']['10']['fighter']['own_turns'],0)
            from unittest.mock import patch
            data=json.loads(row['data_json']);data.update(finished=True,won=True)
            data['players']['10']['manual_turns']=2
            with patch('arena_raid.random.SystemRandom',return_value=random.Random(1)),db.connection:
                db._raid_finish_locked(row,data)
            self.assertEqual(data['rewards']['10']['loot'],'Плагиат')
            with self.assertRaises(ValueError):db._raid_finish_locked(row,data)
        finally:await client.close()


if __name__=='__main__':unittest.main()
