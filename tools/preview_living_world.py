"""Isolated review of shared camps, land appearance and municipal landmarks."""
import argparse
import json
import sys
from pathlib import Path
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_kingdom import application as kingdom_application,CHAT
from arena_kingdom_rules import DAY,HOUR
from arena_kingdom_war import new_unit
import arena_kingdom_estate as estate
import arena_kingdom_camps as camps
import arena_kingdom_finance as finance


async def application():
    app=await kingdom_application();db=app['guild_review_db'];now=app['kingdom_review_clock'][0]
    for actor in (10,20):
        raw=db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=? AND owner=?',(CHAT,actor)).fetchone()
        row=db._kingdom_row_locked(raw['id']);d=row['data']
        d.update(stage=2,construction=None,event=None,next_event=now+365*DAY,population=70)
        d['buildings'].update(hall=2,farm=2,barracks=2,warehouse=3,sawmill=2,quarry=2)
        d['resources'].update(food=2000,wood=1600,stone=1500);d['factions'].update(light=2,velvet=2,grave=2)
        m=d['military'];m['units']=[new_unit(k,now,ready=True) for k in ('shields','paladins','archers','priests','necromancers')]
        m['formation']=[u['id'] for u in m['units']]
        e=estate.initialize(d);e.update(style='gothic' if actor==10 else 'velvet',color='#ada0ce' if actor==10 else '#d393b6',emblem='moon' if actor==10 else 'rose')
        e['tiles'][f'{row["q"]}:{row["r"]}']=dict(name='Столица без выходных' if actor==10 else 'Бархатные сады',description='Временный мир для проверки. Казна пополнена только в демо.',decoration='lanterns')
        if actor==10:
            for q,r,name,decoration in ((6,4,'Последняя аллея','garden'),(7,5,'Площадь добрых намерений','statue')):
                db.connection.execute('INSERT OR IGNORE INTO kingdom_tiles VALUES(?,?,?,?)',(CHAT,q,r,row['id']))
                e['tiles'][f'{q}:{r}']=dict(name=name,description='Область с отдельным именем и украшением.',decoration=decoration)
        finance.credit(db,row,1000000);db._kingdom_save_locked(row)
    db.connection.commit()
    world=db._kingdom_world_locked(CHAT);camps.advance(db,world,now)
    sample=camps.rows(db,CHAT)[0];sample['data'].update(hp=900,raids=1)
    town=db.connection.execute('SELECT id FROM kingdom_towns WHERE chat=? AND owner=20',(CHAT,)).fetchone()['id']
    sample['data']['contributions'][town]=300
    sample['data']['garrison'][0]['hp']=max(1,sample['data']['garrison'][0]['hp']//2)
    sample['data']['history']=[dict(at=now-HOUR,town='Воронья гавань',damage=300,won=True)]
    camps.save(db,sample);db.connection.commit()

    async def review(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Живые земли · демо</title>
<style>*{box-sizing:border-box}body{margin:0;background:#0b1422;color:#d6e2ee;font:13px system-ui;display:flex;flex-direction:column;height:100dvh;overflow:hidden}header{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:10px 14px;border-bottom:1px solid #33435b}b{color:#e2c18a}button,select{font:inherit;padding:8px 11px;background:#1a2a40;border:1px solid #465c78;color:#dce6f1;border-radius:6px}#note{padding:8px 14px;font-size:12px;color:#a9bdce;line-height:1.5}iframe{border:0;flex:1;min-height:0;width:100%;margin:auto;max-width:100%}@media(max-width:650px){header{gap:5px}button,select{font-size:11px;padding:7px}}</style>
<header><b>ЖИВЫЕ ЗЕМЛИ · ВРЕМЕННАЯ БАЗА</b><select id="actor"><option value="10">Чёрный тракт · игрок 10</option><option value="20">Воронья гавань · игрок 20</option></select><button data-hours="6">+6 часов · поход</button><button data-hours="25">+25 часов · рост лагерей</button><button data-hours="168">+7 дней · стройки</button><button id="mobile">390px</button><button id="desktop">ПК</button><button id="refresh">Обновить</button></header>
<div id="note">Карта — объекты и лагеря. Владение — постройки, казна и оформление. Армия — отряды и походы. Совет — политика и события. Ускорение времени доступно только в демо.</div>
<iframe title="Живые лагеря и оформление земель" src="/kingdom-preview?actor=10&amp;tgWebAppStartParam=kingdom_-100"></iframe>
<script>const frame=document.querySelector('iframe'),actor=document.getElementById('actor'),note=document.getElementById('note');const reload=()=>frame.src='/kingdom-preview?actor='+actor.value+'&tgWebAppStartParam=kingdom_-100';actor.onchange=reload;document.getElementById('refresh').onclick=reload;document.getElementById('mobile').onclick=()=>frame.style.width='390px';document.getElementById('desktop').onclick=()=>frame.style.width='100%';document.querySelectorAll('[data-hours]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const r=await fetch('/kingdom-demo/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'time',hours:Number(b.dataset.hours)})}),d=await r.json();note.textContent=d.error||'Время продвинуто. Лагеря, набеги и стройки используют настоящий серверный расчёт. Тестовые ускорения доступны только в демо.';if(r.ok)reload();}finally{b.disabled=false;}});</script></html>''',content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/living-world-review',review)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8138)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
