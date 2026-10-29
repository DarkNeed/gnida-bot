from copy import deepcopy
import json
import subprocess
import unittest
import tempfile
from unittest.mock import AsyncMock
from pathlib import Path
from dataclasses import asdict

from arena_engine import BUILTIN_SKILLS,FIGHTER_CLASSES
from arena_raid_engine import create_raid_state,resolve_round,finish_if_needed
from arena_nazarick import ORDER,SKILLS,load_stage,set_intent,progress,summon,presentation,sprite,contact_afflictions
from arena_nazarick_patterns import shapes,block_threats
from arena_qte_patterns import profile,difficulty
from arena_qte_block import parameters

def encounter(size=3):
    ps=[dict(actor_id=i,fighter_id=i,personal=True,slave_owner=i)for i in(10,20,30)[:size]]
    ss=[dict(owner_id=p['actor_id'],slave_id=p['actor_id'],class_id='mage',level=20,
        loadout=['mana_shot','mana_focus'])for p in ps]
    return create_raid_state(ps,ss,FIGHTER_CLASSES,BUILTIN_SKILLS,'nazarick')

def choose(d):
    for p in d['players'].values():p['selected']='defend'
    return resolve_round(d,BUILTIN_SKILLS)

class GauntletTests(unittest.TestCase):
    def test_command_aliases(self):
        from handlers.raids import RAID_RE,raid_boss_id
        for command in('/рейд аинз','/рейд назарик','/raid ainz','/рейд@GnidoBot Айнз'):
            self.assertEqual(raid_boss_id(RAID_RE.fullmatch(command)),'nazarick')
    def test_order_and_burst_phase_barrier(self):
        d=encounter()
        for stage,who in enumerate(ORDER):
            self.assertEqual(d['nazarick']['stage'],stage)
            self.assertEqual(d['boss']['nz_owner'],who)
            self.assertEqual(d['nazarick']['phase'],1)
            d['boss']['hp']=0
            self.assertFalse(finish_if_needed(d))
            choose(d)
            self.assertEqual(d['nazarick']['phase'],2)
            self.assertEqual(d['boss']['hp'],round(d['boss']['stats']['max_hp']*.5))
            d['boss']['hp']=0
            choose(d)
            self.assertEqual(d['finished'],stage==4)
        self.assertTrue(d['won'])

    def test_full_restore_after_each_guardian_and_not_pandora(self):
        d=encounter()
        for stage in range(4):
            d['nazarick'].update(stage=stage,phase=2);load_stage(d)
            first=d['players']['10']['fighter'];dead=d['players']['20']['fighter']
            first.update(hp=1,resource=0,effects=[dict(id='bad',kind='bleed',value=3,duration=5)],cooldowns={'mana_shot':9},used_skills=['x'])
            dead['hp']=0
            d['players']['30']['withdrawn']=True
            d['boss']['hp']=0
            progress(d)
            f=d['players']['10']['fighter']
            if stage<3:
                self.assertEqual(f,d['nazarick']['initial_players']['10'])
                self.assertGreater(d['players']['20']['fighter']['hp'],0)
            else:self.assertEqual(f['hp'],1)
            self.assertTrue(d['players']['30']['withdrawn'])

    def test_phase_does_not_restore_players(self):
        d=encounter();d['boss']['hp']=1
        before=deepcopy(d['players']);progress(d)
        self.assertEqual(before,d['players'])

    def test_party_defeat_not_revived(self):
        d=encounter()
        for p in d['players'].values():p['fighter']['hp']=0
        d['boss']['hp']=0;progress(d)
        self.assertFalse(d['finished']);self.assertFalse(d['won'])
        self.assertEqual(set(d['nazarick']['blessing_offer']['eligible']),{'10','20','30'})
        self.assertTrue(all(p['fighter']['hp']==0 for p in d['players'].values()))

    def test_summons_cap_delay_and_new_intents(self):
        d=encounter();d['nazarick'].update(stage=4,phase=1);load_stage(d)
        d['round']+=2;summon(d);self.assertEqual(len(d['enemies']),3)
        self.assertEqual(set(d['enemy_intents']),{'boss'})
        set_intent(d);self.assertEqual(len(d['enemy_intents']),3)
        d['enemies']['boss_knight']['hp']=0
        summon(d);self.assertEqual(d['enemies']['boss_knight']['hp'],0)
        d['round']+=4;summon(d);self.assertGreater(d['enemies']['boss_knight']['hp'],0)
        self.assertEqual(len(d['enemies']),3)

    def test_no_unannounced_attack_on_transition(self):
        d=encounter();d['boss']['hp']=1
        before={k:p['fighter']['hp']for k,p in d['players'].items()}
        choose(d)
        self.assertEqual(before,{k:p['fighter']['hp']for k,p in d['players'].items()})

    def test_boss_bleeding_and_burn_tick_once_for_area_action(self):
        d=encounter();d['nazarick'].update(stage=1,phase=1);load_stage(d)
        d['round']=2;set_intent(d);d['boss']['hp']=1000
        d['boss']['effects']=[dict(id='test_bleed',kind='bleed',value=7,duration=2),dict(id='test_burn',kind='burn',value=3,duration=2)]
        choose(d)
        self.assertEqual(d['boss']['hp'],990)
        self.assertEqual(len([e for e in d['log']if e['text'].startswith('Кровотечение / горение')]),1)

    def test_all_stage_attacks_run_and_present(self):
        for stage in range(5):
            for phase in(1,2):
                d=encounter();d['nazarick'].update(stage=stage,phase=phase);load_stage(d)
                for p in d['players'].values():p['fighter']['hp']=p['fighter']['stats']['max_hp']=100000
                for _ in range(7):choose(d)
                self.assertFalse(d['finished'])
                self.assertTrue(presentation(d)['music'].startswith('nz_'))

    def test_assets_present(self):
        root=Path(__file__).resolve().parents[1]/'webapp'
        d=encounter()
        for stage in range(5):
            for phase in(1,2):
                d['nazarick'].update(stage=stage,phase=phase)
                self.assertTrue((root/presentation(d)['background'].replace('/static/','')).is_file())

class PatternParityTests(unittest.TestCase):
    def test_shared_shapes_and_block_scores_all_skills(self):
        fixtures=[]
        for sid,s in SKILLS.items():
            desc=dict(id=f'{sid}:{s.name}:1:{s.damage_type}',base_id=sid,name=s.name,class_id=s.class_id,
                strikes=1,damage_type=s.damage_type,description=s.description)
            p=profile(desc);d=difficulty(dict(accuracy=95,enemyEvasion=5,enemyAccuracy=100,evasion=0))
            for index in (0,1):
                fixtures.append(dict(p=p,d=d,player=dict(x=335,y=173),event=dict(index=index,jitter=.35),
                    params=parameters(p,dict(physicalDefense=20,magicDefense=15,enemyAttack=20,enemyAccuracy=100))))
        script="const N=require('./webapp/nazarick-qte.js'),E=require('./webapp/qte-unique/engine');let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(f=>({shapes:N.shapes(f,f.event),blocks:N.blockThreats(f.p,42,f.params,E.rng),family:E.family(f.p.skill)})))));"
        actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        def compare(a,b):
            if isinstance(a,(int,float)) and not isinstance(a,bool):self.assertAlmostEqual(a,b,places=8)
            elif isinstance(a,list):
                self.assertEqual(len(a),len(b))
                for v,w in zip(a,b):compare(v,w)
            elif isinstance(a,dict):
                self.assertEqual(set(a),set(b))
                for k,v in a.items():compare(v,b[k])
            else:self.assertEqual(a,b)
        for f,a in zip(fixtures,actual):
            with self.subTest(skill=f['p']['skill']['base_id']):
                compare(shapes(f,f['event']),a['shapes'])
                compare(block_threats(f['p'],42,f['params']),a['blocks'])
                self.assertEqual(f['p']['kind'],a['family'])

class RevisedMechanicsTests(unittest.TestCase):
    def test_density_gaze_shelter_timing_and_copy_mana_review_adjustments(self):
        from arena_qte_patterns import touches
        s=self.state('nz_shalltear_p2_0');hs=shapes(s,s['events'][0])
        self.assertEqual(sum(h['type']=='bullet' for h in hs),6)
        s=self.state('nz_shalltear_p1_2');s['player'].update(x=360,y=20)
        for h in shapes(s,s['events'][0]):
            h['start']=0
            self.assertTrue(touches(h,dict(x=360,y=20),dict(x=360,y=20,r=6),0,1/120))
        for sid in ('nz_demiurge_p1_2','nz_demiurge_p2_1','nz_ainz_p2_1'):
            s=self.state(sid);hs=shapes(s,s['events'][0]);safe=next(h for h in hs if h['type']=='safe_zone')
            travel=max(0,((safe['x']-s['player']['x'])**2+(safe['y']-s['player']['y'])**2)**.5-safe['r']+6)/s['d']['moveSpeed']
            self.assertGreater(s['d']['warning']+safe['delay'],travel+.45)
            self.assertEqual(len(s['events']),3)
            if sid=='nz_demiurge_p2_1':
                beam=next(h for h in hs if h['type']=='line')
                self.assertGreater(beam['delay'],safe['delay']+safe['duration']+.35)
        s=self.state('nz_pandora_p2_1')
        s['p']['skill']['copy_skill']=dict(base_id='mana_shot')
        hs=shapes(s,s['events'][0])
        self.assertTrue(all(h['x']<=0 or h['x']>=720 for h in hs))
        self.assertTrue(all((h['vx']**2+h['vy']**2)**.5<=s['d']['speed']*.51 for h in hs))

    def test_seven_stones_are_full_disjoint_color_stages_and_long_duration_replays(self):
        from arena_qte_patterns import prepare,duration
        from arena_qte_block import create
        s=self.state('nz_ainz_p1_0')
        self.assertEqual(len(s['events']),7)
        self.assertEqual(duration(dict(profile=s['p']['skill'],kind='defense',defense_preparation=1)),19.8)
        previous_end=0
        for e in s['events']:
            prepare(s,e);hs=[h for h in s['hazards'] if h['index']==e['index']]
            self.assertGreaterEqual(min(h['start'] for h in hs),previous_end)
            self.assertEqual(len({h['color'] for h in hs}),1)
            previous_end=max(h['end'] for h in hs)
        self.assertLess(previous_end,19.8)
        b=create(dict(profile=s['p']['skill'],seed=42,stats=dict(enemyAccuracy=100)))
        self.assertEqual(b['duration'],19.8)
        self.assertEqual({e['stone'] for e in b['events']},set(range(7)))

    def test_second_time_stop_and_fake_shelters_are_non_damaging_visuals(self):
        from arena_nazarick_patterns import time_stopped
        from arena_qte_patterns import prepare,replay
        s=self.state('nz_ainz_p2_0')
        self.assertEqual(len(s['events']),2)
        for t,expected in ((2,True),(4,False),(7,True),(9,False)):
            s['time']=t;self.assertEqual(time_stopped(s),expected)
        for e in s['events']:prepare(s,e)
        first=[h for h in s['hazards'] if h['cycle']==0]
        self.assertLess(max(h['end'] for h in first),6.7)
        s=self.state('nz_ainz_p2_1');prepare(s,s['events'][0])
        decoys=[h for h in s['hazards'] if h['type']=='decoy']
        self.assertEqual(len(decoys),2);self.assertTrue(all(h['disabled'] for h in decoys))
        safe=next(h for h in s['hazards'] if h['type']=='safe_zone')
        self.assertTrue(all(abs(h['x']-safe['x'])>150 for h in decoys))
        result=replay(dict(profile=s['p']['skill'],kind='defense',seed=42,defense_preparation=1,
            stats=dict(enemyAccuracy=100,evasion=0,accuracy=100,enemyEvasion=0)),dict(abort=True),30)
        self.assertEqual(len(result['contacts']),3)

    def test_new_shelter_patterns_have_clean_routes(self):
        from arena_qte_patterns import replay
        fixtures=[]
        for sid in ('nz_demiurge_p1_2','nz_demiurge_p2_1','nz_ainz_p2_1'):
            s=self.state(sid)
            fixtures.append(dict(profile=s['p']['skill'],kind='defense',seed=42,defense_preparation=1,
                stats=dict(enemyAccuracy=100,evasion=0,accuracy=100,enemyEvasion=0),policy='shelter'))
        traces=json.loads(subprocess.check_output(['node','tests/qte_patterns_trace.cjs'],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        for c,trace in zip(fixtures,traces):
            self.assertEqual(replay(c,trace['proof'],30),trace['result'])
            self.assertEqual(trace['result']['contacts'],[])

    def test_live_and_lab_renderers_support_every_phase_without_invalid_geometry(self):
        fixtures=[dict(id=sid,base_id=sid,name=s.name,class_id=s.class_id,strikes=1,damage_type=s.damage_type)
                  for sid,s in SKILLS.items() if s.damage_type]
        result=json.loads(subprocess.check_output(['node','tests/nazarick_render.cjs'],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        self.assertGreater(result['draws'],3000)
        client=(Path(__file__).resolve().parents[1]/'webapp/qte-unique/client').read_text(encoding='utf8')
        self.assertIn('if(window.QTEView){window.QTEView.draw(ctx,canvas,s);return;}',client)

    def state(self,sid):
        from arena_qte_patterns import defense
        skill=SKILLS[sid]
        p=profile(dict(id=sid,base_id=sid,name=skill.name,class_id='raid',strikes=1,damage_type=skill.damage_type))
        return defense(p,dict(enemyAccuracy=100,evasion=0,accuracy=100,enemyEvasion=0),42)

    def test_red_tracking_and_eye_beams_have_no_full_field_hitbox(self):
        s=self.state('nz_shalltear_p1_0');hs=shapes(s,s['events'][0])
        self.assertTrue(all(h['homing']>0 and h['color']=='#ff244c' for h in hs))
        s=self.state('nz_shalltear_p1_2');hs=shapes(s,s['events'][0])
        self.assertEqual(len(hs),2)
        self.assertTrue(all(h['type']=='line' and h['motif']=='eye' for h in hs))
        from arena_qte_patterns import touches
        for h in hs:
            h.update(start=0)
            self.assertFalse(touches(h,dict(x=40,y=270),dict(x=40,y=270,r=6),.1,1/120))

    def test_homing_expires_instead_of_chasing_forever(self):
        from arena_nazarick_patterns import advance_homing
        s=self.state('nz_shalltear_p1_1');h=shapes(s,s['events'][0])[0];h['start']=0
        for tick in range(200):advance_homing(h,dict(x=330,y=180),tick/120,1/120)
        velocity=(h['vx'],h['vy'])
        for tick in range(200,230):advance_homing(h,dict(x=40,y=280),tick/120,1/120)
        self.assertEqual(velocity,(h['vx'],h['vy']))

    def test_time_stop_locks_player_but_releases_before_blades(self):
        from arena_qte_patterns import defense_step,geometry
        s=self.state('nz_ainz_p2_0')
        for _ in range(200):defense_step(s,dict(x=1,y=0))
        frozen_x=s['player']['x']
        for _ in range(180):defense_step(s,dict(x=-1,y=0))
        self.assertEqual(frozen_x,s['player']['x'])
        self.assertEqual(s['contacts'],[])
        h=s['hazards'][0]
        self.assertEqual(geometry(h,3.5)['x'],h['x'])
        for _ in range(55):defense_step(s,dict(x=-1,y=0))
        self.assertLess(s['player']['x'],frozen_x)
        self.assertEqual(geometry(h,4.0)['x'],h['x'])
        self.assertNotEqual(geometry(h,4.3)['x'],h['x'])

    def test_safe_pentagram_is_safe_inside_and_jagged_bolt_collision_matches(self):
        from arena_qte_patterns import touches
        s=self.state('nz_demiurge_p1_2');h=shapes(s,s['events'][0])[0];h['start']=0
        self.assertEqual(h['type'],'safe_zone')
        p=dict(x=h['x'],y=h['y'],r=6)
        self.assertFalse(touches(h,p,p,.1,1/120))
        p=dict(x=700,y=300,r=6);self.assertTrue(touches(h,p,p,.1,1/120))
        s=self.state('nz_pandora_p1_0');h=shapes(s,s['events'][0])[0];h['start']=0
        self.assertEqual(h['type'],'polyline');self.assertEqual(len(h['points']),13)
        p=dict(x=h['points'][5][0],y=h['points'][5][1],r=6)
        self.assertTrue(touches(h,p,p,.1,1/120))

    def test_statuses_require_verified_contact_and_perfect_block_prevents_them(self):
        f=encounter(1)['players']['10']['fighter'];event=dict(hit=True,damage=3)
        guard=dict(pattern_dodge=dict(contacts=[]))
        self.assertEqual(contact_afflictions(f,'nz_demiurge_p2_0',event,guard),[])
        guard['pattern_dodge']['contacts']=[dict(status='burn',weight=0,reduction=1)]
        self.assertEqual(contact_afflictions(f,'nz_demiurge_p2_0',event,guard),[])
        guard['pattern_dodge']['contacts']=[dict(status='burn',weight=.2),dict(status='curse',weight=.2)]
        for _ in range(5):contact_afflictions(f,'nz_demiurge_p2_0',event,guard)
        effects=[e for e in f['effects'] if e['id'].startswith('nz_contact_')]
        self.assertEqual(len(effects),2)
        self.assertEqual({e['kind']:e['value'] for e in effects},{'burn':3,'damage_pct':-.12})

    def test_actual_raid_applies_fire_only_to_contacted_target(self):
        for touched in (False,True):
            with self.subTest(touched=touched):
                d=encounter(1);d['nazarick'].update(stage=1,phase=2);load_stage(d)
                p=d['players']['10'];p['fighter']['hp']=p['fighter']['stats']['max_hp']=10000
                p['qte_result']=dict(encounter_guards=dict(boss=dict(dodge=[not touched],pattern_dodge=dict(
                    contacts=[dict(id='fire',strike=0,weight=.3,tier='normal',status='burn')] if touched else []))))
                choose(d)
                self.assertEqual(any(e.get('id')=='nz_contact_burn' for e in p['fighter']['effects']),touched)

    def test_pandora_true_form_and_ainz_separate_frontal_sprite(self):
        self.assertTrue(sprite('pandora',1).endswith('/ainz.png'))
        self.assertTrue(sprite('pandora',2).endswith('/pandora.png'))
        self.assertTrue(sprite('ainz',1).endswith('/ainz_front.png'))
        self.assertTrue(sprite('ainz',2).endswith('/ainz_unbound.png'))
        d=encounter();d['nazarick'].update(stage=3,phase=2);load_stage(d)
        self.assertEqual(d['boss']['name'],'Актёр Пандоры')

    def test_copied_player_pattern_and_new_defenses_match_authoritative_replay(self):
        from arena_qte_patterns import replay
        fixtures=[]
        for sid in ('nz_shalltear_p1_0','nz_shalltear_p1_2','nz_pandora_p1_2','nz_ainz_p1_0','nz_ainz_p2_0','nz_pandora_p2_1'):
            s=self.state(sid)
            c=dict(profile=s['p']['skill'],kind='defense',seed=42,defense_preparation=1,
                stats=dict(enemyAccuracy=100,evasion=0,accuracy=100,enemyEvasion=0))
            if sid=='nz_pandora_p2_1':
                c['profile']['copy_skill']=dict(id='mana_shot',base_id='mana_shot',name='Мановый выстрел',class_id='mage',strikes=1,damage_type='magic')
            if sid in ('nz_shalltear_p1_2','nz_pandora_p1_2'):c['perfect']=True
            fixtures.append(c)
        result=json.loads(subprocess.check_output(['node','tests/qte_patterns_trace.cjs'],input=json.dumps(fixtures).encode(),cwd=Path(__file__).resolve().parents[1]))
        for c,trace in zip(fixtures,result):
            with self.subTest(skill=c['profile']['base_id']):
                self.assertEqual(replay(c,trace['proof'],30),trace['result'])
                if c.get('perfect'):self.assertEqual(trace['result']['contacts'],[])

class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from database import Database
        from arena_engine import fighter_xp_limit
        self.temp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.temp.name)/'test.sqlite3');await self.db.connect()
        await self.db.upsert_chat(1,'Тест')
        for actor in(10,20,30):
            await self.db.upsert_user(1,actor,str(actor),'Игрок '+str(actor))
            self.db._arena_profile_locked(1,actor,True)
            self.db._grant_profile_xp_locked('personal_profiles',1,actor,fighter_xp_limit())
            self.db.connection.execute("UPDATE personal_profiles SET class_id='mage',archclass_id='mage_archmage',archclass_stage=20,progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?",(json.dumps(['mana_shot','mana_focus']),actor))
        self.db.connection.commit()
        await self.db.arena_combat_settings(10,enabled=True,defense_mode='block')
        row=await self.db.arena_raid_create(1,10,boss_id='nazarick',silent=True)
        self.row=await self.db.arena_raid_setup(row['token'],10,'start')

    async def asyncTearDown(self):
        await self.db.close();self.temp.cleanup()

    async def test_public_view_redacts_reset_snapshots_and_decorates_summons(self):
        from arena_raid_web import raid_view
        d=json.loads(self.row['data_json']);d['nazarick'].update(stage=4,phase=1);load_stage(d)
        d['nazarick']['next_summon']=0;summon(d);set_intent(d)
        self.db._raid_save_locked(self.row,d);self.db.connection.commit()
        view=await raid_view(self.db,self.db._raid_row_locked(self.row['token']),10)
        self.assertNotIn('initial_players',view['data']['nazarick'])
        self.assertEqual(len(view['data']['enemies']),3)
        self.assertTrue(view['data']['enemies']['boss_knight']['class_avatar_url'].endswith('/knight.png'))
        self.assertEqual(view['data']['boss']['name'],'Аинз Оал Гоун — Король-колдун')

    async def test_long_staff_block_expiry_and_ephemeral_watcher_use_full_duration(self):
        import time
        from arena_qte_watch import Stream
        d=json.loads(self.row['data_json']);d['nazarick'].update(stage=4,phase=1);load_stage(d)
        self.db._raid_save_locked(self.row,d);self.db.connection.commit()
        await self.db.arena_interactive_raid(self.row['token'],10,d['round'],'defend',target='boss')
        flow=self.db._qte_load_locked('raid',self.row['token'],10);stage=flow['stages'][0]
        self.assertEqual(stage['profile']['base_id'],'nz_ainz_p1_0')
        self.assertAlmostEqual(stage['expires']-stage['started'],27.8,places=5)
        stage=deepcopy(stage);stage.update(started=time.time()-25,expires=time.time()+20)
        stream=Stream(stage,None)
        stream.accept(dict(type='data',id=stage['id'],tick=2376,inputs=[],ended=True))
        self.assertEqual(stream.tick,2376)

    async def test_qte_for_primary_and_summons_and_normal_skill_validation(self):
        d=json.loads(self.row['data_json']);d['nazarick'].update(stage=4,phase=1);load_stage(d)
        d['nazarick']['next_summon']=0;summon(d);set_intent(d)
        self.db._raid_save_locked(self.row,d);self.db.connection.commit()
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_raid(self.row['token'],10,d['round'],'nz_ainz_p2_1',target='boss')
        await self.db.arena_interactive_raid(self.row['token'],10,d['round'],'defend',target='boss_knight')
        flow=self.db._qte_load_locked('raid',self.row['token'],10)
        self.assertEqual(len(flow['stages']),3)
        self.assertTrue(all(s['defense_mode']=='block' for s in flow['stages']))
        self.assertEqual({s['encounter_enemy']for s in flow['stages']},{'boss','boss_knight','boss_lich'})

    async def test_guardian_transition_has_no_rewards_and_preserves_block_preference(self):
        d=json.loads(self.row['data_json']);d['nazarick']['phase']=2
        load_stage(d);d['boss']['hp']=0
        progress(d)
        self.db._raid_save_locked(self.row,d);self.db.connection.commit()
        self.assertFalse(d['finished']);self.assertEqual(d['rewards'],{})
        self.assertEqual(d['players']['10']['fighter']['defense_mode'],'block')
        self.assertEqual(self.db._raid_row_locked(self.row['token'])['status'],'active')

if __name__=='__main__':unittest.main()
