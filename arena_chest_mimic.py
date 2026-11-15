"""Treasure-room predator. Deliberately unrelated to the copying raid boss."""
from arena_engine import Skill


def move(key, name, power, cast, effects=(), description=''):
    return Skill('guild_chest_'+key, name, 'universal', 1, 'physical', power, 95, 0, 0,
                 effects=effects, description=description, cast_base=cast)


SKILLS = {s.skill_id: s for s in (
    move('bite', 'Зубастая сделка', 10, 3.2,
         description='Одна цель. Челюсти смыкаются с разных сторон; направление укуса видно заранее.'),
    move('tongue', 'Липкий язык', 7, 2.8,
         ({'id':'chest_tongue','target':'enemy','kind':'speed_pct','value':-.15,'duration':2},),
         'Одна цель. Язык фиксирует направление перед выпадом. Попадание: −15% скорости на 2 действия.'),
    move('coins', 'Возврат наличными', 9, 3.7,
         description='Весь отряд. Веера монет пролетают по полю, затем часть возвращается обратно.'),
    move('devour', 'Сожрать вместе с бронёй', 16, 4.5,
         ({'id':'chest_armor','target':'enemy','kind':'physical_defense_pct','value':-.15,'duration':2},),
         'Одна цель. Втягивающая пасть и обломки. Попадание: −15% физической защиты на 2 действия. Снаряжение не теряется.'),
    move('ravenous_bite', 'Ненасытность · зубы и сдача', 13, 3.6,
         description='Одна цель. Укусы чередуются с монетами; после 35% HP сундук больше не притворяется мебелью.'),
    move('ravenous_coins', 'Ненасытность · мелочь с зубами', 12, 4.1,
         description='Весь отряд. Возвращающиеся монеты и короткие укусы. Оба типа угроз предупреждаются заранее.'),
)}

PHASE_ONE = ['guild_chest_'+k for k in ('bite','tongue','coins','devour')]
PHASE_TWO = ['guild_chest_'+k for k in ('ravenous_bite','tongue','ravenous_coins','devour')]
MASS_ATTACKS = {'guild_chest_coins','guild_chest_ravenous_coins'}

CHEST_EVENT = dict(name='Подозрительно щедрый сундук',
    text='Деревянный сундук с серебристой оковкой ждёт хозяина. На крышке: «Наследство получите лично». '
         'Бухгалтерия рекомендует сначала проверить, кто кого наследует.',
    choices=[dict(id='open',name='Открыть сундук',hint='50% — добыча, 50% — бой с мимиком ранга заказа. Награды сохранятся при успешном завершении похода.'),
             dict(id='leave',name='Пройти мимо',hint='Без боя и без добычи сундука.')])


def template(rank, party_size):
    from arena_guild_rules import RANKS, LEVELS
    i=RANKS.index(rank)
    hp=(44,100,175,260,380,550,800)[i]
    attack=(2,7,12,18,24,32,40)[i]
    armor=(2,4,7,11,16,21,27)[i]
    definition=dict(name='Сундук-мимик', description='Элитный хищник сокровищницы. При 35% HP — ненасытность: укусы и монеты в одной атаке. Навыки не копирует.',
        class_id='ragamuffin',level=LEVELS[i],archclass_id='',archclass_stage=10,
        defense_mode='dodge',skills=list(dict.fromkeys(PHASE_ONE+PHASE_TWO)),passives=[],
        stats=dict(max_hp=round(hp*(1+.6*(party_size-1))),resource_max=100,
                   physical_attack=attack,magic_attack=attack,physical_defense=armor,
                   magic_defense=armor,speed=8+LEVELS[i],evasion=0),
        ai='sequence',avatar_key='',sprite_key='',flip=False,scale=1.05,preset_id='')
    return dict(id='guild:chest_mimic',revision=1,kind='mob',definition=definition,
                guild_monster='chest_mimic',npc_tier=max(0,i-2))


def prepare(fighter):
    """A one-way phase change, without healing or invalidating an announced cast."""
    if fighter.get('chest_phase',1)==1 and 0 < fighter['hp'] <= fighter['stats']['max_hp']*.35:
        fighter['chest_phase']=2
        fighter['rp_ai_index']=0
    return fighter.get('chest_phase',1)
