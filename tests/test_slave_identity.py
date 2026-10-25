import json
import unittest
from collections import Counter
from unittest.mock import patch

from tests import test_holdings as fixtures
from slave_identity import RARITIES, TRAITS, LEGENDARY_WORKER_ID, rarity_for


class RarityRulesTests(unittest.TestCase):
    def test_exact_once_only_odds(self):
        keys=list(RARITIES)
        rolls=Counter(rarity_for(luck) for luck in range(10000))
        self.assertEqual([rolls[k] for k in keys],[5000,2800,1500,600,100])
        self.assertEqual(len(TRAITS),13)


class WorkerIdentityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.HoldingsTests.asyncSetUp
    asyncTearDown=fixtures.HoldingsTests.asyncTearDown
    view=fixtures.HoldingsTests.view
    site=fixtures.HoldingsTests.site

    def identity(self,user=100,luck=9999,trait='mine',created=None):
        self.db.connection.execute('INSERT OR REPLACE INTO slave_identities(user_id,luck,trait,created_at,rarity) VALUES(?,?,?,?,?)',(user,luck,trait,self.clock if created is None else created,rarity_for(luck)))
        self.db.connection.commit()

    async def test_identity_follows_user_across_chats_sale_release_and_restart(self):
        self.identity()
        original=self.db._slave_identity_locked(100)
        self.assertEqual(original['rarity'],'legendary')
        self.assertTrue(await self.db.release_slave(-100,10,100))
        self.clock+=1;await self.db.force_enslave(-100,100,20)
        self.assertEqual(self.db._slave_identity_locked(100),original)
        other=await self.db.holdings_view(-200,10)
        public=next(p['identity'] for p in other['people'] if p['user_id']==100)
        self.assertFalse(public['appraised'])
        self.assertNotIn('rarity',public)
        self.assertEqual(public['trait_id'],original['trait_id'])
        await self.db.close();await self.db.connect()
        self.assertEqual(self.db._slave_identity_locked(100),original)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM personal_profiles').fetchone()[0],0)

    async def test_activity_time_and_multiple_chats_never_change_rarity(self):
        self.identity(luck=7500)
        initial=self.db._slave_identity_locked(100)
        for _ in range(20):await self.db.upsert_user(-100,100,'u','Участник')
        await self.db.upsert_user(-200,100,'u','Участник')
        self.assertEqual(self.db._slave_identity_locked(100),initial)
        self.clock+=86400
        await self.db.upsert_user(-100,100,'u','Участник',touch=False)
        await self.db.upsert_user(100,100,'u','Участник')
        self.assertEqual(self.db._slave_identity_locked(100),initial)
        await self.db.upsert_user(-100,100,'u','Участник')
        self.assertEqual(self.db._slave_identity_locked(100),initial)
        for i in range(70):
            self.clock+=86400;await self.db.upsert_user(-100,100,'u','Участник')
        self.assertEqual(self.db._slave_identity_locked(100),initial)
        self.assertNotIn('next_activity_days',initial)
        self.assertNotIn('active_days',initial)
        self.assertTrue(initial['permanent'])

    async def test_old_activity_records_and_changed_luck_cannot_upgrade_frozen_passport(self):
        self.identity(luck=7500)
        self.db.connection.execute('DELETE FROM slave_activity_days WHERE user_id=100')
        for i in range(7):
            self.db.connection.execute('INSERT INTO slave_activity_days VALUES(?,?,?)',(100,str(i),self.clock+i*86400))
        self.db.connection.commit()
        self.assertEqual(self.db._slave_identity_locked(100,self.clock)['rarity'],'uncommon')
        self.assertEqual(self.db._slave_identity_locked(100,self.clock+6*86400)['rarity'],'uncommon')
        self.assertEqual(self.db._slave_work_percent_locked(100,'mine',self.clock),140)
        self.assertEqual(self.db._slave_work_percent_locked(100,'mine',self.clock+6*86400),140)
        self.db.connection.execute('UPDATE slave_identities SET luck=9999 WHERE user_id=100');self.db.connection.commit()
        self.assertEqual(self.db._slave_identity_locked(100)['rarity'],'uncommon')

    async def test_owner_guaranteed_legendary_once_and_existing_passport_is_preserved(self):
        self.db.connection.execute('DELETE FROM slave_identities WHERE user_id=?',(LEGENDARY_WORKER_ID,));self.db.connection.commit()
        with patch('slave_identity.draw_identity',return_value=(0,'mine')):
            initial=self.db._slave_identity_locked(LEGENDARY_WORKER_ID)
        self.assertEqual(initial['rarity'],'legendary')
        self.assertEqual(initial['trait_id'],'mine')
        self.db.connection.execute("UPDATE slave_identities SET rarity='common' WHERE user_id=?",(LEGENDARY_WORKER_ID,));self.db.connection.commit()
        await self.db.close();await self.db.connect()
        self.assertEqual(self.db._slave_identity_locked(LEGENDARY_WORKER_ID),initial)
        self.identity(101,luck=0)
        self.assertEqual(self.db._slave_identity_locked(101)['rarity'],'common')

    async def test_migration_freezes_old_current_rarity_without_reroll_or_demotion(self):
        self.identity(luck=9500)
        self.db.connection.execute('UPDATE slave_identities SET rarity=NULL WHERE user_id=100')
        for n in range(60):
            self.db.connection.execute('INSERT OR REPLACE INTO slave_activity_days VALUES(?,?,?)',(100,'legacy'+str(n),self.clock-n*86400))
        self.db.connection.commit()
        with patch('slave_identity.draw_identity',side_effect=AssertionError('Do not reroll')):
            self.db._init_slave_identities()
        self.assertEqual(self.db._slave_identity_locked(100)['rarity'],'legendary')
        self.db.connection.execute('DELETE FROM slave_activity_days WHERE user_id=100');self.db.connection.commit()
        await self.db.close();await self.db.connect()
        self.assertEqual(self.db._slave_identity_locked(100)['rarity'],'legendary')
        self.assertEqual(self.db._slave_identity_locked(100)['trait_id'],'mine')

    async def test_rarity_and_specialization_affect_only_active_producer_income(self):
        self.identity()
        site=await self.site()
        await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        self.clock+=3600
        r=await self.db.settle_business(-100,10)
        self.assertEqual(r['gross_income'],6)  # 3 * (100+70+30)%
        self.db.connection.execute('UPDATE users SET last_seen=? WHERE chat_id=-100 AND user_id=100',(self.clock-100000,));self.db.connection.commit()
        self.clock+=3600
        self.assertEqual((await self.db.settle_business(-100,10))['gross_income'],1)
        self.assertEqual(self.db._slave_work_percent_locked(100,'tavern',self.clock),170)

    async def test_manager_bonus_and_subcent_carry_match_hourly_and_batch(self):
        await self.db.credit_francs(-100,20,2000)
        await self.db.force_enslave(-100,101,20);await self.db.force_enslave(-100,103,20)
        for user in (100,101):self.identity(user)
        for user in (102,103):self.identity(user,luck=0,trait='manager')
        first=await self.site()
        self.assertEqual(await self.db.enterprise_create(-100,20,'mine'),'created')
        second=await self.db.get_business(-100,20,business_type='mine')
        for owner,worker,manager,site in ((10,100,102,first),(20,101,103,second)):
            await self.db.enterprise_assign(-100,owner,worker,'worker',site['id'])
            await self.db.enterprise_assign(-100,owner,manager,'leader',site['id'])
        self.clock+=3600
        a=await self.db.settle_business(-100,10)
        self.assertEqual(a['gross_income'],7)
        self.clock+=3600
        b=await self.db.settle_business(-100,10);batch=await self.db.settle_business(-100,20)
        self.assertEqual(b['gross_income'],8)
        self.assertEqual(a['gross_income']+b['gross_income'],batch['gross_income'])
        self.assertEqual(batch['gross_income'],15)

    async def test_existing_unrated_jobs_settle_old_hours_without_retroactive_bonus(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        self.db.connection.execute('DELETE FROM slave_identities WHERE user_id=100');self.db.connection.commit()
        self.clock+=10*3600
        with patch('slave_identity.draw_identity',return_value=(9999,'mine')):
            r=await self.db.settle_business(-100,10)
        self.assertEqual(r['gross_income'],30)
        self.clock+=3600
        self.assertEqual((await self.db.settle_business(-100,10))['gross_income'],6)

    async def test_expediton_traits_power_risk_and_snapshot_without_arena_mutations(self):
        self.identity(trait='scout')
        p=self.db._expedition_source_locked(-100,100)
        self.assertEqual(p['power'],round(p['base_power']*1.2,1))
        self.identity(101,luck=0,trait='insured')
        q=await self.db.expedition_quote(-100,10,'outskirts',[100,101])
        insured=next(m for m in q['members'] if m['user_id']==101)
        self.assertEqual(insured['loss_fail'],insured['loss_win']+1)
        self.identity(100,trait='ruins')
        ruins=await self.db.expedition_quote(-100,10,'ruins',[100])
        base=self.db._expedition_source_locked(-100,100)
        self.assertEqual(ruins['members'][0]['power'],round(base['power']+base['base_power']*.2,1))
        token=await self.db.expedition_start(-100,10,'ruins',[100],ruins['revision'],'s'*32,fixtures.Rolls([0,.999]))
        self.identity(100,luck=0,trait='survivor')
        saved=json.loads(self.db.connection.execute('SELECT quote_json FROM slave_expeditions WHERE id=?',(token,)).fetchone()[0])
        self.assertEqual(saved['members'][0]['identity']['rarity'],'legendary')
        self.assertEqual(saved['members'][0]['identity']['trait_id'],'ruins')
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM personal_profiles').fetchone()[0],0)

    async def test_appraisal_price_and_market_expose_traits_without_reroll(self):
        self.identity()
        before=tuple(self.db.connection.execute('SELECT * FROM slave_identities WHERE user_id=100').fetchone())
        v=await self.view()
        report=await self.db.trader_action(-100,10,dict(action='trader_appraise',worker=100,confirm=True,revision=v['revision'],nonce='p'*32))
        self.assertEqual(next(r['active_rate'] for r in report['report']['rates'] if r['kind']=='mine'),6)
        self.assertEqual(report['report']['identity']['trait_id'],'mine')
        await self.db.trader_action(-100,10,dict(action='trader_list',worker=100,price=500,confirm=True,revision=v['revision'],nonce='l'*32))
        listing=(await self.view())['trader']['listings'][0]
        self.assertEqual(listing['identity']['rarity'],'legendary')
        self.assertEqual(before,tuple(self.db.connection.execute('SELECT * FROM slave_identities WHERE user_id=100').fetchone()))
        self.assertEqual(len((await self.view())['trader']['identity_rules']['traits']),13)


if __name__=='__main__':unittest.main()
