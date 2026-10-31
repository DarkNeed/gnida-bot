"""Signed Mini App API. Each map is scoped to a live, accessible Telegram chat."""
import asyncio
from aiohttp import web
from aiogram.exceptions import TelegramAPIError
from arena_kingdom_rules import coordinates, SITES


def register_kingdom(app, db, bot, actor_key, require_member, read_member):
    async def authorize(chat, actor, fresh=False):
        if type(chat) is not int or not await db.user_knows_chat(actor,chat):raise ValueError('Этот чат недоступен.')
        await db.arena_require_enabled(chat)
        if fresh:
            member=await require_member(bot,chat,actor)
            if getattr(getattr(member,'user',None),'is_bot',False):raise ValueError('Боты не могут управлять поселениями.')
        else:await read_member(chat,actor)

    async def chats(request):
        actor=request[actor_key];semaphore=asyncio.Semaphore(5)
        async def allowed(row):
            async with semaphore:
                try:await asyncio.wait_for(authorize(row['chat_id'],actor),10);return row
                except (ValueError,TelegramAPIError,asyncio.TimeoutError):return None
        rows=await asyncio.gather(*(allowed(r) for r in await db.holdings_chat_candidates(actor)))
        return web.json_response(dict(chats=[row for row in rows if row]))

    async def world(request):
        actor=request[actor_key]
        if request.method=='GET':
            chat=int(request.query.get('chat','0'));await authorize(chat,actor)
            return web.json_response(await db.kingdom_view(chat,actor))
        body=await request.json()
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        chat=body.get('chat');await authorize(chat,actor,True)
        result=await db.kingdom_action(chat,actor,body)
        if result.get('siege'):
            from arena_kingdom_notices import publish_kingdom_notices
            await publish_kingdom_notices(db,bot)
            result['view']=await db.kingdom_view(chat,actor)
        return web.json_response(result)

    async def activity(request):
        actor=request[actor_key];body=await request.json()
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        chat=body.get('chat');await authorize(chat,actor,True)
        site=SITES.get(coordinates(body.get('q'),body.get('r')))
        if not site:raise ValueError('На этой клетке нет приключения.')
        if site['kind'] in ('faction','war'):raise ValueError('Это не лобби рейда. Военные цели открываются через армию поселения, отношения — через события.')
        if site['kind']=='guild':
            result=await db.guild_create(chat,actor,site['target'],body.get('nonce'))
            return web.json_response(dict(kind='guild',id=result['id']))
        result=await db.arena_raid_create(chat,actor,site['target'],silent=True)
        return web.json_response(dict(kind='raid',id=result['token']))

    app.router.add_get('/api/kingdom/chats',chats)
    app.router.add_get('/api/kingdom/world',world)
    app.router.add_post('/api/kingdom/world',world)
    app.router.add_post('/api/kingdom/activity',activity)
