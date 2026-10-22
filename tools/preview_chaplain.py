"""Playable Chaplain review. Disposable SQLite, synthetic Telegram auth, localhost only."""

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
from arena_engine import fighter_xp_limit
from arena_web import create_arena_app, ROOT
from database import Database

TOKEN = 'local-chaplain-review-not-a-real-bot-token'


async def application():
    temporary = tempfile.TemporaryDirectory(prefix='gnida-chaplain-review-')
    db = Database(Path(temporary.name) / 'preview.sqlite3')
    await db.connect()
    await db.upsert_chat(1, 'Капеллан · локальная проверка')
    builds = (
        (10, 'mage', 'mage_archmage', ['mana_shot', 'mana_focus', 'mana_barrier', 'last_amendment']),
        (20, 'priest', 'priest_bishop', ['holy_strike', 'priest_heal']),
        (30, 'hunter', 'hunter_moon', ['hunter_shot', 'blood_bullets']),
    )
    for actor, cls, branch, loadout in builds:
        await db.upsert_user(1, actor, str(actor), {10: 'Испытатель', 20: 'Епископ', 30: 'Охотник'}[actor])
        db._arena_profile_locked(1, actor, True)
        db._grant_profile_xp_locked('personal_profiles', 1, actor, fighter_xp_limit())
        db.connection.execute('''UPDATE personal_profiles SET class_id=?,archclass_id=?,archclass_stage=20,
            progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?''',
            (cls, branch, json.dumps(loadout), actor))
    db.connection.execute('INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)', (0, 10, 1, 'skill', 'last_amendment'))
    db.connection.commit()
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member', user=SimpleNamespace(is_bot=False))))
    app = create_arena_app(db, bot, TOKEN)
    app['chaplain_review_db'] = db

    @web.middleware
    async def review_helpers(request, handler):
        # Demo allies choose without a second tab. This helper is never installed
        # in the production app, and does not alter the actual combat resolver.
        if request.path.startswith('/api/raid/'):
            async with db._lock:
                row = db.connection.execute('SELECT * FROM arena_raids WHERE token=?', (request.path.split('/')[-1],)).fetchone()
                if row and row['status'] == 'active':
                    data = json.loads(row['data_json'])
                    changed = False
                    for key, p in data['players'].items():
                        if key == '10' or p.get('withdrawn') or p['fighter']['hp'] <= 0 or p['selected'] is not None:
                            continue
                        f = p['fighter']
                        if key == '20':
                            choice = 'priest_heal' if f['hp'] < f['stats']['max_hp'] * .6 else 'holy_strike'
                        else:
                            choice = 'hunter_shot'
                        from arena_engine import validate_skill
                        from arena_raid_engine import pair_state
                        try:
                            _, skills = db._fighter_catalog_locked()
                            validate_skill(pair_state(f, data['boss']), 'a', choice, skills)
                        except ValueError:
                            choice = 'defend'
                        p['selected'] = choice
                        changed = True
                    if changed:
                        db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?', (json.dumps(data), row['token']))
                        db.connection.commit()
        return await handler(request)

    app.middlewares.append(review_helpers)

    async def start(request):
        async with db._lock:
            db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
            db.connection.execute('DELETE FROM arena_qte_flows')
            db.connection.commit()
        await db.arena_combat_settings(10, enabled=request.query.get('qte', '1') != '0')
        row = await db.arena_raid_create(1, 10, boss_id='chaplain', silent=True)
        if request.query.get('party') == '3':
            for actor in (20, 30):
                await db.arena_raid_setup(row['token'], actor, 'join')
        row = await db.arena_raid_setup(row['token'], 10, 'start')
        data = json.loads(row['data_json'])
        mode = request.query.get('mode', 'fresh')
        if mode in ('phase2', 'phase3', 'phase4'):
            phase = int(mode[-1])
            data['chaplain'].update(phase=phase, recoveries=phase-1, next_rewind=10)
            data['round'] = 3 if phase != 3 else 4
        elif mode == 'transition':
            data['boss']['hp'] = round(data['boss']['stats']['max_hp'] * .31)
        elif mode == 'victory':
            data['chaplain'].update(phase=4, recoveries=3)
            data['boss']['hp'] = 1
        if mode == 'amendment':
            data['players']['10']['fighter']['hp'] //= 2
        from arena_chaplain import set_intent
        if mode == 'seal':
            data['round'] = 6
            data['chaplain']['next_rewind'] = 7
            set_intent(data)
            data['round'] = 7
        if mode == 'pattern':
            phase = max(1, min(4, int(request.query.get('phase', '2'))))
            move = max(0, min(2, int(request.query.get('move', '0'))))
            data['chaplain'].update(phase=phase, recoveries=phase-1, next_rewind=10)
            data['round'] = move + 1
        set_intent(data)
        async with db._lock:
            db._raid_save_locked(row, data)
            db.connection.commit()
        raise web.HTTPFound('/preview?tgWebAppStartParam=r_' + row['token'])

    async def preview(request):
        pairs = dict(auth_date=str(int(time.time())), user=json.dumps(dict(id=10)))
        secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, '\n'.join(k + '=' + v for k, v in sorted(pairs.items())).encode(), hashlib.sha256).hexdigest()
        html = render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:' + json.dumps(urlencode(pairs)) +
            ',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html, content_type='text/html', headers={'Cache-Control': 'no-store'})

    async def index(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Капеллан · проверка рейда</title><style>*{box-sizing:border-box}body{margin:0;background:#090e19;color:#e9ddbd;font:14px system-ui}header{padding:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}button,select{padding:9px;border:1px solid #8b754b;border-radius:8px;background:#202839;color:#f6e3b7;cursor:pointer}small{color:#afbdd0}iframe{width:100%;height:calc(100dvh - 135px);min-height:500px;border:0}h3{margin:0}label{font-size:12px}</style>
<header><h3>Капеллан · временная база</h3><label>Отряд <select id="party"><option value="1">Соло</option><option value="3">Трое (союзники авто)</option></select></label><label><input id="qte" type="checkbox" checked>Мини-игры</label><label>Экран <select id="screen"><option value="100%">Адаптивный</option><option value="390px">Телефон · 390px</option></select></label><small>Сценарии начинают новый бой. Реальные аккаунты не затрагиваются.</small></header>
<header><button data-mode="fresh">Фаза 1</button><button data-mode="phase2">Фаза 2 · интерфейс</button><button data-mode="phase3">Фаза 3 · подмена</button><button data-mode="phase4">Фаза 4</button><button data-mode="transition">Порог 30% HP</button><button data-mode="seal">Обычный откат</button><button data-mode="victory">Финальное добивание</button><button data-mode="amendment">Трактат · HP 50%</button></header>
<header><label>Мини-игры фазы <select id="pattern-phase"><option>1</option><option selected>2</option><option>3</option><option>4</option></select></label><button data-pattern="0">Атака 1</button><button data-pattern="1">Атака 2</button><button data-pattern="2">Атака 3</button><small>В бою нажми «Защищаться», чтобы проверить входящую мини-игру. ⓘ босса — разрез. Повреждённый навык — удерживать.</small></header>
<iframe title="Боевой интерфейс Капеллана" src="/chaplain-demo" style="display:block;max-width:100%;margin:auto"></iframe><script>document.addEventListener('click',e=>{const b=e.target.closest('[data-mode],[data-pattern]');if(!b)return;const mode=b.dataset.mode||'pattern';document.querySelector('iframe').src='/chaplain-demo?mode='+mode+'&phase='+document.getElementById('pattern-phase').value+'&move='+(b.dataset.pattern||0)+'&party='+document.getElementById('party').value+'&qte='+(document.getElementById('qte').checked?'1':'0')});document.getElementById('screen').addEventListener('change',e=>{document.querySelector('iframe').style.width=e.target.value})</script></html>''', content_type='text/html')

    app.router.add_get('/chaplain-demo', start)
    app.router.add_get('/chaplain-review', index)
    app.router.add_get('/preview', preview)

    async def close(_):
        await db.close()
        temporary.cleanup()
    app.on_cleanup.append(close)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8123)
    args = parser.parse_args()
    web.run_app(application(), host='127.0.0.1', port=args.port)
