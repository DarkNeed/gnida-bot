import json
import math
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from arena_encounters import create_encounter
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES
from arena_raid_engine import resolve_round
from arena_qte_live import challenge
from arena_qte_combined import combine, replay
from arena_action_queue import entries, intercept
import test_arena


def state(actors=(20,), roster=('goblin', 'goblin', 'shaman')):
    data = create_encounter([dict(actor_id=k, fighter_id=k, personal=True, slave_owner=k) for k in actors],
        [dict(slave_id=k, owner_id=k, class_id='ragamuffin', level=1) for k in actors],
        FIGHTER_CLASSES, BUILTIN_SKILLS, list(roster), 10)
    for p in data['players'].values():
        p.update(selected='defend')
        p['fighter']['hp'] = 10000
    return data


class QueueTests(unittest.TestCase):
    def test_fast_fighter_gets_one_follow_up_before_slow_enemy_cast(self):
        from arena_raid_engine import BOSS_SKILLS, create_raid_state
        participants=[dict(actor_id=20,fighter_id=20,personal=True,slave_owner=20)]
        sources=[dict(slave_id=20,owner_id=20,class_id='ragamuffin',level=1)]
        data=create_raid_state(participants,sources,FIGHTER_CLASSES,BUILTIN_SKILLS,'iron')
        player=data['players']['20']
        player.update(selected='bum_punch')
        player['fighter']['stats']['speed']=60
        data['boss']['stats']['speed']=0
        queue=entries(data,{**BUILTIN_SKILLS,**BOSS_SKILLS})
        player_entries=[entry for entry in queue if entry['team']=='players']
        enemy_time=min(entry['at'] for entry in queue if entry['team']=='enemies')
        self.assertEqual([entry['slot'] for entry in player_entries],[0,1])
        self.assertTrue(all(entry['at']<enemy_time for entry in player_entries))
        from test_arena_raids import Roll
        data['boss']['hp']=data['boss']['stats']['max_hp']=10000
        resolve_round(data,BUILTIN_SKILLS,Roll())
        self.assertEqual(player['manual_turns'],2)
        self.assertEqual(len([event for event in data['log'] if event['actor']=='20' and event.get('skill')]),2)

    def test_per_source_contacts_are_applied_not_replaced_with_full_hit(self):
        from test_arena_raids import Roll
        data=state()
        data['qte_modes']={'20':True}
        resolve_round(data,BUILTIN_SKILLS,Roll())
        pending=data['_queue_wait']
        pending['results']['20']={r['source']:dict(dodge=[True],pattern_dodge=dict(mask=[True],contacts=[])) for r in pending['released']}
        before=data['players']['20']['fighter']['hp']
        resolve_round(data,BUILTIN_SKILLS,Roll())
        self.assertEqual(data['players']['20']['fighter']['hp'],before)
        self.assertEqual(data['round'],2)

    def test_release_same_time_and_fast_kill_cancels_only_unfinished(self):
        data = state()
        data['qte_modes'] = {'20': True}
        p = data['players']['20']
        p.update(selected='bum_punch', selected_target='e1', qte_result=dict(attack=[True]))
        p['fighter']['stats']['speed'] = 150
        data['enemies']['e1']['stats']['evasion'] = 0
        data['enemies']['e1']['hp'] = 1
        from test_arena_raids import Roll
        resolve_round(data, BUILTIN_SKILLS, Roll())
        self.assertEqual(data['enemies']['e1']['hp'], 0)
        released = data['_queue_wait']['released']
        self.assertNotIn('e1', [r['source'] for r in released])
        self.assertEqual({r['source'] for r in released}, {'e2', 'e3'})
        self.assertEqual(data['round'], 1)

    def test_mass_attack_charged_once_and_one_tick(self):
        data = state((20, 30), ('goblin',))
        enemy = data['enemies']['e1']
        enemy['loadout'] = ['bum_punch']
        enemy.update(mob_id='custom', rp_sandbox=True, rp_ai='sequence')
        data['enemy_intents']['e1'].update(skill='bum_punch', targets=['20', '30'])
        before = enemy['resource']
        resolve_round(data, BUILTIN_SKILLS)
        hits = [e for e in data['log'] if e.get('skill') == 'bum_punch']
        self.assertEqual(len(hits), 2)
        self.assertEqual(enemy['resource'], min(enemy['stats']['resource_max'], before - BUILTIN_SKILLS['bum_punch'].cost + 8))
        self.assertEqual(enemy['own_turns'], 1)

    def test_interception_is_unique_single_target_reserved_and_reversible(self):
        from arena_rp import rp_skills
        data = state((20, 30))
        for p in data['players'].values(): p['selected'] = None
        skills = rp_skills(BUILTIN_SKILLS)
        data['enemy_intents']['e1']['targets'] = ['30']
        intercept(data, 20, 'e1', skills)
        self.assertEqual(data['enemy_intents']['e1']['targets'], ['20'])
        self.assertEqual(data['players']['20']['fighter']['resource'], 100)
        with self.assertRaises(ValueError): intercept(data, 20, 'e2', skills)
        intercept(data, 20, 'e1', skills)
        self.assertEqual(data['enemy_intents']['e1']['targets'], ['30'])
        data['enemy_intents']['e1']['targets'] = ['20', '30']
        with self.assertRaises(ValueError): intercept(data, 20, 'e1', skills)

    def test_combined_native_replay_matches_browser_both_modes(self):
        data = state()
        actor = data['players']['20']['fighter']
        for mode in ('dodge', 'block'):
            actor['defense_mode'] = mode
            members=[]
            for i, sid in enumerate(('bum_punch', 'mana_blob', 'warning_shot')):
                enemy=deepcopy(data['enemies']['e1'])
                enemy['loadout'].append(sid)
                m=challenge('defense',enemy,actor,BUILTIN_SKILLS[sid],20)
                m.update(encounter_enemy=f'e{i}',seed=17+i*997)
                members.append(m)
            stage=combine(members,20,actor['hp'])
            proof=dict(ticks=math.ceil(stage['duration']*120-1e-7),inputs=[dict(t=t,**(dict(angle=math.sin(t/40)*3,active=t%100<70) if mode=='block' else dict(x=math.sin(t/80),y=math.cos(t/95)))) for t in range(0,math.ceil(stage['duration']*120-1e-7),20)])
            result=replay(stage,proof,99)
            trace=json.loads(subprocess.check_output(['node','tests/qte_combined_trace.cjs'],input=json.dumps(dict(stage=stage,proof=proof)).encode(),cwd=Path(__file__).resolve().parents[1]))
            for source, r in result['sources'].items():
                self.assertEqual(len(r['pattern_dodge']['contacts']),len(trace[source]),(mode,source))
                for expected,actual in zip(r['pattern_dodge']['contacts'],trace[source]):
                    self.assertEqual({k:expected[k] for k in actual if k!='weight'}, {k:v for k,v in actual.items() if k!='weight'},(mode,source))
                    self.assertAlmostEqual(expected['weight'],actual['weight'],places=8)
            with self.assertRaises(ValueError):replay(stage,proof,.01)
            bad=deepcopy(proof);bad['inputs'][0]['t']=-1
            with self.assertRaises(ValueError):replay(stage,bad,99)
            aborted=replay(stage,dict(abort=True),0)
            self.assertEqual(set(aborted['sources']),{'e0','e1','e2'})


class QueueStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown = test_arena.ArenaStoreTests.asyncTearDown

    async def start(self):
        row=await self.db.arena_encounter_create(1,10,['goblin','goblin','shaman'])
        await self.db.arena_raid_set_message(row['token'],5)
        await self.db.arena_raid_setup(row['token'],20,'join')
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        data=json.loads(row['data_json']);data['players']['20']['fighter']['hp']=10000
        with self.db.connection:self.db._raid_save_locked(row,data)
        return row

    async def test_one_flow_sources_restart_repeated_submit_and_public_privacy(self):
        from arena_raid_web import raid_view
        row=await self.start()
        await self.db.arena_interactive_raid(row['token'],20,1,'defend')
        flow=self.db._qte_load_locked('raid',row['token'],20)
        self.assertEqual(flow['stages'][0]['version'],4)
        self.assertEqual(len(flow['stages'][0]['members']),3)
        ident=flow['stages'][0]['id']
        await self.db.close();await self.db.connect()
        view=await raid_view(self.db,await self.db.arena_raid_get(row['token']),20)
        self.assertNotIn('_queue_wait',view['data']);self.assertNotIn('_cast_queue',view['data'])
        with self.assertRaises(ValueError):await self.db.arena_interactive_raid(row['token'],20,1,'bum_punch')
        await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=ident)
        data=json.loads((await self.db.arena_raid_get(row['token']))['data_json'])
        self.assertEqual(data['round'],2)
        self.assertEqual(len([e for e in data['log'] if e.get('skill') and e['actor'].startswith('e')]),3)
        with self.assertRaises(ValueError):await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=ident)

    async def test_attack_is_immediate_one_stage_then_shared_defense(self):
        row=await self.start()
        await self.db.arena_interactive_raid(row['token'],20,1,'bum_punch',target='e2')
        flow=self.db._qte_load_locked('raid',row['token'],20)
        self.assertEqual(len(flow['stages']),1)
        self.assertEqual(flow['stages'][0]['kind'],'attack')
        await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=flow['stages'][0]['id'])
        flow=self.db._qte_load_locked('raid',row['token'],20)
        self.assertEqual(flow['stages'][0]['version'],4)

    async def test_completed_combined_guards_survive_database_handoff(self):
        row=await self.start()
        await self.db.arena_interactive_raid(row['token'],20,1,'defend')
        flow=self.db._qte_load_locked('raid',row['token'],20)
        result=dict(sources={m['encounter_enemy']:dict(dodge=[True]*m['strikes'],pattern_dodge=dict(mask=[True]*m['strikes'],contacts=[])) for m in flow['stages'][0]['members']})
        before=json.loads((await self.db.arena_raid_get(row['token']))['data_json'])['players']['20']['fighter']['hp']
        with patch('arena_qte_live.replay',return_value=result):
            await self.db.arena_interactive_raid(row['token'],20,1,proof={},challenge_id=flow['stages'][0]['id'])
        data=json.loads((await self.db.arena_raid_get(row['token']))['data_json'])
        self.assertEqual(data['players']['20']['fighter']['hp'],before)
        self.assertEqual(data['round'],2)
