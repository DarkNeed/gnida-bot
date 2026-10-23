"""Casino review: disposable characters, real shared QTE engines, localhost only."""
import argparse
import hashlib
import hmac
import html
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode,quote
from aiohttp import web

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arena_web import create_arena_app,ROOT
from arena_assets import render_arena_index
from arena_engine import fighter_xp_limit
from arena_qte_unique import review_catalog
from database import Database

TOKEN='local-casino-review-no-production-credentials'


async def application():
    temporary=tempfile.TemporaryDirectory(prefix='gnida-casino-')
    db=Database(Path(temporary.name)/'casino.sqlite3');await db.connect()
    await db.upsert_chat(1,'Лудоман · проверка')
    for actor,branch,stage in ((10,'',10),(20,'casino_hustler',10),(30,'casino_lucky',10),(40,'casino_hustler',20),(50,'casino_lucky',20)):
        await db.upsert_user(1,actor,str(actor),'Испытатель '+str(actor))
        db._arena_profile_locked(1,actor,True)
        db._grant_profile_xp_locked('personal_profiles',1,actor,fighter_xp_limit())
        loadout=['casino_bet','casino_ace','casino_all_in','casino_house' if branch=='casino_hustler' else 'casino_deposit' if branch else 'casino_credit']
        db.connection.execute('''UPDATE personal_profiles SET class_id='gambler',archclass_id=?,archclass_stage=?,
            progression_level=20,progression_pending_level=0,loadout=?,skill_memory=NULL,skill_seen='[]' WHERE chat_id=0 AND user_id=?''',
            (branch,stage,json.dumps(loadout),actor))
        db._casino_row_locked(actor)
        db._arena_equip_class_passives_locked(1,actor,True,'gambler')
        db.connection.execute('UPDATE arena_casino_unlocks SET invited=1,unlocked=1 WHERE user_id=?',(actor,))
    db.connection.commit()
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member',user=SimpleNamespace(is_bot=False))))
    app=create_arena_app(db,bot,TOKEN)
    catalog=[s for s in review_catalog() if s['class_id']=='gambler']

    async def lab(request):
        mode='qte-block' if request.path.endswith('block') else 'qte-unique'
        text=(ROOT/mode/'index.html').read_text(encoding='utf-8')
        text=text.replace('data-example="warning_shot"','data-example="casino_bet"').replace('Залп Солдато','Ставка')
        text=text.replace('data-example="tigerslayer_flurry"','data-example="casino_all_in"').replace('Тигробой','Ва-банк')
        text=text.replace('data-example="kit_eclipse"','data-example="casino_deposit"').replace('Глаза Кита','777')
        rev=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in ('qte-unique/engine','qte-unique/client','qte-block/engine','qte-block/client','qte-casino-view','qte-view'))).hexdigest()[:16]
        text=text.replace('__REV__',rev).replace('__CATALOG__',json.dumps(catalog,ensure_ascii=False).replace('<','\\u003c'))
        return web.Response(text=text,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def preview(request):
        actor=int(request.query.get('actor',10))
        if actor not in (10,20,30,40,50):raise web.HTTPBadRequest()
        pairs=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=actor)))
        secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        pairs['hash']=hmac.new(secret,'\n'.join(k+'='+v for k,v in sorted(pairs.items())).encode(),hashlib.sha256).hexdigest()
        text=render_arena_index(ROOT).replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>',
            '<script>window.Telegram={WebApp:{initData:'+json.dumps(urlencode(pairs))+',initDataUnsafe:{},ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){}}};</script>')
        return web.Response(text=text,content_type='text/html',headers={'Cache-Control':'no-store'})

    async def index(request):
        gallery='<nav class="roster">'+''.join(f'<a target="game" href="/preview?tgWebAppStartParam=menu_1&amp;actor={actor}"><img src="/static/assets/casino/{key}.png" alt="{name}"><b>{name}</b></a>' for actor,key,name in (
            (10,'gambler','Лудоман'),(20,'casino_hustler','Шулер'),(30,'casino_lucky','Счастливчик'),
            (40,'casino_hustler_final','Хозяин казино'),(50,'casino_lucky_final','Избранник Фортуны')) )+'</nav>'
        chosen=[next(s for s in catalog if s['base_id']==sid and not s['name'].startswith('777')) for sid in ('casino_bet','casino_all_in','casino_deposit')]
        chosen.append(next(s for s in catalog if s['name'].startswith('777')))
        chosen.append(next(s for s in catalog if s['base_id']=='mastery_gambler'))
        rows=''
        for s,diff in zip(chosen,['Средняя','Сложная','Сложная','Очень сложная','Средняя / сложная']):
            from arena_casino_chance import mode
            query=quote(s['id']);attack_url=f'/qte-lab/casino/?skill={query}' if mode(s) else f'/casino-dodge?skill={query}&amp;mode=attack'
            rows+=f'<article><b>{html.escape(s["name"])}</b><span>{diff}</span><a target="game" href="{attack_url}">{"Случайный запуск" if mode(s) else "Попадание"}</a><a target="game" href="/casino-dodge?skill={query}">Уклонение</a><a target="game" href="/casino-block?skill={query}">Блок</a></article>'
        body='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Лудоман · тест казино</title>
<style>body{margin:0;background:#0b1516;color:#f1e5c4;font:15px system-ui}header{padding:20px;max-width:1100px;margin:auto}h1{margin:0;color:#efd08c}p{color:#aebdb5}a{color:#e6bd70}article{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:10px;border-bottom:1px solid #2e4038}article b{min-width:260px}article span{min-width:130px;color:#aaa}nav{display:flex;flex-wrap:wrap;gap:16px;margin:16px 0}.roster a{display:flex;flex:1 1 110px;flex-direction:column;align-items:center;text-decoration:none;background:#15201c;border:1px solid #3d4734;border-radius:12px;padding:12px;text-align:center}.roster img{width:100%;height:165px;object-fit:contain;margin-bottom:10px}iframe{display:block;border:1px solid #354839;border-radius:12px;width:calc(100% - 24px);height:820px;margin:10px auto;background:#0b1522}button{padding:8px;background:#263d33;border:1px solid #9c8250;color:#f0dba4;border-radius:8px}</style>
<header><h1>🎲 Заведение без выхода</h1><p>Лудоман → Шулер / Счастливчик → Хозяин казино / Избранник Фортуны. Временная база, без Telegram, доната и реальных ставок. Босс-казино пока не добавлен.</p>'''+gallery+'''
<details><summary>Кубики, фишки и открытие класса</summary><p>1–2: слабее удар и Невезение; 3–4: обычный; 5: усиленный; 6: джекпот. Три Невезения готовят гарантированную шестёрку. Туз выбирает лучший из двух бросков. Кредит возвращает 30 энергии, будущий реген погашает долг. Ва-банк может ранить самого Лудомана.</p><p>Шулер перебрасывает плохой результат и сохраняет бросок. Счастливчик усиливает джекпоты и расходует Невезение на защиту. Три джекпота и семь боевых фишек готовят 777. Открытие: выигрыш ×5 в /депнуть → бесплатное испытание у торговца → класс для всех слотов.</p></details>
<p>Для сравнения: уклонение 0 / точность врага 100, затем уклонение 30. Блок: броня 35 / атака 30, затем броня 0. Не двигаться и держать щит весь раунд не должно быть надёжной стратегией.</p>'''+rows+'''
<nav><a target="game" href="/preview?tgWebAppStartParam=menu_1&amp;actor=10">Лудоман · билд</a><a target="game" href="/preview?tgWebAppStartParam=menu_1&amp;actor=20">Шулер</a><a target="game" href="/preview?tgWebAppStartParam=menu_1&amp;actor=30">Счастливчик</a><a target="game" href="/preview?tgWebAppStartParam=menu_1&amp;actor=40">Хозяин казино</a><a target="game" href="/preview?tgWebAppStartParam=menu_1&amp;actor=50">Избранник Фортуны</a><button onclick="document.querySelector('iframe').style.width='390px'">Телефон 390px</button><button onclick="document.querySelector('iframe').style.width='calc(100% - 24px)'">ПК</button></nav><p>Заметки после теста: навык / уклонение или блок / характеристики / слишком легко или трудно / что мешает. Удар: одна попытка на отметку, перед атакой есть подготовка.</p></header><iframe name="game" title="Лудоман · игровой тест" src="/casino-dodge?skill=casino_bet"></iframe></html>'''
        body=body.replace('Удар: одна попытка на отметку, перед атакой есть подготовка.',
            'Ва-банк / 777 / Проверка вероятности: случайный запуск без тайминга. Остальные попадания: одна попытка на удар.')
        return web.Response(text=body,content_type='text/html')

    app.router.add_get('/casino-review',index)
    app.router.add_get('/casino-dodge',lab)
    app.router.add_get('/casino-block',lab)
    app.router.add_get('/preview',preview)
    async def cleanup(_):await db.close();temporary.cleanup()
    app.on_cleanup.append(cleanup)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8125)
    web.run_app(application(),host='127.0.0.1',port=parser.parse_args().port)
