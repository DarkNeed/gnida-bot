"""Local settlement review. Only disposable SQLite, mock Telegram and demo clock."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
import time
from datetime import datetime,timedelta
from urllib.parse import urlencode
from unittest.mock import patch
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_guild import application as guild_application, TOKEN, CHAT
from arena_assets import render_arena_index
from arena_web import ROOT
from arena_kingdom_rules import HOUR, DAY, INCIDENTS
from arena_kingdom_war import initialize as military_initialize, new_unit
from arena_kingdom_time import MSK
import arena_kingdom_finance as finance


async def application():
    app=await guild_application();db=app['guild_review_db'];clock=[int(time.time())]
    app['kingdom_review_clock']=clock
    mock=patch('arena_kingdom.kingdom_now',side_effect=lambda:clock[0]);mock.start()
    async def stop(_):mock.stop()
    app.on_cleanup.append(stop)
    await db.upsert_chat(-200,'Южные пределы · другая карта')
    for actor in (10,20,30,40):
        if actor==40:
            await db.upsert_user(CHAT,40,'newlord','Новый правитель');db._arena_profile_locked(CHAT,40,True);db._guild_hunter_locked(40)
            db.connection.execute("UPDATE personal_profiles SET class_id='mage',level=20,progression_level=20,progression_pending_level=0,loadout='[\"mana_shot\",\"mana_blob\",\"mana_focus\"]' WHERE user_id=40 AND chat_id=0")
            db.connection.execute('UPDATE guild_hunters SET rank=3,peak_rank=3 WHERE actor_id=40')
        await db.upsert_user(-200,actor,str(actor),'Правитель '+str(actor))
        db._add_francs_locked(CHAT,actor,500000 if actor!=30 else 1000)
        db._add_francs_locked(-200,actor,200000)
    db.connection.execute('UPDATE guild_hunters SET rank=5,peak_rank=5 WHERE actor_id=20');db.connection.commit()
    for actor,q,name in ((10,6,'Чёрный тракт'),(20,11,'Воронья гавань')):
        await db.kingdom_action(CHAT,actor,dict(action='found',q=q,r=5,name=name,confirm=True,nonce=secrets.token_hex(16)))
        raw=db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=? AND owner=?',(CHAT,actor)).fetchone()
        row=db._kingdom_row_locked(raw['id']);d=row['data']
        d['resources'].update(food=650,wood=640,stone=590)
        d['buildings'].update(sawmill=1,quarry=1,warehouse=1)
        d.update(founded_at=clock[0]-(6 if actor==10 else 21)*DAY,prestige=3 if actor==10 else 12)
        m=military_initialize(d)
        if actor==10:
            row['description']='Там, где кончается дорога, начинается твоя история.'
            d['buildings']['barracks']=1
            d['construction']=dict(building='barracks',level=2,started=clock[0]-2*HOUR,finish=clock[0]+22*HOUR,price=72000,wood=130,stone=160)
            m['units']=[new_unit(k,clock[0],ready=True) for k in ('shields','militia','archers','priests')]
            m['formation']=[u['id'] for u in m['units']]+[None]
            d['event']=dict(id=secrets.token_hex(8),kind='bandits',started=clock[0]-HOUR,deadline=clock[0]+23*HOUR,escrow=0,battle=None,attempted=[])
        else:
            row['description']='Город соседа. Здесь уже знают цену мирной жизни.'
            d.update(stage=2,population=79);d['buildings'].update(hall=2,farm=2,barracks=2)
            d['factions'].update(light=2,velvet=2,grave=2)
            m['units']=[new_unit(k,clock[0],ready=True) for k in ('paladins','shields','archers','priests','agents','agents','skeletons','necromancers')]
            m['formation']=[u['id'] for u in m['units'][:5]]
        db._kingdom_save_locked(row)
    db.connection.commit()

    # A second, entirely disposable world has connected adjoining city lands.
    # It uses production siege gates and the guild preview's mock Telegram bot.
    await db.upsert_chat(-300,'Пограничье · PvP-проверка')
    for actor,q,name in ((10,6,'Северный дозор'),(20,11,'Бархатная корона')):
        await db.upsert_user(-300,actor,str(actor),'Правитель '+str(actor))
        db._add_francs_locked(-300,actor,1000000);db.connection.commit()
        await db.kingdom_action(-300,actor,dict(action='found',q=q,r=5,name=name,confirm=True,nonce=secrets.token_hex(16)))
        raw=db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=-300 AND owner=?',(actor,)).fetchone()
        row=db._kingdom_row_locked(raw['id']);d=row['data']
        row['description']='Соседняя пограничная земля 8:4. Столицу захватить нельзя.'
        d.update(stage=2,founded_at=clock[0]-30*DAY,population=65,next_event=clock[0]+365*DAY)
        d['buildings'].update(hall=2,farm=2,warehouse=2,barracks=2,sawmill=1,quarry=1)
        d['resources'].update(food=1500,wood=900,stone=900);d['factions'].update(light=2,velvet=2,grave=2)
        m=military_initialize(d)
        kinds=('shields','militia','archers') if actor==10 else ('paladins','shields','archers','priests','agents')
        m['units']=[new_unit(k,clock[0],ready=True) for k in kinds]
        m['formation']=[u['id'] for u in m['units']]+[None]*(5-len(kinds))
        db._kingdom_save_locked(row)
        for q,r in (((7,4),(8,4)) if actor==10 else ((11,4),(10,4),(9,4))):
            db.connection.execute('INSERT INTO kingdom_tiles VALUES(?,?,?,?)',(-300,q,r,row['id']))
        db.connection.commit()

    # Only a disposable fixture gets these grants; real towns start at zero.
    await db.upsert_chat(-400,'Монетный берег · бюджет и налоги')
    for actor in (10,20,30,40):
        await db.upsert_user(-400,actor,str(actor),'Правитель '+str(actor));db._add_francs_locked(-400,actor,200000)
    db.connection.commit()
    for actor,q,name in ((10,6,'Монетный берег'),(20,11,'Город поборов')):
        await db.kingdom_action(-400,actor,dict(action='found',q=q,r=5,name=name,confirm=True,nonce=secrets.token_hex(16)))
        ident=db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=-400 AND owner=?',(actor,)).fetchone()['id']
        row=db._kingdom_row_locked(ident);d=row['data'];d.update(stage=2,population=100,order=80 if actor==10 else 35,
            founded_at=clock[0]-30*DAY,next_event=clock[0]+365*DAY,event=None)
        d['buildings'].update(hall=3,farm=3,sawmill=2,quarry=2,barracks=2,warehouse=2)
        d['resources'].update(food=1500,wood=800,stone=800)
        finance.credit(db,row,5000);db._kingdom_save_locked(row);db.connection.commit()
        await db.kingdom_action(-400,actor,dict(action='tax_activate',town=ident,revision=row['revision'],confirm=True,nonce=secrets.token_hex(16)))
        if actor==20:
            row=db._kingdom_row_locked(ident);row['data']['finance']['rate']='extortion';db._kingdom_save_locked(row);db.connection.commit()
    for raw in db.connection.execute('SELECT id FROM kingdom_towns WHERE chat<>-400').fetchall():
        row=db._kingdom_row_locked(raw['id']);finance.credit(db,row,300000);db._kingdom_save_locked(row)
    db.connection.commit()

    async def preview(request):
        actor=int(request.query.get('actor','10'))
        if actor not in (10,20,30,40):raise web.HTTPBadRequest()
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def demo_action(request):
        body=await request.json()
        if body.get('action')=='time':
            hours=body.get('hours')
            if hours not in (.5,6,18,25,168,336):raise web.HTTPBadRequest()
            clock[0]+=int(hours*HOUR)
        elif body.get('action')=='daytime':
            phases=dict(dawn=6,day=12,dusk=19,night=23);phase=body.get('phase')
            if phase not in phases:raise web.HTTPBadRequest()
            local=datetime.fromtimestamp(clock[0],MSK);target=local.replace(hour=phases[phase],minute=0,second=0,microsecond=0)
            if target<=local:target+=timedelta(days=1)
            clock[0]=int(target.timestamp())
        elif body.get('action')=='incident':
            kind=body.get('kind');actor=body.get('actor',10);chat=body.get('chat',CHAT)
            if kind not in INCIDENTS or actor not in (10,20,30,40) or chat not in (CHAT,-200,-300,-400):raise web.HTTPBadRequest()
            async with db._lock:
                with db.connection:
                    found=db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=? AND owner=?',(chat,actor)).fetchone()
                    if not found:return web.json_response(dict(error='Сначала основай поселение.'),status=400)
                    row=db._kingdom_row_locked(found['id'])
                    if row['data']['event']:
                        if row['data']['event'].get('battle'):return web.json_response(dict(error='Сначала закончи вылазку.'),status=400)
                        db._kingdom_resolve_locked(row,'Тестовое событие заменено, резерв возвращён.',success=True)
                    row['data']['event']=dict(id=secrets.token_hex(8),kind=kind,started=clock[0],deadline=clock[0]+24*HOUR,escrow=0,battle=None,attempted=[])
                    db._kingdom_save_locked(row)
        else:raise web.HTTPBadRequest()
        return web.json_response(dict(ok=True))

    async def review(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Королевства · проверка</title>
<style>*{box-sizing:border-box}body{margin:0;background:#0b1520;color:#d7e3e6;font:12px system-ui;display:flex;flex-direction:column;height:100dvh;overflow:hidden}header{padding:9px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #354651;flex-shrink:0}b{color:#d9ba83;margin-right:8px}select,button{background:#192a38;color:#dce7e9;border:1px solid #435966;border-radius:5px;padding:7px;font:inherit}small{color:#91a7b1}iframe{display:block;border:0;width:100%;flex:1;min-height:0;margin:auto}#notice{min-height:22px;padding:4px 14px;color:#d7bc91;flex-shrink:0}</style>
<header><b>ДЕМО · ВРЕМЕННАЯ БАЗА</b><select id="scenario" aria-label="Сценарий"><option value="-400" selected>Бюджет и налоги</option><option value="-100">Развитие и фракции</option><option value="-300">Соседние города · PvP</option></select><select id="actor" aria-label="Игрок демо"><option value="10">Игрок 10 · защитник</option><option value="20">Игрок 20 · нападающий</option><option value="40">Основать с нуля</option><option value="30">Новичок · без допуска</option></select><button data-hours="6">+6 часов</button><button data-hours="18">+18 часов</button><button data-hours="25">+25 часов</button><button data-hours="168">+7 дней</button><button data-kind="bandits">Свора бомжей</button><button data-kind="velvet_coup">Бархатный двор</button><button data-kind="dead_shift">Профсоюз</button><button data-kind="night_diplomacy">Дипломатия 18+</button><button data-kind="holy_audit">Орден</button><button data-phase="dawn">Рассвет</button><button data-phase="day">День</button><button data-phase="dusk">Закат</button><button data-phase="night">Ночь</button><button id="mobile">390px</button><button id="desktop">ПК</button><small>Демо: время идёт только вперёд. День/ночь переводят часы к следующему выбранному периоду; стройки и осады тоже продвигаются.</small></header><div id="notice">Бюджет: игрок 10 — мирный город, игрок 20 — поборы при низком порядке. Открой «Бюджет» и нажми +25 часов. Кошелёк и бюджет раздельные. Демо-гранты не выдаются в реальной игре. PvP — отдельный сценарий.</div>
<iframe title="Королевства — локальное демо" src="/kingdom-preview?actor=10&amp;tgWebAppStartParam=kingdom_-400"></iframe>
<script>const frame=document.querySelector('iframe'),actor=document.getElementById('actor'),scenario=document.getElementById('scenario');const reload=()=>frame.src='/kingdom-preview?actor='+actor.value+'&tgWebAppStartParam=kingdom_'+scenario.value;actor.onchange=reload;scenario.onchange=reload;document.getElementById('mobile').onclick=()=>frame.style.width='390px';document.getElementById('desktop').onclick=()=>frame.style.width='100%';document.querySelector('header').addEventListener('click',async e=>{const b=e.target.closest('[data-hours],[data-kind],[data-phase]');if(!b)return;b.disabled=true;try{const response=await fetch('/kingdom-demo/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b.dataset.phase?{action:'daytime',phase:b.dataset.phase}:b.dataset.hours?{action:'time',hours:Number(b.dataset.hours)}:{action:'incident',kind:b.dataset.kind,actor:Number(actor.value),chat:Number(scenario.value)})}),data=await response.json();document.getElementById('notice').textContent=data.error||'Тестовые условия обновлены.';if(response.ok)frame.src=frame.src;}finally{b.disabled=false;}});</script></html>''',content_type='text/html')
    app.router.add_get('/kingdom-preview',preview)
    app.router.add_get('/kingdom-review',review)
    app.router.add_post('/kingdom-demo/action',demo_action)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8135)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
