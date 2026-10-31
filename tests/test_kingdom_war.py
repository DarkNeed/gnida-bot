"""Trusted military orders, snapshots, attrition and NPC-only rewards."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_kingdom as towns
from arena_kingdom_war import new_unit,initialize,resolve_battle,synergies,UNITS,OUTPOSTS,HOUR


class MilitaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=towns.KingdomTests.asyncSetUp
    asyncTearDown=towns.KingdomTests.asyncTearDown
    view=towns.KingdomTests.view
    action=towns.KingdomTests.action
    found=towns.KingdomTests.found
    town=towns.KingdomTests.town

    async def prepare(self,kinds=('shields','militia','archers','priests'),actor=10):
        await self.found(actor=actor,q=7 if actor==10 else 12)
        row=self.town(actor);d=row['data'];d['buildings']['barracks']=2;d['stage']=2
        d['factions'].update(light=2,velvet=2,grave=2);d['next_event']=self.now+100*HOUR
        d['resources'].update(food=600,wood=500,stone=500)
        m=initialize(d);m['units']=[new_unit(k,self.now,ready=True) for k in kinds]
        m['formation']=[u['id'] for u in m['units'][:5]]+[None]*max(0,5-len(kinds))
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        return self.town(actor)

    async def test_recruitment_gates_atomic_price_single_queue_and_clock(self):
        await self.found()
        with self.assertRaises(ValueError):await self.action('recruit',unit='militia')
        row=self.town();row['data']['buildings']['barracks']=1;self.db._kingdom_save_locked(row);self.db.connection.commit()
        row=self.town();body=dict(action='recruit',unit='militia',town=row['id'],revision=row['revision'],nonce=uuid4().hex,confirm=True,price=0,ready_at=0)
        before=await self.db.franc_balance(-100,10)
        await self.db.kingdom_action(-100,10,body);await self.db.kingdom_action(-100,10,body)
        m=self.town()['data']['military'];self.assertEqual(len(m['units']),1)
        self.assertEqual(await self.db.franc_balance(-100,10),before-12000)
        self.assertEqual(m['units'][0]['ready_at'],self.now+6*HOUR)
        with self.assertRaises(ValueError):await self.action('recruit',unit='archers')
        self.now+=6*HOUR
        with self.assertRaises(ValueError):await self.action('recruit',unit='agents')
        await self.action('recruit',unit='archers')
        self.assertEqual(len(self.town()['data']['military']['units']),2)

    async def test_failed_save_rolls_back_recruitment_payment_and_food(self):
        await self.prepare(kinds=('militia',));row=self.town()
        before=await self.db.franc_balance(-100,10);resources=deepcopy(row['data']['resources'])
        with patch.object(self.db,'_kingdom_save_locked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):await self.action('recruit',unit='militia')
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertEqual(self.town()['data']['resources'],resources)
        self.assertEqual(len(self.town()['data']['military']['units']),1)

    async def test_foreign_town_reserve_cap_duplicate_and_foreign_unit_ids_rejected(self):
        row=await self.prepare(kinds=('militia',)*8);m=row['data']['military']
        with self.assertRaises(ValueError):await self.action('recruit',unit='militia')
        for formation in ([m['units'][0]['id']]*5,['foreign',None,None,None,None],[{},None,None,None,None],[None]):
            with self.assertRaises(ValueError):await self.action('formation',formation=formation)
        for command,extra in [('recruit',dict(unit='militia')),('march',dict(target='road_camp',tactic='guard'))]:
            with self.assertRaises(ValueError):await self.action(command,actor=20,town=row['id'],revision=row['revision'],**extra)
        await self.action('formation',formation=[None]*5)
        with self.assertRaises(ValueError):await self.action('march',target='road_camp',tactic='guard')

    async def test_march_waits_for_recruits_and_cannot_target_a_player_or_unknown_tactic(self):
        row=await self.prepare();row['data']['military']['units'][0]['ready_at']=self.now+HOUR
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        with self.assertRaises(ValueError):await self.action('march',target='road_camp',tactic='guard')
        self.now+=HOUR
        for target,tactic in (('player:20','guard'),('road_camp','godmode'),([], 'guard')):
            with self.assertRaises(ValueError):await self.action('march',target=target,tactic=tactic)
        self.assertIsNone(self.town()['data']['military']['campaign'])

    async def test_campaign_snapshot_hidden_and_locked_then_resolves_once_without_arena_grants(self):
        row=await self.prepare();before_money=await self.db.franc_balance(-100,10)
        before_profile=dict(self.db._arena_profile_locked(-100,10,True))
        result=await self.action('march',target='road_camp',tactic='guard',won=True,seed='cheat')
        public=next(t for t in result['view']['towns'] if t['own'])['military']['campaign']
        self.assertNotIn('seed',public);self.assertNotIn('snapshot',public)
        self.assertFalse('military' in (await self.view(actor=20))['towns'][0])
        for command,extra in [('formation',dict(formation=[None]*5)),('dismiss',dict(unit=row['data']['military']['units'][0]['id'])),('march',dict(target='road_camp',tactic='guard'))]:
            with self.assertRaises(ValueError):await self.action(command,**extra)
        campaign=deepcopy(self.town()['data']['military']['campaign'])
        expected=resolve_battle(campaign['snapshot'],campaign['seed'])
        self.assertTrue(expected['won'])
        self.now+=5*HOUR;await self.view();self.assertFalse(self.town()['data']['military']['reports'])
        # Already deployed units/loot are not recalculated from a changed catalog.
        with patch.dict(UNITS['militia'],attack=99999):
            self.now+=HOUR;await self.view()
        d=self.town()['data'];m=d['military'];report=m['reports'][0]
        self.assertIsNone(m['campaign']);self.assertEqual(report['events'],expected['events'])
        self.assertEqual(m['glory'],1);self.assertTrue(report['won'])
        resources=deepcopy(d['resources']);await self.view();self.assertEqual(self.town()['data']['resources'],resources)
        self.assertEqual(len(self.town()['data']['military']['reports']),1)
        self.assertEqual(await self.db.franc_balance(-100,10),before_money)
        self.assertEqual(dict(self.db._arena_profile_locked(-100,10,True)),before_profile)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM arena_inventory').fetchone()[0],0)
        with self.assertRaises(ValueError):await self.action('march',target='road_camp',tactic='guard')

    async def test_defeat_permanently_removes_dead_squads_and_releases_formation(self):
        await self.prepare(kinds=('militia',))
        await self.action('march',target='bone_foundry',tactic='assault');self.now+=6*HOUR;await self.view()
        m=self.town()['data']['military'];report=m['reports'][0]
        self.assertFalse(report['won']);self.assertEqual(report['lost'],1)
        self.assertFalse(m['units']);self.assertEqual(m['formation'],[None]*5)
        self.assertEqual(m['glory'],0);self.assertEqual(report['loot'],{})

    async def test_recovery_cost_queue_and_dismissal_no_refund(self):
        row=await self.prepare(kinds=('militia',));unit=row['data']['military']['units'][0];unit['condition']=40
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        food=row['data']['resources']['food'];money=await self.db.franc_balance(-100,10)
        await self.action('recover',unit=unit['id'])
        d=self.town()['data'];self.assertEqual(d['resources']['food'],food-60)
        self.assertEqual(d['military']['units'][0]['ready_at'],self.now+3*HOUR)
        with self.assertRaises(ValueError):await self.action('march',target='road_camp',tactic='guard')
        await self.action('dismiss',unit=unit['id']);self.assertEqual(await self.db.franc_balance(-100,10),money)
        self.assertFalse(self.town()['data']['military']['units'])

    async def test_restart_preserves_pending_order_and_reports_are_bounded(self):
        await self.prepare();await self.action('march',target='road_camp',tactic='guard')
        before=deepcopy(self.town()['data']['military']['campaign'])
        await self.db.close();await self.db.connect();self.assertEqual(self.town()['data']['military']['campaign'],before)
        self.now+=6*HOUR;await self.view();self.assertEqual(len(self.town()['data']['military']['reports']),1)
        row=self.town();row['data']['military']['reports']*=3
        for u in row['data']['military']['units']:u['condition']=100
        row['data']['military']['cooldowns']={};row['data']['resources']['food']=600
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        await self.action('march',target='road_camp',tactic='guard');self.now+=6*HOUR;await self.view()
        self.assertEqual(len(self.town()['data']['military']['reports']),3)

    async def test_real_client_can_render_and_step_server_report(self):
        if not shutil.which('node'):self.skipTest('Node required')
        await self.prepare();await self.action('march',target='road_camp',tactic='guard');self.now+=6*HOUR
        view=await self.view()
        script="""const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{const v=JSON.parse(s),t=v.towns.find(t=>t.own),ctx={window:{}};vm.createContext(ctx);vm.runInContext(fs.readFileSync('webapp/kingdom-army.js','utf8'),ctx);let html=ctx.window.KingdomArmy.campaigns(t,v,false,'',999);assert(html.includes('NPC-гарнизон'));assert(html.includes('Диванная баррикада'));assert(html.includes('К итогу'));assert(!html.includes('NaN'));console.log('PASS report playback');});"""
        result=subprocess.run(['node','-e',script],input=json.dumps(view),text=True,encoding='utf-8',capture_output=True,timeout=30,cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_combinations_are_distinct_and_bounded(self):
        self.assertEqual(len(synergies(['vagrants']*5)),1)
        self.assertEqual({s['id'] for s in synergies(['paladins','priests','shields','archers'])},{'holy','covered'})
        self.assertEqual({s['id'] for s in synergies(['agents','agents','archers'])},{'velvet'})
        self.assertEqual({s['id'] for s in synergies(['necromancers','skeletons'])},{'grave'})
        snapshot=dict(target='road_camp',tactic='guard',units=[dict(id=str(i),kind=k,condition=100,slot=i) for i,k in enumerate(('shields','militia','archers','priests'))])
        a=resolve_battle(snapshot,'fixed');b=resolve_battle(snapshot,'fixed')
        self.assertEqual(a,b);self.assertTrue(a['events']);self.assertLessEqual(a['rounds'],12)


if __name__=='__main__':unittest.main()
