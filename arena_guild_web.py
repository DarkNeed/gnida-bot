"""Authenticated guild entry points. Demo routes are intentionally not here."""
import asyncio
from aiohttp import web
from aiogram.exceptions import TelegramAPIError
from arena_guild_avatars import GuildAvatarCache


def register_guild(app,db,bot,actor_key,require_member,read_member,publisher=None):
    avatars=GuildAvatarCache(bot)
    async def authorize(chat,actor,fresh=False):
        if type(chat) is not int or not await db.user_knows_chat(actor,chat):raise ValueError('Этот чат недоступен.')
        await db.arena_require_enabled(chat)
        if fresh:
            member=await require_member(bot,chat,actor)
            if getattr(getattr(member,'user',None),'is_bot',False):raise ValueError('Боты не могут участвовать в гильдии.')
        else:await read_member(chat,actor)

    async def chats(request):
        actor=request[actor_key];semaphore=asyncio.Semaphore(5)
        async def check(row):
            async with semaphore:
                try:
                    await asyncio.wait_for(authorize(row['chat_id'],actor),10);return row
                except (ValueError,TelegramAPIError,asyncio.TimeoutError):return None
        rows=await asyncio.gather(*(check(r) for r in await db.holdings_chat_candidates(actor)))
        return web.json_response(dict(chats=[r for r in rows if r]))

    async def board(request):
        chat=int(request.query.get('chat','0'));actor=request[actor_key]
        await authorize(chat,actor)
        return web.json_response(await db.guild_view(chat,actor))

    async def create(request):
        body=await request.json();actor=request[actor_key]
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        chat=body.get('chat');await authorize(chat,actor,True)
        return web.json_response(await db.guild_create(chat,actor,body.get('contract'),body.get('nonce')))

    async def run(request):
        actor=request[actor_key];ident=request.match_info['id']
        # Read metadata without exposing it until live membership is checked.
        async with db._lock:chat=db._guild_row_locked(ident)['chat_id']
        await authorize(chat,actor,request.method=='POST')
        if request.method=='GET':return web.json_response(await db.guild_get(ident,actor))
        body=await request.json()
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        action=body.get('action')
        if action=='start':
            async with db._lock:members=db._guild_row_locked(ident)['members']
            for user in members:await authorize(chat,user,True)
        target=body.get('target')
        if target is not None and type(target) is not int:raise ValueError('Некорректный участник.')
        result=await db.guild_action(ident,actor,action,body.get('revision'),choice=body.get('choice'),item=body.get('item'),target=target)
        if publisher:await publisher.changed(ident)
        return web.json_response(result)

    async def invite(request):
        actor=request[actor_key];ident=request.match_info['id']
        async with db._lock:chat=db._guild_row_locked(ident)['chat_id']
        await authorize(chat,actor,True)
        if not publisher:raise ValueError('Отправка приглашений в этом режиме недоступна.')
        return web.json_response(await publisher.invite(ident,actor))

    async def avatar(request):
        actor=request[actor_key];ident=request.match_info['id'];user=int(request.match_info['user'])
        async with db._lock:
            row=db._guild_row_locked(ident);chat=row['chat_id'];members=row['members']
        await authorize(chat,actor)
        if user not in members:raise ValueError('Участник не относится к этому отряду.')
        value=await avatars.get(user)
        if not value:return web.Response(status=204,headers={'Cache-Control':'no-store','Vary':'X-Telegram-Init-Data'})
        data,mime=value
        return web.Response(body=data,content_type=mime,headers={
            'Cache-Control':'no-store','Vary':'X-Telegram-Init-Data','X-Content-Type-Options':'nosniff'})

    async def buy(request):
        body=await request.json();actor=request[actor_key]
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        chat=body.get('chat');await authorize(chat,actor,True)
        await db.guild_buy(chat,actor,body.get('item'),body.get('nonce'))
        return web.json_response(await db.guild_view(chat,actor))

    app.router.add_get('/api/guild/chats',chats)
    app.router.add_get('/api/guild/board',board)
    app.router.add_post('/api/guild/runs',create)
    app.router.add_get('/api/guild/runs/{id}',run)
    app.router.add_post('/api/guild/runs/{id}',run)
    app.router.add_post('/api/guild/runs/{id}/invite',invite)
    app.router.add_get('/api/guild/runs/{id}/avatars/{user:\\d+}',avatar)
    app.router.add_post('/api/guild/buy',buy)
