"""Loopback-only economy review. Disposable DB and frozen merchant clock, no Telegram IO."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import time
from unittest.mock import patch

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.preview_guild import application as guild_application, CHAT
from arena_engine import BUILTIN_SKILLS, BUILTIN_PASSIVES
from arena_market import MSK, PRICES


async def application():
    app = await guild_application()
    db = app['guild_review_db']
    now = int(datetime.now(MSK).replace(hour=12, minute=0, second=0).timestamp())
    clock = patch('arena_market.market_now', return_value=now)
    clock.start()
    async def stop_clock(_): clock.stop()
    app.on_cleanup.append(stop_clock)
    with db.connection:
        db._add_francs_locked(CHAT, 10, 15000)
        wallet = db._forge_wallet_locked(CHAT, 10)
        wallet['pages'].update(common=20, uncommon=20, rare=20, epic=60, legendary=12)
        db._forge_save_wallet_locked(CHAT, 10, wallet)
        for ident in ('dust_in_eyes', 'last_argument', 'royal_verdict', 'mana_overload'):
            s=BUILTIN_SKILLS[ident]
            db._arena_add_item_locked(CHAT,10,'skill',ident,s.rarity,6)
        db._arena_add_item_locked(CHAT,10,'passive','unyielding_will','legendary',3)
        db.connection.execute('UPDATE guild_hunters SET reputation=123,rank_wins=4,clearance=0 WHERE actor_id=10')
        visit=db.connection.execute('INSERT INTO arena_merchant_visits(chat_id,day,visit,starts,ends) VALUES(0,?,1,?,?)',('economy-demo',now-1,now+7200)).lastrowid
        for ident in ('mana_overload','royal_verdict','catch_breath'):
            s=BUILTIN_SKILLS[ident]
            db.connection.execute('INSERT INTO arena_merchant_offers(visit_id,kind,content_id,rarity,price,per_user) VALUES(?,?,?,?,?,1)',(visit,'skill',ident,s.rarity,PRICES[s.rarity]))

    async def page(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Исправления экономики · демо</title>
<style>*{box-sizing:border-box}body{margin:0;background:#0c1424;color:#e1eafa;font:14px system-ui}header{padding:12px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}a{color:#d5b76e}iframe{display:block;width:100%;height:calc(100dvh - 90px);border:0}button{background:#1b2c45;color:#e1eafa;border:1px solid #435576;border-radius:6px;padding:7px}</style>
<header><b>ДЕМО · временная база</b><a target="economy" href="/guild-preview?actor=10&amp;tgWebAppStartParam=shop_-100">Торговец / инвентарь / кузница</a><a target="economy" href="/guild-preview?actor=10&amp;tgWebAppStartParam=guild_-100">Репутация 123/100</a><a target="economy" href="/qte-lab/unique/?mode=defense">Капеллан · выбери «Часовая стрелка»</a><button onclick="document.querySelector('iframe').style.width='390px';document.querySelector('iframe').style.margin='auto'">390px</button><button onclick="document.querySelector('iframe').style.width='100%'">ПК</button><small>Ресурсы тестовые. Часы торговца зафиксированы. Реальные аккаунты и Telegram не затрагиваются.</small></header>
<iframe name="economy" title="Проверка экономики" src="/guild-preview?actor=10&amp;tgWebAppStartParam=shop_-100"></iframe></html>''',content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/economy-review', page)
    return app


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8134)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
