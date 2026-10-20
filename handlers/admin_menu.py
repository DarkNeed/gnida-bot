"""Private chat-owner administration; bot-owner exclusive tools stay separate."""

import html
import re
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest
from menu_context import manages_chat, verified_constructor_chat


def markup(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_admin_menu_router(database):
    router = Router(name='private_admin_menu')

    async def picker(bot, actor):
        rows = []
        for chat in await database.list_menu_chats():
            if await manages_chat(bot,int(chat['chat_id']),actor):
                rows.append([InlineKeyboardButton(text=str(chat['title']),callback_data=f"adm:chat:{chat['chat_id']}")])
        return ('<b>⚙️ Админ-меню · выбери чат</b>\nДоступны только чаты, которыми ты можешь управлять.' if rows else
                'Нет доступных чатов для управления. Меню доступно владельцам Telegram-чатов и владельцу бота.'), markup(rows)

    async def home(bot, actor, modules=False):
        chat = await verified_constructor_chat(database,bot,actor)
        if chat is None:
            return await picker(bot,actor)
        title = f"📍 <b>Чат: {html.escape(str(chat['title']))}</b>\n\n"
        if modules:
            settings = await database.arena_modules(int(chat['chat_id']))
            rows = [[InlineKeyboardButton(text=('🟢 ' if m['enabled'] else '⚪ ')+m['name'],
                       callback_data=f"adm:toggle:{chat['chat_id']}:{m['id']}:{int(not m['enabled'])}:{settings['revision']}")] for m in settings['modules']]
            rows.append([InlineKeyboardButton(text='← Админ-меню',callback_data='adm:home')])
            return title+'<b>🧩 Функции чата</b>\nНажми, чтобы включить или выключить модуль.\nАрена: личные бои, пустоши и рейды. Рабовладение: рабство и предприятия. Классы доступны всем. Выключение не удаляет прогресс; при выключении арены незавершённые бои закрываются со возвратом ставок.', markup(rows)
        merchant = await database.arena_merchant_notifications(int(chat['chat_id']))
        merchant_label = '🧳 Сообщения торговца: ' + ('ВКЛ' if merchant['enabled'] else 'ВЫКЛ')
        return title+'<b>⚙️ Админ-меню</b>\nНастройки, команды и события относятся только к этому чату.\nСообщения торговца — только объявления в группе; магазин и покупки остаются доступны в арене.', markup([
            [InlineKeyboardButton(text='🧩 Функции чата',callback_data='adm:modules')],
            [InlineKeyboardButton(text=merchant_label,
                callback_data=f"adm:merchant:{chat['chat_id']}:{int(not merchant['enabled'])}:{merchant['revision']}")],
            [InlineKeyboardButton(text='⚙️ Кастомные команды',callback_data='cc:list:0')],
            [InlineKeyboardButton(text='🎲 Конструктор событий',callback_data='evm:list')],
            [InlineKeyboardButton(text='💬 Выбрать чат',callback_data='adm:chats')],
        ])

    async def edit(callback, view):
        try:
            await callback.message.edit_text(view[0],reply_markup=view[1],parse_mode='HTML')
        except TelegramBadRequest as error:
            if 'message is not modified' not in str(error).casefold():
                await callback.message.answer(view[0],reply_markup=view[1],parse_mode='HTML')

    @router.message(F.text.regexp(re.compile(r'^/(?:админ|admin)(?:@\w+)?\s*$',re.I)))
    async def admin_menu(message: Message, bot, state: FSMContext):
        if message.chat.type!='private' or not message.from_user:
            return
        await state.clear()
        body, keyboard = await home(bot,message.from_user.id)
        await message.answer(body,reply_markup=keyboard,parse_mode='HTML')

    @router.callback_query(F.data.startswith('adm:'))
    async def admin_callback(callback: CallbackQuery, bot, state: FSMContext):
        if not callback.message or callback.message.chat.type!='private' or not callback.from_user:
            await callback.answer('Только в личке бота.',show_alert=True)
            return
        await state.clear()
        parts = (callback.data or '').split(':')
        actor, action = callback.from_user.id, parts[1]
        notice = None
        try:
            if action=='chat':
                chat = int(parts[2])
                if not any(int(c['chat_id'])==chat for c in await database.list_menu_chats()) or not await manages_chat(bot,chat,actor):
                    raise ValueError('Нет прав владельца этого чата.')
                await database.select_menu_chat(actor,chat)
            elif action=='toggle':
                chat = await verified_constructor_chat(database,bot,actor)
                if chat is None or int(parts[2])!=int(chat['chat_id']) or parts[4] not in {'0','1'}:
                    raise ValueError('Чат изменился или права владельца утрачены.')
                notice = await database.arena_set_module(int(parts[2]),actor,parts[3],parts[4]=='1',int(parts[5]))
            elif action=='merchant':
                chat = await verified_constructor_chat(database,bot,actor)
                if chat is None or int(parts[2])!=int(chat['chat_id']) or parts[3] not in {'0','1'}:
                    raise ValueError('Чат изменился или права владельца утрачены.')
                notice = await database.arena_set_merchant_notifications(
                    int(parts[2]), actor, parts[3]=='1', int(parts[4]))
            elif action not in {'home','chats','modules'}:
                raise ValueError('Кнопка устарела.')
            view = await picker(bot,actor) if action=='chats' else await home(bot,actor,action in {'modules','toggle'})
            await edit(callback,view)
            await callback.answer(notice)
        except (ValueError,IndexError) as error:
            await callback.answer(str(error) or 'Кнопка устарела.',show_alert=True)

    return router
