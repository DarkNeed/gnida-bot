"""Two real Mini App clients on disposable local data; never production data."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_web import create_arena_app, ROOT
from database import Database

TOKEN='local-spectator-preview-not-a-bot-token'


async def application():
    temporary=tempfile.TemporaryDirectory(prefix='gnida-spectator-preview-')
    db=Database(Path(temporary.name)/'preview.sqlite3')
    await db.connect()
    await db.upsert_chat(1,'Тест просмотра · временная база')
    for actor in (10,20,30):
        await db.upsert_user(1,actor,str(actor),'Испытатель '+str(actor))
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(
        status='member',user=SimpleNamespace(is_bot=False))))
    app=create_arena_app(db,bot,TOKEN)

    async def preview(request):
        actor=int(request.query.get('player','10'))
        if actor not in (10,20,30):raise web.HTTPBadRequest()
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+
            ',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        if request.query.get('silent')=='1':
            html=html.replace('<script src="/static/audio.js', '<script data-audio-silent="true" src="/static/audio.js')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def demo(request):
        # Reset only this script's disposable sandbox, not a user's database.
        db.connection.execute("UPDATE arena_battles SET status='cancelled' WHERE status IN ('active','offered')")
        db.connection.execute('DELETE FROM arena_qte_flows')
        db.connection.commit()
        mode=request.query.get('mode','block')
        await db.arena_combat_settings(20,defense_mode='block' if mode=='block' else 'dodge')
        row=await db.arena_offer(1,10,20,'personal',0)
        await db.arena_set_message(row['token'],1)
        with patch('arena_store.random.SystemRandom') as rng:
            rng.return_value.choice.return_value='a'
            row=await db.arena_setup(row['token'],20,'accept')
        data=json.loads(row['state_json'])
        for fighter in data['sides'].values():
            fighter['hp']=fighter['stats']['max_hp']=1000
        db.connection.execute('UPDATE arena_battles SET state_json=? WHERE token=?',
                              (json.dumps(data),row['token']))
        db.connection.commit()
        row=await db.arena_interactive_action(row['token'],10,row['revision'],'skill','bum_punch')
        if mode!='attack':
            stage=(await db.arena_qte_view('battle',row['token'],10))['challenge']
            from arena_qte_patterns import attack, profile, attack_frame
            trial=attack(profile(stage['profile']),stage['stats'],stage['seed'])
            tick=0
            while True:
                trial['time']=tick/120
                frame=attack_frame(trial)
                if frame['canHit'] and abs(frame['cursor']-frame['center'])<frame['width']/3:break
                tick+=1
            flow=db._qte_load_locked('battle',row['token'])
            flow['stages'][0]['started']-=10
            db._qte_save_locked(flow);db.connection.commit()
            row=await db.arena_get(row['token'])
            row=await db.arena_interactive_action(row['token'],10,row['revision'],'qte',
                proof=dict(ticks=tick,clicks=[tick]),challenge_id=stage['id'])
        source=10 if mode=='attack' else 20
        viewer=30
        link='/watch-client?tgWebAppStartParam=b_'+row['token']+'&player='
        html='''<!doctype html><meta charset="utf-8"><title>Тест просмотра мини-игр</title>
<style>body{margin:0;background:#0b1321;color:white;font:14px Arial}header{padding:12px}a{color:#e6b963;margin-right:18px}.panes{display:flex;height:calc(100vh - 65px)}iframe{width:50%;border:1px solid #40516a}</style>
<header>Слева игрок, справа зритель — один раз включи «Автопросмотр мини-игр». Звук только у игрока. <a href="?mode=attack">Попадание</a><a href="?mode=dodge">Уклонение</a><a href="?mode=block">Блок</a></header><div class="panes">'''
        html+=f'<iframe title="Игрок" src="{link}{source}"></iframe><iframe title="Зритель" src="{link}{viewer}&silent=1"></iframe></div>'
        # A real spectator stays connected while the left sandbox client swaps
        # to whoever must act next. No automatic skill use or forged proofs.
        html+='<script>const playerFrame=document.querySelector(\'iframe[title="Игрок"]\');const poll=setInterval(async()=>{try{const s=await(await fetch("/watch-demo-state/'+row['token']+'")).json();if(!s.active){clearInterval(poll);return;}const u=new URL(playerFrame.src);if(u.searchParams.get("player")!==String(s.actor)){u.searchParams.set("player",s.actor);playerFrame.src=u.href;}}catch{}},750);</script>'
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def state(request):
        row=await db.arena_get(request.match_info['token'])
        data=json.loads(row['state_json'])
        qte=await db.arena_qte_view('battle',row['token'],30)
        actor=qte.get('actor') if qte else None
        return web.json_response(dict(active=row['status']=='active',
            actor=actor or data['sides'][data['active_side']]['controller_id']))

    app.router.add_get('/watch-client',preview)
    app.router.add_get('/watch-demo',demo)
    app.router.add_get('/watch-demo-state/{token}',state)

    async def cleanup(_):
        await db.close();temporary.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8122)
    args=parser.parse_args()
    web.run_app(application(),host='127.0.0.1',port=args.port)
