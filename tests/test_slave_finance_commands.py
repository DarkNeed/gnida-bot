"""Chat commands use the same real finance ledger; Telegram calls are mocked."""
import asyncio
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import Message, User, Chat
from handlers.slave_finance import (create_finance_router, command_amount, WAGER_COMMAND,
    BORROW_COMMAND, REPAY_COMMAND, STATUS_COMMAND)
from slave_finance_phrases import PHRASES
from tests import test_holdings as fixtures


class CommandParsingTests(unittest.TestCase):
    def test_aliases_caps_slashes_suffix_and_amounts(self):
        for text in ('Взять в долг 1000','взять кредит 1000','/ВЗЯТЬ@GnidoBot кредит 1 000 франков','!взять в долг 1000₣'):
            self.assertEqual(command_amount(text,BORROW_COMMAND),1000)
        for text in ('взять кредит -1','взять в долг 0','взять кредит 1.5','взять кредит 1e3','взять кредит 10 00','взять кредит 1000 потом'):
            with self.assertRaises(ValueError):command_amount(text,BORROW_COMMAND)
        self.assertEqual(command_amount('Погасить долг',REPAY_COMMAND,allow_all=True),'all')
        self.assertEqual(command_amount('вернуть долг всё',REPAY_COMMAND,allow_all=True),'all')
        self.assertTrue(STATUS_COMMAND.fullmatch('/долг@GnidoBot'))
        self.assertTrue(WAGER_COMMAND.match('депнуть @user100'))
        self.assertFalse(WAGER_COMMAND.match('депнуть 100'))

    def test_varied_cosmetic_phrases_have_no_template_injection(self):
        for kind,phrases in PHRASES.items():
            with self.subTest(kind=kind):
                self.assertGreaterEqual(len(phrases),3)
                self.assertEqual(len(phrases),len(set(phrases)))
                self.assertTrue(all('<' not in s and '{' not in s for s in phrases))


class FinanceCommandTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.HoldingsTests.asyncSetUp
    asyncTearDown=fixtures.HoldingsTests.asyncTearDown

    def setup_router(self):
        def member(chat,user):
            return SimpleNamespace(status='member',user=self.user(user))
        self.bot.get_chat_member=AsyncMock(side_effect=member)
        self.router=create_finance_router(self.db)
        self.command=self.router.message.handlers[0].callback
        self.confirm=self.router.callback_query.handlers[0].callback

    def user(self,ident):
        return User(id=ident,is_bot=False,first_name='Игрок <'+str(ident)+'>',username='user'+str(ident))

    def message(self,text,actor=20,source=100,chat=-100):
        return SimpleNamespace(text=text,caption=None,sender_chat=None,from_user=self.user(actor),
            chat=SimpleNamespace(id=chat,type='supergroup',title='Тестовый чат'),message_id=source,
            answer=AsyncMock(return_value=SimpleNamespace(message_id=source+10000)))

    async def row(self,source=100,actor=20,chat=-100):
        return await self.db.finance_command_existing(chat,source,actor)

    def callback(self,row,action='y',actor=None,chat=None,message=None):
        return SimpleNamespace(data='nf:'+action+':'+row['id'],from_user=self.user(actor or row['actor_id']),
            message=SimpleNamespace(chat=SimpleNamespace(id=chat or row['chat_id'],type='supergroup'),
                message_id=message or row['message_id'],edit_text=AsyncMock()),answer=AsyncMock())

    async def test_both_loan_commands_confirm_then_credit_once(self):
        self.setup_router()
        for source,text in ((100,'Взять в долг 1000'),(101,'Взять кредит 1000')):
            with self.subTest(text=text):
                msg=self.message(text,source=source)
                before=await self.db.franc_balance(-100,20)
                await self.command(msg,self.bot)
                self.assertEqual(await self.db.franc_balance(-100,20),before)
                self.assertIn('1150',msg.answer.await_args.args[0])
                self.assertIn('&lt;20&gt;',msg.answer.await_args.args[0])
                row=await self.row(source)
                cb=self.callback(row)
                await self.confirm(cb,self.bot)
                self.assertEqual(await self.db.franc_balance(-100,20),before+1000)
                await self.confirm(cb,self.bot)
                self.assertEqual(await self.db.franc_balance(-100,20),before+1000)
                self.assertIn('Повторного',cb.answer.await_args.args[0])
                loan=self.db._finance_loan_locked(20)
                await self.db.credit_francs(-100,20,150)
                await self.db.finance_action(-100,20,dict(action='finance_repay',loan=loan['id'],amount=1150,confirm=True,nonce=str(source)*16))

    async def test_username_wager_replay_and_owner_bound_cancel(self):
        self.setup_router()
        msg=self.message('депнуть @user100',actor=10)
        await self.command(msg,self.bot)
        row=await self.row(actor=10)
        self.assertIn('17%',row['summary']);self.assertIn('500',row['summary']);self.assertIn('120',row['summary'])
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)
        cb=self.callback(row,actor=20)
        await self.confirm(cb,self.bot)
        self.assertTrue(cb.answer.await_args.kwargs['show_alert'])
        self.assertEqual((await self.row(actor=10))['status'],'pending')
        cancelled=self.callback(row,action='n')
        await self.confirm(cancelled,self.bot)
        self.assertEqual((await self.row(actor=10))['status'],'cancelled')
        await self.confirm(self.callback(row),self.bot)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)

    async def test_real_wager_callback_and_concurrent_clicks_have_one_receipt(self):
        self.setup_router()
        await self.command(self.message('/депнуть@GnidoBot @user100',actor=10),self.bot)
        row=await self.row(actor=10)
        a,b=self.callback(row),self.callback(row)
        await asyncio.gather(self.confirm(a,self.bot),self.confirm(b,self.bot))
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM npc_finance_receipts WHERE user_id=10 AND nonce=?',(row['id'],)).fetchone()[0],1)
        self.assertEqual((await self.row(actor=10))['status'],'done')

    async def test_expiry_chat_message_and_user_binding(self):
        self.setup_router()
        await self.command(self.message('взять кредит 100'),self.bot)
        row=await self.row()
        for cb in (self.callback(row,chat=-200),self.callback(row,message=999),self.callback(row,actor=10)):
            await self.confirm(cb,self.bot)
            self.assertTrue(cb.answer.await_args.kwargs['show_alert'])
        self.clock+=301
        await self.confirm(self.callback(row),self.bot)
        self.assertIsNone(self.db._finance_loan_locked(20))
        self.assertEqual(await self.db.franc_balance(-100,20),0)

    async def test_confirmations_survive_restart_and_redelivery_does_not_resend(self):
        self.setup_router();msg=self.message('взять в долг 1000')
        await self.command(msg,self.bot);await self.command(msg,self.bot)
        msg.answer.assert_awaited_once()
        row=await self.row()
        await self.db.close();await self.db.connect()
        self.setup_router()
        await self.confirm(self.callback(row),self.bot)
        self.assertEqual(await self.db.franc_balance(-100,20),1000)
        await self.db.close();await self.db.connect()
        self.setup_router();await self.confirm(self.callback(row),self.bot)
        self.assertEqual(await self.db.franc_balance(-100,20),1000)

    async def test_wrong_owner_stale_username_and_foreign_worker_rejected(self):
        self.setup_router()
        for text,actor in (('депнуть @user100',20),('депнуть @unknown',10),('депнуть @user100 extra',10)):
            msg=self.message(text,actor=actor)
            await self.command(msg,self.bot)
            self.assertIsNone(await self.row(actor=actor))
        self.bot.get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=self.user(20)))
        await self.command(self.message('депнуть @user100',actor=10),self.bot)
        self.assertIsNone(await self.row(actor=10))

    async def test_debt_status_partial_and_full_repayment_commands(self):
        self.setup_router()
        msg=self.message('взять кредит 1000')
        await self.command(msg,self.bot);await self.confirm(self.callback(await self.row()),self.bot)
        msg=self.message('долг',source=101);await self.command(msg,self.bot)
        self.assertIn('1150',msg.answer.await_args.args[0])
        await self.command(self.message('вернуть долг 500',source=102),self.bot)
        self.assertEqual(self.db._finance_loan_locked(20)['remaining'],1150)
        await self.confirm(self.callback(await self.row(102)),self.bot)
        self.assertEqual(self.db._finance_loan_locked(20)['remaining'],650)
        await self.db.credit_francs(-100,20,150)
        await self.command(self.message('погасить долг',source=103),self.bot)
        await self.confirm(self.callback(await self.row(103)),self.bot)
        self.assertIsNone(self.db._finance_loan_locked(20))
        msg=self.message('/долг',source=104);await self.command(msg,self.bot)
        self.assertIn('Долга нет',msg.answer.await_args.args[0])

    async def test_disabled_module_private_anonymous_and_numeric_deposit_filter(self):
        self.setup_router()
        event=Message(message_id=200,date=datetime.now(timezone.utc),chat=Chat(id=-100,type='supergroup'),from_user=self.user(10),text='депнуть 100')
        self.assertFalse((await self.router.message.handlers[0].check(event))[0])
        for text in ('депнуть @user100','Взять в долг 1000','Взять кредит 1000'):
            event=event.model_copy(update={'text':text})
            self.assertTrue((await self.router.message.handlers[0].check(event))[0])
        event=event.model_copy(update={'text':None,'caption':'Взять кредит 1000'})
        self.assertTrue((await self.router.message.handlers[0].check(event))[0])
        msg=self.message('взять кредит 100');msg.chat.type='private'
        await self.command(msg,self.bot);self.assertIn('в группе',msg.answer.await_args.args[0])
        msg=self.message('взять кредит 100');msg.sender_chat=SimpleNamespace(id=-100)
        await self.command(msg,self.bot);msg.answer.assert_not_awaited()
        with patch.object(self.db,'feature_enabled',AsyncMock(return_value=False)):
            msg=self.message('взять кредит 100');await self.command(msg,self.bot)
            self.assertIn('выключено',msg.answer.await_args.args[0])
        self.assertIsNone(self.db._finance_loan_locked(20))

    async def test_quote_settlement_revalidates_ownership(self):
        self.setup_router()
        await self.command(self.message('депнуть @user100',actor=10),self.bot)
        row=await self.row(actor=10)
        await self.db.transfer_slave(-100,10,100,20)
        await self.confirm(self.callback(row),self.bot)
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],20)
        self.assertFalse(self.db.connection.execute('SELECT 1 FROM npc_finance_receipts WHERE nonce=?',(row['id'],)).fetchone())
