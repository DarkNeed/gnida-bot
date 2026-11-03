import json
import unittest
from copy import deepcopy

import test_arena
from arena_engine import BUILTIN_SKILLS, FIGHTER_CLASSES, create_battle_state, stats_for
from arena_raid_engine import BOSS_SKILLS, create_raid_state
from arena_encounters import create_encounter
import arena_unified_queue as q

SKILLS = {**BOSS_SKILLS, **BUILTIN_SKILLS}


def direct(pvp=False, games=False):
    data = create_battle_state(dict(slave_id=10,owner_id=10,class_id='assassin',level=20),
        dict(slave_id=20 if pvp else 0,owner_id=20 if pvp else 0,class_id='mage',level=20),action_queue_version=True)
    data['qte_modes'] = {'10': games, '20': games}
    return data


def raid(boss='iron', actors=(10,), games=False):
    data = create_raid_state([dict(actor_id=k,fighter_id=k,personal=True,slave_owner=k) for k in actors],
        [dict(slave_id=k,owner_id=k,class_id='assassin',level=20) for k in actors],FIGHTER_CLASSES,BUILTIN_SKILLS,boss,unified=True)
    data['qte_modes'] = {str(k):games for k in actors}
    return data


def commit(data, key, skill='assassin_cut', target=None):
    if target is None:target = 'b' if 'sides' in data else 'boss'
    q.submit(data,key,skill,target,SKILLS,ident=q.choice(data,key))
    q.advance(data,SKILLS)


class CoreTests(unittest.TestCase):
    def test_every_skill_has_finite_positive_duration(self):
        import math
        from arena_skill_timing import duration
        data=direct()
        for skill in SKILLS.values():
            with self.subTest(skill=skill.skill_id):
                value=duration(data['sides']['a'],skill)
                self.assertTrue(math.isfinite(value))
                self.assertGreaterEqual(value,.75)

    def test_saved_pending_cast_survives_restart_without_automatic_repeat(self):
        data=direct(pvp=True)
        commit(data,'a')
        saved=json.dumps(data)
        data=json.loads(saved)
        q.initialize(data,SKILLS)
        self.assertEqual(len(q.clock(data)['pending']),1)
        commit(data,'b','mana_blob',target='a')
        self.assertEqual(data['sides']['a']['own_turns'],1)
        q.advance(data,SKILLS)
        self.assertEqual(data['sides']['a']['own_turns'],1)

    def test_equal_enemy_casts_share_native_defense_field(self):
        data=create_encounter([dict(actor_id=10,fighter_id=10,personal=True,slave_owner=10)],
            [dict(slave_id=10,owner_id=10,class_id='assassin',level=20)],FIGHTER_CLASSES,BUILTIN_SKILLS,['goblin','goblin'],30)
        data.update(unified_version=3,qte_modes={'10':True})
        data['players']['10']['fighter']['stats']['speed']=0
        q.initialize(data,SKILLS)
        for event in q.clock(data)['pending']:event['end']=.5
        commit(data,'10',target='e1')
        stages=q.stages(data,'10',SKILLS)
        self.assertEqual(len(stages),1)
        self.assertEqual(stages[0]['kind'],'defense')
        self.assertEqual({m['encounter_enemy'] for m in stages[0]['members']},{'e1','e2'})

    def test_all_player_classes_complete_native_casts_without_stalling(self):
        from arena_npc_ai import choose_skill
        for class_id in FIGHTER_CLASSES:
            with self.subTest(class_id=class_id):
                data=create_battle_state(dict(slave_id=10,owner_id=10,class_id=class_id,level=20),
                    dict(slave_id=0,owner_id=0,class_id='mage',level=20),action_queue_version=True)
                for f in data['sides'].values():f['hp']=f['stats']['max_hp']=10000
                for _ in range(10):
                    if data['finished']:break
                    sid=choose_skill(data,'a',SKILLS)
                    commit(data,'a',sid)
                    self.assertIn('a',q.ready(data))
                    self.assertGreater(q.clock(data)['time'],0)

    def test_short_actions_are_independent_and_do_not_auto_repeat(self):
        data = direct()
        commit(data,'a')
        self.assertEqual(q.ready(data),['a'])
        self.assertEqual(q.clock(data)['time'],.85)
        self.assertFalse(any(e['actor']=='a' for e in q.clock(data)['pending']))
        own = data['sides']['a']['own_turns']
        q.advance(data,SKILLS)
        self.assertEqual(data['sides']['a']['own_turns'],own)
        commit(data,'a','assassin_needle')
        self.assertEqual(data['sides']['a']['own_turns'],own+1)

    def test_multiple_enemy_actions_happen_during_one_long_cast(self):
        data = direct()
        data['sides']['a']['hp']=data['sides']['a']['stats']['max_hp']=1000
        data['sides']['b']['stats']['speed']=100
        data['sides']['a']['stats']['speed']=0
        data['sides']['a']['loadout'].append('assassin_execution')
        commit(data,'a','assassin_execution')
        self.assertGreaterEqual(data['sides']['b']['own_turns'],2)
        self.assertEqual(data['sides']['a']['own_turns'],1)

    def test_pvp_waits_for_both_choices_and_resolves_at_completion(self):
        data = direct(pvp=True,games=True)
        hp=data['sides']['b']['hp']
        commit(data,'a')
        self.assertEqual(q.clock(data)['time'],0)
        self.assertNotIn('_queue_wait',data)
        commit(data,'b','mana_blob',target='a')
        self.assertEqual(q.clock(data)['time'],.85)
        self.assertEqual(data['sides']['b']['hp'],hp)
        self.assertEqual(q.stages(data,'a',SKILLS)[0]['kind'],'attack')

    def test_every_scripted_boss_uses_same_clock_without_replacing_script(self):
        for boss in ('iron','lei_heng','doofenshmirtz','kit','whaler','chaplain','nazarick'):
            with self.subTest(boss=boss):
                data=raid(boss)
                for _ in range(3):commit(data,'10')
                self.assertEqual(data['players']['10']['manual_turns'],3)
                self.assertGreater(q.clock(data)['time'],0)
                self.assertFalse(any(e['actor']=='10' for e in q.clock(data)['pending']))

    def test_encounter_multiple_mobs_and_party_keep_independent_casts(self):
        data=create_encounter([dict(actor_id=k,fighter_id=k,personal=True,slave_owner=k) for k in (10,20)],
            [dict(slave_id=k,owner_id=k,class_id='assassin',level=20) for k in (10,20)],FIGHTER_CLASSES,BUILTIN_SKILLS,['goblin','shaman'],30)
        data['unified_version']=3
        data['qte_modes']={}
        data['players']['20']['fighter']['loadout'].append('assassin_execution')
        commit(data,'10',target='e1')
        self.assertEqual(q.clock(data)['time'],0)
        commit(data,'20','assassin_execution',target='e2')
        self.assertEqual(q.ready(data),['10'])
        self.assertTrue(any(e['actor']=='20' for e in q.clock(data)['pending']))

    def test_whaler_reacts_to_active_restoration_without_replaying_regular_cast(self):
        data=raid('whaler',games=True)
        f=data['players']['10']['fighter']
        f.update(class_id='nerd',archclass_id='',loadout=['go_to_store'],effects=[],resource=40)
        q.submit(data,'10','go_to_store','boss',SKILLS,ident=q.choice(data,'10'))
        q.advance(data,SKILLS)
        pending=data['_queue_wait']
        self.assertTrue(pending['released'][0]['reaction'])
        self.assertEqual(pending['released'][0]['intent']['skill'],'whaler_punishment')
        self.assertEqual(len([e for e in q.clock(data)['pending'] if e['actor']=='boss']),1)

    def test_nazarick_progress_survives_early_phase_kill(self):
        data=raid('nazarick')
        data['boss']['hp']=1
        commit(data,'10')
        self.assertTrue(data['nazarick']['phase']==2 or data['nazarick']['stage']>0)
        self.assertTrue(any(e['actor']=='boss' for e in q.clock(data)['pending']))

    def test_reservation_and_next_own_turn_regen_are_not_refunds(self):
        data=direct(pvp=True)
        commit(data,'a','assassin_needle')
        self.assertEqual(data['sides']['a']['resource'],86)
        self.assertEqual(data['sides']['a']['own_turns'],0)
        commit(data,'b','mana_blob',target='a')
        self.assertEqual(data['sides']['a']['resource'],94)
        self.assertEqual(data['sides']['a']['own_turns'],1)

    def test_legacy_battle_without_version_keeps_old_turns(self):
        from arena_engine import resolve_skill
        data=create_battle_state(dict(slave_id=10,owner_id=10,class_id='assassin',level=20),dict(slave_id=20,owner_id=20,class_id='mage',level=20))
        resolve_skill(data,'a','assassin_cut')
        self.assertEqual(data['active_side'],'b')
        self.assertFalse(q.enabled(data))

    def test_saved_legacy_raid_keeps_original_timing_and_single_action(self):
        from arena_action_queue import entries,cast_time
        data=raid('iron')
        data.pop('unified_version')
        f=data['players']['10']['fighter']
        f['stats']['speed']=60
        data['players']['10']['selected']='assassin_cut'
        planned=entries(data,SKILLS)
        self.assertEqual(len([e for e in planned if e['actor']=='10']),1)
        self.assertEqual(next(e['at'] for e in planned if e['actor']=='10'),cast_time(f,SKILLS['assassin_cut'],legacy=True))

    def test_long_scripted_fights_and_phase_boundaries_do_not_stall(self):
        from arena_npc_ai import choose_skill
        for boss in ('lei_heng','doofenshmirtz','kit','whaler','chaplain','nazarick'):
            with self.subTest(boss=boss):
                data=raid(boss)
                f=data['players']['10']['fighter']
                f['hp']=f['stats']['max_hp']=1000000
                for n in range(40):
                    if data['finished']:break
                    f=data['players']['10']['fighter']
                    f['hp']=f['stats']['max_hp']=1000000
                    if n in (3,10,20,30):data['boss']['hp']=max(1,round(data['boss']['stats']['max_hp']*.1))
                    target=next((k for k,v in q.roster(data).items() if k in q._enemy_ids(data) and v['hp']>0),'boss')
                    sid=choose_skill(q.pair(f,q.roster(data)[target]),'a',SKILLS)
                    commit(data,'10',sid,target=target)
                    if not data['finished'] and '10' not in q.ready(data):
                        self.assertTrue(data.get('nazarick',{}).get('blessing_offer'))
                        break

    def test_boss_stun_is_consumed_by_only_one_boss_action(self):
        data=raid('iron')
        f=data['players']['10']['fighter']
        f['hp']=f['stats']['max_hp']=10000
        f['stats']['speed']=0
        f['loadout'].append('assassin_execution')
        data['_queue_stunned']=True
        data['boss']['stats']['speed']=100
        commit(data,'10','assassin_execution')
        self.assertFalse(data.get('_queue_stunned'))
        self.assertEqual(sum('Босс ошеломлён' in e['text'] for e in data['log']),1)
        self.assertGreater(data['round'],2)
        self.assertGreater(data['boss']['own_turns'],1)

    def test_enemy_plague_has_one_tick_per_action(self):
        from arena_plague import infect
        data=raid('iron')
        f=data['players']['10']['fighter']
        f['hp']=f['stats']['max_hp']=10000
        f['stats']['speed']=0
        f['loadout'].append('assassin_smoke')
        data['boss']['stats']['speed']=100
        infect(data['boss'],fever=4,turns=3,spores=1,variant='trophy')
        commit(data,'10','assassin_smoke')
        boss_turns=data['boss']['own_turns']
        self.assertGreater(boss_turns,0)
        self.assertEqual(sum(e.get('damage',0) for e in data['log'] if e['actor']=='boss' and 'Чума:' in e['text']),6*boss_turns)


class StoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown=test_arena.ArenaStoreTests.asyncTearDown
    duel=test_arena.ArenaStoreTests.duel

    async def test_pvp_revision_hidden_proofs_and_replay_rejection(self):
        from arena_web import battle_view
        row=await self.duel()
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','bum_punch')
        self.assertIsNone(await self.db.arena_qte_view('battle',row['token'],10))
        revision=row['revision']
        row=await self.db.arena_interactive_action(row['token'],20,row['revision'],'skill','bum_punch')
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(row['token'],20,revision,'skill','bum_punch')
        current=None
        for _ in range(8):
            flow=self.db._qte_load_locked('battle',row['token'])
            if not flow:break
            stage=flow['stages'][0];current=stage
            other=20 if stage['actor']==10 else 10
            self.assertIsNone((await self.db.arena_qte_view('battle',row['token'],other))['challenge'])
            row=await self.db.arena_interactive_action(row['token'],stage['actor'],row['revision'],'qte',proof=dict(abort=True),challenge_id=stage['id'])
        self.assertIsNone(self.db._qte_load_locked('battle',row['token']))
        self.assertIsNotNone(current)
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(row['token'],current['actor'],row['revision'],'qte',proof=dict(abort=True),challenge_id=current['id'])
        public=await battle_view(self.db,row,10)
        self.assertNotIn('_unified',public['state'])
        self.assertNotIn('_queue_wait',public['state'])
        self.assertEqual(public['state']['action_queue']['version'],3)

    async def test_raid_choice_tickets_persist_and_cannot_be_reused(self):
        from arena_raid_web import raid_view
        row=await self.db.arena_raid_create(1,10,'lei_heng',silent=True)
        row=await self.db.arena_raid_setup(row['token'],10,'join')
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        state=json.loads(row['data_json'])
        state['players']['10']['fighter']['hp']=state['players']['10']['fighter']['stats']['max_hp']=10000
        self.db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?',(json.dumps(state),row['token']))
        self.db.connection.commit()
        row=await self.db.arena_raid_get(row['token'])
        public=await raid_view(self.db,row,10)
        ticket=public['data']['players']['10']['choice_id']
        self.assertNotIn('_unified',public['data'])
        n=public['data']['round']
        row=await self.db.arena_interactive_raid(row['token'],10,n,'bum_punch',choice_id=ticket)
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_raid(row['token'],10,n,'bum_punch',choice_id=ticket)
        for _ in range(8):
            flow=self.db._qte_load_locked('raid',row['token'],10)
            if not flow:break
            stage=flow['stages'][0]
            row=await self.db.arena_interactive_raid(row['token'],10,0,proof=dict(abort=True),challenge_id=stage['id'])
        data=json.loads(row['data_json'])
        self.assertFalse(any(e['actor']=='10' for e in q.clock(data)['pending']))
        public=await raid_view(self.db,row,10)
        self.assertNotEqual(ticket,public['data']['players']['10']['choice_id'])

    async def test_surrender_during_cast_finishes_only_once(self):
        row=await self.duel()
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','bum_punch')
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','surrender')
        self.assertEqual(row['status'],'finished')
        self.assertEqual(json.loads(row['state_json'])['winner'],'b')
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','surrender')

    async def test_expired_choice_cannot_be_submitted(self):
        import time
        row=await self.duel()
        self.db.connection.execute('UPDATE arena_battles SET deadline=? WHERE token=?',(int(time.time())-1,row['token']))
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'Время выбора истекло'):
            await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','bum_punch')

    async def test_pvp_independent_tickets_allow_concurrent_choices(self):
        from arena_web import battle_view
        row=await self.duel()
        a,b=[(await battle_view(self.db,row,actor))['state']['choice_id'] for actor in (10,20)]
        revision=row['revision']
        await self.db.arena_interactive_action(row['token'],10,revision,'skill','bum_punch',choice_id=a)
        row=await self.db.arena_interactive_action(row['token'],20,revision,'skill','bum_punch',choice_id=b)
        self.assertIsNotNone(self.db._qte_load_locked('battle',row['token']))
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_action(row['token'],10,revision,'skill','bum_punch',choice_id=a)

    async def test_ranked_both_inactive_timeouts_do_not_crash_or_grant_winner(self):
        from arena_unified_store import expire
        row=await self.duel()
        self.db.connection.execute('UPDATE arena_battles SET ranked=1 WHERE token=?',(row['token'],))
        self.db.connection.commit()
        for _ in range(3):
            row=self.db._arena_row_locked(row['token'])
            data=json.loads(row['state_json'])
            with self.db.connection:expire(self.db,'battle',row,data)
        row=self.db._arena_row_locked(row['token'])
        self.assertEqual(row['status'],'finished')
        self.assertIsNone(json.loads(row['state_json'])['winner'])

    async def test_timeout_during_pending_qte_never_submits_another_cast(self):
        from arena_unified_store import expire
        row=await self.duel()
        for actor in (10,20):
            row=await self.db.arena_interactive_action(row['token'],actor,row['revision'],'skill','bum_punch')
        flow=self.db._qte_load_locked('battle',row['token'])
        self.assertIsNotNone(flow)
        data=json.loads(row['state_json'])
        before=json.dumps(q.clock(data))
        with self.db.connection:expire(self.db,'battle',row,data)
        self.assertEqual(json.dumps(q.clock(data)),before)
        self.assertEqual(self.db._qte_load_locked('battle',row['token'])['stages'][0]['id'],flow['stages'][0]['id'])

    async def test_raid_victory_and_loot_are_settled_exactly_once(self):
        import random
        from unittest.mock import patch
        await self.db.arena_combat_settings(10,enabled=False)
        row=await self.db.arena_raid_create(1,10,'lei_heng',silent=True)
        row=await self.db.arena_raid_setup(row['token'],10,'start')
        data=json.loads(row['data_json'])
        data['boss']['hp']=1
        data['boss']['stats']['evasion']=0
        data['players']['10']['fighter']['stats']['speed']=100
        self.db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?',(json.dumps(data),row['token']))
        self.db.connection.commit()
        with patch('arena_unified_queue.random.SystemRandom',return_value=random.Random(1)):
            row=await self.db.arena_interactive_raid(row['token'],10,1,'bum_punch',choice_id=q.choice(data,'10'))
        self.assertEqual(row['status'],'finished')
        self.assertTrue(json.loads(row['data_json'])['won'])
        balance=await self.db.franc_balance(1,10)
        inventory=list(self.db.connection.execute('SELECT * FROM arena_inventory'))
        with self.assertRaises(ValueError):
            await self.db.arena_interactive_raid(row['token'],10,1,'bum_punch',choice_id=q.choice(data,'10'))
        self.assertEqual(await self.db.franc_balance(1,10),balance)
        self.assertEqual(list(self.db.connection.execute('SELECT * FROM arena_inventory')),inventory)


if __name__=='__main__':unittest.main()
