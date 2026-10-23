import json
import random
import unittest
from copy import deepcopy
from types import SimpleNamespace
from aiohttp.test_utils import TestClient, TestServer

import test_arena
from test_arena_casino import battle, Dice
from arena_casino_chance import commit, draw, mode, public, RED, DICE_FACTORS
from arena_qte_rules import replay
from arena_engine import resolve_skill
from arena_web import create_arena_app


class Fixed(random.Random):
    def __init__(self, number=0, reels=(7,7,7)):
        super().__init__(0);self.number=number;self.reels=iter(reels)
    def randrange(self,*args):return self.number
    def choice(self,values):return next(self.reels)


class ChanceRulesTests(unittest.TestCase):
    def test_roulette_has_37_fair_sectors_and_explicit_payouts(self):
        colors=[]
        for sector in range(37):
            color='green' if sector==0 else 'red' if sector in RED else 'black'
            colors.append(color)
            for bet in ('red','black','green'):
                result=draw('roulette',bet,Fixed(sector))
                self.assertEqual(result['factor'],(30 if color=='green' else 2) if bet==color else 0)
        self.assertEqual([colors.count(c) for c in ('red','black','green')],[18,18,1])

    def test_die_and_automatic_reels(self):
        self.assertEqual([draw('dice','launch',Fixed(i))['factor'] for i in range(1,7)],list(DICE_FACTORS))
        for reels,factor in (((7,7,7),8),((1,1,1),3),((7,1,7),2),((1,7,2),1),((1,2,3),.35)):
            self.assertEqual(draw('slots','launch',Fixed(reels=reels))['factor'],factor)

    def test_committed_result_survives_reload_abort_and_forged_client_factor(self):
        stage=dict(casino_mode='roulette',kind='attack',strikes=1)
        outcome=commit(stage,'green')
        stage=json.loads(json.dumps(stage))
        self.assertEqual(commit(stage,'green'),outcome)
        with self.assertRaises(ValueError):commit(stage,'red')
        self.assertNotIn('_casino_chance_seed',public(stage))
        for proof in (dict(casino_launch=True,factor=999),dict(abort=True)):
            self.assertEqual(replay(stage,proof,0)['casino'],outcome)
        with self.assertRaises(ValueError):replay(dict(casino_mode='dice',strikes=1,kind='attack'),dict(casino_launch=True),0)

    def test_payout_replaces_native_die_multiplier_and_dodge_still_wins(self):
        events=[]
        for factor in (1,2,30):
            s=battle();qte=dict(attack=[True],luck_evasion=False,pattern_attack=dict(casino=dict(mode='roulette',factor=factor,sector=1,color='red')))
            s['sides']['b']['hp']=100000
            events.append(resolve_skill(s,'a','casino_all_in',rng=Dice(),advance_turn=False,qte=qte)['damage'])
        self.assertAlmostEqual(events[1]/events[0],2,delta=.1)
        self.assertAlmostEqual(events[2]/events[0],30,delta=1)
        for factor,dodge in ((0,False),(30,True)):
            s=battle();event=resolve_skill(s,'a','casino_all_in',rng=Dice(),advance_turn=False,qte=dict(attack=[True],dodge=[dodge],pattern_attack=dict(casino=dict(mode='roulette',factor=factor,sector=0,color='green'))))
            self.assertEqual(event['damage'],0)
            self.assertEqual(s['sides']['a']['resource'],60)


class ChanceStoreTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_arena.ArenaStoreTests.asyncSetUp
    asyncTearDown=test_arena.ArenaStoreTests.asyncTearDown
    duel=test_arena.ArenaStoreTests.duel

    async def test_real_flow_authorization_persistence_and_paid_loss(self):
        row=await self.duel()
        s=json.loads(row['state_json']);s['sides']['a']=battle()['sides']['a'];s['active_side']='a'
        self.db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',(json.dumps(s),row['token']));self.db.connection.commit()
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'skill','casino_all_in')
        c=(await self.db.arena_qte_view('battle',row['token'],10))['challenge']
        self.assertEqual(c['casino_mode'],'roulette');self.assertNotIn('_casino_chance_seed',c)
        with self.assertRaises(ValueError):await self.db.arena_qte_casino_roll('battle',row['token'],20,c['id'],'red')
        with self.assertRaises(ValueError):await self.db.arena_qte_casino_roll('battle',row['token'],10,'stale','red')
        result=await self.db.arena_qte_casino_roll('battle',row['token'],10,c['id'],'green')
        self.assertEqual(await self.db.arena_qte_casino_roll('battle',row['token'],10,c['id'],'green'),result)
        with self.assertRaises(ValueError):await self.db.arena_qte_casino_roll('battle',row['token'],10,c['id'],'red')
        resumed=(await self.db.arena_qte_view('battle',row['token'],10))['challenge']
        self.assertEqual(resumed['casino_result'],result)
        self.assertNotIn('_casino_chance_seed',await self.db.arena_qte_stream_stage('battle',row['token'],10,c['id']))
        # Closing after reveal must commit the SAME result and consume energy.
        row=await self.db.arena_interactive_action(row['token'],10,row['revision'],'qte',challenge_id=c['id'],proof=dict(abort=True))
        if result['factor']==0:
            state=json.loads(row['state_json']);self.assertEqual(state['sides']['a']['resource'],60)
            self.assertFalse((await self.db.arena_qte_view('battle',row['token'],20)))


class ChanceHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_uses_server_outcome_and_static_scripts_load(self):
        app=create_arena_app(SimpleNamespace(),SimpleNamespace(),'test')
        async with TestClient(TestServer(app)) as client:
            for skill in ('casino_all_in','mastery_gambler','777 · Фортуна снимает ограничения'):
                response=await client.get('/qte-lab/casino/',params=dict(skill=skill))
                self.assertEqual(response.status,200)
                source=await response.text();self.assertNotIn('_casino_chance_seed',source)
                stage=json.loads(source.split('const stage=')[1].split(';')[0])
                choice='green' if stage['casino_mode']=='roulette' else 'launch'
                body=dict(id=stage['id'],choice=choice)
                first=await (await client.post('/qte-lab/casino/roll',json=body)).json()
                second=await (await client.post('/qte-lab/casino/roll',json=body)).json()
                self.assertEqual(first,second);self.assertIn('factor',first)
            for path in ('/static/qte-casino-chance.js','/static/qte-casino-chance.css'):
                self.assertEqual((await client.get(path)).status,200)
