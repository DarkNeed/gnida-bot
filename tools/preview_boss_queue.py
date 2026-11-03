"""Scripted boss initiative review; disposable data, no production Telegram."""
import argparse
import json
import sys
from pathlib import Path
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preview_chaplain import application as base_application


async def application():
    app = await base_application()
    db = app['chaplain_review_db']

    async def start(request):
        from arena_raid_engine import BOSS_SKILLS
        from arena_nazarick import load_stage, summon, set_intent
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute('DELETE FROM arena_qte_flows')
        boss=request.query.get('boss','nazarick')
        if boss not in ('nazarick','chaplain','kit','whaler','lei_heng','doofenshmirtz'):
            raise web.HTTPBadRequest(text='Неизвестный босс')
        for actor in (10,20,30):
            await db.arena_combat_settings(actor, enabled=actor==10,
                defense_mode='block' if request.query.get('defense')=='block' else 'dodge')
        row=await db.arena_raid_create(1,10,boss_id=boss,silent=True)
        for actor in (20,30):await db.arena_raid_setup(row['token'],actor,'join')
        row=await db.arena_raid_setup(row['token'],10,'start')
        d=json.loads(row['data_json'])
        if boss=='nazarick':
            d['nazarick'].update(stage=4,phase=1)
            load_stage(d)
            d['nazarick']['next_summon']=1
            summon(d)
            set_intent(d)
            # Three existing native attacks coincide at 3.5 on the cast scale.
            for key,f in d['enemies'].items():
                f['stats']['speed']=50 if BOSS_SKILLS[d['enemy_intents'][key]['skill']].power>=35 else 18
                d['enemy_intents'][key]['targets']=['10']
        for key,p in d['players'].items():
            f=p['fighter']
            f['stats'].update(max_hp=800,speed=150 if key=='10' else 0)
            f['hp']=800
        async with db._lock:
            with db.connection:db._raid_save_locked(row,d)
        raise web.HTTPFound('/preview?tgWebAppStartParam=r_'+row['token'])

    app.router.add_get('/boss-queue-review',start)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8143)
    args=parser.parse_args()
    web.run_app(application(),host='127.0.0.1',port=args.port)
