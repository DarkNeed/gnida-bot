"""Local-only Nazarick v2 gallery and playable checkpoint/phase review. No polling."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from preview_chaplain import application as base_application
from arena_nazarick_dungeon_rules import ROOMS,GUARDIANS,MOVES,sprite,background
from arena_unified_store import catalog as combat_catalog, drive
import arena_unified_queue as queue

async def application():
    app=await base_application();db=app['chaplain_review_db']
    app.middlewares[:]=[m for m in app.middlewares if m.__name__!='review_helpers']
    @web.middleware
    async def demo_allies(request,handler):
        if request.path.startswith('/api/raid/'):
            async with db._lock:
                with db.connection:
                    row=db.connection.execute('SELECT * FROM arena_raids WHERE token=?',(request.path.split('/')[-1],)).fetchone()
                    if row and row['status']=='active':
                        row=dict(row);data=json.loads(row['data_json']);changed=False
                        if queue.enabled(data) and not data.get('_queue_wait'):
                            from arena_npc_ai import choose_skill
                            for key in list(queue.ready(data)):
                                if key=='10':continue
                                target=next((k for k in queue._enemy_ids(data) if queue.roster(data)[k]['hp']>0),None)
                                if target is None:continue
                                sid=choose_skill(queue.pair(queue.roster(data)[key],queue.roster(data)[target]),'a',combat_catalog(db))
                                queue.submit(data,key,sid,target,combat_catalog(db),ident=queue.choice(data,key));changed=True
                            if changed:drive(db,'raid',row,data)
        return await handler(request)
    app.middlewares.append(demo_allies)
    await db.upsert_chat(1,'Назарик · демо подземелья')

    async def start(request):
        idx=max(0,min(len(ROOMS)-1,int(request.query.get('room','0'))));party=request.query.get('party','1')=='3'
        phase=max(1,min(2,int(request.query.get('phase','1'))));move=max(0,min(4,int(request.query.get('move','0'))))
        mode=request.query.get('mode','menu');who=request.query.get('who')
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute("UPDATE nazarick_runs SET status='closed' WHERE status IN ('lobby','ready','battle','failed')")
                db.connection.execute('DELETE FROM arena_qte_flows')
                for actor in(10,20,30):
                    db._nzd_progress_locked(actor);db.connection.execute('UPDATE nazarick_progress SET checkpoint=? WHERE actor=?',(idx,actor))
        await db.arena_combat_settings(10,enabled=True,defense_mode='block' if request.query.get('defense')=='block' else 'dodge')
        for actor in (20,30):await db.arena_combat_settings(actor,enabled=False)
        run=await db.nazarick_create(1,10)
        if party:
            for actor in(20,30):run=await db.nazarick_action(run['id'],actor,'join',run['revision'])
        if mode=='menu':raise web.HTTPFound('/preview?tgWebAppStartParam=nzrun_'+run['id'])
        run=await db.nazarick_action(run['id'],10,'treasury' if mode=='treasury' else 'start',run['revision'])
        if not run['battle']:raise web.HTTPFound('/preview?tgWebAppStartParam=nzrun_'+run['id'])
        async with db._lock:
            with db.connection:
                raid=db._raid_row_locked(run['battle']);data=json.loads(raid['data_json'])
                if mode in ('victory','defeat','rewards'):
                    data.update(finished=True,won=mode!='defeat');db._raid_finish_locked(raid,data)
                else:
                    data['round']=move+1
                    if data.get('boss_id')=='nazarick':
                        from arena_nazarick import load_stage,set_intent
                        data['nazarick']['phase']=phase;load_stage(data);set_intent(data)
                    else:
                        from arena_encounters import set_intents
                        for f in data['enemies'].values():
                            w=f.get('nzd_guardian')
                            if w:
                                f.update(nzd_phase=phase,loadout=[f'nz_{w}_p{phase}_{i}' for i in range(len(MOVES[w][phase-1]))])
                                if w=='victim' and phase==2:
                                    f.update(nzd_ritual=True,hp=1,name='Защитный ритуал Виктима',loadout=['nz_victim_p2_4'])
                                    f['stats']['max_hp']=1
                                if 'energy' in request.query:f['resource']=max(0,min(200,int(request.query['energy'])))
                                if mode=='pattern':f['nzd_preview_move']=move
                                if mode=='pattern' and who in GUARDIANS and w!=who:f['hp']=0
                        set_intents(data)
                    data.pop('_unified',None);data.pop('_queue_wait',None);data.pop('_cast_queue',None)
                    db._raid_save_locked(raid,data)
                    if mode=='pattern':
                        for _ in range(8):
                            if data.get('_queue_wait') or data.get('finished'):break
                            target=next((k for k in queue._enemy_ids(data) if queue.roster(data)[k]['hp']>0),None)
                            if target is None:break
                            for key in list(queue.ready(data)):queue.submit(data,key,'defend',target,combat_catalog(db),ident=queue.choice(data,key))
                            drive(db,'raid',raid,data)
                            if any(f.get('own_turns',0)>0 for k,f in queue.roster(data).items() if k in queue._enemy_ids(data)):break
        if mode in ('victory','defeat','rewards'):raise web.HTTPFound('/preview?tgWebAppStartParam=nzrun_'+run['id'])
        raise web.HTTPFound('/preview?tgWebAppStartParam=r_'+run['battle'])

    async def review(request):
        return web.FileResponse(Path(__file__).with_name('nazarick_dungeon_review.html'),headers={'Cache-Control':'no-store'})

    async def catalog(request):
        return web.json_response(dict(rooms=ROOMS,guardians=[dict(id=w,name=info[0],moves=MOVES[w],sprite=sprite(w)) for w,info in GUARDIANS.items()]))

    async def gallery(request):
        from html import escape
        body='<header><p>НАЗАРИК · НОВЫЕ ОБРАЗЫ</p><h1>Стражи и этажи</h1><a href="/nazarick-dungeon-review">← К проверке подземелья</a></header><main class="sprites">'
        for who,info in GUARDIANS.items():
            body+='<article><img src="'+sprite(who)+'"><h2>'+escape(info[0])+'</h2><p>'+escape(info[1])+'</p></article>'
        body+='<article><img src="'+sprite('sebas',2)+'"><h2>Себас · драконья форма</h2><p>Игровая интерпретация раскрытия сущности.</p></article></main><main class="backgrounds">'
        for f,title,bg,rooms in __import__('arena_nazarick_dungeon_rules').FLOORS:
            room=next(r for r in ROOMS if r['floor']==f)
            body+='<article><img src="'+background(room)+'"><h2>'+str(f)+' · '+escape(title)+'</h2></article>'
        return web.Response(text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Назарик · новые изображения</title><style>body{margin:0;background:#0b1020;color:#e9dfc9;font:14px system-ui}header{max-width:1200px;margin:auto;padding:35px 25px}h1{font:44px Georgia}a{color:#d4be8e}main{max-width:1200px;margin:0 auto 40px;display:grid;gap:18px;padding:0 20px}.sprites{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.sprites img{height:310px;width:100%;object-fit:contain}.backgrounds{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}.backgrounds img{width:100%;border-radius:12px}article{background:#182136;border:1px solid #313a53;padding:18px;border-radius:15px}h2{font-size:18px}p{color:#adbad0}</style>'+body+'</main></html>',content_type='text/html')

    app.router.add_get('/nazarick-dungeon-review',review)
    app.router.add_get('/nzd-demo',start)
    app.router.add_get('/nzd-catalog',catalog)
    app.router.add_get('/nzd-gallery',gallery)
    async def music(request):
        html=Path(__file__).with_name('nazarick_dungeon_music.html').read_text(encoding='utf-8')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/nzd-music',music)
    return app

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8140)
    web.run_app(application(),host='127.0.0.1',port=p.parse_args().port)
