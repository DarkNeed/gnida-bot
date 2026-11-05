import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from aiogram.exceptions import TelegramForbiddenError,TelegramNetworkError
from aiogram.methods import SendMessage
from tests import test_npc_workers as fixtures
from handlers.enterprises import sweep_recovery_events,publish_slave_buyouts
from npc_worker_rules import DAY


class SlaveryNoticeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.NpcTests.asyncSetUp
    asyncTearDown=fixtures.NpcTests.asyncTearDown
    act=fixtures.NpcTests.act
    buy=fixtures.NpcTests.buy
    row=fixtures.NpcTests.row

    async def warning(self):
        await self.buy()
        with self.db.connection:
            self.db.connection.execute('UPDATE franc_balances SET balance=0 WHERE chat_id=-100 AND user_id=10')
            self.db._workforce_tick_locked(-100,10)
        return self.db.connection.execute('SELECT * FROM workforce_warnings WHERE chat=-100 AND owner=10').fetchone()

    def bot(self,error=None):
        return SimpleNamespace(send_message=AsyncMock(side_effect=error,return_value=SimpleNamespace(message_id=99)))

    async def test_warning_private_with_context_and_once_per_episode(self):
        before=await self.warning();self.assertIsNone(before['seen'])
        bot=self.bot();await sweep_recovery_events(self.db,bot,username='GnidoBot')
        self.assertEqual(bot.send_message.await_count,1)
        call=bot.send_message.await_args
        self.assertEqual(call.args[0],10)
        self.assertIn('Чат: Тест',call.args[1]);self.assertIn('Причины:',call.args[1])
        self.assertIn('кошельке',call.args[1])
        w=self.db.connection.execute('SELECT * FROM workforce_warnings WHERE chat=-100 AND owner=10').fetchone()
        self.assertEqual(w['deadline'],self.stamp+DAY)
        await sweep_recovery_events(self.db,bot)
        self.assertEqual(bot.send_message.await_count,1)

    async def test_blocked_pm_has_no_group_fallback_no_deadline_and_persistent_backoff(self):
        await self.warning()
        bot=self.bot(TelegramForbiddenError(method=SendMessage(chat_id=10,text='warning'),message='blocked'))
        await sweep_recovery_events(self.db,bot)
        self.stamp+=301;await sweep_recovery_events(self.db,bot)
        await self.db.close();await self.db.connect()
        await sweep_recovery_events(self.db,bot)
        self.assertEqual(bot.send_message.await_count,1)
        w=self.db.connection.execute('SELECT * FROM workforce_warnings WHERE chat=-100 AND owner=10').fetchone()
        self.assertIsNone(w['seen']);self.assertIsNone(w['deadline'])
        self.assertTrue(all(call.args[0]==10 for call in bot.send_message.await_args_list))

    async def test_network_error_retries_after_lease_without_starting_countdown(self):
        await self.warning()
        bot=self.bot(TelegramNetworkError(method=SendMessage(chat_id=10,text='warning'),message='offline'))
        await sweep_recovery_events(self.db,bot);await sweep_recovery_events(self.db,bot)
        self.assertEqual(bot.send_message.await_count,1)
        self.assertIsNone(self.db.connection.execute('SELECT deadline FROM workforce_warnings WHERE chat=-100 AND owner=10').fetchone()[0])
        self.stamp+=301;bot.send_message.side_effect=None
        await sweep_recovery_events(self.db,bot)
        self.assertEqual(bot.send_message.await_count,2)
        self.assertEqual(self.db.connection.execute('SELECT deadline FROM workforce_warnings WHERE chat=-100 AND owner=10').fetchone()[0],self.stamp+DAY)

    async def test_parallel_sweeps_do_not_publish_the_same_warning_twice(self):
        await self.warning();bot=self.bot()
        await asyncio.gather(sweep_recovery_events(self.db,bot),sweep_recovery_events(self.db,bot))
        self.assertEqual(bot.send_message.await_count,1)

    async def test_lease_does_not_prevent_owner_reading_warning_in_app(self):
        await self.warning();await self.db.workforce_notifications()
        with self.db.connection:view=self.db._workforce_view_locked(-100,10)
        self.assertEqual(view['warning']['deadline'],self.stamp+DAY)

    async def test_new_missing_worker_alert_is_private_and_activates_only_on_delivery(self):
        id=await self.buy();worker=self.row(id);event=uuid4().hex
        payload=dict(secret=[0,1,2],history=[],bounty=0)
        with self.db.connection:
            self.db.connection.execute("INSERT INTO workforce_events VALUES(?,-100,10,?,'npc',?,?,'kidnapped','announcing',?,NULL,NULL,NULL,0,?,0)",
                (event,id,worker['created'],worker['data']['name'],self.stamp,json.dumps(payload)))
        bot=self.bot();await sweep_recovery_events(self.db,bot)
        self.assertEqual(bot.send_message.await_count,1)
        self.assertEqual(bot.send_message.await_args.args[0],10)
        e=self.db.connection.execute('SELECT * FROM workforce_events WHERE id=?',(event,)).fetchone()
        self.assertEqual(e['status'],'open');self.assertEqual(e['deadline'],self.stamp+8*3600)
        await sweep_recovery_events(self.db,bot);self.assertEqual(bot.send_message.await_count,1)

    async def test_buyout_notice_committed_once_and_sent_privately_even_without_create_sweep(self):
        await self.db.upsert_user(-100,100,'worker','Раб <script>')
        await self.db.credit_francs(-100,100,100)
        self.assertEqual(await self.db.buyout_slave(-100,10,100),'released')
        self.assertEqual(await self.db.buyout_slave(-100,10,100),'not_owned')
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM slave_buyout_notices').fetchone()[0],1)
        await self.db.close();await self.db.connect()
        bot=self.bot();await sweep_recovery_events(self.db,bot,create=False,username='GnidoBot')
        call=bot.send_message.await_args;self.assertEqual(call.args[0],10)
        self.assertIn('Раб выкупился',call.args[1]);self.assertIn('100 ₣',call.args[1])
        self.assertNotIn('<script>',call.args[1]);self.assertIn('&lt;script&gt;',call.args[1])
        await sweep_recovery_events(self.db,bot,create=False)
        self.assertEqual(bot.send_message.await_count,1)

    async def test_failed_buyout_creates_no_notice(self):
        self.assertEqual(await self.db.buyout_slave(-100,10,100),'insufficient')
        self.assertEqual(await self.db.buyout_slave(-100,20,100),'not_owned')
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM slave_buyout_notices').fetchone()[0],0)

    async def test_notification_queue_and_buyout_roll_back_together_on_database_failure(self):
        await self.db.credit_francs(-100,100,100)
        with patch.object(self.db,'_queue_slave_buyout_notice_locked',side_effect=RuntimeError('database unavailable')):
            with self.assertRaises(RuntimeError):await self.db.buyout_slave(-100,10,100)
        self.assertEqual(await self.db.franc_balance(-100,100),100)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)

    async def test_delivery_failure_does_not_repeat_payment_or_release(self):
        await self.db.credit_francs(-100,100,100)
        await self.db.buyout_slave(-100,10,100)
        bot=self.bot(TelegramNetworkError(method=SendMessage(chat_id=10,text='buyout'),message='offline'))
        await publish_slave_buyouts(self.db,bot);await publish_slave_buyouts(self.db,bot)
        self.assertEqual(bot.send_message.await_count,1)
        self.assertIsNone(await self.db.get_owner(-100,100))
        self.assertEqual(await self.db.franc_balance(-100,100),0)
        self.stamp+=301;bot.send_message.side_effect=None
        await publish_slave_buyouts(self.db,bot)
        self.assertEqual(bot.send_message.await_count,2)
        self.assertEqual(self.db.connection.execute('SELECT sent FROM slave_buyout_notices').fetchone()[0],1)

    async def test_market_buyout_notifies_seller_once_despite_receipt_replay(self):
        v=await self.db.holdings_view(-100,10)
        await self.db.trader_action(-100,10,dict(action='trader_list',worker=100,price=201,confirm=True,nonce=uuid4().hex,revision=v['revision']))
        listing=self.db.connection.execute('SELECT id FROM slave_trader_listings WHERE status=\'active\'').fetchone()[0]
        await self.db.credit_francs(-100,20,500)
        body=dict(action='trader_buy',listing=listing,price=201,confirm=True,nonce=uuid4().hex)
        await self.db.trader_action(-100,20,body);await self.db.trader_action(-100,20,body)
        rows=self.db.connection.execute('SELECT * FROM slave_buyout_notices').fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['recipient'],10)
        self.assertEqual(rows[0]['buyer'],20);self.assertEqual(rows[0]['amount'],201)
        bot=self.bot();await publish_slave_buyouts(self.db,bot)
        self.assertEqual(bot.send_message.await_args.args[0],10)
        self.assertIn('Раб выкуплен у тебя',bot.send_message.await_args.args[1])


if __name__=='__main__':unittest.main()
