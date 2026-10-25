"""Loopback-only trader review with disposable workers and francs, no Telegram calls."""
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

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_web import create_arena_app
from database import Database


async def application():
    temp=tempfile.TemporaryDirectory(prefix='gnida-trader-review-')
    db=Database(Path(temp.name)/'trader.sqlite3');await db.connect()
    chat=-100
    await db.upsert_chat(chat,'Контора · тестовые владения')
    for user,name in ((10,'Испытатель'),(20,'Сосед по рынку'),(100,'Громила'),(101,'Мрачный маг'),
                      (102,'Лунный охотник'),(103,'Трактирщик'),(104,'Сонный мастер'),(105,'Фельдшер')):
        await db.upsert_user(chat,user,str(user),name)
    for worker in range(100,106):await db.force_enslave(chat,worker,20 if worker==100 else 10)
    # Explicit sample passports make every review reproducible; real users use one secure random draw.
    from slave_identity import rarity_for
    for worker,luck,trait in ((100,9400,'survivor'),(101,9999,'posthumous'),
                             (102,8000,'ruins'),(103,6000,'tavern'),
                             (104,1000,'workshop'),(105,9500,'insured')):
        stamp=int(time.time())
        db.connection.execute('UPDATE slave_identities SET luck=?,trait=?,created_at=?,rarity=? WHERE user_id=?',(luck,trait,stamp-62*86400,rarity_for(luck),worker))
    db.connection.execute('UPDATE ownership SET acquired_at=acquired_at-172800')
    db.connection.commit()
    await db.credit_francs(chat,10,2000);await db.credit_francs(chat,20,1000)
    await db.enterprise_create(chat,10,'tavern')
    site=await db.get_business(chat,10,business_type='tavern')
    for worker in (103,104):await db.enterprise_assign(chat,10,worker,'worker',site['id'])
    for worker,cls in ((100,'jock'),(101,'mage'),(102,'hunter'),(105,'priest')):
        await db.arena_characters(worker)
        db.connection.execute('UPDATE personal_profiles SET class_id=?,level=18 WHERE chat_id=0 AND user_id=?',(cls,worker))
    db.connection.commit()
    v=await db.holdings_view(chat,20)
    await db.trader_action(chat,20,dict(action='trader_list',worker=100,price=240,confirm=True,nonce='s'*32,revision=v['revision']))
    token='local-trader-review-no-production-credentials'
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
    app=create_arena_app(db,bot,token)

    @web.middleware
    async def local_auth(request,handler):
        if request.path.startswith('/api/'):
            data=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=10)))
            secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
            data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
            request=request.clone(headers={**request.headers,'X-Telegram-Init-Data':urlencode(data)})
        return await handler(request)

    app.middlewares.insert(0,local_auth)

    async def review(request):
        # Use the production controller and API, not a second implementation of the economy.
        return web.Response(text='''<!doctype html><html lang="ru"><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Работорговец · тестовая база</title><link rel="stylesheet" href="/static/style.css">
            <link rel="stylesheet" href="/static/holdings.css"></head><body>
            <p style="text-align:center;color:#aeb9cc;font:12px system-ui;padding:12px">ЛОКАЛЬНОЕ ДЕМО · Все работники и деньги тестовые</p>
            <main id="app"></main><script src="/static/holdings.js"></script><script>
            const api=async(url,body)=>{const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(!r.ok)throw Error(j.error||'Ошибка');return j};
            HoldingsApp.open({app:document.querySelector('#app'),api,onArena:()=>{},chat:-100}).then(()=>document.querySelector('[data-h="tab:trader"]')?.click());
            </script></body></html>''',content_type='text/html')

    app.router.add_get('/trader-review',review)
    async def cleanup(app):
        await db.close();temp.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8126)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
