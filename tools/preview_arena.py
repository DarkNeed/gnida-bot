"""Local, token-free visual preview. Does not run Telegram polling or touch bot data."""

from pathlib import Path
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1] / "webapp"
app = web.Application()


async def index(request):
    return web.FileResponse(ROOT / "index.html")


async def client(request):
    return web.FileResponse(
        ROOT / "battle-client", headers={"Content-Type": "application/javascript"}
    )


app.router.add_get("/", index)
app.router.add_get("/static/client.js", client)
app.router.add_static("/static/", ROOT)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8085)
