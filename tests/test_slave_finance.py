"""Fictional economy tests only: isolated temporary DB and fake Telegram members."""
import asyncio
import sqlite3
import unittest
from unittest.mock import AsyncMock

from tests import test_holdings as fixtures
from slave_finance import NPC_ID, LOAN_SECONDS, BUYOUT_DECAY_SECONDS
from handlers.slave_finance import sweep_finance
from database import Database


class Roll:
    def __init__(self,n):self.n=n
    def randrange(self,n):return self.n
    def choice(self,values):return values[0]


class FinanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.HoldingsTests.asyncSetUp
    asyncTearDown=fixtures.HoldingsTests.asyncTearDown
    post=fixtures.HoldingsTests.post

    async def call(self,kind,actor=10,chat=-100,nonce=None,rng=None,**body):
        self.seq=getattr(self,'seq',0)+1
        return await self.db.finance_action(chat,actor,dict(action='finance_'+kind,confirm=True,
            nonce=nonce or str(self.seq).zfill(32),**body),rng)

    async def quote(self,worker=100,actor=10,chat=-100):
        return await self.call('quote',actor=actor,chat=chat,worker=worker)

    def loan(self,actor=20):return self.db._finance_loan_locked(actor)

    async def enslave_debtor(self,actor=20):
        await self.call('borrow',actor=actor,amount=2000)
        self.clock+=LOAN_SECONDS-3600
        notices=await self.db.finance_sweep()
        for n in notices:await self.db.finance_notice_sent(n['loan_id'],n['kind'])
        self.clock+=3600
        await self.db.finance_sweep()
        self.assertEqual(self.loan(actor)['status'],'enslaved')
        return self.loan(actor)

    async def test_hidden_value_and_appraisal_and_no_rarity_leak(self):
        self.db.connection.execute("UPDATE slave_identities SET rarity='legendary' WHERE user_id=100")
        self.db.connection.commit()
        q=await self.quote()
        self.assertEqual((q['quote']['value'],q['quote']['payout'],q['quote']['npc_price']),(100,500,120))
        self.assertNotIn('identity',q['quote'])
        v=await self.db.holdings_view(-100,10)
        await self.db.trader_action(-100,10,dict(action='trader_appraise',confirm=True,worker=100,nonce='a'*32,revision=v['revision']))
        self.assertEqual((await self.quote())['quote']['value'],1600)
        with self.assertRaises(ValueError):await self.call('wager',offer=q['offer'],rng=Roll(0))

    async def test_17_percent_boundary_win_preserves_worker_and_credits_fivefold(self):
        q=await self.quote();before=await self.db.franc_balance(-100,10)
        r=await self.call('wager',offer=q['offer'],rng=Roll(16),nonce='b'*32)
        self.assertTrue(r['won']);self.assertEqual(r['payout'],500)
        self.assertEqual(await self.db.franc_balance(-100,10),before+500)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)
        self.assertEqual(r,await self.call('wager',offer=q['offer'],rng=Roll(99),nonce='b'*32))
        with self.assertRaises(ValueError):await self.call('wager',offer=(await self.quote(101))['offer'],rng=Roll(0))

    async def test_loss_npc_custody_job_removed_and_paid_purchase(self):
        await self.db.enterprise_create(-100,10,'mine')
        site=await self.db.get_business(-100,10,business_type='mine')
        await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        q=await self.quote();r=await self.call('wager',offer=q['offer'],rng=Roll(17))
        self.assertFalse(r['won'])
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],NPC_ID)
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM business_workers WHERE chat_id=-100 AND worker_id=100').fetchone())
        self.assertEqual(await self.db.force_enslave(-100,100,20),'protected_slave')
        self.assertFalse(await self.db.release_slave(-100,NPC_ID,100))
        self.assertEqual(await self.db.buyout_slave(-100,NPC_ID,100),'npc_buyout')
        with self.assertRaises(sqlite3.IntegrityError),self.db.connection:
            self.db.connection.execute('DELETE FROM ownership WHERE chat_id=-100 AND slave_id=100')
        before=await self.db.franc_balance(-100,10)
        await self.call('buy',worker=100,price=120)
        self.assertEqual(await self.db.franc_balance(-100,10),before-120)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)

    async def test_stale_foreign_expired_and_away_quotes(self):
        q=await self.quote()
        with self.assertRaises(ValueError):await self.call('wager',actor=20,offer=q['offer'])
        with self.assertRaises(ValueError):await self.call('wager',chat=-200,offer=q['offer'])
        await self.db.transfer_slave(-100,10,100,20)
        with self.assertRaises(ValueError):await self.call('wager',offer=q['offer'])
        q=await self.quote(101);self.clock+=301
        with self.assertRaises(ValueError):await self.call('wager',offer=q['offer'])
        v=await self.db.holdings_view(-100,10)
        await self.db.trader_action(-100,10,dict(action='trader_list',worker=102,price=200,nonce='l'*32,confirm=True,revision=v['revision']))
        with self.assertRaises(ValueError):await self.quote(102)
        q=await self.db.expedition_quote(-100,10,'outskirts',[103])
        await self.db.expedition_start(-100,10,'outskirts',[103],q['revision'],'e'*32)
        with self.assertRaises(ValueError):await self.quote(103)

    async def test_account_limit_fixed_fee_free_transfer_wager_and_global_single_debt(self):
        f=(await self.db.holdings_view(-100,20))['trader']['finance']
        self.assertEqual(f['limit'],2000)
        await self.call('borrow',actor=20,amount=2000)
        self.assertEqual(self.loan()['total'],2300)
        self.assertEqual(await self.db.transfer_francs(-100,20,10,100),'transferred')
        r=await self.db.deposit_francs(-100,20,100,-100,77,Roll(0))
        self.assertEqual(r['payout'],500)
        with self.assertRaises(ValueError):await self.call('borrow',actor=20,chat=-200,amount=1)
        self.assertEqual((await self.db.holdings_view(-100,10))['trader']['finance']['limit'],40200)

    async def test_repayment_partial_and_receipts_restart(self):
        await self.call('borrow',actor=20,amount=1000,nonce='c'*32)
        await self.db.close();await self.db.connect()
        await self.call('borrow',actor=20,amount=1000,nonce='c'*32)
        self.assertEqual(await self.db.franc_balance(-100,20),1000)
        ident=self.loan()['id']
        await self.call('repay',actor=20,loan=ident,amount=500)
        self.assertEqual(self.loan()['remaining'],650)
        await self.db.credit_francs(-200,20,650)
        await self.call('repay',actor=20,chat=-200,loan=ident,amount=650)
        self.assertIsNone(self.loan())
        with self.assertRaises(ValueError):await self.call('repay',actor=20,loan=ident,amount=1)

    async def test_warning_required_late_delivery_grace_and_passive_offline(self):
        await self.call('borrow',actor=20,amount=2000)
        self.clock+=LOAN_SECONDS+200
        notices=await self.db.finance_sweep()
        self.assertEqual(self.loan()['status'],'active')
        self.clock+=10000;await self.db.finance_sweep()
        self.assertEqual(self.loan()['status'],'active')
        await self.db.finance_notice_sent(notices[0]['loan_id'],notices[0]['kind'])
        self.clock+=3599;await self.db.finance_sweep()
        self.assertEqual(self.loan()['status'],'active')
        self.clock+=1;await self.db.finance_sweep()
        self.assertEqual(self.loan()['status'],'enslaved')
        self.clock+=3600*2+100;await self.db.finance_sweep()
        self.assertEqual(self.loan()['remaining'],2254)
        await self.db.finance_sweep();self.assertEqual(self.loan()['remaining'],2254)
        self.clock+=3600*100;await self.db.finance_sweep()
        self.assertIsNone(self.loan());self.assertIsNone(await self.db.get_owner(-100,20))

    async def test_all_wallet_credits_repay_from_every_chat_and_surplus_becomes_spendable(self):
        loan=await self.enslave_debtor()
        before=await self.db.franc_balance(-100,20)
        await self.db.credit_francs(-100,20,200)
        self.assertEqual(await self.db.franc_balance(-100,20),before)
        self.assertEqual(self.loan()['remaining'],2100)
        self.assertEqual(await self.db.transfer_francs(-200,10,20,100),'transferred')
        self.assertEqual(self.loan()['remaining'],2000)
        with self.db.connection:
            self.db.connection.execute('INSERT INTO franc_balances VALUES(-300,20,500,?)',(self.clock,))
        self.assertEqual(self.loan()['remaining'],1500)
        self.assertEqual(await self.db.franc_balance(-300,20),0)
        await self.db.credit_francs(-100,20,1600)
        self.assertIsNone(self.loan());self.assertIsNone(await self.db.get_owner(-100,20))
        self.assertEqual(await self.db.franc_balance(-100,20),before+100)

    async def test_collection_takes_assets_not_player_and_refunds_excess(self):
        await self.call('borrow',amount=100)
        self.clock+=LOAN_SECONDS-3600
        for n in await self.db.finance_sweep():await self.db.finance_notice_sent(n['loan_id'],n['kind'])
        self.clock+=3600
        before=await self.db.franc_balance(-100,10)
        await self.db.finance_sweep()
        self.assertIsNone(self.loan(10));self.assertIsNone(await self.db.get_owner(-100,10))
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM npc_workers').fetchone()[0],2)
        self.assertEqual(await self.db.franc_balance(-100,10),before+85)

    async def test_purchase_debtor_closes_loan_and_buyout_decays_no_100_franc_bypass(self):
        await self.enslave_debtor()
        price=2760
        await self.call('buy',worker=20,price=price)
        self.assertIsNone(self.loan())
        self.assertEqual((await self.db.get_owner(-100,20))['owner_id'],10)
        self.assertEqual(await self.db.slave_buyout_cost(-100,20,10),price)
        self.db.connection.execute('UPDATE franc_balances SET balance=100 WHERE chat_id=-100 AND user_id=20');self.db.connection.commit()
        self.assertEqual(await self.db.buyout_slave(-100,10,20),'insufficient')
        self.clock+=BUYOUT_DECAY_SECONDS//2
        self.assertEqual(await self.db.slave_buyout_cost(-100,20,10),1430)
        self.clock+=BUYOUT_DECAY_SECONDS//2
        self.assertEqual(await self.db.slave_buyout_cost(-100,20,10),100)
        self.assertEqual(await self.db.buyout_slave(-100,10,20),'released')

    async def test_double_purchase_and_double_loan_are_atomic(self):
        r=await asyncio.gather(self.call('borrow',actor=20,amount=100),self.call('borrow',actor=20,amount=100),return_exceptions=True)
        self.assertEqual(sum(isinstance(x,dict) for x in r),1)
        q=await self.quote();await self.call('wager',offer=q['offer'],rng=Roll(99))
        r=await asyncio.gather(self.call('buy',worker=100,price=120),self.call('buy',worker=100,price=120),return_exceptions=True)
        self.assertEqual(sum(isinstance(x,dict) for x in r),1)

    async def test_debtor_price_cannot_be_reset_by_transfer_and_old_warnings_are_not_sent(self):
        await self.enslave_debtor()
        await self.call('buy',worker=20,price=2760)
        await self.db.upsert_user(-100,30,'30','Новый владелец')
        self.assertEqual(await self.db.transfer_slave(-100,10,20,30),'transferred')
        self.assertEqual(await self.db.slave_buyout_cost(-100,20,30),2760)
        self.assertFalse(any(n['kind'].startswith('warn_') for n in await self.db.finance_sweep()))

    async def test_deposit_gross_payout_is_withheld_and_receipt_balance_is_real(self):
        await self.enslave_debtor()
        before=await self.db.franc_balance(-100,20)
        r=await self.db.deposit_francs(-100,20,100,-100,777,Roll(0))
        self.assertEqual(self.loan()['remaining'],1800)
        self.assertEqual(await self.db.franc_balance(-100,20),before-100)
        self.assertEqual(r['balance_after'],before-100)

    async def test_self_buyout_and_existing_third_party_ownership_are_safe(self):
        await self.db.credit_francs(-100,20,1000)
        await self.enslave_debtor()
        await self.call('buy',actor=20,worker=20,price=2760)
        self.assertIsNone(await self.db.get_owner(-100,20));self.assertIsNone(self.loan())
        self.assertEqual(await self.db.franc_balance(-100,20),240)

    async def test_http_auth_bad_numbers_and_foreign_worker(self):
        path='/api/holdings/-100'
        self.assertEqual((await self.client.post(path,json=dict(action='finance_borrow',amount=100))).status,400)
        for amount in (True,0,-1,'100',1.5,10**25):
            with self.assertRaises(ValueError):await self.call('borrow',actor=20,amount=amount)
        r=await self.post(dict(action='finance_quote',worker=100),user=20)
        self.assertEqual(r.status,400)
        r=await self.post(dict(action='finance_borrow',amount=100,confirm=True,nonce='h'*32),user=20)
        self.assertEqual(r.status,200,await r.text())
        self.assertEqual((await r.json())['holdings']['trader']['finance']['loan']['remaining'],115)

    async def test_backup_restores_custody_and_income_interception(self):
        await self.enslave_debtor()
        path=self.path.parent/'finance-backup.sqlite3'
        await self.db.backup_to(path)
        restored=Database(path);await restored.connect()
        try:
            self.assertEqual((await restored.get_owner(-100,20))['owner_id'],NPC_ID)
            before=await restored.franc_balance(-100,20)
            await restored.credit_francs(-100,20,50)
            self.assertEqual(await restored.franc_balance(-100,20),before)
            self.assertEqual(restored._finance_loan_locked(20)['remaining'],2250)
            self.assertEqual(self.loan()['remaining'],2300)
        finally:await restored.close()

    async def test_warning_delivery_failure_retry_and_chat_fallback(self):
        await self.call('borrow',actor=20,amount=2000)
        self.clock+=LOAN_SECONDS+1
        self.bot.send_message=AsyncMock(side_effect=asyncio.TimeoutError)
        await sweep_finance(self.db,self.bot)
        self.assertIsNone(self.loan()['warned_at'])
        self.assertEqual(self.bot.send_message.await_count,2)
        self.clock+=301
        self.bot.send_message=AsyncMock(side_effect=[asyncio.TimeoutError,None])
        await sweep_finance(self.db,self.bot)
        self.assertEqual(self.loan()['warned_at'],self.clock)
        self.assertEqual(self.bot.send_message.await_args.args[0],-100)
        self.clock+=3599;await self.db.finance_sweep()
        self.assertEqual(self.loan()['status'],'active')
        self.clock+=1;await self.db.finance_sweep()
        self.assertEqual(self.loan()['status'],'enslaved')

    async def test_http_quote_settlement_checks_worker_again_and_replays_once(self):
        for offer in (None,{},[],123):
            r=await self.post(dict(action='finance_wager',offer=offer,confirm=True,nonce='bad'*8))
            self.assertEqual(r.status,400)
        r=await self.post(dict(action='finance_quote',worker=100))
        self.assertEqual(r.status,200)
        quote=await r.json()
        body=dict(action='finance_wager',offer=quote['offer'],confirm=True,nonce='w'*32)
        self.bot.get_chat_member.reset_mock()
        r=await self.post(body)
        self.assertEqual(r.status,200,await r.text())
        self.assertIn((-100,100),[c.args for c in self.bot.get_chat_member.await_args_list])
        result=await r.json()
        r=await self.post(body)
        self.assertEqual(r.status,200,await r.text())
        replay=await r.json()
        self.assertEqual(result['notice'],replay['notice'])
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM npc_finance_receipts WHERE nonce=?',('w'*32,)).fetchone()[0],1)


if __name__=='__main__':unittest.main()
