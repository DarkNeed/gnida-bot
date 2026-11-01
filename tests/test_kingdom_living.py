"""Shared camp state, snapshot combat, identity edits and municipal landmarks."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest
from uuid import uuid4

import test_kingdom as base
from arena_kingdom_rules import HOUR,DAY,capacity
from arena_kingdom_war import new_unit
import arena_kingdom_camps as camps
import arena_kingdom_estate as estate
import arena_kingdom_finance as finance


class LivingWorldTests(unittest.IsolatedAsyncioTestCase):
    live_world=True
    asyncSetUp=base.KingdomTests.asyncSetUp
    asyncTearDown=base.KingdomTests.asyncTearDown
    view=base.KingdomTests.view
    action=base.KingdomTests.action
    found=base.KingdomTests.found
    town=base.KingdomTests.town
    budget=base.KingdomTests.budget

    def prepare(self,actor=10):
        row=self.town(actor);d=row['data'];d.update(stage=2,construction=None,event=None,next_event=self.now+365*DAY)
        d['resources'].update(food=2000,wood=2000,stone=2000);d['buildings'].update(warehouse=3,barracks=2)
        m=d['military'];m['units']=[new_unit(k,self.now,ready=True) for k in ('paladins','shields','archers','priests','necromancers')]
        m['formation']=[u['id'] for u in m['units']];self.db._kingdom_save_locked(row);self.db.connection.commit()

    def camp(self):return camps.rows(self.db,-100)[0]

    def unguarded(self):
        c=self.camp()
        for u in c['data']['garrison']:u['hp']=0
        camps.save(self.db,c);self.db.connection.commit();return c

    async def march(self,c,actor=10):
        return await self.action('camp_march',actor,camp=c['id'],camp_revision=c['revision'],tactic='guard')

    async def test_world_spawns_bounded_shared_targets_on_legal_land_and_survives_reconnect(self):
        await self.found();v=await self.view();self.assertEqual(len(v['camps']),3)
        self.assertEqual(v['camps'],(await self.view(20))['camps'])
        self.assertEqual((await self.view(chat=-200))['camps'],[])
        for c in v['camps']:
            tile=next(t for t in v['tiles'] if (t['q'],t['r'])==(c['q'],c['r']))
            self.assertFalse(tile['town']);self.assertFalse(tile['site']);self.assertFalse(tile['can_annex'])
            self.assertNotIn('seed',c);self.assertNotIn('contributions',c)
        ident=v['camps'][0]['id'];await self.db.close();await self.db.connect()
        self.assertIn(ident,[c['id'] for c in (await self.view())['camps']])
        for _ in range(8):self.now+=12*HOUR;await self.view()
        self.assertLessEqual(len([c for c in (await self.view())['camps'] if c['status']=='active']),4)

    async def test_multiple_raids_persist_walls_and_do_not_pay_wallet_or_arena_rewards(self):
        await self.found();self.prepare();c=self.unguarded();before=await self.db.franc_balance(-100,10)
        for expected in (900,600,300,0):
            c=camps.get(self.db,-100,c['id']);await self.march(c)
            # A repeated view cannot instantly finish a six-hour march.
            self.assertEqual(camps.get(self.db,-100,c['id'])['data']['hp'],expected+300)
            self.now+=6*HOUR;await self.view()
            actual=camps.get(self.db,-100,c['id']);self.assertEqual(actual['data']['hp'],expected)
            snapshot=json.dumps(actual,sort_keys=True);await self.view();self.assertEqual(snapshot,json.dumps(camps.get(self.db,-100,c['id']),sort_keys=True))
        self.assertEqual(actual['status'],'ruins');self.assertEqual(estate.initialize(self.town()['data'])['trophies'],1)
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertIsNone(self.town()['data']['military']['campaign'])
        self.assertEqual(len(self.town()['data']['military']['reports']),3)
        with self.assertRaises(ValueError):await self.march(actual)
        self.now+=DAY;await self.view();self.assertNotIn(actual['id'],[c['id'] for c in camps.rows(self.db,-100)])

    async def test_campaign_snapshot_is_authoritative_and_garrison_damage_does_not_stack_armor(self):
        await self.found();self.prepare();c=self.camp();await self.march(c)
        row=self.town();snap=deepcopy(row['data']['military']['campaign']['snapshot'])
        estate.initialize(row['data'])['specials']=['academy'];self.db._kingdom_save_locked(row);self.db.connection.commit()
        self.assertEqual(snap,self.town()['data']['military']['campaign']['snapshot'])
        self.now+=6*HOUR;await self.view();after=camps.get(self.db,-100,c['id'])
        self.assertEqual([u['armor'] for u in c['data']['garrison']],[u['armor'] for u in after['data']['garrison']])
        self.assertTrue(any(u['hp']<u['max_hp'] for u in after['data']['garrison']))

    async def test_busy_target_rejects_second_town_and_foreign_world(self):
        await self.found();self.prepare();v=await self.view(20)
        tile=next(t for t in v['tiles'] if t['can_found'])
        await self.found(actor=20,q=tile['q'],r=tile['r']);self.prepare(20)
        c=self.unguarded();await self.march(c)
        with self.assertRaises(ValueError):await self.march(c,20)
        # A fresh version still cannot bypass the camp's exclusive march.
        with self.assertRaisesRegex(ValueError,'уже идёт'):await self.march(camps.get(self.db,-100,c['id']),20)
        await self.found(chat=-200)
        foreign=camps.rows(self.db,-200)[0]
        with self.assertRaises(ValueError):await self.march(foreign,20)

    async def test_contribution_rewards_do_not_belong_to_last_hit(self):
        await self.found();self.prepare();v=await self.view(20);tile=next(t for t in v['tiles'] if t['can_found'])
        await self.found(actor=20,q=tile['q'],r=tile['r']);self.prepare(20)
        c=self.unguarded();c['data']['hp']=300;c['data']['contributions']={self.town()['id']:900};camps.save(self.db,c);self.db.connection.commit()
        await self.march(camps.get(self.db,-100,c['id']),20);self.now+=6*HOUR;await self.view(20)
        self.assertEqual(estate.initialize(self.town()['data'])['trophies'],1)
        self.assertEqual(estate.initialize(self.town(20)['data'])['trophies'],1)
        self.assertTrue(any('75%' in h['text'] for h in self.town()['data']['history']))
        self.assertTrue(any('25%' in h['text'] for h in self.town(20)['data']['history']))

    async def test_appearance_is_cosmetic_escaped_and_owner_only(self):
        await self.found();before=deepcopy(self.town()['data']['resources']);money=self.budget()
        await self.action('land_style',style='gothic',color='#aa99ff',emblem='moon')
        row=self.town();await self.action('land_decor',q=row['q'],r=row['r'],name='<script>Земля</script>',description='Наша область',decoration='garden')
        own=(await self.view())['towns'][0];self.assertEqual(own['estate']['style'],'gothic')
        public=(await self.view(20))['towns'][0]['estate'];self.assertNotIn('trophies',public);self.assertNotIn('catalog',public)
        self.assertEqual(self.town()['data']['resources'],before);self.assertEqual(self.budget(),money)
        with self.assertRaises(ValueError):await self.action('land_decor',q=0,r=0,name='Чужая',decoration='garden')
        with self.assertRaises(ValueError):await self.action('land_style',style='gothic',color='red;position:fixed',emblem='moon')
        body=dict(action='land_style',town=own['id'],revision=own['revision'],style='holy',color='#aaaaaa',emblem='sun',confirm=True,nonce=uuid4().hex)
        with self.assertRaisesRegex(ValueError,'не твоё'):await self.db.kingdom_action(-100,20,body)

    async def test_special_project_shares_queue_costs_budget_and_is_not_instant(self):
        await self.found();self.prepare();money=self.budget();wallet=await self.db.franc_balance(-100,10)
        await self.action('special_build',special='academy');self.assertEqual(self.budget(),money-120000)
        self.assertFalse(estate.has(self.town()['data'],'academy'))
        with self.assertRaisesRegex(ValueError,'очередь'):await self.action('build',building='sawmill')
        with self.assertRaisesRegex(ValueError,'очередь'):await self.action('special_build',special='temple')
        self.now+=71*HOUR;await self.view();self.assertFalse(estate.has(self.town()['data'],'academy'))
        self.now+=HOUR;await self.view();self.assertTrue(estate.has(self.town()['data'],'academy'))
        self.assertEqual(await self.db.franc_balance(-100,10),wallet)
        d=self.town()['data'];base_unit=camps.army._fighters([dict(id='t',kind='militia',slot=0,condition=100)],'p:')[0]
        improved=estate.buffs(d,[deepcopy(base_unit)])[0]
        self.assertAlmostEqual(improved['attack'],base_unit['attack']*1.08);self.assertEqual(improved['armor'],base_unit['armor']+2)
        self.assertEqual(estate.upkeep(d),120)
        await self.action('special_remove',special='academy');self.assertTrue(estate.has(self.town()['data'],'academy'))
        self.now+=DAY;await self.view();self.assertFalse(estate.has(self.town()['data'],'academy'))
        self.assertEqual(self.budget(),money-120000)

    async def test_camp_raid_does_not_reduce_past_tax_collection_and_tower_halves_pressure(self):
        await self.found();row=self.town();d=row['data']
        d.update(population=55,order=80,event=None,next_event=self.now+365*DAY)
        d['buildings']={key:1 for key in d['buildings']};d['resources'].update(food=1000,wood=500,stone=500)
        self.db._kingdom_save_locked(row);self.db.connection.commit();await self.action('tax_activate')
        for c in camps.rows(self.db,-100):
            c['data']['pressure_at']=self.now+365*DAY;camps.save(self.db,c)
        c=self.camp();c['data'].update(stage=2,pressure_at=self.now+DAY,grow_at=self.now+365*DAY)
        self.db.connection.execute('UPDATE kingdom_camps SET q=?,r=? WHERE id=?',(row['q']+2,row['r'],c['id']))
        self.db.connection.execute('UPDATE kingdom_camp_worlds SET next_spawn=? WHERE chat=-100',(self.now+365*DAY,))
        camps.save(self.db,c);self.db.connection.commit()
        money=self.budget();self.now+=DAY;await self.view()
        self.assertEqual(self.budget(),money+650)
        self.assertEqual(self.town()['data']['order'],78)
        resources=deepcopy(self.town()['data']['resources']);await self.view(20)
        self.assertEqual(resources,self.town()['data']['resources'])
        row=self.town();estate.initialize(row['data'])['specials']=['watchtower'];self.db._kingdom_save_locked(row);self.db.connection.commit()
        self.now+=DAY;await self.view();self.assertEqual(self.town()['data']['order'],77)

    async def test_special_slots_wonder_trophies_validation_and_nonce_replay(self):
        await self.found();self.prepare();row=self.town();e=estate.initialize(row['data']);e['specials']=['academy','temple']
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'места'):await self.action('special_build',special='caravan')
        row=self.town();row['data']['stage']=3;self.db._kingdom_save_locked(row);self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'трофеев'):await self.action('special_build',special='wonder')
        row=self.town();estate.initialize(row['data'])['trophies']=4;self.db._kingdom_save_locked(row);self.db.connection.commit()
        t=next(t for t in (await self.view())['towns'] if t['own'])
        body=dict(action='special_build',special='wonder',town=t['id'],revision=t['revision'],confirm=True,nonce=uuid4().hex)
        money=self.budget();await self.db.kingdom_action(-100,10,body);await self.db.kingdom_action(-100,10,body)
        self.assertEqual(self.budget(),money-600000);self.assertEqual(estate.initialize(self.town()['data'])['trophies'],0)
        self.now+=7*DAY;await self.view();self.assertTrue(estate.has(self.town()['data'],'wonder'))

    async def test_real_renderer_includes_camps_editors_and_landmark_actions(self):
        await self.found();self.prepare();view=await self.view()
        result=subprocess.run(['node','tests/kingdom_living_client.cjs'],input=json.dumps(view),text=True,encoding='utf-8',capture_output=True,cwd=Path(__file__).resolve().parents[1],timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
