"""Read-only standalone review server. Does not import the bot or open a database."""
from pathlib import Path
import argparse
import json
import sys
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create_app():
    @web.middleware
    async def no_cache(request, handler):
        response = await handler(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    app = web.Application(middlewares=[no_cache])

    async def index(request):
        from arena_qte_unique import review_catalog
        from arena_engine import BUILTIN_SKILLS
        from arena_raid_engine import BOSS_SKILLS
        from arena_guild_rules import SKILLS as GUILD_SKILLS
        skills = BUILTIN_SKILLS | BOSS_SKILLS | GUILD_SKILLS
        catalog = [dict(s, cost=skills[s['base_id']].cost if s['base_id'] in skills else 20) for s in review_catalog()]
        name = 'battle.html' if request.path == '/party-battle-review' else 'index.html'
        text = (ROOT / 'tools/action_queue_lab' / name).read_text(encoding='utf-8')
        return web.Response(text=text.replace('__CATALOG__', json.dumps(catalog, ensure_ascii=False).replace('<', '\\u003c')), content_type='text/html')

    async def health(request):
        return web.json_response({'ok': True, 'lab': True, 'accounts': False})

    async def shared_js(request):
        return web.FileResponse(ROOT / 'webapp/qte-input', headers={'Content-Type': 'application/javascript; charset=utf-8'})

    async def shared_css(request):
        return web.FileResponse(ROOT / 'webapp/qte-input.css')

    scripts = {name: ROOT / 'webapp' / source for name, source in {
        'patterns.js': 'qte-unique/engine', 'block.js': 'qte-block/engine',
        'nazarick.js': 'nazarick-qte.js', 'nazarick-dungeon.js': 'nazarick-dungeon-qte.js',
        'art.js': 'qte-art.js', 'casino-view.js': 'qte-casino-view',
        'view.js': 'qte-view', 'block-view.js': 'qte-block-view',
    }.items()}

    async def existing_script(request):
        path = scripts.get(request.match_info['name'])
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Type': 'application/javascript; charset=utf-8'})

    app.router.add_get('/', index)
    app.router.add_get('/action-queue-review', index)
    app.router.add_get('/party-battle-review', index)
    app.router.add_get('/health', health)
    app.router.add_get('/shared/qte-input.js', shared_js)
    app.router.add_get('/shared/qte-input.css', shared_css)
    app.router.add_get('/existing/{name}', existing_script)
    app.router.add_static('/static/assets/', ROOT / 'webapp/assets', show_index=False)
    app.router.add_static('/lab/', ROOT / 'tools/action_queue_lab', show_index=False)
    app.router.add_static('/assets/', ROOT / 'webapp/assets', show_index=False)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8141)
    args = parser.parse_args()
    web.run_app(create_app(), host='127.0.0.1', port=args.port)
