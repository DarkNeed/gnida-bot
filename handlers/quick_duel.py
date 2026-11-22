"""Render one shared duel state in a group or two private chats."""
import asyncio
from html import escape
from hmac import compare_digest
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.routes import PRIVATE_GAMES_SCOPE, display_name, message_content, text_or_caption_regexp
from quick_duel import (ACTIONS, DISRUPT_CHANCE, DuelError, HIT_CHANCES, INLINE_INVITE_PREFIX, INVITE_SECONDS,
                        MAX_ROUNDS, TURN_SECONDS, inline_invite_data)


DUEL_RE = re.compile(r'^\s*[/!]перестрелка(?:@\w+)?(?=\s|$)', re.IGNORECASE)
BUTTON_RE = re.compile(r'dshot:([0-9a-f]{16}):([0-8]):(accept|decline|cancel|shoot|aim|disrupt)')
INLINE_RE = re.compile(rf'{INLINE_INVITE_PREFIX}:([1-9][0-9]{{0,15}}):(accept|cancel):[0-9a-f]{{20}}')


def duel_keyboard(duel, viewer=None):
    def button(label, action):
        return InlineKeyboardButton(text=label, callback_data=f"dshot:{duel['id']}:{duel['state']['round']}:{action}")

    if duel['status'] == 'pending':
        rows = []
        if viewer is None or viewer == duel['guest']:
            rows.append([button('✅ Принять', 'accept'), button('❌ Отклонить', 'decline')])
        if viewer is None or viewer == duel['creator']:
            rows.append([button('↩️ Отозвать вызов', 'cancel')])
    elif duel['status'] == 'active':
        rows = [[button(ACTIONS['shoot'], 'shoot'), button(ACTIONS['aim'], 'aim')],
                [button(f"{ACTIONS['disrupt']} · {DISRUPT_CHANCE}%", 'disrupt')]]
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def duel_text(duel):
    state, status = duel['state'], duel['status']
    names = [escape(fighter['name']) for fighter in state['fighters']]
    lines = ['🤠 <b>Дуэль</b>']
    if status == 'pending':
        lines.extend([f"{names[0]} вызывает <a href=\"tg://user?id={duel['guest']}\">{names[1]}</a>.",
                      f'❤️ По 1 HP · без ставок · принять за {INVITE_SECONDS // 60} мин.'])
        return '\n'.join(lines)
    endings = {'declined': '❌ Вызов отклонён.', 'cancelled': '↩️ Вызов отозван.',
               'expired': '⌛ Время на принятие вызова вышло.'}
    if status in endings:
        return '\n'.join(lines + [endings[status]])
    if status == 'active':
        lines[0] += f" · раунд {state['round']}/{MAX_ROUNDS}"
    for name, fighter in zip(names, state['fighters']):
        hp, aim = fighter['hp'], fighter['aim']
        detail = f" · 🔫 {HIT_CHANCES[aim]}%" if status == 'active' else ''
        if status == 'active' and fighter['cooldown']:
            detail += ' · 💨 перезарядка'
        lines.append(f"{'❤️' if hp else '🖤'} <b>{name}</b>: {hp} HP · 🎯 {aim}/2{detail}")
    last = state['last']
    if last:
        lines.append(f"\n<b>Итог раунда {last['round']}</b>")
        for name, move, effects in zip(names, last['moves'], last['effects']):
            lines.append(f"{name}: {ACTIONS[move]} — {escape(', '.join(effects))}")
    if status == 'active':
        lines.append(f'\n🤫 Выбор скрыт до конца раунда · {TURN_SECONDS} сек. на ход.')
    else:
        winner, reason = state['winner'], state['reason']
        detail = {'timeout': 'Время на ход вышло.', 'round_limit': f'Сыграно {MAX_ROUNDS} раундов.'}.get(reason)
        lines.append('\n🤝 Ничья.' if winner is None else f'\n🏆 Победитель: <b>{names[winner]}</b>.')
        if detail:
            lines.append(detail)
    return '\n'.join(lines)


class QuickDuelPublisher:
    def __init__(self, database, bot):
        self.database, self.bot = database, bot
        # Serialize edits for the same match without keeping a lock per old match.
        self.locks = [asyncio.Lock() for _ in range(32)]

    def lock(self, ident):
        return self.locks[int(ident, 16) % len(self.locks)]

    async def edit(self, duel):
        if duel['inline_message_id'] is not None:
            try:
                await self.bot.edit_message_text(duel_text(duel), inline_message_id=duel['inline_message_id'],
                                                 parse_mode='HTML', reply_markup=duel_keyboard(duel))
            except TelegramAPIError as error:
                if 'message is not modified' not in str(error).casefold():
                    logging.warning('Could not redraw inline duel %s: %s', duel['id'], error)
                    return False
            return True
        private = duel['chat_id'] > 0
        targets = [(duel['chat_id'], duel['message_id'], duel['creator'] if private else None)]
        if private:
            targets.append((duel['guest'], duel['guest_message_id'], duel['guest']))

        async def redraw(chat, message, viewer):
            if message is None:
                return
            try:
                await self.bot.edit_message_text(duel_text(duel), chat_id=chat, message_id=message,
                                                 parse_mode='HTML', reply_markup=duel_keyboard(duel, viewer))
            except TelegramAPIError as error:
                if 'message is not modified' not in str(error).casefold():
                    logging.warning('Could not redraw quick duel %s: %s', duel['id'], error)

        await asyncio.gather(*(redraw(*target) for target in targets))

    async def sweep(self):
        for ident in await self.database.quick_duels_due():
            async with self.lock(ident):
                expired = await self.database.quick_duel_expire(ident)
                if expired:
                    await self.edit(expired)


def create_quick_duel_router(database, publisher):
    router = Router(name='quick_duel')

    @router.message(text_or_caption_regexp(DUEL_RE))
    async def quick_duel(message: Message, bot: Bot):
        if message.chat.type not in ('group', 'supergroup', 'private'):
            await message.answer('🤠 Вызови соперника в группе или в личке бота.')
            return
        creator = message.from_user
        if not creator or creator.is_bot or message.sender_chat:
            return
        content = message_content(message)
        target = content[DUEL_RE.match(content).end():].strip()
        if message.chat.type == 'private':
            await database.quick_duel_remember_private(creator.id, creator.username)
            if not re.fullmatch(r'@[a-zA-Z0-9_]{1,32}', target):
                await message.answer('🤠 Напиши /перестрелка @ник. Бот отправит вызов игроку в личку.')
                return
            if (creator.username or '').casefold() == target[1:].casefold():
                await message.answer('🤠 Выбери другого игрока.')
                return
            target_name = target[1:].casefold()
            for candidate in await database.quick_duel_private_candidates(target_name):
                if candidate == creator.id:
                    continue
                try:
                    peer = await bot.get_chat(candidate)
                except TelegramAPIError:
                    continue
                if (peer.id == candidate and peer.type == 'private'
                    and (peer.username or '').casefold() == target_name):
                    break
            else:
                await message.answer('Не нашёл игрока в личке. Проверь @ник и попроси его нажать «Старт» у бота.')
                return
            name = ' '.join(part for part in (peer.first_name, peer.last_name) if part) or target
            try:
                duel = await database.quick_duel_create(message.chat.id,message.message_id,creator.id,peer.id,(creator.full_name,name))
            except DuelError as error:
                await message.answer(str(error))
                return
            if duel is None:
                return
            async with publisher.lock(duel['id']):
                try:
                    sent = await message.answer(duel_text(duel), parse_mode='HTML', reply_markup=duel_keyboard(duel,creator.id))
                except TelegramAPIError:
                    await database.quick_duel_bind(duel['id'],None)
                    raise
                try:
                    invited = await bot.send_message(peer.id,duel_text(duel), parse_mode='HTML',
                                                     reply_markup=duel_keyboard(duel,peer.id))
                except TelegramAPIError:
                    await database.quick_duel_bind(duel['id'],None)
                    await bot.edit_message_text('Не удалось отправить вызов. Попроси игрока открыть бота и нажать «Старт».',
                                                chat_id=message.chat.id,message_id=sent.message_id,reply_markup=None)
                    return
                await database.quick_duel_bind(duel['id'],sent.message_id,invited.message_id)
            return
        if target:
            if not re.fullmatch(r'@[a-zA-Z0-9_]{1,32}', target):
                await message.answer('🤠 Напиши /перестрелка @ник или ответь командой на сообщение участника.')
                return
            row = await database.resolve_user(message.chat.id, target)
            if not row:
                await message.answer('Не нашёл этот @ник в чате. Ответь командой на сообщение соперника.')
                return
            try:
                member = await bot.get_chat_member(message.chat.id, row['user_id'])
            except TelegramAPIError:
                await message.answer('Не удалось проверить участника. Вызови его ответом на сообщение.')
                return
            guest = member.user if (member.status not in ('left', 'kicked')
                                    and getattr(member, 'is_member', True)
                                    and (member.user.username or '').casefold() == target[1:].casefold()) else None
        else:
            reply = message.reply_to_message
            guest = reply.from_user if reply and not reply.sender_chat else None
        if not guest or guest.is_bot or guest.id == creator.id:
            await message.answer('🤠 Выбери другого участника: /перестрелка @ник или ответ на его сообщение.')
            return
        try:
            duel = await database.quick_duel_create(message.chat.id, message.message_id, creator.id, guest.id,
                                                   (creator.full_name, guest.full_name))
        except DuelError as error:
            await message.answer(str(error))
            return
        if duel is None:
            return
        async with publisher.lock(duel['id']):
            try:
                sent = await message.answer(duel_text(duel), parse_mode='HTML', reply_markup=duel_keyboard(duel))
            except TelegramAPIError:
                await database.quick_duel_bind(duel['id'], None)
                raise
            await database.quick_duel_bind(duel['id'], sent.message_id)

    @router.callback_query(F.data.startswith(INLINE_INVITE_PREFIX + ':'))
    async def quick_duel_inline_invite(callback: CallbackQuery):
        match = INLINE_RE.fullmatch(callback.data or '')
        user, message = callback.from_user, callback.inline_message_id
        if not match or not message or user.is_bot:
            await callback.answer('Этот вызов нужно отправить через инлайн-меню бота.', show_alert=True)
            return
        creator, action = int(match[1]), match[2]
        if not compare_digest(callback.data, inline_invite_data(creator, action, publisher.bot.token)):
            await callback.answer('Некорректный вызов. Отправь новый через инлайн-меню.', show_alert=True)
            return
        author = await database.get_user(PRIVATE_GAMES_SCOPE, creator)
        if author is None:
            await callback.answer('Создателю нужно отправить новый инлайн-вызов.', show_alert=True)
            return
        try:
            duel = await database.quick_duel_inline_invite(message, creator, user.id, action,
                                                           (author['display_name'], display_name(user)))
        except DuelError as error:
            await callback.answer(str(error), show_alert=True)
            return
        async with publisher.lock(duel['id']):
            # A second click must not overwrite a newer round's keyboard.
            current = await database.quick_duel_get(duel['id'])
            if not await publisher.edit(current):
                await callback.answer('Не удалось обновить сообщение. Нажми ещё раз.', show_alert=True)
                return
        await callback.answer()

    @router.callback_query(F.data.startswith('dshot:'))
    async def quick_duel_button(callback: CallbackQuery):
        match = BUTTON_RE.fullmatch(callback.data or '')
        message = callback.message
        inline = callback.inline_message_id
        if not match or (not inline and not isinstance(message, Message)):
            await callback.answer('Кнопка дуэли недоступна.', show_alert=True)
            return
        ident, round_no, action = match.groups()
        async with publisher.lock(ident):
            try:
                args = (None, None) if inline else (message.chat.id, message.message_id)
                notice, duel = await database.quick_duel_action(ident, *args, callback.from_user.id,
                                                              int(round_no), action, inline_message=inline)
            except DuelError as error:
                await callback.answer(str(error), show_alert=True)
                return
            try:
                await callback.answer(notice)
            finally:
                if duel is not None:
                    await publisher.edit(duel)

    return router
