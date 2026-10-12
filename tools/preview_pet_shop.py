"""Local-only shop QA with a disposable database and disabled real payments."""
import argparse
import hashlib
import hmac
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from aiohttp import web
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena_web import create_arena_app
from database import Database


async def create_app():
    temp = tempfile.TemporaryDirectory(prefix="gnida-pet-qa-")
    db = Database(Path(temp.name) / "qa.sqlite")
    await db.connect()
    await db.upsert_chat(1, "Локальное демо")
    await db.upsert_chat(2, "Рейд — локальное демо")
    await db.upsert_chat(3, "Соло — локальное демо")
    for user in (10, 20, 30):
        await db.upsert_user(1, user, str(user), f"Игрок {user}")
        await db.upsert_user(2, user, str(user), f"Игрок {user}")
        await db.upsert_user(3, user, str(user), f"Игрок {user}")
    await db.pet_view(10)
    db.connection.execute("UPDATE pet_wallets SET tickets=40,food=500,essence=10,shards=400 WHERE user_id=10")
    for user,pet in ((10,"bug"),(20,"gachi_duck"),(30,"moon_mimic")):
        db.connection.execute("INSERT INTO pet_owned(user_id,pet_id,acquired_at) VALUES(?,?,?)", (user, pet, int(time.time())))
        for chat in (1,2):
            db.connection.execute("INSERT INTO pet_equipment VALUES(?,?,?)", (chat,user,pet))
    db.connection.commit()
    battle = await db.arena_offer(1,10,20,"personal")
    await db.arena_setup(battle["token"],20,"accept")
    raid = await db.arena_raid_create(2,10,"lei_heng")
    for user in (20,30):
        await db.arena_raid_setup(raid["token"],user,"join")
    await db.arena_raid_setup(raid["token"],10,"start")
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(
        status="member", user=SimpleNamespace(is_bot=False),
    )))
    token = "123456:local-qa-only"
    app = create_arena_app(db, bot, token)

    @web.middleware
    async def local_demo(request, handler):
        # This bypass exists only in this standalone loopback QA server, never production.
        if request.path.startswith("/api/"):
            data = dict(auth_date=str(int(time.time())), user=json.dumps(dict(id=10)))
            secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
            data["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k,v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
            headers = dict(request.headers)
            headers["X-Telegram-Init-Data"] = urlencode(data)
            request = request.clone(headers=headers)
        response = await handler(request)
        if request.path == "/pets" and isinstance(response, web.Response):
            response.text = response.text.replace("Общий аккаунт</span>", "ДЕМО · ТЕСТОВЫЕ ДАННЫЕ</span>")
        return response

    app.middlewares.insert(0, local_demo)

    async def battle_page(request):
        raise web.HTTPFound("/?tgWebAppStartParam=b_" + battle["token"])

    async def raid_page(request):
        raise web.HTTPFound("/?tgWebAppStartParam=r_" + raid["token"])

    async def solo_menu(request):
        raise web.HTTPFound("/?tgWebAppStartParam=menu_3")

    app.router.add_get("/qa/battle", battle_page)
    app.router.add_get("/qa/raid", raid_page)
    app.router.add_get("/qa/menu", solo_menu)

    async def cleanup(app):
        await db.close()
        temp.cleanup()

    app.on_cleanup.append(cleanup)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8101)
    web.run_app(create_app(), host="127.0.0.1", port=parser.parse_args().port)
