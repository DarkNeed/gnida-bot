"""Loopback-only chest event and battle review on an isolated disposable DB."""
import argparse
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlencode
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_guild import application as guild_application, CHAT
from arena_chest_mimic import SKILLS, prepare
from arena_encounters import set_intents
from arena_engine import BUILTIN_SKILLS
from arena_guild_rules import RANKS
from arena_guild_scenery import assign_background
from arena_raid_engine import BOSS_SKILLS
import arena_unified_queue as queue


async def application():
    app=await guild_application();db=app['guild_review_db']

    async def start(request):
        rank=request.query.get('rank','C')
        if rank not in RANKS:raise web.HTTPBadRequest(text='Неизвестный ранг')
        mode=request.query.get('mode','mimic');party=request.query.get('party')=='1'
        room=request.query.get('room','treasure')
        if room not in ('treasure','battle','elite','boss','event','rest'):raise web.HTTPBadRequest(text='Неизвестная комната')
        defense='block' if request.query.get('defense')=='block' else 'dodge'
        async with db._lock:
            with db.connection:
                # Only this process's temporary DB is touched. Never production.
                db.connection.execute("UPDATE guild_runs SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute('DELETE FROM arena_qte_flows')
                db.connection.execute('UPDATE guild_hunters SET rank=6 WHERE actor_id IN (10,20)')
        for actor in ((10,20) if party else (10,)):
            await db.arena_combat_settings(actor,enabled=True,defense_mode=defense)
        run=await db.guild_create(CHAT,10,rank.lower()+'_dungeon','chest-demo-'+secrets.token_hex(8))
        if party:run=await db.guild_action(run['id'],20,'join',run['revision'])
        run=await db.guild_action(run['id'],10,'start',run['revision'])
        async with db._lock:
            with db.connection:
                row=db._guild_row_locked(run['id'])
                node=next(n for n in row['data']['nodes'] if n['id']=='a1')
                node.update(kind=room,roll=.75 if mode=='treasure' else .25)
                if room=='event':node['event']='well'
                else:node.pop('event',None)
                node.pop('scenery',None);assign_background(row['data']['contract'],node)
                self_players=row['data']['players']
                # Explicit reviewer aid; combat rules and enemy stats stay native.
                if request.query.get('sturdy')=='1':
                    for p in self_players.values():p['fighter']['hp']=p['fighter']['stats']['max_hp']=600
                db._guild_save_locked(row)
        run=await db.guild_get(run['id'],10)
        for actor in ((10,20) if party else (10,)):
            run=await db.guild_action(run['id'],actor,'vote',run['revision'],choice='a1')
        if mode=='battle' and (run.get('pending') or {}).get('event')=='chest':
            for actor in ((10,20) if party else (10,)):
                run=await db.guild_action(run['id'],actor,'vote',run['revision'],choice='open')
        if mode=='battle' and run['battle']:
            if request.query.get('phase')=='2' and room=='treasure':
                async with db._lock:
                    with db.connection:
                        raid=db._raid_row_locked(run['battle']);data=json.loads(raid['data_json'])
                        enemy=data['enemies']['e1'];enemy['hp']=max(1,int(enemy['stats']['max_hp']*.35));prepare(enemy)
                        set_intents(data,BOSS_SKILLS)
                        data.pop('_unified',None);queue.initialize(data,{**BOSS_SKILLS,**BUILTIN_SKILLS})
                        db._raid_save_locked(raid,data)
            target='r_'+run['battle']
        else:target='guildrun_'+run['id']
        raise web.HTTPFound('/guild-preview?'+urlencode(dict(actor=10,tgWebAppStartParam=target)))

    async def review(request):
        html=Path(__file__).with_name('chest_mimic_review.html').read_text(encoding='utf-8')
        catalog=[dict(id=s.skill_id+':'+s.name+':1:physical',name=s.name) for s in SKILLS.values()]
        return web.Response(text=html.replace('__CHEST_SKILLS__',json.dumps(catalog,ensure_ascii=False)),content_type='text/html',headers={'Cache-Control':'no-store'})

    app.router.add_get('/chest-mimic-demo',start)
    app.router.add_get('/chest-mimic-review',review)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8160)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
