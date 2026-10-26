"""Authenticated RP APIs and public, sanitized, content-addressed appearances."""
import asyncio
import json
import re
from io import BytesIO
from pathlib import Path
from aiohttp import web
from PIL import Image, UnidentifiedImageError
from aiogram.exceptions import TelegramAPIError
from arena_images import MAX_SPRITE_BYTES, normalize_sprite


def normalize_avatar(raw):
    if not raw or len(raw) > MAX_SPRITE_BYTES:
        raise ValueError('PNG должен весить не больше 2 МБ.')
    try:
        with Image.open(BytesIO(raw), formats=['PNG']) as source:
            if not all(16 <= n <= 1024 for n in source.size) or getattr(source, 'n_frames', 1) != 1:
                raise ValueError('Нужен обычный PNG от 16 до 1024 пикселей по каждой стороне.')
            source.load()
            rgba = source.convert('RGBA')
            clean = Image.frombytes('RGBA', rgba.size, rgba.tobytes())
            output = BytesIO()
            clean.save(output, format='PNG')
            result = output.getvalue()
            if len(result) > MAX_SPRITE_BYTES:
                raise ValueError('Изображение после обработки больше 2 МБ.')
            return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Не удалось прочитать PNG.') from error


def register_rp(app, db, bot, actor_key, require_member, read_member, raid_changed, publisher=None):
    root = Path(__file__).parent / 'webapp'
    publication_lock, image_slots = asyncio.Lock(), asyncio.Semaphore(2)

    async def authorized(chat, actor, fresh=False):
        if not await db.user_knows_chat(actor, chat):
            raise ValueError('Этот чат недоступен. Сначала напиши в нём боту.')
        if fresh:
            await db.arena_require_enabled(chat)
            member = await require_member(bot, chat, actor)
            if getattr(getattr(member, 'user', None), 'is_bot', False):
                raise ValueError('Боты не могут создавать RP-встречи.')
        else:
            await read_member(chat, actor)

    async def chats(request):
        semaphore = asyncio.Semaphore(5)
        actor = request[actor_key]
        async def check(row):
            async with semaphore:
                try:
                    await asyncio.wait_for(authorized(row['chat_id'], actor), timeout=10)
                    return row
                except (ValueError, TelegramAPIError, asyncio.TimeoutError):
                    return None
        rows = await asyncio.gather(*(check(r) for r in await db.holdings_chat_candidates(actor)))
        return web.json_response(dict(chats=[r for r in rows if r]))

    async def catalog(request):
        return web.json_response(await db.arena_rp_catalog())

    async def settings(request):
        actor=request[actor_key]
        body=await request.json() if request.method=='POST' else None
        if request.method=='POST' and (not isinstance(body,dict) or type(body.get('enabled')) is not bool):
            raise ValueError('Некорректный режим мини-игр.')
        async with db._lock:
            with db.connection:
                if body is not None:
                    db.connection.execute('INSERT INTO arena_combat_settings VALUES(?,?) ON CONFLICT(actor_id) DO UPDATE SET minigames=excluded.minigames',
                                          (actor,int(body['enabled'])))
                enabled=db._qte_enabled_locked(actor)
        return web.json_response(dict(combat_settings=dict(minigames=enabled),notice='Настройка мини-игр сохранена для новых боёв.'))

    async def templates(request):
        return web.json_response(dict(templates=await db.arena_rp_templates(request[actor_key])))

    async def save(request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Некорректный запрос.')
        result = await db.arena_rp_save(request[actor_key], body.get('kind'), body.get('definition'),
                                       ident=request.match_info.get('id'), revision=body.get('revision'))
        return web.json_response(dict(template=result))

    async def delete(request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Некорректный запрос.')
        await db.arena_rp_delete(request[actor_key], request.match_info['id'], body.get('revision'))
        return web.json_response(dict(ok=True))

    async def preview(request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Некорректный запрос.')
        return web.json_response(await db.arena_rp_preview(request[actor_key], body.get('kind'), body.get('definition')))

    async def image(request):
        if request.content_type != 'image/png' or request.query.get('kind') not in ('avatar', 'sprite'):
            raise ValueError('Нужен PNG: изображение или спрайт.')
        async with image_slots:
            raw = await request.clone(client_max_size=MAX_SPRITE_BYTES + 1).read()
            png = await asyncio.to_thread(normalize_sprite if request.query['kind'] == 'sprite' else normalize_avatar, raw)
        key = await db.arena_rp_image(request[actor_key], png)
        return web.json_response(dict(key=key, url='/rp/images/' + key + '.png'))

    async def public_image(request):
        key = request.match_info['key']
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise web.HTTPNotFound()
        png = await db.arena_rp_image_png(key)
        if png is None:
            raise web.HTTPNotFound()
        return web.Response(body=png, content_type='image/png', headers={'Cache-Control': 'public,max-age=31536000,immutable'})

    async def encounters(request):
        chat, actor = int(request.query.get('chat', '0')), request[actor_key]
        await authorized(chat, actor)
        async with db._lock:
            db._raid_expire_locked()
            db.connection.commit()
            rows = db.connection.execute("SELECT token,status,round,creator_id,encounter_json FROM arena_raids WHERE chat_id=? AND boss_id='encounter' ORDER BY created_at DESC LIMIT 30", (chat,)).fetchall()
            result = [dict(token=r['token'], status=r['status'], round=r['round'], creator_id=r['creator_id'],
                           roster=json.loads(r['encounter_json'])['roster']) for r in rows]
        return web.json_response(dict(encounters=result))

    async def create_encounter(request):
        body = await request.json()
        if not isinstance(body, dict) or type(body.get('chat')) is not int:
            raise ValueError('Некорректный запрос.')
        actor, chat = request[actor_key], body['chat']
        await authorized(chat, actor, True)
        async with publication_lock:
            row = await db.arena_rp_encounter_create(chat, actor, body.get('roster'), body.get('nonce'))
            notice = 'Встреча создана. Мастер может остаться наблюдателем или вступить в отряд.'
            if publisher and row['status'] == 'lobby' and row['message_id'] is None:
                try:
                    sent = await bot.send_message(chat, await publisher.body(row), reply_markup=publisher.keyboard(row), parse_mode='HTML')
                    await db.arena_raid_set_message(row['token'], sent.message_id)
                except TelegramAPIError:
                    notice = 'Встреча создана, но сообщение не отправлено в чат. Игроки могут найти её через /рп → Встречи.'
            return web.json_response(dict(token=row['token'], notice=notice, published=bool(publisher)))

    async def page(request):
        from arena_assets import render_arena_index
        return web.Response(text=render_arena_index(root), content_type='text/html', headers={'Cache-Control': 'no-store'})

    async def client(request):
        return web.FileResponse(root / 'rp-client', headers={'Content-Type': 'application/javascript; charset=utf-8', 'Cache-Control': 'no-cache'})

    app.router.add_get('/rp', page)
    app.router.add_get('/rp/client.js', client)
    app.router.add_get('/rp/images/{key}.png', public_image)
    app.router.add_get('/api/rp/chats', chats)
    app.router.add_get('/api/rp/catalog', catalog)
    app.router.add_get('/api/rp/settings', settings)
    app.router.add_post('/api/rp/settings', settings)
    app.router.add_get('/api/rp/templates', templates)
    app.router.add_post('/api/rp/templates', save)
    app.router.add_put('/api/rp/templates/{id}', save)
    app.router.add_delete('/api/rp/templates/{id}', delete)
    app.router.add_post('/api/rp/preview', preview)
    app.router.add_post('/api/rp/images', image)
    app.router.add_get('/api/rp/encounters', encounters)
    app.router.add_post('/api/rp/encounters', create_encounter)
