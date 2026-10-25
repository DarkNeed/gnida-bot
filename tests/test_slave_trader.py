import asyncio
import unittest
from unittest.mock import patch

from tests import test_holdings as holdings_tests


class TraderTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=holdings_tests.HoldingsTests.asyncSetUp
    asyncTearDown=holdings_tests.HoldingsTests.asyncTearDown
    view=holdings_tests.HoldingsTests.view
    site=holdings_tests.HoldingsTests.site
    post=holdings_tests.HoldingsTests.post

    async def call(self, action, actor=10, chat=-100, nonce=None, **kwargs):
        self.counter=getattr(self,'counter',0)+1
        v=await self.db.holdings_view(chat,actor)
        body=dict(action='trader_'+action,confirm=True,nonce=nonce or str(self.counter).zfill(32),revision=v['revision'],**kwargs)
        return await self.db.trader_action(chat,actor,body)

    async def listing(self, worker=100, price=201):
        await self.call('list',worker=worker,price=price)
        return (await self.view())['trader']['listings'][0]['id']

    async def mature(self):
        self.clock+=86400
        for chat in (-100,-200):
            for user in range(100,112):await self.db.upsert_user(chat,user,'user'+str(user),'Участник '+str(user))

    async def test_appraisal_exact_fee_read_free_no_arena_writes_and_replay(self):
        before=await self.db.franc_balance(-100,10)
        v=await self.view();b=dict(action='trader_appraise',worker=100,confirm=True,revision=v['revision'],nonce='a'*32)
        r=await self.db.trader_action(-100,10,b)
        self.assertEqual(await self.db.franc_balance(-100,10),before-50)
        self.assertEqual(r,await self.db.trader_action(-100,10,b))
        await self.call('appraise',worker=100)
        self.assertEqual(await self.db.franc_balance(-100,10),before-50)
        await self.call('appraise',worker=100,refresh=True)
        self.assertEqual(await self.db.franc_balance(-100,10),before-100)
        self.assertEqual(len((await self.view())['trader']['reports']),1)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM personal_profiles').fetchone()[0],0)
        self.assertEqual(len(r['report']['rates']),6)
        await self.db.close();await self.db.connect()
        self.assertEqual(r,await self.db.trader_action(-100,10,b))

    async def test_bad_appraisals_never_charge_and_cache_cannot_follow_ownership(self):
        for worker in (True,'100',20,999):
            with self.assertRaises(ValueError):await self.call('appraise',worker=worker)
        await self.call('appraise',worker=100)
        await self.db.force_enslave(-100,100,20)
        self.clock+=1;await self.db.force_enslave(-100,100,10)
        self.assertEqual((await self.view())['trader']['reports'],[])
        self.db.connection.execute('UPDATE franc_balances SET balance=49 WHERE chat_id=-100 AND user_id=10');self.db.connection.commit()
        with self.assertRaises(ValueError):await self.call('appraise',worker=100)
        self.assertEqual(await self.db.franc_balance(-100,10),49)

    async def test_listing_keeps_job_blocks_trip_expires_and_cancels_on_transfer(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        listing=await self.listing()
        self.assertEqual(len((await self.db.enterprise_view(-100,site['id']))['workers']),1)
        with self.assertRaises(ValueError):await self.db.expedition_quote(-100,10,'outskirts',[100])
        with self.assertRaises(ValueError):await self.listing()
        self.clock+=86400
        self.assertEqual((await self.view())['trader']['listings'],[])
        self.assertIn('revision',await self.db.expedition_quote(-100,10,'outskirts',[100]))
        await self.listing();await self.db.force_enslave(-100,100,20)
        self.clock+=1;await self.db.force_enslave(-100,100,10)
        self.assertEqual((await self.view())['trader']['listings'],[])
        with self.assertRaises(ValueError):await self.call('cancel',listing=listing)

    async def test_sale_fee_settlement_job_cleanup_and_idempotence(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        listing=await self.listing();await self.db.credit_francs(-100,20,500)
        before=await self.db.franc_balance(-100,10);self.clock+=3600
        v=await self.db.holdings_view(-100,20)
        b=dict(action='trader_buy',listing=listing,price=201,confirm=True,nonce='b'*32,revision=v['revision'])
        result=await self.db.trader_action(-100,20,b)
        self.assertEqual(await self.db.franc_balance(-100,10),before+3+180)
        self.assertEqual(await self.db.franc_balance(-100,20),299)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],20)
        self.assertEqual((await self.view())['sites'][0]['workers'],[])
        self.assertEqual(self.db.connection.execute('SELECT status FROM slave_trader_listings WHERE id=?',(listing,)).fetchone()[0],'sold')
        self.assertEqual(result,await self.db.trader_action(-100,20,b))
        self.assertEqual(await self.db.franc_balance(-100,20),299)

    async def test_purchase_rejections_and_race(self):
        listing=await self.listing();await self.db.credit_francs(-100,20,500)
        with self.assertRaises(ValueError):await self.call('buy',listing=listing,price=201)
        with self.assertRaises(ValueError):await self.call('buy',actor=20,listing=listing,price=200)
        with self.assertRaises(ValueError):await self.call('buy',actor=20,listing=listing,price=201,chat=-200)
        await self.db.force_enslave(-100,20,10)
        with self.assertRaises(ValueError):await self.call('buy',actor=20,listing=listing,price=201)
        self.assertEqual(await self.db.franc_balance(-100,20),500)
        self.db.connection.execute('DELETE FROM ownership WHERE chat_id=-100 AND slave_id=20');self.db.connection.commit()
        results=await asyncio.gather(self.call('buy',actor=20,listing=listing,price=201),self.call('buy',actor=20,listing=listing,price=201),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(await self.db.franc_balance(-100,20),299)

    async def test_listing_limit_global_cancel_and_invalid_inputs(self):
        ids=[]
        for worker in range(100,105):ids.append(await self.listing(worker))
        with self.assertRaises(ValueError):await self.call('list',chat=-200,worker=105,price=100)
        with self.assertRaises(ValueError):await self.call('cancel',actor=20,listing=ids[0])
        await self.call('cancel',listing=ids[0])
        for price in (True,1,100001,12.5,'100'):
            with self.assertRaises(ValueError):await self.call('list',worker=105,price=price)
        await self.listing(105)

    async def test_order_frees_chat_only_has_global_daily_limit_and_worker_cooldown(self):
        with self.assertRaises(ValueError):await self.call('order',order='active',users=[100])
        await self.mature();site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        before=await self.db.franc_balance(-100,10)
        r=await self.call('order',order='active',users=[100])
        self.assertEqual(r['francs'],70)
        self.assertEqual(await self.db.franc_balance(-100,10),before+70)
        self.assertIsNone(await self.db.get_owner(-100,100))
        self.assertIsNotNone(await self.db.get_owner(-200,100))
        self.assertEqual((await self.view())['sites'][0]['workers'],[])
        with self.assertRaises(ValueError):await self.call('order',chat=-200,order='active',users=[101])
        self.clock+=86400
        with self.assertRaises(ValueError):await self.call('order',chat=-200,order='active',users=[100])
        await self.db.force_enslave(-200,100,20);self.clock+=86400
        with self.assertRaises(ValueError):await self.call('order',actor=20,chat=-200,order='active',users=[100])
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM personal_profiles').fetchone()[0],0)

    async def test_order_validates_all_members_atomic_payout_tax_and_rollback(self):
        await self.mature()
        for users in ([100,100],[100,20],[True,101],[100]):
            with self.assertRaises(ValueError):await self.call('order',order='crew',users=users)
        with self.assertRaises(ValueError):await self.call('order',order='veteran',users=[100])
        with patch.object(self.db,'_credit_business_income_locked',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError):await self.call('order',order='crew',users=[100,101])
        self.assertIsNotNone(await self.db.get_owner(-100,100));self.assertIsNotNone(await self.db.get_owner(-100,101))
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM slave_trader_deliveries').fetchone()[0],0)
        from slave_trader import day
        self.db._credit_business_income_locked(-100,10,day(),300);self.db.connection.commit()
        r=await self.call('order',order='crew',users=[100,101])
        self.assertEqual((r['francs'],r['tax']),(136,24))
        self.assertIsNone(await self.db.get_owner(-100,101))

    async def test_nonce_strict_confirmation_stale_and_http_membership(self):
        v=await self.view()
        b=dict(action='trader_appraise',worker=100,confirm=True,revision=v['revision'],nonce='q'*32)
        for field,value in (('confirm',False),('nonce','bad'),('revision','stale'),('worker',True)):
            response=await self.post(dict(b,**{field:value}))
            self.assertEqual(response.status,400,await response.text())
        self.bot.get_chat_member.return_value.user.is_bot=True
        self.assertEqual((await self.post(b)).status,400)
        self.bot.get_chat_member.return_value.user.is_bot=False
        self.bot.get_chat_member.side_effect=lambda c,u:type('M',(),dict(status='left' if u==100 else 'member'))()
        self.assertEqual((await self.post(b)).status,400)
        self.bot.get_chat_member.side_effect=None
        response=await self.post(b);self.assertEqual(response.status,200,await response.text())
        payload=await response.json();self.assertEqual(payload['holdings']['trader']['appraisal_price'],50)
        with self.assertRaises(ValueError):await self.db.trader_action(-100,10,dict(b,worker=101))
        self.assertEqual(await self.db.franc_balance(-100,10),9950)

    async def test_failed_credit_rolls_back_purchase_and_listing(self):
        listing=await self.listing();await self.db.credit_francs(-100,20,500)
        before=await self.db.franc_balance(-100,10)
        with patch.object(self.db,'_add_francs_locked',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError):await self.call('buy',actor=20,listing=listing,price=201)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)
        self.assertEqual(await self.db.franc_balance(-100,20),500)
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        self.assertEqual((await self.view())['trader']['listings'][0]['id'],listing)

    async def test_missing_and_travelling_workers_cannot_be_sold_or_delivered(self):
        await self.mature()
        q=await self.db.expedition_quote(-100,10,'outskirts',[100])
        await self.db.expedition_start(-100,10,'outskirts',[100],q['revision'],'x'*32)
        for action,kw in (('list',dict(worker=100,price=100)),('order',dict(order='active',users=[100]))):
            with self.assertRaises(ValueError):await self.call(action,**kw)
        self.db.connection.execute("INSERT INTO slave_recovery_events(chat_id,owner_id,slave_id,kind,created_at,pattern_json) VALUES(-100,10,101,'escaped',?,'[]')",(self.clock,))
        self.db.connection.commit()
        with self.assertRaises(ValueError):await self.call('list',worker=101,price=100)

    async def test_http_purchase_membership_and_insufficient_funds(self):
        listing=await self.listing()
        with self.assertRaises(ValueError):await self.call('buy',actor=20,listing=listing,price=201)
        await self.db.credit_francs(-100,20,500)
        body=dict(action='trader_buy',listing=listing,price=201,confirm=True,nonce='h'*32)
        self.bot.get_chat_member.side_effect=lambda c,u:type('M',(),dict(status='left' if u==10 else 'member'))()
        self.assertEqual((await self.post(body,user=20)).status,400)
        self.assertEqual(await self.db.franc_balance(-100,20),500)
        self.bot.get_chat_member.side_effect=None
        response=await self.post(body,user=20)
        self.assertEqual(response.status,200,await response.text())

    async def test_order_receipt_survives_restart_without_second_reward(self):
        await self.mature();v=await self.view()
        body=dict(action='trader_order',order='crew',users=[100,101],confirm=True,nonce='r'*32,revision=v['revision'])
        result=await self.db.trader_action(-100,10,body)
        balance=await self.db.franc_balance(-100,10)
        await self.db.close();await self.db.connect()
        self.assertEqual(await self.db.trader_action(-100,10,body),result)
        self.assertEqual(await self.db.franc_balance(-100,10),balance)


if __name__=='__main__':unittest.main()
