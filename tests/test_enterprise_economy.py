"""Capital-cost rebalance: old properties survive, all new openings cost francs."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from database import Database,BUSINESS_CONFIG
from enterprises import CATALOG,UPGRADE_PRICES


class EnterpriseEconomyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'economy.sqlite'
        self.db=Database(self.path);await self.db.connect()
        await self.db.upsert_chat(-100,'Тест')
        for user in (10,20):await self.db.upsert_user(-100,user,str(user),str(user))
        await self.db.force_enslave(-100,20,10)

    async def asyncTearDown(self):
        await self.db.close();self.folder.cleanup()

    async def test_catalog_has_no_free_enterprises_and_rates_are_unchanged(self):
        self.assertEqual({k:v['price'] for k,v in CATALOG.items()},
            dict(field=1000,brothel=1500,tavern=750,mine=1250,workshop=1750,custom=1250))
        self.assertEqual(UPGRADE_PRICES,{1:1000,2:2500})
        self.assertEqual({k:v['owner_per_producer'] for k,v in BUSINESS_CONFIG.items()},
            dict(field=3,brothel=4,tavern=2,mine=3,workshop=4,custom=3))
        self.assertTrue(all(v['price']>0 for v in CATALOG.values()))

    async def test_formerly_free_types_require_money_and_charge_exactly_once(self):
        for kind in ('field','brothel'):
            with self.subTest(kind=kind):
                self.assertEqual(await self.db.create_business(-100,10,kind),'insufficient')
                self.assertIsNone(await self.db.get_business(-100,10,business_type=kind))
                await self.db.credit_francs(-100,10,CATALOG[kind]['price'])
                results=await asyncio.gather(*(self.db.create_business(-100,10,kind) for _ in range(2)))
                self.assertCountEqual(results,['created','exists'])
                self.assertEqual(await self.db.franc_balance(-100,10),0)

    async def test_all_types_use_the_catalog_price_and_close_does_not_refund(self):
        for kind,definition in CATALOG.items():
            await self.db.credit_francs(-100,10,definition['price'])
            self.assertEqual(await self.db.enterprise_create(-100,10,kind),'created')
            self.assertEqual(await self.db.franc_balance(-100,10),0)
            site=await self.db.get_business(-100,10,business_type=kind)
            view=await self.db.holdings_view(-100,10)
            await self.db.enterprise_close(-100,10,site['id'],view['revision'])
            self.assertEqual(await self.db.franc_balance(-100,10),0)

    async def test_legacy_free_properties_and_jobs_survive_restart_without_backcharge(self):
        self.db.connection.execute("INSERT INTO businesses(chat_id,owner_id,business_type,created_at,last_accrued,rules_since,level,name) VALUES(-100,10,'field',1,1,1,2,'Старое поле')")
        site=await self.db.get_business(-100,10,business_type='field')
        self.db.connection.execute("INSERT INTO business_workers(chat_id,owner_id,worker_id,role,assigned_at,business_id) VALUES(-100,10,20,'collector',1,?)",(site['id'],))
        self.db.connection.commit();await self.db.close();await self.db.connect()
        saved=await self.db.get_business(-100,10,business_type='field')
        self.assertEqual((saved['id'],saved['level'],saved['name']),(site['id'],2,'Старое поле'))
        self.assertEqual(await self.db.franc_balance(-100,10),0)
        self.assertEqual(self.db.connection.execute('SELECT business_id FROM business_workers WHERE worker_id=20').fetchone()[0],site['id'])


if __name__=='__main__':unittest.main()
