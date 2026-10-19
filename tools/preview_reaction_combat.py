"""Real HTTP/replay integration against disposable data; no Telegram polling or real token."""

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_assets import render_arena_index
from arena_web import create_arena_app, ROOT
from database import Database

TOKEN = "disposable-reaction-preview-not-a-bot-token"


async def application():
    temporary = tempfile.TemporaryDirectory(prefix="gnida-qte-preview-")
    db = Database(Path(temporary.name) / "preview.sqlite3")
    await db.connect()
    await db.upsert_chat(1, "Полигон реакции · временная база")
    for actor in (10, 20):
        await db.upsert_user(1, actor, str(actor), "Испытатель " + str(actor))
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(
            return_value=SimpleNamespace(
                status="member", user=SimpleNamespace(is_bot=False)
            )
        )
    )
    app = create_arena_app(db, bot, TOKEN)

    async def preview(request):
        actor = 20 if request.query.get("player") == "20" else 10
        pairs = dict(auth_date=str(int(time.time())), user=json.dumps(dict(id=actor)))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        pairs["hash"] = hmac.new(
            secret,
            "\n".join(k + "=" + v for k, v in sorted(pairs.items())).encode(),
            hashlib.sha256,
        ).hexdigest()
        init = urlencode(pairs)
        html = render_arena_index(ROOT).replace(
            '<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            "<script>window.Telegram={WebApp:{initData:"
            + json.dumps(init)
            + ",initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>",
        )
        return web.Response(
            text=html, content_type="text/html", headers={"Cache-Control": "no-store"}
        )

    async def lobby(request):
        # Local-only helper to open a real two-player duel in two preview tabs.
        # It never runs in the production app and never uses its database.
        r = await db.arena_offer(1, 10, 20, "personal", 0)
        await db.arena_set_message(r["token"], 1)
        r = await db.arena_setup(r["token"], 20, "accept")
        return web.HTTPFound("/preview?tgWebAppStartParam=b_" + r["token"])

    app.router.add_get("/preview", preview)
    app.router.add_post("/preview-duel", lobby)

    async def close(_):
        await db.close()
        temporary.cleanup()

    app.on_cleanup.append(close)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8104)
    web.run_app(application(), host="127.0.0.1", port=parser.parse_args().port)
