"""Separate settlement entry, not a replacement for slave enterprises."""
import re
from aiogram import Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from arena_links import arena_link
from arena_web import require_member
from handlers.routes import text_or_caption_regexp

KINGDOM_RE=re.compile(r'^\s*/(?:королевство|поселение|карта|kingdom)(?:@\w+)?\s*$',re.I)


def create_kingdom_router(db,bot,username,enabled):
    router=Router(name='settlement_kingdom')
    @router.message(text_or_caption_regexp(KINGDOM_RE))
    async def kingdom(message):
        if not message.from_user or message.from_user.is_bot:return
        if not enabled:await message.answer('Карта поселений недоступна: нужно настроить WEBAPP_URL.');return
        if message.chat.type not in ('private','group','supergroup'):
            await message.answer('Используй /карта или /королевство в группе либо в ЛС боту.');return
        parameter='kingdom'
        if message.chat.type!='private':
            try:
                await require_member(bot,message.chat.id,message.from_user.id)
                await db.arena_require_enabled(message.chat.id)
                await db.upsert_chat(message.chat.id,message.chat.title or str(message.chat.id))
                await db.upsert_user(message.chat.id,message.from_user.id,message.from_user.username,message.from_user.full_name,touch=False)
            except ValueError as error:await message.answer(str(error));return
            parameter+='_'+str(message.chat.id)
        await message.answer('🗺️ Королевства · общая карта чата\n\nОсновывай поселение, развивай хозяйство и защищай жителей. '
            'Основание: 20 000 ₣, 15 уровень и ранг охотника C. Чужие поселения можно смотреть, а за помощь — получать личную награду из бюджета поселения заказчика. '
            'Бюджет поселения отделён от кошелька: пополняй его вручную и включай налоги во вкладке «Бюджет». '
            'В ЛС сначала выбери чат.',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='🗺️ Открыть карту мира',url=arena_link(username,parameter))]]))
    return router
