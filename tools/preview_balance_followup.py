"""Loopback review: real arena/menu APIs over the guild demo's temporary DB."""
import argparse
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import urlencode

from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_guild import application as guild_application,CHAT


async def application():
    app=await guild_application();db=app['guild_review_db']
    for actor,cls,branch,stage,loadout in (
        (10,'priest','priest_bishop',20,['light_word','priest_heal','priest_ward','arch_priest_bishop']),
        (20,'mage','mage_archmage',10,['mana_shot','mana_focus','mana_overload','arch_mage_archmage']),
        (30,'gambler','casino_lucky',20,['casino_bet','casino_all_in','casino_guard','casino_deposit'])):
        db.connection.execute('''UPDATE personal_profiles SET class_id=?,level=20,archclass_id=?,archclass_stage=?,
            progression_level=20,progression_pending_level=0,progression_pending_at=NULL,
            skill_memory=NULL,skill_seen='[]',passive_memory=NULL,passive_loadout='[]',loadout=?
            WHERE chat_id=0 AND user_id=?''',(cls,branch,stage,json.dumps(loadout),actor))
        db._arena_equip_class_passives_locked(CHAT,actor,True,cls)
        db._add_francs_locked(CHAT,actor,50000)
        db.connection.execute('UPDATE guild_hunters SET rank=3,peak_rank=MAX(peak_rank,3) WHERE actor_id=?',(actor,))
    db._casino_row_locked(30)
    db.connection.execute('UPDATE arena_casino_unlocks SET invited=1,unlocked=1 WHERE user_id=30')
    db.connection.commit()

    @web.middleware
    async def companion(request,handler):
        if request.method=='GET' and request.path.startswith('/api/raid/'):
            token=request.path.rsplit('/',1)[-1]
            async with db._lock:
                row=db.connection.execute('SELECT * FROM arena_raids WHERE token=?',(token,)).fetchone()
                if row and row['status']=='active':
                    data=json.loads(row['data_json']);main=data.get('_balance_review_actor')
                    if main:
                        for key,p in data['players'].items():
                            if key!=str(main) and p['fighter']['hp']>0 and not p.get('withdrawn') and p['selected'] is None:p['selected']='defend'
                        db.connection.execute('UPDATE arena_raids SET data_json=? WHERE token=?',(json.dumps(data),token));db.connection.commit()
        return await handler(request)
    app.middlewares.append(companion)

    async def scenario(request):
        name=request.match_info['case']
        if name not in ('prayer','party','mana','roulette'):raise web.HTTPBadRequest()
        actor=10 if name in ('prayer','party') else 20 if name=='mana' else 30
        # Only this demo's disposable encounters. Never clear the roulette lock:
        # the next roulette scenario must demonstrate the real retry protection.
        async with db._lock:
            with db.connection:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE status IN ('lobby','active')")
                db.connection.execute("UPDATE arena_battles SET status='cancelled' WHERE status IN ('pending','active')")
                db.connection.execute("UPDATE guild_runs SET status='cancelled' WHERE status IN ('lobby','active')")
                db.connection.execute('DELETE FROM arena_qte_flows')
        row=await db.arena_raid_create(CHAT,actor,'lei_heng',silent=True)
        if name=='party':row=await db.arena_raid_setup(row['token'],20,'join')
        row=await db.arena_raid_setup(row['token'],actor,'start',expected_revision=row['revision'])
        async with db._lock:
            with db.connection:
                data=json.loads(row['data_json']);data['_balance_review_actor']=actor
                boss=data['boss'];boss['hp']=boss['stats']['max_hp']=10000
                boss['stats'].update(magic_defense=30,physical_defense=30,evasion=0)
                hero=data['players'][str(actor)]['fighter'];hero['resource']=100
                hero['defense_mode']='block'
                if name in ('prayer','party'):
                    hero['stats']['max_hp']=187;hero['hp']=10
                    hero['rpg_state']={'faith':3}
                    if name=='party':
                        ally=data['players']['20'];ally['fighter']['hp']=10;ally['fighter']['stats']['max_hp']=187;ally['selected']='defend'
                elif name=='mana':
                    hero['hp']=hero['stats']['max_hp']=1000
                    hero['rpg_state']={'mana':3,'echo_ready':True}
                else:
                    hero['hp']=hero['stats']['max_hp']=1000
                    hero['casino_state']={'misfortune':1,'chips':3,'sevens':3}
                db._raid_save_locked(row,data)
        raise web.HTTPFound('/guild-preview?'+urlencode(dict(actor=actor,tgWebAppStartParam='r_'+row['token'])))

    async def reset_lock(request):
        async with db._lock:
            with db.connection:db.connection.execute('DELETE FROM arena_roulette_windows WHERE actor_id=30')
        return web.json_response(dict(ok=True))

    async def page(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Баланс · молитва, рулетка и мана</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b1425;color:#dce5f7;font:13px system-ui;height:100dvh;display:flex;flex-direction:column;overflow:hidden}
header{padding:12px 16px;border-bottom:1px solid #34415d;display:flex;align-items:center;gap:8px;flex-wrap:wrap}strong{color:#f4cc83;margin-right:8px}
button,select{font:inherit;color:#dce5f7;background:#182740;border:1px solid #465c7d;border-radius:8px;padding:9px 12px;cursor:pointer}button:hover{background:#2e4364}
.note{padding:8px 16px;color:#a7bbd9;line-height:1.5;border-bottom:1px solid #23344f}iframe{border:0;flex:1;min-height:0;width:100%;margin:0 auto;background:#0b1425}
@media(max-width:650px){header{padding:8px;gap:5px}header button{padding:8px;font-size:11px}.note{padding:6px 10px;font-size:11px}}
</style><header><strong>БАЛАНС · ВРЕМЕННАЯ БАЗА</strong>
<button data-scene="prayer">Молитва · соло</button><button data-scene="party">Молитва · вдвоём</button>
<button data-scene="mana">Полная Перегрузка</button><button data-scene="roulette">Ва-банк · новый бой</button>
<select id="actor" aria-label="Персонаж демо"><option value="10">Жрец</option><option value="20">Архимаг</option><option value="30">Счастливчик</option></select>
<button id="menu">Меню · карта и гильдия</button><button id="reset">Сбросить таймер · только демо</button><button id="mobile">390px</button><button id="desktop">ПК</button></header>
<div class="note" id="note">В меню появились «Карта» и «Гильдия». Сценарии пересоздают только временные бои. Никаких реальных игроков и платежей.</div>
<iframe title="Проверка боевого баланса" src="/guild-preview?actor=10&amp;tgWebAppStartParam=menu_-100"></iframe>
<script>
const frame=document.querySelector('iframe'),note=document.getElementById('note'),actor=document.getElementById('actor');
const hints={prayer:'HP 10/187, три Веры. Обычная молитва: +70 HP за 25 маны, Вера остаётся. Финал: +117 HP за 60 маны и три Веры. Перезарядка общая; для сравнения перезапусти сценарий.',
party:'Два героя по 10/187 HP. Финал лечит обоих с Милосердием и защищает. Напарник автоматически выбирает защиту.',
mana:'Три Перенасыщения и готовое Эхо. Полная Перегрузка дополнительно ×1,5. Для сравнения со Стиранием перезапусти сценарий: у врага 30 магической защиты.',
roulette:'Запусти Ва-банк, затем снова открой этот сценарий: новый стол будет закрыт на 3 минуты, остальные навыки работают. В том же бою обычная перезарядка. Перезапуск сценария таймер не стирает.'};
document.querySelectorAll('[data-scene]').forEach(b=>b.onclick=()=>{actor.value=['prayer','party'].includes(b.dataset.scene)?'10':b.dataset.scene==='mana'?'20':'30';note.textContent=hints[b.dataset.scene];frame.src='/balance-demo/'+b.dataset.scene;});
document.getElementById('menu').onclick=()=>{note.textContent='Реальное меню арены. Открой новые кнопки «Карта» и «Гильдия»; вернуться можно кнопкой «Арена».';frame.src='/guild-preview?actor='+actor.value+'&tgWebAppStartParam=menu_-100';};
document.getElementById('reset').onclick=async()=>{await fetch('/balance-demo/reset-roulette',{method:'POST'});note.textContent='Таймер испытателя сброшен только во временной базе. Снова открой Ва-банк.';};
document.getElementById('mobile').onclick=()=>frame.style.width='390px';document.getElementById('desktop').onclick=()=>frame.style.width='100%';
</script></html>''',content_type='text/html',headers={'Cache-Control':'no-store'})

    app.router.add_post('/balance-demo/reset-roulette',reset_lock)
    app.router.add_get('/balance-demo/{case}',scenario)
    app.router.add_get('/balance-review',page)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8137)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
