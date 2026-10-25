import asyncio
import json
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import EditMessageText, SendMessage
from database import Database
from enterprises import CAPACITIES,config
from handlers.enterprises import create_enterprise_router,enterprise_menu,recovery_view,sweep_recovery_events
from slave_recovery import RECOVERY_GAME_SECONDS, RECOVERY_SYMBOLS, code_feedback


class Fixed:
    def random(self):return 0
    def randrange(self,n):return 0
    def sample(self,items,n):return list(items)[:n]
    def choice(self,items):return items[0]


class EnterpriseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'enterprise.sqlite'
        self.db=Database(self.path);await self.db.connect()
        self.clock=1800000000
        self.mock=patch('database.utc_timestamp',side_effect=lambda:self.clock);self.mock.start()
        for chat in (-100,-200):
            await self.db.upsert_chat(chat,'Чат')
            await self.db.upsert_user(chat,10,'owner','Владелец')
            await self.db.credit_francs(chat,10,10000)
            for user in range(100,126):
                await self.db.upsert_user(chat,user,f'u{user}',f'Участник {user}')
                await self.db.force_enslave(chat,user,10)
        self.db.connection.execute("UPDATE slave_identities SET luck=0,trait='survivor',rarity='common' WHERE user_id<>1980056841")
        self.db.connection.commit()

    async def asyncTearDown(self):
        self.mock.stop();await self.db.close();self.temp.cleanup()

    async def site(self,kind='custom',chat=-100):
        self.assertEqual(await self.db.create_business(chat,10,kind),'created')
        return await self.db.get_business(chat,10,business_type=kind)

    async def event(self):
        rows=await self.db.enterprise_due_recoveries(Fixed())
        row=next(r for r in rows if r['chat_id']==-100)
        await self.db.recovery_published(row['id'],-100,999)
        return await self.db.recovery_get(row['id'])

    async def guess(self,event,values):
        for value in values:event=await self.db.recovery_action(event['id'],10,event['revision'],str(value))
        return event

    async def test_three_different_types_custom_unique_and_chat_local_cost(self):
        for kind in ('tavern','mine','custom'):await self.site(kind)
        balance=await self.db.franc_balance(-100,10)
        self.assertEqual(balance,8000)
        self.assertEqual(await self.db.create_business(-100,10,'custom'),'exists')
        self.assertEqual(await self.db.create_business(-100,10,'workshop'),'limit')
        self.assertEqual(await self.db.franc_balance(-100,10),balance)
        await self.site('custom',-200)
        self.assertEqual(await self.db.franc_balance(-200,10),9250)
        self.assertEqual(await self.db.franc_balance(-100,10),balance)

    async def test_creation_and_upgrade_are_atomic_on_replay_or_insufficient(self):
        results=await asyncio.gather(self.db.create_business(-100,10,'mine'),self.db.create_business(-100,10,'mine'))
        self.assertCountEqual(results,['created','exists'])
        site=await self.db.get_business(-100,10)
        results=await asyncio.gather(self.db.enterprise_upgrade(-100,10,site['id'],1),self.db.enterprise_upgrade(-100,10,site['id'],1))
        self.assertCountEqual(results,['upgraded','stale'])
        self.assertEqual(await self.db.franc_balance(-100,10),8850)
        self._balance(50)
        self.assertEqual(await self.db.enterprise_upgrade(-100,10,site['id'],2),'insufficient')
        self.assertEqual((await self.db.get_business(-100,10))['level'],2)

    def _balance(self,n):
        self.db.connection.execute('UPDATE franc_balances SET balance=? WHERE chat_id=-100 AND user_id=10',(n,));self.db.connection.commit()

    async def test_capacity_leader_cap_and_levels(self):
        site=await self.site();sid=site['id']
        self.assertEqual(await self.db.enterprise_assign(-100,10,100,'leader',sid),'updated')
        self.assertEqual(await self.db.enterprise_assign(-100,10,101,'leader',sid),'leader_full')
        for worker in range(101,110):self.assertEqual(await self.db.enterprise_assign(-100,10,worker,'worker',sid),'updated')
        self.assertEqual(await self.db.enterprise_assign(-100,10,110,'worker',sid),'full')
        self.assertEqual(await self.db.enterprise_upgrade(-100,10,sid,1),'upgraded')
        for worker in range(110,115):self.assertEqual(await self.db.enterprise_assign(-100,10,worker,'worker',sid),'updated')
        self.assertEqual(await self.db.enterprise_assign(-100,10,115,'worker',sid),'full')
        self.assertEqual(await self.db.enterprise_upgrade(-100,10,sid,2),'upgraded')
        for worker in range(115,120):self.assertEqual(await self.db.enterprise_assign(-100,10,worker,'worker',sid),'updated')
        self.assertEqual(await self.db.enterprise_assign(-100,10,120,'worker',sid),'full')
        self.assertEqual(len((await self.db.enterprise_view(-100,sid,10))['workers']),20)

    async def test_moves_settle_old_job_and_never_double_assign(self):
        a=await self.site('mine');b=await self.site('workshop')
        await self.db.enterprise_assign(-100,10,100,'worker',a['id'])
        self.clock+=3600
        await self.db.enterprise_assign(-100,10,100,'worker',b['id'])
        self.assertEqual((await self.db.enterprise_view(-100,a['id']))['workers'],[])
        self.clock+=3600;await self.db.settle_business(-100,10)
        rows=self.db.connection.execute('SELECT business_id,gross_income FROM enterprise_income_daily ORDER BY business_id').fetchall()
        self.assertEqual([(r[0],r[1]) for r in rows],[(a['id'],3),(b['id'],4)])
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM business_workers WHERE chat_id=-100 AND worker_id=100').fetchone()[0],1)

    async def test_name_description_roles_validate_and_escape_without_changing_pay(self):
        a=await self.site();b=await self.site('tavern')
        await self.db.enterprise_edit(-100,10,a['id'],'name','<Моя & компания>')
        await self.db.enterprise_edit(-100,10,a['id'],'description','Описание\nВторая строка')
        await self.db.enterprise_edit(-100,10,a['id'],'producer_title','Легенда')
        with self.assertRaises(ValueError):await self.db.enterprise_edit(-100,10,b['id'],'producer_title','Легенда')
        with self.assertRaises(ValueError):await self.db.enterprise_edit(-100,11,a['id'],'name','Взлом')
        with self.assertRaises(ValueError):await self.db.enterprise_edit(-100,10,a['id'],'owner_id','11')
        with self.assertRaises(ValueError):await self.db.enterprise_edit(-100,10,a['id'],'name','x'*61)
        body,kb=await enterprise_menu(self.db,10,-100)
        self.assertIn('&lt;Моя &amp; компания&gt;',body)
        self.assertEqual(config(await self.db.get_business(-100,10,a['id']))['owner_per_producer'],3)
        self.assertTrue(all(len(b.callback_data.encode())<=64 for row in kb.inline_keyboard for b in row))

    async def test_shared_shift_cooldown_across_sites(self):
        a=await self.site('tavern');b=await self.site('mine')
        with patch('database.random.randint',return_value=50):
            first=await self.db.work_at_business(-100,10,100,a['id'])
            second=await self.db.work_at_business(-100,10,100,b['id'])
        self.assertEqual(first[0],'worked');self.assertEqual(second[0],'cooldown')
        ledger=await self.db.enterprise_statistics(-100,10,a['id'])
        self.assertEqual(sum(r['gross_income'] for r in ledger),3)
        self.assertEqual(await self.db.enterprise_statistics(-100,10,b['id']),[])

    async def test_recovery_threshold_cooldowns_and_no_absence_before_publication(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        rows=await self.db.enterprise_due_recoveries(Fixed());row=next(r for r in rows if r['chat_id']==-100)
        self.assertFalse((await self.db.enterprise_view(-100,site['id']))['workers'][0]['away'])
        await self.db.recovery_published(row['id'],-100,999)
        self.assertTrue((await self.db.enterprise_view(-100,site['id']))['workers'][0]['away'])
        self.assertEqual(await self.db.enterprise_due_recoveries(Fixed()),[])
        await self.db.recovery_cancel_publication(row['id']) # pending cannot be cancelled by publication retry
        self.assertEqual((await self.db.recovery_get(row['id']))['status'],'pending')
        self.assertEqual((await self.db.recovery_get(row['id']))['deadline'],self.clock+300)

    async def test_success_preserves_job_restart_and_stale_button_no_double_step(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        event=await self.event()
        with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],11,0,'start')
        event=await self.db.recovery_action(event['id'],10,0,'start')
        event=await self.db.recovery_action(event['id'],10,event['revision'],'0')
        with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],10,event['revision']-1,'0')
        self.assertEqual(json.loads(event['guess_json']),[0])
        deadline=event['deadline'];self.clock+=40
        await self.db.close();await self.db.connect()
        event=await self.db.recovery_get(event['id'])
        self.assertEqual(json.loads(event['guess_json']),[0])
        self.assertEqual(event['deadline'],deadline)
        event=await self.guess(event,[1,2])
        self.assertEqual(event['status'],'returned')
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],10)
        self.assertEqual(len((await self.db.enterprise_view(-100,site['id']))['workers']),1)

    async def test_six_failed_codes_release_only_that_slave_in_that_chat(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        event=await self.event();event=await self.db.recovery_action(event['id'],10,0,'start')
        for _ in range(6):event=await self.guess(event,[3,4,5])
        self.assertEqual(event['status'],'lost')
        self.assertIsNone(await self.db.get_owner(-100,100))
        self.assertIsNotNone(await self.db.get_owner(-100,101))
        self.assertIsNotNone(await self.db.get_owner(-200,100))
        self.assertEqual((await self.db.enterprise_view(-100,site['id']))['workers'],[])
        with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],10,event['revision'],'start')

    async def test_unopened_event_expires_five_minutes_after_publication(self):
        event=await self.event();self.clock+=299
        await self.db.recovery_expire()
        self.assertIsNotNone(await self.db.get_owner(-100,100))
        self.clock+=1
        await self.db.recovery_expire()
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'lost')
        self.assertIsNone(await self.db.get_owner(-100,100))

    async def test_transfer_or_release_cancels_old_event_and_cannot_reclaim(self):
        event=await self.event()
        await self.db.upsert_user(-100,30,'next','Следующий')
        await self.db.transfer_slave(-100,10,100,30)
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],10,0,'start')
        self.assertEqual((await self.db.get_owner(-100,100))['owner_id'],30)

    async def test_failed_delivery_never_pauses_and_old_bot_message_cannot_start(self):
        rows=await self.db.enterprise_due_recoveries(Fixed());event=rows[0]
        await self.db.recovery_cancel_publication(event['id'])
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        self.assertIsNotNone(await self.db.get_owner(event['chat_id'],event['slave_id']))
        self.assertFalse(await self.db.recovery_published(event['id'],event['chat_id'],1))

    async def test_tax_brackets_are_shared_not_reset_for_each_site(self):
        a=await self.site('mine');b=await self.site('workshop')
        for user in range(100,110):await self.db.enterprise_assign(-100,10,user,'worker',a['id'])
        for user in range(110,120):await self.db.enterprise_assign(-100,10,user,'worker',b['id'])
        self.clock+=12*3600
        result=await self.db.settle_business(-100,10)
        self.assertEqual(result['gross_income'],840)
        from database import business_income_tax
        # The twelve hours can straddle Moscow midnight; compare per-day sums.
        totals=self.db.connection.execute('SELECT gross_income,tax_paid FROM business_tax_daily WHERE chat_id=-100 AND owner_id=10').fetchall()
        self.assertEqual(sum(r['tax_paid'] for r in totals),sum(business_income_tax(r['gross_income']) for r in totals))
        self.assertGreater(sum(r['tax_paid'] for r in totals),0)

    async def test_no_income_while_away_and_publication_failure_is_non_destructive(self):
        site=await self.site('mine');await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        event=await self.event();self.clock+=60
        self.assertEqual(await self.db.enterprise_assign(-100,10,100,'worker',site['id']),'away')
        event=await self.db.recovery_action(event['id'],10,0,'start')
        event=await self.guess(event,[0,1,2])
        self.clock+=3540
        self.assertEqual((await self.db.settle_business(-100,10))['gross_income'],0)
        self.clock+=3600
        self.assertEqual((await self.db.settle_business(-100,10))['gross_income'],3)

    async def test_module_disable_cancels_without_losing_owner(self):
        event=await self.event();event=await self.db.recovery_action(event['id'],10,0,'start')
        await self.db.arena_set_module(-100,10,'slavery',False,0)
        # Even re-enabling before the background sweep cannot revive the timer.
        await self.db.arena_set_module(-100,10,'slavery',True,1)
        self.clock+=301;await self.db.recovery_expire()
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        self.assertIsNotNone(await self.db.get_owner(-100,100))

    async def test_private_menu_callback_create_edit_upgrade_and_forged_owner(self):
        router=create_enterprise_router(self.db)
        handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='enterprise_callback')
        state=FSMContext(storage=MemoryStorage(),key=StorageKey(bot_id=1,chat_id=10,user_id=10))
        bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))
        def callback(data,actor=10):return SimpleNamespace(data=data,from_user=SimpleNamespace(id=actor),
            answer=AsyncMock(),message=SimpleNamespace(chat=SimpleNamespace(id=actor,type='private'),message_id=1,edit_text=AsyncMock()))
        cb=callback('ent:create:-100:custom');await handler(cb,state,bot)
        site=await self.db.get_business(-100,10)
        self.assertIsNotNone(site)
        cb=callback(f'ent:edit:-100:{site["id"]}:name');await handler(cb,state,bot)
        self.assertEqual(await state.get_state(),'EnterpriseEdit:value')
        text_handler=next(h.callback for h in router.message.handlers if h.callback.__name__=='enterprise_text')
        msg=SimpleNamespace(text='<Фирма>',from_user=SimpleNamespace(id=10),answer=AsyncMock())
        await text_handler(msg,state,bot)
        self.assertIn('&lt;Фирма&gt;',msg.answer.await_args.args[0])
        await self.db.upsert_user(-100,11,'other','Другой')
        before=await self.db.franc_balance(-100,10)
        cb=callback(f'ent:up:-100:{site["id"]}:1',11);await handler(cb,state,bot)
        self.assertEqual((await self.db.get_business(-100,10))['level'],1)
        self.assertEqual(await self.db.franc_balance(-100,10),before)
        cb=callback(f'ent:up:-100:{site["id"]}:1');await handler(cb,state,bot)
        self.assertEqual((await self.db.get_business(-100,10))['level'],2)

        # A guessed ID from another chat cannot edit the current chat's site.
        cb=callback(f'ent:up:-200:{site["id"]}:2');await handler(cb,state,bot)
        self.assertEqual((await self.db.get_business(-100,10))['level'],2)
        await state.set_state('EnterpriseEdit:value')
        await state.set_data(dict(chat=-100,site=site['id'],field='name'))
        await self.db.arena_set_module(-100,10,'slavery',False,0)
        msg=SimpleNamespace(text='Нельзя изменить',from_user=SimpleNamespace(id=10),answer=AsyncMock())
        await text_handler(msg,state,bot)
        self.assertEqual((await self.db.get_business(-100,10))['name'],'<Фирма>')

    async def test_reacquiring_after_release_does_not_reactivate_an_old_game(self):
        event=await self.event()
        await self.db.release_slave(-100,10,100)
        await self.db.force_enslave(-100,100,10)
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],10,0,'start')
        self.assertIsNotNone(await self.db.get_owner(-100,100))

    async def test_twenty_slaves_or_fewer_do_not_trigger_events(self):
        for chat in (-100,-200):
            for slave in range(120,126):await self.db.release_slave(chat,10,slave)
        self.assertEqual(await self.db.enterprise_due_recoveries(Fixed()),[])

    async def test_insufficient_creation_never_charges_or_creates(self):
        self._balance(749)
        self.assertEqual(await self.db.create_business(-100,10,'mine'),'insufficient')
        self.assertIsNone(await self.db.get_business(-100,10))
        self.assertEqual(await self.db.franc_balance(-100,10),749)

    async def test_existing_overcapacity_jobs_preserved_and_legacy_income_not_cut(self):
        site=await self.site('mine')
        for user in range(100,113):
            self.db.connection.execute('INSERT INTO business_workers(chat_id,owner_id,worker_id,role,assigned_at,business_id) VALUES(-100,10,?,?,?,?)',
                (user,'leader' if user<102 else 'worker',self.clock,site['id']))
        self.db.connection.execute('UPDATE businesses SET rules_since=? WHERE id=?',(self.clock+3600,site['id']))
        self.db.connection.commit();self.clock+=3600
        # Legacy: eleven producers and two managers (+20% and +10%).
        self.assertEqual((await self.db.settle_business(-100,10))['gross_income'],42)
        self.clock+=3600
        # New: nine producers plus one manager. Fractional carry is retained.
        self.assertEqual((await self.db.settle_business(-100,10))['gross_income'],33)
        self.assertEqual(len((await self.db.enterprise_view(-100,site['id']))['workers']),13)

    async def test_start_screen_delivery_failure_cancels_without_timeout_loss(self):
        event=await self.event();router=create_enterprise_router(self.db)
        handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='recovery_callback')
        error=TelegramNetworkError(method=EditMessageText(chat_id=-100,message_id=999,text='game'),message='offline')
        cb=SimpleNamespace(data=f'rec:{event["id"]}:0:start',from_user=SimpleNamespace(id=10),answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100,type='supergroup'),message_id=999,edit_text=AsyncMock(side_effect=error)))
        bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))
        await handler(cb,bot)
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        self.clock+=301;await self.db.recovery_expire()
        self.assertIsNotNone(await self.db.get_owner(-100,100))

    async def test_delivery_cancel_does_not_undo_newer_step_or_final_result(self):
        event=await self.event();event=await self.db.recovery_action(event['id'],10,0,'start')
        previous=event['revision'];event=await self.db.recovery_action(event['id'],10,event['revision'],'0')
        await self.db.recovery_cancel_delivery(event['id'],10,previous)
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'playing')
        event=await self.guess(event,[1,2]) # a completed game cannot be undone by a failed delivery
        await self.db.recovery_cancel_delivery(event['id'],10,event['revision'])
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'returned')
        self.assertIsNotNone(await self.db.get_owner(-100,100))

    async def test_sweep_send_failure_cancels_unpublished_event(self):
        events=await self.db.enterprise_due_recoveries(Fixed())
        bot=SimpleNamespace(send_message=AsyncMock(side_effect=TelegramNetworkError(
            method=SendMessage(chat_id=-100,text='event'),message='offline')))
        with patch.object(self.db,'enterprise_due_recoveries',AsyncMock(return_value=events)):
            await sweep_recovery_events(self.db,bot)
        for row in events:
            self.assertEqual((await self.db.recovery_get(row['id']))['status'],'cancelled')
            self.assertIsNotNone(await self.db.get_owner(row['chat_id'],row['slave_id']))

    async def test_publication_not_creation_starts_clock_and_late_start_never_extends_it(self):
        rows=await self.db.enterprise_due_recoveries(Fixed());event=rows[0]
        self.clock+=45
        await self.db.recovery_published(event['id'],event['chat_id'],999)
        event=await self.db.recovery_get(event['id']);deadline=self.clock+RECOVERY_GAME_SECONDS
        self.assertEqual(event['deadline'],deadline)
        self.clock+=240
        event=await self.db.recovery_action(event['id'],10,0,'start')
        self.assertEqual(event['deadline'],deadline)
        for action in ('view','undo','clear'):
            event=await self.db.recovery_action(event['id'],10,event['revision'],action)
            self.assertEqual(event['deadline'],deadline)
        self.clock=deadline
        event=await self.db.recovery_action(event['id'],10,0,'view')
        self.assertEqual(event['status'],'lost')

    async def test_feedback_history_and_partial_code_survive_restart_without_revealing_secret(self):
        event=await self.event()
        self.db.connection.execute('UPDATE slave_recovery_events SET pattern_json=? WHERE id=?',(json.dumps([5,1,3]),event['id']))
        self.db.connection.commit()
        event=await self.db.recovery_action(event['id'],10,0,'start')
        event=await self.guess(event,[0,1,2])
        history=json.loads(event['history_json'])
        self.assertEqual(history,[dict(guess=[0,1,2],exact=1,misplaced=0)])
        self.assertEqual(json.loads(event['guess_json']),[])
        event=await self.guess(event,[5])
        await self.db.close();await self.db.connect()
        event=await self.db.recovery_get(event['id'])
        self.assertEqual(json.loads(event['guess_json']),[5])
        self.assertEqual(json.loads(event['history_json']),history)
        body,markup=await recovery_view(self.db,event)
        self.assertNotIn('👁 🌙 💀',body)
        self.assertIn('на месте: 1, не на месте: 0',body)
        self.assertIn('Попытка 2/6',body)
        self.assertTrue(all(len(b.callback_data.encode())<=64 for row in markup.inline_keyboard for b in row))

    async def test_duplicate_invalid_symbols_and_replayed_callbacks_do_not_consume_attempts(self):
        event=await self.event();event=await self.db.recovery_action(event['id'],10,0,'start')
        revision=event['revision']
        results=await asyncio.gather(*(self.db.recovery_action(event['id'],10,revision,'0') for _ in range(2)),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,ValueError) for r in results),1)
        event=await self.db.recovery_get(event['id'])
        for invalid in ('0','6','-1','start','guess:123'):
            with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],10,event['revision'],invalid)
        unchanged=await self.db.recovery_get(event['id'])
        self.assertEqual(event,unchanged)
        self.assertEqual(json.loads(event['history_json']),[])
        self.assertEqual(json.loads(event['guess_json']),[0])

    async def test_undo_clear_and_sixth_attempt_can_win(self):
        event=await self.event();event=await self.db.recovery_action(event['id'],10,0,'start')
        event=await self.guess(event,[0,1])
        event=await self.db.recovery_action(event['id'],10,event['revision'],'undo')
        self.assertEqual(json.loads(event['guess_json']),[0])
        event=await self.db.recovery_action(event['id'],10,event['revision'],'clear')
        self.assertEqual(json.loads(event['guess_json']),[])
        for _ in range(5):event=await self.guess(event,[3,4,5])
        self.assertEqual(event['status'],'playing')
        event=await self.guess(event,[0,1,2])
        self.assertEqual(event['status'],'returned')
        self.assertEqual(len(json.loads(event['history_json'])),6)

    async def test_schedule_and_recent_activity_are_local_to_each_chat(self):
        from datetime import datetime
        from slave_recovery import RECOVERY_TZ
        day=datetime.fromtimestamp(self.clock,RECOVERY_TZ).replace(hour=0,minute=0,second=0)
        for hour,minute,second,eligible in ((9,59,59,False),(10,0,0,True),(21,59,59,True),(22,0,0,False),(0,0,0,False)):
            self.clock=int(day.replace(hour=hour,minute=minute,second=second).timestamp())
            self.db.connection.execute('DELETE FROM slave_recovery_events')
            self.db.connection.execute('UPDATE users SET last_seen=? WHERE user_id=10',(self.clock,))
            self.db.connection.commit()
            rows=await self.db.enterprise_due_recoveries(Fixed())
            self.assertEqual(len(rows),2 if eligible else 0)
        self.clock=int(day.replace(hour=12).timestamp())
        self.db.connection.execute('DELETE FROM slave_recovery_events')
        self.db.connection.execute('UPDATE users SET last_seen=? WHERE user_id=10 AND chat_id=-100',(self.clock-3600,))
        self.db.connection.execute('UPDATE users SET last_seen=? WHERE user_id=10 AND chat_id=-200',(self.clock-3601,))
        self.db.connection.commit()
        self.assertEqual([r['chat_id'] for r in await self.db.enterprise_due_recoveries(Fixed())],[-100])

    async def test_legacy_memory_games_are_cancelled_without_losing_slaves(self):
        site=await self.site();await self.db.enterprise_assign(-100,10,100,'worker',site['id'])
        event=await self.event()
        self.db.connection.execute("UPDATE slave_recovery_events SET game_type='memory',deadline=NULL WHERE id=?",(event['id'],))
        self.db.connection.commit();await self.db.close();await self.db.connect()
        event=await self.db.recovery_get(event['id'])
        self.assertEqual(event['status'],'cancelled')
        self.assertIsNotNone(await self.db.get_owner(-100,100))
        self.assertEqual(len((await self.db.enterprise_view(-100,site['id']))['workers']),1)
        with self.assertRaises(ValueError):await self.db.recovery_action(event['id'],10,0,'start')

    async def test_timer_view_is_snapshot_and_uses_absolute_moscow_deadline(self):
        event=await self.event();self.clock+=61
        body,_=await recovery_view(self.db,event)
        self.assertIn('03:59',body)
        self.assertIn('11:05:00 МСК',body)
        self.assertIn('даже без участия',body)

    async def test_pending_refresh_delivery_failure_also_cancels_timer(self):
        event=await self.event();router=create_enterprise_router(self.db)
        handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='recovery_callback')
        cb=SimpleNamespace(data=f'rec:{event["id"]}:0:view',from_user=SimpleNamespace(id=10),answer=AsyncMock(),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100,type='supergroup'),message_id=999,
                edit_text=AsyncMock(side_effect=TelegramNetworkError(method=EditMessageText(chat_id=-100,message_id=999,text='game'),message='offline'))))
        bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')))
        await handler(cb,bot)
        self.clock+=301;await self.db.recovery_expire()
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        self.assertIsNotNone(await self.db.get_owner(-100,100))

    async def test_telegram_membership_service_failure_does_not_cost_a_slave(self):
        event=await self.event();router=create_enterprise_router(self.db)
        handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='recovery_callback')
        cb=SimpleNamespace(data=f'rec:{event["id"]}:0:start',from_user=SimpleNamespace(id=10),answer=AsyncMock())
        bot=SimpleNamespace(get_chat_member=AsyncMock(side_effect=asyncio.TimeoutError()))
        await handler(cb,bot)
        self.clock+=301;await self.db.recovery_expire()
        self.assertEqual((await self.db.recovery_get(event['id']))['status'],'cancelled')
        self.assertIsNotNone(await self.db.get_owner(-100,100))


class RecoveryFeedbackTests(unittest.TestCase):
    def test_exact_misplaced_and_absent(self):
        self.assertEqual(code_feedback([0,1,2],[0,1,2]),(3,0))
        self.assertEqual(code_feedback([0,1,2],[1,2,0]),(0,3))
        self.assertEqual(code_feedback([0,1,2],[0,2,3]),(1,1))
        self.assertEqual(code_feedback([0,1,2],[3,4,5]),(0,0))

    def test_all_generated_codes_are_three_distinct_symbols(self):
        from itertools import permutations
        for secret in permutations(range(len(RECOVERY_SYMBOLS)),3):
            self.assertEqual(code_feedback(secret,secret),(3,0))


class EnterpriseMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_schema_preserves_jobs_wages_pending_income_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.sqlite';clock=1800000000
            with sqlite3.connect(path) as conn:
                conn.executescript('''CREATE TABLE businesses(chat_id INTEGER,owner_id INTEGER,
                    business_type TEXT CHECK(business_type IN ('brothel','field')),
                    created_at INTEGER,last_accrued INTEGER,income_remainder INTEGER DEFAULT 0,PRIMARY KEY(chat_id,owner_id));
                    CREATE TABLE business_workers(chat_id INTEGER,owner_id INTEGER,worker_id INTEGER,
                    role TEXT,assigned_at INTEGER,wage_hours INTEGER DEFAULT 0,PRIMARY KEY(chat_id,owner_id,worker_id));''')
                conn.execute("INSERT INTO businesses VALUES(-100,10,'field',?,?,50)",(clock-7200,clock-3600))
                conn.execute("INSERT INTO business_workers VALUES(-100,10,100,'collector',?,5)",(clock-7200,))
            conn.close()
            db=Database(path)
            try:
                with patch('database.utc_timestamp',return_value=clock):
                    with patch.object(db,'_enterprise_backup_before_migration',side_effect=OSError('disk full')):
                        with self.assertRaises(OSError):await db.connect()
                    self.assertNotIn('id',[r['name'] for r in db.connection.execute('PRAGMA table_info(businesses)')])
                    self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM businesses').fetchone()[0],1)
                    await db.close()
                    await db.connect();await db.upsert_chat(-100,'Чат')
                    for user in (10,100):await db.upsert_user(-100,user,str(user),str(user))
                    db.connection.execute('INSERT INTO ownership(chat_id,owner_id,slave_id,acquired_at) VALUES(-100,10,100,?)',(clock-7200,));db.connection.commit()
                    site=await db.get_business(-100,10)
                    self.assertEqual(site['income_remainder'],50)
                    worker=db.connection.execute('SELECT * FROM business_workers').fetchone()
                    self.assertEqual(worker['business_id'],site['id']);self.assertEqual(worker['wage_hours'],5)
                    await db.settle_business(-100,10)
                    self.assertEqual(await db.franc_balance(-100,10),3)
                    self.assertEqual(await db.franc_balance(-100,100),1)
                    await db.close();await db.connect();await db.settle_business(-100,10)
                    self.assertEqual(await db.franc_balance(-100,10),3)
                    self.assertEqual(len(await db.list_owned_businesses(10)),1)
                    self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM businesses_legacy_backup').fetchone()[0],1)
                    copies=list((path.parent/'backups').glob('before-enterprises-*.sqlite3'))
                    self.assertEqual(len(copies),1)
                    snapshot=sqlite3.connect(copies[0])
                    try:
                        self.assertEqual(snapshot.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                        self.assertEqual(snapshot.execute('SELECT business_type FROM businesses').fetchone()[0],'field')
                        self.assertNotIn('id',[r[1] for r in snapshot.execute('PRAGMA table_info(businesses)')])
                    finally:snapshot.close()
            finally:await db.close()


if __name__=='__main__':unittest.main()
