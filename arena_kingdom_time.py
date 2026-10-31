"""Server-clock map lighting and bounded, non-monetary day/night encounters."""
from datetime import datetime,timezone,timedelta
import hashlib

MSK=timezone(timedelta(hours=3))
HOUR=3600
EVENTS={
    'caravan':dict(name='Караван без страховки',period='day',icon='cart',
        text='Караванщики потеряли колесо и веру в дорожный сбор. Помоги разгрузить телегу: страховщик всё равно записал бы нападение дракона как «естественный износ».',
        result='Колесо нашли под казначеем. Караван оставил строительные припасы.',grant=dict(wood=60,stone=30)),
    'market':dict(name='Ярмарка сомнительной свежести',period='day',icon='sun',
        text='Торговец клянётся, что мясо ещё вчера бегало. Некромант рядом подозрительно кивает. Стража проверила хотя бы хлеб.',
        result='Поселение забрало проверенные припасы. Некроманту велели не оживлять колбасу.',grant=dict(food=75)),
    'lanterns':dict(name='Смена при свечах',period='night',icon='moon',
        text='Скелеты нашли заброшенный склад и требуют доплату за ночные. Предлагают забрать материалы, пока юрист не вспомнил, что умер первым.',
        result='Материалы вывезены. Ночные доплаты внесли в протокол следующей жизни.',grant=dict(wood=45,stone=45)),
    'velvet_watch':dict(name='Бархатный ночной дозор',period='night',icon='star',
        text='Взрослые агенты поймали контрабандистов. У задержанных были запрещённые книги, провизия и чулки. Книги забрал цензор, чулки — командир дозора.',
        result='Провизию передали поселению. Допрос задержанных продлился до неприличного утра.',grant=dict(food=60,wood=20)),
}


def environment(now):
    local=datetime.fromtimestamp(now,MSK);hour=local.hour+local.minute/60
    day=6<=hour<20
    phase='dawn' if 6<=hour<8 else 'day' if 8<=hour<18 else 'dusk' if 18<=hour<20 else 'night'
    start=local.replace(hour=6 if day else 20,minute=0,second=0,microsecond=0)
    if not day and hour<6:start-=timedelta(days=1)
    end=start+timedelta(hours=14 if day else 10)
    return dict(phase=phase,period='day' if day else 'night',
        name=dict(dawn='Рассвет',day='День',dusk='Закат',night='Ночь')[phase],
        clock=local.strftime('%H:%M'),timezone='МСК',window=int(start.timestamp()),ends=int(end.timestamp()))


def encounters(seed,now,tiles):
    env=environment(now)
    eligible=[t for t in tiles if not t['town'] and not t['site'] and t['terrain']!='river']
    used=set();result=[]
    for key,definition in EVENTS.items():
        if definition['period']!=env['period']:continue
        ordered=sorted(eligible,key=lambda t:hashlib.sha256(f"{seed}:{env['window']}:{key}:{t['q']}:{t['r']}".encode()).digest())
        tile=next((t for t in ordered if (t['q'],t['r']) not in used),None)
        if tile is None:continue
        used.add((tile['q'],tile['r']))
        result.append(dict(id=f"{env['window']}:{key}",key=key,q=tile['q'],r=tile['r'],
                           ends=env['ends'],**definition))
    return result


def visit(db,row,world,payload,now):
    from arena_kingdom_rules import WIDTH,HEIGHT,SITES,terrain,capacity
    claims={(r['q'],r['r']):r['town'] for r in db.connection.execute('SELECT q,r,town FROM kingdom_tiles WHERE chat=?',(row['chat'],))}
    ident=payload.get('event');tiles=[dict(q=q,r=r,town=claims.get((q,r)),site=SITES.get((q,r)),terrain=terrain(world['seed'],q,r))
                                    for r in range(HEIGHT) for q in range(WIDTH)]
    event=next((e for e in encounters(world['seed'],now,tiles) if e['id']==ident),None)
    if not event:raise ValueError('Эта временная встреча уже исчезла. Обнови карту: день и ночь меняют события.')
    visits=row['data'].setdefault('timed_visits',{})
    if ident in visits:raise ValueError('Твоё поселение уже посетило эту встречу в текущем цикле.')
    gains={}
    for key,amount in event['grant'].items():
        before=row['data']['resources'][key]
        row['data']['resources'][key]=min(capacity(row['data']),before+amount)
        gains[key]=row['data']['resources'][key]-before
    row['data']['timed_visits']={key:at for key,at in visits.items() if at>now-2*24*HOUR}
    row['data']['timed_visits'][ident]=now
    db._kingdom_log(row,event['name']+': '+event['result'],now)
    return event['result']+' Получено: '+', '.join(str(v)+' '+dict(food='пищи',wood='древесины',stone='камня')[k] for k,v in gains.items())+'.'
