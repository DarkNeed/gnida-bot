"""Production UI/API review, disposable SQLite, loopback only; no real Telegram."""
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
    app.middlewares[:] = [m for m in app.middlewares if m.__name__ != 'review_helpers']

    @web.middleware
    async def ally(request, handler):
        if request.method == 'POST' and request.path.startswith('/api/raid/'):
            body = await request.json()
            if body.get('action') == 'skill':
                async with db._lock:
                    row = db._raid_row_locked(request.path.split('/')[-1])
                    data = json.loads(row['data_json'])
                    if row['status'] == 'active' and not data.get('_cast_queue'):
                        data['players']['20']['selected'] = 'defend'
                        db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?', (json.dumps(data), row['token']))
                        db.connection.commit()
        return await handler(request)
    app.middlewares.append(ally)

    async def start(request):
        from arena_engine import stats_for
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('active','lobby')")
                db.connection.execute('DELETE FROM arena_qte_flows')
                db.connection.execute("UPDATE personal_profiles SET class_id='warrior',archclass_id='',level=20,progression_level=20,progression_pending_level=0,loadout='[\"armor_split\",\"warrior_execute\",\"warrior_guard\",\"bum_punch\"]' WHERE user_id=10")
        await db.arena_combat_settings(10, enabled=True, defense_mode='block' if request.query.get('defense') == 'block' else 'dodge')
        await db.arena_combat_settings(20, enabled=False)
        row = await db.arena_encounter_create(1, 30, ['goblin', 'shaman'])
        await db.arena_raid_set_message(row['token'], 5)
        for actor in (10, 20):
            await db.arena_raid_setup(row['token'], actor, 'join')
        row = await db.arena_raid_setup(row['token'], 30, 'start')
        data = json.loads(row['data_json'])
        for key, cls, hp, sid, name in [('e1', 'ragamuffin', 35, 'bum_punch', 'Бомж'), ('e2', 'mage', 500, 'mana_blob', 'Маг')]:
            f = data['enemies'][key]
            f['stats'] = stats_for(cls, 20)
            f['stats'].update(max_hp=hp, speed=18, evasion=0, physical_attack=6 if key=='e1' else 8, magic_attack=8 if key=='e1' else 35)
            f.update(name=name, class_id=cls, hp=hp, resource=f['stats']['resource_max'], mob_id='custom', rp_sandbox=True, rp_ai='sequence',
                     rp_ai_index=0, rp_flip=True, rp_scale=1, loadout=[sid], cooldowns={}, effects=[], mechanics={})
        from arena_encounters import set_intents
        from arena_rp import rp_skills
        from arena_engine import BUILTIN_SKILLS
        set_intents(data, rp_skills(BUILTIN_SKILLS))
        scenario = request.query.get('scenario', 'mix')
        data['enemy_intents']['e1']['targets'] = ['10']
        data['enemy_intents']['e2']['targets'] = ['20'] if scenario == 'cover' else ['10', '20'] if scenario == 'sweep' else ['10']
        data['players']['10']['fighter']['stats']['speed'] = 40
        async with db._lock:
            with db.connection:
                db._raid_save_locked(row, data)
        raise web.HTTPFound('/preview?tgWebAppStartParam=r_' + row['token'])

    app.router.add_get('/party-queue-review', start)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8142)
    args = parser.parse_args()
    web.run_app(application(), host='127.0.0.1', port=args.port)
