"""Government reforms and warned, transactional, chat-local territorial wars."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from uuid import uuid4

import test_kingdom as towns
import arena_kingdom_council as council
import arena_kingdom_war as army
from arena_kingdom_rules import HOUR,DAY,rates
from arena_kingdom_siege import connected
from arena_kingdom_notices import publish_kingdom_notices


class SiegeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=towns.KingdomTests.asyncSetUp
    asyncTearDown=towns.KingdomTests.asyncTearDown
    view=towns.KingdomTests.view
    action=towns.KingdomTests.action
    found=towns.KingdomTests.found
    town=towns.KingdomTests.town

    async def prepare(self):
        for actor,q in ((10,6),(20,11)):
            await self.found(actor=actor,q=q)
            row=self.town(actor);d=row['data']
            d.update(stage=2,founded_at=self.now-30*DAY,next_event=self.now+365*DAY)
            d['buildings'].update(barracks=2,warehouse=2,farm=2)
            d['resources'].update(food=1400,wood=500,stone=500)
            m=army.initialize(d)
            kinds=('militia',) if actor==10 else ('paladins','paladins','archers','priests','shields')
            m['units']=[army.new_unit(k,self.now,ready=True) for k in kinds]
            m['formation']=[u['id'] for u in m['units']]+[None]*(5-len(kinds))
            self.db._kingdom_save_locked(row)
            for q,r in (((7,4),(8,4)) if actor==10 else ((11,4),(10,4),(9,4))):
                self.db.connection.execute('INSERT INTO kingdom_tiles VALUES(?,?,?,?)',(-100,q,r,row['id']))
        self.db.connection.commit()

    async def declare(self):
        return await self.action('siege',actor=20,defender=self.town()['id'],q=8,r=4,tactic='assault')

    def save(self,row):
        self.db._kingdom_save_locked(row);self.db.connection.commit()

    async def test_reform_price_nonce_delay_cooldown_and_no_arena_power(self):
        await self.found();row=self.town();profile=dict(self.db._arena_profile_locked(-100,10,True))
        before=await self.db.franc_balance(-100,10)
        body=dict(action='reform',field='policy',choice='trade',town=row['id'],revision=row['revision'],confirm=True,nonce=uuid4().hex)
        await self.db.kingdom_action(-100,10,body);await self.db.kingdom_action(-100,10,body)
        self.assertEqual(await self.db.franc_balance(-100,10),before-25000)
        self.assertEqual(self.town()['data']['government']['policy'],'balanced')
        with self.assertRaises(ValueError):await self.action('reform',field='religion',choice='light')
        self.now+=24*HOUR;v=await self.view();g=next(t for t in v['towns'] if t['own'])['government']
        self.assertEqual(g['policy'],'trade');self.assertFalse(g['can_change']);self.assertIsNone(g['pending'])
        self.assertEqual(dict(self.db._arena_profile_locked(-100,10,True)),profile)
        self.now+=7*DAY;await self.action('reform',field='religion',choice='light')

    async def test_reform_production_changes_only_after_completion(self):
        await self.found();row=self.town();d=row['data'];d['buildings'].update(sawmill=2,warehouse=4)
        d['resources'].update(food=2000,wood=0,stone=0);d['next_event']=self.now+100*DAY;self.save(row)
        tiles=self.db._kingdom_tiles_locked(row,self.db._kingdom_world_locked(-100));old=rates(d,tiles)['wood']
        await self.action('reform',field='policy',choice='trade')
        self.now+=25*HOUR;await self.view();d=self.town()['data'];new=rates(d,tiles)['wood']
        self.assertEqual(d['resources']['wood'],old*24+new)

    async def test_catalog_supply_and_fighter_modifiers_have_tradeoffs(self):
        await self.prepare();row=self.town(20);d=row['data'];g=council.initialize(d)
        g.update(policy='military',religion='fortune');self.save(row)
        v=await self.view(20);t=next(t for t in v['towns'] if t['own'])
        self.assertEqual(t['military']['supplies'],251)
        fighters=council.buff(d,army._fighters(army.formation_units(d,self.now),'p:'))
        self.assertAlmostEqual(fighters[0]['attack'],army.UNITS['paladins']['attack']*1.1)
        self.assertTrue(fighters[0]['fortune']);self.assertGreater(fighters[0]['evasion'],army.UNITS['paladins']['evasion'])
        g.update(policy='trade',religion='light')
        self.assertEqual(council.recruit_terms(d,army.UNITS['skeletons'])['price'],round(army.UNITS['skeletons']['price']*.9*1.3))

    async def test_declaration_spends_once_hides_snapshot_and_locks_armies(self):
        await self.prepare();row=self.town(20);money=await self.db.franc_balance(-100,20)
        body=dict(action='siege',town=row['id'],revision=row['revision'],confirm=True,nonce=uuid4().hex,defender=self.town()['id'],q=8,r=4,tactic='guard')
        a=await self.db.kingdom_action(-100,20,body);b=await self.db.kingdom_action(-100,20,body)
        self.assertEqual(a['siege'],b['siege']);self.assertEqual(await self.db.franc_balance(-100,20),money-15000)
        self.assertEqual(len(a['view']['diplomacy']['wars']),1)
        self.assertNotIn('seed',str(a['view']['diplomacy']));self.assertNotIn('fighters',str(a['view']['diplomacy']))
        for command,extra in [('formation',dict(formation=[None]*5)),('march',dict(target='road_camp',tactic='guard')),('reform',dict(field='policy',choice='trade')),('annex',dict(q=12,r=5))]:
            with self.assertRaises(ValueError):await self.action(command,actor=20,**extra)

    async def test_undelivered_notice_expires_refunds_and_releases_both(self):
        await self.prepare();money=await self.db.franc_balance(-100,20);result=await self.declare()
        self.now+=HOUR;await self.view()
        self.assertEqual(self.db._siege_row(result['siege'])['status'],'cancelled')
        self.assertEqual(await self.db.franc_balance(-100,20),money)
        for actor in (10,20):self.assertIsNone(self.town(actor)['data']['military']['siege_lock'])
        self.assertEqual(self.db._siege_land(self.town()),{(6,5),(7,4),(8,4)})

    async def test_cancel_before_and_after_delivery_and_owner_check(self):
        await self.prepare();money=await self.db.franc_balance(-100,20);s=(await self.declare())['siege']
        with self.assertRaises(ValueError):await self.action('cancel_siege',siege=s)
        await self.action('cancel_siege',actor=20,siege=s)
        self.assertEqual(await self.db.franc_balance(-100,20),money)
        self.assertIsNone(self.town(20)['data']['military']['siege_lock'])
        self.now+=HOUR;s=(await self.declare())['siege'];await self.db.kingdom_siege_announced(s)
        await self.action('cancel_siege',actor=20,siege=s)
        self.assertEqual(await self.db.franc_balance(-100,20),money-15000)
        self.now+=HOUR
        with self.assertRaisesRegex(ValueError,'неделю'):await self.declare()
        # Bounded public history must not erase the pair's weekly restriction.
        self.db.connection.execute('DELETE FROM kingdom_sieges');self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'неделю'):await self.declare()

    async def test_restart_and_catalog_changes_do_not_replace_frozen_siege(self):
        await self.prepare();s=(await self.declare())['siege'];await self.db.kingdom_siege_announced(s)
        self.now+=24*HOUR;await self.view();snapshot=deepcopy(self.db._siege_row(s)['data']['snapshot'])
        await self.db.close();await self.db.connect()
        self.assertEqual(self.db._siege_row(s)['data']['snapshot'],snapshot)
        expected=army.resolve_battle(snapshot,self.db._siege_row(s)['data']['seed'])
        with patch.dict(army.UNITS['militia'],attack=999999):
            self.now+=6*HOUR;await self.view()
        self.assertEqual(self.town(20)['data']['military']['reports'][0]['events'],expected['events'])
        defender_report=self.town()['data']['military']['reports'][0]
        self.assertEqual(defender_report['lost'],1)
        self.assertTrue(defender_report['events'])

    async def test_foreign_changes_pending_reform_and_postwar_shield_are_denied(self):
        await self.prepare();row=self.town();g=council.initialize(row['data']);g['pending']=dict(field='policy',choice='trade',started=self.now,finish=self.now+DAY);self.save(row)
        with self.assertRaisesRegex(ValueError,'реформ'):await self.declare()
        row=self.town();row['data']['government']['pending']=None;row['data']['pvp']['shield_until']=self.now+DAY;self.save(row)
        with self.assertRaisesRegex(ValueError,'защита'):await self.declare()
        row=self.town();money=await self.db.franc_balance(-100,10)
        for command,fields in [('reform',dict(field='religion',choice='light')),('defense',dict(tactic='flank'))]:
            body=dict(action=command,confirm=True,nonce=uuid4().hex,town=row['id'],revision=row['revision'],**fields)
            with self.assertRaisesRegex(ValueError,'не твоё'):await self.db.kingdom_action(-100,20,body)
        self.assertEqual(await self.db.franc_balance(-100,10),money)

    async def test_warn_prepare_freeze_then_capture_exactly_once(self):
        await self.prepare();s=(await self.declare())['siege'];await self.db.kingdom_siege_announced(s)
        self.assertFalse(await self.db.kingdom_siege_announced(s));self.assertEqual(self.db._siege_row(s)['battle_at'],self.now+24*HOUR)
        await self.action('defense',tactic='flank')
        await self.action('formation',formation=[None]*5)
        # Newly trained after the deadline cannot retroactively defend an offline city.
        row=self.town();m=row['data']['military'];u=m['units'][0];u['ready_at']=self.now+25*HOUR;m['formation'][0]=u['id'];self.save(row)
        self.now+=25*HOUR;await self.view();siege=self.db._siege_row(s)
        self.assertEqual(siege['status'],'battle');self.assertEqual(len(siege['data']['snapshot']['fighters']['enemies']),1)
        self.assertEqual(siege['data']['snapshot']['fighters']['enemies'][0]['name'],'Городская стража')
        with self.assertRaises(ValueError):await self.action('formation',formation=[None]*5)
        expected=army.resolve_battle(siege['data']['snapshot'],siege['data']['seed']);self.assertTrue(expected['won'])
        before={actor:await self.db.franc_balance(-100,actor) for actor in (10,20)}
        profile=dict(self.db._arena_profile_locked(-100,20,True));self.now+=6*HOUR
        await self.view();await self.view();a=self.town(20);b=self.town()
        self.assertEqual(self.db._siege_row(s)['status'],'finished')
        self.assertIn((8,4),self.db._siege_land(a));self.assertNotIn((8,4),self.db._siege_land(b))
        for row in (a,b):
            self.assertTrue(connected((row['q'],row['r']),self.db._siege_land(row)))
            self.assertIsNone(row['data']['military']['siege_lock']);self.assertEqual(len(row['data']['military']['reports']),1)
            self.assertEqual(row['data']['military']['reports'][0]['loot'],{})
            self.assertEqual(await self.db.franc_balance(-100,row['owner']),before[row['owner']])
        self.assertTrue(a['data']['military']['reports'][0]['won']);self.assertFalse(b['data']['military']['reports'][0]['won'])
        self.assertEqual(b['data']['pvp']['shield_until'],self.now+72*HOUR)
        self.assertEqual(dict(self.db._arena_profile_locked(-100,20,True)),profile)

    async def test_capital_disconnection_caps_newbie_and_crosschat_rejected(self):
        await self.prepare();a=self.town(20);b=self.town()
        for q,r in ((6,5),(7,4)):
            with self.assertRaises(ValueError):await self.action('siege',actor=20,defender=b['id'],q=q,r=r,tactic='guard')
        original=deepcopy(a)
        for key,value in [('stage',1),('founded_at',self.now)]:
            a=deepcopy(original);a['data'][key]=value;self.save(a)
            with self.assertRaises(ValueError):await self.declare()
        self.save(original)
        for point in ((12,5),(12,4)):self.db.connection.execute('INSERT INTO kingdom_tiles VALUES(?,?,?,?)',(-100,*point,a['id']))
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError,'слота'):await self.declare()
        with self.assertRaises(ValueError):await self.action('siege',actor=20,chat=-200,defender=b['id'],q=8,r=4,tactic='guard')

    async def test_refund_on_changed_territory_and_failed_transaction(self):
        await self.prepare();money=await self.db.franc_balance(-100,20)
        with patch.object(self.db,'_kingdom_save_locked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):await self.declare()
        self.assertEqual(await self.db.franc_balance(-100,20),money)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM kingdom_sieges').fetchone()[0],0)
        s=(await self.declare())['siege'];await self.db.kingdom_siege_announced(s)
        self.db.connection.execute('DELETE FROM kingdom_tiles WHERE chat=-100 AND q=8 AND r=4');self.db.connection.commit()
        self.now+=25*HOUR;await self.view();self.assertEqual(self.db._siege_row(s)['status'],'cancelled')
        self.assertEqual(await self.db.franc_balance(-100,20),money)

    async def test_warning_delivery_retry_escaping_and_success(self):
        await self.prepare();row=self.town(20);row['name']='<fake>';self.save(row);s=(await self.declare())['siege']
        bot=SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))
        await publish_kingdom_notices(self.db,bot);await publish_kingdom_notices(self.db,bot)
        self.assertEqual(bot.send_message.await_count,1);self.assertEqual(self.db._siege_row(s)['status'],'notice')
        self.now+=300;bot.send_message.side_effect=None;await publish_kingdom_notices(self.db,bot)
        self.assertIn('&lt;fake&gt;',bot.send_message.call_args.args[1]);self.assertEqual(self.db._siege_row(s)['status'],'warning')
        await publish_kingdom_notices(self.db,bot);self.assertEqual(bot.send_message.await_count,2)


if __name__=='__main__':unittest.main()
