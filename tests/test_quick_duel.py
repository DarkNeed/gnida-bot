import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, User

from database import Database
from handlers.arena import OFFER_RE
from handlers.quick_duel import DUEL_RE, QuickDuelPublisher, create_quick_duel_router, duel_keyboard, duel_text
from handlers.routes import create_router
from quick_duel import DuelError, INVITE_SECONDS, TURN_SECONDS, resolve_round


class Rolls:
    def __init__(self, *rolls):
        self.rolls = list(rolls)

    def randrange(self, limit):
        assert limit == 100
        return self.rolls.pop(0)


def fighter(aim=0):
    return dict(hp=1, aim=aim, cooldown=False)


class MechanicsTests(unittest.TestCase):
    def test_each_hit_chance_uses_strict_threshold_and_consumes_aim(self):
        for aim, chance in enumerate((25, 55, 85)):
            for roll, hp in ((chance - 1, 0), (chance, 1)):
                with self.subTest(aim=aim, roll=roll):
                    before = [fighter(aim), fighter()]
                    after, _ = resolve_round(before, ['shoot', 'aim'], Rolls(roll))
                    self.assertEqual((after[0]['aim'], after[1]['hp']), (0, hp))
                    self.assertEqual(before, [fighter(aim), fighter()])

    def test_disruption_has_exactly_fifty_percent_and_never_cancels_the_shot(self):
        for disruption, hp in ((49, 1), (50, 0)):
            with self.subTest(disruption=disruption):
                rng = Rolls(disruption, 55)
                after, _ = resolve_round([fighter(), fighter(2)], ['disrupt', 'shoot'], rng)
                self.assertEqual((after[0]['hp'], after[1]['aim']), (hp, 0))
                self.assertEqual(rng.rolls, [])
                self.assertTrue(after[0]['cooldown'])

    def test_disrupting_aim_cancels_gain_not_stored_aim(self):
        before = [fighter(), fighter(1)]
        self.assertEqual(resolve_round(before, ['disrupt', 'aim'], Rolls(49))[0][1]['aim'], 1)
        self.assertEqual(resolve_round(before, ['disrupt', 'aim'], Rolls(50))[0][1]['aim'], 2)

    def test_both_shots_land_even_when_first_hit_is_lethal(self):
        after, _ = resolve_round([fighter(), fighter()], ['shoot', 'shoot'], Rolls(0, 0))
        self.assertEqual([p['hp'] for p in after], [0, 0])


class DuelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / 'duels.sqlite')
        self.addAsyncCleanup(self.db.close)
        await self.db.connect()
        self.now = 1800000000
        clock = patch('database.utc_timestamp', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    async def start(self):
        duel = await self.db.quick_duel_create(-100, 1, 10, 20, ('Иван', '<Джей>'))
        await self.db.quick_duel_bind(duel['id'], 77)
        self.ident = duel['id']
        return duel

    async def move(self, user, round_no, action, rng=None, message=77, chat=-100):
        return await self.db.quick_duel_action(self.ident, chat, message, user, round_no, action, rng=rng)

    async def accept(self):
        await self.start()
        _, active = await self.move(20, 0, 'accept')
        return active

    async def test_invitation_binding_authorization_dedup_and_no_command_collision(self):
        self.assertTrue(DUEL_RE.match('/перестрелка @name'))
        self.assertFalse(OFFER_RE.match('/перестрелка @name'))
        self.assertTrue(OFFER_RE.match('/дуэль @name'))
        invite = await self.start()
        self.assertEqual(invite['deadline'], self.now + INVITE_SECONDS)
        self.assertIn('&lt;Джей&gt;', duel_text(invite))
        self.assertIsNone(await self.db.quick_duel_create(-100, 1, 10, 20, ('Иван', 'Джей')))
        with self.assertRaisesRegex(DuelError, 'ещё ждёт ответа'):
            await self.db.quick_duel_create(-100, 2, 10, 30, ('Иван', 'Джон'))
        for user, chat, message in ((10, -100, 77), (30, -100, 77), (20, -200, 77), (20, -100, 78)):
            with self.subTest(user=user, chat=chat, message=message), self.assertRaises(DuelError):
                await self.move(user, 0, 'accept', message=message, chat=chat)
        _, active = await self.move(20, 0, 'accept')
        self.assertEqual(active['status'], 'active')
        self.assertEqual(active['deadline'], self.now + TURN_SECONDS)
        with self.assertRaisesRegex(DuelError, 'уже участвует'):
            await self.db.quick_duel_create(-100, 2, 30, 10, ('Джон', 'Иван'))
        labels = [b.text for row in duel_keyboard(active).inline_keyboard for b in row]
        self.assertEqual(labels, ['🔫 Выстрелить', '🎯 Прицелиться', '💨 Сбить прицел · 50%'])

    async def test_choices_are_immutable_hidden_and_persist_on_restart(self):
        await self.accept()
        notice, public = await self.move(10, 1, 'aim')
        self.assertIn('не видит', notice)
        self.assertIsNone(public)
        await self.db.close()
        await self.db.connect()
        notice, public = await self.move(10, 1, 'shoot')
        self.assertIn('уже принят', notice)
        self.assertIsNone(public)
        _, new = await self.move(20, 1, 'shoot', Rolls(25))
        self.assertEqual(new['state']['round'], 2)
        self.assertEqual(new['state']['last']['moves'], ['aim', 'shoot'])
        self.assertIn('55%', duel_text(new))
        self.assertEqual((await self.move(20, 1, 'shoot'))[1]['state']['round'], 2)

    async def test_unaccepted_invitation_does_not_stop_recipient_playing(self):
        await self.start()
        other = await self.db.quick_duel_create(-100, 2, 20, 30, ('Джей', 'Стэн'))
        await self.db.quick_duel_bind(other['id'], 78)
        await self.db.quick_duel_action(other['id'], -100, 78, 30, 0, 'accept')
        with self.assertRaisesRegex(DuelError, 'уже участвует'):
            await self.move(20, 0, 'accept')
        _, cancelled = await self.move(10, 0, 'cancel')
        self.assertEqual(cancelled['status'], 'cancelled')

    async def test_disruption_cooldown_only_applies_the_next_round(self):
        await self.accept()
        await self.move(10, 1, 'disrupt')
        _, second = await self.move(20, 1, 'aim', Rolls(49))
        self.assertTrue(second['state']['fighters'][0]['cooldown'])
        self.assertIn('перезарядка', duel_text(second))
        with self.assertRaisesRegex(DuelError, 'недоступно'):
            await self.move(10, 2, 'disrupt')
        await self.move(10, 2, 'aim')
        _, third = await self.move(20, 2, 'aim')
        self.assertFalse(third['state']['fighters'][0]['cooldown'])
        self.assertIsNone((await self.move(10, 3, 'disrupt'))[1])

    async def test_concurrent_moves_resolve_once_and_end_in_draw(self):
        await self.accept()
        rng = Rolls(0, 0)
        responses = await asyncio.gather(self.move(10, 1, 'shoot', rng), self.move(20, 1, 'shoot', rng))
        snapshots = [duel for _, duel in responses if duel is not None]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]['status'], 'finished')
        self.assertIn('Ничья', duel_text(snapshots[0]))
        self.assertIsNone(duel_keyboard(snapshots[0]))
        self.assertEqual(rng.rolls, [])

    async def test_eight_missed_rounds_end_in_draw(self):
        await self.accept()
        for n in range(1, 9):
            await self.move(10, n, 'shoot')
            _, last = await self.move(20, n, 'shoot', Rolls(99, 99))
        self.assertEqual(last['state']['round'], 8)
        self.assertEqual(last['state']['reason'], 'round_limit')
        self.assertIsNone(last['state']['winner'])

    async def test_sweep_times_out_without_revealing_hidden_pick(self):
        await self.accept()
        await self.move(10, 1, 'aim')
        self.now += TURN_SECONDS
        bot = SimpleNamespace(edit_message_text=AsyncMock())
        publisher = QuickDuelPublisher(self.db, bot)
        await publisher.sweep()
        await publisher.sweep()
        bot.edit_message_text.assert_awaited_once()
        self.assertIn('Победитель: <b>Иван</b>', bot.edit_message_text.await_args.args[0])
        self.assertNotIn('Прицелиться', bot.edit_message_text.await_args.args[0])
        self.assertIsNone(bot.edit_message_text.await_args.kwargs['reply_markup'])
        duel = (await self.move(20, 1, 'shoot'))[1]
        self.assertEqual(duel['state']['choices'], [None, None])

    async def test_late_accept_expires_invitation_and_no_moves_is_a_draw(self):
        await self.start()
        self.now += INVITE_SECONDS
        _, expired = await self.move(20, 0, 'accept')
        self.assertEqual(expired['status'], 'expired')
        self.assertIsNone(duel_keyboard(expired))
        duel = await self.db.quick_duel_create(-100, 2, 10, 20, ('Иван', 'Джей'))
        self.ident = duel['id']
        await self.db.quick_duel_bind(self.ident, 77)
        await self.move(20, 0, 'accept')
        self.now += TURN_SECONDS
        _, finished = await self.move(20, 1, 'shoot')
        self.assertEqual(finished['state']['reason'], 'timeout')
        self.assertIsNone(finished['state']['winner'])

    async def test_group_command_and_face_to_face_callback_flow(self):
        bot = SimpleNamespace(edit_message_text=AsyncMock())
        publisher = QuickDuelPublisher(self.db, bot)
        router = create_quick_duel_router(self.db, publisher)
        command = router.message.handlers[0].callback
        button = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == 'quick_duel_button')
        creator = User(id=10, is_bot=False, first_name='Иван')
        guest = User(id=20, is_bot=False, first_name='Джей')
        chat = Chat(id=-100, type='supergroup')
        posted = Message(message_id=77, date=datetime.now(timezone.utc), chat=chat)
        message = SimpleNamespace(chat=chat, from_user=creator, sender_chat=None, text='/перестрелка',
                                  caption=None, reply_to_message=SimpleNamespace(from_user=guest, sender_chat=None),
                                  answer=AsyncMock(return_value=posted), message_id=3)
        await command(message, bot)
        await command(message, bot)
        message.answer.assert_awaited_once()
        invite = message.answer.await_args.kwargs['reply_markup']
        callback = SimpleNamespace(data=invite.inline_keyboard[0][0].callback_data, message=posted, inline_message_id=None,
                                   from_user=guest, answer=AsyncMock())
        await button(callback)
        keyboard = bot.edit_message_text.await_args.kwargs['reply_markup']
        callback.data = keyboard.inline_keyboard[0][1].callback_data
        callback.from_user = creator
        await button(callback)
        bot.edit_message_text.assert_awaited_once()  # first move did not leak
        callback.from_user = guest
        await button(callback)
        self.assertEqual(bot.edit_message_text.await_count, 2)
        self.assertIn('Итог раунда 1', bot.edit_message_text.await_args.args[0])

    async def test_username_command_checks_current_member_before_inviting(self):
        await self.db.upsert_user(-100, 20, 'sheriff', 'Джей')
        creator = User(id=10, is_bot=False, first_name='Иван')
        guest = User(id=20, is_bot=False, first_name='Джей', username='sheriff')
        chat = Chat(id=-100, type='supergroup')
        bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='left', user=guest)))
        router = create_quick_duel_router(self.db, QuickDuelPublisher(self.db, bot))
        command = router.message.handlers[0].callback
        message = SimpleNamespace(chat=chat, from_user=creator, sender_chat=None, text='/перестрелка @Sheriff',
                                  caption=None, reply_to_message=None, answer=AsyncMock(return_value=SimpleNamespace(message_id=77)),
                                  message_id=3)
        await command(message, bot)
        self.assertNotIn('reply_markup', message.answer.await_args.kwargs)
        bot.get_chat_member.return_value.status = 'member'
        await command(message, bot)
        self.assertIn('✅ Принять', message.answer.await_args.kwargs['reply_markup'].inline_keyboard[0][0].text)
        bot.get_chat_member.assert_awaited_with(-100, 20)

    async def test_private_duel_updates_both_messages_without_leaking_a_move(self):
        await self.db.quick_duel_remember_private(20, 'sheriff')
        creator = User(id=10, is_bot=False, first_name='Иван')
        guest = User(id=20, is_bot=False, first_name='Джей', username='sheriff')
        source, target = (Chat(id=person.id,type='private') for person in (creator,guest))
        posted, invited = (Message(message_id=77+i,date=datetime.now(timezone.utc),chat=chat)
                           for i,chat in enumerate((source,target)))
        peer = SimpleNamespace(id=20,type='private',username='sheriff',first_name='Джей',last_name=None)
        bot = SimpleNamespace(get_chat=AsyncMock(return_value=peer),send_message=AsyncMock(return_value=invited),
                              edit_message_text=AsyncMock())
        router = create_quick_duel_router(self.db, QuickDuelPublisher(self.db, bot))
        command = router.message.handlers[0].callback
        button = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == 'quick_duel_button')
        message = SimpleNamespace(chat=source,from_user=creator,sender_chat=None,text='/перестрелка @Sheriff',
                                  caption=None,answer=AsyncMock(return_value=posted),message_id=3)
        await command(message, bot)
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0],20)
        self.assertEqual(len(message.answer.await_args.kwargs['reply_markup'].inline_keyboard),1)
        invite = bot.send_message.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
        cb = SimpleNamespace(data=invite,message=posted,inline_message_id=None,from_user=guest,answer=AsyncMock())
        await button(cb)
        self.assertTrue(cb.answer.await_args.kwargs['show_alert'])
        bot.edit_message_text.assert_not_awaited()
        cb.message = invited
        await button(cb)
        self.assertEqual({(c.kwargs['chat_id'],c.kwargs['message_id']) for c in bot.edit_message_text.await_args_list},
                         {(10,77),(20,78)})
        with self.assertRaises(DuelError):
            await self.db.quick_duel_create(30,5,30,20,('Другой','Джей'))
        cb.data = bot.edit_message_text.await_args.kwargs['reply_markup'].inline_keyboard[0][1].callback_data
        await button(cb)
        self.assertEqual(bot.edit_message_text.await_count,2)
        cb.message, cb.from_user = posted, creator
        await button(cb)
        self.assertEqual(bot.edit_message_text.await_count,4)
        self.assertTrue(all('Итог раунда 1' in c.args[0] for c in bot.edit_message_text.await_args_list[-2:]))

    async def test_unreachable_guest_does_not_block_next_private_invite(self):
        await self.db.quick_duel_remember_private(20,'sheriff')
        peer = SimpleNamespace(id=20,type='private',username='sheriff',first_name='Джей',last_name=None)
        bot = SimpleNamespace(get_chat=AsyncMock(return_value=peer), edit_message_text=AsyncMock(),
                              send_message=AsyncMock(side_effect=TelegramForbiddenError(
                                  method=SendMessage(chat_id=20,text='x'), message='Forbidden')))
        router = create_quick_duel_router(self.db, QuickDuelPublisher(self.db, bot))
        message = SimpleNamespace(chat=Chat(id=10,type='private'),from_user=User(id=10,is_bot=False,first_name='Иван'),
                                  sender_chat=None,text='/перестрелка @sheriff',caption=None,message_id=3,
                                  answer=AsyncMock(return_value=SimpleNamespace(message_id=77)))
        await router.message.handlers[0].callback(message, bot)
        self.assertIn('Не удалось отправить',bot.edit_message_text.await_args.args[0])
        retry = await self.db.quick_duel_create(10,4,10,20,('Иван','Джей'))
        self.assertEqual(retry['status'],'pending')

    async def test_inline_query_to_duel_in_one_message_and_no_private_contact(self):
        users = [User(id=i,is_bot=False,first_name='Игрок '+str(i)) for i in (10,20,30)]
        source = create_router(self.db)
        query = SimpleNamespace(query='пере',from_user=users[0],answer=AsyncMock())
        bot = SimpleNamespace(token='test-token',edit_message_text=AsyncMock())
        await source.inline_query.handlers[0].callback(query,bot)
        [card] = query.answer.await_args.args[0]
        self.assertEqual(card.title,'Перестрелка')
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM quick_duels').fetchone()[0],0)
        invite = card.reply_markup.inline_keyboard[0][0].callback_data
        publisher = QuickDuelPublisher(self.db, bot)
        router = create_quick_duel_router(self.db, publisher)
        callbacks = {h.callback.__name__:h.callback for h in router.callback_query.handlers}

        def click(data, who=1, message='inline-one'):
            return SimpleNamespace(data=data,from_user=users[who],inline_message_id=message,message=None,answer=AsyncMock())

        own = click(invite,0)
        await callbacks['quick_duel_inline_invite'](own)
        self.assertTrue(own.answer.await_args.kwargs['show_alert'])
        forged = click(invite.replace(':10:',':30:'))
        await callbacks['quick_duel_inline_invite'](forged)
        self.assertIn('Некорректный вызов',forged.answer.await_args.args[0])
        outsiders = [click(invite,i) for i in (1,2)]
        await asyncio.gather(*(callbacks['quick_duel_inline_invite'](cb) for cb in outsiders))
        self.assertEqual(sum(bool(cb.answer.await_args.kwargs.get('show_alert')) for cb in outsiders),1)
        row = self.db.connection.execute('SELECT id,guest FROM quick_duels WHERE inline_message_id=?',('inline-one',)).fetchone()
        winner = 1 if row['guest']==20 else 2
        self.assertEqual(bot.edit_message_text.await_args.kwargs['inline_message_id'],'inline-one')
        self.assertNotIn('chat_id',bot.edit_message_text.await_args.kwargs)
        move = bot.edit_message_text.await_args.kwargs['reply_markup'].inline_keyboard[0][1].callback_data
        for invalid in (click(move,winner,'another-message'),click(move,3-winner)):
            await callbacks['quick_duel_button'](invalid)
            self.assertTrue(invalid.answer.await_args.kwargs['show_alert'])
        await callbacks['quick_duel_button'](click(move,winner))
        bot.edit_message_text.assert_awaited_once()  # the other app user cannot see the pending move
        await callbacks['quick_duel_button'](click(move,0))
        self.assertIn('Итог раунда 1',bot.edit_message_text.await_args.args[0])
        self.now += TURN_SECONDS
        await publisher.sweep()
        ended = await self.db.quick_duel_get(row['id'])
        self.assertEqual(ended['status'],'finished')
        self.assertIsNone(bot.edit_message_text.await_args.kwargs['reply_markup'])

    async def test_inline_cancel_is_author_only_and_bound_to_one_post(self):
        create = self.db.quick_duel_inline_invite
        with self.assertRaises(DuelError):
            await create('inline-one',10,20,'cancel',('A','B'))
        cancelled = await create('inline-one',10,10,'cancel',('A','A'))
        self.assertEqual(cancelled['status'],'cancelled')
        with self.assertRaises(DuelError):
            await create('inline-one',10,20,'accept',('A','B'))
        next_game = await create('inline-two',10,20,'accept',('A','B'))
        self.assertEqual(next_game['status'],'active')
