"""Durable fictional-debt notices: no collection without a delivered warning."""
import asyncio
import html
import json
import re
from datetime import datetime
from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError
from arena_web import require_member

WAGER_COMMAND=re.compile(r'^\s*[!/]?депнуть(?:@\w+)?\s+@',re.I)
WAGER_FULL=re.compile(r'^\s*[!/]?депнуть(?:@\w+)?\s+(?P<tag>@[A-Za-z0-9_]{1,32})\s*$',re.I)
BORROW_COMMAND=re.compile(r'^\s*[!/]?взять(?:@\w+)?\s+(?:в\s+долг|кредит)(?:\s|$)',re.I)
REPAY_COMMAND=re.compile(r'^\s*[!/]?(?:вернуть|погасить)(?:@\w+)?\s+долг(?:\s|$)',re.I)
STATUS_COMMAND=re.compile(r'^\s*[!/]?(?:мой\s+)?долг(?:@\w+)?\s*$',re.I)
MONEY=re.compile(r'(?P<number>[0-9]+(?:[ \u00a0\u202f][0-9]{3})*)(?:\s*(?:₣|франк(?:а|ов)?))?',re.I)


def command_amount(text, pattern, *, allow_all=False):
    prefix=pattern.match(text)
    payload=text[prefix.end():].strip() if prefix else ''
    if allow_all and payload.casefold() in ('','все','всё'):
        return 'all'
    match=MONEY.fullmatch(payload)
    if not match:
        raise ValueError('Укажи целую положительную сумму: «взять в долг 1000», «взять кредит 1000» или «вернуть долг 500».')
    from slave_finance import positive
    # Check length before converting arbitrary Telegram input to an integer.
    digits=re.sub(r'\s','',match['number'])
    if len(digits)>18:
        raise ValueError('Сумма слишком велика для кошелька.')
    return positive(int(digits))


def confirmation_keyboard(row):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='✅ Подтвердить',callback_data='nf:y:'+row['id']),
        InlineKeyboardButton(text='Отмена',callback_data='nf:n:'+row['id']),
    ]])


def create_finance_router(db):
    router=Router(name='slave_finance')
    command_lock=asyncio.Lock()

    async def actor_in_chat(message,bot):
        actor=message.from_user
        if not actor or actor.is_bot or message.sender_chat:
            return None
        if message.chat.type not in ('group','supergroup'):
            await message.answer('Эти команды работают в группе и используют её кошелёк. В личке — Владения → Торговец.')
            return None
        await require_member(bot,message.chat.id,actor.id)
        if not await db.feature_enabled(message.chat.id,'slavery'):
            raise ValueError('Рабовладение выключено в этом чате.')
        await db.upsert_chat(message.chat.id,message.chat.title or str(message.chat.id))
        await db.settle_businesses_for_user(actor.id)
        await db.upsert_user(message.chat.id,actor.id,actor.username,actor.full_name or str(actor.id))
        return actor

    async def finance_command(message,bot):
        try:
            actor=await actor_in_chat(message,bot)
            if not actor:return
            text=message.text or message.caption or ''
            chat=message.chat.id
            if STATUS_COMMAND.fullmatch(text):
                state=await db.finance_command_state(chat,actor.id)
                loan=state['loan']
                if not loan:
                    await message.answer(f'💰 Долга нет. Лимит займа на аккаунт: {state["limit"]} ₣.\n«Взять в долг 1000» или «Взять кредит 1000».\nРостовщик пока помнит тебя как человека, а не строку инвентаря.')
                else:
                    from database import BUSINESS_STATS_TZ
                    deadline=datetime.fromtimestamp(loan['due_at'],BUSINESS_STATS_TZ).strftime('%d.%m.%Y %H:%M МСК')
                    await message.answer(f'💰 Остаток долга: {loan["remaining"]} ₣ из {loan["total"]} ₣.\nСрок: {deadline}.\n'+
                        ('Ты у NPC: поступления погашают долг, плюс 1% исходного долга в час.\n' if loan['status']=='enslaved' else 'Долг общий для всех чатов. Проценты не накапливаются.\n')+
                        f'В кошельке этого чата: {state["balance"]} ₣.\n«Вернуть долг 500» — частично, «Погасить долг» — полностью.')
                return
            async with command_lock:
                previous=await db.finance_command_existing(chat,message.message_id,actor.id)
                if previous:
                    return  # Telegram redelivery cannot open a new approval or re-roll.
                who=f'<a href="tg://user?id={actor.id}">{html.escape(actor.full_name or str(actor.id))}</a>'
                if WAGER_COMMAND.match(text):
                    match=WAGER_FULL.fullmatch(text)
                    if not match:raise ValueError('Для ставки рабом напиши «депнуть @username». Для франков — «депнуть 100».')
                    candidates=await db.users_by_username(chat,match['tag'])
                    verified=[]
                    for candidate in candidates:
                        try:member=await require_member(bot,chat,candidate['user_id'])
                        except (ValueError,TelegramAPIError,asyncio.TimeoutError):continue
                        user=member.user
                        if not user.is_bot and user.username and user.username.casefold()==match['tag'][1:].casefold():
                            verified.append(user)
                    if len(verified)!=1:
                        raise ValueError('Не удалось проверить @ник. Участник должен написать в этот чат; затем укажи его актуальный @username.')
                    target=verified[0]
                    await db.upsert_user(chat,target.id,target.username,target.full_name or str(target.id),touch=False)
                    result=await db.finance_action(chat,actor.id,dict(action='finance_quote',worker=target.id))
                    q=result['quote'];body=dict(action='finance_wager',offer=result['offer'])
                    summary=(f'🎰 {who}, поставить <b>{html.escape(q["name"])}</b>?\n'
                        f'Стоимость: <b>{q["value"]} ₣</b>.\n'
                        f'17%: <b>+{q["payout"]} ₣</b>, раб остаётся.\n'
                        f'83%: раб переходит к NPC, цена у NPC — <b>{q["npc_price"]} ₣</b>.\n'
                        'Неоценённый считается по минимальной стоимости. После ставки — общий кулдаун 5 минут.\n'
                        'До подтверждения владение и деньги не меняются.')
                elif BORROW_COMMAND.match(text):
                    amount=command_amount(text,BORROW_COMMAND)
                    total=amount+(amount*15+99)//100
                    body=dict(action='finance_borrow',amount=amount)
                    summary=(f'💰 {who}, взять <b>{amount} ₣</b> в кошелёк этого чата?\n'
                        f'Вернуть <b>{total} ₣ за 72 часа</b>. Переплата 15% однократно.\n'
                        'После предупреждения NPC взыщет рабов на сумму просроченного долга, а при нехватке — тебя. '
                        'В рабстве у NPC поступления погашают долг; дополнительно списывается 1% исходного долга в час.\n'
                        'Деньги можно свободно переводить и депать. До подтверждения заём не выдаётся.')
                else:
                    amount=command_amount(text,REPAY_COMMAND,allow_all=True)
                    state=await db.finance_command_state(chat,actor.id)
                    if not state['loan']:raise ValueError('Долга нет. Не подсказывай ростовщику лишние идеи.')
                    if amount=='all':amount=state['loan']['remaining']
                    body=dict(action='finance_repay',amount=amount,loan=state['loan']['id'])
                    summary=f'💰 {who}, внести <b>{amount} ₣</b> в счёт долга?\nДеньги спишутся из кошелька этого чата. До подтверждения списания нет.'
                row=await db.finance_command_create(chat,message.message_id,actor.id,body,summary)
                try:
                    sent=await message.answer(summary+'\n\nПодтверждение действует 5 минут. Нажать может только автор команды.',
                        parse_mode='HTML',reply_markup=confirmation_keyboard(row))
                    await db.finance_command_bind(row['id'],actor.id,sent.message_id)
                except (TelegramAPIError,asyncio.TimeoutError):
                    await db.finance_command_close(row['id'],actor.id,cancelled=True)
                    raise
        except (ValueError,TelegramAPIError,asyncio.TimeoutError) as error:
            await message.answer(str(error) if isinstance(error,ValueError) else 'Не удалось проверить участников или отправить подтверждение. Попробуй позже.')

    router.message.register(finance_command,
        F.text.regexp(WAGER_COMMAND)|F.caption.regexp(WAGER_COMMAND)|
        F.text.regexp(BORROW_COMMAND)|F.caption.regexp(BORROW_COMMAND)|
        F.text.regexp(REPAY_COMMAND)|F.caption.regexp(REPAY_COMMAND)|
        F.text.regexp(STATUS_COMMAND)|F.caption.regexp(STATUS_COMMAND))

    @router.callback_query(F.data.startswith('nf:'))
    async def finance_confirmation(callback,bot):
        match=re.fullmatch(r'nf:([yn]):([0-9a-f]{32})',callback.data or '')
        message=callback.message;actor=callback.from_user
        if not match or not actor or actor.is_bot or not message or not hasattr(message,'edit_text'):
            await callback.answer('Подтверждение недоступно.',show_alert=True);return
        try:
            async with command_lock:
                row=await db.finance_command_get(match[2],message.chat.id,message.message_id,actor.id)
                if row['status']=='done':
                    text=html.escape(row['result']['notice'])
                    answer='Уже выполнено. Повторного списания нет.'
                elif row['status']=='cancelled':
                    text='Действие отменено. Деньги и рабы не списаны.';answer='Уже отменено.'
                elif match[1]=='n':
                    await db.finance_command_close(row['id'],actor.id,cancelled=True)
                    text='Действие отменено. Деньги и рабы не списаны. Ростовщик спрятал рулетку — пока измерительную.'
                    answer='Отменено.'
                else:
                    await require_member(bot,message.chat.id,actor.id)
                    body=json.loads(row['body']);body.update(confirm=True,nonce=row['id'])
                    if body['action']=='finance_wager':
                        for worker in await db.finance_wager_members(message.chat.id,actor.id,body):
                            member=await require_member(bot,message.chat.id,worker)
                            if member.user.is_bot:raise ValueError('Боты не участвуют в торговле.')
                    result=await db.finance_action(message.chat.id,actor.id,body)
                    await db.finance_command_close(row['id'],actor.id)
                    text=html.escape(result['notice']);answer='Готово.'
                await callback.answer(answer)
                who=f'<a href="tg://user?id={actor.id}">{html.escape(actor.full_name or str(actor.id))}</a>'
                text=who+'\n'+text
                try:await message.edit_text(text,parse_mode='HTML',reply_markup=None)
                except TelegramAPIError:pass  # Receipt persists even when Telegram cannot edit the message.
        except (ValueError,TelegramAPIError,asyncio.TimeoutError) as error:
            await callback.answer(str(error)[:180] if isinstance(error,ValueError) else 'Не удалось проверить участников. Попробуй позже.',show_alert=True)

    return router


async def sweep_finance(db, bot):
    for notice in await db.finance_sweep():
        text='⚖ Работорговец · '+notice['text']
        try:
            await bot.send_message(notice['user_id'],text)
        except (TelegramAPIError,asyncio.TimeoutError):
            try:
                await bot.send_message(notice['chat_id'],
                    f'<a href="tg://user?id={notice["user_id"]}">Должник</a>: '+html.escape(text),parse_mode='HTML')
            except (TelegramAPIError,asyncio.TimeoutError):
                continue
        await db.finance_notice_sent(notice['loan_id'],notice['kind'])
