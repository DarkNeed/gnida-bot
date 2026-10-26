"""An independent RP entry point, not an arena main-menu tab."""
import re
from aiogram import Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from arena_links import arena_link
from arena_web import require_member
from handlers.routes import text_or_caption_regexp

RP_RE = re.compile(r'^\s*/(?:рп|rp)(?:@\w+)?\s*$', re.I)


def create_rp_router(db, bot, username, enabled):
    router = Router(name='rp')

    @router.message(text_or_caption_regexp(RP_RE))
    async def rp_menu(message):
        if not message.from_user or message.from_user.is_bot:
            return
        if not enabled:
            await message.answer('RP-меню недоступно: нужно настроить WEBAPP_URL.')
            return
        if message.chat.type not in ('private', 'group', 'supergroup'):
            await message.answer('Открой /рп в группе или в личных сообщениях боту.')
            return
        parameter = 'rp'
        if message.chat.type != 'private':
            try:
                await require_member(bot, message.chat.id, message.from_user.id)
                await db.arena_require_enabled(message.chat.id)
                # This router precedes the general tracking router. A first-ever
                # /рп message must make this verified group available in the picker,
                # without creating an RPG character or retroactively refreshing work.
                await db.upsert_chat(message.chat.id, getattr(message.chat,'title',None) or f'Чат {message.chat.id}')
                await db.upsert_user(message.chat.id, message.from_user.id,
                                     getattr(message.from_user,'username',None),
                                     getattr(message.from_user,'full_name',str(message.from_user.id)), touch=False)
            except ValueError as error:
                await message.answer(str(error))
                return
            parameter += '_' + str(message.chat.id)
        await message.answer(
            '🎭 RP-меню: свои персонажи, мобы и встречи без наград. '
            + ('Сначала выбери чат в мини-приложении.' if parameter == 'rp' else 'Мастер создаёт встречу и наблюдает за боем.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text='🎭 Открыть RP-меню', url=arena_link(username, parameter))]]))
    return router
