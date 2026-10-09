"""Local, token-free visual preview. Does not run Telegram polling or touch bot data."""

from pathlib import Path
import sys
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1] / "webapp"
sys.path.insert(0, str(ROOT.parent))
from arena_assets import render_arena_index

app = web.Application()


async def index(request):
    return web.Response(
        text=render_arena_index(ROOT),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def client(request):
    return web.FileResponse(
        ROOT / "battle-client", headers={"Content-Type": "application/javascript"}
    )


app.router.add_get("/", index)
app.router.add_get("/static/client.js", client)
app.router.add_static("/static/", ROOT)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8085)
