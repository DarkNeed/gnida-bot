"""Authenticated dungeon API. Preview shortcuts live only in tools/."""
from aiohttp import web

def register_nazarick(app,db,bot,actor_key,require_member,read_member):
    async def authorize(chat,actor,fresh=False):
        if type(chat) is not int or not await db.user_knows_chat(actor,chat):raise ValueError('Этот чат недоступен.')
        await db.arena_require_enabled(chat)
        if fresh:await require_member(bot,chat,actor)
        else:await read_member(chat,actor)

    async def board(request):
        actor=request[actor_key];chat=int(request.query.get('chat','0'));await authorize(chat,actor)
        return web.json_response(await db.nazarick_view(chat,actor))

    async def create(request):
        body=await request.json();actor=request[actor_key]
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        chat=body.get('chat');await authorize(chat,actor,True)
        return web.json_response(await db.nazarick_create(chat,actor))

    async def run(request):
        actor=request[actor_key];ident=request.match_info['id']
        async with db._lock:chat=db._nzd_row_locked(ident)['chat']
        await authorize(chat,actor,request.method=='POST')
        if request.method=='GET':return web.json_response(await db.nazarick_get(ident,actor))
        body=await request.json()
        if not isinstance(body,dict):raise ValueError('Некорректный запрос.')
        if body.get('action') in ('start','retry','treasury'):
            async with db._lock:
                snapshot=db._nzd_row_locked(ident)
                if body.get('revision')!=snapshot['revision']:raise ValueError('Поход изменился. Обновите страницу.')
                members=snapshot['members']
            for user in members:await authorize(chat,user,True)
        if body.get('action')=='claim':
            return web.json_response(await db.nazarick_claim(ident,actor,body.get('treatise'),body.get('equipment')))
        return web.json_response(await db.nazarick_action(ident,actor,body.get('action'),body.get('revision')))

    app.router.add_get('/api/nazarick',board)
    app.router.add_post('/api/nazarick',create)
    app.router.add_get('/api/nazarick/runs/{id}',run)
    app.router.add_post('/api/nazarick/runs/{id}',run)
