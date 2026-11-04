"""Nazarick trophies: ordinary equipped passives, never free boss scripts."""
from arena_fingers import has_trait

RELIC_IDS=('nz_pandora_mask','nz_demon_glasses','nz_valkyrie_helm','nz_hermes_armor')
DUNGEON_RELIC_IDS=RELIC_IDS+('nz_cocytus_oath','nz_twins_bond','nz_sebas_etiquette','nz_victim_seal')
TICKET_ID='nazarick_reclass'
TICKET_NAME='Билет на смену класса без потери уровня'
TICKET_DESCRIPTION='Выбери доступный класс. Уровень, XP, изученные трактатами навыки, пассивки, инвентарь и спрайт сохраняются. Ветка развития сбрасывается и выбирается заново. Классовые навыки заменяются навыками нового класса. Билет расходуется только после подтверждения.'


def build_catalog(PassiveSkill):
    specs=(
        ('nz_pandora_mask','Маска Пандоры','После первой атаки смена атакующего навыка даёт +20% прямого урона. Повтор того же навыка бонуса не даёт; поддержка не сбрасывает запомненную атаку. Промах тоже запоминается.'),
        ('nz_demon_glasses','Очки демона','Точность +8. За каждый различный временный дебафф на цели прямой урон +10%, максимум +30%.'),
        ('nz_valkyrie_helm','Шлем валькирии','Вампиризм: 8% реально нанесённого прямого урона, не более 8% максимального HP за действие. Не лечит от периодического урона и не воскрешает. При HP не выше 50% прямой урон +15%.'),
        ('nz_hermes_armor','Броня Гермеса','Получаемый прямой урон −15%. При HP не выше 35% снижение заменяется на −30%. С другими источниками снижения перемножается; не уменьшает периодический урон и самоурон.'),
        ('nz_cocytus_oath','Клятва ледяной чести','При энергии не ниже 50% прямой урон +18%. Подходит физическим и магическим атакам; энергия проверяется до оплаты навыка.'),
        ('nz_twins_bond','Узы шестого этажа','Каждое третье собственное действие восстанавливает 5% максимального HP и 5 энергии. Не воскрешает; это пассивное восстановление, оно не очищает чуму.'),
        ('nz_sebas_etiquette','Безупречный этикет','При HP выше 50% получаемый прямой урон −10%. При HP не выше 50% вместо этого прямой урон +20%.'),
        ('nz_victim_seal','Завет восьмого этажа','Получаемый периодический урон −25%. Не уменьшает прямые атаки и самоурон; сочетается с Сюжетной бронёй.'),
    )
    return {key:PassiveSkill(key,name,(dict(id=key,kind=key,value=1,target='self',raid_loot=True,description=desc),),'legendary') for key,name,desc in specs}


def modifiers(actor,target,skill):
    if not skill.damage_type:return 0,1.0
    accuracy,multiplier=0,1.0
    if has_trait(actor,'nz_pandora_mask'):
        previous=actor.get('relic_state',{}).get('last_attack')
        if previous and previous!=skill.skill_id:multiplier*=1.20
    if has_trait(actor,'nz_demon_glasses'):
        from arena_epic import temporary_debuff
        accuracy+=8
        multiplier*=1+.10*min(3,len({e['kind'] for e in target['effects'] if temporary_debuff(e)}))
    if has_trait(actor,'nz_valkyrie_helm') and 0<actor['hp']<=actor['stats']['max_hp']*.5:multiplier*=1.15
    if has_trait(actor,'nz_cocytus_oath') and actor['resource']>=actor['stats']['resource_max']*.5:multiplier*=1.18
    if has_trait(actor,'nz_sebas_etiquette') and 0<actor['hp']<=actor['stats']['max_hp']*.5:multiplier*=1.2
    return accuracy,multiplier


def incoming(side):
    mult=.9 if has_trait(side,'nz_sebas_etiquette') and side['hp']>side['stats']['max_hp']*.5 else 1.
    if has_trait(side,'nz_hermes_armor'):mult*=.70 if 0<side['hp']<=side['stats']['max_hp']*.35 else .85
    return mult


def after_action(actor,skill,damage):
    notes=[]
    state=actor.setdefault('relic_state',{})
    if has_trait(actor,'nz_twins_bond'):
        state['twins_actions']=state.get('twins_actions',0)+1
        if state['twins_actions']%3==0 and actor['hp']>0:
            hp=min(actor['stats']['max_hp']-actor['hp'],round(actor['stats']['max_hp']*.05));energy=min(5,actor['stats']['resource_max']-actor['resource'])
            actor['hp']+=hp;actor['resource']+=energy
            notes.append(f'Узы шестого этажа: +{hp} HP, +{energy} энергии')
    if skill.damage_type:
        if has_trait(actor,'nz_pandora_mask'):actor.setdefault('relic_state',{})['last_attack']=skill.skill_id
        if has_trait(actor,'nz_valkyrie_helm') and actor['hp']>0 and damage>0:
            heal=min(actor['stats']['max_hp']-actor['hp'],int(damage*.08+.5),max(1,int(actor['stats']['max_hp']*.08)))
            actor['hp']+=heal
            if heal:notes.append(f'Шлем валькирии: +{heal} HP')
    return notes


def periodic_damage(side,amount):
    if has_trait(side,'nz_victim_seal'):amount=int(amount*.75+.5)
    if any(e.get('id')=='nz_plot_armor' for e in side.get('effects',[])):return int(amount*.5+.5)
    return amount
