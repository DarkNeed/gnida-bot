"""Disposable gear merchant review. No production DB, token, or Telegram polling."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
from unittest.mock import patch
from aiohttp import web
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.preview_equipment import application as equipment_application
from arena_market import MSK


async def application():
    frozen=int(datetime(2026,11,15,12,tzinfo=MSK).timestamp())
    clock=patch('arena_market.market_now',return_value=frozen);clock.start()
    try:app=await equipment_application()
    except BaseException:clock.stop();raise
    db=app['guild_review_db']
    with db.connection:
        db.connection.execute('UPDATE guild_hunters SET rank=6,peak_rank=6 WHERE actor_id=10')
        db._add_francs_locked(-100,10,100000)
        db.connection.execute('INSERT INTO arena_merchant_visits(chat_id,day,visit,starts,ends) VALUES(0,?,1,?,?)',('2026-11-15',frozen-60,frozen+3600))
        db._gear_guild_stock_locked('S','2026-11-15')
    async def review(request):
        return web.Response(text='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Торговец · снаряжение</title><style>body{margin:0;background:#0c1324;color:#e1ebff;font:13px system-ui;height:100dvh;display:flex;flex-direction:column}header{display:flex;gap:12px;flex-wrap:wrap;padding:12px}a{color:#efcd83}iframe{width:100%;flex:1;border:0;min-height:0;margin:auto}button{background:#1d2b46;color:#e1ebff;border:1px solid #4e6385;border-radius:6px;padding:6px}</style><header><b>ТОРГОВЕЦ · тестовая база</b><a target="market" href="/guild-preview?actor=10&amp;tgWebAppStartParam=shop_-100">Магазин · ранг S</a><a target="market" href="/guild-preview?actor=30&amp;tgWebAppStartParam=shop_-100">Новичок · ранг F</a><a target="market" href="/guild-preview?actor=10&amp;tgWebAppStartParam=equipment_-100">Снаряжение и продажа</a><button onclick="document.querySelector('iframe').style.width='390px'">Телефон</button><button onclick="document.querySelector('iframe').style.width='100%'">ПК</button><span>Деньги тестовые. Лимиты покупок настоящие. Обновление страницы их не сбрасывает.</span></header><iframe name="market" title="Магазин" src="/guild-preview?actor=10&amp;tgWebAppStartParam=shop_-100"></iframe></html>''',content_type='text/html',headers={'Cache-Control':'no-store'})
    app.router.add_get('/merchant-review',review)
    async def guild_shop_review(request):
        raise web.HTTPFound('/guild-preview?actor='+('30' if request.query.get('newbie')=='1' else '10')+'&tgWebAppStartParam=guildshop_-100')
    app.router.add_get('/guild-shop-review',guild_shop_review)
    async def cleanup(_):clock.stop()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8159)
    web.run_app(application(),host='127.0.0.1',port=p.parse_args().port)
