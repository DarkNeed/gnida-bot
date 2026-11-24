"""Production API/UI with disposable SQLite; never uses real bot data."""
import argparse
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.preview_chaplain import application as base_application, TOKEN
from arena_assets import render_arena_index
from arena_web import ROOT


async def application():
    app = await base_application()
    db = app['chaplain_review_db']
    app.middlewares[:] = [m for m in app.middlewares if m.__name__ != 'review_helpers']
    db.connection.execute("UPDATE personal_profiles SET class_id='assassin',archclass_id='assassin_shadow',loadout=? WHERE user_id=10",
                          (json.dumps(['assassin_cut','assassin_needle','assassin_smoke','arch_assassin_shadow']),))
    db.connection.commit()

    async def start(request):
        mode = request.query.get('mode', 'solo')
        async with db._lock:
            db.connection.execute("UPDATE arena_battles SET status='cancelled' WHERE status IN ('pending','active')")
            db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
            db.connection.execute('DELETE FROM arena_qte_flows')
            db.connection.commit()
        await db.arena_combat_settings(10, enabled=request.query.get('qte','1')!='0',
            defense_mode='block' if request.query.get('defense')=='block' else 'dodge')
        await db.arena_combat_settings(20, enabled=request.query.get('qte','1')!='0')
        if mode == 'solo':
            row = await db.arena_wasteland(1,10,personal=True)
            prefix = 'b_'
        elif mode == 'pvp':
            row = await db.arena_offer(1,10,20,'personal')
            await db.arena_set_message(row['token'],1)
            row = await db.arena_setup(row['token'],20,'accept')
            prefix = 'b_'
        else:
            if mode in ('party','encounter','bars'):
                row = await db.arena_encounter_create(1,30,['goblin','shaman'])
                await db.arena_raid_set_message(row['token'],1)
                for actor in ((10,20) if mode=='party' else (10,)):
                    await db.arena_raid_setup(row['token'],actor,'join')
                row = await db.arena_raid_setup(row['token'],30,'start')
                if mode == 'bars':
                    # One fast attacker and one slow one, with enough HP to
                    # observe several casts. All actions use production code.
                    from arena_unified_queue import clock, initialize
                    from arena_unified_store import catalog
                    async with db._lock:
                        state = json.loads(row['data_json'])
                        state['enemies']['e1']['stats']['speed'] = 30
                        state['enemies']['e2']['stats']['speed'] = 0
                        for fighter in [state['players']['10']['fighter'], *state['enemies'].values()]:
                            fighter['hp'] = fighter['stats']['max_hp'] = 1000
                        clock(state)['pending'].clear()
                        initialize(state, catalog(db))
                        db._raid_save_locked(row, state)
                        db.connection.commit()
            else:
                row = await db.arena_raid_create(1,10,request.query.get('boss','lei_heng'),silent=True)
                row = await db.arena_raid_setup(row['token'],10,'start')
            prefix = 'r_'
        raise web.HTTPFound('/live-preview?tgWebAppStartParam='+prefix+row['token'])

    async def preview(request):
        actor = 20 if request.query.get('actor')=='20' else 10
        pairs = dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret = hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html = render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    app.router.add_get('/live-queue-review',start)
    app.router.add_get('/live-preview',preview)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8155)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
