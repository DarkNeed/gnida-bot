"""Real scripted bosses use initiative and the same per-source defense flow."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES
from arena_raid_engine import create_raid_state, resolve_round, BOSS_SKILLS
from arena_action_queue import cast_time, public_queue
from test_arena_raids import Roll
import test_arena


def state(boss='iron', size=3):
    ids = (10, 20, 30)[:size]
    d = create_raid_state([dict(actor_id=k, fighter_id=k, personal=True, slave_owner=k) for k in ids],
        [dict(slave_id=k, owner_id=k, class_id='mage', level=20, loadout=['mana_shot', 'mana_focus']) for k in ids],
        FIGHTER_CLASSES, BUILTIN_SKILLS, boss)
    for p in d['players'].values():
        p['fighter'].update(hp=10000)
        p['fighter']['stats']['max_hp'] = 10000
        p['selected'] = 'defend'
    return d


def complete(d):
    pending = d['_queue_wait']
    for k in pending['eligible']:
        pending['results'][k] = {r['source']:dict(dodge=[True] * 6,
            pattern_dodge=dict(mask=[True] * 6, contacts=[])) for r in pending['released']}
    resolve_round(d, BUILTIN_SKILLS, Roll())


class BossQueueTests(unittest.TestCase):
    def test_control_after_boss_turn_interrupts_next_cast_not_lost_at_round_end(self):
        d=state('iron',1)
        d['players']['10']['selected']='mana_shot'
        d['players']['10']['fighter']['stats']['speed']=0
        d['boss']['stats']['speed']=150
        skills=dict(BUILTIN_SKILLS,mana_shot=replace(BUILTIN_SKILLS['mana_shot'],effects=(
            dict(id='queue_test_stun',kind='stun',value=1,turns=1,target='enemy',chance=1),)))
        resolve_round(d,skills,Roll())
        self.assertTrue(d['_pending_boss_stun'])
        d['players']['10']['selected']='defend'
        resolve_round(d,skills,Roll())
        self.assertTrue(any('Босс ошеломлён' in e['text'] and e['round']==2 for e in d['log']))
        self.assertNotIn('_pending_boss_stun',d)

    def test_nazarick_native_contact_statuses_use_per_source_combined_results(self):
        from arena_nazarick import load_stage
        for touched in (False,True):
            with self.subTest(touched=touched):
                d=state('nazarick',1)
                d['nazarick'].update(stage=1,phase=2)
                load_stage(d)
                d['qte_modes']={'10':True}
                resolve_round(d,BUILTIN_SKILLS,Roll())
                d['_queue_wait']['results']['10']={'boss':dict(dodge=[not touched],pattern_dodge=dict(
                    mask=[not touched],contacts=[dict(id='fire',strike=0,weight=.3,tier='normal',status='burn')] if touched else []))}
                resolve_round(d,BUILTIN_SKILLS,Roll())
                self.assertEqual(any(e.get('id')=='nz_contact_burn' for e in d['players']['10']['fighter']['effects']),touched)

    def test_boss_can_act_between_fast_and_slow_players_and_timeline_moves(self):
        d=state()
        for key, speed in (('10', 150), ('20', 0), ('30', 0)):
            p=d['players'][key]
            p['selected']='mana_shot'
            p['fighter']['stats']['speed']=speed
        d['boss']['stats']['speed']=40
        resolve_round(d, BUILTIN_SKILLS, Roll())
        order=[e['actor'] for e in d['log'] if e.get('skill')]
        self.assertEqual(order, ['10', 'boss', 'boss', 'boss', '20', '30'])
        times=[e['cast_at'] for e in d['log'] if e.get('skill')]
        self.assertEqual(times, sorted(times))
        self.assertEqual(d['round'], 2)
        self.assertEqual(len(public_queue(d, {**BOSS_SKILLS, **BUILTIN_SKILLS},10)['entries']),2)

    def test_all_scripted_bosses_resume_without_repeating_or_eating_later_attack_proofs(self):
        for boss in ('iron','lei_heng','doofenshmirtz','kit','whaler','chaplain','nazarick'):
            with self.subTest(boss=boss):
                d=state(boss)
                d['qte_modes']={str(k):True for k in (10,20,30)}
                for p in d['players'].values():
                    p.update(selected='mana_shot', qte_result=dict(attack=[True],pattern_attack=dict(mask=[True],contacts=[])))
                    p['fighter']['stats']['speed']=0
                d['boss']['stats']['speed']=150
                resolve_round(d,BUILTIN_SKILLS,Roll())
                self.assertIn('_queue_wait',d)
                self.assertEqual(d['players']['20']['qte_result']['attack'],[True])
                frozen=deepcopy(d)
                resolve_round(d,BUILTIN_SKILLS,Roll())
                self.assertEqual(d,frozen)
                # JSON round-trip exercises detached boss/enemies aliases too.
                d=json.loads(json.dumps(d))
                complete(d)
                self.assertEqual(d['round'],2)
                self.assertNotIn('_queue_wait',d)
                self.assertEqual([p['manual_turns'] for p in d['players'].values()],[1,1,1])
                self.assertTrue(all(p['fighter']['hp']==10000 for p in d['players'].values()))

    def test_nazarick_boss_and_summons_share_one_native_defense_and_phase_cancels_old_casts(self):
        from arena_nazarick import load_stage, summon, set_intent
        d=state('nazarick',1)
        d['nazarick'].update(stage=4,phase=1)
        load_stage(d)
        d['nazarick']['next_summon']=1
        summon(d)
        set_intent(d)
        d['qte_modes']={'10':True}
        # Synchronize native cast times without replacing any attack pattern.
        for key,f in d['enemies'].items():
            sid=d['enemy_intents'][key]['skill']
            f['stats']['speed']=0 if BOSS_SKILLS[sid].power<35 else 22
        times=[cast_time(d['enemies'][k],BOSS_SKILLS[i['skill']]) for k,i in d['enemy_intents'].items()]
        self.assertEqual(len(set(times)),1)
        resolve_round(d,BUILTIN_SKILLS,Roll())
        self.assertEqual({r['source'] for r in d['_queue_wait']['released']},{'boss','boss_knight','boss_lich'})
        before=d['players']['10']['fighter']['hp']
        complete(d)
        self.assertEqual(d['players']['10']['fighter']['hp'],before)
        self.assertEqual(d['round'],2)
        self.assertEqual(len({e['cast_at'] for e in d['log'] if e['actor'] in d['enemies'] and e.get('skill')}),1)
        d['boss']['hp']=1
        d['players']['10'].update(selected='mana_shot',selected_target='boss',qte_result=dict(attack=[True]))
        d['players']['10']['fighter']['stats']['speed']=999
        resolve_round(d,BUILTIN_SKILLS,Roll())
        self.assertEqual(d['nazarick']['phase'],2)
        self.assertNotIn('_queue_wait',d)

    def test_whaler_reaction_is_separate_and_does_not_replay_regular_cast_or_player(self):
        d=state('whaler',1)
        d['qte_modes']={'10':True}
        p=d['players']['10']
        p.update(selected='mana_focus')
        p['fighter']['resource']=30
        resolve_round(d,BUILTIN_SKILLS,Roll())
        complete(d)
        self.assertTrue(d['_queue_wait']['released'][0]['reaction'])
        self.assertEqual(p['manual_turns'],1)
        complete(d)
        self.assertEqual(d['round'],2)
        self.assertEqual(len([e for e in d['log'] if e.get('skill')=='mana_focus']),1)
        self.assertEqual(len([e for e in d['log'] if e.get('skill')=='whaler_harpoon']),1)
        self.assertEqual(len([e for e in d['log'] if e.get('skill')=='whaler_punishment']),1)

    def test_old_round_migrates_only_after_finishing_and_new_queue_does_not_wait_for_afk(self):
        d=state()
        d.pop('action_queue_version')
        resolve_round(d,BUILTIN_SKILLS,Roll())
        self.assertEqual(d['round'],2)
        self.assertEqual(d['action_queue_version'],1)
        d['qte_modes']={'10':True}
        for p in d['players'].values():p['selected']=None
        resolve_round(d,BUILTIN_SKILLS,Roll())
        self.assertEqual(d['round'],3)
        self.assertNotIn('_queue_wait',d)


class BossQueueStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown=test_arena.ArenaStoreTests.asyncTearDown

    async def test_two_defenders_resume_only_after_both_results(self):
        row=await self.db.arena_raid_create(1,20,'lei_heng',silent=True)
        await self.db.arena_raid_setup(row['token'],10,'join')
        row=await self.db.arena_raid_setup(row['token'],20,'start')
        d=json.loads(row['data_json'])
        for p in d['players'].values():p['fighter']['hp']=p['fighter']['stats']['max_hp']=10000
        self.db._raid_save_locked(row,d);self.db.connection.commit()
        await self.db.arena_interactive_raid(row['token'],10,1,'defend')
        await self.db.arena_interactive_raid(row['token'],20,1,'defend')
        first=self.db._qte_load_locked('raid',row['token'],10)['stages'][0]['id']
        second=self.db._qte_load_locked('raid',row['token'],20)['stages'][0]['id']
        row=await self.db.arena_interactive_raid(row['token'],10,1,proof=dict(abort=True),challenge_id=first)
        self.assertEqual(row['round'],1)
        self.assertEqual(self.db._qte_load_locked('raid',row['token'],20)['stages'][0]['id'],second)
        row=await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=second)
        d=json.loads(row['data_json'])
        self.assertEqual(row['round'],2)
        self.assertEqual([p['manual_turns'] for p in d['players'].values()],[1,1])
        self.assertEqual(len([e for e in d['log'] if e.get('skill')=='lei_explosive_slash']),2)

    async def test_attack_submission_then_boss_defense_restart_and_exactly_once_completion(self):
        from arena_raid_web import raid_view
        row=await self.db.arena_raid_create(1,20,'lei_heng',silent=True)
        row=await self.db.arena_raid_setup(row['token'],20,'start')
        d=json.loads(row['data_json'])
        d['players']['20']['fighter']['hp']=d['players']['20']['fighter']['stats']['max_hp']=10000
        self.db._raid_save_locked(row,d);self.db.connection.commit()
        await self.db.arena_interactive_raid(row['token'],20,1,'bum_punch')
        flow=self.db._qte_load_locked('raid',row['token'],20)
        self.assertEqual([s['kind'] for s in flow['stages']],['attack'])
        await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=flow['stages'][0]['id'])
        flow=self.db._qte_load_locked('raid',row['token'],20)
        self.assertEqual(flow['stages'][0]['version'],4)
        self.assertEqual(flow['stages'][0]['members'][0]['encounter_enemy'],'boss')
        ident=flow['stages'][0]['id']
        await self.db.close();await self.db.connect()
        view=await raid_view(self.db,await self.db.arena_raid_get(row['token']),20)
        self.assertNotIn('_queue_wait',view['data'])
        self.assertNotIn('_cast_queue',view['data'])
        row=await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=ident)
        self.assertEqual(json.loads(row['data_json'])['round'],2)
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_raid(row['token'],20,1,proof=dict(abort=True),challenge_id=ident)
