"""Telegram/API share one guild lobby. No real Telegram IO or production DB."""
import asyncio
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from aiogram.exceptions import TelegramForbiddenError,TelegramRetryAfter
from aiogram.methods import SendMessage,EditMessageText
from aiohttp.test_utils import TestClient,TestServer
from handlers.guild import GuildPublisher,create_guild_router,guild_chat_action,GUILD_RE,HUNT_RE,INVITE_RE
from arena_guild_rules import CONTRACTS,contract_by_code
from arena_web import create_arena_app
import test_guild as fixtures
from test_arena import signed,TOKEN


class GuildChatTests(unittest.IsolatedAsyncioTestCase):
    create=fixtures.GuildTests.create
    asyncTearDown=fixtures.GuildTests.asyncTearDown

    async def asyncSetUp(self):
        await fixtures.GuildTests.asyncSetUp(self)
        self.sent=100
        async def send(*args,**kwargs):
            self.sent+=1;return NS(message_id=self.sent)
        self.bot.send_message=AsyncMock(side_effect=send)
        self.bot.edit_message_text=AsyncMock()
        self.pub=GuildPublisher(self.db,self.bot,'TestBot')
        self.router=create_guild_router(self.db,self.bot,'TestBot',True,self.pub)

    def message(self,text,actor=10,chat=-100,ident=15):
        return NS(text=text,caption=None,message_id=ident,
            chat=NS(id=chat,type='private' if chat>0 else 'supergroup',title='Охотники'),
            from_user=NS(id=actor,is_bot=False,username=str(actor),full_name='Охотник '+str(actor)),answer=AsyncMock())

    async def click(self,run,action,actor=10,chat=-100,message_id=None):
        _,post=await self.db.guild_publication(run['id'])
        callback=NS(data='gg:'+action+':'+run['id'],from_user=self.message('',actor).from_user,
            message=NS(chat=NS(id=chat,type='supergroup',title='Охотники'),message_id=message_id or post['message_id']),answer=AsyncMock())
        await self.router.callback_query.handlers[0].callback(callback)
        return callback

    async def publish(self,key='c_dungeon'):
        run=await self.create(key)
        return await self.pub.invite(run['id'],10)

    async def test_codes_and_commands_are_unambiguous(self):
        self.assertEqual(len({c['code'] for c in CONTRACTS.values()}),21)
        for key,c in CONTRACTS.items():self.assertEqual(contract_by_code(c['code'].lower()),key)
        self.assertEqual(contract_by_code('С3'),'c_dungeon')
        for bad in ('F4','SS1','/охота F1','f_hunt',''):
            with self.assertRaises(ValueError):contract_by_code(bad)
        self.assertTrue(HUNT_RE.fullmatch('/охота@TestBot F1'))
        self.assertTrue(INVITE_RE.fullmatch('/позвать@TestBot'))
        self.assertTrue(GUILD_RE.fullmatch('/заказы'))

    async def test_board_private_group_and_hunt_private_help(self):
        for chat,param in ((-100,'guildboard_-100'),(10,'guildboard')):
            msg=self.message('/заказы',chat=chat)
            await self.router.message.handlers[0].callback(msg)
            self.assertTrue(msg.answer.call_args.kwargs['reply_markup'].inline_keyboard[0][0].url.endswith('startapp='+param))
        msg=self.message('/охота F1',chat=10)
        await self.router.message.handlers[1].callback(msg)
        self.assertIn('в группе',msg.answer.call_args.args[0]);self.bot.send_message.assert_not_awaited()

    async def test_hunt_publishes_once_and_redelivery_does_not_create_another_lobby(self):
        msg=self.message('/охота C3')
        await self.router.message.handlers[1].callback(msg)
        run=await self.db.guild_current(-100,10)
        self.assertEqual(run['contract']['code'],'C3');self.assertTrue(run['invite']['posted'])
        self.assertEqual(self.db._guild_used_locked(10),0)
        self.bot.send_message.assert_awaited_once();self.bot.edit_message_text.assert_not_awaited()
        await self.router.message.handlers[1].callback(msg)
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.db.connection.execute('SELECT COUNT(*) FROM guild_runs').fetchone()[0],1)

    async def test_invite_ownership_cooldown_and_repost_retire_old_card(self):
        run=await self.create()
        with self.assertRaises(ValueError):await self.pub.invite(run['id'],20)
        run=await self.pub.invite(run['id'],10)
        _,old=await self.db.guild_publication(run['id'])
        with self.assertRaises(ValueError):await GuildPublisher(self.db,self.bot,'TestBot').invite(run['id'],10)
        now=int(time.time())
        with patch('arena_guild.time.time',return_value=now+301):run=await self.pub.invite(run['id'],10)
        self.assertEqual(self.bot.send_message.await_count,2)
        self.assertTrue(any(c.kwargs.get('message_id')==old['message_id'] for c in self.bot.edit_message_text.await_args_list))
        stale=await self.click(run,'join',20,message_id=old['message_id'])
        self.assertTrue(stale.answer.call_args.kwargs['show_alert'])
        self.assertEqual(len((await self.db.guild_get(run['id'],10))['members']),1)

    async def test_concurrent_invites_have_a_single_persistent_claim(self):
        run=await self.create()
        results=await asyncio.gather(self.pub.invite(run['id'],10),GuildPublisher(self.db,self.bot,'TestBot').invite(run['id'],10),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.bot.send_message.assert_awaited_once()

    async def test_cancelling_and_recreating_cannot_bypass_invite_cooldown(self):
        run=await self.publish()
        await guild_chat_action(self.db,run['id'],10,'leave')
        other=await self.create('c_hunt')
        self.assertGreater(other['invite']['available_at'],time.time())
        with self.assertRaises(ValueError):await self.pub.invite(other['id'],10)
        self.bot.send_message.assert_awaited_once()

    async def test_failed_send_releases_claim_without_spending_daily_allowance(self):
        run=await self.create()
        send=self.bot.send_message.side_effect
        self.bot.send_message.side_effect=TelegramForbiddenError(method=SendMessage(chat_id=-100,text='x'),message='Forbidden')
        with self.assertRaises(ValueError):await self.pub.invite(run['id'],10)
        self.assertEqual(self.db._guild_used_locked(10),0)
        _,post=await self.db.guild_publication(run['id']);self.assertEqual(post['claim'],'');self.assertEqual(post['last_posted'],0)
        self.bot.send_message.side_effect=send
        self.assertTrue((await self.pub.invite(run['id'],10))['invite']['posted'])

    async def test_chat_buttons_join_leave_start_and_leader_only(self):
        run=await self.publish()
        await self.click(run,'join',20)
        self.assertEqual(len((await self.db.guild_get(run['id'],10))['members']),2)
        for action in ('start','cancel'):
            denied=await self.click(run,action,20);self.assertTrue(denied.answer.call_args.kwargs['show_alert'])
        await self.click(run,'leave',20)
        self.assertEqual(len((await self.db.guild_get(run['id'],10))['members']),1)
        await self.click(run,'join',20)
        await self.click(run,'start')
        await self.click(run,'start')
        run=await self.db.guild_get(run['id'],10)
        self.assertEqual(run['status'],'active');self.assertEqual(self.db._guild_used_locked(10),0);self.assertEqual(self.db._guild_used_locked(20),0)
        text,keyboard=self.pub.card(run)
        self.assertIn('Поход начался',text)
        self.assertIn('startapp=guildrun_',keyboard.inline_keyboard[0][0].url)
        self.assertFalse(any(b.callback_data for row in keyboard.inline_keyboard for b in row))
        with self.assertRaises(ValueError):await self.pub.invite(run['id'],10)

    async def test_concurrent_join_capacity_and_idempotent_repeat(self):
        run=await self.publish('f_hunt')
        await self.db.upsert_user(-100,40,'40','Четвёртый')
        results=await asyncio.gather(*(guild_chat_action(self.db,run['id'],a,'join') for a in (20,30,40)),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,dict) for r in results),2)
        run=await self.db.guild_get(run['id'],10)
        self.assertEqual(len(run['members']),3)
        await guild_chat_action(self.db,run['id'],run['members'][1]['actor_id'],'join')
        self.assertEqual(self.db._guild_used_locked(10),0)

    async def test_rank_choice_and_chat_enforced_but_daily_wins_allow_join(self):
        run=await self.publish()
        forwarded=await self.click(run,'join',20,chat=-200)
        self.assertTrue(forwarded.answer.call_args.kwargs['show_alert'])
        self.db.connection.execute('UPDATE guild_hunters SET rank=0 WHERE actor_id=20');self.db.connection.commit()
        denied=await self.click(run,'join',20);self.assertTrue(denied.answer.call_args.kwargs['show_alert'])
        self.db.connection.execute('UPDATE guild_hunters SET rank=3 WHERE actor_id=20')
        from arena_raid import raid_day
        self.db.connection.execute('INSERT INTO guild_reward_days VALUES(?,?,3)',(20,raid_day()));self.db.connection.commit()
        joined=await self.click(run,'join',20);self.assertFalse(joined.answer.call_args.kwargs.get('show_alert',False))
        await self.click(run,'leave',20)
        self.db.connection.execute("UPDATE personal_profiles SET level=10,progression_level=5,progression_pending_level=10 WHERE chat_id=0 AND user_id=20");self.db.connection.commit()
        denied=await self.click(run,'join',20);self.assertTrue(denied.answer.call_args.kwargs['show_alert'])
        self.assertEqual(len((await self.db.guild_get(run['id'],10))['members']),1)

    async def test_first_time_chat_member_can_join_but_departed_member_cannot(self):
        run=await self.publish('f_hunt')
        callback=await self.click(run,'join',99)
        self.assertFalse(callback.answer.call_args.kwargs.get('show_alert',False))
        self.assertTrue(any(p['actor_id']==99 for p in (await self.db.guild_get(run['id'],10))['members']))
        self.bot.get_chat_member.return_value=NS(status='left',user=NS(is_bot=False))
        denied=await self.click(run,'start')
        self.assertTrue(denied.answer.call_args.kwargs['show_alert'])
        self.assertEqual((await self.db.guild_get(run['id'],10))['status'],'lobby')

    async def test_persisted_revision_sweep_expiry_and_telegram_throttling(self):
        run=await self.publish()
        await guild_chat_action(self.db,run['id'],20,'join')
        self.bot.edit_message_text.side_effect=TelegramRetryAfter(method=EditMessageText(text='x',chat_id=-100,message_id=101),message='Flood',retry_after=3)
        await self.pub.sweep()
        _,post=await self.db.guild_publication(run['id']);self.assertGreater(post['retry_at'],time.time())
        self.bot.edit_message_text.side_effect=None
        with patch('arena_guild.time.time',return_value=time.time()+5):await self.pub.sweep()
        edits=self.bot.edit_message_text.await_count
        await GuildPublisher(self.db,self.bot,'TestBot').sweep()
        self.assertEqual(self.bot.edit_message_text.await_count,edits)
        self.db.connection.execute('UPDATE guild_runs SET expires=0 WHERE id=?',(run['id'],));self.db.connection.commit()
        await self.pub.sweep()
        self.assertEqual((await self.db.guild_get(run['id'],10))['status'],'cancelled')
        self.assertIn('истёк',self.bot.edit_message_text.call_args.args[0])

    async def test_api_invite_and_chat_join_share_lobby_and_refresh_card(self):
        run=await self.create()
        client=TestClient(TestServer(create_arena_app(self.db,self.bot,TOKEN,guild_publisher=self.pub)));await client.start_server()
        try:
            headers={'X-Telegram-Init-Data':signed(10,int(time.time()))}
            other={'X-Telegram-Init-Data':signed(20,int(time.time()))}
            url='/api/guild/runs/'+run['id']
            denied=await client.post(url+'/invite',headers=other,json={});self.assertEqual(denied.status,400)
            response=await client.post(url+'/invite',headers=headers,json={});self.assertEqual(response.status,200)
            await self.click(run,'join',20)
            run=await self.db.guild_get(run['id'],10)
            self.assertIn('Отряд: 2/3',self.bot.edit_message_text.call_args.args[0])
            response=await client.post(url,headers=headers,json=dict(action='start',revision=run['revision']))
            self.assertEqual(response.status,200)
            self.assertIn('Поход начался',self.bot.edit_message_text.call_args.args[0])
            self.assertEqual(self.bot.send_message.await_count,1)
        finally:await client.close()

    async def test_card_escapes_names_and_has_watch_link_only_during_battle(self):
        run=await self.publish('c_hunt')
        run['members'][0]['name']='<b>not markup</b>'
        self.assertIn('&lt;b&gt;not markup&lt;/b&gt;',self.pub.card(run)[0])
        await guild_chat_action(self.db,run['id'],10,'start')
        run=await self.db.guild_get(run['id'],10)
        buttons=[b for row in self.pub.card(run)[1].inline_keyboard for b in row]
        self.assertTrue(any(b.url and 'startapp=r_' in b.url for b in buttons))
        self.assertIn('startapp=r_',buttons[0].url)


if __name__=='__main__':unittest.main()
