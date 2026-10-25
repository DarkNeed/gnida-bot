"""Slavery Mini App boundary; identity is always from validated Telegram initData."""

import asyncio
from aiohttp import web
from aiogram.exceptions import TelegramAPIError


def register_holdings(app, db, bot, actor_key, require_member, int_field):
    async def available_chats(actor):
        semaphore=asyncio.Semaphore(5)
        async def check(row):
            async with semaphore:
                try:
                    await asyncio.wait_for(require_member(bot,row['chat_id'],actor),timeout=10)
                    return row if await db.feature_enabled(row['chat_id'],'slavery') else None
                except (ValueError,TelegramAPIError,asyncio.TimeoutError):
                    return None
        rows=await asyncio.gather(*(check(row) for row in await db.holdings_chat_candidates(actor)))
        return [r for r in rows if r]

    async def authorize(request):
        chat=int(request.match_info['chat']);actor=request[actor_key]
        if chat>=0 or not await db.user_knows_chat(actor,chat):
            raise ValueError('Этот чат тебе недоступен. Сначала напиши в нём боту.')
        await require_member(bot,chat,actor)
        if not await db.feature_enabled(chat,'slavery'):
            raise ValueError('Рабовладение выключено в этом чате.')
        return chat,actor

    async def chats(request):
        return web.json_response(dict(chats=await available_chats(request[actor_key])))

    async def view(request):
        chat,actor=await authorize(request)
        return web.json_response(await db.holdings_view(chat,actor))

    async def action(request):
        chat,actor=await authorize(request)
        body=await request.json()
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        kind=body.get('action');notice=''
        if isinstance(kind,str) and kind.startswith('trader_'):
            users=[]
            if kind in ('trader_appraise','trader_list'):users=[body.get('worker')]
            elif kind=='trader_order':users=body.get('users')
            elif kind=='trader_buy':users=await db.trader_listing_members(chat,body.get('listing'))
            if not isinstance(users,list) or len(users)>2:raise ValueError('Некорректные участники.')
            for user in users:
                if type(user) is not int or user<=0:raise ValueError('Некорректный участник.')
                member=await require_member(bot,chat,user)
                if getattr(getattr(member,'user',None),'is_bot',False):raise ValueError('Боты не участвуют в торговле.')
            result=await db.trader_action(chat,actor,body)
            return web.json_response(dict(**result,holdings=await db.holdings_view(chat,actor)))
        if kind=='expedition_quote':
            users=body.get('users')
            if not isinstance(users,list) or len(users)>5:raise ValueError('Отряд: от одного до пяти участников.')
            # Do not dispatch without a fresh membership check for each fighter.
            for user in users:
                if type(user) is not int or user<=0:raise ValueError('Некорректный участник.')
                await require_member(bot,chat,user)
            return web.json_response(dict(quote=await db.expedition_quote(chat,actor,body.get('mission'),users)))
        if kind=='expedition_start':
            users=body.get('users')
            if not isinstance(users,list) or len(users)>5:raise ValueError('Отряд: от одного до пяти участников.')
            for user in users:
                if type(user) is not int or user<=0:raise ValueError('Некорректный участник.')
                await require_member(bot,chat,user)
            await db.expedition_start(chat,actor,body.get('mission'),users,body.get('revision'),body.get('nonce'))
            notice='Отряд отправлен. Состав и риски зафиксированы.'
        elif kind=='assign':
            notice=await db.enterprise_batch(chat,actor,body.get('users'),body.get('site'),body.get('role'),body.get('revision'))
        elif kind=='close':
            if body.get('confirm') is not True:raise ValueError('Сначала подтверди закрытие предприятия.')
            notice=await db.enterprise_close(chat,actor,int_field(body,'site'),body.get('revision'))
        elif kind=='create':
            result=await db.enterprise_create(chat,actor,body.get('kind'))
            messages={'created':'Предприятие открыто.','exists':'Этот тип уже открыт.','limit':'Максимум три разных предприятия.',
                      'no_slaves':'Сначала нужен хотя бы один раб.','insufficient':'Недостаточно франков.'}
            if result!='created':raise ValueError(messages.get(result,'Не удалось открыть предприятие.'))
            notice=messages[result]
        elif kind=='upgrade':
            result=await db.enterprise_upgrade(chat,actor,int_field(body,'site'),int_field(body,'level'))
            if result!='upgraded':raise ValueError({'insufficient':'Недостаточно франков.','stale':'Уровень изменился. Обнови предприятие.','max':'Уже максимальный уровень.'}.get(result,'Предприятие недоступно.'))
            notice='Предприятие расширено.'
        elif kind=='edit':
            await db.enterprise_edit(chat,actor,int_field(body,'site'),body.get('field'),body.get('value'))
            notice='Оформление сохранено.'
        else:
            raise ValueError('Неизвестное действие.')
        return web.json_response(dict(notice=notice,holdings=await db.holdings_view(chat,actor)))

    app.router.add_get('/api/holdings/chats',chats)
    app.router.add_get('/api/holdings/{chat}',view)
    app.router.add_post('/api/holdings/{chat}',action)
