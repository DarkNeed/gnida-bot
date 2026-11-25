"""Production API/UI with disposable SQLite; never uses real bot data."""
import argparse
import hashlib
import hmac
from html import escape
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.preview_chaplain import application as base_application, TOKEN
from arena_assets import render_arena_index
from arena_web import ROOT
from arena_cultist import FORMS, PATRONS, branch_loadout, milestones
from arena_engine import BUILTIN_SKILLS
from arena_progression import choice_avatar


async def application():
    app = await base_application()
    db = app['chaplain_review_db']
    app.middlewares[:] = [m for m in app.middlewares if m.__name__ != 'review_helpers']
    db.connection.execute("UPDATE personal_profiles SET class_id='assassin',archclass_id='assassin_shadow',loadout=? WHERE user_id=10",
                          (json.dumps(['assassin_cut','assassin_needle','assassin_smoke','arch_assassin_shadow']),))
    db.connection.commit()

    async def start(request):
        mode = request.query.get('mode', 'solo')
        patron = request.query.get('patron', '')
        if patron and patron not in PATRONS:
            raise web.HTTPBadRequest(text='Неизвестный покровитель.')
        cultist = mode == 'cultist' or bool(patron)
        stage = 8 if cultist and not patron else 10 if cultist and request.query.get('stage') == '10' else 20
        loadout = branch_loadout(patron) if cultist else ['assassin_cut','assassin_needle','assassin_smoke','arch_assassin_shadow']
        if patron == 'cultist_shub' and stage == 20:
            loadout[1] = 'cult_roots'
        loadout = [key for key in loadout if BUILTIN_SKILLS[key].unlock_level <= stage]
        async with db._lock:
            db.connection.execute("UPDATE arena_battles SET status='cancelled' WHERE status IN ('pending','active')")
            db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
            db.connection.execute('DELETE FROM arena_qte_flows')
            db.connection.execute("""UPDATE personal_profiles SET class_id=?,archclass_id=?,level=?,archclass_stage=?,
                progression_level=?,loadout=?,skill_memory=NULL,skill_offers='[]',skill_seen='[]',
                passive_loadout='[]',passive_memory=NULL,passive_seen='[]' WHERE user_id=10""",
                ('cultist' if cultist else 'assassin', patron if cultist else 'assassin_shadow',
                 stage, max(10,stage), stage, json.dumps(loadout)))
            db.connection.commit()
        await db.arena_combat_settings(10, enabled=request.query.get('qte','1')!='0',
            defense_mode='block' if request.query.get('defense')=='block' else 'dodge')
        await db.arena_combat_settings(20, enabled=request.query.get('qte','1')!='0')
        if mode == 'solo':
            row = await db.arena_wasteland(1,10,personal=True)
            prefix = 'b_'
            summon_demo = request.query.get('summon')
            if summon_demo in ('opponent', 'self'):
                from arena_engine import create_battle_state
                from arena_cultist import after_action
                from arena_unified_queue import clock, initialize
                from arena_unified_store import catalog, _save
                async with db._lock:
                    state = json.loads(row['state_json'])
                    cult = dict(slave_id=0, owner_id=0, class_id='cultist', level=20,
                                archclass_id='cultist_shub', archclass_stage=20, loadout=branch_loadout('cultist_shub'))
                    enemy = create_battle_state(cult,cult)['sides']['b']
                    enemy['hp'] = enemy['stats']['max_hp'] = 280
                    if summon_demo == 'opponent':
                        after_action(enemy, state['sides']['a'], BUILTIN_SKILLS['cult_brood'], True)
                    else:
                        if patron != 'cultist_shub':
                            raise web.HTTPBadRequest(text='Перехват проверяется с веткой Шуб-Ниггурат.')
                        enemy['own_turns'] = 1
                        enemy['loadout'] = ['cult_sign']
                        after_action(state['sides']['a'], enemy, BUILTIN_SKILLS['cult_brood'], True)
                    state['sides']['b'] = enemy
                    clock(state)['pending'].clear()
                    initialize(state, catalog(db))
                    _save(db, 'battle', row, state)
                    db.connection.commit()
        elif mode == 'pvp':
            row = await db.arena_offer(1,10,20,'personal')
            await db.arena_set_message(row['token'],1)
            row = await db.arena_setup(row['token'],20,'accept')
            prefix = 'b_'
        else:
            if mode in ('party','encounter','bars','cultist'):
                row = await db.arena_encounter_create(1,30,['goblin','shaman'])
                await db.arena_raid_set_message(row['token'],1)
                for actor in ((10,20) if mode=='party' else (10,)):
                    await db.arena_raid_setup(row['token'],actor,'join')
                row = await db.arena_raid_setup(row['token'],30,'start')
                if mode in ('bars','cultist') or (mode == 'party' and patron == 'cultist_shub' and request.query.get('summon') == '1'):
                    # One fast attacker and one slow one, with enough HP to
                    # observe several casts. All actions use production code.
                    from arena_unified_queue import clock, initialize
                    from arena_unified_store import catalog
                    async with db._lock:
                        state = json.loads(row['data_json'])
                        if mode == 'bars':
                            state['enemies']['e1']['stats']['speed'] = 30
                            state['enemies']['e2']['stats']['speed'] = 0
                            for fighter in [state['players']['10']['fighter'], *state['enemies'].values()]:
                                fighter['hp'] = fighter['stats']['max_hp'] = 1000
                        else:
                            for enemy in state['enemies'].values():
                                enemy['hp'] = enemy['stats']['max_hp'] = 320
                                enemy['stats']['evasion'] = 0
                            fighter = state['players']['10']['fighter']
                            fighter['hp'] = fighter['stats']['max_hp'] = 260
                            if patron == 'cultist_shub' and request.query.get('summon') == '1':
                                from arena_cultist import after_action
                                target = state['enemies']['e1']
                                after_action(fighter, target, BUILTIN_SKILLS['cult_brood'], True)
                                fighter['rpg_state']['cult_fanaticism'] = 2
                                target['own_turns'] = 1  # Intent targets the already-present offspring.
                                target['stats']['physical_attack'] = 4  # Leave time to test both stances.
                                state['enemies']['e2']['stats'].update(speed=0, magic_attack=3)
                        clock(state)['pending'].clear()
                        initialize(state, catalog(db))
                        db._raid_save_locked(row, state)
                        db.connection.commit()
            else:
                row = await db.arena_raid_create(1,10,request.query.get('boss','lei_heng'),silent=True)
                row = await db.arena_raid_setup(row['token'],10,'start')
            prefix = 'r_'
        raise web.HTTPFound('/live-preview?tgWebAppStartParam='+prefix+row['token'])

    async def preview(request):
        actor = 20 if request.query.get('actor')=='20' else 10
        pairs = dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret = hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        html = render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def cultist_review(request):
        def moves(ids):
            skills = (BUILTIN_SKILLS[sid] for sid in ids)
            def dodge(skill):
                if not skill.hostile:
                    return ''
                url = '/qte-lab/unique/?' + urlencode({'mode': 'defense', 'skill': skill.skill_id})
                return f' <a href="{escape(url)}">Уклонение</a>'
            return ''.join(f'<li><b>{escape(s.name)}</b> · ур. {s.unlock_level}'
                           f'<br>{escape(s.description)}{dodge(s)}</li>' for s in skills)

        def card(key, patron):
            name, passive, description = patron
            form = FORMS[key]
            human = choice_avatar("cultist", key, 10)
            avatar = choice_avatar("cultist", key, 20)
            return (f'<article><span class="tag">Ветка покровителя</span><h2>{escape(name)}</h2>'
                    f'<div class="patron-sprites"><figure class="human-form"><figcaption><span class="tag">10 уровень</span><h3>Культист</h3></figcaption>'
                    f'<img src="{escape(human)}" alt="Культист Бездны · {escape(name)}" loading="lazy" decoding="async"></figure>'
                    f'<figure class="final-form"><figcaption><span class="tag">20 уровень</span><h3>{escape(form["name"])}</h3></figcaption>'
                    f'<img src="{escape(avatar)}" alt="{escape(form["appearance"])}" loading="lazy" decoding="async"></figure></div>'
                    f'<p><b>{escape(passive)}</b> · {escape(description)}</p>'
                    f'<a href="/live-queue-review?mode=cultist&amp;stage=10&amp;patron={key}">Бой на 10 уровне</a>'
                    f'<details open><summary>Навыки ветки</summary><ul>{moves([m["skill_id"] for m in milestones(dict(archclass_id=key, level=20))])}</ul></details>'
                    f'<details><summary>Пассивка формы 20 уровня</summary>'
                    f'<p><b>{escape(form["passive"])}</b> · {escape(form["description"])}</p></details>'
                    f'<a href="/live-queue-review?mode=cultist&amp;patron={key}">Бой формой с мини-играми</a>'
                    f'<a href="/live-queue-review?mode=cultist&amp;qte=0&amp;patron={key}">Быстрый бой</a>'
                    + ('<a href="/live-queue-review?mode=cultist&amp;patron=cultist_shub&amp;summon=1&amp;qte=0">Отпрыск уже на поле</a>'
                       '<a href="/live-queue-review?mode=solo&amp;summon=opponent&amp;qte=0">Бой против отпрыска</a>'
                       if key == 'cultist_shub' else '') + '</article>')

        cards = ''.join(card(key, patron) for key, patron in PATRONS.items())
        icons = ('<aside aria-label="Новые иконки состояний"><h2>Иконки эффектов</h2><ul class="status-preview">' +
                 ''.join(f'<li><img src="/static/assets/status-effects-v4/{key}.png" alt="">{name}</li>'
                         for key, name in (('cult_fanaticism','Фанатизм'), ('cult_seal','Кощунственная печать'),
                                           ('cult_whisper','Шёпот глубин'), ('cult_yellow','Жёлтый знак'),
                                           ('cult_gate','Вход открыт'), ('brood_guard','Защитник'), ('brood_predator','Хищник'))) +
                 '</ul></aside>')
        base = ('<article class="base-cultist"><img src="' + choice_avatar("cultist") +
                '" alt="Базовый Культист Бездны" decoding="async"><div><span class="tag">5–9 уровни</span>'
                '<h2>Без покровителя</h2><p>До выбора ветки Культист пользуется общими знаками, Голосом и Обрядом.</p>'
                '<a href="/live-queue-review?mode=cultist&amp;qte=0">Бой базовым культистом</a>'
                '<details><summary>Общие навыки Культиста</summary><ul>' + moves(branch_loadout('')) +
                '</ul></details></div></article>')
        return web.Response(text='<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Культ Древних</title>'
            '<style>body{background:#101322;color:#e7e7f3;font:16px system-ui;margin:2rem auto;padding:0 1rem;max-width:52rem}'
            'section{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr));gap:1rem}'
            'article{padding:1rem;background:#1a1d30;border:1px solid #363953;border-radius:12px}'
            '.base-cultist{display:grid;grid-template-columns:minmax(74px,8rem) minmax(0,1fr);gap:.75rem;align-items:center;margin-bottom:1rem}'
            '.base-cultist img{width:100%;height:160px;object-fit:contain}'
            '.patron-sprites{display:grid;grid-template-columns:1fr 1fr;gap:.42rem;margin-top:.65rem}'
            'figure{display:flex;flex-direction:column;justify-content:space-between;margin:0;min-width:0;padding:.42rem;border:1px solid #373752;border-radius:9px;background:#111525;text-align:center}'
            'figcaption h3{margin:.2rem 0;font-size:.82rem;color:#efc99a;line-height:1.2;overflow-wrap:anywhere}'
            'figure img{display:block;width:100%;height:clamp(108px,32vw,184px);object-fit:contain}'
            '.tag{font-size:.73rem;color:#aba8c8}'
            'h2{margin:0;color:#ddcaf3}p,li{line-height:1.5}li{margin:.45rem 0}'
            'a{display:inline-block;margin:.6rem .65rem 0 0;color:#b4d7fc}'
            '.status-preview{display:flex;flex-wrap:wrap;gap:.35rem .8rem;padding:0;list-style:none}'
            '.status-preview li{display:flex;align-items:center;gap:.25rem;font-size:.82rem}.status-preview img{width:26px;height:26px}</style>'
            '<h1>Культист Бездны</h1><p>На 10 уровне — договор с покровителем. На 20 уровне — превращение в существо его мифа. '
            '«Уклонение» открывает атаку в лаборатории для отдельной проверки.</p>'
            +icons+base+'<section>'+cards+'</section>',content_type='text/html')

    app.router.add_get('/live-queue-review',start)
    app.router.add_get('/live-preview',preview)
    app.router.add_get('/cultist-review',cultist_review)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8155)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
