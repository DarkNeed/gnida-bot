"""Local RP encounter review: temporary DB, fake auth, no Telegram polling."""

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_engine import xp_for_next_level
from arena_web import create_arena_app, ROOT
from database import Database

TOKEN = 'local-encounter-demo-not-a-real-token'


async def application():
    temporary = tempfile.TemporaryDirectory(prefix='gnida-encounter-review-')
    db = Database(Path(temporary.name) / 'preview.sqlite3')
    await db.connect()
    await db.upsert_chat(1, 'РП-встреча · демо')
    for actor, name in ((10, 'Мастер'), (20, 'Испытатель'), (30, 'Союзник'), (40, 'Напарник')):
        await db.upsert_user(1, actor, str(actor), name)
        if actor != 10:
            db._arena_profile_locked(1, actor, True)
            db._grant_profile_xp_locked('personal_profiles', 1, actor, sum(xp_for_next_level(n) for n in range(1, 6)))
            db.connection.execute('''UPDATE personal_profiles SET class_id='warrior',progression_level=5,
                progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?''',
                (json.dumps(['armor_split', 'steel_charge', 'counter_lunge', 'bum_punch']), actor))
    db.connection.commit()
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member', user=SimpleNamespace(is_bot=False))))
    app = create_arena_app(db, bot, TOKEN)

    @web.middleware
    async def auto_allies(request, handler):
        if request.path.startswith('/api/raid/'):
            async with db._lock:
                raw = db.connection.execute('SELECT * FROM arena_raids WHERE token=?', (request.path.split('/')[-1],)).fetchone()
                if raw and raw['status'] == 'active':
                    data = json.loads(raw['data_json'])
                    from arena_encounters import alive_enemies
                    target = next(iter(alive_enemies(data)), None)
                    for key, p in data['players'].items():
                        if key != '20' and not p.get('withdrawn') and p['fighter']['hp'] > 0 and p['selected'] is None:
                            p.update(selected='bum_punch', selected_target=target)
                    db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?', (json.dumps(data), raw['token']))
                    db.connection.commit()
        return await handler(request)
    app.middlewares.append(auto_allies)

    async def start(request):
        with db.connection:
            db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
            db.connection.execute('DELETE FROM arena_qte_flows')
        mode = request.query.get('mode', 'player')
        await db.arena_combat_settings(20, enabled=request.query.get('qte', '1') != '0',
                                      defense_mode='block' if request.query.get('defense') == 'block' else 'dodge')
        row = await db.arena_encounter_create(1, 10, ['goblin', 'brute', 'shaman'])
        await db.arena_raid_set_message(row['token'], 1)
        if mode != 'lobby':
            for actor in (20, 30, 40):
                await db.arena_raid_setup(row['token'], actor, 'join')
            await db.arena_raid_setup(row['token'], 10, 'start')
        raise web.HTTPFound('/preview?' + urlencode(dict(tgWebAppStartParam='r_' + row['token'], actor=20 if mode == 'player' else 10)))

    async def preview(request):
        actor = 20 if request.query.get('actor') == '20' else 10
        pairs = dict(auth_date=str(int(time.time())), user=json.dumps(dict(id=actor)))
        secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, '\n'.join(k + '=' + v for k, v in sorted(pairs.items())).encode(), hashlib.sha256).hexdigest()
        html = render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:' + json.dumps(urlencode(pairs)) +
            ',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html, content_type='text/html', headers={'Cache-Control': 'no-store'})

    async def index(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>РП-встречи · демо</title>
<style>body{background:#101827;color:#eedcb6;font:15px system-ui;margin:0}header{display:flex;flex-wrap:wrap;gap:12px;padding:12px}a{color:#f1c574}iframe{width:100%;height:calc(100dvh - 90px);border:0;display:block;margin:auto;max-width:100%}button{padding:8px;background:#273954;color:#fff;border:1px solid #977e4e;border-radius:6px}</style>
<header><b>Временная база · без Telegram и наград</b><a target="arena" href="/encounter-demo?mode=lobby">Сбор · мастер</a><a target="arena" href="/encounter-demo?mode=master">Бой · мастер</a><a target="arena" href="/encounter-demo?mode=player&amp;defense=dodge">Играть · уклонение</a><a target="arena" href="/encounter-demo?mode=player&amp;defense=block">Играть · блок</a><a target="arena" href="/encounter-demo?mode=player&amp;qte=0">Без мини-игр</a><button onclick="document.querySelector('iframe').style.width='390px'">390px</button><button onclick="document.querySelector('iframe').style.width='100%'">ПК</button></header><iframe name="arena" title="Демо РП-встречи" src="/encounter-demo?mode=player&amp;defense=block"></iframe></html>''', content_type='text/html')

    app.router.add_get('/encounter-review', index)
    app.router.add_get('/encounter-demo', start)
    app.router.add_get('/preview', preview)
    async def cleanup(_):
        await db.close()
        temporary.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8124)
    web.run_app(application(), host='127.0.0.1', port=parser.parse_args().port)
