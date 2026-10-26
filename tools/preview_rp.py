"""Loopback-only RP constructors and mixed encounter; disposable DB, no Telegram writes."""
import argparse
import hashlib
import hmac
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_web import create_arena_app, ROOT
from database import Database

TOKEN='rp-local-review-not-production'
CHAT=-100


async def application():
    folder=tempfile.TemporaryDirectory(prefix='gnida-rp-review-')
    db=Database(Path(folder.name)/'rp.sqlite3');await db.connect()
    await db.upsert_chat(CHAT,'Таверна потерянных историй · демо')
    for actor,name in ((10,'Мастер'),(20,'Испытатель'),(30,'Обычный персонаж')):
        await db.upsert_user(CHAT,actor,str(actor),name)
    db._arena_profile_locked(CHAT,30,True)
    db.connection.execute("UPDATE personal_profiles SET class_id='warrior',level=15,progression_level=10,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=30",
                          (json.dumps(['armor_split','steel_charge','counter_lunge','bum_punch']),))
    db.connection.commit()
    heroes={}
    for actor in (10,20):
        heroes[actor]=await db.arena_rp_save(actor,'character',dict(name='Охотник чужих историй',
            description='Любые приёмы. Настоящая прогрессия не меняется.',class_id='hunter',level=20,
            archclass_id='hunter_moon',archclass_stage=20,defense_mode='block',
            skills=['hunter_shot','hunter_visceral','arch_hunter_moon','mana_shot','armor_split','chaplain_p3_1','lei_perfected_flurry','bum_punch'],
            passives=['steady_hand','stone_skin','inherent:hunter:0','inherent:hunter:1']))
    mobs=[]
    for name,cid,level,skills,hp,ai in (
        ('Хранитель забытого порога','warrior',12,['armor_split','steel_charge','bum_punch'],320,'sequence'),
        ('Эхо последней редакции','mage',10,['chaplain_p3_1','mana_shot','mana_barrier'],230,'priority')):
        mobs.append(await db.arena_rp_save(10,'mob',dict(name=name,description='Противник мастера. Шаблон можно редактировать.',
            class_id=cid,level=level,skills=skills,passives=['stone_skin'],stats=dict(max_hp=hp),ai=ai)))
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
    app=create_arena_app(db,bot,TOKEN)

    @web.middleware
    async def ally_turn(request,handler):
        if request.path.startswith('/api/raid/'):
            token=request.path.rsplit('/',1)[-1]
            async with db._lock:
                raw=db.connection.execute('SELECT * FROM arena_raids WHERE token=?',(token,)).fetchone()
                if raw and raw['status']=='active':
                    data=json.loads(raw['data_json']);ally=data['players'].get('30')
                    if ally and ally['selected'] is None and not ally.get('withdrawn'):
                        target=next((k for k,v in data['enemies'].items() if v['hp']>0),None)
                        ally.update(selected='bum_punch',selected_target=target)
                        db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?',(json.dumps(data),token));db.connection.commit()
        return await handler(request)
    app.middlewares.append(ally_turn)

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

    async def battle(request):
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
                db.connection.execute("DELETE FROM arena_qte_flows WHERE scope='raid'")
        row=await db.arena_rp_encounter_create(CHAT,10,[dict(kind='mob',id=m['id']) for m in mobs],secrets.token_hex(16))
        await db.arena_raid_setup(row['token'],20,'join',rp_template=heroes[20]['id'])
        await db.arena_raid_setup(row['token'],30,'join')
        await db.arena_raid_setup(row['token'],10,'start')
        raise web.HTTPFound('/rp-preview?'+urlencode(dict(actor=10 if request.query.get('master')=='1' else 20,tgWebAppStartParam='r_'+row['token'])))

    async def index(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RP-режим · проверка</title>
<style>body{margin:0;background:#0d1423;color:#dac9ee;font:14px system-ui}header{display:flex;flex-wrap:wrap;gap:12px;padding:12px;border-bottom:1px solid #3b3450}a{color:#dac9ee}iframe{display:block;width:100%;height:calc(100dvh - 84px);border:0;margin:auto}button{background:#302640;border:1px solid #74608c;color:#e5dbf0;border-radius:6px;padding:6px}</style>
<header><b>RP · временная база, без Telegram и наград</b><a target="rp" href="/rp-preview?actor=10&amp;tgWebAppStartParam=rp_-100">Меню мастера</a><a target="rp" href="/rp-preview?actor=20&amp;tgWebAppStartParam=rp_-100">Меню игрока</a><a target="rp" href="/rp-demo-battle">Смешанный бой · играть</a><a target="rp" href="/rp-demo-battle?master=1">Бой · наблюдать</a><button onclick="document.querySelector('iframe').style.width='390px'">390px</button><button onclick="document.querySelector('iframe').style.width='100%'">ПК</button></header><iframe title="Демо RP-режима" name="rp" src="/rp-preview?actor=10&amp;tgWebAppStartParam=rp_-100"></iframe></html>''',content_type='text/html')
    app.router.add_get('/rp-review',index)
    app.router.add_get('/rp-preview',preview)
    app.router.add_get('/rp-demo-battle',battle)
    async def cleanup(_):await db.close();folder.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8127)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
