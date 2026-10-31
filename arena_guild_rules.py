"""Hunter guild content and pure, fixed-rank expedition generation."""
from copy import deepcopy
import hashlib
import random
from arena_engine import Skill

RANKS = ('F', 'E', 'D', 'C', 'B', 'A', 'S')
LEVELS = (2, 5, 8, 12, 16, 19, 20)
DAILY_FULL_REWARDS = 3
RUN_SECONDS = 48 * 3600
LOBBY_SECONDS = 1800
INVITE_COOLDOWN = 300


def attack(key, name, cls, power, accuracy=90, effects=(), tags=()):
    return Skill('guild_' + key, name, cls, 1, 'magic' if cls in ('mage', 'nerd', 'priest') else 'physical',
                 power, accuracy, 0, 0, effects=effects, tags=tags)


SKILLS = {s.skill_id: s for s in (
    attack('stab', 'Кривой нож гоблина', 'warrior', 8),
    attack('net', 'Паутина охотника', 'ring', 5, effects=({'target':'enemy','kind':'speed_pct','value':-.15,'duration':2},)),
    attack('fang', 'Клыки лютоволка', 'hunter', 12, 92, ({'target':'enemy','kind':'bleed','value':2,'duration':2},)),
    attack('hex', 'Проклятие шамана', 'mage', 10),
    attack('smash', 'Каменный кулак', 'warrior', 18, 85),
    attack('bone', 'Костяной залп', 'mage', 12, 92),
    attack('soul', 'Похищение жизни', 'mage', 17, 95),
    attack('claw', 'Тройное рассечение', 'hunter', 10, 92, tags=('three_strike',)),
    attack('fire', 'Драконье пламя', 'mage', 22, 95, ({'target':'enemy','kind':'burn','value':3,'duration':2},)),
    attack('ice', 'Ледяное копьё', 'mage', 18, 95),
    attack('lightning', 'Грозовая молния', 'mage', 20, 95),
    attack('acid', 'Кислотный плевок', 'mage', 9, 90),
    attack('sticky', 'Липкий выброс', 'mage', 7, 90, ({'id':'guild_sticky','target':'enemy','kind':'speed_pct','value':-.15,'turns':2},)),
    attack('pounce', 'Бросок хищника', 'hunter', 15, 94),
    attack('poison_bite', 'Ядовитые жвала', 'hunter', 12, 93, ({'id':'guild_venom','target':'enemy','kind':'burn','value':2,'turns':2},)),
    attack('cleaver', 'Секира разорителя', 'warrior', 18, 93),
    attack('troll_quake', 'Разлом трясины', 'warrior', 23, 94),
    attack('spectral_blade', 'Клинок забытого рыцаря', 'warrior', 21, 95),
    attack('rune_cross', 'Перекрёсток рун', 'mage', 24, 96),
    attack('stone_rain', 'Обвал каменных шипов', 'warrior', 23, 96),
    attack('venom_rain', 'Чумной ливень', 'mage', 24, 96, ({'id':'guild_venom','target':'enemy','kind':'burn','value':3,'turns':2},)),
    attack('dragon_dive', 'Пикирование хищника', 'hunter', 27, 97),
    attack('tail', 'Разящий хвост', 'warrior', 26, 97),
    attack('wings', 'Пепельный шквал', 'mage', 27, 97),
    attack('ice_tomb', 'Ледяной саркофаг', 'mage', 29, 97),
    attack('soul_prison', 'Темница душ', 'mage', 30, 98),
    attack('grave_crown', 'Корона безымянных', 'mage', 34, 99),
    attack('crypt_blades', 'Клинки погребённого войска', 'warrior', 32, 98),
    attack('ancient_sun', 'Падение последнего солнца', 'mage', 35, 99),
    attack('ash_orbit', 'Хоровод пепельных звёзд', 'mage', 33, 98),
)}

# Each creature has a coherent kit; no knives for spiders, curses for slimes or
# borrowed dragon breath for undead. Legacy IDs remain resolvable in saved runs.
MONSTER_KITS = {
    'goblin':['stab','net'], 'slime':['acid','sticky'], 'shaman':['hex','bone','soul'],
    'spider':['net','poison_bite','venom_rain'], 'wolf':['fang','claw','pounce'],
    'orc':['cleaver','smash','claw'], 'troll':['smash','troll_quake','stone_rain'],
    'wraith':['spectral_blade','bone','soul'], 'golem':['smash','rune_cross','stone_rain','lightning'],
    'wyvern':['claw','venom_rain','dragon_dive','tail'],
    'lich':['bone','soul_prison','ice_tomb','soul'],
    'dragon':['fire','tail','wings','dragon_dive'],
    'ancient':['fire','ancient_sun','ash_orbit','lightning'],
    'deathlord':['bone','grave_crown','crypt_blades','soul_prison'],
}

# HP/attack/armor below are rank content, not functions of the player's level.
MONSTERS = {
    'goblin': dict(name='Гоблин-разведчик', rank='F', role='Налётчик', art='goblin', hp=28, attack=2, armor=2, evasion=8, skills=['guild_stab']),
    'slime': dict(name='Мшистый слизень', rank='F', role='Живая кислота', art='slime', hp=38, attack=1, armor=1, evasion=0, skills=['guild_hex']),
    'shaman': dict(name='Гоблин-шаман', rank='E', role='Проклинатель', art='shaman', hp=70, attack=8, armor=3, evasion=5, skills=['guild_hex','guild_net']),
    'spider': dict(name='Матёрая паучиха', rank='E', role='Ловчая', art='spider', hp=85, attack=7, armor=3, evasion=10, skills=['guild_net','guild_stab']),
    'wolf': dict(name='Лютоволк', rank='D', role='Стайный хищник', art='wolf', hp=120, attack=12, armor=5, evasion=14, skills=['guild_fang','guild_claw']),
    'orc': dict(name='Орк-разоритель', rank='D', role='Сокрушитель', art='brute', hp=150, attack=13, armor=8, evasion=3, skills=['guild_smash','guild_stab']),
    'troll': dict(name='Болотный тролль', rank='C', role='Регенерирующий великан', art='brute', hp=230, attack=18, armor=10, evasion=2, skills=['guild_smash','guild_fang']),
    'wraith': dict(name='Призрачный рыцарь', rank='C', role='Страж склепа', art='skeleton', hp=190, attack=19, armor=12, evasion=12, skills=['guild_bone','guild_soul']),
    'golem': dict(name='Рунный голем', rank='B', role='Каменный бастион', art='golem', hp=330, attack=23, armor=23, evasion=0, skills=['guild_smash','guild_lightning']),
    'wyvern': dict(name='Чумная виверна', rank='B', role='Крылатый хищник', art='dragon', hp=290, attack=25, armor=13, evasion=16, skills=['guild_claw','guild_fire']),
    'lich': dict(name='Хранитель погребённых имён', rank='A', role='Лич', art='skeleton', hp=410, attack=32, armor=18, evasion=10, skills=['guild_soul','guild_bone','guild_ice']),
    'dragon': dict(name='Багровый дракон', rank='A', role='Владыка пламени', art='dragon', hp=490, attack=33, armor=23, evasion=10, skills=['guild_fire','guild_claw','guild_lightning']),
    'ancient': dict(name='Дракон последнего рассвета', rank='S', role='Древняя катастрофа', art='dragon', hp=730, attack=40, armor=28, evasion=14, skills=['guild_fire','guild_ice','guild_lightning']),
    'deathlord': dict(name='Король безымянных могил', rank='S', role='Владыка нежити', art='skeleton', hp=660, attack=42, armor=26, evasion=12, skills=['guild_soul','guild_bone','guild_claw']),
}

for _mid, _kit in MONSTER_KITS.items():
    MONSTERS[_mid]['skills'] = ['guild_'+sid for sid in _kit]

BIOMES = {
    'mines': dict(name='Гоблинские копи', subtitle='Ржавые рельсы. Чужие шаги. Слишком много глаз.', color='#cdb17b'),
    'forest': dict(name='Логово лютоволков', subtitle='Тропа помнит тех, кто не вернулся.', color='#96b9a7'),
    'crypt': dict(name='Проклятый склеп', subtitle='Имена на стенах ещё дописывают.', color='#a899cd'),
    'caldera': dict(name='Пепельная кальдера', subtitle='Золото здесь горячее крови.', color='#da957d'),
}
SUPPLIES = {
    'bandage': dict(name='Полевые бинты', rank='F', price=35, description='Вне боя: +30% HP себе и снятие кровотечения.'),
    'ration': dict(name='Концентрат бодрости', rank='E', price=60, description='Вне боя: +35% максимальной энергии себе.'),
    'antidote': dict(name='Серебряное противоядие', rank='D', price=90, description='Вне боя: снимает чуму, горение и кровотечение с выбранного союзника.'),
    'scout': dict(name='Карта разведчика', rank='C', price=130, description='Раскрывает все комнаты текущего подземелья.'),
    'camp': dict(name='Походный очаг', rank='B', price=180, description='Вне боя: живые участники восстанавливают 25% HP.'),
    'revive': dict(name='Свеча возвращения', rank='A', price=260, description='Вне боя: возвращает павшего союзника с 35% HP. Покинувших отряд не возвращает.'),
    'balm': dict(name='Бальзам высшей гильдии', rank='S', price=400, description='Вне боя: +50% HP и энергии себе, очищение от чумы, ожогов и кровотечения.'),
}


def art(monster):
    return '/static/assets/guild/' + monster + '-v1.png'


# Flavour is separate from objectives and numbers: the guild's sense of humour
# must not hide the actual conditions of a contract.
CONTRACT_FLAVOUR = {
    'f_hunt': 'Разведчик украл ведомость зарплат. Гильдия впервые объявила награду быстрее, чем выдала зарплату.',
    'f_elite': 'Слизень растворил сборщика взносов. Заказ оплачен со слезами — радости бухгалтерии.',
    'e_elite': 'Паучиха предлагает бесплатное жильё с питанием. Предыдущие жильцы уже стали питанием.',
    'd_hunt': 'У лютоволка нашли жетоны трёх охотников. Четвёртый просит снять его с дежурства.',
    'c_elite': 'Рыцарь охраняет склеп без выходных и зарплаты. Гильдия называет это образцовой трудовой дисциплиной.',
    'b_dungeon': 'Похоронные услуги в стоимость допуска не входят. При успешном возвращении они тоже не понадобятся — возможно.',
    'a_hunt': 'Лич хранит имена должников. Из хорошего: проценты больше не растут. Из плохого: должники тоже.',
    's_elite': 'Король обещает каждому вечную службу. Даже наша гильдия не печатает такой пункт крупным шрифтом.',
}


def contracts():
    result = {}
    for i, rank in enumerate(RANKS):
        monsters = [k for k, m in MONSTERS.items() if m['rank'] == rank]
        biome = 'mines' if i < 2 else 'forest' if i == 2 else 'crypt' if i < 5 else 'caldera'
        for kind in ('hunt', 'elite', 'dungeon'):
            key = rank.lower() + '_' + kind
            name = ('След: ' + MONSTERS[monsters[0]]['name'] if kind == 'hunt' else
                    'Особо опасен: ' + MONSTERS[monsters[-1]]['name'] if kind == 'elite' else BIOMES[biome]['name'] + ' · ' + rank)
            result[key] = dict(id=key, code=rank+str(('hunt','elite','dungeon').index(kind)+1), rank=rank, kind=kind, name=name, biome=biome,
                monsters=monsters, reward=45 + i*70 + (30 if kind == 'elite' else 90+i*20 if kind == 'dungeon' else 0),
                recommended_party=1 if kind == 'hunt' else 2 if i < 4 else 3,
                level=LEVELS[i], rooms='1 бой' if kind != 'dungeon' else '6 комнат · развилки',
                description='Уничтожьте отмеченную цель.' if kind=='hunt' else 'Усиленный противник. Подготовьте отряд.' if kind=='elite' else
                    'Выберите маршрут, переживите события и победите хозяина подземелья. Между комнатами нет полного восстановления.')
            if key in CONTRACT_FLAVOUR:
                result[key]['description'] += ' ' + CONTRACT_FLAVOUR[key]
    return result


CONTRACTS = contracts()


def contract_by_code(code):
    value=str(code or '').strip().upper().translate(str.maketrans('АВСЕ','ABCE'))
    key=next((k for k,c in CONTRACTS.items() if c['code']==value),None)
    if not key:raise ValueError('Неизвестный код заказа. Пример: /охота F1. Коды F1–S3 указаны в /заказы.')
    return key

EVENTS = {
    'shrine': dict(name='Святилище без имени', text='В чаше шевелится свет. Надпись обещает исцеление — и долг. Мелким шрифтом: «Душа возврату и обмену не подлежит». Даже у богов нашёлся юрист.', choices=[
        dict(id='blessing', name='Принять свет', hint='+40% HP живым. До конца похода входящий урон +15%.'),
        dict(id='break', name='Разбить чашу', hint='Дополнительный бой. За победу — больше находок.'),
        dict(id='leave', name='Пройти мимо', hint='Без риска и награды.')]),
    'cocoon': dict(name='Кокон над тропой', text='Изнутри доносится стук. Слишком ровный для ветра. На паутине висит табличка: «Пансион. Всё включено». Судя по сапогам внизу, включено и предыдущее меню.', choices=[
        dict(id='rescue', name='Разрезать кокон', hint='Пленник с наградой или засада пауков. Шанс 50/50.'),
        dict(id='burn', name='Сжечь издали', hint='Без боя. Найденное золото уцелеет не всё.'),
        dict(id='leave', name='Не трогать', hint='Продолжить путь.')]),
    'well': dict(name='Колодец памяти', text='Вода отражает не лица, а ваши последние ошибки.', choices=[
        dict(id='drink', name='Выпить', hint='+45% энергии. Каждый живой теряет 10% максимального HP.'),
        dict(id='offering', name='Опустить находки', hint='Потерять 30% походных находок, снять вредные эффекты.'),
        dict(id='leave', name='Уйти', hint='Ничего не менять.')]),
}


def make_map(contract, seed):
    rng = random.Random(seed)
    if contract['kind'] != 'dungeon':
        return [dict(id='boss', layer=0, lane=1, kind='boss', links=[], cleared=False)]
    # Branches rejoin. Six visited rooms, not every node on the board.
    layers = [['start'], ['a1','b1'], ['a2','b2'], ['a3','b3'], ['a4','b4'], ['boss']]
    nodes=[]
    for layer, names in enumerate(layers):
        for lane, key in enumerate(names):
            kind = 'entry' if layer==0 else 'boss' if layer==5 else 'rest' if layer==4 else rng.choice(('battle','battle','event','treasure','elite'))
            if layer==2:kind='event' if lane==0 else 'battle'
            if layer==3:kind='treasure' if lane==0 else 'elite'
            node=dict(id=key, layer=layer, lane=1 if len(names)==1 else lane*2, kind=kind,
                links=list(layers[layer+1]) if layer<5 else [], cleared=layer==0)
            if kind=='event':node['event']=rng.choice(tuple(EVENTS))
            node['roll']=rng.random()
            nodes.append(node)
    return nodes


def mob_templates(contract, node, party_size):
    ids=contract['monsters']
    if node.get('ambush')=='spider':chosen=['spider','spider']
    elif node.get('ambush'):chosen=[ids[-1]]
    elif node['kind']=='boss':chosen=[ids[0] if contract['kind']=='hunt' else ids[-1]]
    elif node['kind']=='elite':chosen=[ids[0]]
    else:chosen=[ids[0]]*(2 if party_size>1 else 1)
    result=[]
    for index, mid in enumerate(chosen):
        m=MONSTERS[mid];level=LEVELS[RANKS.index(m['rank'])]
        elite=(node['kind']=='elite' or node['kind']=='boss' and contract['kind']!='hunt') and not node.get('ambush')
        factor=(1+.6*(party_size-1))*(1.45 if elite else 1)
        stats=dict(max_hp=round(m['hp']*factor), resource_max=100,
            physical_attack=m['attack'], magic_attack=m['attack'],
            physical_defense=m['armor'], magic_defense=m['armor'], speed=8+level,
            evasion=m['evasion'])
        v=dict(name=m['name']+(' · вожак' if elite else ''), description=m['role'],
            class_id='ragamuffin', level=level, archclass_id='', archclass_stage=10,
            defense_mode='dodge', skills=list(m['skills']), passives=[], stats=stats,
            ai='sequence', avatar_key='', sprite_key='', flip=False, scale=1.15 if elite else .9,
            preset_id='')
        result.append(dict(id='guild:'+mid, revision=2, kind='mob', definition=v, guild_monster=mid,
                           npc_tier=max(0,RANKS.index(m['rank'])-2)+(1 if elite and m['rank'] in ('B','A','S') else 0)))
    return result


def calibration_rank(level):
    return 'C' if level>=15 else 'D' if level>=8 else 'E' if level>=5 else None


def fingerprint(parts):
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()
