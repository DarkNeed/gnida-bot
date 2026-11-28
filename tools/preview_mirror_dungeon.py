"""Playable Mirror Wasteland on loopback with a disposable player and wallet."""

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode

from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_engine import fighter_xp_limit
from arena_mirror_dungeon import DEPTH
from arena_web import ROOT
from tools.preview_chaplain import application as base_application, TOKEN


async def application():
    app=await base_application()
    db=app['chaplain_review_db']
    for actor,name in ((40,'Испытатель глубин'),(50,'Испытатель наград')):
        await db.upsert_user(1,actor,str(actor),name)
        with db.connection:
            db._arena_profile_locked(1,actor,True)
            db._grant_profile_xp_locked('personal_profiles',1,actor,fighter_xp_limit())
            db.connection.execute('''UPDATE personal_profiles SET class_id='warrior',progression_level=20,
                progression_pending_level=0 WHERE chat_id=0 AND user_id=?''',(actor,))

    async def finish_battle(run,actor):
        # Preview shortcuts still use the normal victory/shop settlement.
        async with db._lock:
            row=db._arena_row_locked(run['battle_token'])
            state=json.loads(row['state_json'])
            state['sides']['b']['hp']=0
            state.update(finished=True,winner='a',finish_reason='knockout')
            with db.connection:
                db._arena_finish_locked(row,state)
                db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',(json.dumps(state),row['token']))
        return await db.arena_mirror_get(run['token'],actor)

    async def move(run,actor,action,value=''):
        return await db.arena_mirror_action(run['token'],actor,run['revision'],action,value)

    async def clear_room(run,actor):
        run=await move(run,actor,'visit',run['available'][0])
        return await finish_battle(run,actor) if run['phase']=='combat' else run

    async def review(request):
        stage=request.query.get('stage')
        actor={'shop':20,'final':30,'deep':40,'rewards':50}.get(stage,10)
        await db.arena_combat_settings(actor,enabled=request.query.get('qte','1')!='0')
        saved=await db.arena_mirror_list(1,actor)
        run=next((r for r in saved if r['status']=='active'),None)
        if stage=='rewards' and not run and saved:
            run=next((r for r in saved if r['status']=='finished'),None)
        if run and run['status']=='active' and request.query.get('fresh')=='1':
            await db.arena_leave_mirror(1,actor,run['token'])
            run=None
        if not run:
            run=await db.arena_mirror_start(1,actor)
            if stage in ('deep','rewards'):
                stop_after=DEPTH-1 if stage=='deep' else DEPTH
                while run['floor']<=stop_after:
                    while run['step']<len(run['route']):
                        run=await clear_room(run,actor)
                    run=await move(run,actor,'visit',run['available'][0])
                    run=await finish_battle(await move(run,actor,'next'),actor)
                    if run['floor']<DEPTH:
                        run=await move(run,actor,'next')
                    else:
                        break
            if stage in ('shop','final'):
                while run['step']<len(run['route']):
                    run=await clear_room(run,actor)
                if stage=='shop':
                    run=await db.arena_mirror_action(run['token'],actor,run['revision'],'visit',run['available'][0])
        raise web.HTTPFound('/mirror-preview?'+urlencode({'tgWebAppStartParam':'m_'+run['token'],'actor':actor}))

    async def preview(request):
        actor={'20':20,'30':30,'40':40,'50':50}.get(request.query.get('actor'),10)
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        key=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(key,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    app.router.add_get('/mirror-review',review)
    app.router.add_get('/mirror-preview',preview)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8174)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
