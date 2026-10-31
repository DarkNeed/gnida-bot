"""First settlement season: a fixed chat world, six buildings and bounded incidents."""
import hashlib
import math

WIDTH, HEIGHT = 15, 11
FOUND_PRICE = 20000
HOUR = 3600
DAY = 24 * HOUR
BUILD_HOURS = {1: 6, 2: 24, 3: 72, 4: 168}
EVENT_SECONDS = 24 * HOUR
EVENT_INTERVAL = 18 * HOUR
BOUNTY = 5000
STAGES = {
    1: dict(name='Деревня', lands=3, building_cap=2),
    2: dict(name='Город', lands=5, building_cap=3, price=250000, age_days=14,
            population=50, hall=2, building_types=4, prestige=6, rank=5, level=20),
    3: dict(name='Столица', lands=7, building_cap=4, price=1500000, age_days=35,
            population=75, hall=3, building_types=6, prestige=18, rank=6, level=20),
}
FACTIONS = {
    'heating': dict(name='Союз свободных теплотрасс', motto='Ни господ, ни прописки. Только тёплая труба.'),
    'velvet': dict(name='Бархатный двор', motto='Наши чулки крепче ваших политических убеждений.'),
    'light': dict(name='Орден святой отчётности', motto='Свет всё видит. Особенно неоплаченные счета.'),
    'grave': dict(name='Посмертный профсоюз', motto='Рабочая смена не заканчивается смертью.'),
}
# These junctions and NPC estates stay neutral, regardless of wealth or rank.
NEUTRAL_LANDS = {(2,5), (5,5), (8,5), (10,5), (13,5)}
TERRAINS = {
    'plain': dict(name='Равнина', resource='food', bonus=3, color='#456052', buildable=True),
    'forest': dict(name='Чёрный лес', resource='wood', bonus=3, color='#2c4944', buildable=True),
    'hills': dict(name='Каменные холмы', resource='stone', bonus=3, color='#5d5960', buildable=True),
    'river': dict(name='Река Тихая', resource=None, bonus=0, color='#264f66', buildable=False),
    'road': dict(name='Старый тракт', resource='food', bonus=1, color='#776950', buildable=True),
}
BUILDINGS = {
    'hall': dict(name='Ратуша', price=12000, wood=80, stone=90, text='Место для жителей, рост населения и управление городом.', icon='hall'),
    'farm': dict(name='Фермы', price=3500, wood=60, stone=25, text='+32 продовольствия в час за уровень. Жители расходуют пищу.', icon='farm'),
    'sawmill': dict(name='Лесопилка', price=5000, wood=45, stone=40, text='+18 древесины в час за уровень.', icon='sawmill'),
    'quarry': dict(name='Каменоломня', price=6000, wood=70, stone=35, text='+15 камня в час за уровень.', icon='quarry'),
    'barracks': dict(name='Казармы', price=9000, wood=65, stone=80, text='+15 силы гарнизона за уровень. Защита без участия героя.', icon='barracks'),
    'warehouse': dict(name='Амбары', price=4500, wood=80, stone=40, text='+500 к вместимости каждого запаса за уровень. Помогают при бедствиях.', icon='warehouse'),
}
SITES = {
    (1, 3): dict(kind='war', target='road_camp', name='Диванная баррикада', rank='I', text='Мятежная свора перекрыла тракт. Цель для армии поселения, не рейд героя.'),
    (9, 2): dict(kind='war', target='velvet_spies', name='Школа бархатных интриг', rank='II', text='Отступники Бархатного двора испытывают диверсантов на всех, кому не повезло жить рядом.'),
    (12, 4): dict(kind='war', target='tithe_fort', name='Форт последней десятины', rank='III', text='Укрепление раскольников ордена. Гарнизон прикрывают жрецы и стрелки.'),
    (8, 9): dict(kind='war', target='bone_foundry', name='Фабрика вечной смены', rank='IV', text='Некроманты-штрейкбрехеры отказываются отпускать работников даже после смерти.'),
    (1, 2): dict(kind='guild', target='f_dungeon', name='Гоблинские копи', rank='F', text='Гоблины уже подали заявление на право собственности. Подпись — отпечаток сапога.'),
    (6, 1): dict(kind='guild', target='c_dungeon', name='Проклятый склеп', rank='C', text='Мёртвые не платят аренду. Гильдия считает это возмутительным.'),
    (12, 8): dict(kind='guild', target='s_dungeon', name='Пепельная кальдера', rank='S', text='Местная недвижимость горячая. Страховщики сюда не ходят.'),
    (12, 2): dict(kind='boss', target='whaler', name='Чумные болота', rank='Рейд', text='Китобой принимает гостей. Обратно лучше дышать через раз.'),
    (7, 8): dict(kind='boss', target='chaplain', name='Часовня Капеллана', rank='Рейд', text='Здесь даже опоздание можно сделать вечным.'),
    (2, 8): dict(kind='faction', target='heating', name='Вольная теплотрасса', rank='Фракция', text='Лагерь, где право на трон передают вместе с самым сухим матрасом.'),
    (10, 1): dict(kind='faction', target='velvet', name='Бархатная усадьба', rank='Фракция', text='Посольство фембоев. Дресс-код строже законов, декольте глубже государственного долга.'),
    (13, 6): dict(kind='faction', target='light', name='Обитель последней квитанции', rank='Фракция', text='Паладины охраняют вход. Жрецы — кассу. Спасение души оплачивается отдельно.'),
    (9, 9): dict(kind='faction', target='grave', name='Башня ночной смены', rank='Фракция', text='Здесь скелеты подают жалобы на условия загробного труда.'),
}
INCIDENTS = {
    'bandits': dict(name='Союз свободных теплотрасс', type='Налёт своры бомжей', faction='heating', weight=24,
        text='Свора бомжей объявила амбары исторической родиной. Вожак требует хлеба, права на ночлег и объяснить, чем ваш трон лучше его дивана.',
        threat=26, choices=[dict(id='pay', name='Откупиться', francs=2500, text='Бандиты уходят. Финансовая грамотность победила физическую.'),
                           dict(id='garrison', name='Выслать гарнизон', favor=-1, text='Стража вернула амбары. Диван вожака объявлен осадным орудием.'),
                           dict(id='shelter', name='Отдать пустую сторожку', food=120, wood=80, favor=2, followup='heating_union', text='Бездомные получили крышу. Казначей впервые услышал выражение «крышевание» в положительном смысле.')]),
    'velvet_coup': dict(name='Бархатный переворот', type='Интрига фембоев', faction='velvet', weight=24,
        text='Делегация фембоев заняла совет. Все участники взрослые, в отличие от политических решений казначея: он подписал передачу амбаров, увидев подвязку.', threat=0,
        choices=[dict(id='audit', name='Проверить печати, не чулки', francs=4000, favor=-1, text='Поддельные указы сожжены. Казначею выдали очки с цензурой.'),
                 dict(id='envoy', name='Признать бархатного советника', wood=80, stone=40, favor=2, followup='velvet_embassy', text='Советник занял кабинет. Впервые интриги плетут из материала дороже мешковины.')]),
    'holy_audit': dict(name='Святая инвентаризация', type='Орден святой отчётности', faction='light', weight=18,
        text='Жрец уверяет, что недостающие франки вознеслись. Паладин просит оплатить лестницу. Доходы небес растут быстрее ваших.', threat=0,
        choices=[dict(id='court', name='Созвать земной суд', francs=3500, favor=-1, text='Чудо объяснилось двойной бухгалтерией. Оправдание «бес попутал» принято как признание соучастника.'),
                 dict(id='mission', name='Отправить их служить жителям', food=100, wood=60, favor=2, followup='light_hospital', text='Жрец и паладин отправились помогать бедным. Для обоих это оказалось новым игровым режимом.')]),
    'dead_shift': dict(name='Мёртвые души сверхурочно', type='Посмертный профсоюз', faction='grave', weight=18,
        text='Некромант предлагает работников без зарплаты. Скелеты тут же требуют отпуск, страховку и прекратить называть пересборку костей корпоративным массажем.', threat=0,
        choices=[dict(id='dismiss', name='Оплатить достойное упокоение', francs=4500, favor=-1, text='Коллектив отправлен на кладбище. Кадровик отметил: текучка персонала наконец прекратилась.'),
                 dict(id='charter', name='Подписать загробный трудовой устав', stone=100, wood=60, favor=2, followup='grave_charter', text='Устав подписан. Впервые в истории покойникам гарантировали не только вечный покой, но и обеденный перерыв.')]),
    'night_diplomacy': dict(name='Ночная дипломатия', type='Приём Бархатного двора', faction='velvet', weight=12,
        text='Взрослые послы требуют переговоров без доспехов. Стража подозревает засаду, придворные — наконец-то нормальный рабочий вечер. Казначей уже снял бюджет.', threat=0,
        choices=[dict(id='formal', name='Устроить официальный приём', food=100, favor=1, text='Договор подписан при свидетелях. Под столом обнаружили только собаку и репутацию министра.'),
                 dict(id='banquet', name='Оплатить закрытый банкет', francs=6000, favor=2, followup='velvet_embassy', text='Дипломаты довольны. Подробности засекретили; счёт оказался непристойнее вечера.')]),
    'heating_union': dict(name='Прописка для дивана', type='Продолжение · теплотрассы', faction='heating', weight=0,
        text='Новые жильцы сторожки поймали вора. Теперь просят инструменты: по их словам, честная работа ужасно мешает спать, но дом есть дом.', threat=0,
        choices=[dict(id='tools', name='Выдать инструменты', wood=100, favor=2, grant=dict(wood=60), text='Сторожка стала мастерской. Из старых дверей принесли 60 древесины. Над происхождением дверей решили не размышлять.'),
                 dict(id='wages', name='Оплатить общественные работы', francs=5000, favor=1, text='Тракт очищен. Поиски смысла жизни временно заменены поисками метлы.')]),
    'velvet_embassy': dict(name='Чулочная неприкосновенность', type='Продолжение · Бархатный двор', faction='velvet', weight=0,
        text='Советник нашёл настоящего шпиона. Шпион просит обменять его на чиновника: в этом городе даже пытки скучнее совещаний.', threat=0,
        choices=[dict(id='exchange', name='Провести обмен пленными NPC', food=100, favor=2, text='Обмен завершён. Советник вернулся с картами дорог; чиновник обратно не просился.'),
                 dict(id='papers', name='Выкупить секретные документы', francs=6500, favor=1, grant=dict(stone=80), text='Среди бумаг обнаружены складские расписки на 80 камня. Любовные письма министра сданы в архив компромата.')]),
    'light_hospital': dict(name='Палата имени налогоплательщика', type='Продолжение · орден', faction='light', weight=0,
        text='Бывшие сборщики пожертвований открыли лечебницу. Лечат молитвой, травами и неприятным осознанием, сколько стоил бы частный жрец.', threat=0,
        choices=[dict(id='medicine', name='Снабдить лечебницу', food=120, wood=80, favor=2, text='Больные поправились. Паладин научился отличать перевязку от захвата заложника.'),
                 dict(id='fund', name='Учредить городской фонд', francs=7000, favor=1, text='Фонд работает. Чудо произошло: у денег появился проверяемый маршрут.')]),
    'grave_charter': dict(name='Забастовка по ту сторону', type='Продолжение · профсоюз', faction='grave', weight=0,
        text='Скелеты требуют тёплую спецодежду. Некромант недоумевает: кожи нет, а мурашки от условий труда остались.', threat=0,
        choices=[dict(id='workshop', name='Открыть костяную мастерскую', wood=120, favor=2, grant=dict(stone=90), text='Мастерская разобрала заброшенный склеп: +90 камня. Заказчик отметил, что жильцы и так работают здесь.'),
                 dict(id='settle', name='Заключить коллективный договор', francs=5500, favor=1, text='Коллектив вернулся к работе. Выходные записаны на надгробиях, чтобы начальство не забыло.')]),
    'fire': dict(name='Огонь в хлебном квартале', type='Редкое бытовое событие', weight=2,
        text='Пекарь изобрёл хлеб с огнём внутри. Квартал оценил инновацию первым.', threat=0,
        choices=[dict(id='bucket', name='Созвать жителей', food=70, wood=40, text='Цепочка вёдер спасла дома. Пекаря перевели на холодную кухню.'),
                 dict(id='pay', name='Нанять пожарную артель', francs=3000, text='Артель прибыла раньше счёта. Дома спасены.')]),
    'blight': dict(name='Урожай с характером', type='Редкое бытовое событие', weight=2,
        text='Колосья легли, агроном тоже. Последний уверяет, что это часть севооборота.', threat=0,
        choices=[dict(id='reserve', name='Открыть резервы амбаров', food=100, text='Резервы пережили неурожай. Агроном пережил собрание жителей.'),
                 dict(id='pay', name='Купить зерно', francs=3500, text='Караван доставил зерно. Каша снова состоит преимущественно из еды.')]),
}


def incident_kind(identity, sequence):
    """Rare mundane events; follow-ups are only reachable through player choices."""
    roll = int(hashlib.sha256(f'{identity}:{sequence}'.encode()).hexdigest()[:8],16)
    total = sum(event.get('weight',0) for event in INCIDENTS.values())
    roll %= total
    for key,event in INCIDENTS.items():
        roll -= event.get('weight',0)
        if roll < 0:return key
    raise AssertionError('Empty incident catalog')


def land_cap(data):
    return STAGES[data['stage']]['lands']


def promotion(data, now, level, rank):
    target=STAGES.get(data['stage']+1)
    if not target:return None
    ready=data['founded_at']+target['age_days']*DAY
    checks=[dict(text=f"Возраст поселения: {target['age_days']} дней",ok=now>=ready),
            dict(text=f"Население: {target['population']}",ok=data['population']>=target['population']),
            dict(text=f"Ратуша: {target['hall']} уровень",ok=data['buildings']['hall']>=target['hall']),
            dict(text=f"Разных построек: {target['building_types']}",ok=sum(v>0 for v in data['buildings'].values())>=target['building_types']),
            dict(text=f"Решённых событий: {target['prestige']}",ok=data['prestige']>=target['prestige']),
            dict(text=f"Уровень героя: {target['level']}",ok=level>=target['level']),
            dict(text='Ранг охотника: '+('A' if target['rank']==5 else 'S'),ok=rank>=target['rank'])]
    return dict(stage=data['stage']+1,**target,ready_at=ready,checks=checks,allowed=all(c['ok'] for c in checks))


def coordinates(q, r):
    if type(q) is not int or type(r) is not int or not (0 <= q < WIDTH and 0 <= r < HEIGHT):
        raise ValueError('Выбери клетку на карте.')
    return q, r


def neighbours(q, r):
    # Odd-row offset hexagons; axial distance below uses the same conversion.
    diagonal = 1 if r % 2 else -1
    return [(x, y) for x, y in ((q-1,r),(q+1,r),(q,r-1),(q+diagonal,r-1),(q,r+1),(q+diagonal,r+1))
            if 0 <= x < WIDTH and 0 <= y < HEIGHT]


def distance(a, b):
    aq, ar = a[0] - (a[1] - a[1] % 2) // 2, a[1]
    bq, br = b[0] - (b[1] - b[1] % 2) // 2, b[1]
    return (abs(aq-bq) + abs(ar-br) + abs(aq+ar-bq-br)) // 2


def terrain(seed, q, r):
    if q == 3 + r // 3 and (q, r) not in SITES:
        return 'river'
    if r == 5 or (q, r) in SITES:
        return 'road'
    value = int(hashlib.sha256(f'{seed}:{q}:{r}'.encode()).hexdigest()[:8], 16) % 100
    return 'forest' if value < 38 else 'hills' if value < 60 else 'plain'


def capacity(data):
    return 600 + data['buildings']['warehouse'] * 500


def population_cap(data):
    return 30 + data['buildings']['hall'] * 25


def defense(data):
    return data['buildings']['barracks'] * 15 + data['buildings']['hall'] * 3 + data['population'] // 10


def rates(data, tiles):
    from arena_kingdom_council import production
    b = data['buildings']
    values = dict(food=12 + b['farm'] * 32 - math.ceil(data['population'] / 3),
                  wood=6 + b['sawmill'] * 18, stone=4 + b['quarry'] * 15)
    for tile in tiles:
        info = TERRAINS[tile['terrain']]
        if info['resource']:
            values[info['resource']] += info['bonus']
    return production(data,values)


def construction(data, key, now):
    if not isinstance(key,str) or key not in BUILDINGS:
        raise ValueError('Неизвестная постройка.')
    level = data['buildings'][key] + 1
    if level > STAGES[data['stage']]['building_cap']:
        raise ValueError('Для дальнейшего улучшения нужен следующий этап поселения. Максимум — IV уровень.')
    definition = BUILDINGS[key]
    return dict(building=key, level=level, price=definition['price'] * level ** 3,
                wood=definition['wood'] * level, stone=definition['stone'] * level,
                started=now, finish=now + BUILD_HOURS[level] * HOUR)


def initial(now):
    return dict(stage=1, founded_at=now, growth_hours=0, factions={}, stories=[], population=36, order=80, resources=dict(food=380,wood=300,stone=260),
                buildings={key: int(key in ('hall','farm')) for key in BUILDINGS}, construction=None,
                last_tick=now, next_event=now+6*HOUR, event_seq=0, event=None, prestige=0,
                history=[dict(at=now,text='Поселенцы заложили ратушу и поля. История начинается с сорока мешков и больших надежд.')])
