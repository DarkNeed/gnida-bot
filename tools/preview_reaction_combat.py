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


async def application(whaler=False):
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
    if whaler:
        from arena_engine import fighter_xp_limit
        for actor, cls, branch, loadout in [
            (10, 'mage', 'mage_archmage', ['mana_shot', 'mana_focus', 'mana_barrier', 'swamp_miasma']),
            (20, 'priest', 'priest_bishop', ['holy_strike', 'priest_heal']),
        ]:
            db._arena_profile_locked(1, actor, True)
            db._grant_profile_xp_locked('personal_profiles', 1, actor, fighter_xp_limit())
            db.connection.execute('''UPDATE personal_profiles SET class_id=?,archclass_id=?,archclass_stage=20,
                progression_level=20,progression_pending_level=0,loadout=? WHERE chat_id=0 AND user_id=?''',
                (cls, branch, json.dumps(loadout), actor))
            db.connection.execute('INSERT OR IGNORE INTO arena_learned VALUES(?,?,?,?,?)',
                                   (0, actor, 1, 'skill', 'swamp_miasma'))
        db.connection.commit()

        async def whaler_demo(request):
            # Explicit sandbox reset: production code never registers this route.
            rows = db.connection.execute("SELECT token,data_json FROM arena_raids WHERE status IN ('active','lobby')").fetchall()
            for row in rows:
                db.connection.execute("UPDATE arena_raids SET status='cancelled' WHERE token=?", (row['token'],))
                db.connection.execute("DELETE FROM arena_qte_flows WHERE token=?", (row['token'],))
            db.connection.commit()
            row = await db.arena_raid_create(1, 10, boss_id='whaler', silent=True)
            row = await db.arena_raid_setup(row['token'], 10, 'start', expected_revision=row['revision'])
            data = json.loads(row['data_json'])
            data['players']['10']['fighter']['resource'] = 50
            if request.query.get('mode') == 'rot':
                from arena_whaler import set_intent
                data['boss']['hp'] = data['boss']['stats']['max_hp'] // 4
                set_intent(data)
            if request.query.get('mode') == 'miasma':
                from arena_whaler import set_intent
                data['round'] = 3
                set_intent(data)
            db._raid_save_locked(row, data)
            db.connection.commit()
            raise web.HTTPFound('/preview?tgWebAppStartParam=r_' + row['token'])

        app.router.add_get('/whaler-demo', whaler_demo)

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
    parser.add_argument('--whaler', action='store_true', help='Seed disposable level-20 Whaler review')
    args = parser.parse_args()
    web.run_app(application(whaler=args.whaler), host="127.0.0.1", port=args.port)
