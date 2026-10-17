"""Owner-only gifts of the permanent four-character-slot unlock."""
import html
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError

from arena_characters import CHARACTER_OWNER_ID


GRANT_COMMAND = re.compile(
    r'^/выдать(?:@(?P<bot>\w+))?\s+анлок(?:\s+(?P<target>\S+))?\s*$', re.I
)
GRANT_HELP = (
    'Ответь на сообщение игрока командой /выдать анлок '
    'или напиши /выдать анлок @ник либо /выдать анлок Telegram_ID. '
    'Откроются все 4 дополнительных слота во всех чатах.'
)


def create_character_grant_router(db, username):
    router = Router(name='character_grants')

    @router.message(F.from_user.id == CHARACTER_OWNER_ID, F.text.regexp(GRANT_COMMAND))
    async def grant_slots(message, bot):
        if (not message.from_user or message.from_user.id != CHARACTER_OWNER_ID
                or message.sender_chat or message.chat.type not in {'private','group','supergroup'}):
            return
        match = GRANT_COMMAND.fullmatch(message.text or '')
        if not match or (match['bot'] and match['bot'].casefold() != username.casefold()):
            return
        token = match['target']
        target_id, label = None, None
        if token:
            if token.isascii() and token.isdecimal():
                target_id = int(token) if len(token) <= 19 else 0
                label = str(target_id)
            elif re.fullmatch(r'@[A-Za-z0-9_]+', token):
                # Never trust a cached username: Telegram can reassign it.
                matches = {}
                for row in await db.resolve_users_globally(token):
                    try:
                        member = await bot.get_chat_member(row['chat_id'], row['user_id'])
                    except TelegramAPIError:
                        continue
                    user = member.user
                    if not user.is_bot and user.username and user.username.casefold() == token[1:].casefold():
                        matches[user.id] = user
                if len(matches) != 1:
                    await message.answer('Не удалось однозначно проверить @ник. Ответь на сообщение игрока или укажи его Telegram ID.')
                    return
                user = next(iter(matches.values()))
                target_id, label = user.id, '@'+user.username
            else:
                await message.answer(GRANT_HELP)
                return
        elif message.reply_to_message:
            reply = message.reply_to_message
            if reply.sender_chat or not reply.from_user or reply.from_user.is_bot:
                await message.answer('Ответь на обычное сообщение игрока, не бота и не от имени канала.')
                return
            target_id, label = reply.from_user.id, reply.from_user.full_name
        else:
            await message.answer(GRANT_HELP)
            return
        if target_id == bot.id:
            await message.answer('Боту слоты персонажей не нужны.')
            return
        try:
            changed = await db.arena_grant_character_slots(target_id, message.from_user.id)
        except ValueError as error:
            await message.answer(str(error))
            return
        recipient = f'<a href="tg://user?id={target_id}">{html.escape(label)}</a>'
        await message.answer(
            (f'✅ {recipient}: выдан постоянный анлок всех 4 дополнительных слотов. '
             if changed else f'{recipient}: постоянный анлок уже выдавался. ')
            + 'Всего доступны 5 персонажей во всех чатах. Stars не списываются. Обнови меню арены.',
            parse_mode='HTML',
        )

    return router
