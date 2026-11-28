"""Version-two Mirror Wasteland: a saved, forward-only, three-lane graph."""

from collections import Counter
import random

from arena_archclasses import class_title
from arena_engine import FIGHTER_CLASSES, MAX_FIGHTER_LEVEL
from arena_equipment import AFFIXES, CATALOG, SLOTS, public_item
from arena_mirror_effects import GIFTS, NORMAL_GIFTS
from arena_progression import choice_avatar
from arena_wasteland import enemy_source

DEPTH = 10
LANES = 3
NORMAL_DUST = 18
ELITE_DUST = 28
CHECKPOINTS = {3: ('common', 4, 25), 6: ('uncommon', 4, 45), 9: ('rare', 4, 65)}
MIRROR_TITLE = 'Разбивший отражение'
ELITE_SHARD_CHANCE = .15
RARITY_DEPTH = {'common': 0, 'uncommon': 1, 'rare': 2}
SHOP_SUPPLIES = {
    'heal': ('Перевязь', 'Восстанавливает 35% максимального HP.', 15),
    'energy': ('Флакон эха', 'Возвращает 45 энергии.', 9),
}


def floor_enemy_level(floor, kind):
    """The ten-floor route has a fixed difficulty curve, independent of the player."""
    span = DEPTH - 1
    growth = {'fight': 10, 'elite': 13, 'boss': 15}[kind]
    return 15 + ((floor - 1) * growth + span // 2) // span


def _floor_enemy(floor, kind, previous, rng, enabled):
    level = floor_enemy_level(floor, kind)
    enemy = enemy_source(level, previous, rng, enabled_classes=enabled)
    # Keep the native class/skill template at the regular level cap.
    if level > MAX_FIGHTER_LEVEL:
        enemy['mirror_level'] = level
    return enemy


def make_floor(floor, enabled, rng):
    """Three to six rooms on the route, then one shop and one boss."""
    room_count=rng.randint(3,6)
    sparse=set(rng.sample(range(2,room_count+1), (room_count+1)//2))
    route,last=[],None
    for step in range(1,room_count+1):
        lanes=list(range(LANES))
        if step in sparse:
            lanes.remove(rng.choice(lanes))
        if step==1:
            kinds=['fight']*len(lanes)
        else:
            safe='rest' if step==room_count else rng.choice(('rest','cache'))
            kinds=['elite' if step>1 and (floor+step)%3==0 else 'fight',safe]
            if len(lanes)==3:kinds.append('fight')
        rng.shuffle(kinds)
        nodes=[]
        for lane,kind in zip(lanes,kinds):
            node=dict(id=f'f{step}-{lane}',lane=lane,kind=kind)
            if kind in ('fight','elite'):
                enemy=_floor_enemy(floor,kind,last,rng,enabled)
                last=enemy['class_id']
                node['enemy']=enemy
            nodes.append(node)
        links=_connect(route[-1]['nodes'],lanes,rng) if route else []
        route.append(dict(floor=step,nodes=nodes,links=links))
    step=room_count+1
    route.append(dict(floor=step,nodes=[dict(id=f'f{step}-1',kind='shop',lane=1)],
                      links=[[n['lane'],1] for n in route[-1]['nodes']]))
    return route,_floor_enemy(floor,'boss',last,rng,enabled)


def _connect(previous,lanes,rng):
    possibles=[(n['lane'],dst) for n in previous for dst in lanes if abs(n['lane']-dst)<=1]
    rng.shuffle(possibles)
    links=[]
    for src,dst in possibles:
        if not any(a==src for a,_ in links) or not any(b==dst for _,b in links) or rng.random()<.32:
            links.append([src,dst])
    diagonals=[x for x in possibles if x[0]!=x[1]]
    if diagonals and all(a==b for a,b in links):
        links.append(list(rng.choice(diagonals)))
    return links


def make_route(level, enabled, rng):
    """Previous ten-row playtest layout, retained for compatibility tests."""
    route, last = [], None
    sparse = set(rng.sample(range(2, DEPTH), 5))
    for floor in range(1, DEPTH+1):
        if floor == DEPTH:
            route.append(dict(floor=floor,nodes=[dict(id=f'f{floor}-1',kind='shop',lane=1)],
                              links=[[n['lane'],1] for n in route[-1]['nodes']]))
            break
        kinds = ['fight', 'fight', rng.choice(('rest', 'cache'))]
        if floor in CHECKPOINTS:
            kinds = ['fight','fight','elite']
        if floor == 1:
            kinds = ['fight','fight','fight']
        lanes = list(range(LANES))
        if floor in sparse:
            lanes.remove(rng.choice(lanes))
            kinds.pop(1 if floor in CHECKPOINTS else 0)
        rng.shuffle(kinds)
        nodes = []
        for lane, kind in zip(lanes,kinds):
            node = dict(id=f'f{floor}-{lane}', kind=kind, lane=lane)
            if kind in ('fight', 'elite'):
                enemy = enemy_source(level + (floor-1)//3 + int(kind=='elite'), last, rng, enabled_classes=enabled)
                last = enemy['class_id']
                node['enemy'] = enemy
            nodes.append(node)
        links = _connect(route[-1]['nodes'],lanes,rng) if route else []
        route.append(dict(floor=floor,nodes=nodes,links=links))
    return route, enemy_source(level+4, last, rng, enabled_classes=enabled)


def available(data):
    if data['phase']!='map':
        return []
    row = data['route'][data.get('step',data['floor'])-1]
    if data['lane'] is None:
        return [node['id'] for node in row['nodes']]
    connected = {dst for src,dst in row['links'] if src==data['lane']}
    return [node['id'] for node in row['nodes'] if node['lane'] in connected]


def enemy_card(enemy):
    cls = FIGHTER_CLASSES[enemy['class_id']]
    return dict(name=class_title(enemy,cls.name), level=enemy.get('mirror_level',enemy['level']),
                sprite=choice_avatar(enemy['class_id'],enemy['archclass_id'],enemy['archclass_stage']))


def public_route(data):
    route = [dict(floor=row['floor'],links=row['links'],nodes=[
        dict(id=n['id'],lane=n['lane'],kind=n['kind'],**(dict(mob=enemy_card(n['enemy'])) if 'enemy' in n else {}))
        for n in row['nodes']]) for row in data['route']]
    offers = [dict(id=g, name=GIFTS[g][0], description=GIFTS[g][1], price=price,
        kind='artifact', bought=g in data['gifts']) for g,price in data.get('shop',[])]
    if data['phase']=='merchant':
        offers.extend(dict(id=k,name=n,description=d,price=shop_price(data,p),kind='supply',
            bought=k in data.get('supplies',[]), full=(data['hp']==data['max_hp'] if k=='heal' else data['resource']==data['resource_max']))
            for k,(n,d,p) in SHOP_SUPPLIES.items())
    return dict(route=route,available=available(data),path=data['path'],boss=enemy_card(data['final_enemy']),dust=data['dust'],
                offers=offers,rewards=data.get('rewards_available',[]), pages=data.get('pages',{}),
                cleared=data['cleared'],boss_active=data.get('boss_active',False),weekly_bonus=data.get('weekly_bonus',False),
                route_version=data.get('route_version',1),step=data.get('step',data['floor']),floor_length=len(route)+1)


def shop_stock(data, rng=None):
    rng=rng or random.SystemRandom()
    pool=[g for g in NORMAL_GIFTS if g not in data['gifts']]
    return [[g, shop_price(data,18 if g in ('edge','focus','shell','curtain') else 12)]
            for g in rng.sample(pool,min(3,len(pool)))]


def shop_price(data, base):
    return max(1,base-5*bool(data.get('discount')))


def scale_enemy(fighter, floor, kind, *, chapter=False, mirror_level=None):
    boss=kind=='boss'
    stats=fighter['stats']
    tune=.86+.018*floor
    extra_levels = 0
    if chapter and mirror_level is not None:
        extra_levels = max(0, mirror_level - MAX_FIGHTER_LEVEL)
        fighter['level'] = mirror_level
    role_factor = 1.14 if boss else 1.04 if kind=='elite' else 1
    for key in ('physical_attack','magic_attack','physical_defense','magic_defense'):
        growth = .03 if key.endswith('_attack') else .02
        stats[key]=round(stats[key]*tune*role_factor*(1+growth*extra_levels),2)
    factor=(1.25+.027*floor if chapter else 1.52) if boss else 1.19 if kind=='elite' else .87+.015*floor
    stats['max_hp']=round(stats['max_hp']*factor*(1+.04*extra_levels))
    fighter.update(hp=stats['max_hp'],is_boss=boss)


def capped_rarity(level, rarity):
    cap=0 if level<5 else 1 if level<10 else 2
    return ('common','uncommon','rare')[min(cap,RARITY_DEPTH[rarity])]


def checkpoint(data):
    if data['floor'] not in CHECKPOINTS:
        return 0, {}
    rarity, amount, francs = CHECKPOINTS[data['floor']]
    return francs,{rarity:amount}


def final_pages(level):
    result=Counter({capped_rarity(level,'rare'):3})
    result[capped_rarity(level,'uncommon')]+=2
    return dict(result)


def elite_shard_rank(floor, rng):
    if floor < 7 or rng.random() >= ELITE_SHARD_CHANCE:
        return None
    return 'S' if floor >= 9 else 'A'


def gear_rewards(stats, rarity, rng):
    """Offer one fixed roll for each slot, matching the hero's main damage type."""
    physical = stats['physical_attack'] >= stats['magic_attack']
    keys = ('mirror_edge' if physical else 'mirror_staff',
            'mirror_plate' if physical else 'mirror_mantle', 'mirror_sigil','mirror_hour')
    offers = []
    for key in keys:
        definition = CATALOG[key]
        affixes = rng.sample([stat for stat in AFFIXES if stat != definition['main']], 2)
        item = public_item(dict(key=key,rank='S',rarity=rarity,affixes=affixes))
        offers.append(dict(id='gear-'+item['slot'],kind='gear',key=key,name=item['name'],rarity=rarity,
                           slot_name=SLOTS[item['slot']],rarity_name=item['rarity_name'],affixes=affixes,
                           stats=item['stats'],effect_text=item['effect_text']))
    return offers
