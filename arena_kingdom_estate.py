"""Cosmetic land identity and bounded, municipal-only landmark projects."""
from copy import deepcopy
import re

from arena_kingdom_rules import HOUR

STYLES={'frontier':'Пограничье','gothic':'Мрачное королевство','holy':'Священная держава',
        'grave':'Некрополь','velvet':'Бархатное княжество','scrap':'Империя трущоб'}
EMBLEMS={'crown':'Корона','moon':'Луна','sun':'Солнце','skull':'Череп','rose':'Роза','tower':'Башня'}
DECORATIONS={'none':'Без украшения','lanterns':'Фонари','garden':'Сад','statue':'Статуя','cemetery':'Кладбище','road':'Мощёная дорога'}
SPECIALS={
 'academy':dict(name='Военная академия',price=120000,wood=350,stone=400,hours=72,upkeep=120,
                text='Пехота армии: +8% урона и +2 брони. Бонус фиксируется при отправлении армии.'),
 'caravan':dict(name='Караванный двор',price=90000,wood=400,stone=220,hours=48,upkeep=80,
                text='Снабжение походов дешевле на 15%; припасы за набеги на живые лагеря +20%.'),
 'watchtower':dict(name='Разведывательная башня',price=80000,wood=250,stone=350,hours=48,upkeep=80,
                text='Вдвое уменьшает потери припасов и порядка от соседних живых лагерей. Показывает разведсводку лагерей.'),
 'temple':dict(name='Великий храм',price=150000,wood=300,stone=500,hours=96,upkeep=150,
                text='Лечение армии +20%, святым отрядам +10% HP. Собственные религии — следующий этап, пока храм усиливает войска.'),
 'siegeworks':dict(name='Осадная мастерская',price=180000,wood=500,stone=450,hours=96,upkeep=180,
                text='Победный набег разрушает 35% исходной прочности лагеря вместо 25%. На захват земель игроков пока не влияет.'),
 'wonder':dict(name='Чудо государства',price=600000,wood=800,stone=1000,hours=168,upkeep=300,trophies=4,stage=3,
                text='Всей армии +8% HP и особый силуэт столицы. Нужны 4 трофея разрушенных лагерей и этап столицы.'),
}


def initialize(d):
    return d.setdefault('estate',dict(style='frontier',color='#91b9bc',emblem='crown',tiles={},specials=[],job=None,trophies=0))


def capacity(d):return {1:0,2:2,3:3}[d['stage']]


def has(d,key):return key in initialize(d)['specials']


def upkeep(d):return sum(SPECIALS[k]['upkeep'] for k in initialize(d)['specials'])


def buffs(d,team):
    e=initialize(d)
    for unit in team:
        if 'academy' in e['specials'] and 'infantry' in unit['tags']:
            unit['attack']*=1.08;unit['armor']+=2
        if 'temple' in e['specials']:unit['heal']*=1.2
        hp=(1.1 if 'temple' in e['specials'] and 'holy' in unit['tags'] else 1)*(1.08 if 'wonder' in e['specials'] else 1)
        ratio=unit['hp']/unit['max_hp'];unit['max_hp']=round(unit['max_hp']*hp);unit['hp']=max(1,round(unit['max_hp']*ratio))
    return team


def advance(row,now):
    e=initialize(row['data']);job=e['job']
    if job and job['finish']<=now:
        if job['kind']=='build':e['specials'].append(job['special'])
        else:e['specials'].remove(job['special'])
        e['job']=None
        return ('Завершено строительство: ' if job['kind']=='build' else 'Разобрано без возврата затрат: ')+SPECIALS[job['special']]['name']+'.'


def public(d,owned,own):
    e=deepcopy(initialize(d));e['tiles']={k:v for k,v in e['tiles'].items() if k in owned}
    if not own:
        return {k:e[k] for k in ('style','color','emblem','tiles','specials')}
    e.update(capacity=capacity(d),styles=STYLES,emblems=EMBLEMS,decorations=DECORATIONS,catalog=SPECIALS)
    return e


def text(value,limit,label,minimum=0):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=limit:raise ValueError(label)
    return value.strip()


def action(db,row,command,payload,now):
    d=row['data'];e=initialize(d)
    if command=='land_style':
        style=payload.get('style');emblem=payload.get('emblem');color=payload.get('color')
        if not isinstance(style,str) or style not in STYLES or not isinstance(emblem,str) or emblem not in EMBLEMS or not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):
            raise ValueError('Выбери оформление, символ и цвет из редактора.')
        e.update(style=style,color=color.lower(),emblem=emblem)
        return 'Герб и оформление владения сохранены. Характеристики местности не изменились.'
    if command=='land_decor':
        from arena_kingdom_rules import coordinates
        q,r=coordinates(payload.get('q'),payload.get('r'))
        if not db.connection.execute('SELECT 1 FROM kingdom_tiles WHERE chat=? AND town=? AND q=? AND r=?',(row['chat'],row['id'],q,r)).fetchone():
            raise ValueError('Можно оформлять только свою землю.')
        decor=payload.get('decoration')
        if not isinstance(decor,str) or decor not in DECORATIONS:raise ValueError('Неизвестное украшение.')
        name=text(payload.get('name',''),32,'Название области — до 32 символов.')
        description=text(payload.get('description',''),180,'Описание области — до 180 символов.')
        e['tiles'][f'{q}:{r}']=dict(name=name,description=description,decoration=decor)
        return 'Область оформлена. Это косметика, без изменения производства и защиты.'
    key=payload.get('special')
    if not isinstance(key,str) or key not in SPECIALS:raise ValueError('Неизвестная особая постройка.')
    if e['job'] or d['construction']:raise ValueError('Общая строительная очередь занята.')
    definition=SPECIALS[key]
    if command=='special_remove':
        if key not in e['specials']:raise ValueError('Эта постройка не возведена.')
        if d['military']['campaign'] or d['military'].get('siege_lock'):raise ValueError('Дождись возвращения армии и завершения осады.')
        e['job']=dict(kind='remove',special=key,started=now,finish=now+24*HOUR)
        return 'Начат снос: сутки. До конца работ бонус сохраняется; возврата средств и трофеев нет.'
    if d['stage']<definition.get('stage',2):raise ValueError('Для особой постройки нужен город, для чуда — столица.')
    if key in e['specials']:raise ValueError('Такая особая постройка уже есть.')
    if len(e['specials'])>=capacity(d):raise ValueError('Все места особых построек заняты. Город: 2, столица: 3.')
    if e['trophies']<definition.get('trophies',0):raise ValueError('Не хватает трофеев разрушенных лагерей.')
    for resource in ('wood','stone'):
        if d['resources'][resource]<definition[resource]:raise ValueError('Не хватает строительных запасов.')
    from arena_kingdom_finance import spend
    spend(db,row,definition['price'])
    for resource in ('wood','stone'):d['resources'][resource]-=definition[resource]
    e['trophies']-=definition.get('trophies',0)
    e['job']=dict(kind='build',special=key,started=now,finish=now+definition['hours']*HOUR)
    return 'Заложена особая постройка: '+definition['name']+'. Платного ускорения нет.'
