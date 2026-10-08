import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import BUSINESS_STATS_TZ, Database, business_income_tax
from handlers.routes import create_router


class BusinessTaxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.folder.name) / "tax.sqlite3")
        await self.db.connect()
        self.start = int(datetime(2026, 10, 6, tzinfo=BUSINESS_STATS_TZ).timestamp())

    async def asyncTearDown(self):
        await self.db.close()
        self.folder.cleanup()

    async def business(self, owner=10, producers=10, leaders=0, chat=1, kind="brothel"):
        await self.db.upsert_chat(chat, "Чат")
        await self.db.upsert_user(chat, owner, f"owner{owner}", "Владелец")
        config_roles = ("courtesan", "manager") if kind == "brothel" else ("collector", "overseer")
        # Fixed fixtures avoid settlement during worker assignment and keep workers active.
        self.db.connection.execute(
            "INSERT INTO businesses(chat_id,owner_id,business_type,created_at,last_accrued) VALUES(?,?,?,?,?)",
            (chat, owner, kind, self.start, self.start),
        )
        for index in range(producers + leaders):
            worker = owner * 1000 + index
            await self.db.upsert_user(chat, worker, f"worker{worker}", "Работник")
            self.db.connection.execute(
                "UPDATE users SET last_seen=? WHERE chat_id=? AND user_id=?",
                (self.start + 86400, chat, worker),
            )
            self.db.connection.execute(
                "INSERT INTO ownership(chat_id,slave_id,owner_id,acquired_at) VALUES(?,?,?,?)",
                (chat, worker, owner, self.start),
            )
            self.db.connection.execute(
                "INSERT INTO business_workers(chat_id,owner_id,worker_id,role,assigned_at) VALUES(?,?,?,?,?)",
                (chat, owner, worker, config_roles[index >= producers], self.start),
            )
        self.db.connection.commit()

    async def settle(self, owner, hours, chat=1):
        with patch("database.utc_timestamp", return_value=self.start + hours * 3600):
            return await self.db.settle_business(chat, owner)

    def tax_rows(self, owner=10, chat=1):
        return [tuple(row) for row in self.db.connection.execute(
            "SELECT income_day,gross_income,tax_paid FROM business_tax_daily WHERE chat_id=? AND owner_id=? ORDER BY income_day",
            (chat, owner),
        )]

    async def test_progressive_brackets_and_examples(self):
        for gross, tax in ((0, 0), (300, 0), (480, 27), (960, 99),
                           (1000, 105), (2880, 763), (3000, 805), (4800, 1885)):
            with self.subTest(gross=gross):
                self.assertEqual(business_income_tax(gross), tax)

    async def test_full_day_net_income_and_untaxed_worker_wages(self):
        await self.business(producers=30)
        result = await self.settle(10, 24)
        self.assertEqual((result["gross_income"], result["tax"], result["owner_income"]), (2880, 763, 2117))
        self.assertEqual(await self.db.franc_balance(1, 10), 2117)
        self.assertEqual(await self.db.franc_balance(1, 10000), 4)
        self.assertEqual(self.tax_rows(), [("2026-10-06", 2880, 763)])

    async def test_hourly_and_batch_settlement_match_with_fractional_manager_bonus(self):
        await self.business(owner=10, producers=40, leaders=5)
        await self.business(owner=11, producers=40, leaders=5)
        batch = await self.settle(10, 24)
        hourly_net = hourly_gross = hourly_tax = 0
        for hour in range(1, 25):
            result = await self.settle(11, hour)
            hourly_net += result["owner_income"]
            hourly_gross += result["gross_income"]
            hourly_tax += result["tax"]
        self.assertEqual((hourly_net, hourly_gross, hourly_tax),
                         (batch["owner_income"], batch["gross_income"], batch["tax"]))
        self.assertEqual(self.tax_rows(10), self.tax_rows(11))
        self.assertEqual(batch["gross_income"], 5299)
        self.assertEqual((await self.db.get_business(1, 10))["income_remainder"], 20)

    async def test_multiday_accrual_uses_separate_moscow_day_brackets(self):
        await self.business(producers=10)
        result = await self.settle(10, 48)
        self.assertEqual(result["gross_income"], 1920)
        self.assertEqual(result["tax"], 198)
        self.assertEqual(result["owner_income"], 1722)
        self.assertEqual(self.tax_rows(), [("2026-10-06", 960, 99), ("2026-10-07", 960, 99)])

    async def test_restart_does_not_credit_or_tax_twice(self):
        await self.business(producers=10)
        await self.settle(10, 24)
        await self.db.close()
        await self.db.connect()
        result = await self.settle(10, 24)
        self.assertEqual(result["owner_income"], 0)
        self.assertEqual(result["tax"], 0)
        self.assertEqual(await self.db.franc_balance(1, 10), 861)
        self.assertEqual(self.tax_rows(), [("2026-10-06", 960, 99)])

    async def test_old_paid_income_and_existing_balance_not_retroactively_taxed(self):
        await self.business(producers=1)
        self.db.connection.execute(
            "INSERT INTO business_income_daily VALUES(1,10,'2026-10-06',5000)"
        )
        self.db._add_francs_locked(1, 10, 5000)
        self.db.connection.commit()
        result = await self.settle(10, 24)
        self.assertEqual(result["tax"], 0)
        self.assertEqual(await self.db.franc_balance(1, 10), 5096)

    async def test_shift_income_is_taxed_but_worker_pay_is_not(self):
        await self.business(producers=1)
        self.db._credit_business_income_locked(1, 10, "2026-10-06", 306)
        self.db.connection.commit()
        with patch("database.utc_timestamp", return_value=self.start + 3600), patch("database.random.randint", return_value=60):
            status, worker_pay, owner_pay, _ = await self.db.work_at_business(1, 10, 20)
        self.assertEqual((status, worker_pay, owner_pay), ("worked", 60, 0))
        self.assertEqual(await self.db.franc_balance(1, 20), 60)
        self.assertEqual(await self.db.franc_balance(1, 10), 306)
        self.assertEqual(self.tax_rows(), [("2026-10-06", 307, 1)])

    async def test_tax_and_net_statistics_for_completed_days(self):
        await self.business(producers=10)
        await self.settle(10, 48)
        today = datetime(2026, 10, 8, tzinfo=BUSINESS_STATS_TZ)
        with patch("database.datetime") as date_mock:
            date_mock.now.return_value = today
            self.assertEqual(await self.db.business_income_periods(1, 10), (861, 1722))
            self.assertEqual(await self.db.business_tax_periods(1, 10), (99, 198))

    async def test_owners_and_chats_have_independent_tax_ledgers(self):
        await self.business(owner=10, producers=10)
        await self.business(owner=11, producers=10, chat=2, kind="field")
        await self.settle(10, 24)
        await self.settle(11, 24, chat=2)
        self.assertEqual(self.tax_rows(10, 1), [("2026-10-06", 960, 99)])
        self.assertEqual(self.tax_rows(11, 2), [("2026-10-06", 720, 63)])

    async def test_public_enterprise_statistics_show_net_income_and_tax(self):
        await self.business(producers=10)
        await self.settle(10, 48)
        router = create_router(self.db)
        handler = next(item.callback for item in router.callback_query.handlers
                       if item.callback.__name__ == "enterprise_stats_callback")
        callback = SimpleNamespace(
            data="es:1:10", from_user=SimpleNamespace(id=20), answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=1, type="supergroup"), edit_text=AsyncMock()),
        )
        with patch("database.utc_timestamp", return_value=self.start + 48 * 3600), patch("database.datetime") as date_mock:
            date_mock.now.return_value = datetime(2026, 10, 8, tzinfo=BUSINESS_STATS_TZ)
            await handler(callback, SimpleNamespace())
        text = callback.message.edit_text.await_args.args[0]
        self.assertIn("Доход после налога вчера: <b>861 ₣</b> (налог 99 ₣)", text)
        self.assertIn("<b>1722 ₣</b> (налог 198 ₣)", text)


if __name__ == "__main__":
    unittest.main()
