"""Owner gifts/removals by reply, verified username, or explicit Telegram ID."""
import html
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError

from arena_characters import CHARACTER_OWNER_ID
from arena_pets import PETS


PET_COMMAND = re.compile(r'^/(?P<action>подарить|забрать)(?:@(?P<bot>\w+))?(?:\s+(?P<body>[^\r\n]+))?\s*$', re.I)
PET_HELP = (
    'Ответь на сообщение игрока: /подарить гачи уточка или /забрать гачи уточка.\n'
    'Без ответа: /подарить гачи уточка @ник либо /забрать гачи уточка Telegram_ID.\n'
    'Работают полные названия питомцев и их ID. Выдача не тратит ресурсы. '
    'Повторная выдача не меняет прокачку и не даёт осколков. '
    'Изъятие удаляет питомца вместе с прокачкой и снимает его с боя, без возврата ресурсов. '
    'Уже начатый бой сохраняет своего спутника до завершения.'
)


def normalized_name(value):
    return re.sub(r'[\W_]+', ' ', value.casefold().replace('ё', 'е')).strip()


def find_pet(value):
    name = normalized_name(value)
    return next((key for key, pet in PETS.items()
                 if name in {normalized_name(key), normalized_name(pet['name'])}), None)


def create_pet_grant_router(db, username):
    router = Router(name='pet_grants')

    @router.message(F.from_user.id == CHARACTER_OWNER_ID, F.text.regexp(PET_COMMAND))
    async def change_pet(message, bot):
        if (not message.from_user or message.from_user.id != CHARACTER_OWNER_ID
                or message.sender_chat or message.chat.type not in {'private', 'group', 'supergroup'}):
            return
        match = PET_COMMAND.fullmatch(message.text or '')
        if not match or (match['bot'] and match['bot'].casefold() != username.casefold()):
            return
        body = (match['body'] or '').strip()
        parts = body.rsplit(maxsplit=1)
        token = None
        if len(parts) == 2 and (parts[1].startswith('@') or re.fullmatch(r'-?\d+', parts[1])):
            body, token = parts
        pet_id = find_pet(body)
        if not pet_id:
            await message.answer(PET_HELP + '\n\nПитомцы: ' + ', '.join(p['name'] for p in PETS.values()))
            return
        target_id, label = None, None
        if token:
            if token.isascii() and token.isdecimal():
                target_id = int(token) if len(token) <= 19 else 0
                label = str(target_id)
            elif re.fullmatch(r'@[A-Za-z0-9_]+', token):
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
                target_id, label = user.id, '@' + user.username
            else:
                await message.answer(PET_HELP)
                return
        elif message.reply_to_message:
            reply = message.reply_to_message
            if reply.sender_chat or not reply.from_user or reply.from_user.is_bot:
                await message.answer('Ответь на обычное сообщение игрока, не бота и не от имени канала.')
                return
            target_id, label = reply.from_user.id, reply.from_user.full_name
        else:
            await message.answer(PET_HELP)
            return
        if target_id == bot.id:
            await message.answer('Боту питомцы не нужны.')
            return
        revoke = match['action'].casefold() == 'забрать'
        event_key = f'telegram:{bot.id}:{message.chat.id}:{message.message_id}'
        try:
            result = await db.pet_admin_change(target_id, pet_id, message.from_user.id, event_key, revoke=revoke)
        except ValueError as error:
            await message.answer(str(error))
            return
        recipient = f'<a href="tg://user?id={target_id}">{html.escape(label)}</a>'
        pet_name = html.escape(PETS[pet_id]['name'])
        if result['replay']:
            text = 'Эта команда уже обработана. Коллекция повторно не изменялась.'
        elif revoke:
            text = (f'✅ {recipient}: {pet_name} изъят и снят с экипировки. Прокачка удалена без возврата ресурсов.'
                    if result['changed'] else f'{recipient}: питомца «{pet_name}» нет в коллекции.')
        else:
            text = (f'🎁 {recipient}: подарен {pet_name} первого уровня. Его можно выбрать в коллекции.'
                    if result['changed'] else f'{recipient}: {pet_name} уже есть. Прокачка сохранена, осколки не начислены.')
        await message.answer(text + ' Обнови меню питомцев.', parse_mode='HTML')

    return router
