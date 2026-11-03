"""Adult fictional workers; no Telegram identity or arena progression is created."""
import random
from copy import deepcopy

HOUR=3600
DAY=86400
PROFESSIONS={
 'accountant':dict(name='Гоблин-счетовод',work='custom',icon='📒',price=1500,upkeep=12,trait='audit',
    text='Конец света не освобождает от декларации. На своём предприятии эффективнее; помогает вести любое хозяйство.'),
 'skeleton':dict(name='Скелет трудового резерва',work='field',icon='💀',price=1300,upkeep=10,trait='undead',
    text='Работа до гроба оказалась только испытательным сроком. Вместо еды требуется обслуживание магической связи.'),
 'paladin':dict(name='Бывший паладин',work='mine',icon='🛡️',price=1600,upkeep=18,trait='guard',
    text='Охраняет коллег и хорошо ходит в экспедиции. Латы заложил, чувство долга почему-то не приняли.'),
 'diplomat':dict(name='Бархатный дипломат',work='tavern',icon='🌹',price=900,upkeep=14,trait='diplomat',
    text='Только взрослый NPC. На переговорах исчезают границы приличия, а не сотрудники предприятия.'),
 'miner':dict(name='Шахтёр-долгожитель',work='mine',icon='⛏️',price=1500,upkeep=16,trait='veteran',
    text='Знает, какой свет в конце тоннеля точно не стоит проверять. Особенно полезен в шахте.'),
 'mechanic':dict(name='Механик последней смены',work='workshop',icon='🔧',price=2100,upkeep=18,trait='artisan',
    text='Вскрытие показало: механизм умер от переработки. К счастью, инструменты были ещё тёплыми.'),
}
RARITIES={'common':dict(name='Обычный',bonus=0,color='#a5b3c6'),
 'uncommon':dict(name='Необычный',bonus=10,color='#8ac9ad'),'rare':dict(name='Редкий',bonus=25,color='#8ab9eb'),
 'epic':dict(name='Эпический',bonus=45,color='#bc9de2'),'legendary':dict(name='Легендарный',bonus=70,color='#edc879')}
NAMES=('Борис','Гримм','Феликс','Вальтер','Лазарь','Мартин','Роберт','Северин','Гектор','Фома','Виктор','Альберт')
FEMALE_NAMES=('Агата','Фрида','Эльза','Марта','Грета','Ада','Лидия','Вера','Рада','Инга','Тесса','Мария')
FEMALE_PROFESSIONS={'accountant':'Гоблинка-счетовод','skeleton':'Скелет работницы',
 'paladin':'Бывшая паладинша','diplomat':'Бархатная дипломатка',
 'miner':'Шахтёрка-ветеран','mechanic':'Мастерица последней смены'}
SPRITE_ROOT='/static/assets/npc-workers-v1/'
TRAITS={'audit':'Выработка везде +5%.','undead':'Не нуждается в пище; обслуживание всё равно оплачивается.',
 'guard':'Защищает от похищений, если здоров и не отсутствует. Побеги из-за плохих условий не предотвращает.',
 'diplomat':'Снижает риск происшествия на одну ступень; поисковая группа получает +10 п.п.',
 'veteran':'При подходящей работе медленнее устаёт.','artisan':'В мастерской дополнительно +10% выработки.'}


def appearance(d):
    """Canonical asset IDs only; old workers keep the male appearance permanently."""
    profession=d['profession']
    if profession not in PROFESSIONS:raise ValueError('Неизвестная профессия NPC.')
    gender=d.get('gender','male')
    if gender not in ('male','female'):gender='male'
    return gender,profession+'-'+gender


def create(profession,rng=None,*,gender=None):
    rng=rng or random.SystemRandom();definition=PROFESSIONS[profession]
    if gender is None:gender=rng.choice(('male','female'))
    if gender not in ('male','female'):raise ValueError('Некорректный образ NPC.')
    rarity=rng.choices(list(RARITIES),weights=[50,28,15,6,1],k=1)[0]
    title=FEMALE_PROFESSIONS[profession] if gender=='female' else definition['name']
    return dict(name=rng.choice(FEMALE_NAMES if gender=='female' else NAMES)+' · '+title,
        gender=gender,appearance=profession+'-'+gender,profession=profession,rarity=rarity,
        trait=definition['trait'],age=rng.randint(25,68),level=3,experience=0,profession_level=1,
        health=100,fatigue=0,loyalty=75,unpaid=0,appraised=False,remainder=0,cost_remainder=0,
        training=None,ready_at=0,history=[])


def power(d):
    return round((20+d['level']*4+RARITIES[d['rarity']]['bonus']*.25+(10 if d['profession']=='paladin' else 0))*d['health']/100,1)


def efficiency(d,kind):
    bonus=RARITIES[d['rarity']]['bonus']+2*(d['profession_level']-1)
    if PROFESSIONS[d['profession']]['work']==kind:bonus+=30
    if d['trait']=='audit':bonus+=5
    if d['trait']=='artisan' and kind=='workshop':bonus+=10
    return .75*(1+bonus/100)*(1 if d['fatigue']<70 else .7)*d['health']/100


def public(row):
    d=deepcopy(row['data']);definition=PROFESSIONS[d['profession']]
    gender,key=appearance(d)
    d.update(gender=gender,appearance=key,sprite_url=SPRITE_ROOT+key+'.png',thumbnail_url=SPRITE_ROOT+key+'-small.png',
        id=row['id'],status=row['status'],site=row['site'],revision=row['revision'],
        profession_name=FEMALE_PROFESSIONS[d['profession']] if gender=='female' else definition['name'],
        icon=definition['icon'],description=definition['text'],trait_text=TRAITS[d['trait']],upkeep=definition['upkeep'],
        power=power(d),cost=row['price'])
    if d['appraised']:d['quality']=RARITIES[d['rarity']]
    else:
        d.pop('rarity');d['quality']=dict(name='Не оценён',color='#9baabd')
        d['power']=None
    for key in ('remainder','cost_remainder','unpaid'):d.pop(key,None)
    return d
