"""Local-only five-boss review. Disposable DB; no real Telegram or polling."""
import argparse
import json
from pathlib import Path
import sys
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from preview_chaplain import application as base_application
from arena_nazarick import ORDER,load_stage,set_intent,summon

async def application():
    app=await base_application()
    db=app['chaplain_review_db']

    async def start(request):
        stage=max(0,min(4,int(request.query.get('stage','0'))))
        phase=max(1,min(2,int(request.query.get('phase','1'))))
        move=max(0,min(2,int(request.query.get('move','0'))))
        async with db._lock:
            db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
            db.connection.execute('DELETE FROM arena_qte_flows');db.connection.commit()
        await db.arena_combat_settings(10,enabled=True,defense_mode='block' if request.query.get('defense')=='block' else 'dodge')
        row=await db.arena_raid_create(1,10,boss_id='nazarick',silent=True)
        if request.query.get('party','3')=='3':
            for actor in(20,30):await db.arena_raid_setup(row['token'],actor,'join')
        row=await db.arena_raid_setup(row['token'],10,'start')
        data=json.loads(row['data_json'])
        data['nazarick'].update(stage=stage,phase=phase)
        load_stage(data)
        data['round']=move+1
        if request.query.get('summons')=='1' and stage in(1,4):
            data['nazarick']['next_summon']=0;summon(data)
        if phase==2:
            data['boss']['hp']=round(data['boss']['stats']['max_hp']*.5)
        mode=request.query.get('mode')
        if mode=='copy-mana' and stage==3 and phase==2:
            from arena_engine import BUILTIN_SKILLS
            copied=BUILTIN_SKILLS['mana_shot']
            data['nazarick']['copied_skill']=dict(id='mana_shot:copy-demo',base_id='mana_shot',
                name=copied.name,class_id=copied.class_id,strikes=1,damage_type=copied.damage_type,
                tags=list(copied.tags),description='Копия Пандоры: выстрелы с краёв арены, медленнее оригинала.')
        if mode=='transition':data['boss']['hp']=round(data['boss']['stats']['max_hp']*.51)
        if mode=='finish':
            data['nazarick']['phase']=2;data['boss']['hp']=1
            for p in data['players'].values():p['fighter']['hp']=max(1,p['fighter']['stats']['max_hp']//3)
        if mode=='ritual':
            data['nazarick'].update(stage=4,phase=2);load_stage(data)
            data['round']=3;data['nazarick']['ritual']=dict(hp=data['boss']['hp'],threshold=round(data['boss']['hp']*.1),start=2)
        set_intent(data)
        if mode=='blessing':
            from arena_nazarick import offer_blessing
            for p in data['players'].values():p['fighter']['hp']=0
            offer_blessing(data)
            # Demo allies consent automatically; real participants vote themselves.
            offer=data['nazarick']['blessing_offer']
            for key in offer['eligible']:
                if key!='10':offer['votes'][key]=True
        async with db._lock:
            db._raid_save_locked(row,data);db.connection.commit()
        raise web.HTTPFound('/preview?tgWebAppStartParam=r_'+row['token'])

    async def review(request):
        return web.FileResponse(Path(__file__).with_name('nazarick_review.html'),headers={'Cache-Control':'no-store'})
    async def music(request):
        return web.FileResponse(Path(__file__).with_name('nazarick_music.html'),headers={'Cache-Control':'no-store'})
    async def rewards(request):
        from html import escape
        from arena_engine import BUILTIN_PASSIVES
        from arena_relics import RELIC_IDS,TICKET_NAME,TICKET_DESCRIPTION
        body='<h1>Трофеи Назарика</h1><p>За полную награду каждый участник получает одну из четырёх случайных легендарных пассивок (25% каждая) и независимо 70% на билет. Обычный часовой кулдаун наград сохраняется.</p>'
        for key in RELIC_IDS:
            p=BUILTIN_PASSIVES[key]
            body+='<article><h2>'+escape(p.name)+'</h2><p>'+escape(p.effects[0]['description'])+'</p></article>'
        body+='<article><h2>🎟️ '+escape(TICKET_NAME)+'</h2><p>'+escape(TICKET_DESCRIPTION)+'</p></article><p>Благословение убирает только билет, а не пассивку. После единогласного согласия отряд переигрывает текущего босса с первой фазы и входящим уроном −50% до конца похода. Повторного благословения нет.</p><a href="/nazarick-ticket-demo">Проверить билет в инвентаре (временная база)</a>'
        return web.Response(text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#0c1120;color:#e4dcf1;font:16px system-ui;max-width:850px;margin:20px auto;padding:18px}article{background:#18223a;padding:18px;border:1px solid #6f5591;border-radius:14px;margin:14px 0}h2{font-size:20px;color:#dfc48e}a{color:#cbb5ff}</style>'+body+'</html>',content_type='text/html')
    async def ticket(request):
        from arena_relics import TICKET_ID
        async with db._lock:
            db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
            db._arena_add_item_locked(1,10,'class_ticket',TICKET_ID,'legendary')
            db.connection.commit()
        raise web.HTTPFound('/preview?tgWebAppStartParam=menu_1')
    app.router.add_get('/nazarick-demo',start)
    app.router.add_get('/nazarick-review',review)
    app.router.add_get('/nazarick-music',music)
    app.router.add_get('/nazarick-rewards',rewards)
    app.router.add_get('/nazarick-ticket-demo',ticket)
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8129)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
