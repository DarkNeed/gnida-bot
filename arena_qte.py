"""Isolated, client-only combat experiment. No identity, database or rewards."""

import hashlib
import html
import json
import secrets
import time
from pathlib import Path

from aiohttp import web


def add_qte_lab_routes(app: web.Application, root: Path) -> None:
    from arena_qte_unique import add_unique_qte_routes

    add_unique_qte_routes(app, root)
    folder = root / "qte-lab"

    async def page(request):
        version = hashlib.sha256(
            b"".join(
                (folder / name).read_bytes()
                for name in ("style.css", "engine", "client")
            )
        ).hexdigest()[:16]
        return web.Response(
            text=(folder / "index.html")
            .read_text(encoding="utf-8")
            .replace("__REV__", version),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def script(request):
        return web.FileResponse(
            folder / request.match_info["name"],
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/qte-lab", page)
    app.router.add_get("/qte-lab/", page)
    app.router.add_get("/qte-lab/{name:engine|client}.js", script)

    async def live(request):
        return web.FileResponse(
            root / "qte-live",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/static/qte-live.js", live)

    async def patterns(request):
        return web.FileResponse(
            root / "qte-unique" / "engine",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    async def pattern_view(request):
        return web.FileResponse(
            root / "qte-view",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/static/qte-engine.js", patterns)
    app.router.add_get("/static/qte-view.js", pattern_view)
    async def casino_view(request):
        return web.FileResponse(root / 'qte-casino-view',headers={
            'Content-Type':'application/javascript; charset=utf-8','Cache-Control':'no-cache'})
    app.router.add_get('/static/qte-casino-view.js',casino_view)
    async def casino_chance(request):
        name = 'qte-casino-chance.css' if request.path.endswith('.css') else 'qte-casino-chance'
        return web.FileResponse(root / name, headers={'Cache-Control':'no-cache',
            'Content-Type':'text/css' if name.endswith('.css') else 'application/javascript; charset=utf-8'})
    app.router.add_get('/static/qte-casino-chance.js',casino_chance)
    app.router.add_get('/static/qte-casino-chance.css',casino_chance)
    # Small bounded practice buffer only; never touches a player or currency.
    casino_trials = {}

    async def casino_page(request):
        from arena_casino_chance import mode
        from arena_qte_unique import review_catalog
        catalog = [p for p in review_catalog() if mode(p)]
        query = request.query.get('skill','casino_all_in')
        selected = next((p for p in catalog if query in (p['id'],p['base_id'],p['name'])), None)
        if not selected: raise ValueError('Нет такого испытания казино.')
        now = time.time()
        for key in list(casino_trials):
            if casino_trials[key]['expires'] < now: casino_trials.pop(key)
        while len(casino_trials) >= 128: casino_trials.pop(next(iter(casino_trials)))
        ident = secrets.token_hex(24)
        stage = dict(id=ident, casino_mode=mode(selected), expires=now+300, profile=selected, name=selected['name'], strikes=selected['strikes'])
        casino_trials[ident] = stage
        links=''.join('<a href="?skill='+p['base_id']+'">'+html.escape(p['name'])+'</a>' for p in catalog)
        body='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Казино · случайные атаки</title>
<link rel="stylesheet" href="/static/qte-casino-chance.css"><style>body{margin:0;padding:20px;background:#0c1716;color:#f0e5cd;font:15px/1.6 system-ui}main{max-width:780px;margin:auto}h1{font-size:26px}nav{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}a{color:#e9c57c}#summary{color:#9dd5b4}small{color:#adbeaf}</style><main><small>ЛУДОМАН / ПРОВЕРКА СЛУЧАЙНОСТИ</small><h1>'''+html.escape(selected['name'])+'''</h1><p>Без проверки реакции: результат фиксируется сервером после запуска. Только тестовый урон, без ставок франками и наград.</p><nav>'''+links+'''</nav><div id="game"></div><p id="summary" role="status"></p><nav><a href="">Новый бросок ↻</a><a href="/casino-review">← Обзор класса</a></nav></main><script src="/static/qte-engine.js"></script><script src="/static/qte-casino-view.js"></script><script src="/static/qte-casino-chance.js"></script><script>
const stage='''+json.dumps({k:v for k,v in stage.items() if k!='_casino_chance_seed'},ensure_ascii=False).replace('<','\\u003c')+''';
QTECasinoChance.mount(document.getElementById('game'),stage,async choice=>{const r=await fetch('/qte-lab/casino/roll',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:stage.id,choice})});const d=await r.json();if(!r.ok)throw new Error(d.error||'Не удалось принять ставку');return d;},result=>{document.getElementById('summary').textContent='Тест: опорный урон 40 × '+result.factor+' = '+Math.round(40*result.factor)+'. В настоящем бою урон также зависит от характеристик, блока и уклонения.';});
</script></html>'''
        return web.Response(text=body,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def casino_practice_roll(request):
        from arena_casino_chance import commit
        body = await request.json()
        if not isinstance(body,dict) or not isinstance(body.get('id'),str): raise ValueError('Некорректное испытание.')
        stage = casino_trials.get(body['id'])
        if not stage or stage['expires'] < time.time(): raise ValueError('Испытание истекло. Открой новое.')
        return web.json_response(commit(stage,body.get('choice')),headers={'Cache-Control':'no-store'})

    app.router.add_get('/qte-lab/casino/',casino_page)
    app.router.add_post('/qte-lab/casino/roll',casino_practice_roll)

    async def block_view(request):
        return web.FileResponse(root / "qte-block-view", headers={
            "Content-Type":"application/javascript; charset=utf-8", "Cache-Control":"no-cache",
        })

    app.router.add_get("/static/qte-block-view.js", block_view)

    async def touch_input(request):
        return web.FileResponse(
            root / "qte-input",
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    app.router.add_get("/static/qte-input.js", touch_input)

    async def touch_style(request):
        return web.FileResponse(
            root / "qte-input.css", headers={"Cache-Control": "no-cache"}
        )

    app.router.add_get("/static/qte-input.css", touch_style)

    async def live_style(request):
        return web.FileResponse(
            root / "qte-live.css", headers={"Cache-Control": "no-cache"}
        )

    app.router.add_get("/static/qte-live.css", live_style)
