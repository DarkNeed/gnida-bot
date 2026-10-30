"""Equipment definitions and combat hooks. No persistence, client input or RNG in combat."""
from copy import deepcopy

RANKS = ('F', 'E', 'D', 'C', 'B', 'A', 'S')
LEVELS = (1, 4, 7, 10, 13, 16, 20)
RARITIES = ('common', 'uncommon', 'rare', 'epic', 'legendary')
LABELS = dict(zip(RARITIES, ('Обычный', 'Необычный', 'Редкий', 'Эпический', 'Легендарный')))
SLOTS = dict(weapon='Оружие', armor='Доспех', accessory='Аксессуар', relic='Реликвия')
STATS = dict(max_hp='HP', physical_attack='Физ. атака', magic_attack='Маг. атака',
             physical_defense='Физ. защита', magic_defense='Маг. защита', speed='Скорость', evasion='Уклонение')
AFFIXES = tuple(STATS)
CHANCES = ((55,35,10,0,0), (55,35,10,0,0), (15,45,35,5,0), (15,45,35,5,0),
           (0,20,55,23,2), (0,20,55,23,2), (0,0,55,40,5))
EFFECTS = {
    'bleeding': 'Прямой урон по кровоточащей цели +20%. Сам кровотечение не накладывает.',
    'summoner': 'При действующем призыве магический урон +15%. Первое завершение призыва за бой возвращает 15 энергии.',
    'stone': 'Первый прямой урон в каждом действии врага уменьшается на 5. На всю атаку, не на каждый снаряд.',
    'immortal': 'Раз за бой смертельный прямой удар оставляет 1 HP. Следующие 2 собственных действия входящий прямой урон −30%, лечение навыками вдвое слабее.',
    'troll': 'После потери не менее 20% максимального HP за действие врага восстанавливает 8% HP. Перерыв — 2 собственных действия. Не воскрешает.',
    'empty': 'При энергии ниже 25% прямой урон +25%. Проверяется до оплаты навыка.',
    'dot': 'Повторное наложение вашего кровотечения или горения усиливает его на 1 урона, до +3. Не создаёт новый эффект.',
    'cycle': 'Цикл атакующих действий: первые два −10% прямого урона, третье +40%. Промах тоже продвигает цикл.',
    'mercy': 'Ваши лечебные навыки восстанавливают на 20% больше HP. Пассивное лечение не усиливает.',
    'execution': 'Прямой урон по цели с HP не выше 30% повышен на 20%.',
    'opener': 'Первое атакующее действие в бою наносит на 30% больше прямого урона. Промах расходует эффект.',
    'leech': 'Восстанавливает 6% фактически снятого прямым ударом HP, максимум 6% вашего максимального HP за действие. Не воскрешает.',
}

# Eight items per biome, two alternatives for each slot. Art is code-native iconography.
_SPECS = (
 ('mines','weapon','brick','Кирпич убедительной аргументации','physical_attack','opener'),
 ('mines','weapon','shaman','Шаманский громоотвод','magic_attack','cycle'),
 ('mines','armor','helmet','Каска предпоследнего рабочего','physical_defense','stone'),
 ('mines','armor','apron','Фартук растворённого сборщика','magic_defense','immortal'),
 ('mines','accessory','shift','Жетон ночной смены','max_hp','empty'),
 ('mines','accessory','flask','Печать пустой фляги','speed','empty'),
 ('mines','relic','payroll','Проклятая ведомость','magic_attack','cycle'),
 ('mines','relic','escape','Амулет «Меня здесь не было»','evasion','immortal'),
 ('forest','weapon','fang','Клык последнего волка','physical_attack','bleeding'),
 ('forest','weapon','thorn','Посох терновой тропы','magic_attack','dot'),
 ('forest','armor','pelt','Шкура вожака','physical_defense','troll'),
 ('forest','armor','web','Мантия паучьего пансиона','magic_defense','stone'),
 ('forest','accessory','heart','Сердце болотного тролля','max_hp','troll'),
 ('forest','accessory','track','След потерянного охотника','evasion','execution'),
 ('forest','relic','cocoon','Кокон последнего жильца','max_hp','immortal'),
 ('forest','relic','moon','Луна над пустым логовом','speed','bleeding'),
 ('crypt','weapon','staff','Посох недоплаченного некроманта','magic_attack','summoner'),
 ('crypt','weapon','grave','Могильный тесак','physical_attack','execution'),
 ('crypt','armor','mantle','Мантия неоплаченного бессмертия','magic_defense','immortal'),
 ('crypt','armor','warden','Доспех безымянного стража','physical_defense','stone'),
 ('crypt','accessory','candle','Свеча чужого возвращения','max_hp','mercy'),
 ('crypt','accessory','bell','Колокольчик костоправа','speed','summoner'),
 ('crypt','relic','eye','Глаз погребённого лича','magic_attack','dot'),
 ('crypt','relic','name','Украденное имя','max_hp','leech'),
 ('caldera','weapon','ash','Клинок последнего рассвета','physical_attack','execution'),
 ('caldera','weapon','ember','Посох негаснущего пепла','magic_attack','dot'),
 ('caldera','armor','golem','Панцирь рунного голема','physical_defense','stone'),
 ('caldera','armor','scale','Одеяние багрового дракона','magic_defense','immortal'),
 ('caldera','accessory','prayer','Обугленная молитва','max_hp','mercy'),
 ('caldera','accessory','spark','Искра над пропастью','evasion','opener'),
 ('caldera','relic','ledger','Драконья бухгалтерия','physical_attack','cycle'),
 ('caldera','relic','blood','Чаша пепельной крови','magic_attack','leech'),
)
CATALOG = {key:dict(key=key, biome=biome, slot=slot, name=name, main=main, effect=effect)
           for biome,slot,key,name,main,effect in _SPECS}


def item_stats(item):
    definition=CATALOG[item['key']]; tier=RANKS.index(item['rank'])
    quality=RARITIES.index(item['rarity'])
    value=(1.5+tier*.7)*(1+quality*.12)*(1+item.get('upgrade',0)*.08)
    result={definition['main']:round(value*(6 if definition['main']=='max_hp' else 1),2)}
    for key in item.get('affixes',[]):
        result[key]=round(result.get(key,0)+(1+tier*.4)*(5 if key=='max_hp' else .7),2)
    return result


def public_item(item):
    value=deepcopy(item); definition=CATALOG[item['key']]
    value.update(definition, stats=item_stats(item), min_level=LEVELS[RANKS.index(item['rank'])],
                 rarity_name=LABELS[item['rarity']], effect_text=EFFECTS[definition['effect']] if item['rarity'] in ('epic','legendary') else '',
                 salvage=(2,3,5,8,12)[RARITIES.index(item['rarity'])],
                 upgrade_cost=2+item.get('upgrade',0)*2, reroll_cost=5)
    return value


def apply_stats(stats,items):
    result=dict(stats)
    for item in items:
        for key,value in item_stats(item).items():result[key]=round(result.get(key,0)+value,2)
    result['max_hp']=round(result['max_hp'])
    return result


def has(side,effect):
    return any(i['rarity'] in ('epic','legendary') and CATALOG.get(i['key'],{}).get('effect')==effect for i in side.get('equipment',[]))


def modifiers(actor,target,skill):
    if not skill.damage_type:return 1.
    mult=1.;state=actor.get('gear_state',{})
    if has(actor,'bleeding') and any(e['kind']=='bleed' for e in target['effects']):mult*=1.2
    if has(actor,'summoner') and skill.damage_type=='magic' and actor.get('rpg_state',{}).get('summon',0)>0:mult*=1.15
    if has(actor,'empty') and actor['resource']<actor['stats']['resource_max']*.25:mult*=1.25
    if has(actor,'execution') and target['hp']<=target['stats']['max_hp']*.3:mult*=1.2
    if has(actor,'opener') and not state.get('attacks',0):mult*=1.3
    if has(actor,'cycle'):mult*=1.4 if state.get('attacks',0)%3==2 else .9
    return mult


def incoming(side,amount,action_id):
    """One reduction per attacker action even for AoE/weighted projectile contacts."""
    state=side.setdefault('gear_state',{})
    if has(side,'stone') and state.get('stone_action')!=action_id and amount>0:
        state['stone_action']=deepcopy(action_id);amount=max(0,amount-5)
    if state.get('saved_until',-1)>side.get('own_turns',0):amount=round(amount*.7)
    if has(side,'immortal') and not state.get('saved') and 0<side['hp']<=amount:
        state.update(saved=True,saved_until=side.get('own_turns',0)+2)
        amount=max(0,side['hp']-1)
    return amount


def heal_amount(actor,recipient,amount):
    if has(actor,'mercy'):amount=round(amount*1.2)
    until=recipient.get('gear_state',{}).get('saved_until',-1)
    turn=recipient.get('own_turns',0)
    # The native resolver ticks the acting character before applying healing.
    if (until>=turn if recipient is actor else until>turn):amount=round(amount*.5)
    return amount


def after_action(actor,target,skill,damage,before_hp,summon_before,action_id):
    notes=[];state=actor.setdefault('gear_state',{})
    # A multi-target raid resolves the same paid action once per victim.
    fresh=state.get('last_action')!=action_id
    if fresh:
        state['last_action']=deepcopy(action_id)
        if skill.damage_type:state['attacks']=state.get('attacks',0)+1
        state['leech_healed']=0
    if has(actor,'leech') and actor['hp']>0 and damage>0:
        cap=max(1,round(actor['stats']['max_hp']*.06))
        gain=min(actor['stats']['max_hp']-actor['hp'],max(0,cap-state.get('leech_healed',0)),round(damage*.06))
        actor['hp']+=gain;state['leech_healed']=state.get('leech_healed',0)+gain
        if gain:notes.append(f'Чаша крови: +{gain} HP')
    if has(actor,'summoner') and summon_before>0 and not actor.get('rpg_state',{}).get('summon',0) and not state.get('summon_refund'):
        state['summon_refund']=True
        if actor['hp']>0:
            gain=min(15,actor['stats']['resource_max']-actor['resource']);actor['resource']+=gain
            if gain:notes.append(f'Последняя служба: +{gain} энергии')
    ts=target.setdefault('gear_state',{})
    lost=max(0,before_hp-target['hp'])
    if has(target,'troll') and target['hp']>0 and lost>=target['stats']['max_hp']*.2 and target.get('own_turns',0)>=ts.get('troll_ready',0):
        gain=min(target['stats']['max_hp']-target['hp'],round(target['stats']['max_hp']*.08));target['hp']+=gain
        ts['troll_ready']=target.get('own_turns',0)+2;notes.append(f'Сердце тролля: +{gain} HP')
    return notes


def enhance_dot(actor,new,previous):
    if not has(actor,'dot') or new['kind'] not in ('bleed','burn'):return
    owner=[actor.get('controller_id'),actor.get('slave_id')]
    new['gear_dot_owner']=owner
    if previous and previous.get('gear_dot_owner')==owner:
        bonus=min(3,previous.get('gear_dot_bonus',0)+1)
        new['value']=max(new['value'],previous['value']-previous.get('gear_dot_bonus',0))+bonus
        new['gear_dot_bonus']=bonus
