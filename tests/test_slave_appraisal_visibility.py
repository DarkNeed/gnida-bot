import json
import unittest

from tests import test_holdings as fixtures


class AppraisalVisibilityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.HoldingsTests.asyncSetUp
    asyncTearDown=fixtures.HoldingsTests.asyncTearDown
    view=fixtures.HoldingsTests.view
    post=fixtures.HoldingsTests.post

    def assertHidden(self,identity):
        self.assertFalse(identity['appraised'])
        for field in ('rarity','rarity_name','color','income_bonus','expedition_bonus'):
            self.assertNotIn(field,identity)
        self.assertIn('trait_name',identity)

    async def action(self,kind,actor=10,chat=-100,nonce='a'*32,**fields):
        view=await self.db.holdings_view(chat,actor)
        return await self.db.trader_action(chat,actor,dict(action='trader_'+kind,confirm=True,nonce=nonce,revision=view['revision'],**fields))

    async def test_roster_and_api_hide_rarity_until_paid_assessment(self):
        before=await self.db.franc_balance(-100,10)
        for p in (await self.view())['people']:
            self.assertHidden(p['identity']);self.assertNotIn('base_power',p)
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        view=await self.view()
        response=await self.post(dict(action='trader_appraise',worker=100,confirm=True,nonce='p'*32,revision=view['revision']))
        self.assertEqual(response.status,200,await response.text())
        result=await response.json()
        self.assertIn('rarity',result['report']['identity'])
        known=next(p for p in result['holdings']['people'] if p['user_id']==100)
        self.assertTrue(known['identity']['appraised'])
        self.assertIn('rarity',known['identity'])
        self.assertEqual(await self.db.franc_balance(-100,10),before-50)
        for p in result['holdings']['people']:
            if p['user_id']!=100:self.assertHidden(p['identity'])

    async def test_insufficient_payment_and_foreign_ownership_cannot_reveal(self):
        self.db.connection.execute('UPDATE franc_balances SET balance=49 WHERE chat_id=-100 AND user_id=10');self.db.connection.commit()
        with self.assertRaises(ValueError):await self.action('appraise',worker=100)
        self.assertHidden(next(p for p in (await self.view())['people'] if p['user_id']==100)['identity'])
        with self.assertRaises(ValueError):await self.action('appraise',actor=20,worker=100)
        self.assertEqual(await self.db.franc_balance(-100,10),49)

    async def test_assessment_persists_but_is_bound_to_owner_chat_and_acquisition(self):
        await self.action('appraise',worker=100)
        await self.db.close();await self.db.connect()
        self.assertTrue(next(p for p in (await self.view())['people'] if p['user_id']==100)['identity']['appraised'])
        other=await self.db.holdings_view(-200,10)
        self.assertHidden(next(p for p in other['people'] if p['user_id']==100)['identity'])
        original=self.db._slave_identity_locked(100)
        await self.db.force_enslave(-100,100,20)
        owner_view=await self.db.holdings_view(-100,20)
        self.assertHidden(owner_view['people'][0]['identity'])
        self.clock+=1;await self.db.force_enslave(-100,100,10)
        self.assertHidden(next(p for p in (await self.view())['people'] if p['user_id']==100)['identity'])
        self.assertEqual(self.db._slave_identity_locked(100),original)

    async def test_market_discloses_only_seller_appraised_lots(self):
        await self.action('list',worker=100,price=100)
        public=await self.db.holdings_view(-100,20)
        listing=public['trader']['listings'][0]
        self.assertHidden(listing['identity'])
        await self.action('appraise',worker=100,nonce='p'*32)
        public=await self.db.holdings_view(-100,20)
        self.assertTrue(public['trader']['listings'][0]['identity']['appraised'])
        await self.db.credit_francs(-100,20,500)
        await self.action('buy',actor=20,listing=listing['id'],price=100,nonce='b'*32)
        purchased=(await self.db.holdings_view(-100,20))['people'][0]
        self.assertHidden(purchased['identity'])

    async def test_expedition_quotes_and_persisted_history_filter_internal_rarity(self):
        q=await self.db.expedition_quote(-100,10,'outskirts',[100])
        self.assertHidden(q['members'][0]['identity'])
        self.assertNotIn('base_power',q['members'][0])
        token=await self.db.expedition_start(-100,10,'outskirts',[100],q['revision'],'e'*32,fixtures.Rolls([0,.999]))
        raw=json.loads(self.db.connection.execute('SELECT quote_json FROM slave_expeditions WHERE id=?',(token,)).fetchone()[0])
        self.assertIn('rarity',raw['members'][0]['identity'])
        active=(await self.view())['expeditions'][0]
        self.assertHidden(active['quote']['members'][0]['identity'])
        await self.action('appraise',worker=100,nonce='p'*32)
        active=(await self.view())['expeditions'][0]
        self.assertTrue(active['quote']['members'][0]['identity']['appraised'])
        self.clock+=1801;await self.db.expedition_sweep()
        self.assertEqual((await self.view())['expeditions'][0]['status'],'finished')


if __name__=='__main__':unittest.main()
