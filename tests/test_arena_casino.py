import json
import random
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from arena_casino import roll_action,after_action,variant,restriction
from arena_engine import BUILTIN_SKILLS,create_battle_state,resolve_skill,restore_turn_resource,effective_skill,unlocked_skill_ids
from arena_qte_unique import review_catalog
from arena_qte_patterns import profile,defense,prepare
from arena_qte_rules import replay
from arena_qte_block import replay as block_replay
from arena_casino_qte import block_threats
from database import Database


class Dice(random.Random):
    def __init__(self,*dice):super().__init__(0);self.dice=iter(dice)
    def randint(self,a,b):return next(self.dice)
    def random(self):return .5
    def uniform(self,a,b):return 1
    def choice(self,values):return values[0]
    def randrange(self,*args):return 0


def battle(branch=''):
    state=create_battle_state(dict(slave_id=10,owner_id=10,class_id='gambler',level=20,archclass_id=branch,archclass_stage=20),
                              dict(slave_id=20,owner_id=20,class_id='warrior',level=20))
    state.update(active_side='a')
    for s in state['sides'].values():s.update(hp=1000,resource=100);s['stats'].update(max_hp=1000,evasion=0)
    state['sides']['a']['loadout']=['casino_bet','casino_ace','casino_credit','casino_all_in']
    state['sides']['a'].pop('_casino_roll_seed',None)  # Explicit deterministic dice in unit tests.
    return state


class CasinoCombatTests(unittest.TestCase):
    def test_hidden_seed_predicts_same_die_without_mutating_reads(self):
        from arena_casino import public_state
        a=battle('casino_lucky')['sides']['a'];a['_casino_roll_seed']='private-seed'
        _,one=roll_action(deepcopy(a),BUILTIN_SKILLS['casino_bet'],random.Random(1))
        _,two=roll_action(deepcopy(a),BUILTIN_SKILLS['casino_bet'],random.Random(99))
        self.assertEqual(one,two)
        self.assertNotIn('_casino_roll_seed',json.dumps(public_state(dict(sides=[a],nested=dict(seed=a)))))
        self.assertEqual(a['_casino_roll_seed'],'private-seed')

    def test_preview_never_rolls_or_mutates(self):
        s=battle('casino_lucky');s['sides']['a']['casino_state']=dict(chips=7,sevens=3)
        before=deepcopy(s)
        for _ in range(4):self.assertTrue(effective_skill(s,'a','casino_deposit').name.startswith('777'))
        self.assertEqual(s,before)

    def test_three_bad_rolls_prepare_six_even_on_miss(self):
        s=battle();a=s['sides']['a']
        for _ in range(3):
            a['resource']=100
            resolve_skill(s,'a','casino_bet',rng=Dice(1),advance_turn=False,qte=dict(attack=[False]))
        self.assertEqual(a['casino_state']['misfortune'],3)
        a['resource']=100
        event=resolve_skill(s,'a','casino_bet',rng=Dice(),advance_turn=False,qte=dict(attack=[True]))
        self.assertIn('ДЖЕКПОТ',event['text']);self.assertEqual(a['casino_state']['misfortune'],0)

    def test_ace_best_of_two_preserves_guarantee_until_attack(self):
        s=battle();a=s['sides']['a'];a['casino_state']=dict(misfortune=3)
        resolve_skill(s,'a','casino_ace',rng=Dice(),advance_turn=False)
        self.assertEqual(a['casino_state']['misfortune'],3)
        _,r=roll_action(a,BUILTIN_SKILLS['casino_bet'],Dice())
        self.assertEqual(r['die'],6);self.assertTrue(a['casino_state']['ace'])
        _,r=roll_action(a,BUILTIN_SKILLS['casino_bet'],Dice(1,5));self.assertEqual(r['die'],5)

    def test_lucky_jackpot_stronger_and_spends_777_on_miss(self):
        a=battle('casino_lucky')['sides']['a'];a['casino_state']=dict(chips=7,sevens=3)
        skill=variant(BUILTIN_SKILLS['casino_deposit'],a)
        rolled,r=roll_action(a,skill,Dice(6))
        self.assertTrue(r['seven']);self.assertAlmostEqual(rolled.power,55*8)
        self.assertEqual(a['casino_state']['chips'],2);self.assertEqual(a['casino_state']['sevens'],1)

    def test_credit_real_gain_debt_and_once_per_turn_regen(self):
        s=battle();a=s['sides']['a'];a['resource']=75
        event=resolve_skill(s,'a','casino_credit',rng=Dice(),advance_turn=False)
        self.assertEqual(a['resource'],100);self.assertEqual(a['casino_state']['debt'],25)
        self.assertEqual(event['deliberate_resource_restored'],25)
        self.assertTrue(restriction(a,BUILTIN_SKILLS['casino_credit']))
        a['resource']=0
        for turn in (1,2,3):
            a['own_turns']=turn;self.assertEqual(restore_turn_resource(a),0)
            restore_turn_resource(a)
        self.assertEqual(a['casino_state']['debt'],1)
        a['own_turns']=4;self.assertEqual(restore_turn_resource(a),7)
        self.assertEqual(a['casino_state']['debt'],0)

    def test_zero_credit_full_energy_creates_no_debt(self):
        s=battle();resolve_skill(s,'a','casino_credit',rng=Dice(),advance_turn=False)
        self.assertEqual(s['sides']['a']['casino_state']['debt'],0)

    def test_all_in_self_damage_and_cost_even_on_miss(self):
        s=battle();a=s['sides']['a']
        event=resolve_skill(s,'a','casino_all_in',rng=Dice(1),qte=dict(attack=[False]),advance_turn=False)
        self.assertEqual(a['hp'],920);self.assertEqual(a['resource'],60);self.assertEqual(event['damage'],0)

    def test_dodge_priority_and_json_reload(self):
        s=battle('casino_lucky');s['sides']['a']['casino_state']=dict(misfortune=3,chips=4)
        s=json.loads(json.dumps(s))
        event=resolve_skill(s,'a','casino_bet',rng=Dice(),qte=dict(attack=[True],dodge=[True]),advance_turn=False)
        self.assertEqual(event['damage'],0);self.assertEqual(s['sides']['a']['casino_state']['last_die'],6)
        self.assertEqual(s['sides']['a']['resource'],85)  # No jackpot refund on dodge.

    def test_foreign_skills_no_dice_and_no_free_energy(self):
        a=battle()['sides']['a'];before=deepcopy(a)
        skill,r=roll_action(a,BUILTIN_SKILLS['bum_punch'],Dice())
        self.assertIsNone(r);self.assertEqual(a,before)

    def test_hustler_reroll_limit_and_single_use_store(self):
        a=battle('casino_hustler')['sides']['a'];a['own_turns']=0
        _,r=roll_action(a,BUILTIN_SKILLS['casino_bet'],Dice(1,5));self.assertEqual(r['die'],5)
        after_action(a,BUILTIN_SKILLS['casino_hold'],True,None)
        _,r=roll_action(a,BUILTIN_SKILLS['casino_bet'],Dice())
        self.assertEqual(r['die'],5);self.assertTrue(restriction(a,BUILTIN_SKILLS['casino_hold']))
        _,r=roll_action(a,BUILTIN_SKILLS['casino_bet'],Dice(1));self.assertEqual(r['die'],1)

    def test_branch_skills_cannot_leak(self):
        normal=unlocked_skill_ids('gambler',20)
        self.assertNotIn('casino_deposit',normal);self.assertNotIn('casino_house',normal)
        lucky=unlocked_skill_ids('gambler',20,archclass_id='casino_lucky')
        self.assertIn('casino_deposit',lucky);self.assertNotIn('casino_house',lucky)


class CasinoPatternTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_client_uses_all_casino_sprites_and_preserves_custom_priority(self):
        from test_arena_market_client import ArenaMarketClientTests
        runner=ArenaMarketClientTests()
        keys=('gambler','casino_hustler','casino_lucky','casino_hustler_final','casino_lucky_final')
        paths=['/static/assets/casino/'+key+'.png' for key in keys]
        inputs=[dict(sprite='gambler',class_avatar_url=path) for path in paths]
        self.assertEqual(json.loads(runner.run_client('out=JSON.stringify(input.map(sprite));',inputs)),paths)
        custom='/sprites/'+'a'*64+'.png'
        for item in inputs:item['sprite_url']=custom
        self.assertEqual(json.loads(runner.run_client('out=JSON.stringify(input.map(sprite));',inputs)),[custom]*5)
        self.assertEqual(runner.run_client('out=sprite(input);','gambler'),paths[0])
        self.assertEqual(runner.run_client('out=sprite(input);',dict(sprite='gambler',class_avatar_url='https://example.com/other.png')),paths[0])

    def test_all_five_game_sprites_are_compact_transparent_exports(self):
        from PIL import Image
        from arena_progression import choice_avatar
        for key in ('gambler','casino_hustler','casino_lucky','casino_hustler_final','casino_lucky_final'):
            path=Path('webapp/assets/casino')/(key+'.png')
            self.assertLess(path.stat().st_size,700000)
            with Image.open(path) as sprite:
                self.assertEqual(sprite.size,(512,768));self.assertEqual(sprite.mode,'RGBA')
                self.assertEqual(sprite.getchannel('A').getextrema(),(0,255))
        self.assertEqual(choice_avatar('','casino_hustler'),choice_avatar('gambler','casino_hustler'))

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_themed_views_and_single_attempt(self):
        result=subprocess.run([shutil.which('node'),'tests/casino_views.cjs'],input=json.dumps(review_catalog()),capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_five_patterns_have_distinct_geometry_and_block_schedules(self):
        rows=[s for s in review_catalog() if s['class_id']=='gambler']
        self.assertEqual(len({profile(s)['kind'] for s in rows}),5)
        stats=dict(accuracy=75,enemyEvasion=0,enemyAccuracy=100,evasion=0)
        schedules={}
        for row in rows:
            p=profile(row);s=defense(p,stats,17);prepare(s,s['events'][0])
            self.assertTrue(s['hazards'])
            events=block_threats(p,17,dict(warning=.65))
            schedules[p['kind']]=[(e['at'],e['kind'],e['weight']) for e in events]
            if p['kind']=='casino_roulette':self.assertEqual(sum(e['kind']=='feint' for e in events),2)
            if p['kind']=='casino_dice':
                self.assertEqual({e['face'] for e in events},{2,3,4})
                self.assertTrue(all(h.get('motif')=='casino_pip' for h in s['hazards'][:-1]))
            if p['kind']=='casino_jackpot':
                self.assertEqual({e.get('reel') for e in events if e.get('reel')},{1,2,3})
                self.assertEqual(len(s['events']),6)
        self.assertEqual(len({json.dumps(v) for v in schedules.values()}),5)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_clean_dodge_routes_exist_even_without_evasion(self):
        catalog=[s for s in review_catalog() if s['class_id']=='gambler']
        configs=[dict(version=2,kind='defense',defense_preparation=1,profile=s,seed=17,strikes=s['strikes'],perfect=True,
                      stats=dict(accuracy=75,enemyEvasion=0,enemyAccuracy=100,evasion=0)) for s in catalog]
        result=subprocess.run([shutil.which('node'),'tests/qte_patterns_trace.cjs'],input=json.dumps(configs),capture_output=True,text=True,encoding='utf-8',timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        for c,trace in zip(configs,json.loads(result.stdout)):
            self.assertFalse(trace['result']['contacts'],c['profile']['name'])
            self.assertEqual(replay(c,trace['proof'],30),trace['result'])

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_client_server_match_all_casino_patterns(self):
        catalog=[s for s in review_catalog() if s['class_id']=='gambler']
        self.assertEqual({s['base_id'] for s in catalog},{'casino_bet','casino_all_in','casino_deposit','mastery_gambler'})
        configs=[dict(version=2,kind='defense',defense_preparation=1,profile=s,seed=seed,strikes=s['strikes'],
                      stats=dict(accuracy=75,enemyEvasion=20,enemyAccuracy=accuracy,evasion=evasion))
                 for s in catalog for seed in (17,29) for accuracy,evasion in ((100,0),(65,40))]
        result=subprocess.run([shutil.which('node'),'tests/qte_patterns_trace.cjs'],input=json.dumps(configs),capture_output=True,text=True,encoding='utf-8',timeout=90)
        self.assertEqual(result.returncode,0,result.stderr)
        for c,trace in zip(configs,json.loads(result.stdout)):
            self.assertEqual(replay(c,trace['proof'],30),trace['result'],c['profile']['name'])
        for c in configs:c.update(version=3,defense_mode='block',stats=dict(physicalDefense=35,magicDefense=35,enemyAttack=30,enemyAccuracy=c['stats']['enemyAccuracy']))
        result=subprocess.run([shutil.which('node'),'tests/qte_block_trace.cjs'],input=json.dumps(configs),capture_output=True,text=True,encoding='utf-8',timeout=90)
        self.assertEqual(result.returncode,0,result.stderr)
        for c,trace in zip(configs,json.loads(result.stdout)):
            actual=block_replay(c,trace['proof'],30)
            self.assertEqual(actual,trace['result'],c['profile']['name'])

    def test_preparation_and_777_pressure(self):
        rows=[s for s in review_catalog() if s['base_id']=='casino_deposit']
        stats=dict(accuracy=75,enemyEvasion=0,enemyAccuracy=100,evasion=0)
        plain=defense(profile(next(s for s in rows if not s['name'].startswith('777'))),stats,17)
        seven=defense(profile(next(s for s in rows if s['name'].startswith('777'))),stats,17)
        self.assertGreater(seven['d']['speed'],plain['d']['speed'])
        for s in (plain,seven):
            prepare(s,s['events'][0]);self.assertTrue(all(h['start']>=1 for h in s['hazards']))


class CasinoUnlockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'test.sqlite3');await self.db.connect()
        await self.db.upsert_chat(-100,'Чат');await self.db.upsert_user(-100,10,'test','Игрок')
        await self.db.credit_francs(-100,10,1000)

    async def asyncTearDown(self):await self.db.close();self.tmp.cleanup()

    async def test_win_invitation_atomic_and_hidden_from_shop(self):
        self.assertFalse((await self.db.arena_casino_view(-100,10))['invited'])
        result=await self.db.deposit_francs(-100,10,1,-100,1,rng=Dice())
        self.assertTrue(result['won']);self.assertTrue((await self.db.arena_casino_view(-100,10))['invited'])
        self.assertNotIn(('class','gambler'),self.db._arena_shop_catalog_locked())
        self.assertFalse(any(v['details'].get('class_id')=='gambler' for v in self.db._arena_shop_catalog_locked().values()))
        self.assertEqual(self.db._arena_secret_classes_locked(10),set())

    async def test_free_trial_revision_and_account_unlock(self):
        self.db._casino_row_locked(10)
        self.db.connection.execute('UPDATE arena_casino_unlocks SET invited=1 WHERE user_id=10');self.db.connection.commit()
        with patch.object(self.db,'_arena_merchant_view_locked',return_value=dict(visit_id=1)):
            await self.db.arena_casino_action(-100,10,dict(move='start',revision=0),rng=Dice(1))
        with self.assertRaises(ValueError):await self.db.arena_casino_action(-100,10,dict(move='high',revision=0),rng=Dice(13))
        for rev in range(1,6):
            await self.db.arena_casino_action(-100,10,dict(move='high' if rev%2 else 'low',revision=rev),rng=Dice(13 if rev%2 else 1))
        self.assertEqual(self.db._arena_secret_classes_locked(10),{'gambler'})
        self.assertEqual(self.db.connection.execute('SELECT balance FROM franc_balances WHERE chat_id=-100 AND user_id=10').fetchone()[0],1000)
        with self.assertRaises(ValueError):await self.db.arena_casino_action(-100,10,dict(move='equip',revision=6))
        self.db._arena_profile_locked(-100,10,True)
        self.db._grant_profile_xp_locked('personal_profiles',-100,10,1000)
        await self.db.arena_casino_action(-100,10,dict(move='equip',revision=6,confirm=True))
        profile=self.db._arena_profile_locked(-100,10,True)
        self.assertEqual(profile['class_id'],'gambler');self.assertEqual(profile['level'],5)
        self.assertEqual(self.db._arena_secret_classes_locked(10),{'gambler'})
