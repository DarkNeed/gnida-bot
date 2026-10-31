"""Explicit settlement reforms. Never grants arena power or purchasable time."""
from copy import deepcopy
import math

HOUR=3600
POLICIES={
    'balanced':dict(name='Совет равновесия',text='Без усилений и штрафов. Спокойное развитие без военной специализации.'),
    'military':dict(name='Военная держава',text='Войска: +10% урона и +2 брони. Походное снабжение +30%; производство дерева и камня −10%.'),
    'trade':dict(name='Торговая республика',text='Дерево и камень +20%, найм войск дешевле на 10%. Урон армии −10%.'),
    'communal':dict(name='Народное собрание',text='Житель за 4 часа вместо 6. Городская стража в обороне получает +20% HP; производство пищи −10%.'),
    'intrigue':dict(name='Тайная канцелярия',text='Бархатные агенты: +8 уклонения и +2 скорости. Производство камня −10%; походное снабжение +10%.'),
}
RELIGIONS={
    'none':dict(name='Светский договор',text='Свобода совести без усилений и штрафов. Никаких требований к вере игрока.'),
    'light':dict(name='Культ Последнего Света',text='Лечение армии +20%, святым отрядам +10% HP. Найм нежити и некромантов дороже на 30%.'),
    'ancestors':dict(name='Культ Предков',text='Пехоте +4 брони, но −1 скорости. Живые и мёртвые предки спорят, кто первым занял ваш трон.'),
    'void':dict(name='Завет Пустоты',text='Магам и некромантам +15% урона. Лечение армии слабее на 15%.'),
    'fortune':dict(name='Храм Слепой Фортуны',text='Всем войскам +5 уклонения. Шанс удара с +30% урона — 8%; походное снабжение дороже на 10%.'),
}


def initialize(d):
    return d.setdefault('government',dict(policy='balanced',religion='none',pending=None,next_change_at=0))


def growth_hours(d):
    return 4 if initialize(d)['policy']=='communal' else 6


def production(d, values):
    p=initialize(d)['policy'];result=dict(values)
    for key in result:
        multiplier=1
        if p=='military' and key in ('wood','stone'):multiplier=.9
        if p=='trade' and key in ('wood','stone'):multiplier=1.2
        if p=='communal' and key=='food':multiplier=.9
        if p=='intrigue' and key=='stone':multiplier=.9
        result[key]=math.floor(result[key]*multiplier)
    return result


def recruit_terms(d, definition):
    g=initialize(d);result=deepcopy(definition);percent=90 if g['policy']=='trade' else 100
    faith=130 if g['religion']=='light' and any(t in definition['tags'] for t in ('undead','necro')) else 100
    # Integer percentages avoid charging an extra franc from float rounding.
    result['price']=(definition['price']*percent*faith+9999)//10000
    return result


def supplies(d, count):
    g=initialize(d);multiplier={'military':1.3,'intrigue':1.1}.get(g['policy'],1)
    if g['religion']=='fortune':multiplier*=1.1
    return math.ceil((25+30*count)*multiplier)


def buff(d, fighters, *, guard=False):
    g=initialize(d)
    for u in fighters:
        ratio=u['hp']/u['max_hp'];hp=1
        if g['policy']=='military':u['attack']*=1.1;u['armor']+=2
        if g['policy']=='trade':u['attack']*=.9
        if g['policy']=='intrigue' and u['kind']=='agents':u['evasion']+=8;u['speed']+=2
        if g['policy']=='communal' and guard:hp*=1.2
        if g['religion']=='light':
            u['heal']*=1.2
            if 'holy' in u['tags']:hp*=1.1
        if g['religion']=='ancestors' and 'infantry' in u['tags']:u['armor']+=4;u['speed']=max(1,u['speed']-1)
        if g['religion']=='void':
            u['heal']*=.85
            if 'mage' in u['tags'] or 'necro' in u['tags']:u['attack']*=1.15
        if g['religion']=='fortune':u['evasion']+=5;u['fortune']=True
        u['evasion']=min(35,u['evasion']);u['max_hp']=round(u['max_hp']*hp);u['hp']=max(1,round(u['max_hp']*ratio))
    return fighters


def advance(d, now):
    g=initialize(d);pending=g['pending']
    if not pending or pending['finish']>now:return None
    old_interval=growth_hours(d)
    g[pending['field']]=pending['choice'];g['next_change_at']=pending['finish']+7*24*HOUR;g['pending']=None
    d['growth_hours']=math.floor(d.get('growth_hours',0)/old_interval*growth_hours(d))
    return (POLICIES if pending['field']=='policy' else RELIGIONS)[pending['choice']]['name']


def view(d,now):
    g=deepcopy(initialize(d));g.update(policies=POLICIES,religions=RELIGIONS,policy_price=25000,religion_price=40000,
                                   reform_hours=24,can_change=not g['pending'] and g['next_change_at']<=now)
    return g


def reform(db,row,payload,now):
    d=row['data'];g=initialize(d);field=payload.get('field');choice=payload.get('choice')
    if field not in ('policy','religion') or not isinstance(choice,str):raise ValueError('Выбери политический курс или верование.')
    catalog=POLICIES if field=='policy' else RELIGIONS
    if choice not in catalog or choice==g[field]:raise ValueError('Выбери другой доступный путь.')
    if g['pending'] or g['next_change_at']>now:raise ValueError('Реформа уже идёт или ещё действует недельное ограничение.')
    if d.get('military',{}).get('siege_lock'):raise ValueError('Реформы во время осады запрещены.')
    price=25000 if field=='policy' else 40000
    from arena_kingdom_finance import spend
    spend(db,row,price)
    g['pending']=dict(field=field,choice=choice,started=now,finish=now+24*HOUR)
    return 'Начата реформа: '+catalog[choice]['name']+'. До завершения действуют прежние правила.'
