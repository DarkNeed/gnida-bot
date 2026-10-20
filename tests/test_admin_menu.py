import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiogram.types import User
from menu_context import manages_chat
from handlers.admin_menu import create_admin_menu_router
import test_constructor_chats as constructors


class ChatOwnerAdminTests(constructors.ConstructorChatTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.owner=User(id=10,is_bot=False,first_name='Владелец чата')
        await self.db.upsert_user(-100,10,None,'Владелец чата')
        await self.db.select_menu_chat(10,-100)
        self.roles={-100:'creator',-200:'administrator'}
        async def get_member(chat_id,user_id):return SimpleNamespace(status=self.roles[chat_id])
        self.bot.get_chat_member=AsyncMock(side_effect=get_member)
        self.admin=create_admin_menu_router(self.db)

    async def test_lists_follow_selection_from_menu_and_direct_commands(self):
        # Parent suite targets the global owner's privileges; replace with the
        # local creator's scope. Other inherited mutation/isolation tests also
        # run against this stricter identity.
        callback=await self.custom('cc:list:0')
        self.assertIn('Каргассия',callback.message.edit_text.await_args.args[0])
        callback=await self.event('evm:list')
        self.assertIn('Каргассия',callback.message.edit_text.await_args.args[0])

    async def test_no_selection_or_left_chat_shows_picker_without_records(self):
        self.roles[-100]='member'
        for callback in (await self.custom('cc:list:0'),await self.event('evm:list')):
            callback.message.edit_text.assert_not_awaited()
            self.assertTrue(callback.answer.await_args.kwargs['show_alert'])

    async def test_manual_event_launch_respects_selection_but_auto_events_remain_enabled(self):
        await self.store.toggle_template(self.events[-100])
        message=self.message('/event '+str(self.events[-100]))
        await self.handler(self.event_router,'event_manual_command',False)(message,self.bot,self.state())
        self.bot.send_message.assert_awaited_once()
        self.roles[-100]='administrator'
        self.bot.send_message.reset_mock()
        await self.handler(self.event_router,'event_manual_command',False)(message,self.bot,self.state())
        self.bot.send_message.assert_not_awaited()

    async def test_other_chat_records_do_not_affect_pagination_or_empty_lists(self):
        # Unowned second chat is not reachable, even if already selected.
        await self.db.select_menu_chat(10,-200)
        for callback in (await self.custom('cc:list:0'),await self.event('evm:list')):
            callback.message.edit_text.assert_not_awaited()

    async def test_old_constructor_buttons_cannot_edit_or_delete_other_chat(self):
        self.roles[-200]='creator'
        await super().test_old_constructor_buttons_cannot_edit_or_delete_other_chat()

    async def admin_click(self,data):
        callback=self.callback(data)
        await self.handler(self.admin,'admin_callback')(callback,self.bot,self.state())
        return callback

    async def test_picker_creator_only_and_toggle_chat_revision_binding(self):
        callback=await self.admin_click('adm:chats')
        values={b.callback_data for b in self.buttons(callback)}
        self.assertIn('adm:chat:-100',values)
        self.assertNotIn('adm:chat:-200',values)
        await self.admin_click('adm:toggle:-100:arena:0:0')
        self.assertFalse(next(m['enabled'] for m in (await self.db.arena_modules(-100))['modules'] if m['id']=='arena'))
        callback=await self.admin_click('adm:toggle:-100:slavery:0:0')
        self.assertIn('изменились',callback.answer.await_args.args[0])
        callback=await self.admin_click('adm:toggle:-200:slavery:0:0')
        self.assertIn('прав',callback.answer.await_args.args[0])
        self.roles[-100]='administrator'
        callback=await self.admin_click('adm:toggle:-100:slavery:0:1')
        self.assertIn('прав',callback.answer.await_args.args[0])
        self.assertTrue(next(m['enabled'] for m in (await self.db.arena_modules(-100))['modules'] if m['id']=='slavery'))

    async def test_revoked_role_blocks_constructor_inputs(self):
        self.roles[-100]='administrator'
        state=self.state({'command_id':self.commands[-100],'field':'cost'})
        await self.handler(self.router,'custom_command_edit_value',False)(self.message('100'),state,self.bot)
        self.assertEqual((await self.db.get_custom_command_by_id(self.commands[-100]))['cost'],0)
        state.clear.assert_awaited()
        state=self.state({'template_id':self.events[-100],'field':'success_reward','action':'field'})
        await self.handler(self.event_router,'event_input',False)(self.message('1000'),state,self.bot)
        self.assertEqual((await self.store.get_template(self.events[-100]))['success_reward'],15)
        state.clear.assert_awaited()

    async def test_merchant_toggle_is_local_persistent_and_revision_bound(self):
        callback = await self.admin_click('adm:home')
        buttons = self.buttons(callback)
        self.assertTrue(any(b.callback_data == 'adm:merchant:-100:0:0' and
                            'ВКЛ' in b.text for b in buttons))
        callback = await self.admin_click('adm:merchant:-100:0:0')
        self.assertIn('отключены', callback.answer.await_args.args[0])
        self.assertTrue(any(b.callback_data == 'adm:merchant:-100:1:1' and
                            'ВЫКЛ' in b.text for b in self.buttons(callback)))
        self.assertTrue((await self.db.arena_merchant_notifications(-200))['enabled'])
        self.assertTrue(await self.db.feature_enabled(-100, 'arena'))
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.arena_merchant_notifications(-100),
                         dict(enabled=False, revision=1))
        callback = await self.admin_click('adm:merchant:-100:1:0')
        self.assertIn('изменились', callback.answer.await_args.args[0])
        await self.admin_click('adm:merchant:-100:1:1')
        self.assertTrue((await self.db.arena_merchant_notifications(-100))['enabled'])

    async def test_merchant_toggle_checks_selected_chat_and_current_owner_role(self):
        callback = await self.admin_click('adm:merchant:-200:0:0')
        self.assertTrue(callback.answer.await_args.kwargs['show_alert'])
        self.assertTrue((await self.db.arena_merchant_notifications(-200))['enabled'])
        self.roles[-100] = 'administrator'
        callback = await self.admin_click('adm:merchant:-100:0:0')
        self.assertTrue(callback.answer.await_args.kwargs['show_alert'])
        self.assertTrue((await self.db.arena_merchant_notifications(-100))['enabled'])
        self.roles[-100] = 'creator'
        callback = await self.admin_click('adm:merchant:-100:bad:0')
        self.assertTrue(callback.answer.await_args.kwargs['show_alert'])
        callback = self.callback('adm:merchant:-100:0:0')
        callback.message.chat.type = 'supergroup'
        await self.handler(self.admin, 'admin_callback')(callback, self.bot, self.state())
        self.assertTrue(callback.answer.await_args.kwargs['show_alert'])
        self.assertTrue((await self.db.arena_merchant_notifications(-100))['enabled'])

    async def test_global_owner_still_requires_membership_not_ownership(self):
        self.assertTrue(await manages_chat(self.bot,-100,1980056841))
        self.roles[-100]='left'
        self.assertFalse(await manages_chat(self.bot,-100,1980056841))
        self.roles[-100]='member'
        self.assertFalse(await manages_chat(self.bot,-100,10))

    async def test_main_menu_has_no_constructors_public_commands_stay(self):
        cb=self.callback('sm:home')
        await self.handler(self.router,'slave_menu_callback')(cb,self.bot)
        self.assertFalse(any(b.callback_data in {'sm:custom','sm:events'} for b in self.buttons(cb)))
        cb=self.callback('sm:c:-100:offers:0')
        await self.handler(self.router,'slave_menu_callback')(cb,self.bot)
        self.assertIn('Первая команда',cb.message.edit_text.await_args.args[0])
