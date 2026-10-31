"""Closed municipal budgets, independent taxes and non-destructive debt."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_kingdom as towns
import arena_kingdom_finance as finance
from arena_kingdom_rules import DAY,HOUR
from arena_kingdom_war import new_unit


class FinanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=towns.KingdomTests.asyncSetUp
    asyncTearDown=towns.KingdomTests.asyncTearDown
    view=towns.KingdomTests.view
    action=towns.KingdomTests.action
    town=towns.KingdomTests.town
    budget=towns.KingdomTests.budget

    async def found(self,actor=10,chat=-100,q=7):
        return await self.action('found',actor,chat,q=q,r=5,name='Налоговый рай')

    async def setup_tax(self,rate='normal',funds=10000):
        await self.found();row=self.town();d=row['data']
        d.update(population=55,order=80,next_event=self.now+365*DAY,event=None)
        d['buildings']={key:1 for key in d['buildings']};d['resources'].update(food=1000,wood=500,stone=500)
        finance.credit(self.db,row,funds);self.db._kingdom_save_locked(row);self.db.connection.commit()
        await self.action('tax_activate');row=self.town();row['data']['finance']['rate']=rate
        self.db._kingdom_save_locked(row);self.db.connection.commit()

    async def test_old_and_new_towns_default_to_empty_budget_no_taxes(self):
        result=await self.found();self.assertEqual(result['view']['balance'],980000)
        b=next(t for t in result['view']['towns'] if t['own'])['budget']
        self.assertEqual(b['balance'],0);self.assertFalse(b['active'])
        self.now+=30*DAY;await self.view();self.assertEqual(self.budget(),0)
        self.assertEqual(await self.db.franc_balance(-100,10),980000)
        self.assertEqual(self.town()['data']['finance']['arrears'],0)
        with self.assertRaisesRegex(ValueError,'бюджете'):await self.action('build',building='barracks')

    async def test_manual_transfers_spending_and_nonce_conserve_both_balances(self):
        await self.found();row=self.town()
        body=dict(action='budget_deposit',town=row['id'],revision=row['revision'],confirm=True,nonce=uuid4().hex,amount=20000)
        await self.db.kingdom_action(-100,10,body);await self.db.kingdom_action(-100,10,body)
        self.assertEqual(self.budget(),20000);self.assertEqual(await self.db.franc_balance(-100,10),960000)
        await self.action('build',building='barracks')
        self.assertEqual(self.budget(),11000);self.assertEqual(await self.db.franc_balance(-100,10),960000)
        with self.assertRaises(ValueError):await self.action('budget_withdraw',amount=1000)
        self.assertEqual(self.budget(),11000);self.assertEqual(await self.db.franc_balance(-100,10),960000)
        for amount in (True,0,-100,1.5,'100',2000000001):
            with self.assertRaises(ValueError):await self.action('budget_deposit',amount=amount)

    async def test_failed_save_rolls_back_wallet_and_budget(self):
        await self.found();money=await self.db.franc_balance(-100,10)
        with patch.object(self.db,'_kingdom_save_locked',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):await self.action('budget_deposit',amount=10000)
        self.assertEqual(await self.db.franc_balance(-100,10),money);self.assertEqual(self.budget(),0)

    async def test_daily_normal_income_and_cost_exact_no_personal_rewards(self):
        await self.setup_tax();wallet=await self.db.franc_balance(-100,10);profile=dict(self.db._arena_profile_locked(-100,10,True))
        self.now+=DAY;await self.view();f=self.town()['data']['finance']
        self.assertEqual(f['collected'],880);self.assertEqual(f['paid'],230)
        self.assertEqual(self.budget(),10650);self.assertEqual(self.town()['data']['order'],80)
        self.assertEqual(await self.db.franc_balance(-100,10),wallet)
        self.assertEqual(dict(self.db._arena_profile_locked(-100,10,True)),profile)

    async def test_sampling_frequency_restart_and_offline_cap_cannot_mint_more(self):
        await self.setup_tax();self.now+=12*HOUR;await self.view();await self.db.close();await self.db.connect()
        for _ in range(12):self.now+=HOUR;await self.view()
        self.assertEqual(self.budget(),10650)
        for _ in range(10):await self.view()
        self.assertEqual(self.budget(),10650)
        self.now+=30*DAY;await self.view();self.assertEqual(self.budget(),11950)
        await self.view();self.assertEqual(self.budget(),11950)
        self.now+=DAY;await self.view();self.assertEqual(self.budget(),12600)

    async def test_taxes_order_and_growth_are_not_overridden_by_old_recovery(self):
        await self.setup_tax(rate='high');self.now+=DAY;await self.view()
        self.assertEqual(self.town()['data']['order'],70)
        self.assertEqual(self.budget(),11090)
        self.assertEqual(finance.collection(69),80);self.assertEqual(finance.collection(49),50)
        self.assertEqual(finance.collection(29),0)

    async def test_spectators_cannot_extend_an_absent_owners_income_window(self):
        await self.setup_tax()
        for _ in range(8):
            self.now+=DAY;await self.view(actor=20)
        self.assertEqual(self.budget(),11300)
        await self.view();self.assertEqual(self.budget(),11300)
        self.now+=DAY;await self.view();self.assertEqual(self.budget(),11950)

    async def test_growth_uses_tax_multiplier_and_holiday_recovery_caps_at_85(self):
        await self.setup_tax(rate='holiday');row=self.town();row['data']['population']=36
        self.db._kingdom_save_locked(row);self.db.connection.commit();self.now+=4*HOUR;await self.view()
        self.assertEqual(self.town()['data']['population'],37)
        self.now+=DAY;await self.view();self.assertEqual(self.town()['data']['order'],85)

    async def test_rate_change_cooldown_and_partial_hour_use_old_rate(self):
        await self.setup_tax()
        with self.assertRaises(ValueError):await self.action('tax_rate',rate='high')
        self.now+=DAY+HOUR//2;await self.action('tax_rate',rate='high')
        old=deepcopy(self.town()['data']['finance'])
        self.assertEqual(old['collected'],898) # 24.5h at 880/day, fractional carry retained
        self.now+=HOUR//2;await self.view();f=self.town()['data']['finance']
        self.assertEqual(f['collected'],925) # then 0.5h at 1320/day, not a full high-tax hour
        with self.assertRaises(ValueError):await self.action('tax_rate',rate='extortion')

    async def test_no_direct_withdrawal_and_foreign_town_access(self):
        await self.setup_tax();row=self.town();self.assertEqual(finance.view(self.db,row,self.now)['reserve'],230)
        wallet=await self.db.franc_balance(-100,10)
        with self.assertRaises(ValueError):await self.action('budget_withdraw',amount=10000)
        with self.assertRaises(ValueError):await self.action('budget_withdraw',amount=9770)
        with self.assertRaisesRegex(ValueError,'вывод'):finance.action(self.db,row,'budget_withdraw',dict(amount=1),self.now)
        self.assertEqual(self.budget(),10000);self.assertEqual(await self.db.franc_balance(-100,10),wallet)
        self.assertNotIn('withdrawable',finance.view(self.db,row,self.now))
        body=dict(action='budget_deposit',amount=1,town=row['id'],revision=row['revision'],confirm=True,nonce=uuid4().hex)
        with self.assertRaises(ValueError):await self.db.kingdom_action(-100,20,body)
        with self.assertRaises(ValueError):await self.db.kingdom_action(-200,10,body)

    async def test_multiple_tax_towns_are_independent_without_weekly_transfer(self):
        await self.setup_tax();await self.found(chat=-200)
        await self.action('tax_activate',chat=-200)
        self.assertTrue(finance.active(self.db,self.town()));self.assertTrue(finance.active(self.db,self.town(chat=-200)))
        self.assertEqual(self.town()['data']['order'],80)
        self.now+=DAY;await self.view();await self.view(chat=-200)
        self.assertEqual(self.budget(),10650)
        self.assertGreater(self.town(chat=-200)['data']['finance']['collected'],0)
        await self.action('tax_rate',rate='high')
        self.assertEqual(self.town(chat=-200)['data']['finance']['rate'],'normal')
        self.assertTrue(finance.active(self.db,self.town(chat=-200)))

    async def test_prototype_tax_account_migrates_without_losing_budget_or_debt(self):
        await self.found();row=self.town()
        finance.credit(self.db,row,1234);row['data']['finance']['arrears']=57
        self.db._kingdom_save_locked(row)
        self.db.connection.execute('CREATE TABLE kingdom_tax_accounts(owner INTEGER PRIMARY KEY,town TEXT UNIQUE,switch_at INTEGER,active_until INTEGER)')
        self.db.connection.execute('INSERT INTO kingdom_tax_accounts VALUES(?,?,?,?)',(10,row['id'],self.now+7*DAY,self.now+2*DAY))
        self.db.connection.commit();await self.db.close();await self.db.connect()
        self.assertTrue(finance.active(self.db,self.town()))
        self.assertEqual(finance.deadline(self.db,self.town()),self.now+2*DAY)
        self.assertEqual(self.budget(),1234);self.assertEqual(self.town()['data']['finance']['arrears'],57)
        await self.found(chat=-200);await self.action('tax_activate',chat=-200)
        self.assertTrue(finance.active(self.db,self.town()));self.assertTrue(finance.active(self.db,self.town(chat=-200)))
        await self.db.close();await self.db.connect()
        self.assertEqual(self.budget(),1234);self.assertEqual(self.town()['data']['finance']['arrears'],57)

    async def test_debt_caps_economy_and_manual_payment_never_seize_or_delete(self):
        await self.setup_tax(rate='holiday',funds=0);wallet=await self.db.franc_balance(-100,10)
        before_buildings=deepcopy(self.town()['data']['buildings']);self.now+=2*DAY;await self.view()
        f=self.town()['data']['finance'];self.assertEqual(f['arrears'],460);self.assertTrue(f['economy'])
        for action,fields in [('recruit',dict(unit='militia')),('march',dict(target='road_camp',tactic='guard')),('reform',dict(field='policy',choice='trade'))]:
            with self.assertRaisesRegex(ValueError,'задолженность'):await self.action(action,**fields)
        self.now+=DAY;await self.view();self.assertEqual(self.town()['data']['finance']['arrears'],460)
        self.assertEqual(await self.db.franc_balance(-100,10),wallet);self.assertEqual(self.town()['data']['buildings'],before_buildings)
        with self.assertRaises(ValueError):await self.action('budget_withdraw',amount=1)
        await self.action('budget_deposit',amount=600)
        self.assertEqual(self.town()['data']['finance']['arrears'],0);self.assertEqual(self.budget(),140)

    async def test_strike_forces_holiday_for_a_day_without_destroying_population(self):
        await self.setup_tax(rate='extortion');row=self.town();row['data']['order']=29
        self.db._kingdom_save_locked(row);self.db.connection.commit();self.now+=HOUR;await self.view()
        row=self.town();f=row['data']['finance'];self.assertEqual(f['rate'],'holiday');self.assertGreater(f['strike_until'],self.now)
        self.assertEqual(f['collected'],0);self.assertEqual(row['data']['population'],55)
        with self.assertRaises(ValueError):await self.action('tax_rate',rate='high')

    async def test_smaller_army_does_not_write_off_existing_maintenance_debt(self):
        await self.setup_tax(rate='holiday',funds=0);row=self.town()
        row['data']['military']['units']=[new_unit('paladins',self.now,ready=True)]
        self.db._kingdom_save_locked(row);self.db.connection.commit();self.now+=2*DAY;await self.view()
        debt=self.town()['data']['finance']['arrears'];self.assertEqual(debt,1560)
        unit=self.town()['data']['military']['units'][0]['id'];await self.action('dismiss',unit=unit)
        self.now+=HOUR;await self.view();self.assertEqual(self.town()['data']['finance']['arrears'],debt)

    async def test_army_casualties_change_maintenance_at_return_time(self):
        await self.setup_tax();row=self.town();d=row['data'];d['stage']=2
        unit=new_unit('militia',self.now,ready=True);d['military']['units']=[unit];d['military']['formation']=[unit['id'],None,None,None,None]
        self.db._kingdom_save_locked(row);self.db.connection.commit()
        await self.action('march',target='bone_foundry',tactic='assault')
        self.now+=DAY;await self.view();d=self.town()['data']
        self.assertEqual(d['military']['units'],[])
        self.assertEqual(d['finance']['paid'],380) # 350 civilian + 6h * 120/day for the lost unit
        self.assertEqual(self.budget(),11380)

    async def test_quoted_upkeep_matches_approved_city_and_army_examples(self):
        await self.setup_tax();row=self.town();d=row['data'];d.update(stage=2,population=100)
        d['buildings'].update(hall=3,farm=3,sawmill=2,quarry=2,barracks=2,warehouse=2)
        self.assertEqual(finance.quote(d,self.now)['net'],2480)
        d['military']['units']=[new_unit(k,self.now,ready=True) for k in ('paladins','shields','archers','priests','agents')]
        self.assertEqual(finance.upkeep(d)['army'],1920);self.assertEqual(finance.quote(d,self.now)['net'],560)
        d['stage']=3;d['population']=130;d['buildings']={k:4 for k in d['buildings']}
        self.assertEqual(finance.quote(d,self.now)['net'],2740)

    async def test_old_wallet_escrow_refunds_wallet_new_budget_escrow_refunds_budget(self):
        await self.found();row=self.town()
        self.db._forge_spend_francs_locked(-100,10,5000)
        row['data']['event']=dict(id='legacy',kind='bandits',deadline=self.now-1,escrow=5000,battle=None,attempted=[])
        self.db._kingdom_save_locked(row);self.db.connection.commit();await self.view()
        self.assertEqual(await self.db.franc_balance(-100,10),980000);self.assertEqual(self.budget(),0)


if __name__=='__main__':unittest.main()
