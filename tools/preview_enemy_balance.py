"""Local monster kit/QTE review. Only the guild demo's disposable database."""
import argparse
import json
from pathlib import Path
import sys

from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_guild import application as guild_application
from arena_guild_rules import MONSTERS, RANKS
from arena_qte_unique import review_catalog


async def application():
    app=await guild_application()
    async def page(request):
        catalog=review_catalog()
        monsters=[]
        for key,m in MONSTERS.items():
            tier=max(0,min(4,RANKS.index(m['rank'])-2))
            moves=[next(s for s in catalog if s['base_id']==sid and s.get('npc_tier',0)==tier) for sid in m['skills']]
            monsters.append(dict(id=key,name=m['name'],rank=m['rank'],moves=moves))
        data=json.dumps(monsters,ensure_ascii=False).replace('<','\\u003c')
        html='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Проверка сильных врагов</title><style>*{box-sizing:border-box}body{margin:0;height:100dvh;display:flex;flex-direction:column;overflow:hidden;background:#0c1424;color:#dfebfa;font:15px system-ui}header{flex-shrink:0;padding:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #334665}select,button,a{font:inherit;background:#1b2b43;color:#dfebfa;border:1px solid #4a6289;border-radius:8px;padding:10px;max-width:100%}button.active{background:#49678b}#note{flex-shrink:0;padding:8px 14px;color:#9fb4d4}iframe{width:100%;flex:1;min-height:0;border:0}@media(max-width:600px){header{gap:6px;padding:8px}select{width:100%}#note{font-size:12px}}</style>
<header><strong>Сильные враги · локальное демо</strong><select id="monster"></select><select id="move"></select><button id="dodge" class="active">Уклонение</button><button id="block">Блок</button><a href="/guild-review" target="_blank">Походы гильдии</a></header><div id="note">Проверь сначала без уклонения: точность 98–100%, уклонение 0–10%. Затем подними уклонение. Секунда подготовки сохранена.</div><iframe id="lab" title="Мини-игра противника"></iframe>
<script type="application/json" id="data">__DATA__</script><script>
const monsters=JSON.parse(document.getElementById('data').textContent),mob=document.getElementById('monster'),move=document.getElementById('move');let mode='dodge';
for(const m of monsters)mob.add(new Option(m.rank+' · '+m.name,m.id));mob.value='deathlord';
function show(){document.getElementById('lab').src='/qte-lab/'+(mode==='block'?'block/':'unique/?mode=defense&')+(mode==='block'?'?':'')+'skill='+encodeURIComponent(move.value);}
function fill(){move.replaceChildren(...monsters.find(m=>m.id===mob.value).moves.map(s=>new Option(s.name,s.id)));show();}
mob.onchange=fill;move.onchange=show;for(const k of ['dodge','block'])document.getElementById(k).onclick=()=>{mode=k;for(const id of ['dodge','block'])document.getElementById(id).classList.toggle('active',id===k);show();};fill();
</script></html>'''
        return web.Response(text=html.replace('__DATA__',data),content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/enemy-review',page)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8133)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
