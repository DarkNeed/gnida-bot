"""Loopback-only, disposable NPC/upkeep/recovery demo. No Telegram requests."""
import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from urllib.parse import urlencode
from uuid import uuid4
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_web import create_arena_app,ROOT
from arena_assets import render_arena_index
from database import Database
from npc_worker_rules import create,HOUR,PROFESSIONS,SPRITE_ROOT,FEMALE_PROFESSIONS


async def application():
    temp=tempfile.TemporaryDirectory(prefix='gnida-npc-review-');clock=[0];stamp=lambda:int(time.time())+clock[0]
    clock_patch=patch('database.utc_timestamp',side_effect=stamp);clock_patch.start()
    db=Database(Path(temp.name)/'npc.sqlite');await db.connect()
    await db.upsert_chat(-100,'NPC · тестовая контора')
    for user,name in ((10,'Испытатель'),(20,'Сосед-спасатель'),(30,'Третий защитник'),(100,'Работник-игрок'),(101,'Похищенный игрок')):
        await db.upsert_user(-100,user,str(user),name)
    for user in (100,101):await db.force_enslave(-100,user,10)
    await db.credit_francs(-100,10,50000);await db.credit_francs(-100,20,5000)
    await db.enterprise_create(-100,10,'mine');await db.enterprise_create(-100,10,'tavern')
    mine=await db.get_business(-100,10,business_type='mine');tavern=await db.get_business(-100,10,business_type='tavern')
    await db.enterprise_assign(-100,10,100,'leader',mine['id'])
    db._npc_estate_locked(-100,10)
    for profession,gender,rarity,status,site in (('miner','male','rare','work',mine['id']),('skeleton','female','common','rest',None),('diplomat','male','epic','work',tavern['id']),('mechanic','female','uncommon','rest',None)):
        d=create(profession,gender=gender);d['rarity']=rarity;d['appraised']=profession=='miner'
        if profession=='skeleton':d.update(fatigue=86,health=72,loyalty=36,unpaid=25)
        db.connection.execute('INSERT INTO fictional_workers VALUES(?,-100,10,?,?,?, ?,0,?,?)',
            (uuid4().hex,status,site,PROFESSIONS[profession]['price'],json.dumps(d,ensure_ascii=False),stamp(),stamp()))
    db.connection.commit()
    for user,cid,loadout in ((10,'warrior',['armor_split','steel_charge','warrior_execute','bum_punch']),
                              (20,'hunter',['hunter_shot','hunter_cut','hunter_visceral','bum_punch']),
                              (30,'mage',['mana_shot','mana_blob','mana_focus','bum_punch'])):
        db._arena_profile_locked(-100,user,True)
        db.connection.execute('''UPDATE personal_profiles SET class_id=?,level=20,progression_level=20,
            progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?''',(cid,json.dumps(loadout),user))
    db.connection.commit()
    # These two demo allies submit actions automatically. Do not leave the new
    # shared cast queue waiting for minigames in nonexistent helper tabs.
    for helper in (20,30):
        await db.arena_combat_settings(helper,enabled=False)
    token='local-npc-review-only';messages=[]
    async def send(chat,text,**kwargs):
        messages.append(dict(chat=chat,text=text));return SimpleNamespace(message_id=len(messages)+100)
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))),
        send_message=AsyncMock(side_effect=send),get_user_profile_photos=AsyncMock(return_value=SimpleNamespace(photos=[])))
    app=create_arena_app(db,bot,token)
    @web.middleware
    async def auth(request,handler):
        if request.path.startswith('/api/'):
            actor=int(request.query.get('actor',request.cookies.get('npc_actor','10')))
            if actor not in (10,20,30):raise web.HTTPBadRequest()
            data=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
            secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
            data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
            request=request.clone(headers={**request.headers,'X-Telegram-Init-Data':urlencode(data)})
        return await handler(request)
    app.middlewares.insert(0,auth)
    @web.middleware
    async def demo_allies(request,handler):
        if request.path.startswith('/api/raid/') and request.method=='GET':
            key=request.path.rsplit('/',1)[-1]
            async with db._lock:
                raw=db.connection.execute('SELECT * FROM arena_raids WHERE token=?',(key,)).fetchone()
                if raw and raw['status']=='active':
                    d=json.loads(raw['data_json'])
                    if d.get('protection_event'):
                        _,skills=db._fighter_catalog_locked()
                        for uid in ('20','30'):
                            p=d['players'].get(uid)
                            if p and not p.get('withdrawn') and p['fighter']['hp']>0 and p['selected'] is None:
                                f=p['fighter'];sid=next((s for s in f['loadout'] if s in skills and skills[s].cost<=f['resource'] and not f['cooldowns'].get(s)), 'bum_punch')
                                p.update(selected=sid,selected_target=next((k for k,v in d['enemies'].items() if v['hp']>0),None))
                        db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?',(json.dumps(d,ensure_ascii=False),key));db.connection.commit()
        return await handler(request)
    app.middlewares.append(demo_allies)
    async def review(request):
        return web.Response(text='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Предприятия · NPC и крыша · демо</title><base href="/protection-preview"><link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/holdings.css"><link rel="stylesheet" href="/static/npc-workers.css"><style>.demo-tools{padding:12px;max-width:1100px;margin:auto;font:12px system-ui;color:#b6c6dd;display:flex;gap:8px;flex-wrap:wrap;align-items:center}.demo-tools button,.demo-tools select{background:#25334a;color:#dbe5f7;border:1px solid #50617c;border-radius:8px;padding:9px;font-size:12px}.demo-tools small{width:100%;color:#93a8c4}</style></head><body><header class="demo-tools"><b>ТОЛЬКО ТЕСТОВАЯ БАЗА</b><a href="/npc-review?protection=1" style="color:#ceb7ec">Крыша и налоги</a><button data-demo-threat="orcs">Орки</button><button data-demo-threat="escape">Заговор</button><button data-demo-threat="strike">Забастовка</button><a href="/protection-defense-demo" style="color:#edc879">Тест боя · 3 орка A</a><a href="/npc-sprites" style="color:#ceb7ec">Спрайты · 12</a><button data-demo-hours="6">＋6 ч</button><button data-demo-hours="25">＋25 ч</button><button data-demo-event="escaped">Побег</button><button data-demo-event="kidnapped">Похищение</button><select id="demo-actor" aria-label="Участник"><option value="10">Владелец</option><option value="20">Помощник</option></select><small>Время перематывается для проверки расходов и дедлайнов. События по кнопке — тестовые; в игре риск проверяется один раз в сутки после предупреждения.</small></header><main id="app"></main><script src="/static/npc-workers.js"></script><script src="/static/holdings.js"></script><script>
      const api=async(url,body)=>{const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(!r.ok)throw Error(j.error||'Ошибка');return j};
      async function load(){await HoldingsApp.open({app:document.querySelector('#app'),api,onArena:()=>{},chat:-100});document.querySelector('[data-h="tab:'+(new URLSearchParams(location.search).has('protection')?'sites':'people')+'"]').click()};load();
      document.querySelector('#demo-actor').value=document.cookie.includes('npc_actor=20')?'20':'10';
      document.querySelector('#demo-actor').onchange=e=>{document.cookie='npc_actor='+e.target.value+'; SameSite=Lax';location.reload()};
      document.querySelectorAll('[data-demo-hours]').forEach(b=>b.onclick=async()=>{await api('/demo/time',{hours:Number(b.dataset.demoHours)});await load()});
      document.querySelectorAll('[data-demo-event]').forEach(b=>b.onclick=async()=>{await api('/demo/event',{kind:b.dataset.demoEvent});await load()});
      document.querySelectorAll('[data-demo-threat]').forEach(b=>b.onclick=async()=>{await api('/demo/protection',{kind:b.dataset.demoThreat});location.href='/npc-review?protection=1'});
      </script></body></html>''',content_type='text/html')
    async def advance(request):
        body=await request.json();hours=body.get('hours')
        if hours not in (6,25):raise web.HTTPBadRequest()
        clock[0]+=hours*HOUR
        with db.connection:
            for owner in (10,20):db._enterprise_settle_owner_locked(-100,owner,stamp());db._workforce_tick_locked(-100,owner)
            db._workforce_roll_locked()
        return web.json_response(dict(ok=True))
    async def incident(request):
        body=await request.json();kind=body.get('kind')
        if kind not in ('escaped','kidnapped'):raise web.HTTPBadRequest()
        worker=db.connection.execute("SELECT * FROM fictional_workers WHERE owner=10 AND status IN ('work','rest') ORDER BY created,id LIMIT 1").fetchone()
        typ='npc';id=worker['id'] if worker else '101';epoch=worker['created'] if worker else stamp()
        name=json.loads(worker['data'])['name'] if worker else 'Похищенный игрок'
        if not worker:
            owned=db.connection.execute('SELECT acquired_at FROM ownership WHERE chat_id=-100 AND owner_id=10 AND slave_id=101').fetchone()
            if not owned:return web.json_response(dict(ok=False))
            epoch=owned[0];typ='human'
        with db.connection:
            db.connection.execute("INSERT INTO workforce_events VALUES(?,-100,10,?,?,?,?,?,'announcing',?,NULL,NULL,NULL,0,?,0)",
                (uuid4().hex,id,typ,epoch,name,kind,stamp(),json.dumps(dict(secret=[0,1,2],history=[],bounty=0))))
        return web.json_response(dict(ok=True))
    async def gallery(request):
        cards=''.join('<article><img src="'+SPRITE_ROOT+profession+'-'+gender+'.png" width="512" height="768" alt="'+(FEMALE_PROFESSIONS[profession] if gender=='female' else info['name'])+'"><h2>'+(FEMALE_PROFESSIONS[profession] if gender=='female' else info['name'])+'</h2><p>'+('Женский' if gender=='female' else 'Мужской')+' образ</p></article>' for gender in ('male','female') for profession,info in PROFESSIONS.items())
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Спрайты NPC · 12 образов</title><style>*{box-sizing:border-box}body{margin:0;background:#0d1727;color:#e0e8f4;font-family:system-ui}main{max-width:1440px;padding:24px;margin:auto}a{color:#d1b8f2}h1{font-size:28px}header p{color:#aabbd2;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}article{border:1px solid #344761;background:#19283e;border-radius:14px;overflow:hidden;text-align:center;padding:10px}img{display:block;width:100%;height:280px;object-fit:contain}h2{font-size:14px;min-height:38px;margin:12px 0 0}article p{font-size:12px;color:#aabbd2;margin:6px}@media(max-width:950px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:500px){main{padding:14px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}img{height:220px}h1{font-size:23px}}</style><main><header><a href="/npc-review">← Вернуться к рабам</a><h1>NPC · 12 образов</h1><p>Люди, гоблины и скелеты. По два образа для каждой профессии. Внешность закрепляется при появлении NPC и не зависит от редкости. Это отдельная страница проверки рисунков, не новая вкладка в игровом меню.</p></header><section class="grid">'''+cards+'</section></main></html>',content_type='text/html')
    app.router.add_get('/npc-sprites',gallery)
    async def protection_demo(request):
        kind=(await request.json()).get('kind')
        if kind not in ('orcs','strike','escape'):raise web.HTTPBadRequest()
        # Reset explicit, disposable test incidents only. Never exposed by the app.
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute("UPDATE enterprise_threats SET status='cancelled' WHERE status='open'")
                db.connection.execute('DELETE FROM enterprise_outages')
                db.connection.execute('INSERT OR REPLACE INTO enterprise_protection VALUES(-100,10,0,?,?,1)',(stamp(),stamp()+2*24*HOUR))
                db._protection_event_locked(-100,10,kind)
        return web.json_response(dict(ok=True))
    async def defense_demo(request):
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute("UPDATE enterprise_threats SET status='cancelled' WHERE status='open'")
                ident=db._protection_event_locked(-100,10,'orcs')
                event=db.connection.execute('SELECT * FROM enterprise_threats WHERE id=?',(ident,)).fetchone()
                raid=db._protection_lobby_locked(event)
        for user in (10,20,30):await db.arena_raid_setup(raid,user,'join')
        await db.arena_raid_setup(raid,10,'start')
        raise web.HTTPFound('/protection-preview?tgWebAppStartParam=r_'+raid)
    async def protection_preview(request):
        actor=int(request.query.get('actor',request.cookies.get('npc_actor','10')))
        if actor not in (10,20,30):raise web.HTTPBadRequest()
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/protection-preview',protection_preview)
    app.router.add_get('/protection-defense-demo',defense_demo)
    app.router.add_post('/demo/protection',protection_demo)
    app.router.add_get('/npc-review',review);app.router.add_post('/demo/time',advance);app.router.add_post('/demo/event',incident)
    from handlers.raids import RaidPublisher
    from enterprise_protection_notices import publish_protection
    async def notices():
        publisher=RaidPublisher(db,bot,'GnidoBot')
        while True:
            await publish_protection(db,bot,'GnidoBot',publisher)
            await asyncio.sleep(5)
    async def startup(app):app['npc_review_notices']=asyncio.create_task(notices())
    app.on_startup.append(startup)
    async def cleanup(app):
        app['npc_review_notices'].cancel();await asyncio.gather(app['npc_review_notices'],return_exceptions=True)
        await db.close();clock_patch.stop();temp.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8139);args=parser.parse_args()
    web.run_app(application(),host='127.0.0.1',port=args.port)
