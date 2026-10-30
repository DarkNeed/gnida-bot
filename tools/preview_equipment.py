"""Equipment review on a new disposable guild DB. Never reads .env or polls Telegram."""
import argparse
import json
import secrets
import sys
from pathlib import Path
from aiohttp import web
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_guild import application as guild_application,CHAT
from arena_equipment import CATALOG
from arena_raid_engine import finish_if_needed
from arena_web import ACTOR


async def application():
    app=await guild_application();db=app['guild_review_db']
    with db.connection:
        for actor in (10,20):
            for rank in ('F','D','C','S'):db._gear_material_locked(actor,rank,60)
        for key,rank,rarity in (
            ('fang','C','epic'),('golem','C','epic'),('heart','C','rare'),('eye','C','legendary'),
            ('brick','F','common'),('shaman','C','rare'),('helmet','D','uncommon'),('mantle','C','epic'),
            ('staff','C','epic'),('flask','C','epic'),('ledger','C','legendary'),('candle','C','epic'),
            ('blood','C','epic'),('grave','S','legendary')):
            item=db._gear_grant_locked(10,key,rank,rarity)
            if key in ('fang','golem','heart'):
                db.connection.execute('INSERT INTO gear_loadouts VALUES(?,1,?,?)',(10,CATALOG[key]['slot'],item['id']))
        db.connection.execute('INSERT OR IGNORE INTO arena_character_grants VALUES(10,1980056841,0)')
    async def review(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Экипировка · проверка</title><style>body{margin:0;background:#0c1324;color:#e5edfc;font:12px system-ui;height:100dvh;display:flex;flex-direction:column}header{padding:10px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #354561}a{color:#e0c28c;text-decoration:none}button{background:#22324e;color:#dce8fa;border:1px solid #4e6488;border-radius:5px;padding:6px 10px;cursor:pointer}iframe{border:0;display:block;width:100%;flex:1;min-height:0;margin:auto}</style>
<header><b>ДЕМО · временная база</b><a target="equipment" href="/guild-preview?actor=10&amp;tgWebAppStartParam=equipment_-100">Снаряжение</a><a target="equipment" href="/guild-demo-map">Подземелье · пройти самому</a><a target="equipment" href="/guild-preview?actor=30&amp;tgWebAppStartParam=equipment_-100">Пустой склад новичка</a><button id="loot">Завершить тестовый данж → дроп</button><button onclick="document.querySelector('iframe').style.width='390px'">390px</button><button onclick="document.querySelector('iframe').style.width='100%'">ПК</button><span id="status">Предметы и материалы тестовые. Telegram не используется.</span></header>
<iframe name="equipment" title="Снаряжение — тест" src="/guild-preview?actor=10&amp;tgWebAppStartParam=equipment_-100"></iframe>
<script>document.getElementById('loot').onclick=async function(){this.disabled=true;try{const r=await fetch('/equipment-demo/complete',{method:'POST'});const d=await r.json();if(!r.ok)throw Error(d.error||'Ошибка демо');document.querySelector('iframe').src=d.url;document.getElementById('status').textContent='Данж завершён. Награда выдана настоящим обработчиком гильдии.';}catch(e){document.getElementById('status').textContent=e.message;}finally{this.disabled=false;}};</script></html>''',content_type='text/html',headers={'Cache-Control':'no-store'})
    async def complete(request):
        # Demo-only fast-forward. No endpoint or client flag in production app.
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE guild_runs SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute('DELETE FROM guild_daily');db.connection.execute('DELETE FROM guild_reward_days');db.connection.execute('DELETE FROM arena_qte_flows')
        run=await db.guild_create(CHAT,10,'c_dungeon','equipment-demo-'+secrets.token_hex(10))
        run=await db.guild_action(run['id'],20,'join',run['revision'])
        run=await db.guild_action(run['id'],10,'start',run['revision'])
        async with db._lock:
            with db.connection:
                row=db._guild_row_locked(run['id'])
                for n in row['data']['nodes']:
                    if n['id'] in ('a1','a2','a3','a4'):n['cleared']=True
                db._guild_enter_locked(row,'boss');db._guild_save_locked(row)
                raid=db._raid_row_locked(row['data']['battle']);battle=json.loads(raid['data_json'])
                for enemy in battle['enemies'].values():enemy['hp']=0
                if finish_if_needed(battle):db._raid_finish_locked(raid,battle)
        return web.json_response(dict(url='/guild-preview?actor=10&tgWebAppStartParam=guildrun_'+run['id']))
    app.router.add_get('/equipment-review',review)
    app.router.add_post('/equipment-demo/complete',complete)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8132)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
