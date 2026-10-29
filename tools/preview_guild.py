"""Loopback-only hunter guild review with a disposable database. No Telegram IO."""
import argparse
import hashlib
import hmac
from html import escape
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_web import create_arena_app,ROOT,ACTOR
from database import Database
from arena_guild_rules import MONSTERS, art
from handlers.guild import GuildPublisher

TOKEN='guild-local-review-not-production'
CHAT=-100


async def application():
    folder=tempfile.TemporaryDirectory(prefix='gnida-guild-review-')
    db=Database(Path(folder.name)/'guild.sqlite3');await db.connect()
    await db.upsert_chat(CHAT,'Гильдия у Чёрного тракта · демо')
    for actor,name,cid,rank,level in ((10,'Твой охотник','warrior',3,20),(20,'Лис · напарник','hunter',2,20),(30,'Новый охотник','mage',0,7)):
        await db.upsert_user(CHAT,actor,str(actor),name);db._arena_profile_locked(CHAT,actor,True)
        loadout={'warrior':['armor_split','steel_charge','warrior_execute','bum_punch'],
                 'hunter':['hunter_shot','hunter_cut','hunter_visceral','bum_punch'],
                 'mage':['mana_shot','mana_blob','mana_focus','bum_punch']}[cid]
        db.connection.execute('''UPDATE personal_profiles SET class_id=?,level=?,progression_level=?,progression_pending_level=0,
            loadout=? WHERE chat_id=0 AND user_id=?''',(cid,level,20 if level>=20 else 5,json.dumps(loadout),actor))
        db._guild_hunter_locked(actor)
        db.connection.execute('UPDATE guild_hunters SET rank=?,peak_rank=?,reputation=?,wins=?,dungeons=? WHERE actor_id=?',
            (rank,rank,35 if rank else 0,9 if rank else 0,2 if rank else 0,actor))
        db._add_francs_locked(CHAT,actor,1500)
        for item in ('bandage','ration','antidote','scout'):
            db.connection.execute('INSERT INTO guild_bag VALUES(?,?,3)',(actor,item))
    db.connection.commit()
    messages={}
    async def send(chat,text,**kwargs):
        ident=len(messages)+100;messages[ident]=dict(text=text,keyboard=kwargs.get('reply_markup'))
        return SimpleNamespace(message_id=ident)
    async def edit(text,**kwargs):messages[kwargs['message_id']]=dict(text=text,keyboard=kwargs.get('reply_markup'))
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))),
        get_user_profile_photos=AsyncMock(return_value=SimpleNamespace(photos=[])),
        send_message=AsyncMock(side_effect=send),edit_message_text=AsyncMock(side_effect=edit))
    publisher=GuildPublisher(db,bot,'GnidoBot')
    app=create_arena_app(db,bot,TOKEN,guild_publisher=publisher)
    app['guild_review_db']=db

    @web.middleware
    async def demo_ally(request,handler):
        # The demo's companion follows the tester's map decisions and makes basic
        # combat choices. Production uses independent real-player votes/actions.
        if request.path.startswith('/api/raid/') and request.method=='GET':
            token=request.path.rsplit('/',1)[-1]
            async with db._lock:
                raw=db.connection.execute('SELECT * FROM arena_raids WHERE token=?',(token,)).fetchone()
                if raw and raw['status']=='active':
                    data=json.loads(raw['data_json']);ally=data['players'].get('20')
                    if data.get('guild_run_id') and ally and not ally.get('withdrawn') and ally['fighter']['hp']>0 and ally['selected'] is None:
                        ally.update(selected='bum_punch',selected_target=next((k for k,v in data['enemies'].items() if v['hp']>0),None))
                        db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?',(json.dumps(data,ensure_ascii=False),token));db.connection.commit()
        response=await handler(request)
        if request.path.startswith('/api/guild/runs/') and request.method=='POST' and response.status==200:
            body=await request.json()
            if body.get('action')=='vote' and request.get(ACTOR)==10:
                ident=request.path.rsplit('/',1)[-1];run=await db.guild_get(ident,10)
                if run['votes'].get('10') and any(p['actor_id']==20 and p['hp']>0 for p in run['members']) and '20' not in run['votes']:
                    run=await db.guild_action(ident,20,'vote',run['revision'],choice=body['choice'])
                    return web.json_response(run)
        return response
    app.middlewares.append(demo_ally)

    async def preview(request):
        actor=int(request.query.get('actor','10'))
        if actor not in (10,20,30):raise web.HTTPBadRequest()
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+
            ',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def demo_map(request):
        # Explicitly reset only this temporary demo's runs/quotas so the reviewer
        # can exercise the map repeatedly. No such route exists in production.
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE guild_runs SET status='cancelled' WHERE status IN ('lobby','active')")
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
                db.connection.execute('DELETE FROM arena_qte_flows');db.connection.execute('DELETE FROM guild_daily')
        run=await db.guild_create(CHAT,10,'c_dungeon','demo-'+secrets.token_hex(8))
        run=await db.guild_action(run['id'],20,'join',run['revision'])
        run=await db.guild_action(run['id'],10,'start',run['revision'])
        async with db._lock:
            with db.connection:
                row=db._guild_row_locked(run['id'])
                # A reproducible demonstration of an event vs a combat branch.
                for n in row['data']['nodes']:
                    if n['id']=='a1':n.update(kind='event',event='shrine')
                    elif n['id']=='b1':n.update(kind='battle')
                db._guild_save_locked(row)
        raise web.HTTPFound('/guild-preview?'+urlencode(dict(actor=10,tgWebAppStartParam='guildrun_'+run['id'])))

    async def review(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Гильдия охотников · демо</title>
<style>body{margin:0;background:#0b1418;color:#d7dfd5;font:12px system-ui}header{padding:10px 14px;display:flex;flex-wrap:wrap;gap:13px;align-items:center;border-bottom:1px solid #455e4a}a{color:#dec18e;text-decoration:none}header small{color:#8fa492}iframe{display:block;border:0;width:100%;height:calc(100dvh - 82px);margin:auto}button{background:#1b2b28;color:#dbd6bc;border:1px solid #4b5e4c;border-radius:5px;padding:5px 9px}</style>
<header><b>ДЕМО · временная база</b><a target="guild" href="/guild-preview?actor=10&amp;tgWebAppStartParam=guild_-100">Охотник C</a><a target="guild" href="/guild-preview?actor=30&amp;tgWebAppStartParam=guild_-100">Новичок F</a><a target="guild" href="/guild-preview?actor=20&amp;tgWebAppStartParam=guild_-100">Напарник D</a><a target="guild" href="/guild-demo-map">Новое подземелье · отряд</a><a target="guild" href="/guild-sprites">Спрайты · 14 монстров</a><button onclick="document.querySelector('iframe').style.width='390px'">390px</button><button onclick="document.querySelector('iframe').style.width='100%'">ПК</button><small>Франки и награды тестовые. Лис голосует за твой маршрут и автоматически выбирает базовую атаку в бою.</small></header>
<iframe name="guild" title="Гильдия охотников — тест" src="/guild-preview?actor=10&amp;tgWebAppStartParam=guild_-100"></iframe></html>''',content_type='text/html')

    app.router.add_get('/guild-review',review)
    app.router.add_get('/guild-preview',preview)
    app.router.add_get('/guild-demo-map',demo_map)
    async def sprites(request):
        cards=''.join('<article><a href="'+art(key)+'" target="_blank" rel="noopener" aria-label="Открыть спрайт: '+escape(m['name'])+'"><img src="'+art(key)+'" alt="'+escape(m['name'])+'" loading="lazy"></a><small>РАНГ '+m['rank']+' · '+escape(m['role'])+'</small><h2>'+escape(m['name'])+'</h2></article>' for key,m in MONSTERS.items())
        html=(ROOT/'guild-sprites-review.html').read_text(encoding='utf-8').replace('<!-- MONSTER_CARDS -->',cards)
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/guild-sprites',sprites)
    async def chat_preview(request):
        cards=''.join('<article>'+m['text'].replace('\n','<br>')+'<p>'+(' · '.join(escape(b.text) for row in m['keyboard'].inline_keyboard for b in row) if m['keyboard'] else '')+'</p></article>' for m in messages.values())
        return web.Response(text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:15px/1.6 system-ui;background:#0c1419;color:#dce1d6;margin:24px}article{padding:24px;background:#192a2d;border:1px solid #50654f;border-radius:16px;max-width:650px;margin:18px 0}p{color:#c3ad80}</style><h1>Приглашения · тестовый чат</h1><p>Это локальная имитация. Сообщения в настоящий Telegram не отправляются.</p>'+ (cards or '<p>Прими заказ и нажми «Позвать в чат» в лобби.</p>')+'</html>',content_type='text/html')
    app.router.add_get('/guild-chat-demo',chat_preview)
    async def cleanup(_):await db.close();folder.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8131)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
