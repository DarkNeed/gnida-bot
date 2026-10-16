import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

from aiogram.types import User
from database import Database,MAX_FRANC_BALANCE
from franc_deposit import DEPOSIT_RE,parse_deposit,WIN_PHRASES,LOSS_PHRASES
from handlers.routes import create_router


class Fixed:
    def __init__(self,roll):self.roll=roll;self.calls=0
    def randrange(self,limit):self.calls+=1;assert limit==100;return self.roll
    def choice(self,values):return values[0]


class DepositParserTests(unittest.TestCase):
    def test_accepted(self):
        for text,amount in [('депнуть 100',100),('депнуть 13400 франков',13400),('/депнуть 1 франк',1),
                            ('!ДЕПНУТЬ 22 франка',22),('/депнуть@GnidoBot 75 ₣',75),(' депнуть 5₣ ',5),
                            ('депнуть всё','all'),('депнуть все','all'),('/ДЕПНУТЬ ПОЛОВИНУ','half'),
                            ('!депнуть@GnidoBot Всё','all')]:
            self.assertIsNotNone(DEPOSIT_RE.match(text));self.assertEqual(parse_deposit(text),amount)

    def test_rejected_without_ambiguous_parsing(self):
        for text in ('депнуть','депнуть 0','депнуть -100','депнуть +100','депнуть 1.5','депнуть 1e3',
                     'депнуть 100 всем','депнуть 100 200','депнуть 9'*100,'передепнуть 100',
                     'депнуть '+str(MAX_FRANC_BALANCE),'депнуть １０'):
            with self.assertRaises(ValueError,msg=text):parse_deposit(text)

    def test_phrase_templates(self):
        for s in WIN_PHRASES+LOSS_PHRASES:
            self.assertIn('Игрок',s.format(user='Игрок',stake=100,payout=500))


class DepositTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock=1800000000
        self.time_patch=patch('database.utc_timestamp',side_effect=lambda:self.clock)
        self.time_patch.start()
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'deposits.sqlite3'
        self.db=Database(self.path);await self.db.connect()
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Чат <'+str(chat)+'>')
            await self.db.upsert_user(chat,10,'user','Игрок')
            await self.db.credit_francs(chat,10,1000)
        self.router=create_router(self.db)
        self.handler=next(h.callback for h in self.router.message.handlers if h.callback.__name__=='deposit')
        self.bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))

    async def asyncTearDown(self):
        for handler in self.router.shutdown.handlers:await handler.callback()
        await self.db.close();self.folder.cleanup()
        self.time_patch.stop()

    async def bet(self,roll=99,stake=100,mid=1,source=-100,chat=-100,rng=None):
        return await self.db.deposit_francs(chat,10,stake,source,mid,rng or Fixed(roll))

    def message(self,text='депнуть 100',private=False,mid=1):
        return SimpleNamespace(text=text,caption=None,from_user=User(id=10,is_bot=False,first_name='<Игрок>'),
            sender_chat=None,chat=SimpleNamespace(id=10 if private else -100,type='private' if private else 'supergroup'),
            message_id=mid,answer=AsyncMock())

    async def test_win_is_gross_x5_not_net_x5(self):
        result=await self.bet(roll=19)
        self.assertEqual((result['won'],result['payout'],result['balance_after']),(1,500,1400))
        self.assertEqual(await self.db.franc_balance(-200,10),1000)

    async def test_loss_only_loses_stake(self):
        for roll in (20,99):
            r=await self.bet(roll=roll,mid=roll)
            self.assertEqual(r['won'],0);self.assertEqual(r['payout'],0)
            self.clock+=60
        self.assertEqual(await self.db.franc_balance(-100,10),800)

    async def test_exact_twenty_out_of_one_hundred_rolls(self):
        wins=0
        for roll in range(100):
            wins+=(await self.bet(roll=roll,stake=1,mid=roll+1))['won']
            self.clock+=60
        self.assertEqual(wins,20)
        self.assertEqual(await self.db.franc_balance(-100,10),1000)

    async def test_duplicate_update_and_restart_do_not_reroll(self):
        r=await self.bet(roll=0)
        await self.db.close();await self.db.connect()
        rng=Fixed(99);again=await self.bet(rng=rng)
        self.assertEqual(again,r);self.assertEqual(rng.calls,0)
        self.assertEqual(await self.db.franc_balance(-100,10),1400)
        with self.assertRaises(ValueError):await self.bet(stake=200)
        with self.assertRaises(ValueError):await self.bet(chat=-200)

    async def test_parallel_duplicate_and_distinct_bets(self):
        a,b=await asyncio.gather(self.bet(roll=0),self.bet(roll=99))
        self.assertEqual(a,b);self.assertEqual(await self.db.franc_balance(-100,10),1400)
        self.clock+=60
        out=await asyncio.gather(self.bet(stake=1000,mid=2),self.bet(stake=1000,mid=3),return_exceptions=True)
        self.assertEqual(sum(bool(r.get('blocked')) for r in out),1)
        self.assertEqual(await self.db.franc_balance(-100,10),400)

    async def test_insufficient_invalid_and_overflow_never_roll(self):
        rng=Fixed(0)
        for amount in (0,-1,True,2.5,1001,MAX_FRANC_BALANCE):
            with self.assertRaises(ValueError):await self.bet(stake=amount,rng=rng)
        self.db.connection.execute('UPDATE franc_balances SET balance=? WHERE chat_id=-100',(MAX_FRANC_BALANCE,));self.db.connection.commit()
        with self.assertRaises(ValueError):await self.bet(stake=1,rng=rng)
        self.assertEqual(rng.calls,0)
        self.assertEqual(await self.db.franc_balance(-100,10),MAX_FRANC_BALANCE)

    async def test_transaction_rolls_back_when_receipt_insert_fails(self):
        self.db.connection.execute("CREATE TRIGGER fail_deposit BEFORE INSERT ON franc_deposits BEGIN SELECT RAISE(ABORT,'disk'); END")
        self.db.connection.commit()
        with self.assertRaises(Exception):await self.bet(roll=0)
        self.assertEqual(await self.db.franc_balance(-100,10),1000)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM franc_deposits').fetchone()[0],0)

    async def test_command_errors_and_html_escaping(self):
        msg=self.message('депнуть 2000');await self.handler(msg,self.bot)
        self.assertIn('Не хватает',msg.answer.call_args.args[0])
        msg=self.message('депнуть 100',mid=2);await self.handler(msg,self.bot)
        self.assertIn('&lt;Игрок&gt;',msg.answer.call_args.args[0]);self.assertIn('Баланс после ставки',msg.answer.call_args.args[0])
        self.assertEqual(msg.answer.call_args.kwargs['parse_mode'],'HTML')

    async def test_private_requires_explicit_verified_chat_and_scopes_receipt(self):
        msg=self.message(private=True)
        await self.handler(msg,self.bot)
        self.assertIn('Сначала выбери чат',msg.answer.call_args.args[0])
        self.assertEqual(await self.db.franc_balance(-100,10),1000)
        await self.db.select_menu_chat(10,-200)
        self.bot.get_chat_member.return_value.status='left'
        msg=self.message(private=True,mid=2)
        await self.handler(msg,self.bot)
        self.assertEqual(await self.db.franc_balance(-200,10),1000)
        self.bot.get_chat_member.return_value.status='member'
        msg=self.message(private=True,mid=3)
        await self.handler(msg,self.bot)
        row=self.db.connection.execute('SELECT * FROM franc_deposits').fetchone()
        self.assertEqual((row['chat_id'],row['message_chat_id']),(-200,10))
        self.assertEqual(await self.db.franc_balance(-100,10),1000)
        self.assertIn('Чат &lt;-200&gt;',msg.answer.call_args.args[0])

    async def test_anon_and_bot_messages_do_nothing(self):
        m=self.message();m.sender_chat=SimpleNamespace(id=-100)
        await self.handler(m,self.bot);m.answer.assert_not_called()
        m=self.message();m.from_user=m.from_user.model_copy(update={'is_bot':True})
        await self.handler(m,self.bot);m.answer.assert_not_called()

    async def test_all_win_loss_and_unrelated_wallet(self):
        won=await self.bet(stake='all',roll=0)
        self.assertEqual((won['stake'],won['payout'],won['balance_after']),(1000,5000,5000))
        self.clock+=60
        lost=await self.bet(stake='all',roll=99,mid=2)
        self.assertEqual((lost['stake'],lost['payout'],lost['balance_after']),(5000,0,0))
        self.assertEqual(await self.db.franc_balance(-200,10),1000)

    async def test_half_rounds_down_and_uses_current_balance(self):
        await self.db.credit_francs(-100,10,1)
        a=await self.bet(stake='half',mid=1)
        self.clock+=60
        b=await self.bet(stake='half',mid=2)
        self.assertEqual((a['stake'],b['stake']),(500,250))
        self.assertEqual(await self.db.franc_balance(-100,10),251)

    async def test_dynamic_replay_retains_original_stake_after_balance_change_and_restart(self):
        for mode,mid in (('half',1),('all',2)):
            original=await self.bet(stake=mode,roll=0,mid=mid)
            await self.db.credit_francs(-100,10,99)
            await self.db.close();await self.db.connect()
            before=await self.db.franc_balance(-100,10);rng=Fixed(99)
            self.assertEqual(await self.bet(stake=mode,mid=mid,rng=rng),original)
            self.assertEqual(rng.calls,0)
            self.assertEqual(await self.db.franc_balance(-100,10),before)
            self.clock+=60
        with self.assertRaises(ValueError):await self.bet(stake='half',mid=2)

    async def test_zero_tiny_overflow_dynamic_stakes_never_roll(self):
        rng=Fixed(0)
        for balance,mode in ((0,'all'),(0,'half'),(1,'half'),(MAX_FRANC_BALANCE,'all'),(MAX_FRANC_BALANCE,'half')):
            self.db.connection.execute('UPDATE franc_balances SET balance=? WHERE chat_id=-100 AND user_id=10',(balance,));self.db.connection.commit()
            with self.assertRaises(ValueError):await self.bet(stake=mode,rng=rng)
            self.assertEqual(await self.db.franc_balance(-100,10),balance)
        self.assertEqual(rng.calls,0)

    async def test_dynamic_command_private_context_and_displays_stake(self):
        await self.db.select_menu_chat(10,-200)
        msg=self.message('депнуть половину',private=True)
        await self.handler(msg,self.bot)
        self.assertIn('Ставка: <b>500 ₣</b>',msg.answer.call_args.args[0])
        row=self.db.connection.execute('SELECT * FROM franc_deposits').fetchone()
        self.assertEqual((row['chat_id'],row['stake_mode']),(-200,'half'))

    async def test_old_receipts_migrate_without_changing_amount_or_balance(self):
        old=await self.bet(roll=0)
        self.db.connection.execute('ALTER TABLE franc_deposits DROP COLUMN stake_mode');self.db.connection.commit()
        await self.db.close();await self.db.connect()
        self.assertEqual(await self.bet(roll=99),old)
        self.assertEqual(await self.db.franc_balance(-100,10),1400)

    async def test_cooldown_is_account_wide_and_warns_once(self):
        await self.bet()
        rng=Fixed(0)
        first=await self.bet(chat=-200,source=-200,mid=2,rng=rng)
        second=await self.bet(stake='all',source=10,mid=3,rng=rng)
        self.assertEqual(first,dict(blocked=True,notify=True,remaining=60))
        self.assertEqual(second,dict(blocked=True,notify=False,remaining=60))
        self.assertEqual(rng.calls,0)
        self.assertEqual(await self.db.franc_balance(-200,10),1000)
        self.assertEqual(await self.db.franc_balance(-100,10),900)

    async def test_attempts_never_extend_cooldown_and_rejected_message_cannot_play_later(self):
        await self.bet();self.clock+=5
        first=await self.bet(mid=2)
        self.assertEqual(first['remaining'],55)
        self.clock+=54
        self.assertEqual((await self.bet(mid=3))['remaining'],1)
        self.clock+=1
        self.assertFalse((await self.bet(mid=2))['notify']) # previously rejected message
        self.assertEqual((await self.bet(mid=4))['stake'],100)
        self.assertEqual(await self.db.franc_balance(-100,10),800)

    async def test_cooldown_and_warning_survive_restart(self):
        await self.bet();await self.bet(mid=2)
        self.clock+=20;await self.db.close();await self.db.connect()
        self.assertEqual(await self.bet(mid=3),dict(blocked=True,notify=False,remaining=40))
        self.clock+=40
        self.assertEqual((await self.bet(mid=4))['stake'],100)
        self.assertTrue((await self.bet(mid=5))['notify'])

    async def test_spam_handler_is_silent_after_first_warning_and_skips_membership(self):
        await self.bet()
        first=self.message('депнуть всё',private=True,mid=2)
        await self.handler(first,self.bot)
        self.assertIn('60 сек.',first.answer.call_args.args[0])
        second=self.message('депнуть мусор',private=True,mid=3)
        await self.handler(second,self.bot);second.answer.assert_not_called()
        self.bot.get_chat_member.assert_not_called()
        replay=self.message(mid=1);await self.handler(replay,self.bot);replay.answer.assert_not_called()

    async def test_errors_are_throttled_globally_without_delaying_valid_bet(self):
        first=self.message('депнуть -1',mid=1);await self.handler(first,self.bot)
        self.assertIn('Напиши:',first.answer.call_args.args[0])
        self.clock+=20
        second=self.message('депнуть 2000',mid=2);await self.handler(second,self.bot);second.answer.assert_not_called()
        self.clock+=10
        third=self.message('депнуть -1',mid=3);await self.handler(third,self.bot);third.answer.assert_called_once()
        valid=self.message('депнуть 100',mid=4);await self.handler(valid,self.bot)
        self.assertIn('Ставка: <b>100 ₣</b>',valid.answer.call_args.args[0])
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM franc_deposits').fetchone()[0],1)

    async def test_error_limit_persists_and_does_not_shift_on_spam(self):
        first=await self.db.deposit_error_gate(10,-100,1)
        self.assertTrue(first['notify'])
        self.clock+=10;await self.db.close();await self.db.connect()
        self.assertFalse((await self.db.deposit_error_gate(10,10,2))['notify'])
        self.clock+=20
        self.assertTrue((await self.db.deposit_error_gate(10,-200,3))['notify'])

    async def test_roll_failure_does_not_start_cooldown(self):
        self.db.connection.execute("CREATE TRIGGER fail_deposit BEFORE INSERT ON franc_deposits BEGIN SELECT RAISE(ABORT,'disk'); END")
        self.db.connection.commit()
        with self.assertRaises(Exception):await self.bet(roll=0)
        self.assertIsNone(await self.db.deposit_gate(10,-100,2))

    async def test_concurrent_handler_updates_do_not_duplicate_result_reply(self):
        first=self.message(mid=1);second=self.message(mid=1)
        await asyncio.gather(self.handler(first,self.bot),self.handler(second,self.bot))
        self.assertEqual(first.answer.call_count+second.answer.call_count,1)
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM franc_deposits').fetchone()[0],1)

    async def test_recent_legacy_bet_seeds_account_limit_on_migration(self):
        await self.bet()
        self.db.connection.execute('DROP TABLE franc_deposit_limits')
        self.db.connection.execute('DROP TABLE franc_deposit_rejections');self.db.connection.commit()
        self.clock+=20;await self.db.close();await self.db.connect()
        self.assertEqual(await self.bet(mid=2),dict(blocked=True,notify=True,remaining=40))

    async def test_other_accounts_have_independent_limits(self):
        await self.bet()
        await self.db.credit_francs(-100,20,100)
        result=await self.db.deposit_francs(-100,20,100,-100,2,Fixed(99))
        self.assertEqual((result['stake'],result['balance_after']),(100,0))
        self.assertTrue((await self.bet(mid=3))['blocked'])


if __name__=='__main__':unittest.main()
