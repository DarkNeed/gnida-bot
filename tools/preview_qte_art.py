"""Local read-only class art review. No bot token, database, polling or payments."""
import argparse
from pathlib import Path
import sys
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_qte_unique import add_unique_qte_routes


def application():
    root = Path(__file__).resolve().parents[1] / 'webapp'
    app = web.Application()
    add_unique_qte_routes(app, root)

    async def script(request):
        return web.FileResponse(root / request.match_info['name'], headers={
            'Content-Type': 'application/javascript; charset=utf-8',
            'Cache-Control': 'no-cache',
        })

    app.router.add_get('/static/{name:qte-view|qte-block-view|qte-casino-view|qte-input}.js', script)
    app.router.add_static('/static/', root)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8130)
    web.run_app(application(), host='127.0.0.1', port=parser.parse_args().port)
