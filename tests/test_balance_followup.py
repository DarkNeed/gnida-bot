"""Prayer choice, charged mana and durable account-wide roulette retry guard."""
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch

from arena_engine import (BUILTIN_SKILLS,create_battle_state,effective_skill,resolve_skill,
                          validate_skill,unlocked_skill_ids)
from arena_rpg import prayer_actions
from arena_casino_chance import commit_account,roulette_reason,ROULETTE_NEW_BATTLE_SECONDS
from arena_casino import variant
from test_arena_epic import FixedRoll
import test_arena


def battle(cls='priest',branch='priest_bishop'):
    s=create_battle_state(dict(slave_id=10,owner_id=10,class_id=cls,level=20,
        archclass_id=branch,archclass_stage=20,progression_level=20),
        dict(slave_id=20,owner_id=20,class_id='warrior',level=20))
    s['active_side']='a'
    for f in s['sides'].values():
        f['hp']=10;f['stats'].update(max_hp=187,magic_defense=30,evasion=0)
        f['resource']=100;f['loadout']=['priest_heal','mana_overload']
    s['sides']['b']['hp']=s['sides']['b']['stats']['max_hp']=10000
    return s


class PrayerManaTests(unittest.TestCase):
    def cast(self,s,sid,**kw):
        return resolve_skill(s,'a',sid,rng=FixedRoll(.5),advance_turn=False,**kw)

    def test_single_member_raid_gets_solo_heal_and_mercy(self):
        s=battle();a=s['sides']['a'];a['rpg_state']={'faith':3}
        self.cast(s,'priest_heal',allies=[a],raid_context={})
        self.assertEqual(a['hp'],127) # 117 healed, not the old 47.
        self.assertEqual(a['resource'],40);self.assertEqual(a['rpg_state']['faith'],0)
        self.assertTrue(a['rpg_state']['dawn_used'])
        self.assertEqual(a['cooldowns']['priest_heal_regular'],4)

    def test_regular_choice_preserves_faith_once_flag_and_shared_cooldown(self):
        for ready,healed in ((False,70),(True,94)):
            s=battle();a=s['sides']['a'];a['rpg_state']={'faith':3,'prayer_ready':ready}
            self.assertEqual(prayer_actions(a),['priest_heal_regular'])
            before=deepcopy(a['loadout']);self.cast(s,'priest_heal_regular',allies=[a])
            self.assertEqual(a['hp'],10+healed);self.assertEqual(a['resource'],75)
            self.assertEqual(a['rpg_state']['faith'],3);self.assertFalse(a['rpg_state'].get('dawn_used'))
            self.assertEqual(a['loadout'],before)
            self.assertEqual(a['cooldowns']['priest_heal'],3)
            with self.assertRaisesRegex(ValueError,'восстанавливается'):validate_skill(s,'a','priest_heal')
            with self.assertRaisesRegex(ValueError,'восстанавливается'):validate_skill(s,'a','priest_heal_regular')

    def test_choice_is_not_a_learned_slot_or_free_foreign_final(self):
        self.assertNotIn('priest_heal_regular',unlocked_skill_ids('priest',20,archclass_id='priest_bishop',progression_level=20))
        for fields in (dict(level=19),dict(archclass_stage=10),dict(archclass_id='priest_paladin'),dict(loadout=[])):
            s=battle();a=s['sides']['a'];a['rpg_state']={'faith':3};a.update(fields)
            self.assertEqual(prayer_actions(a),[])
            with self.assertRaises(ValueError):validate_skill(s,'a','priest_heal_regular')

    def test_party_healing_and_revive_keep_their_distinct_roles(self):
        s=battle();a=s['sides']['a'];a['rpg_state']={'faith':3};friend=deepcopy(a)
        self.cast(s,'priest_heal',allies=[a,friend],raid_context={})
        self.assertEqual((a['hp'],friend['hp']),(68,68)) # 25% * Mercy, each.
        s=battle();a=s['sides']['a'];a['rpg_state']={'faith':3};friend=deepcopy(a);friend['hp']=0;context={}
        self.cast(s,'priest_heal',allies=[a,friend],raid_context=context)
        self.assertEqual(friend['hp'],56);self.assertTrue(context['rpg_revive_used'])

    def test_full_overload_only_gets_the_extra_multiplier_at_three_charges(self):
        from arena_rpg import rpg_modifiers
        for cls,branch in (('mage','mage_archmage'),('mage','mage_elementalist'),('mage','')):
            s=battle(cls,branch);a,b=s['sides'].values();skill=BUILTIN_SKILLS['mana_overload']
            for charges in range(4):
                a['rpg_state']={'mana':charges};expected=1+.35*charges
                if charges==3:expected*=1.5
                self.assertAlmostEqual(rpg_modifiers(a,b,skill)[1],expected)
            a['rpg_state']={'mana':3,'echo_ready':True};a['loadout']=['mana_overload']
            before=effective_skill(s,'a','mana_overload')
            e=self.cast(s,'mana_overload',qte=dict(attack=[True],luck_evasion=False))
            self.assertGreater(e['damage'],100 if branch=='mage_archmage' else 60)
            self.assertEqual(a['rpg_state']['mana'],0);self.assertEqual(a['resource'],100-before.cost)

    def test_full_overload_miss_preserves_preparation_but_pays_cost(self):
        s=battle('mage','mage_archmage');a=s['sides']['a'];a['rpg_state']={'mana':3,'echo_ready':True}
        self.cast(s,'mana_overload',qte=dict(attack=[False]))
        self.assertEqual(a['rpg_state']['mana'],3);self.assertTrue(a['rpg_state']['echo_ready'])
        self.assertEqual(a['resource'],70)

    def test_777_remains_specific_to_lucky_branch(self):
        for key,expected in (('',False),('casino_hustler',False),('casino_lucky',True)):
            a=battle('gambler',key)['sides']['a'];a['casino_state']={'chips':7,'sevens':3}
            self.assertEqual(variant(BUILTIN_SKILLS['casino_deposit'],a).name.startswith('777'),expected)


class RouletteRetryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown=test_arena.ArenaStoreTests.asyncTearDown

    async def first_stage(self):
        self.db._arena_profile_locked(1,10,True)
        self.db.connection.execute("UPDATE personal_profiles SET class_id='gambler',level=20,progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=10",
            (json.dumps(['casino_bet','casino_ace','casino_all_in','casino_credit']),));self.db.connection.commit()
        row=await self.db.arena_raid_create(1,10,'lei_heng',silent=True)
        row=await self.db.arena_raid_setup(row['token'],10,'start',expected_revision=row['revision'])
        row=await self.db.arena_interactive_raid(row['token'],10,1,'casino_all_in')
        return row,(await self.db.arena_qte_view('raid',row['token'],10))['challenge']

    async def test_new_battle_retry_blocked_reload_stable_and_other_skills_work(self):
        row,stage=await self.first_stage();token=row['token']
        outcome=await self.db.arena_qte_casino_roll('raid',token,10,stage['id'],'green')
        until=self.db.connection.execute('SELECT until_at FROM arena_roulette_windows WHERE actor_id=10').fetchone()[0]
        self.assertEqual(await self.db.arena_qte_casino_roll('raid',token,10,stage['id'],'green'),outcome)
        self.assertEqual(self.db.connection.execute('SELECT until_at FROM arena_roulette_windows WHERE actor_id=10').fetchone()[0],until)
        await self.db.arena_interactive_raid(token,10,1,'surrender')
        new=await self.db.arena_raid_create(1,10,'lei_heng',silent=True)
        new=await self.db.arena_raid_setup(new['token'],10,'start',expected_revision=new['revision'])
        with self.assertRaisesRegex(ValueError,'Новый стол'):await self.db.arena_interactive_raid(new['token'],10,1,'casino_all_in')
        with self.assertRaisesRegex(ValueError,'Новый стол'):await self.db.arena_raid_action(new['token'],10,1,'casino_all_in')
        self.assertIsNone(self.db._qte_load_locked('raid',new['token'],10))
        await self.db.arena_interactive_raid(new['token'],10,1,'casino_bet')
        self.assertIsNotNone(self.db._qte_load_locked('raid',new['token'],10))
        await self.db.close();await self.db.connect()
        self.assertTrue(roulette_reason(self.db,'battle','different-chat-or-character',10))
        self.assertFalse(roulette_reason(self.db,'raid',token,10))
        self.assertFalse(roulette_reason(self.db,'raid','another',20))
        self.assertFalse(roulette_reason(self.db,'raid','another',10,now=until+.01))

    async def test_window_and_flow_roll_back_together_on_save_failure(self):
        row,stage=await self.first_stage()
        with patch.object(self.db,'_qte_save_locked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):await self.db.arena_qte_casino_roll('raid',row['token'],10,stage['id'],'green')
        self.assertFalse(roulette_reason(self.db,'raid','other',10))
        self.assertFalse(self.db._qte_load_locked('raid',row['token'],10)['stages'][0].get('casino_result'))

    async def test_same_table_and_rp_dont_create_new_battle_penalties(self):
        with self.db.connection:
            first=dict(casino_mode='roulette');commit_account(self.db,'raid','one',10,first,'red',now=100)
            second=dict(casino_mode='roulette');commit_account(self.db,'raid','one',10,second,'black',now=110)
            self.assertTrue(roulette_reason(self.db,'raid','two',10,now=111))
            self.assertFalse(roulette_reason(self.db,'raid','two',10,now=110+ROULETTE_NEW_BATTLE_SECONDS))
            rp=dict(casino_mode='roulette',casino_retry_exempt=True)
            commit_account(self.db,'raid','rp',10,rp,'green',now=120)
            self.assertFalse(roulette_reason(self.db,'raid','one',10,now=121))

    async def test_raid_view_exposes_both_prayers_without_equipping_an_extra_slot(self):
        from arena_raid_web import raid_view
        self.db._arena_profile_locked(1,10,True)
        self.db.connection.execute("UPDATE personal_profiles SET class_id='priest',level=20,archclass_id='priest_bishop',archclass_stage=20,progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=10",(json.dumps(['priest_heal']),));self.db.connection.commit()
        row=await self.db.arena_raid_create(1,10,'lei_heng',silent=True)
        row=await self.db.arena_raid_setup(row['token'],10,'start',expected_revision=row['revision'])
        data=json.loads(row['data_json']);data['players']['10']['fighter']['rpg_state']={'faith':3}
        with self.db.connection:self.db._raid_save_locked(row,data)
        view=await raid_view(self.db,await self.db.arena_raid_get(row['token']),10)
        hero=view['data']['players']['10']['fighter'];details={s['skill_id']:s for s in hero['skill_details']}
        self.assertEqual(details['priest_heal']['name'],'Пока горит свет')
        self.assertEqual(details['priest_heal_regular']['cost'],25)
        self.assertNotIn('priest_heal_regular',hero['loadout'])


class FollowupDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_temporary_review_scenarios_and_actual_api_snapshots(self):
        from aiohttp.test_utils import TestClient,TestServer
        from tools.preview_balance_followup import application
        from arena_raid_web import raid_view
        app=await application();db=app['guild_review_db']
        async with TestClient(TestServer(app)) as client:
            page=await client.get('/balance-review');self.assertEqual(page.status,200)
            self.assertIn('Сбросить таймер',await page.text())
            for name,actor in (('prayer',10),('party',10),('mana',20),('roulette',30)):
                response=await client.get('/balance-demo/'+name,allow_redirects=False)
                self.assertEqual(response.status,302)
                row=dict(db.connection.execute("SELECT * FROM arena_raids WHERE status='active' ORDER BY created_at DESC LIMIT 1").fetchone())
                row=await db.arena_raid_get(row['token']);view=await raid_view(db,row,actor)
                hero=view['data']['players'][str(actor)]['fighter']
                if actor==10:self.assertIn('priest_heal_regular',[s['skill_id'] for s in hero['skill_details']])
                if actor==20:self.assertEqual(hero['rpg_state']['mana'],3)
            self.assertEqual((await client.post('/balance-demo/reset-roulette')).status,200)


if __name__=='__main__':unittest.main()
