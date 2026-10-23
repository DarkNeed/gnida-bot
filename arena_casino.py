"""Secret casino lineage. Dice and chips are battle-local, never franc wagers."""

from dataclasses import replace
import random

CLASS_ID = 'gambler'
BRANCHES = {
    'casino_hustler': dict(class_id=CLASS_ID, name='Шулер', final_name='Хозяин казино',
        description='Плохой бросок можно автоматически перебросить раз в три своих действия. Туз в рукаве даёт лучший из двух бросков.',
        final_description='Казино всегда в плюсе: три следующие родные атаки сильнее на 25%; плохой бросок возвращает 8 энергии.'),
    'casino_lucky': dict(class_id=CLASS_ID, name='Счастливчик', final_name='Избранник Фортуны',
        description='Джекпот усиливает родную атаку на 90% вместо 60%. Три джекпота готовят 777.',
        final_description='Последний депозит превращается в 777 при трёх джекпотах и семи фишках. Фортуна не отменяет блок и уклонение.'),
}


def build_catalog(FighterClass, Skill, effect):
    cls = FighterClass(CLASS_ID, 'Лудоман', 'Азарт', 5,
        dict(max_hp=46, physical_attack=10, magic_attack=13, physical_defense=8, magic_defense=9, speed=11, evasion=8),
        dict(max_hp=4.5, physical_attack=1.1, magic_attack=1.4, physical_defense=.8, magic_defense=.8, speed=.8, evasion=.25),
        (dict(effect('casino_comeback','casino_comeback',1,target='self'), name='Мам, я отыграюсь',
              description='При HP не выше 35% плохой бросок даёт два Невезения вместо одного. На трёх следующий атакующий бросок — 6.'),), 'rare')
    def s(key,name,level,power,cost,cd,description,tags=()):
        return Skill(key,name,CLASS_ID,level,'magic' if power else None,power,95 if power else 100,cost,cd,
                     rarity='epic' if level>=15 else 'rare',description=description,
                     tags=('casino_native',)+tags)
    skills = (
        s('casino_bet','Ставка принята',5,12,15,0,'Кубик: 1–2 = ×0,75, 3–4 = ×1, 5 = ×1,25, 6 = ×1,6 урона и возврат 8 энергии при попадании. Атака даёт фишку; джекпот — две, максимум 7.'),
        s('casino_ace','Туз в рукаве',5,0,10,3,'Следующая родная атака бросает два кубика и выбирает лучший. Подготовленный гарантированный джекпот не расходуется этим навыком.'),
        s('casino_credit','Кредит доверия',6,0,0,4,'Возвращает до 30 энергии. Столько же составляет долг: будущий пассивный реген сперва погашает его. Пока долг не погашен, новый кредит недоступен.'),
        s('casino_hold','Припрятанный бросок',10,0,15,4,'Сохраняет последний бросок 3–6 для следующей родной атаки. Сохранённый бросок расходуется один раз; повторно сохранить тот же нельзя.',('archclass:casino_hustler',)),
        s('casino_guard','Фортуна прикроет',10,0,15,3,'Расходует одно Невезение: входящий прямой урон −45% до следующего своего действия.',('archclass:casino_lucky',)),
        s('casino_all_in','Ва-банк',8,25,40,3,'Ставка на цвет рулетки: красное/чёрное ×2 урона (18/37), зелёное ×30 (1/37). Несовпадение: урон 0 и самоурон 8% максимального HP. При трёх фишках расходует их ради +20% урона. Успех даёт пробитие 40%. Без мини-игр ставка автоматически на красное.',('hybrid_attack',)),
        s('casino_house','Казино всегда в плюсе',15,0,35,5,'Следующие три родные атаки получают +15% урона; на плохом броске возвращают 5 энергии. С 18 уровня +20%; финальная ступень — +25% и возврат 8.',('archclass:casino_hustler',)),
        s('casino_deposit','Последний депозит',15,34,70,5,'Три удара с общей силой 34. При трёх джекпотах и семи фишках превращается в автоматический 777: сила 46 (финал 54), пробитие 45%. Один запуск без остановки барабанов: 777 ×8, три одинаковых ×3, две 7 ×2, одна 7 ×1, иначе ×0,35. На каждом барабане равновероятны 7/♦/♠/♥. Тратит заряды даже при промахе.',('archclass:casino_lucky','three_strike','hybrid_attack')),
    )
    catalog={s.skill_id:s for s in skills}
    catalog['casino_credit']=replace(catalog['casino_credit'],effects=(effect('casino_credit','resource',30,target='self'),))
    catalog['casino_guard']=replace(catalog['casino_guard'],effects=(effect('casino_guard','incoming_damage_multiplier',.55,1,target='self'),))
    return {CLASS_ID:cls}, catalog


def branch(side):
    key=side.get('archclass_id','')
    return key if side.get('class_id')==CLASS_ID and side.get('level',0)>=10 and key in BRANCHES else ''


def final(side):
    return side.get('level',0)>=20 and side.get('archclass_stage',20)>=20


def variant(skill, actor):
    if skill.class_id!=CLASS_ID:return skill
    changes={}
    if skill.skill_id=='casino_deposit' and actor.get('casino_state',{}).get('sevens',0)>=3 and actor.get('casino_state',{}).get('chips',0)>=7:
        changes.update(name='777 · Фортуна снимает ограничения',power=54 if final(actor) else 46,pierce=.45)
    if skill.damage_type and actor.get('level',0)>=12:changes['power']=changes.get('power',skill.power)+1
    return replace(skill,**changes) if changes else skill


def restriction(side,skill):
    if skill.skill_id=='casino_credit' and side.get('casino_state',{}).get('debt',0)>0:
        return 'Сначала погаси предыдущий долг пассивным восстановлением энергии.'
    m=side.get('casino_state',{})
    if skill.skill_id=='casino_guard' and m.get('misfortune',0)<1:return 'Нужно хотя бы одно Невезение.'
    if skill.skill_id=='casino_hold' and (m.get('last_die',0)<3 or m.get('stored_used',False) or m.get('stored')):return 'Нужен новый бросок 3–6, который ещё не сохранялся.'
    return ''


def roll_action(actor,skill,rng,chance=None):
    """Only a validated, committed action draws dice; previews never mutate RNG/state."""
    if actor.get('class_id')!=CLASS_ID or skill.class_id!=CLASS_ID:return skill,None
    memory=actor.setdefault('casino_state',{})
    if not skill.damage_type:return skill,None
    from arena_casino_chance import mode as chance_mode, draw as chance_draw
    kind=chance_mode(dict(base_id=skill.skill_id,name=skill.name))
    if actor.get('_casino_roll_seed'):
        # Forecast and committed action draw the same hidden, battle-local dice.
        # Skill selection/readbacks cannot reroll the current own turn.
        rng=random.Random(str(actor['_casino_roll_seed'])+':'+str(actor.get('own_turns',0)))
    forced=not kind and memory.get('misfortune',0)>=3
    stored=memory.pop('stored',0) if not forced and not kind else 0
    draw=lambda: rng.randint(1,6) if hasattr(rng,'randint') else min(6,1+int(rng.random()*6))
    rolls=[3] if kind else [6] if forced else [stored] if stored else [draw()]
    if not kind:memory['stored_used']=bool(stored)
    if not kind and not forced and memory.pop('ace',False):rolls.append(draw())
    if not kind and not forced and max(rolls)<=2 and branch(actor)=='casino_hustler' and actor.get('own_turns',0)>=memory.get('reroll_at',0):
        rolls.append(draw());memory['reroll_at']=actor.get('own_turns',0)+3
    if kind:
        # With QTE disabled the same lottery applies; roulette defaults to red.
        chance=chance or chance_draw(kind,'red' if kind=='roulette' else 'launch',rng)
        die=chance.get('face',6 if chance['factor']>=2 or kind=='roulette' and chance['factor']>0 else 1 if not chance['factor'] else 3)
        rolls=[die]
    else:
        chance=None;die=max(rolls)
    if forced:memory['misfortune']=0
    if die<=2:
        from arena_fingers import has_trait
        gain=2 if actor['hp']<=actor['stats']['max_hp']*.35 and has_trait(actor,'casino_comeback') else 1
        memory['misfortune']=min(3,memory.get('misfortune',0)+gain)
    factor=.75 if die<=2 else 1 if die<=4 else 1.25 if die==5 else 1.9 if branch(actor)=='casino_lucky' else 1.6
    if skill.skill_id=='casino_all_in' and die<=2:factor=1
    if chance:factor=chance['factor']
    chip_spent=skill.skill_id=='casino_all_in' and memory.get('chips',0)>=3
    if chip_spent:memory['chips']-=3;factor*=1.20
    table=memory.get('table',0)>0
    if table:
        factor*=1.25 if final(actor) else 1.20 if actor['level']>=18 else 1.15
        memory['table']-=1
    seven=skill.skill_id=='casino_deposit' and memory.get('sevens',0)>=3 and memory.get('chips',0)>=7
    if seven:memory.update(sevens=0,chips=0)
    if die==6:memory['sevens']=min(3,memory.get('sevens',0)+1)
    memory['chips']=min(7,memory.get('chips',0)+(2 if die==6 else 1))
    memory['last_die']=die
    return replace(skill,power=skill.power*factor,pierce=.40 if die==6 and skill.skill_id=='casino_all_in' else skill.pierce),dict(die=die,rolls=rolls,forced=forced,table=table,seven=seven,chip_spent=chip_spent,chance=chance)


def after_action(actor,skill,hit,roll,restored=0):
    if actor.get('class_id')!=CLASS_ID or skill.class_id!=CLASS_ID:return []
    m=actor.setdefault('casino_state',{})
    if skill.skill_id=='casino_ace':m['ace']=True;return ['Туз спрятан: следующая атака выбирает лучший бросок']
    if skill.skill_id=='casino_credit':
        gain=restored;m['debt']=gain
        return [f'Кредит: +{gain} энергии, долг {gain}']
    if skill.skill_id=='casino_hold':m['stored']=m['last_die'];m['stored_used']=True;return ['Бросок сохранён в рукаве']
    if skill.skill_id=='casino_guard':m['misfortune']-=1;return ['Фортуна прикрывает: Невезение −1']
    if skill.skill_id=='casino_house':m['table']=3;return ['Игровой стол открыт на три атаки']
    if not roll:return []
    if skill.skill_id=='mastery_gambler':m['chips']=min(7,m.get('chips',0)+1)
    die=roll['die'];notes=[f'🎲 {" → ".join(map(str,roll["rolls"]))}: '+('ДЖЕКПОТ' if die==6 else 'не повезло' if die<=2 else 'ставка сыграла')]
    if roll.get('chance'):
        c=roll['chance'];outcome=str(c['sector'])+' '+dict(red='красное',black='чёрное',green='зелёное')[c['color']] if c['mode']=='roulette' else ' · '.join(map(str,c['reels'])) if c['mode']=='slots' else 'кубик '+str(c['face'])
        notes=[f'🎰 {outcome}: ×{c["factor"]} урона']
    if roll['seven']:notes.append('777: фишки и джекпоты поставлены на кон')
    if roll['chip_spent']:notes.append('Три фишки: урон +20%')
    refund=(8 if die==6 and hit else 0)+(8 if final(actor) else 5 if actor['level']<18 else 6) * int(roll['table'] and die<=2)
    if refund:
        gain=min(refund,actor['stats']['resource_max']-actor['resource']);actor['resource']+=gain
        notes.append(f'Возврат {gain} энергии')
    if die<=2 and skill.skill_id=='casino_all_in':
        loss=min(actor['hp'],max(1,round(actor['stats']['max_hp']*.08)));actor['hp']-=loss
        notes.append(f'Проигранная ставка: −{loss} HP')
    return notes


def repay_regen(side,gain):
    debt=side.get('casino_state',{}).get('debt',0)
    paid=min(debt,gain)
    if paid:side['casino_state']['debt']-=paid
    return gain-paid


def public_state(value):
    """Remove hidden dice seeds from nested public combat snapshots."""
    if isinstance(value,dict):return {k:public_state(v) for k,v in value.items() if k not in ('_casino_roll_seed','_casino_chance_seed')}
    if isinstance(value,list):return [public_state(v) for v in value]
    return value
