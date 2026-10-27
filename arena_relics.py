"""Nazarick trophies: ordinary equipped passives, never free boss scripts."""
from arena_fingers import has_trait

RELIC_IDS=('nz_pandora_mask','nz_demon_glasses','nz_valkyrie_helm','nz_hermes_armor')
TICKET_ID='nazarick_reclass'
TICKET_NAME='Билет на смену класса без потери уровня'
TICKET_DESCRIPTION='Выбери доступный класс. Уровень, XP, изученные трактатами навыки, пассивки, инвентарь и спрайт сохраняются. Ветка развития сбрасывается и выбирается заново. Классовые навыки заменяются навыками нового класса. Билет расходуется только после подтверждения.'


def build_catalog(PassiveSkill):
    specs=(
        ('nz_pandora_mask','Маска Пандоры','После первой атаки смена атакующего навыка даёт +20% прямого урона. Повтор того же навыка бонуса не даёт; поддержка не сбрасывает запомненную атаку. Промах тоже запоминается.'),
        ('nz_demon_glasses','Очки демона','Точность +8. За каждый различный временный дебафф на цели прямой урон +10%, максимум +30%.'),
        ('nz_valkyrie_helm','Шлем валькирии','Вампиризм: 8% реально нанесённого прямого урона, не более 8% максимального HP за действие. Не лечит от периодического урона и не воскрешает. При HP не выше 50% прямой урон +15%.'),
        ('nz_hermes_armor','Броня Гермеса','Получаемый прямой урон −15%. При HP не выше 35% снижение заменяется на −30%. С другими источниками снижения перемножается; не уменьшает периодический урон и самоурон.'),
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
    return accuracy,multiplier


def incoming(side):
    if not has_trait(side,'nz_hermes_armor'):return 1.0
    return .70 if 0<side['hp']<=side['stats']['max_hp']*.35 else .85


def after_action(actor,skill,damage):
    notes=[]
    if skill.damage_type:
        if has_trait(actor,'nz_pandora_mask'):actor.setdefault('relic_state',{})['last_attack']=skill.skill_id
        if has_trait(actor,'nz_valkyrie_helm') and actor['hp']>0 and damage>0:
            heal=min(actor['stats']['max_hp']-actor['hp'],int(damage*.08+.5),max(1,int(actor['stats']['max_hp']*.08)))
            actor['hp']+=heal
            if heal:notes.append(f'Шлем валькирии: +{heal} HP')
    return notes


def periodic_damage(side,amount):
    if any(e.get('id')=='nz_plot_armor' for e in side.get('effects',[])):return int(amount*.5+.5)
    return amount
